"""Anonymous Twitch clip and completed-VOD acquisition using native GraphQL.

Client identity, clip assets and usher endpoint researched in yt-dlp's
extractor/twitch.py (Unlicense), commit 51bab8a0116f4d8004c315706d809782607d5847.
Project-owned queries and parser; no channel/live or playlist traversal.
"""
from datetime import datetime, timezone
import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from . import Failure, diagnostic, read_json, read_text

CLIENT_ID = 'ue6666qo983tsx6so1t0vnawi233wa'
CLIP_INFO = '''query($slug: ID!){clip(slug:$slug){id slug title durationSeconds viewCount createdAt thumbnailURL broadcaster{displayName} curator{displayName}}}'''
CLIP_MEDIA = '''query($slug: ID!){clip(slug:$slug){id slug playbackAccessToken(params:{platform:"web",playerBackend:"mediaplayer",playerType:"site"}){value signature} assets{aspectRatio videoQualities{quality frameRate sourceURL}}}}'''
VOD_INFO = '''query($id: ID!){video(id:$id){id title lengthSeconds viewCount publishedAt previewThumbnailURL broadcastType owner{displayName}}}'''
VOD_TOKEN = '''query($id: ID!){videoPlaybackAccessToken(id:$id,params:{platform:"web",playerBackend:"mediaplayer",playerType:"site"}){value signature}}'''


