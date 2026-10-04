"""Native Bluesky post videos. Public API/PDS flow researched from yt-dlp
(Unlicense), commit 51bab8a0116f4d8004c315706d809782607d5847.
Quoted posts and external embeds never replace the requested post's video.
"""
from datetime import datetime, timezone
import re
from urllib.parse import unquote, urlencode, urlsplit
from . import Failure, diagnostic, read_json


def _endpoint(did, cookies):
    if re.fullmatch(r'did:plc:[a-z0-9]+', did):
        document = read_json('https://plc.directory/' + did, cookies=cookies)
    elif did.startswith('did:web:'):
        parts = did[8:].split(':')
        host = unquote(parts[0])
        if '/' in host or '@' in host or '?' in host or '#' in host:
            raise Failure('parse_failed', 'Bluesky returned an invalid DID host.')
        path = '/'.join(unquote(p) for p in parts[1:])
        document = read_json('https://' + host + ('/' + path + '/did.json' if path else '/.well-known/did.json'), cookies=cookies)
    else:
        raise Failure('parse_failed', 'Bluesky returned an unsupported author DID.')
    endpoints = [s.get('serviceEndpoint') for s in document.get('service', [])
                 if s.get('type') == 'AtprotoPersonalDataServer']
    if len(endpoints) != 1 or not isinstance(endpoints[0], str) or urlsplit(endpoints[0]).scheme != 'https':
        raise Failure('parse_failed', 'Bluesky DID does not identify one HTTPS personal data server.')
    return endpoints[0].rstrip('/')


def resolve(url, *, part=None, cookies=None, need=None):
    if part is not None:
        raise Failure('invalid_part', '--part only applies to Bilibili.')
    parsed = urlsplit(url)
    match = re.fullmatch(r'/profile/([^/]+)/post/([a-zA-Z0-9]+)/?', parsed.path)
    if parsed.scheme not in ('http', 'https') or parsed.hostname not in ('bsky.app', 'www.bsky.app', 'main.bsky.dev') or not match:
        raise Failure('invalid_url', 'A Bluesky single-post URL is required.')
    handle, identifier = unquote(match[1]), match[2]
    if not re.fullmatch(r'[a-zA-Z0-9.:%-]+', handle):
        raise Failure('invalid_url', 'Invalid Bluesky profile identifier.')
    canonical = 'https://bsky.app/profile/' + handle + '/post/' + identifier
    data = read_json('https://public.api.bsky.app/xrpc/app.bsky.feed.getPostThread?' + urlencode(
        {'uri': f'at://{handle}/app.bsky.feed.post/{identifier}', 'depth': 0, 'parentHeight': 0}), cookies=cookies)
    post = (data.get('thread') or {}).get('post') or {}
    author = post.get('author') or {}
    did = author.get('did') or ''
    if post.get('uri') != f'at://{did}/app.bsky.feed.post/{identifier}' or handle not in (did, author.get('handle')):
        raise Failure('parse_failed', 'Bluesky returned no matching public post.')
    record = post.get('record') or {}
    embed, record_embed = post.get('embed') or {}, record.get('embed') or {}
    if embed.get('$type') == 'app.bsky.embed.recordWithMedia#view':
        embed, record_embed = embed.get('media') or {}, record_embed.get('media') or {}
    if embed.get('$type') != 'app.bsky.embed.video#view' or record_embed.get('$type') != 'app.bsky.embed.video':
        raise Failure('native_video_absent', 'The requested Bluesky post contains no native video.')
    needs = set(need or ('info', 'transcript', 'video'))
    text = record.get('text') or ''
    thumbnail = embed.get('thumbnail')
    if thumbnail and (urlsplit(thumbnail).scheme != 'https' or urlsplit(thumbnail).query):
        thumbnail = None
    result = {'source': {'platform': 'bluesky', 'id': identifier, 'url': canonical},
              'metadata': {'platform': 'bluesky', 'id': identifier, 'url': canonical,
                  'title': text.replace('\n', ' ')[:120] or embed.get('alt') or 'Bluesky video ' + identifier,
                  'description': text, 'author': author.get('displayName') or author.get('handle'),
                  'published_at': record.get('createdAt'), 'duration': None, 'thumbnail': thumbnail,
                  'like_count': post.get('likeCount'), 'comment_count': post.get('replyCount'),
                  'audio_expected': None, 'original_language': None, 'collected_at': datetime.now(timezone.utc).isoformat()},
              'formats': [], 'subtitles': [], 'diagnostics': []}
    media_needed = bool(needs.intersection(('video', 'audio', 'frames', 'media')))
    captions = record_embed.get('captions') or []
    endpoint = None
    if media_needed or 'transcript' in needs and captions:
        try:
            endpoint = _endpoint(did, cookies)
        except Failure as exc:
            result['diagnostics'].append(diagnostic('media' if media_needed else 'transcript', exc))
    def blob_url(cid):
        return endpoint + '/xrpc/com.atproto.sync.getBlob?' + urlencode({'did': did, 'cid': cid})
    if 'transcript' in needs:
        for caption in captions:
            file = caption.get('file') or {}
            cid = (file.get('ref') or {}).get('$link')
            if endpoint and cid and file.get('mimeType') == 'text/vtt':
                result['subtitles'].append({'url': blob_url(cid), 'language': caption.get('lang') or 'und',
                                            'ext': 'vtt', 'origin': 'platform_unknown'})
        if not result['subtitles']:
            result['diagnostics'].append(diagnostic('transcript', Failure(
                'subtitle_unavailable' if captions else 'subtitle_absent',
                'Bluesky caption tracks could not be resolved.' if captions else 'Bluesky post exposes no caption tracks.', 'Use local ASR.')))
    if media_needed:
        file = record_embed.get('video') or {}
        cid = (file.get('ref') or {}).get('$link')
        if embed.get('cid') and cid != embed['cid']:
            raise Failure('parse_failed', 'Bluesky video blob identity is inconsistent.')
        if endpoint and cid and file.get('mimeType') == 'video/mp4':
            # aspectRatio is not the encoded resolution; keep dimensions unknown.
            result['formats'].append({'url': blob_url(cid), 'ext': 'mp4', 'has_video': True,
                                      'has_audio': None, 'width': None, 'height': None, 'format_id': 'original', 'is_original': True})
        playlist = embed.get('playlist')
        if playlist and urlsplit(playlist).scheme == 'https':
            try:
                if __package__ == 'scripts.platforms':
                    from ..streams import _fetch, hls_formats
                else:
                    from streams import _fetch, hls_formats
                final, content = _fetch(playlist, cookies)
                formats, _ = hls_formats(content, final, include_audio='frames' not in needs or bool(needs.intersection(('video', 'audio', 'transcript'))))
                result['formats'].extend(formats)
            except Failure as exc:
                result['diagnostics'].append(diagnostic('media', exc))
        if not result['formats']:
            result['diagnostics'].append(diagnostic('media', Failure('media_unavailable', 'Bluesky exposes no supported native video resource.')))
    return result
