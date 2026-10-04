"""Shared non-encrypted VOD HLS transport for dedicated platform adapters.

Research: yt-dlp downloader/hls.py (Unlicense), including byte-range offsets.
This module receives explicit
platform media candidates; it does not resolve arbitrary websites or URLs.
"""
import http.client
import math
from pathlib import Path
import re
import tempfile
from urllib.parse import urljoin

if __package__:
    from .platforms import Failure, download_file, media, request, response_text
else:
    from platforms import Failure, download_file, media, request, response_text


def _attrs(text):
    return dict(re.findall(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)', text))


def _value(attrs, key, default=''):
    return attrs.get(key, default).strip('"')


def hls_formats(text, url, *, include_audio=True, headers=None):
    """Expand a platform master into media and original/default audio playlists."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or lines[0] != '#EXTM3U':
        raise Failure('parse_failed', 'HLS response is not a playlist.')
    if any(line.startswith(('#EXT-X-KEY:', '#EXT-X-SESSION-KEY:'))
           and _value(_attrs(line.split(':', 1)[1]), 'METHOD') != 'NONE' for line in lines):
        raise Failure('encrypted_stream_unsupported', 'Encrypted HLS is not supported.')
    groups = {}
    for line in lines:
        if line.startswith('#EXT-X-MEDIA:'):
            attrs = _attrs(line.split(':', 1)[1])
            if _value(attrs, 'TYPE') == 'AUDIO' and _value(attrs, 'URI'):
                groups.setdefault(_value(attrs, 'GROUP-ID'), []).append(attrs)
    headers = headers or {}
    formats = []
    for index, line in enumerate(lines):
        if not line.startswith('#EXT-X-STREAM-INF:'):
            continue
        attrs = _attrs(line.split(':', 1)[1])
        if index + 1 >= len(lines) or lines[index + 1].startswith('#'):
            raise Failure('parse_failed', 'HLS variant has no resource address.')
        resolution = _value(attrs, 'RESOLUTION')
        if not re.fullmatch(r'\d+x\d+', resolution):
            continue
        width, height = map(int, resolution.split('x'))
        bandwidth = _value(attrs, 'BANDWIDTH', '0')
        if not bandwidth.isdigit():
            raise Failure('parse_failed', 'HLS variant has an invalid bandwidth.')
        group = _value(attrs, 'AUDIO')
        formats.append({'url': urljoin(url, lines[index + 1]), 'ext': 'm3u8', 'protocol': 'hls',
                        'width': width, 'height': height, 'fps': media.frame_rate(_value(attrs, 'FRAME-RATE')),
                        'bitrate': int(bandwidth), 'has_video': True,
                        'has_audio': False if group in groups else None,
                        'audio_group': group, 'headers': headers})
    language = None
    if include_audio and formats:
        languages = set()
        for group in dict.fromkeys(f['audio_group'] for f in formats):
            renditions = groups.get(group, [])
            native = [a for a in renditions if 'original' in _value(a, 'NAME').lower()]
            if not native:
                native = [a for a in renditions if _value(a, 'DEFAULT') == 'YES'
                          and 'dubbed' not in _value(a, 'NAME').lower()]
            if not native and len(renditions) == 1 and 'dubbed' not in _value(renditions[0], 'NAME').lower():
                native = renditions
            if renditions and len(native) != 1:
                raise Failure('audio_ambiguous', 'HLS does not identify one original or default audio track.',
                              'Provide a local video with the intended audio track.')
            if native:
                audio = native[0]
                if 'original' in _value(audio, 'NAME').lower() and _value(audio, 'LANGUAGE'):
                    languages.add(_value(audio, 'LANGUAGE'))
                formats.append({'url': urljoin(url, _value(audio, 'URI')), 'ext': 'm3u8', 'protocol': 'hls',
                                'has_video': False, 'has_audio': True, 'audio_group': group,
                                'language': _value(audio, 'LANGUAGE') or None, 'headers': headers})
        if len(languages) == 1:
            language = languages.pop()
    return formats, language


def _fetch(url, cookies=None, headers=None):
    try:
        with request(url, cookies=cookies, headers=headers) as response:
            return response.geturl(), response_text(response)
    except (OSError, http.client.HTTPException):
        raise Failure('network_failed', 'HTTP response could not be completely read.', 'Retry acquisition later.') from None


def _playlist(text, url):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or lines[0] != '#EXTM3U':
        raise Failure('parse_failed', 'HLS resource does not begin with #EXTM3U.')
    for line in lines:
        if line.startswith(('#EXT-X-KEY:', '#EXT-X-SESSION-KEY:')) and _value(_attrs(line.split(':', 1)[1]), 'METHOD') != 'NONE':
            raise Failure('encrypted_stream_unsupported', 'Encrypted HLS is not supported.', 'Provide an unencrypted media file.')
        if line.startswith(('#EXT-X-DISCONTINUITY', '#EXT-X-GAP', '#EXT-X-PART', '#EXT-X-SKIP', '#EXT-X-I-FRAMES-ONLY', '#EXT-X-DEFINE')):
            raise Failure('hls_feature_unsupported', 'HLS discontinuities, gaps and low latency features are unsupported.')
    if any(line.startswith('#EXT-X-STREAM-INF:') for line in lines):
        if any(line.startswith('#EXT-X-MEDIA:') and _value(_attrs(line.split(':', 1)[1]), 'TYPE') in ('AUDIO', 'VIDEO') for line in lines):
            raise Failure('hls_feature_unsupported', 'HLS with separate rendition groups is not supported yet.', 'Use a muxed media file.')
        formats = []
        for index, line in enumerate(lines):
            if not line.startswith('#EXT-X-STREAM-INF:'):
                continue
            attrs = _attrs(line.split(':', 1)[1])
            if _value(attrs, 'AUDIO') or _value(attrs, 'VIDEO'):
                raise Failure('hls_feature_unsupported', 'HLS with separate rendition groups is not supported yet.')
            if index + 1 >= len(lines) or lines[index + 1].startswith('#'):
                raise Failure('parse_failed', 'HLS variant has no resource address.')
            resolution = _value(attrs, 'RESOLUTION')
            width, height = map(int, resolution.split('x')) if re.fullmatch(r'\d+x\d+', resolution) else (None, None)
            bandwidth = _value(attrs, 'BANDWIDTH', '0')
            if not bandwidth.isdigit():
                raise Failure('parse_failed', 'HLS variant has an invalid bandwidth.')
            formats.append({'url': urljoin(url, lines[index + 1]), 'ext': 'm3u8', 'protocol': 'hls',
                            'width': width, 'height': height, 'bitrate': int(bandwidth),
                            'fps': media.frame_rate(_value(attrs, 'FRAME-RATE')),
                            'has_video': True, 'has_audio': None})
        return formats, None
    if '#EXT-X-ENDLIST' not in lines:
        raise Failure('live_unsupported', 'HLS must be a completed VOD playlist with EXT-X-ENDLIST.')
    segments, durations, ranges, init = [], [], [], None
    pending, byte_range = None, None
    for line in lines:
        if line.startswith('#EXTINF:'):
            if pending is not None:
                raise Failure('parse_failed', 'HLS segment duration has no resource address.')
            try:
                pending = float(line.split(':', 1)[1].split(',', 1)[0])
                if not math.isfinite(pending) or pending <= 0:
                    raise ValueError
            except ValueError:
                raise Failure('parse_failed', 'HLS has an invalid segment duration.') from None
        elif line.startswith('#EXT-X-BYTERANGE:'):
            match = re.fullmatch(r'(\d+)(?:@(\d+))?', line.split(':', 1)[1])
            if byte_range is not None or not match or int(match[1]) <= 0:
                raise Failure('parse_failed', 'HLS has an invalid byte range.')
            byte_range = (int(match[1]), int(match[2]) if match[2] is not None else None)
        elif line.startswith('#EXT-X-MAP:'):
            attrs = _attrs(line.split(':', 1)[1])
            if init or segments or 'BYTERANGE' in attrs or not _value(attrs, 'URI'):
                raise Failure('hls_feature_unsupported', 'Only one full initialization segment before HLS media is supported.')
            init = urljoin(url, _value(attrs, 'URI'))
        elif not line.startswith('#'):
            if pending is None:
                raise Failure('parse_failed', 'HLS media segment lacks EXTINF duration.')
            address = urljoin(url, line)
            if byte_range is not None:
                length, start = byte_range
                if start is None:
                    if not ranges or ranges[-1] is None or segments[-1] != address:
                        raise Failure('parse_failed', 'HLS implicit byte range has no preceding range in the same resource.')
                    start = ranges[-1][1]
                ranges.append((start, start + length))
            else:
                ranges.append(None)
            segments.append(address)
            durations.append(pending)
            pending, byte_range = None, None
    if not segments or pending is not None or byte_range is not None:
        raise Failure('parse_failed', 'HLS playlist has no complete media segments.')
    size = None
    if any(ranges):
        # Completed contiguous ranges in one full TS resource need one download,
        # not a repeated download of the same blob for every EXTINF entry.
        end = 0
        for address, span in zip(segments, ranges):
            if init or address != segments[0] or span is None or span[0] != end:
                raise Failure('hls_feature_unsupported', 'HLS byte ranges must cover one complete resource from byte zero without gaps.')
            end = span[1]
        segments, size = segments[:1], end
    return {'segments': segments, 'init': init, 'size': size, 'duration': sum(durations)}, sum(durations)


def download_hls(candidate, path, *, cookies=None):
    """Fetch fragments with scoped HTTP credentials; FFmpeg sees only local bytes."""
    url, text = _fetch(candidate['url'], cookies, candidate.get('headers'))
    parsed, duration = _playlist(text, url)
    if isinstance(parsed, list):
        raise Failure('hls_feature_unsupported', 'Nested HLS master playlists are unsupported.')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=path.parent, prefix='.hls-') as directory:
        directory = Path(directory)
        joined = directory / ('joined.mp4' if parsed['init'] else 'joined.ts')
        addresses = ([parsed['init']] if parsed['init'] else []) + parsed['segments']
        with joined.open('wb') as output:
            for address in addresses:
                fragment = download_file(address, directory / 'fragment', headers=candidate.get('headers'), cookies=cookies)
                if parsed['size'] is not None and fragment.stat().st_size != parsed['size']:
                    raise Failure('download_incomplete', 'HLS resource size does not match its complete byte ranges.')
                with fragment.open('rb') as handle:
                    while chunk := handle.read(1024 * 1024):
                        output.write(chunk)
                fragment.unlink()
        temporary = directory / 'complete.mkv'
        media.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
                   '-f', 'mov' if parsed['init'] else 'mpegts', '-i', joined,
                   '-map', '0:v?', '-map', '0:a?', '-c', 'copy', temporary], timeout=600)
        actual = media.probe(temporary)
        if actual['duration'] < duration - max(.25, duration * .03):
            raise Failure('download_incomplete', 'HLS output is shorter than the playlist duration.')
        temporary.replace(path)
    return path
