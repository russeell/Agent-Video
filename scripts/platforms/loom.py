"""Public Loom shares; endpoint schema researched from yt-dlp/loom.py,
51bab8a0116f4d8004c315706d809782607d5847 (Unlicense, public domain).
No external extractor is imported or executed.
"""
from datetime import datetime, timezone
import json
import re
import uuid
from urllib.parse import urlsplit
from . import Failure, diagnostic, read_json


def _graphql(operation, identifier, fields, *, cookies=None):
    query = 'query ' + operation + '($videoId: ID!) { ' + fields + ' }'
    response = read_json('https://www.loom.com/graphql', cookies=cookies,
        headers={'Content-Type': 'application/json', 'Origin': 'https://www.loom.com',
                 'apollographql-client-name': 'web', 'apollographql-client-version': '45a5bd4',
                 'x-loom-request-source': 'loom_web_45a5bd4', 'graphql-operation-name': operation},
        data=json.dumps({'operationName': operation, 'variables': {'videoId': identifier}, 'query': query}).encode())
    if response.get('errors'):
        raise Failure('parse_failed', 'Loom GraphQL did not return the requested public video data.')
    return response.get('data') or {}


def resolve(url, *, part=None, cookies=None, need=None):
    if part is not None:
        raise Failure('invalid_part', '--part only applies to Bilibili.')
    parsed = urlsplit(url)
    match = re.fullmatch(r'/(?:share|embed)/([a-f0-9]{32})/?', parsed.path)
    if parsed.scheme not in ('http', 'https') or parsed.hostname not in ('loom.com', 'www.loom.com') or not match:
        raise Failure('invalid_url', 'A Loom single-video share or embed URL is required.')
    identifier, canonical = match[1], 'https://www.loom.com/share/' + match[1]
    video = _graphql('GetVideoSSR', identifier,
        'getVideo(id: $videoId) { __typename ... on RegularUserVideo { id name description createdAt owner { display_name } video_properties { duration width height microphone_enabled tab_audio } playable_duration } }', cookies=cookies).get('getVideo') or {}
    kind = video.get('__typename')
    if kind in ('PrivateVideo', 'VideoPasswordMissingOrIncorrect'):
        raise Failure('access_denied', 'Loom video is private or password protected; anonymous public access is required.')
    if str(video.get('id')) != identifier or kind != 'RegularUserVideo':
        raise Failure('parse_failed', 'Loom returned no matching public video.')
    props = video.get('video_properties') or {}
    needs = set(need or ('info', 'transcript', 'video'))
    result = {'source': {'platform': 'loom', 'id': identifier, 'url': canonical},
        'metadata': {'platform': 'loom', 'id': identifier, 'url': canonical, 'title': video.get('name'),
            'description': video.get('description'), 'author': (video.get('owner') or {}).get('display_name'),
            'duration': video.get('playable_duration') or props.get('duration'), 'published_at': video.get('createdAt'),
            'audio_expected': True if props.get('microphone_enabled') or props.get('tab_audio') else None,
            'original_language': None, 'collected_at': datetime.now(timezone.utc).isoformat()},
        'subtitles': [], 'formats': [], 'diagnostics': []}
    if 'transcript' in needs:
        try:
            track = _graphql('FetchVideoTranscript', identifier,
                'fetchVideoTranscript(videoId: $videoId) { __typename ... on VideoTranscriptDetails { source_url captions_source_url } }', cookies=cookies).get('fetchVideoTranscript') or {}
            address = track.get('captions_source_url')
            if address and urlsplit(address).scheme in ('http', 'https'):
                result['subtitles'].append({'url': address, 'ext': 'vtt', 'language': '', 'origin': 'platform_unknown'})
            elif track.get('source_url'):
                result['diagnostics'].append(diagnostic('transcript', Failure('subtitle_format_unsupported', 'Loom exposes JSON transcript data without a supported VTT caption track.', 'Use local ASR.')))
            else:
                result['diagnostics'].append(diagnostic('transcript', Failure('subtitle_unavailable', 'Loom returned no supported caption track; transcript availability is unconfirmed.', 'Use local ASR.')))
        except Failure as exc:
            result['diagnostics'].append(diagnostic('transcript', exc))
    if needs.intersection(('video', 'audio', 'frames', 'media')):
        # Native raw media retains source quality; transcodes provide a progressive fallback.
        for endpoint in ('raw-url', 'transcoded-url'):
            try:
                response = read_json(f'https://www.loom.com/api/campaigns/sessions/{identifier}/{endpoint}', cookies=cookies,
                    headers={'Content-Type': 'application/json', 'Referer': canonical},
                    data=json.dumps({'anonID': str(uuid.uuid4()), 'deviceID': None, 'force_original': False, 'password': None}).encode())
                address = response.get('url')
                if not address or urlsplit(address).scheme not in ('http', 'https'):
                    continue
                ext = urlsplit(address).path.rsplit('.', 1)[-1].lower()
                headers = {'Referer': canonical}
                if ext == 'm3u8':
                    if __package__ == 'scripts.platforms':
                        from ..streams import _fetch, hls_formats
                    else:
                        from streams import _fetch, hls_formats
                    final, text = _fetch(address, cookies, headers)
                    original_url, final_url = urlsplit(address), urlsplit(final)
                    same_origin = (original_url.scheme, original_url.netloc.lower()) == (final_url.scheme, final_url.netloc.lower())
                    resource_query = original_url.query if same_origin else final_url.query
                    formats, _ = hls_formats(text, final, headers=headers, segment_query=resource_query or None, include_audio='frames' not in needs or bool(needs.intersection(('video', 'audio', 'transcript'))))
                    result['formats'].extend(formats)
                elif ext in ('mp4', 'webm', 'mov'):
                    result['formats'].append({'url': address, 'ext': ext,
                        'width': props.get('width') if endpoint == 'raw-url' else None, 'height': props.get('height') if endpoint == 'raw-url' else None,
                        'has_video': True, 'has_audio': None, 'is_original': endpoint == 'raw-url', 'headers': headers})
                else:
                    result['diagnostics'].append(diagnostic('media', Failure('format_unsupported', 'Loom returned an unsupported media container.')))
                if result['formats']:
                    break
            except Failure as exc:
                result['diagnostics'].append(diagnostic('media', exc))
        if not result['formats']:
            result['diagnostics'].append(diagnostic('media', Failure('media_unavailable', 'Loom exposes no supported public media.')))
    return result
