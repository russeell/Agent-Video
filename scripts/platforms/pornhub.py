"""Public Pornhub single-work acquisition, without login, premium or DRM.

Flashvars, caption and media endpoint research: yt-dlp/extractor/pornhub.py,
commit 51bab8a0116f4d8004c315706d809782607d5847 (Unlicense).
Project-owned JSON parser; no JavaScript evaluation or external extractor.
"""
from datetime import datetime, timezone
import html
import json
import re
from urllib.parse import parse_qs, urlencode, urlsplit
from . import Failure, diagnostic, read_json, read_text, _opener


def _identity(url):
    parsed = urlsplit(url)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname
            or not re.fullmatch(r'(?:(?:www|[a-z]{2})\.)?pornhub\.(?:com|net|org)', parsed.hostname)):
        raise Failure('invalid_url', 'A public Pornhub single-video URL is required; premium and other hosts are unsupported.')
    if parsed.path == '/view_video.php':
        values = parse_qs(parsed.query).get('viewkey') or []
        identifier = values[0] if len(values) == 1 else None
    else:
        match = re.fullmatch(r'/embed/([a-z0-9]+)/?', parsed.path)
        identifier = match[1] if match else None
    if not identifier or not re.fullmatch(r'(?:ph[a-f0-9]+|[0-9]+)', identifier):
        raise Failure('invalid_url', 'A Pornhub viewkey or embed single-video URL is required.')
    return identifier, parsed.hostname


def _flashvars(text, identifier):
    for match in re.finditer(r'\b(?:var\s+)?flashvars_\d+\s*=\s*', text):
        try:
            data = json.JSONDecoder().raw_decode(text[match.end():])[0]
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        linked = data.get('link_url')
        if not isinstance(linked, str):
            canonical = re.search(r'<link\b[^>]*rel=["\']canonical["\'][^>]*href=["\']([^"\']+)', text, re.I)
            linked = html.unescape(canonical[1]) if canonical else ''
        try:
            returned, _ = _identity(linked)
        except Failure:
            continue
        if returned == identifier:
            return data
    raise Failure('parse_failed', 'The page exposes no readable player JSON matching the requested work.',
                  'Protected pages and JavaScript-only player assignments are unsupported.')


def _formats(definitions, *, cookies=None, headers=None, include_audio=True, opener=None):
    if __package__ == 'scripts.platforms':
        from ..streams import _fetch, hls_formats
    else:
        from streams import _fetch, hls_formats
    formats, diagnostics, seen = [], [], set()
    for entry in definitions:
        if not isinstance(entry, dict):
            continue
        address = entry.get('videoUrl')
        if not isinstance(address, str) or urlsplit(address).scheme != 'https' or address in seen:
            continue
        seen.add(address)
        if urlsplit(address).path == '/video/get_media':
            if not re.fullmatch(r'(?:(?:www|[a-z]{2})\.)?pornhub\.(?:com|net|org)', urlsplit(address).hostname or ''):
                continue
            try:
                resources = read_json(address, headers=headers, cookies=cookies, opener=opener)
                if not isinstance(resources, list):
                    raise Failure('parse_failed', 'The native MP4 endpoint returned no resource list.')
                nested, errors = _formats([e for e in resources if isinstance(e, dict)
                    and urlsplit(str(e.get('videoUrl') or '')).path != '/video/get_media'],
                    cookies=cookies, headers=headers, include_audio=include_audio, opener=opener)
                formats.extend(nested)
                diagnostics.extend(errors)
            except Failure as exc:
                diagnostics.append(diagnostic('media', exc))
        elif entry.get('format') == 'hls' or urlsplit(address).path.endswith('.m3u8'):
            try:
                final, text = _fetch(address, cookies, headers)
                variants, _ = hls_formats(text, final, include_audio=include_audio, headers=headers)
                formats.extend(variants)
            except Failure as exc:
                diagnostics.append(diagnostic('media', exc))
        elif entry.get('format') == 'mp4' or urlsplit(address).path.endswith('.mp4'):
            height = str(entry.get('quality') or '')
            dimensions = re.search(r'(\d+)[pP]_\d+[kK]', urlsplit(address).path)
            formats.append({'url': address, 'ext': 'mp4', 'has_video': True, 'has_audio': None,
                            'width': entry.get('width'), 'height': int(height) if height.isdigit() else int(dimensions[1]) if dimensions else None,
                            'headers': headers})
    return list({f['url']: f for f in formats}.values()), diagnostics


def resolve(url, *, part=None, cookies=None, need=None):
    if part is not None:
        raise Failure('invalid_part', '--part only applies to Bilibili.')
    identifier, host = _identity(url)
    canonical = 'https://' + host + '/view_video.php?' + urlencode({'viewkey': identifier})
    headers = {'Origin': 'https://' + host, 'Referer': 'https://' + host + '/'}
    # Native MP4 metadata requires the anonymous session cookies set by this
    # exact page request. A new cookie jar returns HTTP 200 with an empty list.
    opener = _opener(cookies)
    text = read_text(canonical, cookies=cookies, headers=headers, opener=opener)
    data = _flashvars(text, identifier)
    if any(str(data.get(key)).lower() in ('true', '1') for key in ('video_unavailable', 'video_unavailable_country')):
        raise Failure('access_denied', 'The native player marks this work as unavailable.')
    duration = str(data.get('video_duration') or '')
    title = re.search(r"""<meta\b[^>]*property=(["'])og:title\1[^>]*content=(["'])(.*?)\2""", text, re.I | re.S)
    result = {'source': {'platform': 'pornhub', 'id': identifier, 'url': canonical},
              'metadata': {'platform': 'pornhub', 'id': identifier, 'url': canonical,
                           'title': html.unescape(title[3]) if title else data.get('video_title'),
                           'duration': int(duration) if duration.isdigit() else None,
                           'audio_expected': None, 'experimental': True,
                           'collected_at': datetime.now(timezone.utc).isoformat()},
              'subtitles': [], 'formats': [], 'diagnostics': []}
    needs = set(need or ('info', 'transcript', 'video'))
    if 'transcript' in needs:
        address = data.get('closedCaptionsFile')
        if isinstance(address, str) and urlsplit(address).scheme == 'https':
            result['subtitles'].append({'url': address, 'ext': 'srt', 'language': '',
                                        'origin': 'platform_unknown', 'headers': headers})
        else:
            result['diagnostics'].append(diagnostic('transcript', Failure('subtitle_absent', 'The native player exposes no caption file.', 'Use local ASR.')))
    if needs.intersection(('video', 'audio', 'frames', 'media')):
        formats, errors = _formats(
            data.get('mediaDefinitions') or [], cookies=cookies, headers=headers, opener=opener,
            include_audio=bool(needs.intersection(('video', 'audio', 'transcript'))) or 'frames' not in needs)
        result['formats'] = formats
        result['diagnostics'].extend(errors)
        result['metadata']['audio_expected'] = True if any(f.get('has_audio') is True for f in result['formats']) else None
        if not result['formats']:
            result['diagnostics'].append(diagnostic('media', Failure('media_unavailable', 'The player exposes no supported public MP4 or HLS resource.', 'DRM and JavaScript decoding are unsupported.')))
    return result
