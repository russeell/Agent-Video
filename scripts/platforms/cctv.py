"""央视网 public VOD; 央视频 (yangshipin.cn) is a separate service.

Page GUID and getHttpVideoInfo schema researched from yt-dlp cctv.py,
51bab8a0116f4d8004c315706d809782607d5847 (Unlicense). Native implementation;
no external extractor runtime. Never use the API's encrypted manifest entries.
"""
from datetime import datetime, timezone
import html
import math
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from . import Failure, diagnostic, read_json, read_text


def _valid_url(url):
    try:
        p = urlsplit(url)
        if p.port not in (None, 80, 443):
            return False
    except ValueError:
        return False
    host = p.hostname or ''
    return (p.scheme in ('http', 'https') and not p.username and not p.password
            and re.fullmatch(r'(?:[a-z0-9-]+\.)*(?:cctv|cntv)\.(?:com|cn)', host)
            and (re.fullmatch(r'/\d{4}/\d{2}/\d{2}/(?:VIDE|ARTI)[A-Za-z0-9]+\.s?html', p.path)
                 or host == 'tv.cntv.cn' and re.fullmatch(r'/video/[A-Za-z0-9]+/[a-fA-F0-9]{32}', p.path)))


def _number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) and result > 0 else None
    except (TypeError, ValueError):
        return None


def resolve(url, *, part=None, cookies=None, need=None):
    if part is not None:
        raise Failure('invalid_part', '--part only applies to Bilibili.')
    if not _valid_url(url):
        raise Failure('invalid_url', 'A CCTV/ CNTV single VOD page is required; 央视频 is a separate service.')
    p = urlsplit(url)
    canonical = urlunsplit(('https', p.hostname, p.path, '', ''))
    page = read_text(canonical, cookies=cookies)
    guid = None
    for pattern in (r'var\s+guid\s*=\s*["\']([a-fA-F0-9]{32})["\']',
                    r'videoCenterId(?:["\']\s*,|:)\s*["\']([a-fA-F0-9]{32})["\']',
                    r'(?:changePlayer|load[Vv]ideo)\s*\(\s*["\']([a-fA-F0-9]{32})["\']'):
        ids = set(re.findall(pattern, page))
        if len(ids) > 1:
            raise Failure('parse_failed', 'CCTV page identifies multiple videos rather than one VOD.')
        if ids:
            guid = ids.pop().lower()
            break
    if not guid:
        raise Failure('parse_failed', 'CCTV page exposes no single VOD GUID.')
    if p.hostname == 'tv.cntv.cn' and p.path.startswith('/video/') and p.path.rsplit('/', 1)[-1].lower() != guid:
        raise Failure('parse_failed', 'CNTV page identifies a different requested video.')
    api = 'https://vdn.apps.cntv.cn/api/getHttpVideoInfo.do?' + urlencode(
        {'pid': guid, 'url': canonical, 'idl': 32, 'idlr': 32, 'modifyed': 'false'})
    data = read_json(api, cookies=cookies)
    if not isinstance(data, dict) or not data.get('title') or data.get('ack') != 'yes':
        raise Failure('media_unavailable', 'CCTV API returned no public VOD information.')
    for key in ('pid', 'videoid', 'video_id'):
        if data.get(key) and str(data[key]).lower() != guid:
            raise Failure('parse_failed', 'CCTV API identifies a different video.')
    if str(data.get('is_preview', '0')) != '0':
        raise Failure('preview_unsupported', 'CCTV exposes only a preview for this video.')
    if (str(data.get('is_protected', '0')) != '0' or str(data.get('public', '1')) != '1'
            or str(data.get('is_invalid_copyright', '0')) != '0' or str(data.get('play', '1')) != '1'):
        raise Failure('access_denied', 'CCTV marks this VOD restricted or unavailable.')
    video = data.get('video') if isinstance(data.get('video'), dict) else {}
    description = re.search(r'<meta\s+[^>]*name=["\']description["\'][^>]*content=["\']([^"\']*)', page, re.I)
    result = {'source': {'platform': 'cctv', 'id': guid, 'url': canonical},
        'metadata': {'platform': 'cctv', 'id': guid, 'url': canonical, 'title': data['title'],
                     'description': html.unescape(description[1]) if description else None,
                     'author': data.get('editer_name'), 'duration': _number(video.get('totalLength')),
                     'published_at': data.get('f_pgmtime'), 'thumbnail': data.get('image'),
                     'original_language': None, 'audio_expected': None,
                     'collected_at': datetime.now(timezone.utc).isoformat()},
        'subtitles': [], 'formats': [], 'diagnostics': []}
    needs = set(need or ('info', 'transcript', 'video'))
    if 'transcript' in needs:
        result['diagnostics'].append(diagnostic('transcript', Failure('subtitle_unavailable',
            'CCTV VOD API exposes no downloadable subtitle tracks; page descriptions are not transcripts.', 'Use local ASR.')))
    if not needs.intersection(('video', 'audio', 'frames', 'media')):
        return result
    # Chapter lists can be samples or pieces of a long programme. Only one
    # chapter explicitly covering the whole reported duration is a file candidate.
    duration = result['metadata']['duration']
    for key, entries in video.items():
        if key != 'lowChapters' and not re.fullmatch(r'chapters\d*', key):
            continue
        if not isinstance(entries, list) or len(entries) != 1 or not isinstance(entries[0], dict):
            continue
        entry = entries[0]
        length = _number(entry.get('duration'))
        address = entry.get('url') or ''
        if (duration and length and abs(length - duration) <= max(1, duration * .01)
                and urlsplit(address).scheme in ('http', 'https')):
            result['formats'].append({'url': address, 'ext': 'mp4', 'has_video': True, 'has_audio': None})
    address = data.get('hls_url')
    if isinstance(address, str) and urlsplit(address).scheme in ('http', 'https'):
        try:
            if __package__ == 'scripts.platforms':
                from ..streams import _fetch, hls_formats, _playlist
            else:
                from streams import _fetch, hls_formats, _playlist
            # This API's maxbr is a public quality cap. Request the full public
            # master, retaining all other query parameters.
            p = urlsplit(address)
            address = urlunsplit((p.scheme, p.netloc, p.path,
                urlencode([(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k != 'maxbr']), p.fragment))
            final, master = _fetch(address, cookies)
            formats, language = hls_formats(master, final, include_audio=needs != {'frames'})
            if not formats:
                parsed, _ = _playlist(master, final)
                formats = parsed if isinstance(parsed, list) else [
                    {'url': final, 'ext': 'm3u8', 'protocol': 'hls', 'has_video': True, 'has_audio': None}]
            # Reject encryption/live/features before offering a leaf for selection.
            for candidate in formats:
                if candidate['url'] != final:
                    leaf_url, leaf = _fetch(candidate['url'], cookies)
                    _playlist(leaf, leaf_url)
            result['formats'].extend(formats)
            result['metadata']['original_language'] = language
        except Failure as exc:
            result['diagnostics'].append(diagnostic('media', exc))
    if not result['formats']:
        result['diagnostics'].append(diagnostic('media', Failure('media_unavailable', 'CCTV exposes no supported full VOD stream.')))
    return result
