"""Douyin single-work public data and honest challenge diagnostics."""
import json
import unittest
from urllib.parse import quote
from scripts import platforms
from scripts.platforms import douyin


class DouyinPublicDataTests(unittest.TestCase):
    def test_signature_challenge_is_not_authentication_or_absent_subtitles(self):
        page = '<script>window.byted_acrawler; var __ac_signature;</script>'
        with self.assertRaises(platforms.Failure) as caught:
            douyin._embedded(page)
        self.assertEqual(caught.exception.code, 'player_challenge_unsupported')
        self.assertIn(str(len(page.encode('utf-8'))), str(caught.exception))
        self.assertNotIn('auth_required', str(caught.exception))

    def test_embedded_data_keeps_exact_single_work_identity(self):
        item = {'aweme_id': '123', 'video': {'duration': 2000}}
        data = {'loaderData': {'page': {'item_list': [item]}}}
        pages = ['<script id="RENDER_DATA">' + quote(json.dumps(data)) + '</script>']
        for page in pages:
            with self.subTest(page=page[:30]):
                extracted = douyin._embedded(page)
                self.assertEqual(douyin._find(extracted, '123'), item)
                self.assertIsNone(douyin._find(extracted, '456'))
        with self.assertRaises(platforms.Failure) as caught:
            douyin._embedded('<script id="RENDER_DATA">not json</script>')
        self.assertEqual(caught.exception.code, 'parse_failed')


if __name__ == '__main__':
    unittest.main()
