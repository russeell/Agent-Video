"""TED single talks. Next.js/player resource schema researched from yt-dlp,
commit 51bab8a0116f4d8004c315706d809782607d5847 (Unlicense).
Native metadata/full WebVTT subtitles verified against public TED responses.
No external extractor is imported or executed.
"""
from datetime import datetime, timezone
import json
import re
from urllib.parse import urlsplit
from . import Failure, diagnostic, read_json, read_text


def resolve(url, *, part=None, cookies=None, need=None):
    if part is not None:
        raise Failure('invalid_part', '--part only applies to Bilibili.')
    parsed = urlsplit(url)
    match = re.fullmatch(r'/talks/(?:lang/[\w-]+/)?([\w-]+)(?:/transcript)?/?', parsed.path)
    if not match or parsed.hostname not in ('ted.com', 'www.ted.com'):
        raise Failure('invalid_url', 'A TED single-talk URL is required.')
    canonical = 'https://www.ted.com/talks/' + match[1]
    html = read_text(canonical, cookies=cookies)
    embedded = re.search(r'<script[^>]*\bid="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    try:
        talk = json.loads(embedded[1])['props']['pageProps']['videoData']
    except (TypeError, ValueError, KeyError):
        raise Failure('parse_failed', 'TED returned no readable single-talk player data.') from None
    if talk.get('slug') != match[1] or not talk.get('id'):
        raise Failure('parse_failed', 'TED returned information for a different talk.')
    identifier = str(talk['id'])
    player = talk.get('videoPlayerData') or {}
    resources = player.get('resources') or {}
    needs = set(need or ('info', 'transcript', 'video'))
    result = {'source': {'platform': 'ted', 'id': identifier, 'url': canonical},
              'metadata': {'platform': 'ted', 'id': identifier, 'url': canonical,
                           'title': talk.get('title'), 'author': talk.get('presenterDisplayName'),
                           'description': talk.get('description'), 'duration': talk.get('duration'),
                           'original_language': player.get('nativeLanguage') or talk.get('audioInternalLanguageCode'),
                           'published_at': talk.get('publishedAt'), 'audio_expected': None,
                           'collected_at': datetime.now(timezone.utc).isoformat()},
              'subtitles': [], 'formats': [], 'diagnostics': []}
    hls = resources.get('hls') or {}
    if 'transcript' in needs:
        if hls.get('metadata'):
            try:
                captions = read_json(hls['metadata'], cookies=cookies)
                result['subtitles'] = [{'url': t['webvtt'], 'ext': 'vtt', 'language': t.get('code'),
                                         'origin': 'platform_manual'}
                                        for t in captions.get('subtitles') or [] if t.get('webvtt')]
            except Failure as exc:
                result['diagnostics'].append(diagnostic('transcript', exc))
        if not result['subtitles'] and not result['diagnostics']:
            result['diagnostics'].append(diagnostic('transcript', Failure('subtitle_absent', 'TED native player exposes no full subtitle tracks.', 'Use local ASR.')))
    if needs.intersection(('video', 'audio', 'frames', 'media')):
        for entry in resources.get('h264') or []:
            if entry.get('file'):
                # TED's fallback is a muxed stream; dimensions absent in the API
                # remain unknown rather than being invented from its bitrate.
                result['formats'].append({'url': entry['file'], 'ext': 'mp4', 'has_video': True,
                    'has_audio': None, 'width': entry.get('width'), 'height': entry.get('height'),
                    'bitrate': entry.get('bitrate', 0) * 1000})
        if hls.get('stream'):
            try:
                if __package__ == 'scripts.platforms':
                    from ..streams import _fetch, hls_formats, _playlist
                else:
                    from streams import _fetch, hls_formats, _playlist
                final, text = _fetch(hls['stream'], cookies)
                formats, language = hls_formats(text, final, include_audio='frames' not in needs or bool(needs.intersection(('video', 'audio', 'transcript'))))
                # Validate the highest leaf before offering HLS for selection.
                # TED intro segments may require unsupported discontinuities.
                best = max((f for f in formats if f.get('has_video')), key=lambda f: (f.get('width', 0) * f.get('height', 0), f.get('bitrate', 0)), default=None)
                if best:
                    leaf_url, leaf = _fetch(best['url'], cookies)
                    _playlist(leaf, leaf_url)
                result['formats'].extend(formats)
                result['metadata']['original_language'] = result['metadata']['original_language'] or language
            except Failure as exc:
                result['diagnostics'].append(diagnostic('media', exc))
        if talk.get('audioDownload'):
            result['formats'].append({'url': talk['audioDownload'], 'ext': 'mp3', 'has_video': False, 'has_audio': True})
        result['metadata']['audio_expected'] = True if any(f.get('has_audio') is True for f in result['formats']) else None
        if not result['formats']:
            external = player.get('external') or {}
            result['diagnostics'].append(diagnostic('media', Failure(
                'external_host_unsupported' if external else 'media_unavailable',
                'TED has no supported native stream' + ('; its player uses ' + str(external.get('service') or 'an external host') if external else '') + '.',
                'Use the external video URL directly or provide local media.')))
    return result
