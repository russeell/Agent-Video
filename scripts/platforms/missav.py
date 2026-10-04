"""Single public MissAV works; native static player parsing, never JavaScript execution.

Player schema researched from smalltownjj/yt-dlp-plugin-missav at
f25a30b76c03d79c81d7adcc30d97808680e4355 and
wmrussell8653/yt-dlp-plugin-yellow at 485f1aa607cc7914ce80b63eadc3ba126ceec1f6
(both Unlicense/public domain). Their positional URL construction is not used.
HTTP challenges, authentication and encrypted/DRM media are not bypassed.
"""
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import re
from urllib.parse import urljoin, urlsplit
from . import Failure, diagnostic, read_text


_HOSTS = ('missav.ws', 'www.missav.ws', 'missav.com', 'www.missav.com')
_LOCALES = ('en', 'ja', 'zh', 'cn', 'tw', 'zh-cn', 'zh-tw', 'ko', 'vi', 'ms', 'th', 'de', 'fr', 'ru', 'es', 'pt', 'cs')
_LITERAL = r'''(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')'''


def _identity(url):
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return None
    if (parsed.scheme not in ('http', 'https') or parsed.hostname not in _HOSTS
            or parsed.username or parsed.password or port not in (None, 80, 443)):
        return None
    match = re.fullmatch(r'/([a-z]{2}(?:-[a-z]{2})?)/([a-z0-9]+(?:-[a-z0-9]+)+)/?', parsed.path)
    return match[2] if match and match[1] in _LOCALES else None


def _string(literal):
    """Decode the string literal subset used by packer arguments, without eval."""
    if len(literal) > 512000 or len(literal) < 2 or literal[0] != literal[-1]:
        raise ValueError
    content = literal[1:-1]
    escapes = {'n': '\n', 'r': '\r', 't': '\t', 'b': '\b', 'f': '\f', 'v': '\v',
               '/': '/', '\\': '\\', "'": "'", '"': '"'}
    def replace(match):
        value = match[1]
        if value in escapes:
            return escapes[value]
        if value.startswith(('x', 'u')):
            return chr(int(value[1:], 16))
        # Do not accept JS line continuations or arbitrary unknown escapes.
        raise ValueError
    return re.sub(r'\\(x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|.)', replace, content, flags=re.S)


def _unpack(script):
    """Expand only the public packer's bounded dictionary substitution as data."""
    if len(script) > 512000:
        raise Failure('parse_failed', 'MissAV player script exceeds the static parsing limit.')
    if not re.search(r'eval\s*\(\s*function\s*\(\s*p\s*,\s*a\s*,\s*c\s*,\s*k\s*,\s*e\s*,\s*[rd]\s*\)', script):
        return script
    args = re.search(r'}\s*\(\s*(' + _LITERAL + r')\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(' + _LITERAL + r')\s*\.split\(\s*["\']\|["\']\s*\)', script, re.S)
    if not args:
        raise Failure('parse_failed', 'MissAV packed player arguments were not recognized.')
    try:
        radix, count = int(args[2]), int(args[3])
        if not 2 <= radix <= 62 or not 0 <= count <= 10000:
            raise ValueError
        payload, table = _string(args[1]), _string(args[4]).split('|')
        if len(table) != count:
            raise ValueError
        alphabet = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
        def substitute(match):
            value = 0
            for character in match[0]:
                digit = alphabet.find(character)
                if digit < 0 or digit >= radix:
                    return match[0]
                value = value * radix + digit
                if value >= count:
                    return match[0]
            return table[value] or match[0]
        return re.sub(r'\b[0-9A-Za-z]+\b', substitute, payload)
    except (ValueError, OverflowError):
        raise Failure('parse_failed', 'MissAV packed player dictionary was not recognized.') from None


class _Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta, self.canonical, self.sources, self.tracks, self.scripts = {}, None, [], [], []
        self.script_type, self.script_chunks = None, None
        self.in_video = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta':
            self.meta[attrs.get('property') or attrs.get('name')] = attrs.get('content')
        elif tag == 'link' and attrs.get('rel') == 'canonical':
            self.canonical = attrs.get('href')
        elif tag == 'video':
            self.in_video = True
            if attrs.get('src'):
                self.sources.append(attrs['src'])
        elif tag == 'source' and self.in_video and attrs.get('src'):
            self.sources.append(attrs['src'])
        elif tag == 'track' and self.in_video and attrs.get('kind') in ('captions', 'subtitles'):
            self.tracks.append(attrs)
        elif tag == 'script' and not attrs.get('src'):
            self.script_type, self.script_chunks = attrs.get('type'), []

    def handle_data(self, data):
        if self.script_chunks is not None:
            self.script_chunks.append(data)

    def handle_endtag(self, tag):
        if tag == 'video':
            self.in_video = False
        if tag == 'script' and self.script_chunks is not None:
            self.scripts.append((self.script_type, ''.join(self.script_chunks)))
            self.script_type, self.script_chunks = None, None


def _address(value, canonical):
    try:
        address = urljoin(canonical, value)
        parsed = urlsplit(address)
        parsed.port
    except ValueError:
        return None
    return address if parsed.scheme in ('http', 'https') and parsed.hostname and not parsed.username and not parsed.password else None


