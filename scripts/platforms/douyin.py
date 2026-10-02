"""Douyin single-work extraction, with an isolated anonymous Chrome context.

Media field research: yt-dlp's Unlicense Douyin/TikTok extractor. Browser
acquisition and parsing are implemented here; no external downloader is run.
"""
import base64
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time
from urllib.parse import parse_qs, unquote, urlsplit
from urllib.request import ProxyHandler, build_opener
from . import Failure, diagnostic, read_text, request


def _find(data, identifier):
    if isinstance(data, dict):
        if str(data.get('aweme_id') or data.get('awemeId')) == identifier and isinstance(data.get('video'), dict):
            return data
        for value in data.values():
            result = _find(value, identifier)
            if result:
                return result
    elif isinstance(data, list):
        for value in data:
            result = _find(value, identifier)
            if result:
                return result
    return None


def _embedded(page):
    match = re.search(r'<script\b[^>]*\bid=[\"\']RENDER_DATA[\"\'][^>]*>(.*?)</script>', page, re.S)
    if match:
        try:
            return json.loads(unquote(html.unescape(match[1])))
        except ValueError:
            raise Failure('parse_failed', 'Douyin returned malformed embedded work data.') from None
    size = len(page.encode('utf-8'))
    if 'byted_acrawler' in page and '__ac_signature' in page:
        raise Failure('player_challenge_unsupported',
                      f'Douyin returned a JavaScript signature challenge ({size} response bytes), not work data.',
                      'This anonymous path is limited; provide a local media file or your own Cookie file.')
    raise Failure('experimental_access_limited',
                  f'Douyin exposed no readable single-work data ({size} response bytes).',
                  'Retry later or provide a local media file.')


def _identifier(url, cookies=None):
    """Normalize a video page, modal or platform share redirect to one work."""
    parsed = urlsplit(url)
    if parsed.hostname == 'v.douyin.com':
        with request(url, cookies=cookies) as response:
            url = response.geturl()
        parsed = urlsplit(url)
        host = parsed.hostname or ''
        if not (host == 'douyin.com' or host.endswith('.douyin.com')
                or host in ('iesdouyin.com', 'www.iesdouyin.com')):
            raise Failure('invalid_url', 'Douyin short link redirected outside Douyin.')
    match = re.fullmatch(r'/(?:video|share/video)/(\d+)/?', parsed.path)
    modal = parse_qs(parsed.query).get('modal_id', [])
    identifiers = set(([match[1]] if match else []) + modal)
    if len(identifiers) != 1 or not re.fullmatch(r'\d+', next(iter(identifiers), '')):
        raise Failure('invalid_url', 'A Douyin single-video URL is required.')
    return identifiers.pop()


