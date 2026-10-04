"""Public LinkedIn native video posts. Page schema researched from yt-dlp/linkedin.py,
51bab8a0116f4d8004c315706d809782607d5847 (Unlicense, public domain).
No external extractor or authenticated Learning/events API is used.
"""
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
import json
import re
from urllib.parse import urljoin, urlsplit
from . import Failure, diagnostic, read_text


class _Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta, self.video, self.videos, self.canonical, self.reactions = {}, None, [], None, None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta':
            self.meta[attrs.get('property') or attrs.get('name')] = attrs.get('content')
        if tag == 'link' and attrs.get('rel') == 'canonical':
            self.canonical = attrs.get('href')
        if tag == 'video' and 'data-sources' in attrs:
            self.videos.append(attrs)
            if self.video is None:
                self.video = attrs
        if attrs.get('data-num-reactions', '').isdigit():
            self.reactions = int(attrs['data-num-reactions'])


def _identity(url):
    try:
        parsed = urlsplit(url)
        if (parsed.scheme not in ('http', 'https') or parsed.hostname not in ('linkedin.com', 'www.linkedin.com')
                or parsed.username or parsed.password or parsed.port not in (None, 80, 443)):
            return None
        match = re.fullmatch(r'/posts/[^/]+-(\d+)-[\w-]{4}/?', parsed.path) or re.fullmatch(r'/(?:embed/)?feed/update/urn:li:activity:(\d+)/?', parsed.path)
        return match[1] if match else None
    except ValueError:
        return None


def _check_identity(value, canonical, identifier):
    if value and (not isinstance(value, str) or _identity(urljoin(canonical, value)) != identifier):
        raise Failure('parse_failed', 'LinkedIn page metadata belongs to another post or does not identify the requested post.')


def resolve(url, *, part=None, cookies=None, need=None):
    if part is not None:
        raise Failure('invalid_part', '--part only applies to Bilibili.')
    parsed = urlsplit(url)
    match = re.fullmatch(r'/posts/[^/]+-(\d+)-[\w-]{4}/?', parsed.path) or re.fullmatch(r'/feed/update/urn:li:activity:(\d+)/?', parsed.path)
    if parsed.scheme not in ('http', 'https') or parsed.hostname not in ('linkedin.com', 'www.linkedin.com') or not match:
        raise Failure('invalid_url', 'A LinkedIn public native video post URL is required.')
    identifier = match[1]
    canonical = 'https://www.linkedin.com' + parsed.path.rstrip('/')
    text = read_text(canonical, cookies=cookies)
    page = _Page()
    page.feed(text)
    if not page.video:
        raise Failure('media_unavailable', 'LinkedIn returned no public native video; the post may be unavailable or contain an external link.')
    for value in (page.canonical, page.meta.get('og:url')):
        _check_identity(value, canonical, identifier)
    players = set()
    for player in page.videos:
        asset = player.get('data-digitalmedia-asset-urn')
        if asset:
            key = ('asset', asset)
        else:
            try:
                sources = json.loads(player['data-sources'])
                if not isinstance(sources, list) or any(not isinstance(item, dict) for item in sources):
                    raise ValueError
                key = ('sources', tuple(sorted({item.get('src') for item in sources if isinstance(item.get('src'), str)})))
            except (ValueError, TypeError):
                raise Failure('parse_failed', 'LinkedIn native video sources were not recognized.') from None
        players.add(key)
    if len(players) > 1:
        raise Failure('media_ambiguous', 'LinkedIn page exposes multiple distinct native videos; a single-post player is required.')
    author, duration, published = None, None, None
    for script in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', text, re.S):
        try:
            value = json.loads(unescape(script))
            items = value if isinstance(value, list) else value.get('@graph', [value])
            for item in items:
                if isinstance(item, dict) and item.get('@type') in ('SocialMediaPosting', 'VideoObject'):
                    for field in ('@id', 'url', 'embedUrl'):
                        _check_identity(item.get(field), canonical, identifier)
                    author = (item.get('author') or item.get('creator') or {}).get('name')
                    published = item.get('datePublished') or item.get('uploadDate')
                    span = re.fullmatch(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?', item.get('duration') or '')
                    if span:
                        duration = sum(float(n or 0) * factor for n, factor in zip(span.groups(), (3600, 60, 1)))
        except (ValueError, AttributeError, TypeError):
            continue
    needs = set(need or ('info', 'transcript', 'video'))
    result = {'source': {'platform': 'linkedin', 'id': identifier, 'url': canonical},
        'metadata': {'platform': 'linkedin', 'id': identifier, 'url': canonical,
            'title': page.meta.get('og:title'), 'description': page.meta.get('og:description'), 'author': author,
            'duration': duration, 'published_at': published, 'like_count': page.reactions, 'original_language': None, 'audio_expected': None,
            'collected_at': datetime.now(timezone.utc).isoformat()},
        'subtitles': [], 'formats': [], 'diagnostics': []}
    headers = {'Referer': canonical}
    if 'transcript' in needs:
        address = page.video.get('data-captions-url')
        if address and urlsplit(address).scheme in ('http', 'https'):
            result['subtitles'].append({'url': address, 'ext': 'vtt', 'language': page.video.get('data-language') or '',
                'origin': 'platform_unknown', 'headers': headers})
        else:
            result['diagnostics'].append(diagnostic('transcript', Failure('subtitle_absent', 'LinkedIn native player exposes no captions.', 'Use local ASR.')))
    if needs.intersection(('video', 'audio', 'frames', 'media')):
        try:
            sources = json.loads(page.video['data-sources'])
        except (ValueError, KeyError):
            raise Failure('parse_failed', 'LinkedIn native video sources were not recognized.') from None
        for source in sources:
            if not isinstance(source, dict):
                continue
            address = source.get('src')
            if not address or urlsplit(address).scheme not in ('http', 'https') or source.get('type') != 'video/mp4':
                continue
            # The native CDN path explicitly labels height; unknown widths remain unknown.
            resolution = re.search(r'/mp4-(\d+)p-', urlsplit(address).path)
            bitrate = source.get('data-bitrate')
            result['formats'].append({'url': address, 'ext': 'mp4', 'height': int(resolution[1]) if resolution else None,
                'bitrate': float(bitrate) if isinstance(bitrate, (int, float)) else None,
                'has_video': True, 'has_audio': None, 'headers': headers})
        if not result['formats']:
            result['diagnostics'].append(diagnostic('media', Failure('media_unavailable', 'LinkedIn exposes no supported public MP4 sources.')))
    return result
