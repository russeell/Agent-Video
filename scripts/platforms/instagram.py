"""Single Instagram videos; field research in yt-dlp (Unlicense), commit
51bab8a0116f4d8004c315706d809782607d5847, extractor/instagram.py.
Project-owned parser, including current Relay media and older GraphQL pages.
"""
from datetime import datetime, timezone
import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit
from . import Failure, diagnostic, read_json, read_text, request


def _pk(identifier):
    value = 0
    for char in identifier:
        value = value * 64 + 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'.index(char)
    return str(value)


def _identifier(url, cookies=None):
    parsed = urlsplit(url)
    if parsed.hostname not in ('instagram.com', 'www.instagram.com'):
        raise Failure('invalid_url', 'An Instagram single-video URL is required.')
    if parsed.path.startswith('/share/'):
        with request(url, cookies=cookies) as response:
            url = response.geturl()
        parsed = urlsplit(url)
        if parsed.hostname not in ('instagram.com', 'www.instagram.com'):
            raise Failure('invalid_url', 'Instagram share link redirected outside Instagram.')
    match = re.fullmatch(r'/(?:[^/]+/)?(?:p|tv|reel|reels)/([A-Za-z0-9_-]+)/?', parsed.path)
    if not match:
        raise Failure('invalid_url', 'An Instagram post, reel or video URL is required.')
    return match[1]


def _find(data, identifier):
    if isinstance(data, dict):
        if (data.get('code') == identifier or data.get('shortcode') == identifier
                or str(data.get('pk')) == _pk(identifier)):
            if data.get('carousel_media') or data.get('edge_sidecar_to_children'):
                raise Failure('unsupported_content', 'Instagram carousel posts are unsupported; choose a single video.')
            if 'video_versions' in data or data.get('is_video') or data.get('video_url'):
                return data
            if data.get('media_type') == 1 or data.get('is_video') is False:
                raise Failure('unsupported_content', 'This Instagram post is an image, not a video.')
        for value in data.values():
            found = _find(value, identifier)
            if found:
                return found
    elif isinstance(data, list):
        for value in data:
            found = _find(value, identifier)
            if found:
                return found
    return None


def _item(page, identifier):
    for script in re.findall(r'<script\b[^>]*>(.*?)</script>', page, re.S):
        script = script.strip()
        assignment = re.match(r'window\._sharedData\s*=\s*', script)
        if assignment:
            script = script[assignment.end():]
        if not script.startswith(('{', '[')):
            continue
        try:
            data = json.JSONDecoder().raw_decode(script)[0]
        except ValueError:
            continue
        found = _find(data, identifier)
        if found:
            return found
    raise Failure('experimental_access_limited', 'Instagram returned no readable media for the requested post.',
                  'Anonymous access may be gated; provide your own Cookie file or a local media file.')


def _formats(item, canonical):
    streams = list(item.get('video_versions') or [])
    if item.get('video_url'):
        streams.append({'url': item['video_url'], **(item.get('dimensions') or {})})
    formats, seen = [], set()
    for stream in streams:
        url = stream.get('url')
        if not isinstance(url, str) or not url.startswith('https://') or url in seen:
            continue
        seen.add(url)
        formats.append({'url': url, 'ext': 'mp4', 'width': stream.get('width') or item.get('original_width'),
                        'height': stream.get('height') or item.get('original_height'),
                        'bitrate': stream.get('bitrate'), 'has_video': True,
                        'has_audio': item.get('has_audio'), 'headers': {'Referer': canonical}})
    manifest = item.get('video_dash_manifest')
    if isinstance(manifest, str):
        try:
            root = ET.fromstring(manifest)
        except ET.ParseError:
            return formats
        def tag(element):
            return element.tag.rsplit('}', 1)[-1]
        # Instagram's static DASH exposes complete files via BaseURL and
        # SegmentBase indexes. Segmented templates and DRM need other support.
        if any(tag(e) in ('ContentProtection', 'SegmentTemplate', 'SegmentList') for e in root.iter()):
            return formats
        for adaptation in (e for e in root.iter() if tag(e) == 'AdaptationSet'):
            for rep in (e for e in adaptation if tag(e) == 'Representation'):
                address = next((e.text for e in rep if tag(e) == 'BaseURL'), None)
                mime = rep.get('mimeType') or adaptation.get('mimeType') or ''
                kind = rep.get('contentType') or adaptation.get('contentType') or mime.split('/')[0]
                if kind not in ('video', 'audio') or not address or not address.startswith('https://') or address in seen:
                    continue
                seen.add(address)
                def integer(name):
                    value = rep.get(name) or adaptation.get(name)
                    return int(value) if value and value.isdigit() else None
                formats.append({'url': address, 'ext': 'm4a' if kind == 'audio' else 'mp4',
                                'width': integer('width'), 'height': integer('height'),
                                'bitrate': integer('bandwidth'), 'has_video': kind == 'video',
                                'has_audio': kind == 'audio', 'headers': {'Referer': canonical}})
    return formats


