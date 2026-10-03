"""Weibo public single-post and TV acquisition with an isolated guest session.

Visitor handshake, statuses/show and playback_list research: yt-dlp's
extractor/weibo.py (Unlicense), commit 51bab8a0116f4d8004c315706d809782607d5847.
Project-owned parser; anonymous visitor cookies are scoped by shared HTTP.
"""
from datetime import datetime, timezone
import html
import json
import math
import re
from urllib.parse import parse_qs, urlencode, urlsplit
from . import Failure, _opener, diagnostic, read_text

HEADERS = {'Referer': 'https://weibo.com/'}


def _number(value, *, integer=False):
    try:
        number = float(value)
        if isinstance(value, bool) or not math.isfinite(number) or number < 0:
            return None
        return int(number) if integer else number
    except (TypeError, ValueError):
        return None


def _identity(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https'):
        raise Failure('invalid_url', 'A Weibo single-post or TV video URL is required.')
    if parsed.hostname in ('weibo.com', 'www.weibo.com'):
        match = re.fullmatch(r'/\d+/([A-Za-z0-9]+)/?', parsed.path)
        if match:
            return 'status', match[1]
        match = re.fullmatch(r'/tv/show/(\d+:(?:[0-9a-f]{32}|\d{16,}))/?', parsed.path)
        if match:
            return 'tv', match[1]
    elif parsed.hostname == 'm.weibo.cn':
        match = re.fullmatch(r'/(?:status|detail)/([A-Za-z0-9]+)/?', parsed.path)
        if match:
            return 'status', match[1]
    elif parsed.hostname == 'video.weibo.com' and parsed.path.rstrip('/') == '/show':
        values = parse_qs(parsed.query).get('fid') or []
        if len(values) == 1 and re.fullmatch(r'\d+:(?:[0-9a-f]{32}|\d{16,})', values[0]):
            return 'tv', values[0]
    raise Failure('invalid_url', 'A Weibo single-post or TV video URL is required; accounts and feeds are unsupported.')


def _jsonp(text, callback):
    match = re.search(r'\b' + re.escape(callback) + r'\s*\(\s*', text)
    if not match:
        raise Failure('parse_failed', 'Weibo visitor response has an unrecognized callback.')
    try:
        data, end = json.JSONDecoder().raw_decode(text[match.end():])
        if not text[match.end() + end:].lstrip().startswith(')') or not isinstance(data, dict):
            raise ValueError
        return data
    except ValueError:
        raise Failure('parse_failed', 'Weibo visitor response contains unrecognized JSON.') from None


def _bootstrap(cookies=None, *, opener=None):
    headers = {**HEADERS, 'Content-Type': 'application/x-www-form-urlencoded'}
    fingerprint = {'os': '1', 'browser': 'Chrome131,0,0,0', 'fonts': 'undefined',
                   'screenInfo': '1920*1080*24', 'plugins': ''}
    body = urlencode({'cb': 'gen_callback', 'fp': json.dumps(fingerprint, separators=(',', ':'))}).encode()
    visitor = _jsonp(read_text('https://passport.weibo.com/visitor/genvisitor',
                              headers=headers, cookies=cookies, data=body, opener=opener), 'gen_callback')
    data = visitor.get('data') or {}
    if visitor.get('retcode') != 20000000 or not data.get('tid'):
        raise Failure('access_denied', 'Weibo did not grant an anonymous visitor session.', 'Provide a local media file.')
    query = {'a': 'incarnate', 't': data['tid'], 'w': 3 if data.get('new_tid') else 2,
             'c': f'{data.get("confidence", 100):03d}', 'gc': '', 'cb': 'cross_domain', 'from': 'weibo'}
    result = _jsonp(read_text('https://passport.weibo.com/visitor/visitor?' + urlencode(query),
                             headers=HEADERS, cookies=cookies, opener=opener), 'cross_domain')
    if result.get('retcode') != 20000000:
        raise Failure('access_denied', 'Weibo rejected the anonymous visitor callback.', 'Provide a local media file.')


def _json(url, *, cookies=None, data=None, headers=None, opener=None):
    headers = {**HEADERS, **(headers or {})}
    text = read_text(url, headers=headers, cookies=cookies, data=data, opener=opener)
    if '<title>Sina Visitor System</title>' in text:
        _bootstrap(cookies, opener=opener)
        text = read_text(url, headers=headers, cookies=cookies, data=data, opener=opener)
        if '<title>Sina Visitor System</title>' in text:
            raise Failure('access_denied', 'Weibo still requires visitor verification after one anonymous handshake.',
                          'Try an explicitly supplied Cookie file or provide a local media file.')
    try:
        value = json.loads(text)
        if not isinstance(value, dict):
            raise ValueError
        return value
    except ValueError:
        raise Failure('parse_failed', 'Weibo returned an unreadable single-work JSON response.') from None


def _status(data, identifier):
    if not isinstance(data, dict) or not any(str(data.get(k)) == identifier for k in ('id', 'id_str', 'mid', 'mblogid')):
        raise Failure('parse_failed', 'Weibo response does not identify the requested single post.')
    return data


def _media(post, fid=None):
    page = post.get('page_info') or {}
    mixed = [m.get('data') or {} for m in (post.get('mix_media_info') or {}).get('items') or []
             if isinstance(m, dict) and m.get('type') != 'pic']
    if fid:
        options = [page, *mixed]
        matches = [m for m in options if m.get('object_id') == fid or (m.get('media_info') or {}).get('object_id') == fid]
        if not matches:
            raise Failure('parse_failed', 'The Weibo post does not identify the requested TV video.')
        selected = next((m for m in matches if m.get('media_info')), matches[0])
        return selected.get('media_info') or {}, selected.get('page_pic')
    if len(mixed) > 1:
        raise Failure('media_ambiguous', 'This Weibo post contains multiple videos.', 'Use the specific /tv/show/ video URL.')
    if mixed:
        return mixed[0].get('media_info') or {}, page.get('page_pic')
    return page.get('media_info') or {}, page.get('page_pic')


def _formats(info):
    result, seen = [], set()
    for entry in info.get('playback_list') or []:
        stream = entry.get('play_info') or {}
        address = html.unescape(stream.get('url') or '')
        if urlsplit(address).scheme not in ('https', 'http') or address in seen:
            continue
        seen.add(address)
        mime = stream.get('mime') or ''
        path = urlsplit(address).path
        protocol = 'dash' if 'dash' in mime or path.endswith('.mpd') else 'hls' if 'mpegurl' in mime.lower() or path.endswith('.m3u8') else None
        audio = stream.get('audio_codecs')
        has_audio = False if audio == 'none' else True if audio or stream.get('audio_channels') else None
        ext = 'mpd' if protocol == 'dash' else 'm3u8' if protocol == 'hls' else {'video/webm': 'webm', 'video/x-flv': 'flv'}.get(mime, 'mp4')
        result.append({'url': address, 'ext': ext,
                       'protocol': protocol, 'width': _number(stream.get('width'), integer=True),
                       'height': _number(stream.get('height'), integer=True),
                       'fps': _number(stream.get('fps')), 'bitrate': _number(stream.get('bitrate'), integer=True), 'has_video': True,
                       'has_audio': has_audio, 'headers': HEADERS})
    if result:
        return result
    for key, value in info.items():
        if not isinstance(value, str):
            continue
        address = html.unescape(value)
        if urlsplit(address).scheme not in ('http', 'https') or address in seen:
            continue
        query = parse_qs(urlsplit(address).query)
        size = (query.get('template') or [''])[0]
        if 'label' not in query or not re.fullmatch(r'\d+x\d+', size):
            continue
        seen.add(address)
        width, height = map(int, size.split('x'))
        result.append({'url': address, 'ext': 'mp4', 'width': width, 'height': height,
                       'has_video': True, 'has_audio': None, 'headers': HEADERS})
    return result


def _resolve(url, *, cookies=None, need=None, opener=None):
    kind, identifier = _identity(url)
    fid = identifier if kind == 'tv' else None
    if fid:
        body = urlencode({'data': json.dumps({'Component_Play_Playinfo': {'oid': fid}}, separators=(',', ':'))}).encode()
        component = _json('https://weibo.com/tv/api/component?' + urlencode({'page': '/tv/show/' + fid}),
                          cookies=cookies, data=body, opener=opener, headers={'Content-Type': 'application/x-www-form-urlencoded',
                                                            'Referer': 'https://weibo.com/tv/show/' + fid})
        identifier = str(((component.get('data') or {}).get('Component_Play_Playinfo') or {}).get('mid') or '')
        if not identifier.isdigit():
            raise Failure('parse_failed', 'Weibo TV did not identify the owning post.')
    post = _status(_json('https://weibo.com/ajax/statuses/show?' + urlencode({'id': identifier}), cookies=cookies, opener=opener), identifier)
    info, thumbnail = _media(post, fid)
    work_id = str(post.get('id_str') or post.get('id') or post.get('mid'))
    canonical = f'https://weibo.com/tv/show/{fid}' if fid else f'https://m.weibo.cn/detail/{work_id}'
    if thumbnail and (urlsplit(thumbnail).scheme not in ('http', 'https') or urlsplit(thumbnail).query):
        thumbnail = None
    metadata = {'platform': 'weibo', 'id': work_id, 'url': canonical,
                'title': info.get('video_title') or info.get('kol_title') or info.get('name') or post.get('text_raw'),
                'description': post.get('text_raw'), 'author': (post.get('user') or {}).get('screen_name'),
                'duration': _number(info.get('duration')), 'published_at': info.get('video_publish_time') or post.get('created_at'),
                'view_count': _number(info.get('online_users_number'), integer=True),
                'like_count': _number(post.get('attitudes_count'), integer=True),
                'comment_count': _number(post.get('comments_count'), integer=True), 'thumbnail': thumbnail, 'audio_expected': None,
                'experimental': True, 'collected_at': datetime.now(timezone.utc).isoformat()}
    result = {'source': {'platform': 'weibo', 'id': work_id, 'url': canonical},
              'metadata': metadata, 'subtitles': [], 'formats': [], 'diagnostics': []}
    needs = set(need or ('info', 'transcript', 'video'))
    if 'transcript' in needs:
        result['diagnostics'].append(diagnostic('transcript', Failure('subtitle_failed',
            'The Weibo single-work API does not establish downloadable caption availability.', 'Use local ASR.')))
    if needs.intersection(('video', 'audio', 'frames', 'media')):
        for candidate in _formats(info):
            try:
                if candidate.get('protocol') == 'dash':
                    from .reddit import _mpd
                    formats, _ = _mpd(read_text(candidate['url'], cookies=cookies, headers=HEADERS, opener=opener), candidate['url'])
                    result['formats'].extend({**f, 'headers': HEADERS} for f in formats)
                elif candidate.get('protocol') == 'hls':
                    if __package__ == 'scripts.platforms':
                        from ..streams import hls_formats
                    else:
                        from streams import hls_formats
                    formats, _ = hls_formats(read_text(candidate['url'], cookies=cookies, headers=HEADERS, opener=opener),
                                             candidate['url'], headers=HEADERS,
                                             include_audio=bool(needs.intersection(('video', 'audio', 'media'))))
                    result['formats'].extend(formats)
                else:
                    result['formats'].append(candidate)
            except Failure as exc:
                result['diagnostics'].append(diagnostic('media', exc))
        if not result['formats']:
            result['diagnostics'].append(diagnostic('media', Failure('media_unavailable', 'Weibo exposed no usable media for this post.')))
        elif any(f.get('has_audio') for f in result['formats']):
            metadata['audio_expected'] = True
    return result


def resolve(url, *, part=None, cookies=None, need=None):
    if part is not None:
        raise Failure('invalid_part', '--part only applies to Bilibili.')
    _identity(url)
    return _resolve(url, cookies=cookies, need=need, opener=_opener(cookies))
