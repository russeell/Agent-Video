"""Public Google Drive videos. Playback schema researched from yt-dlp/googledrive.py,
51bab8a0116f4d8004c315706d809782607d5847 (Unlicense, public domain).
No external extractor is imported or executed; no OAuth/private workspace access.
"""
from datetime import datetime, timezone
import re
from urllib.parse import parse_qs, urlencode, urlsplit
import xml.etree.ElementTree as ET
from . import Failure, diagnostic, read_json, read_text, media


def resolve(url, *, part=None, cookies=None, need=None):
    if part is not None:
        raise Failure('invalid_part', '--part only applies to Bilibili.')
    parsed = urlsplit(url)
    match = re.fullmatch(r'/file/d/([\w-]+)(?:/(?:view|preview|edit))?/?', parsed.path)
    query = parse_qs(parsed.query)
    identifier = match[1] if match else (query.get('id') or [None])[0] if parsed.path in ('/open', '/uc', '/download') else None
    if parsed.scheme not in ('http', 'https') or parsed.hostname not in ('drive.google.com', 'docs.google.com', 'drive.usercontent.google.com') or not identifier or not re.fullmatch(r'[\w-]{20,}', identifier):
        raise Failure('invalid_url', 'A Google Drive single public video share URL is required.')
    resourcekey = (query.get('resourcekey') or [None])[0]
    canonical = 'https://drive.google.com/file/d/' + identifier + '/view'
    if resourcekey:
        canonical += '?' + urlencode({'resourcekey': resourcekey})
    headers = {'Referer': 'https://drive.google.com/'}
    if resourcekey:
        headers['X-Goog-Drive-Resource-Keys'] = identifier + '/' + resourcekey
    # Public client key used by Drive's anonymous video player, not a user credential.
    video = read_json('https://content-workspacevideo-pa.googleapis.com/v1/drive/media/' + identifier +
                      '/playback?key=AIzaSyDVQw45DwoYh632gvsP5vPDqEKvb-Ywnb8', cookies=cookies, headers=headers)
    metadata = video.get('mediaMetadata') or {}
    if not metadata:
        raise Failure('parse_failed', 'Google Drive returned no public video information.')
    duration = metadata.get('duration')
    duration = float(duration.rstrip('s')) if isinstance(duration, str) and re.fullmatch(r'\d+(?:\.\d+)?s?', duration) else None
    needs = set(need or ('info', 'transcript', 'video'))
    result = {'source': {'platform': 'googledrive', 'id': identifier, 'url': canonical},
        'metadata': {'platform': 'googledrive', 'id': identifier, 'url': canonical, 'title': metadata.get('title'),
            'duration': duration, 'author': None, 'original_language': None, 'audio_expected': None,
            'collected_at': datetime.now(timezone.utc).isoformat()},
        'subtitles': [], 'formats': [], 'diagnostics': []}
    if 'transcript' in needs:
        base = (video.get('timedTextDetails') or {}).get('timedTextBaseUrl')
        try:
            if base:
                separator = '&' if '?' in base else '?'
                text = read_text(base + separator + urlencode({'type': 'list', 'v': identifier, 'hl': 'en-US'}), cookies=cookies, headers=headers)
                root = ET.fromstring(text)
                for track in root.iter('track'):
                    language = track.get('lang_code')
                    if language:
                        params = {'type': 'track', 'v': identifier, 'lang': language, 'fmt': 'vtt', 'hl': 'en-US'}
                        if track.get('kind'):
                            params['kind'] = track.get('kind')
                        if track.get('name'):
                            params['name'] = track.get('name')
                        result['subtitles'].append({'url': base + separator + urlencode(params), 'ext': 'vtt',
                            'language': language, 'origin': 'platform_auto' if track.get('kind') == 'asr' else 'platform_manual', 'headers': headers})
            if not result['subtitles']:
                result['diagnostics'].append(diagnostic('transcript', Failure('subtitle_absent', 'Google Drive exposes no caption tracks.', 'Use local ASR.')))
        except (Failure, ET.ParseError) as exc:
            result['diagnostics'].append(diagnostic('transcript', exc if isinstance(exc, Failure) else Failure('parse_failed', 'Google Drive caption list was not recognized.')))
    if needs.intersection(('video', 'audio', 'frames', 'media')):
        streams = (video.get('mediaStreamingData') or {}).get('formatStreamingData') or {}
        for kind in ('progressiveTranscodes', 'adaptiveTranscodes'):
            for fmt in streams.get(kind) or []:
                address, meta = fmt.get('url'), fmt.get('transcodeMetadata') or {}
                if not address or urlsplit(address).scheme not in ('http', 'https'):
                    continue
                mime = meta.get('mimeType') or ''
                if mime.split(';')[0] not in ('video/mp4', 'audio/mp4', 'video/webm', 'audio/webm'):
                    continue
                if kind == 'adaptiveTranscodes':
                    has_video = bool(meta.get('videoCodecString')) or mime.startswith('video/')
                    has_audio = bool(meta.get('audioCodecString')) or mime.startswith('audio/')
                else:
                    has_video = bool(meta.get('videoCodecString')) or mime.startswith('video/')
                    has_audio = True if meta.get('audioCodecString') or mime.startswith('audio/') else None
                result['formats'].append({'url': address, 'ext': 'webm' if 'webm' in mime else 'mp4',
                    'width': meta.get('width'), 'height': meta.get('height'), 'fps': media.frame_rate(meta.get('videoFps')),
                    'bitrate': meta.get('maxContainerBitrate'), 'has_video': has_video, 'has_audio': has_audio, 'headers': headers})
        if any(f['has_audio'] for f in result['formats']):
            result['metadata']['audio_expected'] = True
        if not result['formats']:
            result['diagnostics'].append(diagnostic('media', Failure('media_unavailable', 'Google Drive exposes no supported public transcodes.')))
    return result
