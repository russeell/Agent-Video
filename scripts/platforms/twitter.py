"""Public X single-status acquisition via the platform's syndication endpoint.

Endpoint and mediaDetails research: yt-dlp/extractor/twitter.py, Unlicense,
commit 51bab8a0116f4d8004c315706d809782607d5847. Project-owned parser.
Syndication exposes a subset of media; quoted posts are never substituted.
"""
from datetime import datetime, timezone
import re
from urllib.parse import urlsplit
from . import Failure, diagnostic, read_json, read_text


def _identity(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or parsed.hostname not in (
            'x.com', 'www.x.com', 'twitter.com', 'www.twitter.com', 'mobile.twitter.com'):
        raise Failure('invalid_url', 'An X/Twitter single-status URL is required.')
    match = re.fullmatch(r'/(?:i/web|[^/]+)/status/(\d+)(?:/video/([1-9]\d*))?/?', parsed.path)
    if not match:
        raise Failure('invalid_url', 'An X/Twitter single-status URL is required.')
    identifier, index = match.groups()
    return identifier, int(index) if index else None


def _formats(detail):
    result = []
    for variant in (detail.get('video_info') or {}).get('variants') or []:
        url = variant.get('url')
        if variant.get('content_type') != 'video/mp4' or not isinstance(url, str) or urlsplit(url).scheme != 'https':
            continue
        size = re.search(r'/(\d+)x(\d+)/', urlsplit(url).path)
        result.append({'url': url, 'ext': 'mp4', 'width': int(size[1]) if size else None,
                       'height': int(size[2]) if size else None, 'bitrate': variant.get('bitrate'),
                       'has_video': True, 'has_audio': detail.get('type') != 'animated_gif'})
    return result


def resolve(url, *, part=None, cookies=None, need=None):
    if part is not None:
        raise Failure('invalid_part', '--part only applies to Bilibili.')
    identifier, index = _identity(url)
    # The public endpoint accepts a nonempty token. This is an anonymous
    # syndication parameter, not an account access token or credential.
    data = read_json(f'https://cdn.syndication.twimg.com/tweet-result?id={identifier}&token=1',
                     headers={'User-Agent': 'Googlebot'}, cookies=cookies)
    if not isinstance(data, dict) or str(data.get('id_str')) != identifier:
        raise Failure('experimental_access_limited', 'X syndication did not return the requested status.',
                      'The status may be unavailable to anonymous syndication; provide a local media file.')
    attachments = data.get('mediaDetails') or []
    videos = [m for m in attachments if isinstance(m, dict) and m.get('type') in ('video', 'animated_gif')]
    if index:
        if index > len(attachments) or attachments[index - 1] not in videos:
            raise Failure('invalid_url', 'The selected X media index is not a video.')
        detail = attachments[index - 1]
    elif len(videos) > 1:
        raise Failure('media_ambiguous', 'This status contains several videos.',
                      'Use the specific /video/1 or /video/2 status URL.')
    else:
        detail = videos[0] if videos else {}
    canonical = f'https://x.com/i/web/status/{identifier}' + (f'/video/{index}' if index else '')
    info = detail.get('video_info') or {}
    duration = info.get('duration_millis')
    thumbnail = detail.get('media_url_https')
    metadata = {'platform': 'twitter', 'id': identifier, 'url': canonical, 'title': data.get('text'),
                'description': data.get('text'), 'author': (data.get('user') or {}).get('name'),
                'duration': duration / 1000 if isinstance(duration, (int, float)) else None,
                'thumbnail': thumbnail if thumbnail and not urlsplit(thumbnail).query else None,
                'published_at': data.get('created_at'), 'like_count': data.get('favorite_count'),
                'comment_count': data.get('conversation_count'), 'experimental': True,
                'audio_expected': detail.get('type') == 'video' if detail else None,
                'collected_at': datetime.now(timezone.utc).isoformat()}
    result = {'source': {'platform': 'twitter', 'id': identifier, 'url': canonical},
              'metadata': metadata, 'subtitles': [], 'formats': [], 'diagnostics': []}
    needs = set(need or ('info', 'transcript', 'video'))
    if needs.intersection(('video', 'audio', 'frames', 'media')):
        result['formats'] = _formats(detail)
        if __package__ == 'scripts.platforms':
            from ..streams import hls_formats
        else:
            from streams import hls_formats
        for variant in info.get('variants') or []:
            address = variant.get('url')
            if (variant.get('content_type') not in ('application/x-mpegURL', 'application/vnd.apple.mpegurl')
                    or not isinstance(address, str) or urlsplit(address).scheme != 'https'):
                continue
            try:
                formats, _ = hls_formats(read_text(address, cookies=cookies), address,
                                        include_audio=bool(needs.intersection(('video', 'audio', 'media'))))
                result['formats'].extend(formats)
            except Failure as exc:
                result['diagnostics'].append(diagnostic('media', exc))
        if not result['formats']:
            result['diagnostics'].append(diagnostic('media', Failure('experimental_access_limited',
                'X syndication exposed no downloadable video for this status.', 'Provide a local media file.')))
    if 'transcript' in needs:
        result['diagnostics'].append(diagnostic('transcript', Failure('subtitle_failed',
            'The anonymous syndication response does not establish caption availability.', 'Use local ASR.')))
    return result
