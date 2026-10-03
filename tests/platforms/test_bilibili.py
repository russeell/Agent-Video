"""Single-part identity and full anonymous Bilibili playback responses."""
from unittest.mock import MagicMock, patch
from io import BytesIO
from http.client import IncompleteRead
from urllib.parse import quote, parse_qs, urlsplit
import unittest

from scripts import platforms
from scripts.platforms import bilibili


class BilibiliPlaybackTests(unittest.TestCase):
    def test_public_web_subtitle_reply_and_encoded_address(self):
        def integer(value):
            result = bytearray()
            while value > 127:
                result.append((value & 127) | 128)
                value >>= 7
            return bytes(result + bytes([value]))
        def field(number, value):
            return integer(number * 8 + 2) + integer(len(value)) + value
        view = {'aid': 123, 'bvid': 'BVexample', 'title': 'Public work',
                'pages': [{'page': 1, 'cid': 7, 'duration': 142}]}
        for index, (prefix, key) in enumerate(bilibili._SUBTITLE_ENCODINGS):
            with self.subTest(encoding=prefix):
                subtitle_path = '/bfs/subtitle/example.json' if index == 0 else '/bfs/ai_subtitle/prod/example'
                plain = prefix + subtitle_path
                encoded = ''.join(chr(ord(c) ^ ord(key[i % len(key)])) for i, c in enumerate(plain))
                address = '//subtitle.bilibili.com/' + quote(encoded, safe='') + '?auth_key=public-test'
                track = field(3, b'ai-zh') + field(5, address.encode()) + b'\x38\x01'
                body = field(1, field(3, track))
                with patch.object(bilibili, '_api', return_value=view) as api, \
                     patch.object(bilibili, 'request', return_value=BytesIO(body)) as request:
                    result = bilibili.resolve('https://www.bilibili.com/video/BVexample', need=['transcript'])
                api.assert_called_once()
                self.assertEqual(urlsplit(request.call_args.args[0]).path, '/x/v2/subtitle/web/view')
                self.assertEqual(parse_qs(urlsplit(request.call_args.args[0]).query)['pid'], ['123'])
                self.assertEqual(result['subtitles'][0]['url'],
                                 'https://aisubtitle.hdslb.com' + subtitle_path + '?auth_key=public-test')
                self.assertEqual(result['subtitles'][0]['language'], 'zh')
                self.assertEqual(result['subtitles'][0]['origin'], 'platform_auto')
                self.assertEqual(result['diagnostics'], [])
        with patch.object(bilibili, '_api', return_value=view) as api, \
             patch.object(bilibili, 'request', return_value=BytesIO(b'\x0a\x00')):
            result = bilibili.resolve('https://www.bilibili.com/video/BVexample', need=['transcript'])
        api.assert_called_once()
        self.assertEqual(result['diagnostics'][0]['code'], 'subtitle_absent')

    def test_subtitle_failures_keep_information_and_auth_diagnostics(self):
        view = {'aid': 123, 'bvid': 'BVexample', 'title': 'Public work',
                'pages': [{'page': 1, 'cid': 7, 'duration': 142}]}
        cases = [(b'{"code":-101}', 'auth_required'),
                 (b'\x0a\x06short', 'parse_failed'),
                 (b'\x0a\x03\x1a\x05x', 'parse_failed'),
                 (IncompleteRead(b'partial', 10), 'network_failed')]
        for body, code in cases:
            response = BytesIO(body) if isinstance(body, bytes) else MagicMock()
            if not isinstance(body, bytes):
                response.__enter__.return_value.read.side_effect = body
            with self.subTest(code=code, body=body), \
                 patch.object(bilibili, '_api', side_effect=[view, {'need_login_subtitle': True}]) as api, \
                 patch.object(bilibili, 'request', return_value=response):
                result = bilibili.resolve('https://www.bilibili.com/video/BVexample', need=['info', 'transcript'])
            self.assertEqual(api.call_count, 2)  # info plus one legacy fallback
            self.assertEqual(result['metadata']['title'], 'Public work')
            self.assertEqual(result['subtitles'], [])
            self.assertEqual(result['diagnostics'][0]['code'], code)
            self.assertNotIn('subtitle_absent', [d['code'] for d in result['diagnostics']])
        for address in ['//subtitle.bilibili.com/%nothex', '//subtitle.bilibili.com/unknown']:
            with self.subTest(address=address), self.assertRaises(platforms.Failure):
                bilibili._subtitle_url(address)

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

    def test_confirmed_supporter_only_work_keeps_info_without_retrying_playback(self):
        view = {'bvid': 'BVexample', 'title': 'Listed but supporter-only',
                'is_upower_exclusive': True, 'is_upower_play': False,
                'pages': [{'page': 1, 'cid': 7, 'duration': 16}]}
        for need in (['info'], ['video'], ['audio'], ['frames']):
            with self.subTest(need=need), \
                 patch.object(bilibili, '_api', return_value=view), \
                 patch.object(bilibili, '_playinfo') as play:
                result = bilibili.resolve('https://www.bilibili.com/video/BVexample', need=need)
            play.assert_not_called()
            self.assertEqual(result['metadata']['title'], view['title'])
            self.assertIs(result['metadata']['supporter_only'], True)
            self.assertEqual(result['formats'], [])
            self.assertEqual([d['code'] for d in result['diagnostics']],
                             [] if need == ['info'] else ['auth_required'])

    def test_supporter_flag_does_not_block_authorized_or_unknown_playback(self):
        base = {'bvid': 'BVexample', 'pages': [{'page': 1, 'cid': 7, 'duration': 238}]}
        cases = [({'is_upower_exclusive': True, 'is_upower_play': False}, '/explicit/cookies.txt'),
                 ({'is_upower_exclusive': True, 'is_upower_play': True}, None),
                 ({'is_upower_exclusive': True}, None),
                 ({'is_upower_exclusive': False, 'is_upower_play': False}, None),
                 ({}, None)]
        for flags, cookies in cases:
            with self.subTest(flags=flags, cookies=cookies), \
                 patch.object(bilibili, '_api', return_value={**base, **flags}), \
                 patch.object(bilibili, '_playinfo', return_value=self.full()) as play:
                result = bilibili.resolve('https://www.bilibili.com/video/BVexample',
                                          need=['video'], cookies=cookies)
            play.assert_called_once_with('BVexample', 7, 238, cookies)
            self.assertTrue(result['formats'])
            self.assertEqual(result['diagnostics'], [])

        # Code 87008 alone is not evidence that an unrelated work is paywalled.
        with patch.object(bilibili, '_api', return_value=base), \
             patch.object(bilibili, '_playinfo', side_effect=platforms.Failure(
                 'platform_failed', 'Bilibili API rejected the request (code 87008).')):
            result = bilibili.resolve('https://www.bilibili.com/video/BVexample', need=['video'])
        self.assertIsNone(result['metadata']['supporter_only'])
        self.assertEqual(result['diagnostics'][0]['code'], 'platform_failed')

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
