"""Streamable single videos; endpoint researched from yt-dlp (Unlicense),
commit 51bab8a0116f4d8004c315706d809782607d5847. Project-owned acquisition.
"""
from datetime import datetime, timezone
import re
from urllib.parse import urlsplit
from . import Failure, diagnostic, read_json


def resolve(url, *, part=None, cookies=None, need=None):
    if part is not None:
        raise Failure('invalid_part', '--part only applies to Bilibili.')
    parsed = urlsplit(url)
    match = re.fullmatch(r'/(?:e/)?([a-zA-Z0-9]+)/?', parsed.path)
    if not match:
        match = re.fullmatch(r'/s/([a-zA-Z0-9]+)(?:/[a-zA-Z0-9]+)?/?', parsed.path)
    if parsed.scheme not in ('http', 'https') or parsed.hostname not in ('streamable.com', 'www.streamable.com') or not match:
        raise Failure('invalid_url', 'A Streamable single-video URL is required.')
    identifier = match[1]
    canonical = 'https://streamable.com/' + identifier
    data = read_json('https://ajax.streamable.com/videos/' + identifier, cookies=cookies)
    if data.get('shortcode') and data['shortcode'] != identifier:
        raise Failure('parse_failed', 'Streamable returned a different video.')
    if data.get('status') != 2:
        raise Failure('media_unavailable', 'Streamable video is unavailable or still processing.')
    needs = set(need or ('info', 'transcript', 'video'))
    thumbnail = data.get('dynamic_thumbnail_url')
    if thumbnail and thumbnail.startswith('//'):
        thumbnail = 'https:' + thumbnail
    if thumbnail and (urlsplit(thumbnail).scheme not in ('http', 'https') or urlsplit(thumbnail).query):
        thumbnail = None
    result = {'source': {'platform': 'streamable', 'id': identifier, 'url': canonical},
              'metadata': {'platform': 'streamable', 'id': identifier, 'url': canonical,
                  'title': data.get('reddit_title') or data.get('title'), 'description': data.get('description'),
                  'author': (data.get('owner') or {}).get('user_name'), 'duration': data.get('duration'),
                  'published_at': data.get('date_added'), 'view_count': data.get('plays'), 'thumbnail': thumbnail,
                  'audio_expected': None, 'original_language': None, 'collected_at': datetime.now(timezone.utc).isoformat()},
              'formats': [], 'subtitles': [], 'diagnostics': []}
    if 'transcript' in needs:
        # No caption schema has been verified; unknown nonempty data is not absence.
        present = bool(data.get('captions'))
        result['diagnostics'].append(diagnostic('transcript', Failure(
            'subtitle_unsupported' if present else 'subtitle_absent',
            'Streamable caption data is not supported.' if present else 'Streamable exposes no caption tracks.', 'Use local ASR.')))
    if needs.intersection(('video', 'audio', 'frames', 'media')):
        for name, entry in (data.get('files') or {}).items():
            address = entry.get('url')
            if not address or not name.startswith('mp4'):
                continue
            if address.startswith('//'):
                address = 'https:' + address
            if urlsplit(address).scheme not in ('http', 'https'):
                continue
            channels = entry.get('audio_channels', data.get('audio_channels'))
            result['formats'].append({'url': address, 'ext': 'mp4', 'has_video': True,
                'has_audio': channels > 0 if isinstance(channels, (int, float)) else None,
                'width': entry.get('width'), 'height': entry.get('height'), 'fps': entry.get('framerate'),
                'bitrate': entry.get('bitrate'), 'headers': {'Referer': canonical}})
        if not result['formats']:
            result['diagnostics'].append(diagnostic('media', Failure('media_unavailable', 'Streamable exposes no supported MP4 file.')))
        if any(f['has_audio'] is True for f in result['formats']):
            result['metadata']['audio_expected'] = True
    return result
