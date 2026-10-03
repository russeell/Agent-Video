"""Reddit single-post native video acquisition, without external link traversal.

JSON reddit_video fields and direct MPD resources researched in yt-dlp
extractor/reddit.py (Unlicense), commit 51bab8a0116f4d8004c315706d809782607d5847.
Project-owned parser; a post identity remains the source identity.
"""
from datetime import datetime, timezone
import html
import re
from urllib.parse import urljoin, urlsplit
import xml.etree.ElementTree as ET
from . import Failure, diagnostic, media, read_json, read_text


def _identity(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or parsed.hostname not in (
            'reddit.com', 'www.reddit.com', 'old.reddit.com', 'new.reddit.com', 'm.reddit.com'):
        raise Failure('invalid_url', 'A Reddit single-post URL is required.')
    match = re.fullmatch(r'/(?:(?:r|user)/[^/]+/)?comments/([a-zA-Z0-9]+)(?:/[^/]+)?/?', parsed.path)
    if not match:
        raise Failure('invalid_url', 'A Reddit single-post URL is required; feeds and external links are unsupported.')
    return match[1].lower()


def _post(data, identifier):
    try:
        post = data[0]['data']['children'][0]['data']
    except (KeyError, IndexError, TypeError):
        raise Failure('parse_failed', 'Reddit did not return a readable single post.') from None
    if not isinstance(post, dict) or post.get('id') != identifier:
        raise Failure('parse_failed', 'Reddit response does not identify the requested post.')
    return post


def _mpd(text, url):
    """Read full-file SegmentBase representations, never forge audio URLs."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        raise Failure('parse_failed', 'Reddit returned an unrecognized DASH manifest.') from None
    ns = {'d': 'urn:mpeg:dash:schema:mpd:2011'}
    if root.tag != '{urn:mpeg:dash:schema:mpd:2011}MPD' or root.get('type', 'static') != 'static':
        raise Failure('live_unsupported', 'Only completed Reddit videos are supported.')
    if len(root.findall('d:Period', ns)) != 1:
        raise Failure('format_unsupported', 'Reddit DASH must contain one complete period.')
    period = root.find('d:Period', ns)
    if any(e.tag.rsplit('}', 1)[-1] in ('SegmentTemplate', 'SegmentList', 'ContentProtection') for e in list(root) + list(period)):
        raise Failure('format_unsupported', 'Reddit DASH exposes segmented or protected resources.')
    formats, subtitles = [], []
    for adaptation in root.findall('d:Period/d:AdaptationSet', ns):
        for rep in adaptation.findall('d:Representation', ns):
            address = rep.findtext('d:BaseURL', namespaces=ns)
            if not address or rep.find('d:ContentProtection', ns) is not None or adaptation.find('d:ContentProtection', ns) is not None:
                continue
            if any(e.tag.rsplit('}', 1)[-1] in ('SegmentTemplate', 'SegmentList') for e in list(rep) + list(adaptation)):
                continue
            address = urljoin(url, address)
            if urlsplit(address).scheme != 'https':
                continue
            mime = rep.get('mimeType') or adaptation.get('mimeType') or ''
            if mime in ('text/vtt', 'application/x-subrip'):
                subtitles.append({'url': address, 'ext': 'vtt' if mime == 'text/vtt' else 'srt',
                                  'language': adaptation.get('lang') or rep.get('lang') or '',
                                  'origin': 'platform_unknown'})
            elif mime in ('video/mp4', 'audio/mp4'):
                def number(key):
                    value = rep.get(key)
                    return int(value) if value and value.isdigit() else None
                formats.append({'url': address, 'ext': 'mp4' if mime == 'video/mp4' else 'm4a',
                                'width': number('width'), 'height': number('height'), 'bitrate': number('bandwidth'),
                                'fps': media.frame_rate(rep.get('frameRate') or adaptation.get('frameRate') or ''),
                                'has_video': mime == 'video/mp4', 'has_audio': mime == 'audio/mp4'})
    return formats, subtitles


def resolve(url, *, part=None, cookies=None, need=None):
    if part is not None:
        raise Failure('invalid_part', '--part only applies to Bilibili.')
    identifier = _identity(url)
    canonical = f'https://www.reddit.com/comments/{identifier}/'
    post = _post(read_json(canonical + '.json?raw_json=1', cookies=cookies), identifier)
    video = next(((post.get(k) or {}).get('reddit_video') for k in ('secure_media', 'media')
                  if (post.get(k) or {}).get('reddit_video')), {})
    # Crossposts are not silently mapped to another post's media.
    thumbnail = post.get('thumbnail')
    if not isinstance(thumbnail, str) or urlsplit(thumbnail).scheme != 'https' or urlsplit(thumbnail).query:
        thumbnail = None
    metadata = {'platform': 'reddit', 'id': identifier, 'url': canonical, 'title': post.get('title'),
                'description': post.get('selftext'), 'author': post.get('author'), 'duration': video.get('duration'),
                'published_at': post.get('created_utc'), 'thumbnail': thumbnail, 'like_count': post.get('ups'),
                'comment_count': post.get('num_comments'), 'experimental': True,
                'audio_expected': video.get('has_audio'), 'collected_at': datetime.now(timezone.utc).isoformat()}
    result = {'source': {'platform': 'reddit', 'id': identifier, 'url': canonical},
              'metadata': metadata, 'subtitles': [], 'formats': [], 'diagnostics': []}
    needs = set(need or ('info', 'transcript', 'video'))
    media_needed = bool(needs.intersection(('video', 'audio', 'frames', 'media')))
    if not media_needed and 'transcript' not in needs:
        return result
    if not video:
        stage = 'media' if media_needed else 'transcript'
        result['diagnostics'].append(diagnostic(stage, Failure('media_unavailable',
            'This post exposes no Reddit-hosted single video.', 'Use the original supported platform URL or a local media file.')))
        return result
    if video.get('is_gif'):
        metadata['audio_expected'] = False
    manifest = video.get('dash_url')
    if manifest:
        try:
            formats, subtitles = _mpd(read_text(html.unescape(manifest), cookies=cookies), html.unescape(manifest))
            if media_needed:
                result['formats'] = formats
            if 'transcript' in needs:
                result['subtitles'] = subtitles
            if metadata['audio_expected'] is None and formats:
                metadata['audio_expected'] = any(f['has_audio'] for f in formats)
        except Failure as exc:
            result['diagnostics'].append(diagnostic('media' if media_needed else 'transcript', exc))
    if media_needed and not any(f['has_video'] for f in result['formats']):
        fallback = video.get('fallback_url')
        if isinstance(fallback, str) and urlsplit(fallback).scheme == 'https':
            result['formats'].append({'url': html.unescape(fallback), 'ext': 'mp4', 'width': video.get('width'),
                                      'height': video.get('height'), 'has_video': True, 'has_audio': False})
        else:
            result['diagnostics'].append(diagnostic('media', Failure('media_unavailable', 'No native Reddit video resource was returned.')))
    if media_needed and metadata['audio_expected'] is not False and not any(f['has_audio'] for f in result['formats']):
        result['diagnostics'].append(diagnostic('media', Failure('audio_unavailable',
            'A usable original Reddit audio track could not be established.', 'Provide a local media file.')))
    if 'transcript' in needs and not result['subtitles']:
        result['diagnostics'].append(diagnostic('transcript', Failure('subtitle_failed',
            'The Reddit DASH path exposed no usable captions; other caption availability is unknown.', 'Use local ASR.')))
    return result
