import http.server
import json
import re
from pathlib import Path
import sys
import tempfile
import threading
from functools import partial
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import platforms
from platforms import bilibili, youtube, tiktok, generic


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

    def test_generic_real_http_media_and_vod_hls(self):
        observed = []
        class Handler(http.server.SimpleHTTPRequestHandler):
            def do_GET(self):
                observed.append((self.path, self.headers.get('Cookie', '')))
                super().do_GET()
            def log_message(self, *args):
                pass
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            platforms.media.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
                '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10:duration=3',
                '-f', 'lavfi', '-i', 'sine=frequency=440:duration=3', '-c:v', 'mpeg4',
                '-g', '10', '-c:a', 'aac', '-shortest', directory / 'direct.mp4'])
            for name, extra in [('vod', []), ('fragmented', ['-hls_segment_type', 'fmp4'])]:
                platforms.media.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
                    '-i', directory / 'direct.mp4', '-c:v', 'mpeg2video' if name == 'vod' else 'copy', '-g', '10', '-c:a', 'copy', '-hls_time', '1', '-hls_list_size', '0',
                    *extra, directory / (name + '.m3u8')])
            (directory / 'master.m3u8').write_text('#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=100000,RESOLUTION=160x90\nvod.m3u8\n')
            (directory / 'page.html').write_text('<title>Public clip</title><video><source src="direct.mp4"></video>')
            (directory / 'ambiguous.html').write_text('<video src="direct.mp4"></video><video src="direct.mp4"></video>')
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(directory)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                root = f'http://127.0.0.1:{server.server_port}'
                cookie = directory / 'cookies.txt'
                cookie.write_text('# Netscape HTTP Cookie File\n127.0.0.1\tFALSE\t/\tFALSE\t2147483647\tsession\tsecret\n')
                cross = re.sub(r'(?m)^(vod\d+\.ts)$', f'http://localhost:{server.server_port}/\\1', (directory / 'vod.m3u8').read_text())
                (directory / 'cross.m3u8').write_text(cross)
                platforms.download(platforms.resolve(root + '/cross.m3u8', cookies=cookie), directory / 'downloads', cookies=cookie)
                self.assertTrue(any('session=secret' in value for path, value in observed if path == '/cross.m3u8'))
                self.assertTrue(any(path.endswith('.ts') for path, value in observed))
                self.assertTrue(all(not value for path, value in observed if path.endswith('.ts')))
                for name in ('direct.mp4', 'page.html', 'vod.m3u8', 'fragmented.m3u8', 'master.m3u8'):
                    with self.subTest(name=name):
                        result = platforms.resolve(root + '/' + name, need=['video'])
                        output = platforms.download(result, directory / 'downloads')
                        actual = platforms.media.probe(output)
                        self.assertTrue(actual['video'])
                        self.assertTrue(actual['audio'])
                        self.assertAlmostEqual(actual['duration'], 3, delta=.3)
                with self.assertRaises(platforms.Failure) as caught:
                    platforms.resolve(root + '/ambiguous.html')
                self.assertEqual(caught.exception.code, 'media_ambiguous')
                (directory / 'short.m3u8').write_text(re.sub(r'#EXTINF:[^,]+', '#EXTINF:10', (directory / 'vod.m3u8').read_text()))
                with self.assertRaises(platforms.Failure) as caught:
                    platforms.download(platforms.resolve(root + '/short.m3u8'), directory / 'downloads')
                self.assertEqual(caught.exception.code, 'download_incomplete')
                self.assertFalse(list((directory / 'downloads').glob('.hls-*')))
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_hls_explicit_unsupported_boundaries(self):
        base = '#EXTM3U\n#EXTINF:1,\na.ts\n#EXT-X-ENDLIST\n'
        for text, code in [
            (base.replace('#EXT-X-ENDLIST', ''), 'live_unsupported'),
            (base.replace('#EXTINF', '#EXT-X-KEY:METHOD=AES-128,URI="key"\n#EXTINF'), 'encrypted_stream_unsupported'),
            (base.replace('#EXTINF', '#EXT-X-BYTERANGE:100@0\n#EXTINF'), 'hls_feature_unsupported'),
            (base.replace('#EXTINF', '#EXT-X-DISCONTINUITY\n#EXTINF'), 'hls_feature_unsupported'),
            ('#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",URI="a.m3u8"\n#EXT-X-STREAM-INF:BANDWIDTH=100,AUDIO="a"\nv.m3u8\n', 'hls_feature_unsupported'),
        ]:
            with self.subTest(code=code), self.assertRaises(platforms.Failure) as caught:
                generic._playlist(text, 'https://example.test/media.m3u8')
            self.assertEqual(caught.exception.code, code)

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
