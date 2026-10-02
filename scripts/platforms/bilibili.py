"""Bilibili public single-work APIs, implemented locally.

Endpoint and DASH field research: yt-dlp's Unlicense bilibili extractor;
this implementation only uses the public single-work API responses.
"""
from datetime import datetime, timezone
import re
from urllib.parse import parse_qs, urlencode, urlsplit
from . import Failure, diagnostic, read_json, request

API = 'https://api.bilibili.com'
HEADERS = {'Referer': 'https://www.bilibili.com/'}


def _api(path, query, cookies):
    data = read_json(API + path + '?' + urlencode(query), headers=HEADERS, cookies=cookies)
    code = data.get('code')
    if code != 0:
        if code in (-101, -104):
            raise Failure('auth_required', 'Bilibili requires authentication for this resource.', 'Provide your own Cookie file.')
        raise Failure('platform_failed', f'Bilibili API rejected the request (code {code}).', 'Retry later or check the work is publicly available.')
    if not isinstance(data.get('data'), dict):
        raise Failure('parse_failed', 'Bilibili API response has no work data.')
    return data['data']


def resolve(url, *, part=None, cookies=None, need=None):
    if urlsplit(url).hostname == 'b23.tv':
        with request(url, cookies=cookies) as response:
            url = response.geturl()
        if urlsplit(url).hostname not in ('www.bilibili.com', 'bilibili.com', 'm.bilibili.com'):
            raise Failure('invalid_url', 'The short link does not resolve to a Bilibili video.')
    match = re.search(r'/video/(BV[0-9A-Za-z]+|av\d+)', urlsplit(url).path)
    if not match:
        raise Failure('invalid_url', 'A Bilibili single-video BV or av URL is required.')
    identifier = match[1]
    query_p = parse_qs(urlsplit(url).query).get('p', [None])[0]
    try:
        linked = int(query_p) if query_p is not None else None
        chosen = int(part) if part is not None else (linked or 1)
    except (TypeError, ValueError):
        raise Failure('invalid_part', 'Bilibili part must be a positive integer.') from None
    if chosen < 1 or (part is not None and linked is not None and chosen != linked):
        raise Failure('invalid_part', 'The requested part conflicts with the URL part or is not positive.')
    view = _api('/x/web-interface/view', {'bvid': identifier} if identifier.startswith('BV') else {'aid': identifier[2:]}, cookies)
    pages = view.get('pages', [])
    page = next((p for p in pages if p.get('page') == chosen), None)
    if page is None:
        raise Failure('invalid_part', 'The requested part does not exist.')
    bvid, cid = view['bvid'], page['cid']
    canonical = f'https://www.bilibili.com/video/{bvid}?p={chosen}'
    stats = view.get('stat') or {}
    result = {'source': {'platform': 'bilibili', 'id': bvid, 'url': canonical, 'part': chosen, 'cid': cid},
              'metadata': {'platform': 'bilibili', 'id': bvid, 'url': canonical, 'title': view.get('title'),
                           'part_title': page.get('part'), 'part': chosen, 'cid': cid,
                           'declared_dimensions': page.get('dimension') or view.get('dimension'),
                           'author': (view.get('owner') or {}).get('name'), 'description': view.get('desc'),
                           'published_at': view.get('pubdate'), 'duration': page.get('duration'),
                           'thumbnail': view.get('pic'), 'view_count': stats.get('view'),
                           'like_count': stats.get('like'), 'comment_count': stats.get('reply'),
                           'parts': [{'part': p.get('page'), 'title': p.get('part'), 'duration': p.get('duration')} for p in pages],
                           'collected_at': datetime.now(timezone.utc).isoformat()},
              'subtitles': [], 'formats': [], 'diagnostics': []}
    needs = set(need or ('info', 'transcript', 'video'))
    if 'transcript' in needs:
        try:
            player = _api('/x/player/v2', {'bvid': bvid, 'cid': cid}, cookies)
            for subtitle in (player.get('subtitle') or {}).get('subtitles', []):
                address = subtitle.get('subtitle_url')
                if address:
                    result['subtitles'].append({'url': 'https:' + address if address.startswith('//') else address,
                                               'ext': 'json', 'language': subtitle.get('lan'),
                                               'origin': 'platform_auto' if subtitle.get('ai_type') or str(subtitle.get('lan', '')).startswith('ai-') else 'platform_manual',
                                               'headers': HEADERS})
                    result['subtitles'][-1]['language'] = str(subtitle.get('lan', '')).removeprefix('ai-')
            if not result['subtitles']:
                code = 'auth_required' if player.get('need_login_subtitle') else 'subtitle_absent'
                result['diagnostics'].append(diagnostic('transcript', Failure(code, 'Bilibili returned no accessible subtitle tracks.', 'Provide your own Cookie file or use local ASR.')))
        except Failure as exc:
            result['diagnostics'].append(diagnostic('transcript', Failure('subtitle_failed', str(exc), exc.next_action)))
    if needs.intersection(('video', 'audio', 'frames', 'media')):
        try:
            play = _api('/x/player/playurl', {'bvid': bvid, 'cid': cid, 'fnval': 4048, 'qn': 120, 'fourk': 1}, cookies)
            if play.get('is_preview'):
                raise Failure('auth_required', 'Bilibili only returned a preview, not the full work.', 'Provide your own authorized Cookie file.')
            dash = play.get('dash') or {}
            for kind in ('video', 'audio'):
                for stream in dash.get(kind) or []:
                    address = stream.get('baseUrl') or stream.get('base_url')
                    if address:
                        result['formats'].append({'url': address, 'ext': 'mp4' if kind == 'video' else 'm4a',
                                                  'width': stream.get('width'), 'height': stream.get('height'),
                                                  'has_video': kind == 'video', 'has_audio': kind == 'audio',
                                                  'quality_id': stream.get('id') if kind == 'video' else None,
                                                  'bitrate': stream.get('bandwidth'), 'headers': HEADERS})
            if not result['formats']:
                segments = play.get('durl') or []
                if len(segments) == 1:
                    stream = segments[0]
                    result['formats'].append({'url': stream['url'], 'ext': 'flv' if '.flv' in stream['url'] else 'mp4',
                                              'width': None, 'height': None, 'has_video': True, 'has_audio': True,
                                              'headers': HEADERS})
                elif segments:
                    raise Failure('format_unsupported', 'Bilibili returned a multi-file segmented resource; this path is not implemented.')
                else:
                    raise Failure('media_unavailable', 'Bilibili returned no usable media streams.')
            available = {f['quality_id'] for f in result['formats'] if f.get('has_video') and f.get('quality_id') is not None}
            supported = [{'quality_id': f.get('quality'), 'label': f.get('new_description') or f.get('display_desc'),
                          **{k: f[k] for k in ('need_login', 'need_vip') if k in f}}
                         for f in play.get('support_formats', [])]
            result['metadata']['quality_info'] = {
                'available_sizes': sorted({(f['width'], f['height']) for f in result['formats']
                                           if f.get('has_video') and f.get('width') and f.get('height')}),
                'available_quality_ids': sorted(available), 'supported_qualities': supported}
            missing = [f for f in supported if f['quality_id'] not in available]
            if available and missing:
                names = ', '.join(str(f['label'] or f['quality_id']) for f in missing)
                sizes = ', '.join(f'{w}×{h}' for w, h in result['metadata']['quality_info']['available_sizes']) or 'unknown dimensions'
                result['diagnostics'].append(diagnostic('media', Failure(
                    'quality_unavailable', f'Bilibili advertises {names}, but returned no streams for these qualities under current access conditions. Available video sizes: {sizes}; quality IDs: {sorted(available)}. Advertised qualities are not accessible formats.',
                    'Use the returned quality or provide your own authorized Cookie file to check availability; higher quality is not guaranteed.')))
        except Failure as exc:
            result['diagnostics'].append(diagnostic('media', exc))
    result['metadata']['audio_expected'] = any(f['has_audio'] for f in result['formats']) if result['formats'] else None
    return result