def _duration(item):
    duration = item.get('video_duration')
    if isinstance(duration, (int, float)):
        return duration
    try:
        root = ET.fromstring(item.get('video_dash_manifest') or '')
    except ET.ParseError:
        return None
    match = re.fullmatch(r'PT(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?',
                         root.get('mediaPresentationDuration') or '')
    return sum(float(value or 0) * factor for value, factor in zip(match.groups(), (3600, 60, 1))) if match else None


def resolve(url, *, part=None, cookies=None, need=None):
    if part is not None:
        raise Failure('invalid_part', '--part only applies to Bilibili.')
    identifier = _identifier(url, cookies)
    kind = 'reel' if re.search(r'/reels?/', urlsplit(url).path) else 'p'
    canonical = 'https://www.instagram.com/' + kind + '/' + identifier + '/'
    try:
        item = _item(read_text(canonical, cookies=cookies), identifier)
    except Failure as exc:
        if exc.code != 'experimental_access_limited':
            raise
        if cookies:
            # Explicit credentials stay in the HTTP context, never an
            # anonymous browser or a user's existing browser profile.
            data = read_json('https://www.instagram.com/api/v1/media/' + _pk(identifier) + '/info/',
                             cookies=cookies, headers={'Referer': canonical, 'X-IG-App-ID': '936619743392459'})
            item = _find(data, identifier)
            if not item:
                raise Failure('parse_failed', 'Instagram media API did not identify the requested video.')
        else:
            try:
                from ..browser import browser_page
            except ImportError:
                from browser import browser_page
            def ready(page):
                try:
                    _item(page, identifier)
                    return True
                except Failure as failure:
                    if failure.code != 'experimental_access_limited':
                        raise
                    return False
            item = _item(browser_page(canonical, ready=ready), identifier)
    caption = item.get('caption') or {}
    edges = (item.get('edge_media_to_caption') or {}).get('edges') or []
    description = caption.get('text') if isinstance(caption, dict) else None
    if not description and edges:
        description = (edges[0].get('node') or {}).get('text')
    author = item.get('user') or item.get('owner') or {}
    available = _formats(item, canonical)
    needs = set(need or ('info', 'transcript', 'video'))
    result = {'source': {'platform': 'instagram', 'id': identifier, 'url': canonical},
              'metadata': {'platform': 'instagram', 'id': identifier, 'url': canonical,
                           'title': item.get('title') or ('Video by ' + author['username'] if author.get('username') else None),
                           'description': description, 'author': author.get('full_name') or author.get('username'),
                           'duration': _duration(item),
                           'published_at': item.get('taken_at') or item.get('taken_at_timestamp'),
                           'view_count': item.get('view_count') or item.get('video_view_count'),
                           'like_count': item.get('like_count'), 'comment_count': item.get('comment_count'),
                           'experimental': True, 'audio_expected': item.get('has_audio'),
                           'collected_at': datetime.now(timezone.utc).isoformat()},
              'subtitles': [], 'formats': available if needs & {'video', 'audio', 'frames', 'media'} else [],
              'diagnostics': []}
    if 'transcript' in needs:
        result['diagnostics'].append(diagnostic('transcript', Failure('subtitle_failed',
            'Instagram media data exposed no caption tracks; caption availability is unknown.', 'Use local ASR.')))
    if needs & {'video', 'audio', 'frames', 'media'} and not available:
        result['diagnostics'].append(diagnostic('media', Failure('experimental_access_limited',
            'Instagram media data exposed no directly downloadable video.', 'Provide a local media file.')))
    return result
