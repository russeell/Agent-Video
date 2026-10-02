"""Generic page and VOD HLS acquisition using small real local media."""
import http.server
import re
import shutil
import tempfile
import threading
from functools import partial
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import platforms
from platforms import generic


class GenericTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg and ffprobe required')
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

if __name__ == '__main__':
    unittest.main()
