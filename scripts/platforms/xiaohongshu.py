"""Single video notes, researched in yt-dlp (Unlicense), commit
51bab8a0116f4d8004c315706d809782607d5847, extractor/xiaohongshu.py.
The page parser is project-owned; descriptions are not speech transcripts.
"""
from datetime import datetime, timezone
import json
import re
from urllib.parse import parse_qs, urlencode, urlsplit
from . import Failure, diagnostic, read_text, request


def _identifier(url, cookies=None):
    parsed = urlsplit(url)
    if parsed.hostname == 'xhslink.com' or parsed.hostname == 'www.xhslink.com':
        with request(url, cookies=cookies) as response:
            url = response.geturl()
        parsed = urlsplit(url)
    if parsed.hostname not in ('xiaohongshu.com', 'www.xiaohongshu.com'):
        raise Failure('invalid_url', 'Xiaohongshu link redirected outside the platform.')
    match = re.fullmatch(r'/(?:explore|discovery/item)/([0-9a-f]{24})/?', parsed.path)
    if not match:
        raise Failure('invalid_url', 'A Xiaohongshu single-note URL is required.')
    identifier = match[1]
    query = parse_qs(parsed.query)
    # Preserve the public share access token for acquisition and evidence reuse.
    access = {key: query[key][0] for key in ('xsec_token', 'xsec_source') if key in query}
    canonical = 'https://www.xiaohongshu.com/explore/' + identifier
    return identifier, canonical + ('?' + urlencode(access) if access else '')


def _state(page):
    match = re.search(r'window\.__INITIAL_STATE__\s*=\s*', page)
    if not match:
        raise Failure('experimental_access_limited', 'Xiaohongshu returned no embedded note data.',
                      'Provide the complete public share link or your own Cookie file.')
    # This is JSON with JS undefined values. Match quoted strings first so
    # literal text containing "undefined" is preserved; never execute script.
    tail = page[match.end():].split('</script>', 1)[0]
    tail = re.sub(r'"(?:\\.|[^"\\])*"|\bundefined\b',
                  lambda m: 'null' if m[0] == 'undefined' else m[0], tail)
    try:
        return json.JSONDecoder().raw_decode(tail)[0]
    except ValueError:
        raise Failure('parse_failed', 'Xiaohongshu returned malformed note data.') from None


def _note(page, identifier):
    notes = (_state(page).get('note') or {}).get('noteDetailMap') or {}
    item = (notes.get(identifier) or {}).get('note')
    if not item:
        raise Failure('experimental_access_limited', 'Xiaohongshu exposed no requested note in its detail map.',
                      'The note may be unavailable or access restricted; supply a complete share link or your own Cookie file.')
    if item.get('noteId') != identifier:
        raise Failure('parse_failed', 'Xiaohongshu data does not identify the requested note.')
    if item.get('type') != 'video':
        raise Failure('unsupported_content', 'Xiaohongshu image notes are unsupported; provide a video note.')
    return item


def _formats(video, canonical):
    formats, seen = [], set()
    streams = ((video.get('media') or {}).get('stream') or {})
    for group in streams.values():
        if not isinstance(group, list):
            continue
        for stream in group:
            for url in [stream.get('masterUrl'), *(stream.get('backupUrls') or [])]:
                if not isinstance(url, str) or not url.startswith(('https://', 'http://')) or url in seen:
                    continue
                seen.add(url)
                formats.append({'url': url, 'ext': 'mp4', 'width': stream.get('width'),
                                'height': stream.get('height'), 'fps': stream.get('fps'),
                                'bitrate': stream.get('avgBitrate'), 'has_video': True,
                                'has_audio': stream['audioCodec'] != 'none' if stream.get('audioCodec') else None,
                                'headers': {'Referer': canonical}})
    return formats


def resolve(url, *, part=None, cookies=None, need=None):
    if part is not None:
        raise Failure('invalid_part', '--part only applies to Bilibili.')
    identifier, canonical = _identifier(url, cookies)
    item = _note(read_text(canonical, cookies=cookies), identifier)
    video = item.get('video') or {}
    available = _formats(video, canonical)
    streams = ((video.get('media') or {}).get('stream') or {})
    durations = [s.get('duration') for group in streams.values() if isinstance(group, list)
                 for s in group if isinstance(s.get('duration'), (int, float))]
    needs = set(need or ('info', 'transcript', 'video'))
    counts = item.get('interactInfo') or {}
    result = {'source': {'platform': 'xiaohongshu', 'id': identifier, 'url': canonical},
              'metadata': {'platform': 'xiaohongshu', 'id': identifier, 'url': canonical,
                           'title': item.get('title'), 'description': item.get('desc'),
                           'author': (item.get('user') or {}).get('nickname'),
                           'duration': max(durations) / 1000 if durations else None,
                           'published_at': item.get('time'), 'experimental': True,
                           'like_count': counts.get('likedCount'), 'comment_count': counts.get('commentCount'),
                           'audio_expected': True if any(f['has_audio'] is True for f in available) else
                               False if available and all(f['has_audio'] is False for f in available) else None,
                           'collected_at': datetime.now(timezone.utc).isoformat()},
              'subtitles': [], 'formats': available if needs & {'video', 'audio', 'frames', 'media'} else [],
              'diagnostics': []}
    if 'transcript' in needs:
        result['diagnostics'].append(diagnostic('transcript', Failure('subtitle_failed',
            'The note page exposed no caption tracks; caption availability is unknown.', 'Use local ASR.')))
    if needs & {'video', 'audio', 'frames', 'media'} and not available:
        result['diagnostics'].append(diagnostic('media', Failure('experimental_access_limited',
            'Xiaohongshu exposed no downloadable video streams.', 'Provide your own Cookie file or local media.')))
    return result
