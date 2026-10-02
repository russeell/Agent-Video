"""Single-part identity and full anonymous Bilibili playback responses."""
from unittest.mock import patch
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import platforms
from platforms import bilibili


class BilibiliPlaybackTests(unittest.TestCase):
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
