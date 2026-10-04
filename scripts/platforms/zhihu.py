"""Zhihu zvideo API researched from yt-dlp (Unlicense), commit
51bab8a0116f4d8004c315706d809782607d5847. No external downloader runtime.
"""
from datetime import datetime, timezone
import re
from urllib.parse import urlsplit
from . import Failure, diagnostic, read_json


def resolve(url, *, part=None, cookies=None, need=None):
    if part is not None:
        raise Failure('invalid_part', '--part only applies to Bilibili.')
    parsed = urlsplit(url)
    match = re.fullmatch(r'/zvideo/([0-9]+)/?', parsed.path)
    if parsed.scheme not in ('http', 'https') or parsed.hostname not in ('zhihu.com', 'www.zhihu.com') or not match:
        raise Failure('invalid_url', 'A Zhihu zvideo URL is required.')
    identifier = match[1]
    canonical = 'https://www.zhihu.com/zvideo/' + identifier
    headers = {'Referer': canonical}
    data = read_json('https://www.zhihu.com/api/v4/zvideos/' + identifier, headers=headers, cookies=cookies)
    if str(data.get('id')) != identifier or not data.get('title'):
        raise Failure('parse_failed', 'Zhihu returned no matching zvideo metadata.')
    video = data.get('video') or {}
    needs = set(need or ('info', 'transcript', 'video'))
    result = {'source': {'platform': 'zhihu', 'id': identifier, 'url': canonical},
              'metadata': {'platform': 'zhihu', 'id': identifier, 'url': canonical,
                  'title': data['title'], 'author': (data.get('author') or {}).get('name'),
                  'description': data.get('description'), 'duration': video.get('duration'),
                  'published_at': data.get('published_at'), 'view_count': data.get('play_count'),
                  'like_count': data.get('liked_count'), 'comment_count': data.get('comment_count'),
                  'audio_expected': None, 'original_language': None, 'collected_at': datetime.now(timezone.utc).isoformat()},
              'formats': [], 'subtitles': [], 'diagnostics': []}
    if 'transcript' in needs:
        result['diagnostics'].append(diagnostic('transcript', Failure('subtitle_absent', 'Zhihu zvideo API exposes no subtitle tracks.', 'Use local ASR.')))
    if needs.intersection(('video', 'audio', 'frames', 'media')):
        if video.get('is_trial') or video.get('is_paid'):
            result['diagnostics'].append(diagnostic('media', Failure('access_denied', 'Zhihu paid or trial media is unsupported.')))
            return result
        for entry in (video.get('playlist') or {}).values():
            address = entry.get('url') or entry.get('play_url')
            if not address or urlsplit(address).scheme not in ('http', 'https') or entry.get('format', 'mp4') != 'mp4':
                continue
            channels = entry.get('channels')
            result['formats'].append({'url': address, 'ext': 'mp4', 'has_video': True,
                'has_audio': channels > 0 if isinstance(channels, (int, float)) else None,
                'width': entry.get('width'), 'height': entry.get('height'), 'fps': entry.get('fps'),
                'bitrate': entry.get('bitrate') * 1000 if isinstance(entry.get('bitrate'), (int, float)) else None,
                'headers': headers})
        if not result['formats']:
            result['diagnostics'].append(diagnostic('media', Failure('media_unavailable', 'Zhihu exposes no supported MP4 file.')))
        if any(f['has_audio'] is True for f in result['formats']):
            result['metadata']['audio_expected'] = True
    return result
