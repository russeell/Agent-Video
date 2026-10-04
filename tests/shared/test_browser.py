"""Anonymous browser scope, CDP reads and cleanup without browser credentials."""
import io
import json
import unittest
from unittest.mock import MagicMock, patch
import websocket
from scripts import browser
from scripts.media import Failure


class BrowserTests(unittest.TestCase):
    def test_only_supported_single_work_without_embedded_credentials(self):
        for url in ('https://www.instagram.com.evil.test/p/ABC/', 'https://www.xiaohongshu.com/explore/ABC',
                    'https://www.instagram.com/accounts/login/', 'https://user:password@www.instagram.com/p/ABC/',
                    'https://www.instagram.com:8443/p/ABC/', 'https://www.instagram.com:badport/p/ABC/',
                    'https://www.ixigua.com/', 'https://user:pass@m.ixigua.com/video/7313122846971167258',
                    'https://m.ixigua.com.evil.test/video/7313122846971167258'):
            with self.assertRaises(Failure) as caught:
                browser.browser_page(url)
            self.assertEqual(caught.exception.code, 'invalid_url')

    def _read(self, messages, ready=None, url='https://www.instagram.com/reel/ABC/'):
        process = MagicMock(pid=123)
        process.poll.return_value = None
        socket = MagicMock()
        socket.recv.side_effect = messages
        response = MagicMock()
        response.__enter__.return_value = io.StringIO('[{"type":"page","webSocketDebuggerUrl":"ws://127.0.0.1:9222/devtools/page/test"}]')
        opener = MagicMock()
        opener.open.return_value = response
        with patch.object(browser.shutil, 'which', return_value='/test/chrome'), \
                patch.object(browser.Path, 'is_file', return_value=True), \
                patch.object(browser.Path, 'read_text', return_value='9222\n'), \
                patch.object(browser.subprocess, 'Popen', return_value=process) as launch, \
                patch.object(browser, 'build_opener', return_value=opener), \
                patch.object(websocket, 'create_connection', return_value=socket) as connect, \
                patch.object(browser.os, 'killpg', create=True) as kill:
            try:
                result = browser.browser_page(url, ready=ready)
            finally:
                if browser.os.name == 'posix':
                    kill.assert_called_once_with(123, browser.signal.SIGKILL)
                else:
                    process.kill.assert_called_once()
                socket.close.assert_called_once()
                process.wait.assert_called_once_with(timeout=3)
        return result, launch, connect, socket

    def test_ixigua_accepts_mobile_redirect_only_to_requested_work(self):
        source = 'https://www.ixigua.com/7313122846971167258'
        for identifier, expected in [('7313122846971167258', None), ('6963187000321147400', 'invalid_url')]:
            state = json.dumps({'url': 'https://m.ixigua.com/video/' + identifier + '?wid_try=1', 'html': '<html>_SSR_DATA</html>'})
            message = json.dumps({'id': 4, 'result': {'result': {'value': state}}})
            if expected:
                with self.assertRaises(Failure) as caught:
                    self._read([message], ready=lambda text: '_SSR_DATA' in text, url=source)
                self.assertEqual(caught.exception.code, expected)
            else:
                result, launch, _, _ = self._read([message], ready=lambda text: '_SSR_DATA' in text, url=source)
                self.assertIn('_SSR_DATA', result)
                self.assertTrue(any(flag.startswith('--user-data-dir=') for flag in launch.call_args.args[0]))

    def test_anonymous_cdp_reads_complete_matching_dom_and_closes(self):
        state = json.dumps({'url': 'https://www.instagram.com/reel/ABC/', 'html': '<html>matching media</html>'})
        message = json.dumps({'id': 4, 'result': {'result': {'value': state}}})
        result, launch, connect, socket = self._read([message], ready=lambda page: 'matching media' in page)
        self.assertEqual(result, '<html>matching media</html>')
        command = launch.call_args.args[0]
        self.assertIn('--headless=new', command)
        self.assertIn('--remote-debugging-address=127.0.0.1', command)
        self.assertTrue(any(flag.startswith('--user-data-dir=') for flag in command))
        self.assertFalse(any('cookie' in flag or 'dump-dom' in flag for flag in command))
        self.assertIn('127.0.0.1', connect.call_args.kwargs['http_no_proxy'])
        methods = [json.loads(c.args[0])['method'] for c in socket.send.call_args_list]
        self.assertEqual(methods, ['Network.enable', 'Network.setBlockedURLs', 'Page.navigate', 'Runtime.evaluate'])
        self.assertEqual(json.loads(socket.send.call_args_list[1].args[0])['params']['urls'],
                         ['*.mp4*', '*.webm*', '*.m3u8*', '*.mpd*'])

    def test_cross_site_redirect_and_socket_failure_clean_up(self):
        state = json.dumps({'url': 'https://example.test/', 'html': '<html>video_versions</html>'})
        message = json.dumps({'id': 4, 'result': {'result': {'value': state}}})
        for messages, code in [([message], 'invalid_url'), ([websocket.WebSocketException('closed')], 'browser_failed')]:
            with self.assertRaises(Failure) as caught:
                self._read(messages)
            self.assertEqual(caught.exception.code, code)

    def test_complete_network_document_when_renderer_is_busy(self):
        received = json.dumps({'method': 'Network.responseReceived', 'params': {
            'type': 'Document', 'requestId': 'document', 'response': {'url': 'https://www.instagram.com/reel/ABC/'}}})
        finished = json.dumps({'method': 'Network.loadingFinished', 'params': {'requestId': 'document'}})
        body = json.dumps({'id': 5, 'result': {'body': '<html>matching work</html>', 'base64Encoded': False}})
        result, _, _, socket = self._read([received, finished, body], ready=lambda page: 'matching work' in page)
        self.assertEqual(result, '<html>matching work</html>')
        self.assertEqual(json.loads(socket.send.call_args_list[-1].args[0])['method'], 'Network.getResponseBody')
