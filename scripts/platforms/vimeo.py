"""Vimeo single videos. Player schema researched from yt-dlp/vimeo.py,
commit 51bab8a0116f4d8004c315706d809782607d5847 (Unlicense).
No external extractor is imported or executed.
"""
from datetime import datetime, timezone
import json
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from . import Failure, diagnostic, read_json, media


def _config(player, query, canonical, identifier, cookies):
    try:
        return read_json(player + '/config' + query, cookies=cookies, headers={'Referer': canonical})
    except Failure as exc:
        if exc.code != 'access_denied':
            raise
    # Some public works deny the config endpoint while their native embed page
    # exposes the same player data. Read its JSON assignment, never execute JS.
    from . import read_browser_text
    page = read_browser_text(player + query, cookies=cookies, headers={'Referer': canonical})
    decoder = json.JSONDecoder()
    for match in re.finditer(r'\b(?:playerC|c)onfig\s*=\s*', page):
        try:
            config, _ = decoder.raw_decode(page[match.end():])
        except ValueError:
            continue
        if (isinstance(config, dict) and isinstance(config.get('video'), dict)
                and str(config['video'].get('id')) == identifier):
            return config
    raise Failure('parse_failed', 'Vimeo embed page exposes no matching native player JSON.')


def resolve(url, *, part=None, cookies=None, need=None):
    if part is not None:
        raise Failure('invalid_part', '--part only applies to Bilibili.')
    parsed = urlsplit(url)
    match = re.fullmatch(r'/(?:video/)?(\d+)(?:/([a-fA-F0-9]+))?/?', parsed.path)
    if not match or parsed.hostname not in ('vimeo.com', 'www.vimeo.com', 'player.vimeo.com'):
        raise Failure('invalid_url', 'A Vimeo single-video or player URL is required.')
    identifier = match[1]
    token = match[2] or parse_qs(parsed.query).get('h', [None])[0]
    query = '?' + urlencode({'h': token}) if token else ''
    canonical = 'https://vimeo.com/' + identifier + ('/' + token if token else '')
    player = 'https://player.vimeo.com/video/' + identifier
    config = _config(player, query, canonical, identifier, cookies)
    video, request = config.get('video') or {}, config.get('request') or {}
    if str(video.get('id')) != identifier:
        raise Failure('parse_failed', 'Vimeo returned no matching public video information.')
    if (video.get('live_event') or {}).get('status') in ('started', 'active', 'pending'):
        raise Failure('live_unsupported', 'Vimeo live and upcoming streams are unsupported.')
    needs = set(need or ('info', 'transcript', 'video'))
    result = {'source': {'platform': 'vimeo', 'id': identifier, 'url': canonical},
              'metadata': {'platform': 'vimeo', 'id': identifier, 'url': canonical,
                           'title': video.get('title'), 'author': (video.get('owner') or {}).get('name'),
                           'duration': video.get('duration'), 'original_language': video.get('language'),
                           'audio_expected': True if video.get('channel_layout') in ('mono', 'stereo', '2.0', '5.1', '7.1') else None, 'collected_at': datetime.now(timezone.utc).isoformat()},
              'subtitles': [], 'formats': [], 'diagnostics': []}
    if 'transcript' in needs:
        result['subtitles'] = [{'url': urljoin(player, track['url']), 'ext': 'vtt',
                                'language': track.get('lang'), 'origin': 'platform_unknown'}
                               for track in request.get('text_tracks') or [] if track.get('url')]
        if not result['subtitles']:
            result['diagnostics'].append(diagnostic('transcript', Failure('subtitle_absent', 'Vimeo player exposes no subtitle tracks.', 'Use local ASR.')))
    if needs.intersection(('video', 'audio', 'frames', 'media')):
        files = video.get('files') or request.get('files') or {}
        headers = {'Referer': player + query}
        for f in files.get('progressive') or []:
            if f.get('url'):
                result['formats'].append({'url': f['url'], 'ext': 'mp4', 'width': f.get('width'),
                    'height': f.get('height'), 'fps': media.frame_rate(f.get('fps')), 'bitrate': f.get('bitrate'),
                    'has_video': True, 'has_audio': None, 'headers': headers})
        hls = files.get('hls') or {}
        cdns = hls.get('cdns') or {}
        cdn = cdns.get(hls.get('default_cdn')) or next(iter(cdns.values()), {})
        address = cdn.get('url')
        if address and '/drm/' in urlsplit(address).path:
            result['diagnostics'].append(diagnostic('media', Failure('encrypted_stream_unsupported', 'Vimeo exposes DRM-protected HLS; encrypted streams are unsupported.')))
            address = None
        if address:
            # Preserve the API's signed URL. Separate HLS audio groups are
            # supported by the shared parser and must stay paired with video.
            try:
                if __package__ == 'scripts.platforms':
                    from ..streams import _fetch, hls_formats
                else:
                    from streams import _fetch, hls_formats
                final, text = _fetch(address, cookies, headers)
                formats, _ = hls_formats(text, final, headers=headers, include_audio='frames' not in needs or bool(needs.intersection(('video', 'audio', 'transcript'))))
                result['formats'].extend(formats)
            except Failure as exc:
                result['diagnostics'].append(diagnostic('media', exc))
        if not result['formats']:
            result['diagnostics'].append(diagnostic('media', Failure('media_unavailable', 'Vimeo exposes no supported progressive or HLS streams.', 'DASH and protected streams are unsupported.')))
        result['metadata']['audio_expected'] = result['metadata']['audio_expected'] or (True if any(f.get('has_audio') is True for f in result['formats']) else None)
    return result
