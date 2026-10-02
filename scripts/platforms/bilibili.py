"""Bilibili public single-work APIs, implemented locally.

Endpoint and DASH field research: yt-dlp's Unlicense bilibili extractor;
this implementation only uses the public single-work API responses.
Subtitle wire fields and public player URL decoding adapted from BBDownT,
commit 259a5558cee0a349a7ebb60bd31e40c88e5bc1ed.

MIT License

Copyright (c) 2020 nilaoda

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
from datetime import datetime, timezone
import http.client
import json
import re
from urllib.parse import parse_qs, unquote, urlencode, urlsplit
from . import Failure, diagnostic, read_json, request, media

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


def _full_playinfo(play, duration):
    if play.get('is_preview'):
        raise Failure('auth_required', 'Bilibili only returned a preview, not the full work.', 'Provide your own authorized Cookie file.')
    # A full-work duration in metadata does not make a preview a complete file.
    # Also reject a shorter declared playback duration before downloading;
    # shared download() verifies the actual media duration afterwards.
    lengths = [play.get('timelength')]
    dash_duration = (play.get('dash') or {}).get('duration')
    if isinstance(dash_duration, (int, float)):
        lengths.append(dash_duration * 1000)
    if duration and any(isinstance(value, (int, float)) and
                        value / 1000 < duration - max(2, duration * .03) for value in lengths):
        raise Failure('media_unavailable', 'Bilibili returned a shortened playback resource, not the full work.',
                      'Use an authorized full-work source.')
    return play


def _playinfo(bvid, cid, duration, cookies):
    query = {'bvid': bvid, 'cid': cid, 'fnval': 4048, 'fnver': 0, 'qn': 120, 'fourk': 1}
    if not cookies:
        # Public web playback can expose additional DASH qualities with this
        # standard anonymous parameter. Never accept a preview as a full work.
        try:
            play = _full_playinfo(_api('/x/player/playurl', {**query, 'try_look': 1}, cookies), duration)
            if (play.get('dash') or {}).get('video') or play.get('durl'):
                return play
        except Failure:
            pass
    return _full_playinfo(_api('/x/player/playurl', query, cookies), duration)


# Public player obfuscation constants, not credentials. Only the subtitle path
# is encoded; query signatures must be kept unchanged.
_SUBTITLE_ENCODINGS = (
    ('nP](wOFRvU.+<fjS{jn-!$D|Dz&",zT`', '=CFxYRn{.y|uVyO$uh&sikph?N.ilF/`bilibili'),
    ('Bn"q~|albg@]Go~ACgyDvKnd+)_D}^&J?', "Cu~L!xs~f^&r@'vh=q]q{eeng*sEg^kp#Jbilibili"),
)


def _subtitle_url(address):
    address = 'https:' + address if address.startswith('//') else address
    parsed = urlsplit(address)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise Failure('parse_failed', 'Bilibili returned an invalid subtitle address.')
    if parsed.hostname != 'subtitle.bilibili.com':
        return address
    encoded = parsed.path[1:]
    if re.search(r'%(?![0-9a-fA-F]{2})', encoded):
        raise Failure('parse_failed', 'Bilibili subtitle address has invalid encoding.')
    cipher = unquote(encoded)
    for prefix, key in _SUBTITLE_ENCODINGS:
        plain = ''.join(chr(ord(c) ^ ord(key[i % len(key)])) for i, c in enumerate(cipher))
        if not plain.startswith(prefix):
            continue
        path = plain[len(prefix):]
        if (not path.startswith(('/bfs/subtitle/', '/bfs/ai_subtitle/'))
                or path in ('/bfs/subtitle/', '/bfs/ai_subtitle/')
                or any(ord(c) < 32 or ord(c) == 127 or c in '?#\\' for c in path)
                or any(p in ('.', '..') for p in path.split('/'))):
            raise Failure('parse_failed', 'Bilibili decoded subtitle path is invalid.')
        return 'https://aisubtitle.hdslb.com' + path + ('?' + parsed.query if parsed.query else '')
    raise Failure('format_unsupported', 'Bilibili subtitle address uses an unknown public encoding.')


def _wire_fields(body):
    """Read only the standard wire fields used by the web subtitle reply."""
    at = 0
    fields = {}
    def varint():
        nonlocal at
        value = 0
        for shift in range(0, 70, 7):
            if at >= len(body):
                break
            byte = body[at]
            at += 1
            value |= (byte & 127) << shift
            if byte < 128:
                return value
        raise Failure('parse_failed', 'Bilibili subtitle reply contains a truncated integer.')
    while at < len(body):
        tag = varint()
        number, wire = tag >> 3, tag & 7
        if not number:
            raise Failure('parse_failed', 'Bilibili subtitle reply contains an invalid field.')
        if wire == 0:
            value = varint()
        elif wire in (1, 2, 5):
            size = varint() if wire == 2 else (8 if wire == 1 else 4)
            if size > len(body) - at:
                raise Failure('parse_failed', 'Bilibili subtitle reply contains a truncated field.')
            value = body[at:at + size]
            at += size
        else:
            raise Failure('format_unsupported', 'Bilibili subtitle reply uses an unsupported wire type.')
        fields.setdefault(number, []).append(value)
    return fields


def _web_subtitles(aid, cid, cookies):
    query = {'oid': cid, 'pid': aid, 'context_ext': '{"video_type":1}', 'type': 1,
             'cur_production_type': 0, 'preferred_language': 'ai-zh', 'playlist_switch': 0}
    try:
        with request(API + '/x/v2/subtitle/web/view?' + urlencode(query),
                     headers={**HEADERS, 'Accept': 'application/octet-stream'}, cookies=cookies) as response:
            body = response.read(1024 * 1024 + 1)
    except (OSError, http.client.HTTPException):
        raise Failure('network_failed', 'Bilibili subtitle track reply could not be completely read.', 'Retry later.') from None
    if len(body) > 1024 * 1024:
        raise Failure('parse_failed', 'Bilibili subtitle track reply is too large.')
    if body.lstrip().startswith(b'{'):
        # Some API errors use JSON despite the requested protobuf response.
        try:
            error = json.loads(body)
        except ValueError:
            raise Failure('parse_failed', 'Bilibili returned an invalid subtitle reply.') from None
        code = 'auth_required' if error.get('code') in (-101, -104) else 'subtitle_failed'
        raise Failure(code, 'Bilibili subtitle API rejected the request (code %s).' % error.get('code'))
    try:
        reply = _wire_fields(body)
        if not reply.get(1) or not isinstance(reply[1][0], bytes):
            raise Failure('parse_failed', 'Bilibili subtitle reply has no subtitle container.')
        video = _wire_fields(reply[1][0])
        candidates = []
        for encoded in video.get(3, []):
            if not isinstance(encoded, bytes):
                raise Failure('parse_failed', 'Bilibili returned an invalid subtitle track.')
            track = _wire_fields(encoded)
            language = track.get(3, [b''])[0].decode()
            address = track.get(5, [b''])[0].decode()
            if not language or not address:
                continue
            candidates.append({'url': _subtitle_url(address), 'ext': 'json',
                               'language': language.removeprefix('ai-'),
                               'origin': 'platform_auto' if language.startswith('ai-') or track.get(7, [0])[0] == 1 or track.get(9, [0])[0] else 'platform_manual',
                               'headers': HEADERS})
        return candidates
    except (AttributeError, UnicodeError, TypeError, ValueError):
        raise Failure('parse_failed', 'Bilibili returned invalid subtitle track fields.') from None


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
            result['subtitles'] = _web_subtitles(view['aid'], cid, cookies)
            if not result['subtitles']:
                result['diagnostics'].append(diagnostic('transcript', Failure(
                    'subtitle_absent', 'Bilibili returned no accessible subtitle tracks.', 'Use local ASR if needed.')))
        except Failure as exc:
            # Keep the established JSON path as one fallback for endpoint errors.
            # A successful empty new reply does not cause another query.
            try:
                player = _api('/x/player/v2', {'bvid': bvid, 'cid': cid}, cookies)
                for subtitle in (player.get('subtitle') or {}).get('subtitles', []):
                    if subtitle.get('subtitle_url'):
                        language = str(subtitle.get('lan', ''))
                        result['subtitles'].append({'url': _subtitle_url(subtitle['subtitle_url']), 'ext': 'json',
                            'language': language.removeprefix('ai-'),
                            'origin': 'platform_auto' if subtitle.get('ai_type') or language.startswith('ai-') else 'platform_manual',
                            'headers': HEADERS})
                if not result['subtitles']:
                    result['diagnostics'].append(diagnostic('transcript', exc))
                    if player.get('need_login_subtitle') and exc.code != 'auth_required':
                        result['diagnostics'].append(diagnostic('transcript', Failure(
                            'auth_required', 'Bilibili legacy subtitle response requires login.', 'Provide your own Cookie file or use local ASR.')))
            except Failure as fallback:
                result['diagnostics'].append(diagnostic('transcript', exc))
                if fallback.code != exc.code:
                    result['diagnostics'].append(diagnostic('transcript', fallback))
    if needs.intersection(('video', 'audio', 'frames', 'media')):
        try:
            play = _playinfo(bvid, cid, page.get('duration'), cookies)
            dash = play.get('dash') or {}
            for kind in ('video', 'audio'):
                for stream in dash.get(kind) or []:
                    address = stream.get('baseUrl') or stream.get('base_url')
                    if address:
                        result['formats'].append({'url': address, 'ext': 'mp4' if kind == 'video' else 'm4a',
                                                  'width': stream.get('width'), 'height': stream.get('height'),
                                                  'has_video': kind == 'video', 'has_audio': kind == 'audio',
                                                  'quality_id': stream.get('id') if kind == 'video' else None,
                                                  'fps': media.frame_rate(stream.get('frameRate') or stream.get('frame_rate')),
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
