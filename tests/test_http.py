"""Shared HTTP transport, retries and credential boundaries; local servers only."""
import http.server
import io
import json
import tempfile
import threading
from unittest.mock import MagicMock, patch
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import platforms


class HTTPTests(unittest.TestCase):
    def test_json_post_preserves_body_and_header_boundaries(self):
        observed = []
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers['Content-Length']))
                observed.append((json.loads(body), self.headers.get('Content-Type'),
                                 self.headers.get('Authorization'), self.headers.get('Cookie')))
                payload = b'{"ok":true}'
                self.send_response(200)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            def log_message(self, *args):
                pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f'http://127.0.0.1:{server.server_port}/player'
            result = platforms.read_json(url, data=json.dumps({'videoId': 'test'}).encode(),
                                         headers={'Content-Type': 'application/json',
                                                  'Authorization': 'secret', 'Cookie': 'secret'})
            self.assertEqual(result, {'ok': True})
            self.assertEqual(observed, [({'videoId': 'test'}, 'application/json', None, None)])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_http_cookie_domain_and_atomic_download(self):
        observed = []
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                observed.append(self.headers.get('Cookie', ''))
                if self.path == '/redirect':
                    self.send_response(302)
                    self.send_header('Location', f'http://localhost:{self.server.server_port}/file')
                    self.end_headers()
                    return
                payload = b'{"ok":true}'
                self.send_response(200)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            def log_message(self, *args):
                pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                directory = Path(directory)
                cookie = directory / 'cookies.txt'
                cookie.write_text('# Netscape HTTP Cookie File\n127.0.0.1\tFALSE\t/\tFALSE\t2147483647\tsession\tsecret\n')
                root = f'http://127.0.0.1:{server.server_port}'
                self.assertTrue(platforms.read_json(root + '/file', cookies=cookie)['ok'])
                path = platforms.download_file(root + '/redirect', directory / 'file.json', cookies=cookie)
                self.assertEqual(json.loads(path.read_text()), {'ok': True})
                self.assertIn('session=secret', observed[0])
                self.assertIn('session=secret', observed[1])
                self.assertEqual(observed[2], '')
                self.assertFalse(list(directory.glob('*.part')))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_http_download_retries_whole_response_at_most_three_times(self):
        calls = {}
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                calls[self.path] = calls.get(self.path, 0) + 1
                status = {'/down': 503, '/denied': 403, '/missing': 404}.get(self.path, 200)
                self.send_response(status)
                self.send_header('Content-Length', '4')
                self.end_headers()
                if self.path == '/permanent' or (self.path == '/short' and calls[self.path] == 1):
                    self.wfile.write(b'ab')
                elif self.path != '/empty' or calls[self.path] > 1:
                    self.wfile.write(b'abcd')
                self.close_connection = True
            def log_message(self, *args):
                pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory, patch.object(platforms.time, 'sleep'):
                directory = Path(directory)
                root = f'http://127.0.0.1:{server.server_port}'
                for route in ('/short', '/empty'):
                    path = platforms.download_file(root + route, directory / route[1:])
                    self.assertEqual(path.read_bytes(), b'abcd')
                    self.assertEqual(calls[route], 2)
                for route, code, count in [('/permanent', 'download_incomplete', 3),
                                           ('/down', 'network_failed', 3),
                                           ('/denied', 'access_denied', 1),
                                           ('/missing', 'network_failed', 1)]:
                    with self.subTest(route=route), self.assertRaises(platforms.Failure) as caught:
                        platforms.download_file(root + route, directory / route[1:])
                    self.assertEqual(caught.exception.code, code)
                    self.assertEqual(calls[route], count)
                    self.assertFalse((directory / route[1:]).exists())
                self.assertFalse(list(directory.glob('.*.part')))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_http_download_read_failure_restarts_and_disk_failure_does_not_retry(self):
        class Response(io.BytesIO):
            headers = {'Content-Length': '4'}
        broken = Response(b'ab')
        broken.read = MagicMock(side_effect=[b'ab', ConnectionResetError('connection reset')])
        with tempfile.TemporaryDirectory() as directory, patch.object(platforms.time, 'sleep'):
            path = Path(directory) / 'media'
            with patch.object(platforms, 'request', side_effect=[broken, Response(b'abcd')]) as request:
                self.assertEqual(platforms.download_file('https://example.test/media', path), path)
                self.assertEqual(path.read_bytes(), b'abcd')
                self.assertEqual(request.call_count, 2)
                self.assertTrue(all(call.kwargs['attempts'] == 1 for call in request.call_args_list))
            handle = MagicMock()
            handle.__enter__.return_value = handle
            handle.write.side_effect = OSError('disk full')
            with patch.object(platforms, 'request', return_value=Response(b'abcd')) as request, \
                    patch.object(Path, 'open', return_value=handle):
                with self.assertRaises(platforms.Failure) as caught:
                    platforms.download_file('https://example.test/media', path)
                self.assertEqual(caught.exception.code, 'download_failed')
                self.assertEqual(request.call_count, 1)
            self.assertEqual(path.read_bytes(), b'abcd')
            self.assertFalse(list(Path(directory).glob('.*.part')))

if __name__ == '__main__':
    unittest.main()
