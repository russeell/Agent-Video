"""Xiaohongshu state, share access and quality regression tests."""
import json
import unittest
from unittest.mock import patch
from scripts.platforms import Failure, select_formats, xiaohongshu


class XiaohongshuTests(unittest.TestCase):
    identifier = '69ae11820000000022038fd8'

    def test_state_preserves_literal_undefined_and_share_access(self):
        data = xiaohongshu._state('<script>window.__INITIAL_STATE__={"desc":"undefined","unused":undefined}</script>')
        self.assertEqual(data, {'desc': 'undefined', 'unused': None})
        identifier, url = xiaohongshu._identifier('https://www.xiaohongshu.com/discovery/item/' + self.identifier +
                                                 '?xsec_token=sample%3D&xsec_source=app_share&track=ignored')
        self.assertEqual(identifier, self.identifier)
        self.assertIn('xsec_token=sample%3D', url)
        self.assertNotIn('track=', url)

    def test_quality_and_info_only(self):
        streams = {'h264': [{'masterUrl': 'https://cdn.test/low', 'width': 360, 'height': 640,
                             'duration': 3000}, {'masterUrl': 'https://cdn.test/high', 'width': 1080,
                             'height': 1920, 'duration': 3000, 'audioCodec': 'aac'}]}
        item = {'noteId': self.identifier, 'type': 'video', 'title': 'title', 'desc': 'description',
                'video': {'media': {'stream': streams}}}
        page = '<script>window.__INITIAL_STATE__=' + json.dumps({'note': {'noteDetailMap': {
            self.identifier: {'note': item}}}}) + '</script>'
        with patch.object(xiaohongshu, '_read_page', return_value=page):
            info = xiaohongshu.resolve('https://www.xiaohongshu.com/explore/' + self.identifier, need=['info'])
            result = xiaohongshu.resolve('https://www.xiaohongshu.com/explore/' + self.identifier, need=['video'])
        self.assertEqual(info['formats'], [])
        self.assertEqual(info['subtitles'], [])
        self.assertEqual(info['diagnostics'], [])
        self.assertEqual(info['metadata']['duration'], 3)
        self.assertEqual(select_formats(result['formats'], quality='source')[0]['height'], 1920)
        self.assertIsNone(result['formats'][0]['has_audio'])
        self.assertTrue(result['formats'][1]['has_audio'])
        self.assertTrue(result['metadata']['audio_expected'])

    def test_empty_detail_map_wrong_id_and_images(self):
        def page(item):
            return '<script>window.__INITIAL_STATE__=' + json.dumps({'note': {'noteDetailMap': {
                self.identifier: {'note': item}}}}) + '</script>'
        with self.assertRaises(Failure) as caught:
            xiaohongshu._note('<script>window.__INITIAL_STATE__={"note":{"noteDetailMap":{}}}</script>', self.identifier)
        self.assertEqual(caught.exception.code, 'experimental_access_limited')
        for item, code in [({'noteId': 'wrong', 'type': 'video'}, 'parse_failed'),
                           ({'noteId': self.identifier, 'type': 'normal'}, 'unsupported_content')]:
            with self.assertRaises(Failure) as caught:
                xiaohongshu._note(page(item), self.identifier)
            self.assertEqual(caught.exception.code, code)

    def test_unavailable_and_security_redirect_are_not_empty_data_parse_errors(self):
        for url, code in [('https://www.xiaohongshu.com/404?error_code=300031', 'platform_unavailable'),
                          ('https://www.xiaohongshu.com/404/sec_example?redirectPath=%2Fexplore%2Fexample', 'access_denied'),
                          ('https://example.test/explore/123', 'invalid_url')]:
            with self.assertRaises(Failure) as caught:
                xiaohongshu._check_response_url(url)
            self.assertEqual(caught.exception.code, code)
