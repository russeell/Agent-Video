import unittest
from unittest.mock import patch
from scripts.platforms import Failure, dailymotion


class DailymotionTests(unittest.TestCase):
    def test_short_link_info_skips_manifest(self):
        data = {'title': 'Demo', 'duration': 7, 'qualities': {'auto': [{'type': 'application/x-mpegURL', 'url': 'https://cdn.test/master'}]}}
        with patch.object(dailymotion, 'read_json', return_value=data) as read:
            result = dailymotion.resolve('https://dai.ly/xabc', need=['info'])
        self.assertEqual(read.call_count, 1)
        self.assertEqual(result['source']['url'], 'https://www.dailymotion.com/video/xabc')
        self.assertEqual(result['formats'], [])

    def test_native_subtitles_and_mp4_not_manifest(self):
        data = {'title': 'Demo', 'subtitles': {'data': {'en': {'urls': ['https://cdn.test/captions.vtt']}}},
                'qualities': {'1080': [{'type': 'video/mp4', 'url': 'https://cdn.test/H264-1920x1080-60/file.mp4#ignored'}]}}
        with patch.object(dailymotion, 'read_json', return_value=data):
            result = dailymotion.resolve('https://www.dailymotion.com/video/xabc_title', need=['transcript', 'video'])
        self.assertEqual(result['subtitles'][0]['ext'], 'vtt')
        self.assertEqual(result['formats'][0]['width'], 1920)
        self.assertEqual(result['formats'][0]['fps'], 60)
        self.assertNotIn('#', result['formats'][0]['url'])
        self.assertIsNone(result['formats'][0]['has_audio'])
        self.assertIsNone(result['metadata']['audio_expected'])

    def test_empty_subtitle_array_and_access_error(self):
        with patch.object(dailymotion, 'read_json', return_value={'title': 'Demo', 'subtitles': {'data': []}}):
            result = dailymotion.resolve('https://dai.ly/xabc', need=['transcript'])
        self.assertEqual(result['diagnostics'][0]['code'], 'subtitle_absent')
        with patch.object(dailymotion, 'read_json', return_value={'error': {'title': 'Geoblocked'}}):
            with self.assertRaises(Failure) as error:
                dailymotion.resolve('https://dai.ly/xabc')
        self.assertEqual(error.exception.code, 'access_denied')

    def test_hls_preserves_playback_headers_for_segments(self):
        data = {'title': 'Demo', 'qualities': {'auto': [{'type': 'application/x-mpegURL', 'url': 'https://cdn.test/master'}]}}
        master = '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000000,RESOLUTION=1920x1080\nvideo.m3u8'
        with patch.object(dailymotion, 'read_json', return_value=data), patch('scripts.streams._fetch', return_value=('https://cdn.test/master', master)) as fetch:
            result = dailymotion.resolve('https://dai.ly/xabc', need=['video'])
        self.assertEqual(fetch.call_args.args[2]['Referer'], 'https://www.dailymotion.com/')
        self.assertEqual(result['formats'][0]['headers']['Origin'], 'https://www.dailymotion.com')
