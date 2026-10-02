import http.server
import io
import json
import re
from pathlib import Path
import sys
import tempfile
import threading
from functools import partial
import unittest
from unittest.mock import MagicMock, patch

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
        self.assertEqual([f['url'] for f in platforms.select_formats(tracks)], ['3840', 'audio'])
        self.assertEqual([f['url'] for f in platforms.select_formats(tracks, quality='1080p')], ['1920', 'audio'])
        self.assertEqual(platforms.select_formats(tracks, quality='source')[0]['width'], 3840)
        self.assertEqual(platforms.select_formats(tracks, want_video='frames', width=768)[0]['width'], 1280)
        self.assertEqual(platforms.select_formats(tracks, want_video=False)[0]['url'], 'audio')
        portrait = [{'url': 'p', 'width': 1080, 'height': 1920, 'has_video': True, 'has_audio': True}]
        self.assertEqual(platforms.select_formats(portrait)[0]['url'], 'p')

    def test_video_resolution_then_fps_then_bitrate(self):
        base = {'url': '30fps', 'width': 1920, 'height': 1080,
                'has_video': True, 'has_audio': True, 'fps': 30, 'bitrate': 10000}
        smooth = {**base, 'url': '60fps', 'fps': 60, 'bitrate': 5000}
        sharp = {**base, 'url': '4k', 'width': 3840, 'height': 2160, 'fps': 24, 'bitrate': 1000}
        self.assertEqual(platforms.select_formats([base, smooth])[0]['url'], '60fps')
        self.assertEqual(platforms.select_formats([base, smooth, sharp])[0]['url'], '4k')
        self.assertEqual(platforms.select_formats([base, smooth, sharp], quality='1080p')[0]['url'], '60fps')
        self.assertEqual(platforms.select_formats([base, {**base, 'url': 'higher', 'bitrate': 20000}])[0]['url'], 'higher')

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
            (directory / 'master.m3u8').write_text('#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=100000,RESOLUTION=160x90,FRAME-RATE=60\nvod.m3u8\n')
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
                        if name == 'master.m3u8':
                            self.assertEqual(result['formats'][0]['fps'], 60)
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


class BilibiliPlaybackTests(unittest.TestCase):
    def full(self, height=1080):
        return {'timelength': 237922, 'dash': {'duration': 237.922,
                'video': [{'id': 80, 'width': 1920, 'height': height,
                           'baseUrl': 'https://media.example/video'}]}}

    def test_anonymous_standard_playback_returns_high_quality(self):
        response = self.full()
        with patch.object(bilibili, '_api', return_value=response) as api:
            self.assertIs(bilibili._playinfo('BVtest', 1, 238, None), response)
        query = api.call_args.args[1]
        self.assertEqual(query['try_look'], 1)
        self.assertEqual(query['fnver'], 0)
        self.assertEqual(query['fnval'], 4048)
        self.assertEqual(api.call_count, 1)

    def test_anonymous_failed_preview_short_and_empty_fall_back(self):
        failures = [platforms.Failure('network_failed', 'Temporary failure'),
                    {**self.full(), 'is_preview': True},
                    {**self.full(), 'timelength': 30000},
                    {**self.full(), 'dash': {'duration': 30, 'video': [{}]}}, {}]
        for failed in failures:
            with self.subTest(response=type(failed).__name__):
                complete = self.full(480)
                with patch.object(bilibili, '_api', side_effect=[failed, complete]) as api:
                    self.assertIs(bilibili._playinfo('BVtest', 1, 238, None), complete)
                self.assertNotIn('try_look', api.call_args.args[1])

    def test_user_cookie_skips_anonymous_parameter(self):
        with patch.object(bilibili, '_api', return_value=self.full()) as api:
            bilibili._playinfo('BVtest', 1, 238, '/explicit/cookies.txt')
        self.assertEqual(api.call_count, 1)
        self.assertNotIn('try_look', api.call_args.args[1])

    def test_preview_and_truncated_fallback_are_not_accepted(self):
        for response in ({**self.full(), 'is_preview': True},
                         {**self.full(), 'timelength': 30000}):
            with self.subTest(response=response):
                with patch.object(bilibili, '_api', return_value=response):
                    with self.assertRaises(platforms.Failure):
                        bilibili._playinfo('BVtest', 1, 238, None)


if __name__ == '__main__':
    unittest.main()