def _identity(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https'):
        raise Failure('invalid_url', 'A Twitch clip or completed video URL is required.')
    if parsed.hostname == 'clips.twitch.tv':
        match = re.fullmatch(r'/([A-Za-z0-9_-]+)/?', parsed.path)
        if match:
            return 'clip', match[1]
    elif parsed.hostname in ('twitch.tv', 'www.twitch.tv', 'm.twitch.tv', 'go.twitch.tv'):
        match = re.fullmatch(r'/videos/(\d+)/?', parsed.path)
        if match:
            return 'vod', match[1]
        match = re.fullmatch(r'/(?:[^/]+/)?clip/([A-Za-z0-9_-]+)/?', parsed.path)
        if match:
            return 'clip', match[1]
        if re.fullmatch(r'/[^/]+/?', parsed.path):
            raise Failure('live_unsupported', 'Twitch live channels are unsupported.', 'Use a clip or completed /videos/ URL.')
    raise Failure('invalid_url', 'A Twitch clip or completed /videos/ URL is required; channel feeds are unsupported.')


def _gql(query, variables, cookies=None):
    data = read_json('https://gql.twitch.tv/gql', headers={
        'Client-ID': CLIENT_ID, 'Content-Type': 'text/plain;charset=UTF-8'}, cookies=cookies,
        data=json.dumps({'query': query, 'variables': variables}).encode())
    if not isinstance(data, dict) or data.get('errors') or not isinstance(data.get('data'), dict):
        raise Failure('parse_failed', 'Twitch did not return the requested GraphQL data.', 'Retry later or provide a local media file.')
    return data['data']


def _token(token):
    if not isinstance(token, dict) or not token.get('value') or not token.get('signature'):
        raise Failure('access_denied', 'Twitch did not grant a playback token.', 'Use a publicly available work or provide a local media file.')
    return {'sig': token['signature'], 'token': token['value']}


def _clip_formats(clip):
    token = _token(clip.get('playbackAccessToken'))
    assets = clip.get('assets') or []
    # A portrait edit can crop the original clip. Preserve the default asset.
    asset = assets[0] if assets and isinstance(assets[0], dict) else {}
    ratio = asset.get('aspectRatio')
    result = []
    for source in asset.get('videoQualities') or []:
        address = source.get('sourceURL')
        if not isinstance(address, str) or urlsplit(address).scheme != 'https':
            continue
        parsed = urlsplit(address)
        query = dict(parse_qsl(parsed.query))
        query.update(token)
        height = int(source['quality']) if str(source.get('quality', '')).isdigit() else None
        width = round(height * ratio) if height and isinstance(ratio, (int, float)) and ratio > 0 else None
        fps = source.get('frameRate')
        result.append({'url': urlunsplit(parsed._replace(query=urlencode(query))), 'ext': 'mp4',
                       'width': width, 'height': height, 'fps': fps if isinstance(fps, (int, float)) and fps > 0 else None,
                       'has_video': True, 'has_audio': True})
    return result


def resolve(url, *, part=None, cookies=None, need=None):
    if part is not None:
        raise Failure('invalid_part', '--part only applies to Bilibili.')
    kind, identifier = _identity(url)
    canonical = f'https://clips.twitch.tv/{identifier}' if kind == 'clip' else f'https://www.twitch.tv/videos/{identifier}'
    query = CLIP_INFO if kind == 'clip' else VOD_INFO
    variables = {'slug' if kind == 'clip' else 'id': identifier}
    item = _gql(query, variables, cookies).get('clip' if kind == 'clip' else 'video')
    if not isinstance(item, dict):
        raise Failure('media_unavailable', 'The requested Twitch work is unavailable or private.')
    if (not item.get('id') or kind == 'clip' and item.get('slug') != identifier
            or kind == 'vod' and str(item.get('id')) != identifier):
        raise Failure('parse_failed', 'Twitch response does not identify the requested work.')
    thumbnail = item.get('thumbnailURL' if kind == 'clip' else 'previewThumbnailURL')
    if kind == 'vod' and thumbnail and '404_processing_' in thumbnail and item.get('broadcastType') == 'ARCHIVE':
        raise Failure('live_unsupported', 'This Twitch archive is still being recorded or processed.', 'Wait for the completed VOD.')
    if thumbnail and ('{' in thumbnail or urlsplit(thumbnail).query):
        thumbnail = None
    work_id = str(item['id'])
    metadata = {'platform': 'twitch', 'id': work_id, 'url': canonical, 'title': item.get('title'),
                'author': (item.get('broadcaster' if kind == 'clip' else 'owner') or {}).get('displayName'),
                'duration': item.get('durationSeconds' if kind == 'clip' else 'lengthSeconds'),
                'published_at': item.get('createdAt' if kind == 'clip' else 'publishedAt'),
                'view_count': item.get('viewCount'), 'thumbnail': thumbnail, 'audio_expected': True,
                'experimental': True, 'collected_at': datetime.now(timezone.utc).isoformat()}
    result = {'source': {'platform': 'twitch', 'id': work_id, 'url': canonical},
              'metadata': metadata, 'subtitles': [], 'formats': [], 'diagnostics': []}
    needs = set(need or ('info', 'transcript', 'video'))
    if 'transcript' in needs:
        result['diagnostics'].append(diagnostic('transcript', Failure('subtitle_failed',
            'The public Twitch API does not establish downloadable caption availability.', 'Use local ASR.')))
    if not needs.intersection(('video', 'audio', 'frames', 'media')):
        return result
    try:
        if kind == 'clip':
            clip = _gql(CLIP_MEDIA, variables, cookies).get('clip')
            if not isinstance(clip, dict) or str(clip.get('id')) != work_id or clip.get('slug') != identifier:
                raise Failure('parse_failed', 'Twitch playback response does not identify the requested clip.')
            result['formats'] = _clip_formats(clip)
        else:
            token = _token(_gql(VOD_TOKEN, variables, cookies).get('videoPlaybackAccessToken'))
            address = f'https://usher.ttvnw.net/vod/{identifier}.m3u8?' + urlencode({
                **token, 'allow_source': 'true', 'allow_audio_only': 'true', 'platform': 'web',
                'player': 'twitchweb', 'playlist_include_framerate': 'true', 'supported_codecs': 'av1,h265,h264'})
            if __package__ == 'scripts.platforms':
                from ..streams import hls_formats
            else:
                from streams import hls_formats
            result['formats'], _ = hls_formats(read_text(address, cookies=cookies), address,
                include_audio=bool(needs.intersection(('video', 'audio', 'media'))))
        if not result['formats']:
            raise Failure('media_unavailable', 'Twitch exposed no usable media stream for this work.')
    except Failure as exc:
        result['diagnostics'].append(diagnostic('media', exc))
    return result
