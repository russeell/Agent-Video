"""Experimental public-page TikTok single-work extraction.

Embedded-data and bitrateInfo fields researched in yt-dlp (Unlicense):
https://github.com/yt-dlp/yt-dlp/blob/51bab8a0116f4d8004c315706d809782607d5847/yt_dlp/extractor/tiktok.py
Project-owned single-work parser; music.playUrl is not the work audio.
"""
from datetime import datetime, timezone
import html
import json
import re
from urllib.parse import urlsplit
from . import Failure, diagnostic, read_text, request


def _embedded(text):
    for name in ('__UNIVERSAL_DATA_FOR_REHYDRATION__', 'SIGI_STATE'):
        match = re.search(r'<script\b[^>]*\bid=[\"\']' + name + r'[\"\'][^>]*>(.*?)</script>', text, re.S)
        if match:
            try:
                return json.loads(html.unescape(match[1]))
            except ValueError:
                pass
    raise Failure('experimental_access_limited', 'TikTok returned no readable single-work embedded data.', 'Try your own Cookie file or provide a local media file.')


def _item(data, identifier):
    scope = data.get('__DEFAULT_SCOPE__', {})
    item = ((scope.get('webapp.video-detail') or {}).get('itemInfo') or {}).get('itemStruct')
    if not item:
        item = (data.get('ItemModule') or {}).get(identifier)
    if not isinstance(item, dict) or str(item.get('id')) != identifier:
        raise Failure('parse_failed', 'TikTok page does not identify the requested single video.')
    return item


def _formats(video):
    formats = []
    seen = set()
    headers = {'Referer': 'https://www.tiktok.com/'}
    for stream in video.get('bitrateInfo') or []:
        # ByteDance's custom bytevc2 stream is not a generally playable codec.
        if stream.get('CodecType') not in (None, 'h264', 'bytevc1', 'h265'):
            continue
        address = stream.get('PlayAddr') or {}
        urls = address.get('UrlList') or []
        # The platform's own play endpoint can work when its CDN host denies
        # the same public work. Use only returned URLs, without forging paths.
        urls = sorted((u for u in urls if isinstance(u, str)),
                      key=lambda u: urlsplit(u).hostname != 'www.tiktok.com')
        for url in urls:
            if not isinstance(url, str) or not url.startswith('https://') or url in seen:
                continue
            seen.add(url)
            formats.append({'url': url, 'ext': 'mp4', 'width': address.get('Width'),
                            'height': address.get('Height'), 'fps': stream.get('BitrateFPS'),
                            'bitrate': stream.get('Bitrate'), 'has_video': True,
                            'has_audio': not urlsplit(url).path.endswith('/media-video-hvc1/'),
                            'headers': headers})
    for key in ('playAddr', 'downloadAddr'):
        url = video.get(key)
        if isinstance(url, str) and url.startswith('https://') and url not in seen:
            seen.add(url)
            formats.append({'url': url, 'ext': 'mp4', 'width': video.get('width'),
                            'height': video.get('height'), 'bitrate': video.get('bitrate'),
                            'has_video': True, 'has_audio': True, 'headers': headers})
    return formats


def resolve(url, *, part=None, cookies=None, need=None):
    if part is not None:
        raise Failure('invalid_part', '--part only applies to Bilibili.')
    if urlsplit(url).hostname in ('vm.tiktok.com', 'vt.tiktok.com') or urlsplit(url).path.startswith('/t/'):
        with request(url, cookies=cookies) as response:
            url = response.geturl()
        if not (urlsplit(url).hostname or '').endswith('.tiktok.com'):
            raise Failure('invalid_url', 'TikTok short link redirected outside TikTok.')
    match = re.search(r'/@([^/]+)/video/(\d+)', urlsplit(url).path)
    if not match:
        raise Failure('invalid_url', 'A TikTok single-video URL is required; photo and account links are unsupported.')
    author, identifier = match.groups()
    canonical = f'https://www.tiktok.com/@{author}/video/{identifier}'
    item = _item(_embedded(read_text(canonical, cookies=cookies)), identifier)
    video = item.get('video') or {}
    stats = item.get('stats') or {}
    result = {'source': {'platform': 'tiktok', 'id': identifier, 'url': canonical},
              'metadata': {'platform': 'tiktok', 'id': identifier, 'url': canonical, 'title': item.get('desc'),
                           'author': (item.get('author') or {}).get('nickname'), 'description': item.get('desc'),
                           'duration': video.get('duration'),
                           'thumbnail': video.get('cover') if not urlsplit(video.get('cover') or '').query else None, 'published_at': item.get('createTime'),
                           'view_count': stats.get('playCount'), 'like_count': stats.get('diggCount'),
                           'comment_count': stats.get('commentCount'), 'experimental': True,
                           'collected_at': datetime.now(timezone.utc).isoformat()},
              'subtitles': [], 'formats': [], 'diagnostics': []}
    needs = set(need or ('info', 'transcript', 'video'))
    if 'transcript' in needs:
        for subtitle in video.get('subtitleInfos') or []:
            if subtitle.get('Url') and subtitle.get('Format') in ('webvtt', 'srt'):
                result['subtitles'].append({'url': subtitle['Url'], 'ext': 'srt' if subtitle.get('Format') == 'srt' else 'vtt',
                                           'language': re.sub(r'^(eng|zho|cmn)(?=-|$)', lambda m: {'eng': 'en', 'zho': 'zh', 'cmn': 'zh'}[m[1]], subtitle.get('LanguageCodeName') or ''),
                                           'origin': 'platform_auto' if subtitle.get('Source') in ('ASR', 'asr') else 'platform_unknown'})
        if not result['subtitles']:
            result['diagnostics'].append(diagnostic('transcript', Failure('subtitle_failed', 'The experimental page path exposed no caption tracks; availability is unknown.', 'Use local ASR.')))
    if needs.intersection(('video', 'audio', 'frames', 'media')):
        result['formats'] = _formats(video)
        if not result['formats']:
            result['diagnostics'].append(diagnostic('media', Failure('experimental_access_limited', 'TikTok page exposed no directly downloadable video address.', 'Provide a local media file.')))
    result['metadata']['audio_expected'] = any(f['has_audio'] for f in result['formats']) if result['formats'] else None
    return result
