"""91porn literal player data, identity, requests and access boundaries."""
import unittest
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote
from scripts.platforms import porn91
from scripts import platforms
from scripts.media import Failure


URL = 'https://91porn.com/view_video.php?viewkey=abc123'
PAGE = '<title>Sample - Chinese homemade video</title><video id="player_one"></video><a href="/view_video.php?viewkey=abc123&action=comment">Comments</a>'


class Porn91Tests(unittest.TestCase):
    def test_mirror_keeps_origin_and_ignores_commented_media(self):
        mirror = 'https://up.91splt.app/view_video.php?viewkey=abc123'
        address = 'https://cdn.example.test/work.mp4?token=a%2Fb'
        encoded = quote('<source src="' + address + '" type="video/mp4">', safe='')
        page = ('<title>Sample - Chinese homemade video</title>'
                '<video id="player_one">'
                '<!-- <source src="https://cdn.example.test/unrelated.mp4"> -->'
                '<script>document.write(strencode2("' + encoded + '"));</script></video>'
                '<a href="?viewkey=abc123&action=comment">Comments</a>'
                '<div>Duration: <span>00:10</span></div>')
        for source in (mirror, 'http://up.91splt.app/view_video.php?c=tracking&viewkey=abc123&category='):
            with self.subTest(source=source):
                with patch.object(porn91, 'read_text', return_value=page) as fetch:
                    result = platforms.resolve(source, cookies='explicit-file', need=['video'])
                self.assertEqual(result['source'], {'platform': '91porn', 'id': 'abc123', 'url': mirror})
                self.assertEqual(result['metadata']['duration'], 10)
                self.assertEqual([f['url'] for f in result['formats']], [address])
                self.assertEqual(result['formats'][0]['headers'], {'Referer': mirror})
                fetch.assert_called_once_with(mirror, cookies='explicit-file',
                                              headers={'Referer': 'https://up.91splt.app/'})

    def test_identity_and_query_normalization(self):
        with patch.object(porn91, 'read_text', return_value=PAGE) as fetch:
            result = porn91.resolve('http://www.91porn.com/view_video.php?utm=x&viewkey=abc123', need=['info'])
        self.assertEqual(result['source'], {'platform': '91porn', 'id': 'abc123', 'url': URL})
        self.assertEqual(result['metadata']['title'], 'Sample')
        self.assertIsNone(result['metadata']['duration'])
        self.assertIsNone(result['metadata']['original_language'])
        self.assertEqual(result['formats'], [])
        fetch.assert_called_once_with(URL, cookies=None, headers={'Referer': 'https://91porn.com/'})

    def test_literal_player_percent_decoding_and_metadata(self):
        address = 'https://cdn.example.test/work.mp4?token=a%2Fb&expires=123'
        encoded = quote('<source src="' + address.replace('&', '&amp;') + '" type="video/mp4">', safe='')
        page = PAGE + '<div>时长: <span>01:02</span></div><script>document.write(strencode2("' + encoded + '"));</script>'
        with patch.object(porn91, 'read_text', return_value=page):
            result = porn91.resolve(URL, cookies='explicit-file', need=['video', 'transcript'])
        self.assertEqual(result['metadata']['duration'], 62)
        self.assertEqual(result['formats'][0]['url'], address)
        self.assertIsNone(result['formats'][0]['has_audio'])
        self.assertNotIn('token=', repr(result['metadata']))
        self.assertEqual(result['diagnostics'][0]['code'], 'subtitle_absent')

    def test_direct_video_captions_and_info_do_not_fetch_media(self):
        page = PAGE + '<video id="player_one" src="https://cdn.example.test/work.mp4"><track kind="subtitles" src="https://cdn.example.test/sub.vtt" srclang="en"></video>'
        with patch.object(porn91, 'read_text', return_value=page) as fetch:
            result = porn91.resolve(URL, need=['transcript'])
        fetch.assert_called_once()
        self.assertEqual(result['formats'], [])
        self.assertEqual(result['subtitles'][0]['language'], 'en')
        self.assertEqual(result['subtitles'][0]['ext'], 'vtt')
        self.assertEqual(result['diagnostics'], [])

    def test_player_work_duration_preserves_incomplete_download_check(self):
        page = PAGE + '<script>const videoDuration = 925.085;</script><video id="player_one" src="https://cdn.example.test/work.mp4"></video>'
        with patch.object(porn91, 'read_text', return_value=page):
            result = porn91.resolve(URL, need=['video'])
        self.assertEqual(result['metadata']['duration'], 925.085)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg and ffprobe required')
    def test_playable_short_substitute_is_not_delivered_as_full_work(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            short = directory / 'short.mp4'
            platforms.media.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'lavfi',
                '-i', 'testsrc2=size=160x90:rate=10:duration=2', '-f', 'lavfi',
                '-i', 'sine=frequency=440:duration=2', '-c:v', 'mpeg4', '-c:a', 'aac', '-shortest', short])
            page = PAGE + '<script>const videoDuration = 925.085;</script><video id="player_one" src="https://cdn.example.test/work.mp4"></video>'
            with patch.object(porn91, 'read_text', return_value=page):
                result = porn91.resolve(URL, need=['video'])
            def fetch(url, path, **kwargs):
                path = Path(path)
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(short, path)
                return path
            with patch.object(platforms, 'download_file', side_effect=fetch), self.assertRaises(Failure) as caught:
                platforms.download(result, directory / 'download')
            self.assertEqual(caught.exception.code, 'download_incomplete')
            self.assertFalse(list((directory / 'download').glob('*')))
            self.assertTrue(short.exists())

    def test_vod_hls_and_partial_media_failure(self):
        page = PAGE + '<video id="player_one"><source src="https://cdn.example.test/work.m3u8"></video>'
        with patch.object(porn91, 'read_text', return_value=page), patch('scripts.streams._fetch', return_value=(
                'https://cdn.example.test/work.m3u8', '#EXTM3U\n#EXTINF:2,\na.ts\n#EXT-X-ENDLIST\n')):
            result = porn91.resolve(URL, need=['video'])
        self.assertEqual(result['formats'][0]['protocol'], 'hls')
        with patch.object(porn91, 'read_text', return_value=page), patch('scripts.streams._fetch', return_value=(
                'https://cdn.example.test/work.m3u8', '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=100\nchild.m3u8\n')):
            result = porn91.resolve(URL, need=['video'])
        self.assertEqual(result['formats'][0]['url'], 'https://cdn.example.test/child.m3u8')
        self.assertEqual(result['formats'][0]['headers']['Referer'], URL)
        with patch.object(porn91, 'read_text', return_value=page), patch('scripts.streams._fetch', return_value=(
                'https://cdn.example.test/work.m3u8', '#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key"\n#EXTINF:2,\na.ts\n#EXT-X-ENDLIST\n')):
            result = porn91.resolve(URL, need=['video'])
        self.assertEqual(result['metadata']['title'], 'Sample')
        self.assertEqual(result['formats'], [])
        self.assertEqual(result['diagnostics'][0]['code'], 'encrypted_stream_unsupported')

    def test_invalid_urls_do_not_request(self):
        for url in ('https://91porn.com/v.php', 'https://91porn.com/view_video.php?viewkey=x&viewkey=y',
                    'https://up.91splt.app/view_video.php?viewkey=x&viewkey=y',
                    'https://up.91splt.app.evil.test/view_video.php?viewkey=x',
                    'https://91porn.com.evil.test/view_video.php?viewkey=x', 'https://user:pass@91porn.com/view_video.php?viewkey=x',
                    'https://91porn.com:bad/view_video.php?viewkey=x'):
            with self.subTest(url=url), patch.object(porn91, 'read_text') as fetch, self.assertRaises(Failure):
                porn91.resolve(url)
            fetch.assert_not_called()

    def test_identity_access_and_no_player_are_distinct(self):
        for page, code in [('<title>Wrong</title><a href="?viewkey=other">Other</a>', 'parse_failed'),
                           ('<title>Listing</title><a href="?viewkey=abc123">Candidate</a>', 'parse_failed'),
                           (PAGE + '<link rel="canonical" href="?viewkey=other">', 'parse_failed'),
                           ('视频不存在,可能已经被删除', 'media_unavailable'),
                           ('作为游客，你每天只可观看10个视频', 'auth_required')]:
            with self.subTest(code=code), patch.object(porn91, 'read_text', return_value=page), self.assertRaises(Failure) as caught:
                porn91.resolve(URL)
            self.assertEqual(caught.exception.code, code)
        with patch.object(porn91, 'read_text', return_value=PAGE):
            result = porn91.resolve(URL, need=['video'])
        self.assertEqual(result['diagnostics'][0]['code'], 'media_unavailable')


if __name__ == '__main__':
    unittest.main()
