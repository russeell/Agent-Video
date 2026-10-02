"""Experimental Douyin public RENDER_DATA single-work path; no signature backend."""
from datetime import datetime, timezone
import html
import json
import re
from urllib.parse import unquote, urlsplit
from . import Failure, diagnostic, read_text, request


def _find(data, identifier):
    if isinstance(data, dict):
        if str(data.get('aweme_id') or data.get('awemeId')) == identifier and isinstance(data.get('video'), dict):
            return data
        for value in data.values():
            result = _find(value, identifier)
            if result:
                return result
    elif isinstance(data, list):
        for value in data:
            result = _find(value, identifier)
            if result:
                return result
    return None


def resolve(url, *, part=None, cookies=None, need=None):
    if part is not None:
        raise Failure('invalid_part', '--part only applies to Bilibili.')
    if urlsplit(url).hostname == 'v.douyin.com':
        with request(url, cookies=cookies) as response:
            url = response.geturl()
        if not (urlsplit(url).hostname or '').endswith('.douyin.com'):
            raise Failure('invalid_url', 'Douyin short link redirected outside Douyin.')
    match = re.search(r'/(?:video|share/video)/(\d+)', urlsplit(url).path)
    if not match:
        raise Failure('invalid_url', 'A Douyin single-video URL is required.')
    identifier = match[1]
    canonical = 'https://www.douyin.com/video/' + identifier
    page = read_text(canonical, cookies=cookies)
    match = re.search(r'<script\b[^>]*\bid=[\"\']RENDER_DATA[\"\'][^>]*>(.*?)</script>', page, re.S)
    try:
        item = _find(json.loads(unquote(html.unescape(match[1]))), identifier) if match else None
    except ValueError:
        item = None
    if not item:
        raise Failure('experimental_access_limited', 'Douyin returned no readable public single-work data; challenge processing is unsupported.', 'Provide a local media file or retry with your own Cookie file.')
    video = item['video']
    author = item.get('author') or {}
    address = video.get('play_addr') or video.get('playAddr') or {}
    urls = address.get('url_list') or address.get('urlList') or []
    formats = [{'url': value, 'ext': 'mp4', 'width': video.get('width'), 'height': video.get('height'),
                'has_video': True, 'has_audio': True, 'headers': {'Referer': canonical}}
               for value in urls if isinstance(value, str) and value.startswith('https://')]
    return {'source': {'platform': 'douyin', 'id': identifier, 'url': canonical},
            'metadata': {'platform': 'douyin', 'id': identifier, 'url': canonical, 'title': item.get('desc'),
                         'description': item.get('desc'), 'author': author.get('nickname'),
                         'duration': video.get('duration', 0) / 1000 or None, 'published_at': item.get('create_time'),
                         'experimental': True, 'audio_expected': bool(formats), 'collected_at': datetime.now(timezone.utc).isoformat()},
            'subtitles': [], 'formats': formats,
            'diagnostics': [diagnostic('transcript', Failure('subtitle_failed', 'The experimental Douyin page path cannot establish subtitle availability.', 'Use local ASR.'))] if not need or 'transcript' in need else []}