def _browser_item(identifier, cookies=None):
    """Read the platform's own detail response in a disposable browser profile."""
    import websocket
    candidates = [shutil.which(name) for name in ('google-chrome', 'chromium', 'chromium-browser')]
    candidates += ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome']
    for base in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA'):
        if os.environ.get(base):
            candidates.append(str(Path(os.environ[base]) / 'Google/Chrome/Application/chrome.exe'))
    browser = next((path for path in candidates if path and Path(path).is_file()), None)
    if not browser:
        raise Failure('dependency_missing', 'Douyin verification needs Chrome or Chromium.', 'See INSTALL.md for Douyin setup.')
    canonical = 'https://www.douyin.com/video/' + identifier
    with tempfile.TemporaryDirectory(prefix='agent-video-browser-', ignore_cleanup_errors=True) as temporary:
        profile = Path(temporary)
        try:
            process = subprocess.Popen([browser, '--headless=new', '--no-first-run', '--no-default-browser-check',
                '--disable-extensions', '--autoplay-policy=user-gesture-required', '--remote-debugging-address=127.0.0.1',
                '--remote-debugging-port=0', '--user-data-dir=' + str(profile), 'about:blank'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            raise Failure('browser_failed', 'Chrome could not start its isolated video-reading context.') from None
        socket = None
        sequence = 0
        def send(method, params=None):
            nonlocal sequence
            sequence += 1
            socket.send(json.dumps({'id': sequence, 'method': method, 'params': params or {}}))
            return sequence
        try:
            port_file = profile / 'DevToolsActivePort'
            deadline = time.monotonic() + 8
            while not port_file.is_file() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(.1)
            if not port_file.is_file():
                raise Failure('browser_failed', 'Chrome did not start its isolated video-reading context.')
            port = int(port_file.read_text().splitlines()[0])
            # Local browser control must not pass through the user's HTTP proxy.
            with build_opener(ProxyHandler({})).open(f'http://127.0.0.1:{port}/json/list', timeout=3) as response:
                tabs = json.load(response)
            address = next(tab['webSocketDebuggerUrl'] for tab in tabs if tab.get('type') == 'page')
            socket = websocket.create_connection(address, timeout=.5, suppress_origin=True,
                                                 http_no_proxy=['127.0.0.1', 'localhost'])
            send('Network.enable')
            # The browser only reads work data; media is downloaded by our shared code.
            send('Network.setBlockedURLs', {'urls': ['*://*.douyinvod.com/*', '*://*.douyinvod2.com/*',
                                                     '*://*.douyinvod3.com/*']})
            if cookies:
                from . import _opener
                jar = next(handler.cookiejar for handler in _opener(cookies).handlers if hasattr(handler, 'cookiejar'))
                supplied = [{'name': c.name, 'value': c.value, 'domain': c.domain, 'path': c.path, 'secure': c.secure,
                             **({'expires': c.expires} if c.expires else {})}
                            for c in jar if c.domain.lstrip('.') in ('douyin.com', 'www.douyin.com')]
                if supplied:
                    send('Network.setCookies', {'cookies': supplied})
            send('Page.navigate', {'url': canonical})
            requests, bodies = set(), set()
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                try:
                    message = json.loads(socket.recv())
                except websocket.WebSocketTimeoutException:
                    continue
                params = message.get('params') or {}
                if message.get('method') == 'Network.responseReceived':
                    url = urlsplit(params['response']['url'])
                    if (url.hostname == 'www.douyin.com' and url.path == '/aweme/v1/web/aweme/detail/'
                            and parse_qs(url.query).get('aweme_id') == [identifier]):
                        requests.add(params['requestId'])
                elif message.get('method') == 'Network.loadingFinished' and params['requestId'] in requests:
                    bodies.add(send('Network.getResponseBody', {'requestId': params['requestId']}))
                elif message.get('id') in bodies and 'result' in message:
                    result = message['result']
                    body = base64.b64decode(result['body']).decode() if result.get('base64Encoded') else result['body']
                    try:
                        item = json.loads(body).get('aweme_detail')
                    except (ValueError, AttributeError):
                        continue
                    if isinstance(item, dict) and str(item.get('aweme_id')) == identifier:
                        return item
            raise Failure('experimental_access_limited', 'Douyin did not return the requested work in the anonymous browser context.',
                          'The site may require interactive verification; no login or CAPTCHA solving was attempted.')
        except (OSError, ValueError, StopIteration, websocket.WebSocketException):
            raise Failure('browser_failed', 'The isolated Chrome video-reading context failed.', 'Check Chrome installation and connectivity.') from None
        finally:
            if socket:
                try:
                    send('Browser.close')
                except (OSError, websocket.WebSocketException):
                    pass
                try:
                    socket.close()
                except (OSError, websocket.WebSocketException):
                    pass
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    if os.name == 'posix':
                        os.killpg(process.pid, signal.SIGTERM)
                    else:
                        process.terminate()
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    try:
                        if os.name == 'posix':
                            os.killpg(process.pid, signal.SIGKILL)
                        else:
                            process.kill()
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=3)


def _formats(video, canonical):
    formats, seen = [], set()
    streams = [stream for stream in video.get('bit_rate') or []
               if stream.get('format') in (None, 'mp4') and not stream.get('is_bytevc2')
               and stream.get('is_bytevc1') in (None, 0, 1)]
    streams += [{'play_addr': video.get(key) or {}} for key in ('play_addr', 'play_addr_h264', 'play_addr_265', 'playAddr')]
    for stream in streams:
        address = stream.get('play_addr') or {}
        for url in address.get('url_list') or address.get('urlList') or []:
            if not isinstance(url, str) or not url.startswith('https://') or url in seen:
                continue
            seen.add(url)
            formats.append({'url': url, 'ext': 'mp4', 'width': address.get('width') or video.get('width'),
                            'height': address.get('height') or video.get('height'),
                            'fps': stream.get('FPS'), 'bitrate': stream.get('bit_rate'),
                            'has_video': True, 'has_audio': True, 'headers': {'Referer': canonical}})
    return formats


def resolve(url, *, part=None, cookies=None, need=None):
    if part is not None:
        raise Failure('invalid_part', '--part only applies to Bilibili.')
    identifier = _identifier(url, cookies)
    canonical = 'https://www.douyin.com/video/' + identifier
    page = read_text(canonical, cookies=cookies)
    try:
        item = _find(_embedded(page), identifier)
    except Failure as exc:
        if exc.code != 'player_challenge_unsupported':
            raise
        item = _browser_item(identifier, cookies=cookies)
    if (not isinstance(item, dict) or str(item.get('aweme_id') or item.get('awemeId')) != identifier
            or not isinstance(item.get('video'), dict)):
        raise Failure('parse_failed', 'Douyin embedded data does not identify the requested single video.',
                      'Check the video URL or provide a local media file.')
    if item.get('images') or item.get('aweme_type') in (2, 68):
        raise Failure('unsupported_content', 'Douyin image posts are not supported; a video work is required.')
    video = item['video']
    author = item.get('author') or {}
    needs = set(need or ('info', 'transcript', 'video'))
    available = _formats(video, canonical)
    formats = available if needs & {'video', 'audio', 'frames', 'media'} else []
    return {'source': {'platform': 'douyin', 'id': identifier, 'url': canonical},
            'metadata': {'platform': 'douyin', 'id': identifier, 'url': canonical, 'title': item.get('desc'),
                         'description': item.get('desc'), 'author': author.get('nickname'),
                         'duration': video.get('duration') / 1000 if video.get('duration') is not None else None, 'published_at': item.get('create_time'),
                         'experimental': True, 'audio_expected': True if available else None, 'collected_at': datetime.now(timezone.utc).isoformat()},
            'subtitles': [], 'formats': formats,
            'diagnostics': [diagnostic('transcript', Failure('subtitle_failed', 'The experimental Douyin page path cannot establish subtitle availability.', 'Use local ASR.'))] if not need or 'transcript' in need else []}
