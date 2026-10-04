"""Shared VOD HLS acquisition using small real local media."""
import http.server
import re
import shutil
import tempfile
import threading
from functools import partial
from pathlib import Path
import unittest

from scripts import platforms
from scripts import streams


class HLSTests(unittest.TestCase):
    def test_opt_in_signed_query_preserves_bytes_and_origin_boundary(self):
        query = 'token=a%2Fb%2Bz&expires=123&label=a+b'
        parent = 'https://cdn.example.test/master.m3u8?' + query
        child = streams._resource_query('https://cdn.example.test/video.m3u8?expires=456', parent, query)
        self.assertEqual(child, 'https://cdn.example.test/video.m3u8?expires=456&token=a%2Fb%2Bz&label=a+b')
        for foreign in ('https://other.example.test/video.m3u8', 'http://cdn.example.test/video.m3u8'):
            self.assertEqual(streams._resource_query(foreign, parent, query), foreign)
        master = '#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",NAME="Original",URI="https://other.example.test/audio.m3u8"\n#EXT-X-STREAM-INF:BANDWIDTH=10,RESOLUTION=1280x720,AUDIO="a"\nvideo.m3u8\n'
        formats, _ = streams.hls_formats(master, parent, segment_query=query)
        self.assertIn(query, formats[0]['url'])
        self.assertEqual(formats[0]['segment_query'], query)
        self.assertNotIn('segment_query', formats[1])
        self.assertNotIn('token', formats[1]['url'])
        # No implicit propagation for platforms that do not opt in.
        ordinary, _ = streams.hls_formats(master, parent)
        self.assertEqual(ordinary[0]['url'], 'https://cdn.example.test/video.m3u8')

    def test_master_pairs_audio_with_selected_video_quality(self):
        master = '''#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="low",NAME="English original",LANGUAGE="en",URI="audio-low.m3u8"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="high",NAME="English original",LANGUAGE="en",URI="audio-high.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=1000000,RESOLUTION=1920x1080,AUDIO="low"
video-low.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=5000000,RESOLUTION=3840x2160,AUDIO="high"
video-high.m3u8
'''
        formats, language = streams.hls_formats(master, 'https://example.test/master.m3u8',
                                               headers={'Referer': 'https://example.test/'})
        self.assertEqual(language, 'en')
        for quality, group in [('source', 'high'), ('1080p', 'low')]:
            with self.subTest(quality=quality):
                selected = platforms.select_formats(formats, quality=quality)
                self.assertEqual([f['audio_group'] for f in selected], [group, group])
                self.assertTrue(all(f['headers']['Referer'] == 'https://example.test/' for f in selected))
        frames = platforms.select_formats(formats, want_video='frames', width=0)
        self.assertEqual(len(frames), 1)
        without_high_audio = [f for f in formats if not (f.get('has_audio') and f['audio_group'] == 'high')]
        with self.assertRaises(platforms.Failure) as caught:
            platforms.select_formats(without_high_audio, quality='source')
        self.assertEqual(caught.exception.code, 'audio_unavailable')

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg and ffprobe required')
    def test_real_http_vod_hls(self):
        observed = []
        class Handler(http.server.SimpleHTTPRequestHandler):
            def do_GET(self):
                observed.append((self.path, self.headers.get('Cookie', '')))
                if self.path.startswith('/redirect.m3u8'):
                    self.send_response(302)
                    self.send_header('Location', f'http://localhost:{self.server.server_port}/vod.m3u8')
                    self.end_headers()
                    return
                if self.path.startswith('/signed') and '?token=a%2Fb%2Bz&expires=123' not in self.path:
                    self.send_error(403)
                    return
                super().do_GET()
            def log_message(self, *args):
                pass
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            platforms.media.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
                '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10:duration=3',
                '-f', 'lavfi', '-i', 'sine=frequency=440:duration=3', '-c:v', 'mpeg4',
                '-g', '10', '-c:a', 'aac', '-shortest', directory / 'source.mp4'])
            for name, extra in [('vod', []), ('fragmented', ['-hls_segment_type', 'fmp4']),
                                ('single', ['-hls_flags', 'single_file'])]:
                platforms.media.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
                    '-i', directory / 'source.mp4', '-c:v', 'copy' if name == 'fragmented' else 'mpeg2video', '-g', '10', '-c:a', 'copy', '-hls_time', '1', '-hls_list_size', '0',
                    *extra, directory / (name + '.m3u8')])
            # YouTube original audio uses packed ADTS AAC with an ID3 timestamp,
            # without EXT-X-MAP. Absence of a map does not imply MPEG-TS.
            platforms.media.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
                '-i', directory / 'source.mp4', '-vn', '-c:a', 'copy', '-f', 'adts', directory / 'packed.aac'])
            packed = directory / 'packed.aac'
            payload = b'com.apple.streaming.transportStreamTimestamp\0' + bytes(8)
            frame = b'PRIV' + len(payload).to_bytes(4, 'big') + bytes(2) + payload
            packed.write_bytes(b'ID3\x03\0\0' + len(frame).to_bytes(4, 'big') + frame + packed.read_bytes())
            (directory / 'packed.m3u8').write_text('#EXTM3U\n#EXTINF:3,\npacked.aac\n#EXT-X-ENDLIST\n')
            (directory / 'master.m3u8').write_text('#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=100000,RESOLUTION=160x90,FRAME-RATE=60\nvod.m3u8\n')
            (directory / 'signed.m3u8').write_text((directory / 'vod.m3u8').read_text().replace('vod', 'signed'))
            for segment in directory.glob('vod*.ts'):
                shutil.copyfile(segment, directory / segment.name.replace('vod', 'signed'))
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(directory)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                root = f'http://127.0.0.1:{server.server_port}'
                audio = streams.download_hls({'url': root + '/packed.m3u8'}, directory / 'downloads/audio.mkv')
                audio_info = platforms.media.probe(audio)
                self.assertFalse(audio_info['video'])
                self.assertEqual(audio_info['audio'][0]['codec_name'], 'aac')
                self.assertAlmostEqual(audio_info['duration'], 3, delta=.3)
                platforms.media.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error',
                                     '-xerror', '-i', audio, '-f', 'null', '-'])
                query = 'token=a%2Fb%2Bz&expires=123'
                signed = streams.download_hls({'url': root + '/signed.m3u8?' + query, 'segment_query': query},
                                               directory / 'downloads/signed.mkv')
                signed_info = platforms.media.probe(signed)
                self.assertTrue(signed_info['video'])
                self.assertTrue(signed_info['audio'])
                self.assertAlmostEqual(signed_info['duration'], 3, delta=.3)
                self.assertTrue(all(path.endswith('?' + query) for path, _ in observed if path.startswith('/signed')))
                before = len(observed)
                redirected = streams.download_hls({'url': root + '/redirect.m3u8?' + query, 'segment_query': query},
                                                  directory / 'downloads/redirected.mkv')
                self.assertAlmostEqual(platforms.media.probe(redirected)['duration'], 3, delta=.3)
                self.assertTrue(all('token=' not in path for path, _ in observed[before + 1:]))
                cookie = directory / 'cookies.txt'
                cookie.write_text('# Netscape HTTP Cookie File\n127.0.0.1\tFALSE\t/\tFALSE\t2147483647\tsession\tsecret\n')
                cross = re.sub(r'(?m)^(vod\d+\.ts)$', f'http://localhost:{server.server_port}/\\1', (directory / 'vod.m3u8').read_text())
                (directory / 'cross.m3u8').write_text(cross)
                streams.download_hls({'url': root + '/cross.m3u8'}, directory / 'downloads/cross.mkv', cookies=cookie)
                self.assertTrue(any('session=secret' in value for path, value in observed if path == '/cross.m3u8'))
                self.assertTrue(any(path.endswith('.ts') for path, value in observed))
                self.assertTrue(all(not value for path, value in observed if path.endswith('.ts')))
                for name in ('vod.m3u8', 'fragmented.m3u8', 'master.m3u8', 'single.m3u8'):
                    with self.subTest(name=name):
                        url, text = streams._fetch(root + '/' + name)
                        parsed, duration = streams._playlist(text, url)
                        formats = parsed if isinstance(parsed, list) else [
                            {'url': url, 'protocol': 'hls', 'ext': 'm3u8', 'has_video': True, 'has_audio': None}]
                        result = {'formats': formats, 'metadata': {'duration': duration}}
                        if name == 'master.m3u8':
                            self.assertEqual(result['formats'][0]['fps'], 60)
                        output = platforms.download(result, directory / 'downloads')
                        actual = platforms.media.probe(output)
                        self.assertTrue(actual['video'])
                        self.assertTrue(actual['audio'])
                        self.assertAlmostEqual(actual['duration'], 3, delta=.3)
                self.assertEqual(sum(path == '/single.ts' for path, _ in observed), 1)
                # Implicit offsets have the same byte coverage. No network Range
                # support is needed when the playlist covers the complete blob.
                single = (directory / 'single.m3u8').read_text()
                implicit = re.sub(r'(?m)(#EXT-X-BYTERANGE:\d+)@(?!0$)\d+$', r'\1', single)
                (directory / 'implicit.m3u8').write_text(implicit)
                output = streams.download_hls({'url': root + '/implicit.m3u8'}, directory / 'downloads/implicit.mkv')
                self.assertAlmostEqual(platforms.media.probe(output)['duration'], 3, delta=.3)
                # Reject a resource whose bytes do not cover the entire playlist,
                # before remuxing it into a plausible but incomplete video.
                (directory / 'single.ts').write_bytes((directory / 'single.ts').read_bytes()[:-188])
                with self.assertRaises(platforms.Failure) as caught:
                    streams.download_hls({'url': root + '/single.m3u8'}, directory / 'downloads/incomplete.mkv')
                self.assertEqual(caught.exception.code, 'download_incomplete')
                self.assertFalse((directory / 'downloads/incomplete.mkv').exists())
                (directory / 'short.m3u8').write_text(re.sub(r'#EXTINF:[^,]+', '#EXTINF:10', (directory / 'vod.m3u8').read_text()))
                with self.assertRaises(platforms.Failure) as caught:
                    streams.download_hls({'url': root + '/short.m3u8'}, directory / 'downloads/short.mkv')
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
            (base.replace('#EXTINF', '#EXT-X-BYTERANGE:100@1\n#EXTINF'), 'hls_feature_unsupported'),
            (base.replace('#EXTINF', '#EXT-X-DISCONTINUITY\n#EXTINF'), 'hls_feature_unsupported'),
            ('#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",URI="a.m3u8"\n#EXT-X-STREAM-INF:BANDWIDTH=100,AUDIO="a"\nv.m3u8\n', 'hls_feature_unsupported'),
        ]:
            with self.subTest(code=code), self.assertRaises(platforms.Failure) as caught:
                streams._playlist(text, 'https://example.test/media.m3u8')
            self.assertEqual(caught.exception.code, code)

    def test_byte_range_validation(self):
        base = '#EXTM3U\n#EXTINF:1,\n#EXT-X-BYTERANGE:100@0\na.ts\n#EXTINF:1,\n#EXT-X-BYTERANGE:50\na.ts\n#EXT-X-ENDLIST\n'
        parsed, duration = streams._playlist(base, 'https://example.test/media.m3u8')
        self.assertEqual(parsed['segments'], ['https://example.test/a.ts'])
        self.assertEqual((parsed['size'], duration), (150, 2))
        for text, code in [
            (base.replace('100@0', '100'), 'parse_failed'),
            (base.replace('100@0', '0@0'), 'parse_failed'),
            (base.replace('100@0', '-100@0'), 'parse_failed'),
            (base.replace('50\na.ts', '50\nb.ts'), 'parse_failed'),
            (base.replace('50\na.ts', '50@0\nb.ts'), 'hls_feature_unsupported'),
            (base.replace('50\na.ts', '50@101\na.ts'), 'hls_feature_unsupported'),
            (base.replace('#EXT-X-BYTERANGE:50\n', ''), 'hls_feature_unsupported'),
            (base.replace('#EXT-X-ENDLIST', '#EXT-X-BYTERANGE:10@150\n#EXT-X-ENDLIST'), 'parse_failed'),
        ]:
            with self.subTest(code=code), self.assertRaises(platforms.Failure) as caught:
                streams._playlist(text, 'https://example.test/media.m3u8')
            self.assertEqual(caught.exception.code, code)

if __name__ == '__main__':
    unittest.main()
