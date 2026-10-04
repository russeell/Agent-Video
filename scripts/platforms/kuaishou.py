"""Project-owned single-work parser. photoUrl field research: iawia002/lux
(MIT, Copyright 2018-present iawia002), commit
dd00f6d258d80b6684a0b9402d7124e5c18ef42f/extractors/kuaishou/kuaishou.go.
No upstream code or downloader is executed; identity is checked before media.
Mobile INIT_STATE field research: wujunwei928/parse-video-py (MIT,
Copyright 2024 wujunwei928), commit
5fcf87256edb5ffcdebf0e4aac2a5a41745da76e/src/parse_video_py/parser/kuaishou.py.
"""
from datetime import datetime, timezone
import json
import re
from urllib.parse import parse_qs, urlsplit
from . import Failure, diagnostic, read_text, request

MOBILE_UA = ('Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 '
             '(KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36')


def _allowed(host):
    return host in ('kuaishou.com', 'www.kuaishou.com', 'www1.kuaishou.com',
                    'www2.kuaishou.com', 'v.kuaishou.com', 'www.gifshow.com') or bool(
        re.fullmatch(r'[a-z0-9-]+\.m\.chenzhongtech\.com', host or ''))


def _identifier(url, cookies=None):
    parsed = urlsplit(url)
    if not _allowed(parsed.hostname):
        raise Failure('invalid_url', 'A Kuaishou single-video URL is required.')
    if parsed.hostname in ('v.kuaishou.com', 'www.gifshow.com') or parsed.path.startswith('/f/'):
        with request(url, cookies=cookies, headers={'User-Agent': MOBILE_UA}) as response:
            url = response.geturl()
        parsed = urlsplit(url)
    if not _allowed(parsed.hostname):
        raise Failure('invalid_url', 'Kuaishou link redirected outside the platform.')
    match = re.fullmatch(r'/(?:short-video|fw/(?:photo|long-video))/([A-Za-z0-9_-]+)/?', parsed.path)
    values = ([match[1]] if match else []) + parse_qs(parsed.query).get('photoId', [])
    identifiers = set(values)
    if len(identifiers) != 1 or not re.fullmatch(r'[A-Za-z0-9_-]+', next(iter(identifiers), '')):
        raise Failure('invalid_url', 'A Kuaishou single-video URL is required.')
    return identifiers.pop()


def _find(data, identifier):
    if isinstance(data, dict):
        if 'photo' in data and data.get('result') not in (None, 1):
            raise Failure('experimental_access_limited', 'Kuaishou mobile detail response did not return a successful work.',
                          'Provide your own Cookie file or local media.')
        share = parse_qs(data.get('share_info') or '') if isinstance(data.get('share_info'), str) else {}
        matched = str(data.get('photoId') or data.get('id')) == identifier or share.get('photoId') == [identifier]
        extra = data.get('ext_params') if isinstance(data.get('ext_params'), dict) else {}
        if matched and (data.get('photoType') in ('IMAGE', 'ATLAS') or extra.get('atlas')):
            raise Failure('unsupported_content', 'Kuaishou image posts are unsupported; provide a video work.')
        if matched and (data.get('photoUrl') or data.get('videoResource') or data.get('manifest') or data.get('mainMvUrls')):
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


def _item(page, identifier):
    # Apollo/SSR objects and script JSON contain the work's actual identity.
    chunks = re.findall(r'<script\b[^>]*>(.*?)</script>', page, re.S)
    if page.lstrip().startswith('{'):
        chunks.append(page)
    for chunk in chunks:
        assignment = re.search(r'(?:window\.)?(?:__(?:APOLLO_STATE|INITIAL_STATE|NEXT_DATA)__|INIT_STATE)\s*=\s*', chunk)
        if assignment:
            chunk = chunk[assignment.end():]
        chunk = chunk.strip()
        if not chunk.startswith(('{', '[')):
            continue
        try:
            data = json.JSONDecoder().raw_decode(chunk)[0]
        except ValueError:
            continue
        result = _find(data, identifier)
        if result:
            return result
        if isinstance(data, dict) and data.get('result') not in (None, 1):
            raise Failure('experimental_access_limited', f'Kuaishou returned result={data.get("result")} without the requested work.',
                          'Access may require verification; provide your own Cookie file or local media.')
    raise Failure('experimental_access_limited', 'Kuaishou exposed no identifiable requested work data.',
                  'Provide your own Cookie file or a local media file.')


