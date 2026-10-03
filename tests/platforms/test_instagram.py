"""Instagram identity and direct video regression tests."""
import json
import unittest
from unittest.mock import patch
from scripts.platforms import Failure, instagram, select_formats


class InstagramTests(unittest.TestCase):
    def test_authenticated_api_only_with_explicit_cookie_and_matching_work(self):
        with patch.object(instagram, 'read_text', return_value='<html>Login</html>'), \
                patch.object(instagram, 'read_json', return_value={'items': [{'pk': '66', 'video_versions': []}]}) as api, \
                patch('scripts.browser.browser_page', return_value='<html>Login</html>') as browser:
            with self.assertRaises(Failure):
                instagram.resolve('https://www.instagram.com/reel/BC', need=['info'])
            api.assert_not_called()
            result = instagram.resolve('https://www.instagram.com/reel/BC', need=['info'], cookies='explicit-file')
            self.assertEqual(result['source']['id'], 'BC')
            self.assertEqual(api.call_args.kwargs['cookies'], 'explicit-file')
            self.assertEqual(browser.call_count, 1)
            api.return_value = {'items': [{'pk': '67', 'video_versions': []}]}
            with self.assertRaises(Failure) as caught:
                instagram.resolve('https://www.instagram.com/reel/BC', need=['info'], cookies='explicit-file')
            self.assertEqual(caught.exception.code, 'parse_failed')

    def test_relay_identity_and_all_direct_qualities(self):
        item = {'code': 'ABC', 'caption': {'text': 'description'}, 'video_duration': 3,
                'video_versions': [{'url': 'https://cdn.test/low', 'width': 360, 'height': 640},
                                   {'url': 'https://cdn.test/high', 'width': 1080, 'height': 1920}]}
        page = '<script type="application/json">' + json.dumps({'require': [{'data': {
            'xig_polaris_media': {'if_not_gated_logged_out': item}}}]}) + '</script>'
        with patch.object(instagram, 'read_text', return_value=page):
            info = instagram.resolve('https://www.instagram.com/reel/ABC/', need=['info'])
            result = instagram.resolve('https://www.instagram.com/reel/ABC/', need=['video'])
        self.assertEqual(info['formats'], [])
        self.assertEqual(info['diagnostics'], [])
        self.assertEqual(info['subtitles'], [])
        self.assertEqual(info['metadata']['description'], 'description')
        self.assertEqual(select_formats(result['formats'], quality='source')[0]['height'], 1920)
        self.assertIsNone(result['metadata']['audio_expected'])
        self.assertTrue(all(f['has_audio'] is None for f in result['formats']))

    def test_wrong_work_and_real_login_shell_fail(self):
        page = '<script>' + json.dumps({'code': 'DEF', 'video_versions': []}) + '</script>'
        for value in (page, '<html><title>Login • Instagram</title></html>'):
            with self.assertRaises(Failure) as caught:
                instagram._item(value, 'ABC')
            self.assertEqual(caught.exception.code, 'experimental_access_limited')

    def test_numeric_pk_and_carousel(self):
        self.assertEqual(instagram._find({'pk': '66', 'video_versions': []}, 'BC')['pk'], '66')
        with self.assertRaises(Failure) as caught:
            instagram._find({'code': 'ABC', 'carousel_media': [{}]}, 'ABC')
        self.assertEqual(caught.exception.code, 'unsupported_content')
        for url in ('https://instagram.com.evil.test/reel/ABC/', 'https://www.instagram.com/author/'):
            with self.assertRaises(Failure):
                instagram._identifier(url)

    def test_complete_dash_baseurls_keep_highest_and_actual_audio(self):
        manifest = '<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"><Period>' \
                   '<AdaptationSet mimeType="video/mp4"><Representation width="1080" height="1920" bandwidth="4000000">' \
                   '<BaseURL>https://cdn.test/video</BaseURL><SegmentBase indexRange="0-99"/></Representation></AdaptationSet>' \
                   '<AdaptationSet mimeType="audio/mp4"><Representation bandwidth="128000">' \
                   '<BaseURL>https://cdn.test/audio</BaseURL></Representation></AdaptationSet></Period></MPD>'
        selected = select_formats(instagram._formats({'video_dash_manifest': manifest}, 'https://www.instagram.com/'), quality='source')
        self.assertEqual([f['url'] for f in selected], ['https://cdn.test/video', 'https://cdn.test/audio'])
        self.assertFalse(selected[0]['has_audio'])
        self.assertTrue(selected[1]['has_audio'])
        protected = manifest.replace('<Period>', '<Period><ContentProtection/>')
        self.assertEqual(instagram._formats({'video_dash_manifest': protected}, 'https://www.instagram.com/'), [])
        encoded = manifest.replace('<MPD ', '<MPD mediaPresentationDuration="PT31.413S" ').replace(
            'https://cdn.test/video', 'https://cdn.test/video?first=1&amp;second=2')
        page = '<script>' + json.dumps({'code': 'ABC', 'video_versions': [], 'video_dash_manifest': encoded}) + '</script>'
        item = instagram._item(page, 'ABC')
        self.assertEqual(instagram._duration(item), 31.413)
        self.assertEqual(instagram._formats(item, 'https://www.instagram.com/')[0]['url'],
                         'https://cdn.test/video?first=1&second=2')
