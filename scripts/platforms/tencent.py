"""Public Tencent single-video acquisition, implemented in this project.

cKey 8.1 and response fields researched in yt-dlp (Unlicense):
https://github.com/yt-dlp/yt-dlp/blob/51bab8a0116f4d8004c315706d809782607d5847/yt_dlp/extractor/tencent.py
The upstream public-domain dedication and warranty disclaimer are available at:
https://github.com/yt-dlp/yt-dlp/blob/51bab8a0116f4d8004c315706d809782607d5847/LICENSE
No upstream downloader or extractor is imported or executed.
"""
from datetime import datetime, timezone
import json
import math
from pathlib import PurePosixPath
import re
import secrets
import time
from urllib.parse import urlencode, urlsplit

from . import Failure, UA, diagnostic, read_text, media

API = 'https://h5vv6.video.qq.com/getvinfo'
HEADERS = {'User-Agent': UA, 'Referer': 'https://v.qq.com/'}


def _number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None
    except (TypeError, ValueError):
        return None


def _ckey(vid, url, guid, timestamp=None):
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError:
        raise Failure('dependency_missing', 'Tencent cKey requires the declared cryptography dependency.',
                      'Install the project dependencies using pip or uv.') from None
    timestamp = int(time.time()) if timestamp is None else int(timestamp)
    fields = [vid, str(timestamp), 'mg3c3b04ba', '3.5.57', guid, '10901',
              url[:48], UA.lower()[:48], '', 'Mozilla', 'Netscape', 'Windows x86_64', '00', '']
    payload = '|'.join(fields)
    data = f'|{sum(ord(char) for char in payload)}|{payload}'.encode('utf-8')
    data += b' ' * (-len(data) % 16)
    encryptor = Cipher(algorithms.AES(bytes.fromhex('4f6bdaa39e2f8cb07f5e722d9edef314')),
                       modes.CBC(bytes.fromhex('01504af356e619cf2e42bba68c3f70f9'))).encryptor()
    return (encryptor.update(data) + encryptor.finalize()).hex().upper()


def _api(vid, canonical, cid, quality, cookies):
    guid = secrets.token_hex(8)
    query = {'vid': vid, 'cKey': _ckey(vid, canonical, guid), 'encryptVer': '8.1',
             'spcaptiontype': '0', 'sphls': '2', 'dtype': '3', 'defn': quality,
             'spsrt': '2', 'sphttps': '1', 'otype': 'json', 'spwm': '1',
             'hevclv': '28', 'drm': '0', 'host': 'v.qq.com', 'referer': 'v.qq.com',
             'ehost': canonical, 'appVer': '3.5.57', 'platform': '10901',
             'guid': guid, 'flowid': secrets.token_hex(16)}
    if cid:
        query['cid'] = cid
    raw = read_text(API + '?' + urlencode(query), headers=HEADERS, cookies=cookies)
    match = re.fullmatch(r'\s*QZOutputJson\s*=\s*(\{.*\})\s*;?\s*', raw, re.S)
    try:
        data = json.loads(match[1] if match else raw)
        if not isinstance(data, dict):
            raise ValueError
    except (ValueError, TypeError):
        raise Failure('parse_failed', 'Tencent returned unrecognized video API data.') from None
    if str(data.get('code')) != '0.0' or data.get('s') == 'f':
        message = str(data.get('msg') or '')
        if any(text in message for text in ('所在区域', 'outside', 'your area')):
            code = 'geo_restricted'
        elif any(text in message.lower() for text in ('not pay', 'vip', '会员', '付费')):
            code = 'membership_required'
        elif any(text in message.lower() for text in ('login', '登录')):
            code = 'auth_required'
        else:
            code = 'platform_failed'
        raise Failure(code, f'Tencent video API rejected the request (code {data.get("code")}): {message}',
                      'Use a publicly accessible non-DRM video or a local media file.')
    return data


def _video(data):
    try:
        video = data['vl']['vi'][0]
        if not isinstance(video, dict):
            raise TypeError
        return video
    except (KeyError, IndexError, TypeError):
        raise Failure('parse_failed', 'Tencent video API has no single-video data.') from None


def _qualities(data):
    formats = (data.get('fl') or {}).get('fi') or []
    return [f for f in formats if isinstance(f, dict)]


def _selected(data, video):
    return next((f for f in _qualities(data) if f.get('br') is not None and f.get('br') == video.get('br')),
                _qualities(data)[0] if len(_qualities(data)) == 1 else {})