def resolve(url, *, part=None, cookies=None, need=None):
    if part is not None:
        raise Failure('invalid_part', '--part only applies to Bilibili.')
    try:
        identifier = _identity(url)
    except ValueError:
        identifier = None
    if not identifier:
        raise Failure('invalid_url', 'A supported MissAV locale and single-work URL is required.')
    parsed = urlsplit(url)
    canonical = 'https://' + parsed.hostname.removeprefix('www.') + parsed.path.rstrip('/')
    text = read_text(canonical, cookies=cookies)
    if len(text) > 2000000:
        raise Failure('parse_failed', 'MissAV page exceeds the static parsing limit.')
    page = _Page()
    page.feed(text)
    if re.search(r'challenge-platform|cf-chl-|g-recaptcha|h-captcha', text, re.I):
        raise Failure('page_unavailable', 'MissAV returned a web challenge; no work data was acquired.',
                      'Retry later or provide an explicitly exported Cookie file or local media.')
    declared = [value for value in (page.canonical, page.meta.get('og:url')) if value]
    if not declared or any(_identity(urljoin(canonical, value)) != identifier for value in declared):
        raise Failure('parse_failed', 'MissAV page does not confirm the requested single-work identity.')
    title = page.meta.get('og:title')
    if not title:
        raise Failure('parse_failed', 'MissAV page exposes no readable single-work metadata.')
    duration, published, author = None, None, None
    for script_type, script in page.scripts:
        if script_type != 'application/ld+json':
            continue
        try:
            value = json.loads(script)
            items = value if isinstance(value, list) else value.get('@graph', [value])
            for item in items:
                if not isinstance(item, dict) or item.get('@type') != 'VideoObject':
                    continue
                stated = item.get('url') or item.get('@id')
                if stated and _identity(urljoin(canonical, stated)) != identifier:
                    raise Failure('parse_failed', 'MissAV video metadata belongs to another work.')
                span = re.fullmatch(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?', item.get('duration') or '')
                if span:
                    duration = sum(float(n or 0) * factor for n, factor in zip(span.groups(), (3600, 60, 1)))
                published = item.get('uploadDate')
                owner = item.get('author')
                author = owner.get('name') if isinstance(owner, dict) else None
        except (ValueError, AttributeError, TypeError):
            continue
    needs = set(need or ('info', 'transcript', 'video'))
    result = {'source': {'platform': 'missav', 'id': identifier, 'url': canonical},
        'metadata': {'platform': 'missav', 'id': identifier, 'url': canonical,
            'title': title, 'description': page.meta.get('og:description'), 'duration': duration,
            'published_at': published, 'author': author, 'original_language': None, 'audio_expected': None,
            'collected_at': datetime.now(timezone.utc).isoformat()},
        'subtitles': [], 'formats': [], 'diagnostics': []}
    if 'transcript' in needs:
        for track in page.tracks:
            address = _address(track.get('src') or '', canonical)
            ext = urlsplit(address).path.rsplit('.', 1)[-1].lower() if address else ''
            if ext in ('vtt', 'srt'):
                result['subtitles'].append({'url': address, 'ext': ext, 'language': track.get('srclang') or '',
                    'origin': 'platform_unknown', 'headers': {'Referer': canonical}})
        if not result['subtitles']:
            result['diagnostics'].append(diagnostic('transcript', Failure('subtitle_unavailable',
                'MissAV page exposes no verified supported caption tracks; availability is unconfirmed.', 'Use local ASR.')))
    if needs.intersection(('video', 'audio', 'frames', 'media')):
        candidates = list(page.sources)
        for script_type, script in page.scripts:
            if script_type == 'application/ld+json':
                continue
            try:
                unpacked = _unpack(script)
                for match in re.finditer(r'\bsource(?:\d+)?\s*=\s*(' + _LITERAL + ')', unpacked):
                    candidates.append(_string(match[1]))
            except (Failure, ValueError) as exc:
                result['diagnostics'].append(diagnostic('media', exc if isinstance(exc, Failure) else Failure('parse_failed', 'MissAV player resource literal was not recognized.')))
        seen = set()
        for value in candidates:
            address = _address(value, canonical)
            if not address or address in seen:
                continue
            seen.add(address)
            headers = {'Referer': canonical}
            ext = urlsplit(address).path.rsplit('.', 1)[-1].lower()
            if ext == 'm3u8':
                try:
                    if __package__ == 'scripts.platforms':
                        from ..streams import _fetch, _playlist, hls_formats
                    else:
                        from streams import _fetch, _playlist, hls_formats
                    final, playlist = _fetch(address, cookies, headers)
                    formats, _ = hls_formats(playlist, final, headers=headers,
                        include_audio='frames' not in needs or bool(needs.intersection(('video', 'audio', 'transcript'))))
                    if not formats:
                        parsed_playlist, _ = _playlist(playlist, final)
                        formats = parsed_playlist if isinstance(parsed_playlist, list) else [
                            {'url': final, 'ext': 'm3u8', 'protocol': 'hls', 'has_video': True, 'has_audio': None}]
                        for candidate in formats:
                            candidate['headers'] = headers
                    result['formats'].extend(formats)
                except Failure as exc:
                    result['diagnostics'].append(diagnostic('media', exc))
            elif ext in ('mp4', 'webm'):
                result['formats'].append({'url': address, 'ext': ext, 'has_video': True, 'has_audio': None, 'headers': headers})
        if not result['formats'] and not any(d['stage'] == 'media' for d in result['diagnostics']):
            result['diagnostics'].append(diagnostic('media', Failure('media_unavailable', 'MissAV page exposes no supported public player resources.')))
    return result
