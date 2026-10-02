"""Public YouTube player response. Cipher/challenge paths remain unsupported.

Field research: yt-dlp (Unlicense); no external extractor is run or imported.
"""
from datetime import datetime, timezone
import json
import re
from urllib.parse import parse_qs, urlencode, urlsplit
from . import Failure, diagnostic, read_text


def _player(text):
    for marker in ('ytInitialPlayerResponse =', 'ytInitialPlayerResponse='):
        at = text.find(marker)
        if at >= 0:
            try:
                return json.JSONDecoder().raw_decode(text[at + len(marker):].lstrip())[0]
            except ValueError:
                pass
    raise Failure('parse_failed', 'YouTube page has no readable public player response.', 'Try a local video; this public-page path may be restricted.')


def resolve(url, *, part=None, cookies=None, need=None):
    if part is not None:
        raise Failure('invalid_part', '--part only applies to Bilibili.')
    parsed = urlsplit(url)
    identifier = parsed.path.strip('/') if parsed.hostname == 'youtu.be' else parse_qs(parsed.query).get('v', [None])[0]
    if not identifier:
        match = re.match(r'/(?:shorts|embed)/([\w-]+)', parsed.path)
        identifier = match[1] if match else None
    if not identifier or not re.fullmatch(r'[\w-]{11}', identifier):
        raise Failure('invalid_url', 'A YouTube single-video URL is required.')
    canonical = 'https://www.youtube.com/watch?v=' + identifier
    data = _player(read_text(canonical, cookies=cookies))
    details = data.get('videoDetails') or {}
    if not details.get('title'):
        raise Failure('access_denied', 'YouTube returned no public video information; its player is restricted.', 'Try your own Cookie file or provide local media.')
    micro = (data.get('microformat') or {}).get('playerMicroformatRenderer') or {}
    result = {'source': {'platform': 'youtube', 'id': identifier, 'url': canonical},
              'metadata': {'platform': 'youtube', 'id': identifier, 'url': canonical, 'title': details.get('title'),
                           'author': details.get('author'), 'description': details.get('shortDescription'),
                           'duration': float(details['lengthSeconds']) if details.get('lengthSeconds') else None,
                           'published_at': micro.get('publishDate'), 'view_count': int(details['viewCount']) if details.get('viewCount', '').isdigit() else None,
                           'thumbnail': next(iter(reversed((details.get('thumbnail') or {}).get('thumbnails') or [])), {}).get('url'),
                           'original_language': micro.get('defaultAudioLanguage'),
                           'collected_at': datetime.now(timezone.utc).isoformat()},
              'subtitles': [], 'formats': [], 'diagnostics': []}
    needs = set(need or ('info', 'transcript', 'video'))
    if 'transcript' in needs:
        tracks = ((data.get('captions') or {}).get('playerCaptionsTracklistRenderer') or {}).get('captionTracks') or []
        for track in tracks:
            if track.get('baseUrl'):
                address = track['baseUrl'] + ('&' if '?' in track['baseUrl'] else '?') + 'fmt=json3'
                result['subtitles'].append({'url': address, 'ext': 'json3', 'language': track.get('languageCode'),
                                           'origin': 'platform_auto' if track.get('kind') == 'asr' else 'platform_manual'})
        if not tracks:
            status = (data.get('playabilityStatus') or {}).get('status')
            code = 'subtitle_absent' if status == 'OK' else 'subtitle_failed'
            result['diagnostics'].append(diagnostic('transcript', Failure(code, 'The public player returned no caption tracks.', 'Use local ASR or retry with your own Cookie file.')))
    if needs.intersection(('video', 'audio', 'frames', 'media')):
        streaming = data.get('streamingData') or {}
        cipher_count = 0
        for fmt in streaming.get('formats', []) + streaming.get('adaptiveFormats', []):
            if not fmt.get('url'):
                cipher_count += bool(fmt.get('signatureCipher') or fmt.get('cipher'))
                continue
            mime = fmt.get('mimeType', '')
            video = mime.startswith('video/')
            audio = bool(fmt.get('audioQuality') or fmt.get('audioChannels')) or mime.startswith('audio/')
            extension = 'webm' if 'webm' in mime else ('mp4' if video else 'm4a')
            result['formats'].append({'url': fmt['url'], 'ext': extension, 'width': fmt.get('width'),
                                      'height': fmt.get('height'), 'has_video': video, 'has_audio': audio,
                                      'bitrate': fmt.get('bitrate')})
        if cipher_count or not result['formats']:
            result['diagnostics'].append(diagnostic('media', Failure('player_challenge_unsupported', 'YouTube requires unsupported player signature or client challenge processing for some or all streams.', 'Use a local media file; this public-page path is currently limited.')))
    result['metadata']['audio_expected'] = any(f['has_audio'] for f in result['formats']) if result['formats'] else None
    return result
