"""Kuaishou explicit work identity, denial and stream qualities."""
import json
import unittest
from unittest.mock import patch
from scripts.platforms import Failure, kuaishou, select_formats


class KuaishouTests(unittest.TestCase):
    def test_identity_all_qualities_and_info_only(self):
        item = {'photoId': '3xsample', 'caption': 'description', 'duration': 3000,
                'photoUrl': 'https://cdn.test/fallback', 'videoResource': {'h264': {'adaptationSet': [
                    {'representation': [{'url': 'https://cdn.test/low', 'width': 360, 'height': 640},
                                        {'url': 'https://cdn.test/high', 'width': 1080, 'height': 1920}]}]}}}
        page = '<script>window.__APOLLO_STATE__=' + json.dumps({'data': {'photo': item}}) + '</script>'
        with patch.object(kuaishou, 'read_text', return_value=page):
            info = kuaishou.resolve('https://www.kuaishou.com/short-video/3xsample', need=['info'])
            result = kuaishou.resolve('https://www.kuaishou.com/short-video/3xsample', need=['video'])
        self.assertEqual(info['formats'], [])
        self.assertEqual(info['subtitles'], [])
        self.assertEqual(info['diagnostics'], [])
        self.assertEqual(info['metadata']['duration'], 3)
        self.assertEqual(select_formats(result['formats'], quality='source')[0]['height'], 1920)
        self.assertIsNone(result['metadata']['audio_expected'])
        self.assertTrue(all(f['has_audio'] is None for f in result['formats']))

    def test_real_result_two_and_wrong_work(self):
        for page in ('{"result":2,"error_msg":null,"request_id":"sample"}',
                     '<script>{"photoId":"wrong","photoUrl":"https://cdn.test/other"}</script>'):
            with self.assertRaises(Failure) as caught:
                kuaishou._item(page, '3xsample')
            self.assertEqual(caught.exception.code, 'experimental_access_limited')

    def test_conflicting_share_identity_and_nonplatform(self):
        for url in ('https://www.kuaishou.com/short-video/one?photoId=other',
                    'https://kuaishou.com.evil.test/short-video/one'):
            with self.assertRaises(Failure):
                kuaishou._identifier(url)
        self.assertEqual(kuaishou._identifier('https://v.m.chenzhongtech.com/fw/photo/one'), 'one')
