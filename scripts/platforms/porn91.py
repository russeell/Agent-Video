"""Public 91porn single works, without guest-limit or authentication bypass.

Player encoding researched from wmrussell8653/yt-dlp-plugin-yellow,
commit 485f1aa607cc7914ce80b63eadc3ba126ceec1f6 (Unlicense/public domain).
Independently parsed HTML and percent-encoded data; no JavaScript evaluation.
"""
from datetime import datetime, timezone
from html.parser import HTMLParser
import re
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlsplit
from . import Failure, diagnostic, read_text


def _identity(url):
    try:
        parsed = urlsplit(url)
        values = parse_qs(parsed.query).get('viewkey', [])
        if (parsed.scheme in ('http', 'https') and parsed.hostname in ('91porn.com', 'www.91porn.com', 'up.91splt.app')
                and not parsed.username and not parsed.password and parsed.port in (None, 80, 443)
                and parsed.path == '/view_video.php' and len(values) == 1
                and re.fullmatch(r'[A-Za-z0-9_]{1,100}', values[0])):
            return values[0]
    except ValueError:
        pass
    return None


class _Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta, self.links, self.sources, self.tracks, self.title = {}, [], [], [], []
        self.in_title = self.in_video = self.has_player = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta':
            self.meta[attrs.get('property') or attrs.get('name')] = attrs.get('content')
        elif tag == 'a' and attrs.get('href'):
            self.links.append(attrs['href'])
        elif tag == 'link' and attrs.get('rel') == 'canonical' and attrs.get('href'):
            self.meta['canonical'] = attrs['href']
        elif tag == 'title':
            self.in_title = True
        elif tag == 'video':
            self.in_video = attrs.get('id') == 'player_one'
            self.has_player |= self.in_video
            if self.in_video and attrs.get('src'):
                self.sources.append(attrs['src'])
        elif tag == 'source' and self.in_video and attrs.get('src'):
            self.sources.append(attrs['src'])
        elif tag == 'track' and self.in_video and attrs.get('kind') in ('captions', 'subtitles'):
            self.tracks.append(attrs)

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False
        elif tag == 'video':
            self.in_video = False

    def handle_data(self, value):
        if self.in_title:
            self.title.append(value)


def _address(value, canonical):
    try:
        address = urljoin(canonical, value)
        parsed = urlsplit(address)
        parsed.port
        return address if parsed.scheme in ('http', 'https') and parsed.hostname and not parsed.username and not parsed.password else None
    except ValueError:
        return None


