import unittest
from unittest.mock import patch
from scripts.platforms import Failure, zhihu


class ZhihuTests(unittest.TestCase):
    def test_need_formats_and_unknown_language(self):
        data = {'id': '123', 'title': '中文标题', 'video': {'duration': 10, 'play_auth_token': 'secret',
                'playlist': {'fhd': {'play_url': 'https://cdn.test/v.mp4?token=secret', 'width': 1920, 'height': 1080, 'channels': 2, 'bitrate': 500}}}}
        with patch.object(zhihu, 'read_json', return_value=data):
            info = zhihu.resolve('https://www.zhihu.com/zvideo/123', need=['info'])
            media = zhihu.resolve('https://zhihu.com/zvideo/123', need=['video', 'transcript'])
        self.assertEqual(info['formats'], [])
        self.assertNotIn('secret', str(info['metadata']))
        self.assertIsNone(info['metadata']['original_language'])
        self.assertEqual(media['formats'][0]['bitrate'], 500000)
        self.assertTrue(media['formats'][0]['has_audio'])
        self.assertEqual(media['diagnostics'][0]['code'], 'subtitle_absent')

    def test_trial_does_not_download_preview(self):
        with patch.object(zhihu, 'read_json', return_value={'id': '123', 'title': 'Trial', 'video': {'is_trial': True}}):
            result = zhihu.resolve('https://zhihu.com/zvideo/123', need=['video'])
        self.assertEqual(result['formats'], [])
        self.assertEqual(result['diagnostics'][0]['code'], 'access_denied')

    def test_identity_and_routes(self):
        with patch.object(zhihu, 'read_json', return_value={'id': '456', 'title': 'Wrong'}), self.assertRaises(Failure):
            zhihu.resolve('https://zhihu.com/zvideo/123')
        for url in ['https://evil.test/zvideo/123', 'https://zhihu.com/question/123', 'https://zhihu.com/zvideo/123/extra']:
            with self.assertRaises(Failure):
                zhihu.resolve(url)
