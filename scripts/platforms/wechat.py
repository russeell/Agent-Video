"""WeChat Channels single-work acquisition, using official endpoints only.

Project-owned implementation. Share/preview request schema researched in the
official finder-preview merlin.82141f20.js and lcx0cd/sph-dl's pipeline.mjs
(MIT, Copyright 2026 lcx0cd, commit 216182ad8c86b346d8ea334200b0b0086a3644f4).
No upstream downloader, parser service, browser credentials or client capture.
"""
from datetime import datetime, timezone
import json
import math
import re
import time
from urllib.parse import parse_qs, urlencode, urlsplit
import uuid
from . import Failure, diagnostic, read_json

ORIGIN = 'https://channels.weixin.qq.com'
PREVIEW = ORIGIN + '/finder-preview/pages/'
PARSE = 'https://yuanbao.tencent.com/api/weixin/get_parse_result'


def _identity(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or parsed.username or parsed.password:
        raise Failure('invalid_url', 'A WeChat Channels share or playback URL is required.')
    query = parse_qs(parsed.query, keep_blank_values=True)
    if parsed.hostname == 'weixin.qq.com':
        match = re.fullmatch(r'/sph/([A-Za-z0-9_-]+)/?', parsed.path)
        if match:
            return match[1], 'https://weixin.qq.com/sph/' + match[1], None
    if parsed.hostname == 'channels.weixin.qq.com':
        if parsed.path.rstrip('/') == '/finder-preview/pages/sph':
            ids = query.get('id', [])
            if len(ids) == 1 and re.fullmatch(r'[A-Za-z0-9_-]+', ids[0]):
                return ids[0], 'https://weixin.qq.com/sph/' + ids[0], None
        if parsed.path.rstrip('/') == '/finder-preview/pages/feed':
            tokens, ids = query.get('token', []), query.get('eid', [])
            if len(tokens) == len(ids) == 1 and tokens[0] and ids[0]:
                canonical = PREVIEW + 'feed?' + urlencode({'token': tokens[0], 'eid': ids[0]})
                return ids[0], canonical, tokens[0]
    raise Failure('invalid_url', 'Use a WeChat Channels sph share or finder-preview playback link; profiles and homepages are unsupported.')


def _feed(identifier, canonical, token=None, cookies=None):
    page = canonical if token is not None else PREVIEW + 'sph?' + urlencode({'id': identifier})
    query = urlencode({'_rid': f'{int(time.time() * 1000):x}-{uuid.uuid4().hex[:8]}', '_pageUrl': page})
    body = {'baseReq': {'generalToken': token or ''},
            'exportId' if token is not None else 'shortUri': identifier}
    result = read_json(ORIGIN + '/finder-preview/api/feed/get_feed_info?' + query,
                       headers={'Content-Type': 'application/json', 'Origin': ORIGIN, 'Referer': page},
                       cookies=cookies, data=json.dumps(body).encode())
    if not isinstance(result, dict) or result.get('errCode') != 0:
        raise Failure('parse_failed', 'WeChat did not return a successful single-work response.')
    data = result.get('data')
    if not isinstance(data, dict):
        raise Failure('parse_failed', 'WeChat work response is missing its data object.')
    detail = data.get('errMsg')
    if isinstance(detail, dict) and detail.get('type') not in (None, 0):
        raise Failure('experimental_access_limited',
                      f'WeChat playback is unavailable (preview response type {detail["type"]}).',
                      'Try a fresh playable preview link. This response does not establish why access was limited.')
    if not isinstance(data.get('feedInfo'), dict) or not data['feedInfo']:
        raise Failure('parse_failed', 'WeChat returned no identifiable work information.')
    return data


def _playback(share, cookies):
    try:
        result = read_json(PARSE, cookies=cookies, data=json.dumps({
            'type': 'video_channel_url', 'url': share, 'scene': 1}).encode(),
            headers={'Content-Type': 'application/json', 'Origin': 'https://yuanbao.tencent.com',
                     'Referer': 'https://yuanbao.tencent.com/'})
    except Failure as exc:
        if exc.code == 'access_denied':
            raise Failure('auth_required', 'Yuanbao share parsing was denied (HTTP 401/403); no playback link was obtained.',
                          'Supply a valid, explicitly exported yuanbao.tencent.com Netscape Cookie file with --cookies.') from None
        raise
    data = result.get('data') if isinstance(result, dict) else None
    if not isinstance(result, dict) or result.get('code') != 0 or not isinstance(data, dict) or not isinstance(data.get('playable_url'), str):
        raise Failure('parse_failed', 'Yuanbao returned no playable Channels link; authentication success is not established.')
    try:
        identifier, page, token = _identity(data['playable_url'])
    except (Failure, ValueError):
        raise Failure('parse_failed', 'Yuanbao returned an unrecognized Channels playback link.') from None
    if token is None:
        raise Failure('parse_failed', 'Yuanbao did not return a Channels playback token and work ID.')
    return identifier, page, token


def _number(value):
    try:
        number = float(value)
        return number if not isinstance(value, bool) and math.isfinite(number) and number >= 0 else None
    except (TypeError, ValueError):
        return None


def _formats(feed):
    formats, seen = [], set()
    if feed.get('decodeKey') not in (None, '', 0, '0'):
        return formats
    # Only official video fields, never covers, advertisements or background music.
    nodes = [feed] + [feed[key] for key in ('h264VideoInfo', 'h265VideoInfo')
                     if isinstance(feed.get(key), dict)]
    for node in nodes:
        url = node.get('videoUrl')
        if not isinstance(url, str) or url in seen:
            continue
        try:
            parsed = urlsplit(url)
            if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
                continue
        except ValueError:
            continue
        if node.get('decodeKey') not in (None, '', 0, '0'):
            continue
        seen.add(url)
        formats.append({'url': url, 'ext': 'mp4', 'has_video': True, 'has_audio': None,
                        'width': _number(node.get('width')), 'height': _number(node.get('height')),
                        'fps': _number(node.get('fps')), 'bitrate': _number(node.get('bitrate')),
                        'headers': {'Referer': ORIGIN + '/'}})
    return formats


def resolve(url, *, part=None, cookies=None, need=None):
    if part is not None:
        raise Failure('invalid_part', '--part only applies to Bilibili.')
    identifier, canonical, token = _identity(url)
    needs = set(need or ('info', 'transcript', 'video'))
    media_needed = bool(needs & {'video', 'audio', 'frames', 'media'})
    diagnostics, data, initial_error = [], None, None
    try:
        data = _feed(identifier, canonical, token, cookies)
    except Failure as exc:
        initial_error = exc
    available = _formats(data['feedInfo']) if data else []
    if token is None and media_needed and not available:
        try:
            if not cookies:
                raise Failure('auth_required', 'WeChat public share preview returned no video stream.',
                              'Provide a playable finder-preview link or an explicitly exported Yuanbao Cookie file with --cookies.')
            eid, page, playback_token = _playback(canonical, cookies)
            data = _feed(eid, page, playback_token, cookies)
            available = _formats(data['feedInfo'])
        except Failure as exc:
            diagnostics.append(diagnostic('media', exc))
    if data is None:
        raise initial_error or Failure('parse_failed', 'No Channels work information was obtained.')
    feed = data['feedInfo']
    if feed.get('mediaType') == 2 or feed.get('picInfo') and feed.get('mediaType') != 4 and not available:
        raise Failure('unsupported_content', 'This Channels work is an image post, not a video.')
    duration_ms = _number(feed.get('durationMs'))
    description = feed.get('description')
    author = data.get('authorInfo') if isinstance(data.get('authorInfo'), dict) else {}
    source = {'platform': 'wechat', 'id': identifier, 'url': canonical}
    metadata = {**source, 'title': feed.get('title') or (description[:120] if isinstance(description, str) else None),
                'description': description, 'author': author.get('nickname'),
                'duration': duration_ms / 1000 if duration_ms is not None else None,
                'published_at': _number(feed.get('createtime')), 'thumbnail': feed.get('coverUrl'),
                'view_count': None, 'like_count': _number(feed.get('likeCountFmt')),
                'comment_count': _number(feed.get('commentCountFmt')), 'audio_expected': None,
                'experimental': True, 'collected_at': datetime.now(timezone.utc).isoformat()}
    if 'transcript' in needs:
        diagnostics.append(diagnostic('transcript', Failure('subtitle_failed',
            'Channels work information exposed no caption tracks; the description is not a transcript.', 'Use configured local ASR after obtaining actual audio.')))
    if media_needed and not available and not any(d['stage'] == 'media' for d in diagnostics):
        diagnostics.append(diagnostic('media', Failure('media_unavailable',
            'WeChat returned work information without a supported video stream.', 'Try a fresh playable preview link.')))
    return {'source': source, 'metadata': metadata, 'subtitles': [],
            'formats': available if media_needed else [], 'diagnostics': diagnostics}