def resolve(url, *, part=None, cookies=None, need=None):
    if part is not None:
        raise Failure('invalid_part', '--part only applies to Bilibili.')
    identifier = _identity(url)
    if not identifier:
        raise Failure('invalid_url', 'A 91porn single-video viewkey URL is required.')
    host = urlsplit(url).hostname
    origin = 'https://' + (host if host == 'up.91splt.app' else '91porn.com')
    canonical = origin + '/view_video.php?' + urlencode({'viewkey': identifier})
    text = read_text(canonical, cookies=cookies, headers={'Referer': origin + '/'})
    if len(text) > 2000000:
        raise Failure('parse_failed', '91porn page exceeds the static parsing limit.')
    if re.search(r'视频不存在|视频已被删除|Video (?:does not exist|has been deleted)', text, re.I):
        raise Failure('media_unavailable', '91porn reports this work was removed or does not exist.')
    if re.search(r'作为游客[，,]\s*你每天只可观看|daily (?:viewing )?limit (?:reached|exceeded)', text, re.I):
        raise Failure('auth_required', '91porn reports the anonymous viewing limit was reached.',
                      'Provide an explicitly exported authorized Cookie file or local media.')
    page = _Page()
    page.feed(text)
    declared = [page.meta[key] for key in ('canonical', 'og:url') if page.meta.get(key)]
    work_links = [urljoin(canonical, value) for value in page.links
                  if parse_qs(urlsplit(value).query).get('action') == ['comment']]
    if (declared and any(_identity(urljoin(canonical, value)) != identifier for value in declared)
            or not declared and not (page.has_player and any(_identity(value) == identifier for value in work_links))):
        raise Failure('parse_failed', '91porn page does not confirm the requested work identity.')
    title = page.meta.get('og:title') or ''.join(page.title).strip()
    if not title:
        raise Failure('parse_failed', '91porn exposes no readable work metadata.')
    title = re.sub(r'\s*(?:-\s*)?Chinese homemade video\s*$', '', title, flags=re.I).strip()
    span = re.search(r'(?:时长|Duration)\s*[:：]\s*(?:<[^>]*>\s*)*(\d+(?::\d+){1,2})', text, re.I)
    duration = None
    if span:
        duration = 0
        for value in span[1].split(':'):
            duration = duration * 60 + int(value)
    else:
        # Current pages declare the work length independently of the CDN file.
        # Retain it so shared download validation rejects substituted short clips.
        declared_duration = re.search(r'\b(?:const|let|var)\s+videoDuration\s*=\s*(\d+(?:\.\d+)?)\s*;', text)
        if declared_duration:
            duration = float(declared_duration[1])
    result = {'source': {'platform': '91porn', 'id': identifier, 'url': canonical},
              'metadata': {'platform': '91porn', 'id': identifier, 'url': canonical, 'title': title,
                           'description': page.meta.get('og:description') or page.meta.get('description'),
                           'duration': duration, 'original_language': None, 'audio_expected': None,
                           'collected_at': datetime.now(timezone.utc).isoformat()},
              'subtitles': [], 'formats': [], 'diagnostics': []}
    needs = set(need or ('info', 'transcript', 'video'))
    headers = {'Referer': canonical}
    if 'transcript' in needs:
        for track in page.tracks:
            address = _address(track.get('src') or '', canonical)
            ext = urlsplit(address).path.rsplit('.', 1)[-1].lower() if address else ''
            if ext in ('vtt', 'srt'):
                result['subtitles'].append({'url': address, 'ext': ext, 'language': track.get('srclang') or '',
                                             'origin': 'platform_unknown', 'headers': headers})
        if not result['subtitles']:
            result['diagnostics'].append(diagnostic('transcript', Failure('subtitle_absent',
                '91porn exposes no supported caption tracks.', 'Use local ASR.')))
    if needs.intersection(('video', 'audio', 'frames', 'media')):
        addresses = list(page.sources)
        for match in re.finditer(r'''document\.write\(\s*strencode2\(\s*(["'])([^"']+)\1\s*\)\s*\)''', text):
            fragment = _Page()
            # The player emits a literal <source>, not an executable script.
            fragment.feed('<video id="player_one">' + unquote(match[2]) + '</video>')
            addresses.extend(fragment.sources)
        seen = set()
        for value in addresses:
            address = _address(value, canonical)
            if not address or address in seen:
                continue
            seen.add(address)
            ext = urlsplit(address).path.rsplit('.', 1)[-1].lower()
            if ext in ('mp4', 'webm'):
                result['formats'].append({'url': address, 'ext': ext, 'has_video': True,
                                          'has_audio': None, 'headers': headers})
            elif ext == 'm3u8':
                if __package__ == 'scripts.platforms':
                    from ..streams import _fetch, _playlist, hls_formats
                else:
                    from streams import _fetch, _playlist, hls_formats
                try:
                    final, playlist = _fetch(address, cookies, headers)
                    formats, _ = hls_formats(playlist, final, headers=headers,
                        include_audio='frames' not in needs or bool(needs.intersection(('video', 'audio', 'transcript'))))
                    if not formats:
                        parsed, _ = _playlist(playlist, final)
                        formats = parsed if isinstance(parsed, list) else [
                            {'url': final, 'ext': 'm3u8', 'protocol': 'hls', 'has_video': True, 'has_audio': None}]
                        for candidate in formats:
                            candidate['headers'] = headers
                    result['formats'].extend(formats)
                except Failure as exc:
                    result['diagnostics'].append(diagnostic('media', exc))
        if not result['formats'] and not any(d['stage'] == 'media' for d in result['diagnostics']):
            result['diagnostics'].append(diagnostic('media', Failure('media_unavailable',
                '91porn exposes no supported public video resource.')))
    return result
