"""Shared non-encrypted VOD HLS transport for dedicated platform adapters.

Research: yt-dlp downloader/hls.py (Unlicense). This module receives explicit
platform media candidates; it does not resolve arbitrary websites or URLs.
"""
import http.client
import math
from pathlib import Path
import re
import tempfile
from urllib.parse import urljoin

if __package__:
    from .platforms import Failure, download_file, media, request
else:
    from platforms import Failure, download_file, media, request


def _attrs(text):
    return dict(re.findall(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)', text))


def _value(attrs, key, default=''):
    return attrs.get(key, default).strip('"')


def _fetch(url, cookies=None, headers=None):
    try:
        with request(url, cookies=cookies, headers=headers) as response:
            return response.geturl(), response.read().decode('utf-8-sig', errors='replace')
    except (OSError, http.client.HTTPException):
        raise Failure('network_failed', 'HTTP response could not be completely read.', 'Retry acquisition later.') from None


def _playlist(text, url):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or lines[0] != '#EXTM3U':
        raise Failure('parse_failed', 'HLS resource does not begin with #EXTM3U.')
    for line in lines:
        if line.startswith(('#EXT-X-KEY:', '#EXT-X-SESSION-KEY:')) and _value(_attrs(line.split(':', 1)[1]), 'METHOD') != 'NONE':
            raise Failure('encrypted_stream_unsupported', 'Encrypted HLS is not supported.', 'Provide an unencrypted media file.')
        if line.startswith(('#EXT-X-BYTERANGE', '#EXT-X-DISCONTINUITY', '#EXT-X-GAP', '#EXT-X-PART', '#EXT-X-SKIP', '#EXT-X-I-FRAMES-ONLY', '#EXT-X-DEFINE')):
            raise Failure('hls_feature_unsupported', 'HLS byte ranges, discontinuities, gaps and low latency features are unsupported.')
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
    segments, durations, init = [], [], None
    pending = None
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
        elif line.startswith('#EXT-X-MAP:'):
            attrs = _attrs(line.split(':', 1)[1])
            if init or segments or 'BYTERANGE' in attrs or not _value(attrs, 'URI'):
                raise Failure('hls_feature_unsupported', 'Only one full initialization segment before HLS media is supported.')
            init = urljoin(url, _value(attrs, 'URI'))
        elif not line.startswith('#'):
            if pending is None:
                raise Failure('parse_failed', 'HLS media segment lacks EXTINF duration.')
            segments.append(urljoin(url, line))
            durations.append(pending)
            pending = None
    if not segments or pending is not None:
        raise Failure('parse_failed', 'HLS playlist has no complete media segments.')
    return {'segments': segments, 'init': init, 'duration': sum(durations)}, sum(durations)


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