def _formats(data):
    video = _video(data)
    selected = _selected(data, video)
    drm_flags = [obj['drm'] for obj in (video, selected) if 'drm' in obj]
    if not drm_flags:
        raise Failure('format_unsupported', 'Tencent did not identify whether this format is non-DRM.')
    if any(_number(flag) != 0 for flag in drm_flags):
        raise Failure('drm_unsupported', 'Tencent returned a DRM-protected format.', 'Use a non-DRM video or local file.')
    if video.get('iflag') or video.get('pl') or (_number(selected.get('preview')) or 0) > 0:
        raise Failure('preview_only', 'Tencent returned restricted or preview playback; it cannot be delivered as the complete video.',
                      'Choose a publicly accessible complete video or provide a local file.')
    if _number(selected.get('lmt')):
        raise Failure('membership_required', 'Tencent restricts this format under the current access conditions.')
    candidates = []
    for item in (video.get('ul') or {}).get('ui') or []:
        if not isinstance(item, dict) or not isinstance(item.get('url'), str):
            continue
        base = item['url']
        if urlsplit(base).scheme not in ('http', 'https'):
            continue
        hls = item.get('hls') or {}
        if not isinstance(hls, dict):
            raise Failure('parse_failed', 'Tencent returned an unrecognized HLS resource descriptor.')
        if hls or urlsplit(base).path.lower().endswith('.m3u8'):
            address = base + str(hls.get('pt') or '')
            protocol, ext = 'hls', 'm3u8'
        else:
            if _number((video.get('cl') or {}).get('fc')):
                raise Failure('format_unsupported', 'Tencent returned multiple direct-media clips; clip key retrieval is not implemented.',
                              'Use an available non-DRM HLS format or a local file.')
            filename, key = video.get('fn'), video.get('fvkey')
            if not isinstance(filename, str) or not key:
                continue
            address = base + filename + '?' + urlencode({'vkey': key})
            protocol, ext = 'http', PurePosixPath(filename).suffix.lstrip('.').lower() or 'mp4'
        candidates.append({'url': address, 'protocol': protocol, 'ext': ext,
                           'width': _number(video.get('vw')), 'height': _number(video.get('vh')),
                           'has_video': selected.get('video') != 0, 'has_audio': selected.get('audio') != 0,
                           'fps': media.frame_rate(video.get('fps')),
                           'quality_id': selected.get('name'), 'bitrate': _number(selected.get('bandwidth')),
                           'headers': HEADERS})
    if not candidates:
        raise Failure('media_unavailable', 'Tencent returned no usable non-DRM media addresses.')
    # CDN mirrors are alternatives, not additional quality tiers.
    return candidates[:1]


def resolve(url, *, part=None, cookies=None, need=None):
    if part is not None:
        raise Failure('invalid_part', '--part only applies to Bilibili.')
    parsed = urlsplit(url)
    match = re.fullmatch(r'/x/(?:page|cover/(?P<cid>[A-Za-z0-9]+))/(?P<vid>[A-Za-z0-9]{11})\.html/?', parsed.path)
    if parsed.scheme not in ('http', 'https') or parsed.hostname not in ('v.qq.com', 'm.v.qq.com') or not match:
        raise Failure('invalid_url', 'Tencent requires a single-video /x/page/VID.html or /x/cover/CID/VID.html URL.',
                      'Select one video or episode; series pages are not supported.')
    vid, cid = match['vid'], match['cid']
    canonical = f'https://v.qq.com/x/cover/{cid}/{vid}.html' if cid else f'https://v.qq.com/x/page/{vid}.html'
    first = _api(vid, canonical, cid, 'hd', cookies)
    video = _video(first)
    metadata = {'platform': 'tencent', 'id': vid, 'url': canonical, 'title': video.get('ti'),
                'author': None, 'description': None, 'published_at': None,
                'duration': _number(video.get('td')), 'thumbnail': video.get('pic'),
                'view_count': None, 'like_count': None, 'comment_count': None,
                'collected_at': datetime.now(timezone.utc).isoformat()}
    result = {'source': {'platform': 'tencent', 'id': vid, 'url': canonical},
              'metadata': metadata, 'subtitles': [], 'formats': [], 'diagnostics': []}
    needs = set(need or ('info', 'transcript', 'video'))
    if 'transcript' in needs:
        for track in (first.get('sfl') or {}).get('fi') or []:
            if isinstance(track, dict) and track.get('url') and track.get('lang'):
                if urlsplit(track['url']).path.endswith('.m3u8'):
                    continue
                result['subtitles'].append({'url': track['url'], 'language': track['lang'].lower(),
                                            'ext': 'srt' if track.get('captionType') == 1 else 'vtt',
                                            'origin': 'platform_unknown', 'headers': HEADERS})
        if not result['subtitles']:
            result['diagnostics'].append(diagnostic('transcript', Failure(
                'subtitle_absent', 'Tencent returned no supported text subtitle tracks.', 'Use local ASR if audio is available.')))
    if needs.intersection(('video', 'audio', 'frames', 'media')):
        try:
            result['formats'].extend(_formats(first))
        except Failure as exc:
            result['diagnostics'].append(diagnostic('media', exc))
            return result
        selected_name = _selected(first, video).get('name')
        for quality in dict.fromkeys(f.get('name') for f in _qualities(first)
                                    if f.get('name') and f.get('name') not in ('ld', 'sd', 'hd', selected_name)
                                    and not _number(f.get('drm')) and not _number(f.get('lmt'))):
            try:
                response = _api(vid, canonical, cid, quality, cookies)
                more = _formats(response)
                if more[0]['quality_id'] not in {f['quality_id'] for f in result['formats']}:
                    result['formats'].extend(more)
                if more[0]['quality_id'] != quality:
                    result['diagnostics'].append(diagnostic('media', Failure(
                        'quality_unavailable', f'Tencent advertised {quality}, but returned {more[0]["quality_id"]} under current access conditions.')))
            except Failure as exc:
                result['diagnostics'].append(diagnostic('media', exc))
        metadata['quality_info'] = {
            'available_sizes': sorted({(f['width'], f['height']) for f in result['formats'] if f['width'] and f['height']}),
            'available_quality_ids': list(dict.fromkeys(f['quality_id'] for f in result['formats'])),
            'supported_qualities': [{'quality_id': f.get('name'), 'label': f.get('cname'),
                                     'drm': f.get('drm'), 'limit': f.get('lmt')} for f in _qualities(first)]}
        metadata['audio_expected'] = any(f['has_audio'] for f in result['formats'])
    return result
