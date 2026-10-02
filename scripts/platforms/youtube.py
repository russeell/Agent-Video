"""Public YouTube watch metadata and native player captions/media.

Client/HLS research: yt-dlp 51bab8a0116f4d8004c315706d809782607d5847
(Unlicense); no external extractor is run or imported. JS challenges remain unsupported.
Caption request research: youtube-transcript-api v1.2.4, commit
505f412a5a691cc1bac6430dd35144222c667598 (MIT).

Copyright (c) 2018 Jonas Depoix

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
from datetime import datetime, timezone
import json
import re
from urllib.parse import parse_qs, parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from . import Failure, diagnostic, read_json, read_text, media


VISIONOS_CLIENT = {
    'clientName': 'VISIONOS', 'clientVersion': '1.02',
    'deviceMake': 'Apple', 'deviceModel': 'RealityDevice17,1',
    'userAgent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 15_7_3) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Safari/605.1.15',
    'osName': 'visionOS', 'osVersion': '26.5.23O471',
    'hl': 'en', 'timeZone': 'UTC', 'utcOffsetMinutes': 0,
}


def _innertube_player(html, identifier, cookies=None):
    client = dict(VISIONOS_CLIENT)
    payload = {'context': {'client': client}, 'videoId': identifier,
               'contentCheckOk': True, 'racyCheckOk': True,
               'playbackContext': {'contentPlaybackContext': {'html5Preference': 'HTML5_PREF_WANTS'}}}
    timestamp = re.search(r'"STS":\s*(\d+)', html)
    if timestamp:
        payload['playbackContext']['contentPlaybackContext']['signatureTimestamp'] = int(timestamp[1])
    headers = {'Content-Type': 'application/json', 'Accept-Language': 'en-US',
               'Origin': 'https://www.youtube.com', 'X-YouTube-Client-Version': client['clientVersion']}
    if client.get('userAgent'):
        headers['User-Agent'] = client['userAgent']
    headers['X-YouTube-Client-Name'] = '101'
    visitor = re.search(r'"VISITOR_DATA":\s*"([^"]+)"', html)
    if visitor:
        headers['X-Goog-Visitor-Id'] = visitor[1]
    endpoint = 'https://www.youtube.com/youtubei/v1/player?prettyPrint=false'
    data = read_json(endpoint, data=json.dumps(payload).encode(), headers=headers, cookies=cookies)
    if not isinstance(data, dict):
        raise Failure('parse_failed', 'YouTube returned an invalid player response.')
    returned_id = (data.get('videoDetails') or {}).get('videoId')
    if returned_id and returned_id != identifier:
        raise Failure('parse_failed', 'YouTube player returned information for a different video.')
    status = data.get('playabilityStatus') or {}
    if status.get('status') not in (None, 'OK'):
        code = 'auth_required' if status['status'] == 'LOGIN_REQUIRED' else 'access_denied'
        raise Failure(code, 'YouTube player was not playable: ' + str(status.get('reason') or status['status']),
                      'Retry later or provide a local media file.')
    return data


def _original_language(player):
    streaming = player.get('streamingData') or {}
    languages = set()
    for fmt in streaming.get('formats', []) + streaming.get('adaptiveFormats', []):
        track = fmt.get('audioTrack') or {}
        original = track.get('isOriginal') is True or 'original' in str(track.get('displayName', '')).lower()
        if not original or track.get('isAutoDubbed'):
            continue
        language = str(track.get('id', '')).split('.')[0]
        if re.fullmatch(r'[a-z]{2,3}(?:-[A-Za-z0-9]+)*', language):
            languages.add(language)
    if languages:
        return next(iter(languages)) if len(languages) == 1 else None
    micro = (player.get('microformat') or {}).get('playerMicroformatRenderer') or {}
    return micro.get('defaultAudioLanguage')


def _caption_candidates(player):
    tracks = ((player.get('captions') or {}).get('playerCaptionsTracklistRenderer') or {}).get('captionTracks') or []
    candidates = []
    for track in tracks:
        if not track.get('baseUrl'):
            continue
        address = urlsplit(track['baseUrl'])
        query = [(k, v) for k, v in parse_qsl(address.query, keep_blank_values=True) if k != 'fmt']
        query.append(('fmt', 'json3'))
        candidates.append({'url': urlunsplit((address.scheme, address.netloc, address.path, urlencode(query), address.fragment)),
                           'ext': 'json3', 'language': track.get('languageCode'),
                           'origin': 'platform_auto' if track.get('kind') == 'asr' else 'platform_manual',
                           'headers': {'User-Agent': VISIONOS_CLIENT['userAgent'], 'Accept-Language': 'en-US'}})
    return candidates


def _player(text):
    for marker in ('ytInitialPlayerResponse =', 'ytInitialPlayerResponse='):
        at = text.find(marker)
        if at >= 0:
            try:
                return json.JSONDecoder().raw_decode(text[at + len(marker):].lstrip())[0]
            except ValueError:
                pass
    raise Failure('parse_failed', 'YouTube page has no readable public player response.', 'Try a local video; this public-page path may be restricted.')


def _native_audio_ids(formats):
    tracks = {track['id']: track for fmt in formats
              if (track := fmt.get('audioTrack') or {}).get('id')}
    if not tracks:
        return None
    original = {key for key, track in tracks.items() if not track.get('isAutoDubbed')
                and (track.get('isOriginal') is True or 'original' in str(track.get('displayName', '')).lower())}
    preferred = ({key for key in original if tracks[key].get('audioIsDefault')} or original
                 or {key for key, track in tracks.items() if track.get('audioIsDefault')
                     and not track.get('isAutoDubbed') and 'dubbed' not in str(track.get('displayName', '')).lower()})
    if not preferred and len(tracks) == 1:
        preferred = {key for key, track in tracks.items() if not track.get('isAutoDubbed')
                     and 'dubbed' not in str(track.get('displayName', '')).lower()}
    return preferred


def _hls_formats(text, url, *, include_audio=True):
    if __package__ == 'scripts.platforms':
        from ..streams import _attrs, _value
    else:
        from streams import _attrs, _value
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or lines[0] != '#EXTM3U':
        raise Failure('parse_failed', 'YouTube HLS response is not a playlist.')
    if any(line.startswith(('#EXT-X-KEY:', '#EXT-X-SESSION-KEY:'))
           and _value(_attrs(line.split(':', 1)[1]), 'METHOD') != 'NONE' for line in lines):
        raise Failure('encrypted_stream_unsupported', 'Encrypted YouTube HLS is not supported.')
    groups = {}
    for line in lines:
        if line.startswith('#EXT-X-MEDIA:'):
            attrs = _attrs(line.split(':', 1)[1])
            if _value(attrs, 'TYPE') == 'AUDIO' and _value(attrs, 'URI'):
                groups.setdefault(_value(attrs, 'GROUP-ID'), []).append(attrs)
    headers = {'User-Agent': VISIONOS_CLIENT['userAgent']}
    formats = []
    for index, line in enumerate(lines):
        if not line.startswith('#EXT-X-STREAM-INF:'):
            continue
        attrs = _attrs(line.split(':', 1)[1])
        if index + 1 >= len(lines) or lines[index + 1].startswith('#'):
            raise Failure('parse_failed', 'YouTube HLS variant has no resource address.')
        resolution = _value(attrs, 'RESOLUTION')
        if not re.fullmatch(r'\d+x\d+', resolution):
            continue
        width, height = map(int, resolution.split('x'))
        bandwidth = _value(attrs, 'BANDWIDTH', '0')
        if not bandwidth.isdigit():
            raise Failure('parse_failed', 'YouTube HLS variant has an invalid bandwidth.')
        group = _value(attrs, 'AUDIO')
        formats.append({'url': urljoin(url, lines[index + 1]), 'ext': 'm3u8', 'protocol': 'hls',
                        'width': width, 'height': height, 'fps': media.frame_rate(_value(attrs, 'FRAME-RATE')),
                        'bitrate': int(bandwidth), 'has_video': True,
                        'has_audio': False if group in groups else None,
                        'audio_group': group, 'headers': headers})
    language = None
    if include_audio and formats:
        best = max(formats, key=lambda f: (f['width'] * f['height'], f['fps'] or 0, f['bitrate']))
        renditions = groups.get(best['audio_group'], [])
        native = [a for a in renditions if 'original' in _value(a, 'NAME').lower()]
        if not native:
            native = [a for a in renditions if _value(a, 'DEFAULT') == 'YES'
                      and 'dubbed' not in _value(a, 'NAME').lower()]
        if not native and len(renditions) == 1 and 'dubbed' not in _value(renditions[0], 'NAME').lower():
            native = renditions
        if renditions and len(native) != 1:
            raise Failure('audio_ambiguous', 'YouTube HLS does not identify one original or default audio track.',
                          'Provide a local video with the intended audio track.')
        if native:
            audio = native[0]
            if 'original' in _value(audio, 'NAME').lower():
                language = _value(audio, 'LANGUAGE') or None
            formats.append({'url': urljoin(url, _value(audio, 'URI')), 'ext': 'm3u8', 'protocol': 'hls',
                            'has_video': False, 'has_audio': True, 'audio_group': best['audio_group'],
                            'language': _value(audio, 'LANGUAGE') or None, 'headers': headers})
    return formats, language


def _media_formats(player, *, cookies=None, want_video=True, want_audio=True):
    if __package__ == 'scripts.platforms':
        from ..streams import _fetch
    else:
        from streams import _fetch
    streaming = player.get('streamingData') or {}
    raw = streaming.get('formats', []) + streaming.get('adaptiveFormats', [])
    native_ids = _native_audio_ids(raw)
    formats, diagnostics = [], []
    audio_uncertain = False
    expected_audio = any(fmt.get('audioQuality') or fmt.get('audioChannels')
                         or fmt.get('mimeType', '').startswith('audio/') for fmt in raw)
    for fmt in raw:
        if not fmt.get('url'):
            continue
        mime = fmt.get('mimeType', '')
        video = mime.startswith('video/')
        audio = bool(fmt.get('audioQuality') or fmt.get('audioChannels')) or mime.startswith('audio/')
        track_id = (fmt.get('audioTrack') or {}).get('id')
        if audio and native_ids is not None and track_id and track_id not in native_ids:
            continue
        extension = 'webm' if 'webm' in mime else ('mp4' if video else 'm4a')
        formats.append({'url': fmt['url'], 'ext': extension, 'width': fmt.get('width'),
                        'height': fmt.get('height'), 'has_video': video, 'has_audio': audio,
                        'bitrate': fmt.get('bitrate'), 'fps': media.frame_rate(fmt.get('fps')),
                        'headers': {'User-Agent': VISIONOS_CLIENT['userAgent']}})
    language = _original_language(player)
    has_audio = any(f['has_audio'] for f in formats)
    if streaming.get('hlsManifestUrl') and (want_video or not has_audio):
        try:
            url, text = _fetch(streaming['hlsManifestUrl'], cookies,
                               {'User-Agent': VISIONOS_CLIENT['userAgent']})
            hls, hls_language = _hls_formats(text, url, include_audio=want_audio and not has_audio)
            formats.extend(hls)
            language = language or hls_language
            expected_audio = expected_audio or any(f.get('has_audio') is True or f.get('audio_group') for f in hls)
            if not expected_audio and any(f.get('has_audio') is None for f in hls):
                expected_audio = None
        except Failure as exc:
            if exc.code == 'audio_ambiguous':
                expected_audio = True
            elif not expected_audio and not has_audio:
                audio_uncertain = True
            diagnostics.append(diagnostic('media', exc))
    if want_audio and audio_uncertain:
        diagnostics.append(diagnostic('media', Failure('audio_unavailable', 'Audio availability could not be verified because the HLS lookup failed.',
                                                       'Retry later or provide local media with the intended audio.')))
    elif want_audio and expected_audio and not any(f.get('has_audio') for f in formats):
        diagnostics.append(diagnostic('media', Failure('audio_unavailable', 'YouTube returned no accessible original or default audio stream.',
                                                       'Retry later or provide local media with the intended audio.')))
    if not formats and not diagnostics:
        code = 'player_challenge_unsupported' if any(f.get('signatureCipher') or f.get('cipher') for f in raw) else 'media_unavailable'
        diagnostics.append(diagnostic('media', Failure(code, 'YouTube returned no supported accessible media streams.',
                                                       'Retry later or provide a local media file.')))
    return formats, language, diagnostics, expected_audio if (formats or expected_audio is True) and not audio_uncertain else None


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
    html = read_text(canonical, cookies=cookies)
    data = _player(html)
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
                           'original_language': _original_language(data),
                           'collected_at': datetime.now(timezone.utc).isoformat()},
              'subtitles': [], 'formats': [], 'diagnostics': []}
    needs = set(need or ('info', 'transcript', 'video'))
    if needs.intersection(('transcript', 'video', 'audio', 'frames', 'media')):
        try:
            playback = _innertube_player(html, identifier, cookies)
        except Failure as exc:
            playback = {}
            for stage in ('transcript', 'media'):
                if (stage == 'transcript' and 'transcript' in needs) or (stage == 'media' and needs.intersection(('video', 'audio', 'frames', 'media'))):
                    result['diagnostics'].append(diagnostic(stage, exc))
        result['metadata']['original_language'] = _original_language(data) or _original_language(playback)
        data = playback
    if 'transcript' in needs:
        tracks = ((data.get('captions') or {}).get('playerCaptionsTracklistRenderer') or {}).get('captionTracks') or []
        result['subtitles'] = _caption_candidates(data)
        if not tracks and not any(d['stage'] == 'transcript' for d in result['diagnostics']):
            status = (data.get('playabilityStatus') or {}).get('status')
            code = 'subtitle_absent' if status == 'OK' else 'subtitle_failed'
            result['diagnostics'].append(diagnostic('transcript', Failure(code, 'The public player returned no caption tracks.', 'Use local ASR or retry with your own Cookie file.')))
    if needs.intersection(('video', 'audio', 'frames', 'media')):
        formats, language, diagnostics, expected_audio = _media_formats(
            data, cookies=cookies, want_video=bool(needs.intersection(('video', 'frames', 'media'))),
            want_audio=bool(needs.intersection(('video', 'audio', 'transcript'))
                            or 'media' in needs and 'frames' not in needs))
        result['formats'] = formats
        result['metadata']['original_language'] = result['metadata']['original_language'] or language
        result['metadata']['audio_expected'] = expected_audio
        result['diagnostics'].extend(diagnostics)
    return result
