"""Explicit public HTTP media and a deliberately small VOD HLS subset.

Design researched in yt-dlp generic.py / downloader/hls.py (Unlicense).
Parsing and transport are implemented here; no upstream runtime dependency.
"""
from datetime import datetime, timezone
import hashlib
import http.client
import math
from html.parser import HTMLParser
from pathlib import Path
import re
import tempfile
from urllib.parse import urljoin, urlsplit

from . import Failure, download_file, media, request

_MEDIA_EXTS = {'mp4', 'mov', 'webm', 'mkv', 'm4v', 'mp3', 'm4a', 'ogg', 'wav', 'flv'}
_AUDIO_EXTS = {'mp3', 'm4a', 'ogg', 'wav'}


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


class _VideoHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.videos, self.current, self.title, self.in_title = [], None, '', False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'title':
            self.in_title = True
        elif tag == 'video':
            self.current = []
            self.videos.append(self.current)
            if attrs.get('src'):
                self.current.append(attrs['src'])
        elif tag == 'source' and self.current is not None and attrs.get('src'):
            self.current.append(attrs['src'])

    def handle_endtag(self, tag):
        if tag == 'video':
            self.current = None
        elif tag == 'title':
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data


def _direct(url, content_type=''):
    ext = Path(urlsplit(url).path).suffix.lstrip('.').lower()
    audio = content_type.startswith('audio/') or ext in _AUDIO_EXTS
    return {'url': url, 'ext': ext if ext in _MEDIA_EXTS else 'bin', 'has_video': not audio,
            'has_audio': True if audio else None, 'width': None, 'height': None}


def resolve(url, *, part=None, cookies=None, need=None):
    if part is not None:
        raise Failure('invalid_part', '--part only applies to Bilibili.')
    with request(url, cookies=cookies) as response:
        canonical = response.geturl()
        content_type = response.headers.get('Content-Type', '').split(';')[0].lower()
        prefix = response.read(512)
        ext = Path(urlsplit(canonical).path).suffix.lower()
        is_hls = prefix.lstrip().startswith(b'#EXTM3U') or ext == '.m3u8' or 'mpegurl' in content_type
        if is_hls:
            text = (prefix + response.read()).decode('utf-8-sig', errors='replace')
        elif content_type.startswith(('video/', 'audio/')) or (ext.lstrip('.') in _MEDIA_EXTS and content_type != 'text/html'):
            text = None
        elif content_type == 'application/dash+xml' or ext == '.mpd':
            raise Failure('format_unsupported', 'DASH media is not supported.')
        else:
            text = (prefix + response.read()).decode('utf-8-sig', errors='replace')
    duration, title = None, Path(urlsplit(canonical).path).name or 'HTTP media'
    if is_hls:
        parsed, duration = _playlist(text, canonical)
        formats = parsed if isinstance(parsed, list) else [{'url': canonical, 'ext': 'm3u8', 'protocol': 'hls', 'has_video': True, 'has_audio': None}]
    elif text is None:
        formats = [_direct(canonical, content_type)]
    else:
        page = _VideoHTML()
        page.feed(text)
        if len(page.videos) > 1:
            raise Failure('media_ambiguous', 'The page contains multiple video elements.', 'Provide the intended media URL directly.')
        if not page.videos or not page.videos[0]:
            raise Failure('unsupported_source', 'The page has no explicit video/source media URL.', 'Provide a direct media URL or local file; JavaScript players are unsupported.')
        title = page.title.strip() or title
        formats = []
        for address in dict.fromkeys(page.videos[0]):
            address = urljoin(canonical, address)
            if Path(urlsplit(address).path).suffix.lower() == '.m3u8':
                final_url, playlist = _fetch(address, cookies)
                parsed, item_duration = _playlist(playlist, final_url)
                formats.extend(parsed if isinstance(parsed, list) else [{'url': final_url, 'ext': 'm3u8', 'protocol': 'hls', 'has_video': True, 'has_audio': None}])
                duration = item_duration or duration
            else:
                formats.append(_direct(address))
    identifier = hashlib.sha256(canonical.encode()).hexdigest()[:16]
    source = {'platform': 'generic', 'id': identifier, 'url': url}
    metadata = {**source, 'title': title, 'duration': duration, 'author': None, 'description': None,
                'thumbnail': None, 'published_at': None, 'collected_at': datetime.now(timezone.utc).isoformat()}
    return {'source': source, 'metadata': metadata, 'formats': formats, 'subtitles': [], 'diagnostics': []}


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
