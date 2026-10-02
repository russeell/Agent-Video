import http.server
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import platforms
from platforms import bilibili, youtube, tiktok


class PlatformsTest(unittest.TestCase):
    def test_subtitle_language_and_origin(self):
        tracks = [{'url': 'a', 'language': 'en', 'origin': 'platform_auto'},
                  {'url': 'b', 'language': 'en', 'origin': 'platform_manual'},
                  {'url': 'c', 'language': 'zh', 'origin': 'platform_manual'},
                  {'url': 'd', 'language': 'live_chat', 'origin': 'platform_manual'}]
        self.assertEqual(platforms.select_subtitle(tracks, 'en')['url'], 'b')
        with self.assertRaises(platforms.Failure) as caught:
            platforms.select_subtitle(tracks)
        self.assertEqual(caught.exception.code, 'subtitle_ambiguous')
        self.assertIsNone(platforms.select_subtitle([tracks[-1]]))

    def test_quality_and_required_audio(self):
        tracks = [{'url': str(w), 'width': w, 'height': h, 'has_video': True, 'has_audio': False}
                  for w, h in [(640, 360), (1280, 720), (1920, 1080), (3840, 2160)]]
        tracks += [{'url': 'audio', 'has_video': False, 'has_audio': True}]
        self.assertEqual([f['url'] for f in platforms.select_formats(tracks)], ['1920', 'audio'])
        self.assertEqual(platforms.select_formats(tracks, quality='source')[0]['width'], 3840)
        self.assertEqual(platforms.select_formats(tracks, want_video='frames', width=768)[0]['width'], 1280)
        self.assertEqual(platforms.select_formats(tracks, want_video=False)[0]['url'], 'audio')
        portrait = [{'url': 'p', 'width': 1080, 'height': 1920, 'has_video': True, 'has_audio': True}]
        self.assertEqual(platforms.select_formats(portrait)[0]['url'], 'p')

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

    def test_bilibili_part_and_normalization(self):
        view = {'bvid': 'BVexample', 'title': 'Parent', 'owner': {'name': 'Author'},
                'pages': [{'page': 1, 'cid': 7, 'part': 'One', 'duration': 90},
                          {'page': 2, 'cid': 8, 'part': 'Two', 'duration': 30}]}
        with patch.object(bilibili, '_api', return_value=view):
            r = bilibili.resolve('https://www.bilibili.com/video/BVexample?p=2', need=['info'])
            self.assertEqual(r['source']['cid'], 8)
            self.assertEqual(r['metadata']['duration'], 30)
            self.assertIsNone(r['metadata']['view_count'])
        with self.assertRaises(platforms.Failure):
            bilibili.resolve('https://www.bilibili.com/video/BVexample?p=2', part=1)

    def test_embedded_public_data(self):
        data = {'videoDetails': {'videoId': 'abcdefghijk', 'title': 'Video'}}
        self.assertEqual(youtube._player('ytInitialPlayerResponse = ' + json.dumps(data) + ';'), data)
        item = {'id': '123', 'video': {'duration': 7}}
        html = '<script id="SIGI_STATE">' + json.dumps({'ItemModule': {'123': item}}) + '</script>'
        self.assertEqual(tiktok._item(tiktok._embedded(html), '123'), item)


if __name__ == '__main__':
    unittest.main()
