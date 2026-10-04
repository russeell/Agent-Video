"""Read a public platform page using a disposable, anonymous Chrome profile."""
import base64
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener

if __package__:
    from .media import Failure
else:
    from media import Failure


def browser_page(url, *, ready=None):
    # This is a platform helper, not a generic website fallback or a user session.
    parsed = urlsplit(url)
    instagram = (parsed.netloc == 'www.instagram.com' and
                 re.fullmatch(r'/(?:p|reel|reels|tv)/[A-Za-z0-9_-]+/?', parsed.path))
    ixigua = (parsed.netloc in ('www.ixigua.com', 'm.ixigua.com') and
              re.fullmatch(r'/(?:video/)?\d{10,25}/?', parsed.path))
    if parsed.scheme not in ('http', 'https') or not (instagram or ixigua):
        raise Failure('invalid_url', 'The anonymous page reader requires a supported platform work URL.')
    platform = 'Instagram' if instagram else 'Ixigua'
    def accepts(address):
        location = urlsplit(address)
        if instagram:
            return location.scheme in ('http', 'https') and location.netloc == 'www.instagram.com'
        return (location.scheme in ('http', 'https') and location.netloc in ('www.ixigua.com', 'm.ixigua.com')
                and re.fullmatch(r'/(?:video/)?\d{10,25}/?', location.path)
                and location.path.rstrip('/').split('/')[-1] == parsed.path.rstrip('/').split('/')[-1])
    candidates = [shutil.which(name) for name in ('google-chrome', 'chromium', 'chromium-browser')]
    candidates.append('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
    for base in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA'):
        if os.environ.get(base):
            candidates.append(str(Path(os.environ[base]) / 'Google/Chrome/Application/chrome.exe'))
    browser = next((p for p in candidates if p and Path(p).is_file()), None)
    if not browser:
        raise Failure('dependency_missing', platform + ' page verification needs Chrome or Chromium.',
                      'Install Chrome or Chromium, then retry this public video.')
    import websocket
    with tempfile.TemporaryDirectory(prefix='agent-video-page-', ignore_cleanup_errors=True) as temporary:
        process, socket = None, None
        try:
            process = subprocess.Popen([browser, '--headless=new', '--no-first-run',
                '--disable-extensions', '--remote-debugging-address=127.0.0.1',
                '--remote-debugging-port=0', '--user-data-dir=' + temporary, 'about:blank'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            port_file = Path(temporary) / 'DevToolsActivePort'
            deadline = time.monotonic() + 8
            while not port_file.is_file() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(.1)
            if not port_file.is_file():
                raise Failure('browser_failed', 'Chrome did not start its isolated page-reading context.')
            port = int(port_file.read_text().splitlines()[0])
            with build_opener(ProxyHandler({})).open(f'http://127.0.0.1:{port}/json/list', timeout=3) as response:
                tabs = json.load(response)
            address = next(tab['webSocketDebuggerUrl'] for tab in tabs if tab.get('type') == 'page')
            socket = websocket.create_connection(address, timeout=.5, suppress_origin=True,
                                                 http_no_proxy=['127.0.0.1', 'localhost'])
            socket.send(json.dumps({'id': 1, 'method': 'Network.enable'}))
            socket.send(json.dumps({'id': 2, 'method': 'Network.setBlockedURLs', 'params': {
                'urls': ['*.mp4*', '*.webm*', '*.m3u8*', '*.mpd*']}}))
            socket.send(json.dumps({'id': 3, 'method': 'Page.navigate', 'params': {'url': url}}))
            sequence, pending, next_read = 3, None, 0
            documents, bodies = set(), set()
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                if pending is None and time.monotonic() >= next_read:
                    sequence += 1
                    pending = sequence
                    socket.send(json.dumps({'id': sequence, 'method': 'Runtime.evaluate', 'params': {
                        'expression': 'JSON.stringify({url:location.href,html:document.documentElement.outerHTML})',
                        'returnByValue': True}}))
                try:
                    message = json.loads(socket.recv())
                except websocket.WebSocketTimeoutException:
                    continue
                params = message.get('params') or {}
                if message.get('method') == 'Network.responseReceived' and params.get('type') == 'Document':
                    response_url = (params.get('response') or {}).get('url') or ''
                    if not accepts(response_url):
                        raise Failure('invalid_url', platform + ' page redirected outside the requested work.')
                    documents.add(params['requestId'])
                elif message.get('method') == 'Network.loadingFinished' and params.get('requestId') in documents:
                    # A blocked player can repeatedly retry media and keep its
                    # renderer busy. Read the complete browser document through
                    # the network process as well as the hydrated DOM.
                    sequence += 1
                    bodies.add(sequence)
                    socket.send(json.dumps({'id': sequence, 'method': 'Network.getResponseBody',
                                            'params': {'requestId': params['requestId']}}))
                elif message.get('id') in bodies:
                    result = message.get('result') or {}
                    page = result.get('body') or ''
                    if result.get('base64Encoded'):
                        page = base64.b64decode(page).decode('utf-8', errors='replace')
                    if page and (ready(page) if ready else 'video_versions' in page):
                        return page
                if message.get('id') != pending:
                    continue
                pending, next_read = None, time.monotonic() + .5
                value = ((message.get('result') or {}).get('result') or {}).get('value')
                if not isinstance(value, str):
                    continue
                state = json.loads(value)
                current = state.get('url') or ''
                host = urlsplit(current).hostname
                if host and not accepts(current):
                    raise Failure('invalid_url', platform + ' page redirected outside the requested work.')
                page = state.get('html') or ''
                if accepts(current) and page and (ready(page) if ready else 'video_versions' in page):
                    return page
            raise Failure('experimental_access_limited', platform + ' exposed no requested media in its anonymous browser context.',
                          'The page may require login or verification; provide your own Cookie file or local media.')
        except (OSError, ValueError, StopIteration, websocket.WebSocketException):
            raise Failure('browser_failed', 'The isolated Chrome page-reading context failed.') from None
        finally:
            if socket:
                try:
                    socket.close()
                except websocket.WebSocketException:
                    pass
            if process is not None and process.poll() is None:
                try:
                    if os.name == 'posix':
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                except ProcessLookupError:
                    pass
                process.wait(timeout=3)
