"""Dailymotion single videos. Player metadata researched from yt-dlp,
commit 51bab8a0116f4d8004c315706d809782607d5847 (Unlicense).
No external extractor is imported or executed.
"""
from datetime import datetime, timezone
import re
from urllib.parse import parse_qs, urlsplit
from . import Failure, diagnostic, read_json


def resolve(url, *, part=None, cookies=None, need=None):
    if part is not None:
        raise Failure('invalid_part', '--part only applies to Bilibili.')
    parsed = urlsplit(url)
    pattern = r'/([a-zA-Z0-9]+)/?' if parsed.hostname == 'dai.ly' else r'/(?:embed/)?video/([a-zA-Z0-9]+)(?:_[^/]*)?/?'
    match = re.fullmatch(pattern, parsed.path)
    if parsed.hostname == 'geo.dailymotion.com' and re.fullmatch(r'/player(?:/[a-zA-Z0-9]+)?\.html', parsed.path):
        identity = parse_qs(parsed.query).get('video', [''])[0]
        match = re.fullmatch(r'([a-zA-Z0-9]+)', identity)
    if not match or parsed.hostname not in ('dai.ly', 'dailymotion.com', 'www.dailymotion.com', 'geo.dailymotion.com'):
        raise Failure('invalid_url', 'A Dailymotion single-video URL is required.')
    identifier = match[1]
    canonical = 'https://www.dailymotion.com/video/' + identifier
    data = read_json('https://www.dailymotion.com/player/metadata/video/' + identifier + '?app=com.dailymotion.neon', cookies=cookies)
    if data.get('error'):
        raise Failure('access_denied', 'Dailymotion player denied access: ' + str(data['error'].get('title') or data['error'].get('raw_message') or 'restricted video'))
    if data.get('id') and str(data['id']) != identifier:
        raise Failure('parse_failed', 'Dailymotion returned information for a different video.')
    if not data.get('title'):
        raise Failure('parse_failed', 'Dailymotion returned no public single-video metadata.')
    if data.get('is_live') or data.get('mode') == 'live':
        raise Failure('live_unsupported', 'Dailymotion live streams are unsupported.')
    needs = set(need or ('info', 'transcript', 'video'))
    result = {'source': {'platform': 'dailymotion', 'id': identifier, 'url': canonical},
              'metadata': {'platform': 'dailymotion', 'id': identifier, 'url': canonical,
                           'title': data['title'], 'author': (data.get('owner') or {}).get('screenname'),
                           'duration': data.get('duration'), 'description': data.get('description'), 'original_language': data.get('language'),
                           'audio_expected': None, 'collected_at': datetime.now(timezone.utc).isoformat()},
              'subtitles': [], 'formats': [], 'diagnostics': []}
    if 'transcript' in needs:
        for language, track in ((data.get('subtitles') or {}).get('data') or {}).items():
            for address in track.get('urls') or []:
                result['subtitles'].append({'url': address, 'language': language, 'ext': 'vtt', 'origin': 'platform_unknown'})
        if not result['subtitles']:
            result['diagnostics'].append(diagnostic('transcript', Failure('subtitle_absent', 'Dailymotion player exposes no subtitle tracks.', 'Use local ASR.')))
    if needs.intersection(('video', 'audio', 'frames', 'media')):
        seen = set()
        headers = {'Referer': 'https://www.dailymotion.com/', 'Origin': 'https://www.dailymotion.com',
                   'Accept': '*/*', 'Accept-Language': 'en-US,en;q=0.9'}
        for quality, entries in (data.get('qualities') or {}).items():
            for entry in entries:
                address = (entry.get('url') or '').split('#')[0]
                kind = entry.get('type') or ''
                if not address or address in seen:
                    continue
                seen.add(address)
                if kind in ('application/x-mpegURL', 'application/vnd.apple.mpegurl'):
                    try:
                        if __package__ == 'scripts.platforms':
                            from ..streams import _fetch, hls_formats
                        else:
                            from streams import _fetch, hls_formats
                        final, text = _fetch(address, cookies, headers)
                        formats, _ = hls_formats(text, final, headers=headers, include_audio='frames' not in needs or bool(needs.intersection(('video', 'audio', 'transcript'))))
                        result['formats'].extend(formats)
                    except Failure as exc:
                        result['diagnostics'].append(diagnostic('media', exc))
                elif kind == 'video/mp4':
                    dimensions = re.search(r'/H264-(\d+)x(\d+)(?:-(60)/)?', address)
                    result['formats'].append({'url': address, 'ext': 'mp4', 'has_video': True, 'has_audio': None,
                        'width': int(dimensions[1]) if dimensions else None,
                        'height': int(dimensions[2]) if dimensions else int(quality) if quality.isdigit() else None,
                        'fps': 60 if dimensions and dimensions[3] else None, 'headers': headers})
        if not result['formats']:
            result['diagnostics'].append(diagnostic('media', Failure('media_unavailable', 'Dailymotion exposes no supported MP4 or HLS stream.')))
        result['metadata']['audio_expected'] = True if any(f.get('has_audio') is True for f in result['formats']) else None
    return result