def _formats(item, canonical):
    formats, seen = [], set()
    extra = item.get('ext_params') if isinstance(item.get('ext_params'), dict) else {}
    sound = extra.get('sound')
    actual_audio = True if isinstance(sound, (int, float)) and sound > 0 else item.get('hasAudio')
    def add(url, data):
        if not isinstance(url, str) or not url.startswith(('https://', 'http://')) or url in seen:
            return
        seen.add(url)
        bitrate = data.get('avgBitrate')
        formats.append({'url': url, 'ext': 'mp4', 'width': data.get('width'), 'height': data.get('height'),
                        'fps': data.get('frameRate'), 'bitrate': bitrate * 1000 if isinstance(bitrate, (int, float)) else data.get('bitrate'),
                        'has_video': True, 'has_audio': data.get('hasAudio', actual_audio),
                        'headers': {'Referer': canonical}})
    def walk(data):
        if isinstance(data, dict):
            add(data.get('url'), data)
            backups = data.get('backupUrl') or []
            for backup in backups if isinstance(backups, list) else [backups]:
                add(backup, data)
            for value in data.values():
                walk(value)
        elif isinstance(data, list):
            for value in data:
                walk(value)
    # Only walk video resource fields; avatars/covers are never video formats.
    for key in ('videoResource', 'manifest', 'manifestH265'):
        value = item.get(key)
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                continue
        walk(value)
    add(item.get('photoUrl'), item)
    add(item.get('photoH265Url'), item)
    for address in item.get('mainMvUrls') or []:
        if isinstance(address, dict):
            add(address.get('url'), item)
    return formats


def resolve(url, *, part=None, cookies=None, need=None):
    if part is not None:
        raise Failure('invalid_part', '--part only applies to Bilibili.')
    identifier = _identifier(url, cookies)
    canonical = 'https://www.kuaishou.com/short-video/' + identifier
    mobile = 'https://v.m.chenzhongtech.com/fw/photo/' + identifier
    item = _item(read_text(mobile, cookies=cookies, headers={
        'User-Agent': MOBILE_UA, 'Referer': 'https://v.kuaishou.com/'}), identifier)
    available = _formats(item, canonical)
    needs = set(need or ('info', 'transcript', 'video'))
    duration = item.get('duration')
    user = item.get('user') or item.get('author') or {}
    result = {'source': {'platform': 'kuaishou', 'id': identifier, 'url': canonical},
              'metadata': {'platform': 'kuaishou', 'id': identifier, 'url': canonical,
                           'title': item.get('caption'), 'description': item.get('caption'),
                           'author': user.get('name') or item.get('userName'),
                           'duration': duration / 1000 if isinstance(duration, (float, int)) else None,
                           'published_at': item['timestamp'] / 1000 if isinstance(item.get('timestamp'), (int, float)) else None,
                           'view_count': item.get('viewCount'),
                           'like_count': item.get('likeCount'), 'comment_count': item.get('commentCount'),
                           'experimental': True, 'audio_expected': next((f['has_audio'] for f in available
                                                                        if f['has_audio'] is not None), None),
                           'collected_at': datetime.now(timezone.utc).isoformat()},
              'subtitles': [], 'formats': available if needs & {'video', 'audio', 'frames', 'media'} else [],
              'diagnostics': []}
    if 'transcript' in needs:
        result['diagnostics'].append(diagnostic('transcript', Failure('subtitle_failed',
            'Kuaishou work data exposed no caption tracks; caption availability is unknown.', 'Use local ASR.')))
    if needs & {'video', 'audio', 'frames', 'media'} and not available:
        result['diagnostics'].append(diagnostic('media', Failure('experimental_access_limited',
            'Kuaishou exposed no downloadable video stream.', 'Provide your own Cookie file or local media.')))
    return result
