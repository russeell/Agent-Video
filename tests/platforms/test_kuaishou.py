"""Kuaishou explicit work identity, denial and stream qualities."""
import json
import unittest
from unittest.mock import patch
from scripts.platforms import Failure, kuaishou, select_formats


class KuaishouTests(unittest.TestCase):
    def test_mobile_state_numeric_id_uses_precise_public_share_identity(self):
        item = {'photoId': '5257108313064881477', 'share_info': 'userId=author&photoId=3xsample',
                'photoType': 'VIDEO', 'duration': 105307, 'width': 720, 'height': 1280,
                'ext_params': {'sound': 105323}, 'mainMvUrls': [{'url': 'https://cdn.test/base'}],
                'manifest': json.dumps({'adaptationSet': [{'representation': [{
                    'url': 'https://cdn.test/high', 'backupUrl': ['https://cdn.test/backup'],
                    'width': 720, 'height': 1280, 'avgBitrate': 2915, 'frameRate': 29.998}]}]})}
        page = '<script>window.INIT_STATE = ' + json.dumps({'opaque.route': {'result': 1, 'photo': item}}) + '</script>'
        parsed = kuaishou._item(page, '3xsample')
        formats = kuaishou._formats(parsed, 'https://www.kuaishou.com/')
        self.assertEqual(len(formats), 3)
        self.assertEqual(select_formats(formats, quality='source')[0]['bitrate'], 2915000)
        self.assertTrue(all(f['has_audio'] for f in formats))
        with self.assertRaises(Failure):
            kuaishou._item(page, 'other-work')

    def test_mobile_share_redirect_uses_mobile_user_agent_and_platform_hosts(self):
        from unittest.mock import MagicMock
        response = MagicMock()
        response.__enter__.return_value.geturl.return_value = 'https://kph8gvfz.m.chenzhongtech.com/fw/photo/3xsample?photoId=3xsample'
        with patch.object(kuaishou, 'request', return_value=response) as request:
            self.assertEqual(kuaishou._identifier('https://v.kuaishou.com/example'), '3xsample')
        self.assertIn('Mobile', request.call_args.kwargs['headers']['User-Agent'])
        response.__enter__.return_value.geturl.return_value = 'https://evil.test/fw/photo/3xsample'
        with patch.object(kuaishou, 'request', return_value=response), self.assertRaises(Failure):
            kuaishou._identifier('https://v.kuaishou.com/example')

    def test_mobile_non_success_and_image_post_are_not_video(self):
        for item, code in [({'result': 2, 'photo': {'photoId': '3xsample', 'mainMvUrls': [{}]}}, 'experimental_access_limited'),
                           ({'photoId': '3xsample', 'photoType': 'ATLAS', 'mainMvUrls': [{}]}, 'unsupported_content')]:
            page = '<script>window.INIT_STATE = ' + json.dumps({'opaque': item}) + '</script>'
            with self.assertRaises(Failure) as caught:
                kuaishou._item(page, '3xsample')
            self.assertEqual(caught.exception.code, code)
        item = {'photoId': '3xsample', 'ext_params': 'unrecognized', 'mainMvUrls': [{'url': 'https://cdn.test/media'}]}
        self.assertEqual(kuaishou._find({'recommendation': {'ext_params': 1}, 'target': item}, '3xsample'), item)
        self.assertIsNone(kuaishou._formats(item, 'https://www.kuaishou.com/')[0]['has_audio'])

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
