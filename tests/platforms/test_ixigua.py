import base64
import json
import unittest
from unittest.mock import MagicMock, patch
from scripts.platforms import Failure, ixigua

ID = '6963187000321147400'
URL = 'https://www.ixigua.com/' + ID


def page(video):
    return '<script id="SSR_HYDRATED_DATA">window._SSR_HYDRATED_DATA=' + json.dumps({'anyVideo': {'gidInformation': {'packerData': {'video': video}}}}) + '</script>'


def resource(address, **fields):
    return dict(main_url=base64.b64encode(address.encode()).decode(), **fields)


class IxiguaTests(unittest.TestCase):
    def test_need_aware_and_undefined_does_not_change_user_text(self):
        video = {'gid': ID, 'title': 'literal undefined', 'video_abstract': 'Description :undefined, is not transcript', 'duration': 90, 'other': None,
                 'videoResource': {'normal': {'video_list': {'a': resource('https://cdn.test/full.mp4')}}}}
        text = page(video).replace('"other": null', '"other": undefined')
        with patch.object(ixigua, 'read_text', return_value=text):
            result = ixigua.resolve(URL, need=['info', 'transcript'])
        self.assertEqual(result['formats'], [])
        self.assertEqual(result['subtitles'], [])
        self.assertEqual(result['metadata']['title'], 'literal undefined')
        self.assertEqual(result['metadata']['description'], video['video_abstract'])

    def test_muxed_and_separate_stream_tracks_preserve_dimensions(self):
        video = {'gid': ID, 'title': 'Demo', 'videoResource': {'normal': {'video_list': {'a': resource('https://cdn.test/720.mp4', vwidth=1280, vheight=720)},
                  'dynamic_video': {'dynamic_video_list': {'v': resource('https://cdn.test/1080.mp4', vwidth=1920, vheight=1080)},
                                    'dynamic_audio_list': {'a': resource('https://cdn.test/audio.m4a')}}}}}
        with patch.object(ixigua, 'read_text', return_value=page(video)):
            result = ixigua.resolve('https://m.ixigua.com/video/' + ID, need=['video'])
        self.assertEqual(result['source']['url'], URL)
        self.assertEqual([(f['has_video'], f['has_audio']) for f in result['formats']], [(True, None), (True, False), (False, True)])
        self.assertTrue(result['metadata']['audio_expected'])
        self.assertEqual(result['formats'][1]['height'], 1080)

    def test_share_final_identity_and_off_platform_redirect_validation(self):
        response = MagicMock()
        response.__enter__.return_value.geturl.return_value = 'https://www.toutiao.com/video/' + ID
        with patch.object(ixigua, 'request', return_value=response), patch.object(ixigua, 'read_text', return_value=page({'gid': ID, 'title': 'Demo'})):
            result = ixigua.resolve('https://m.toutiao.com/is/abcdef/', need=['info'])
        self.assertEqual(result['source']['id'], ID)
        with self.assertRaises(Failure):
            ixigua._ShareRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.test/' + ID)
        response.__enter__.return_value.geturl.return_value = 'https://www.toutiao.com/'
        with patch.object(ixigua, 'request', return_value=response), self.assertRaises(Failure):
            ixigua.resolve('https://v.ixigua.com/abc/')

    def test_wrong_identity_live_paid_and_unreadable_page(self):
        for video in [{'gid': '0', 'title': 'Other'}, {'gid': ID, 'title': 'Live', 'is_live': True}]:
            with patch.object(ixigua, 'read_text', return_value=page(video)), self.assertRaises(Failure):
                ixigua.resolve(URL)
        with patch.object(ixigua, 'read_text', return_value=page({'gid': ID, 'title': 'Paid', 'is_pay': True})):
            result = ixigua.resolve(URL, need=['video'])
        self.assertEqual(result['diagnostics'][0]['code'], 'access_denied')
        with patch.object(ixigua, 'read_text', return_value='<script>challenge()</script>'), self.assertRaises(Failure) as exc:
            ixigua.resolve(URL, cookies='explicit.txt')
        self.assertEqual(exc.exception.code, 'page_unavailable')

    def test_invalid_media_and_protected_entries_not_offered(self):
        video = {'gid': ID, 'title': 'Demo', 'videoResource': {'normal': {'video_list': {'a': {'main_url': '???'}, 'b': resource('file:///private/file'), 'c': resource('https://cdn.test/drm', is_drm=True)}}}}
        with patch.object(ixigua, 'read_text', return_value=page(video)):
            result = ixigua.resolve(URL, need=['video'])
        self.assertEqual(result['formats'], [])
        self.assertEqual(result['diagnostics'][0]['code'], 'media_unavailable')

    def test_nonvideo_and_deceptive_hosts_do_not_request(self):
        for url in ['https://www.ixigua.com/home/123', 'https://www.ixigua.com.evil.test/' + ID, 'https://toutiao.com/article/123']:
            with patch.object(ixigua, 'read_text') as read, self.assertRaises(Failure):
                ixigua.resolve(url)
            read.assert_not_called()

    def test_anonymous_mobile_metadata_has_exact_identity_and_explicit_media_limit(self):
        mobile = {'data': {'storeState': {'detail': {'videoData': {'result': {'gid': ID, 'title': 'Clock', 'duration': 168.47,
            'media_user': {'screen_name': 'Math teacher'}, 'play_count': 818, 'url': 'opaque'}}}}}}
        payload = '<script>window._SSR_DATA = ' + json.dumps(mobile) + '</script>'
        with patch.object(ixigua, 'read_text', return_value='<script>challenge()</script>'), patch('scripts.browser.browser_page', return_value=payload) as browser:
            result = ixigua.resolve(URL, need=['info', 'video'])
        self.assertEqual(result['metadata']['author'], 'Math teacher')
        self.assertEqual(result['metadata']['duration'], 168.47)
        self.assertEqual(result['formats'], [])
        self.assertEqual(result['diagnostics'][0]['code'], 'parse_failed')
        self.assertTrue(browser.call_args.kwargs['ready'](payload))

    def test_mobile_native_address_envelope_and_invalid_padding(self):
        # Deterministic CryptoJS-compatible public address envelope, distinct
        # from media encryption. The decoded result remains an ordinary URL.
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives.padding import PKCS7
        import hashlib
        salt, derived, previous = b'12345678', b'', b''
        while len(derived) < 48:
            previous = hashlib.md5(previous + b'xigua.fe.web_mobile' + salt).digest()
            derived += previous
        padder = PKCS7(128).padder()
        clear = padder.update(b'https://v6-xgwap.ixigua.com/native.mp4') + padder.finalize()
        encryptor = Cipher(algorithms.AES(derived[:32]), modes.CBC(derived[32:48])).encryptor()
        payload = b'Salted__' + salt + encryptor.update(clear) + encryptor.finalize()
        encoded = base64.b64encode(payload).decode()[::-1]
        self.assertEqual(ixigua._mobile_address(encoded), 'https://v6-xgwap.ixigua.com/native.mp4')
        for invalid in ['opaque', base64.b64encode(b'Salted__' + salt + b'broken').decode()[::-1]]:
            with self.assertRaises(Failure):
                ixigua._mobile_address(invalid)

    def test_mobile_info_does_not_decode_or_offer_media(self):
        mobile = {'data': {'storeState': {'detail': {'videoData': {'result': {'gid': ID, 'title': 'Clock', 'url': 'opaque'}}}}}}
        payload = '<script>window._SSR_DATA=' + json.dumps(mobile) + '</script>'
        with patch.object(ixigua, 'read_text', return_value=payload), patch.object(ixigua, '_mobile_address') as decode:
            result = ixigua.resolve(URL, need=['info'])
        decode.assert_not_called()
        self.assertEqual(result['formats'], [])
        self.assertEqual(result['diagnostics'], [])

    def test_share_guard_runs_before_shared_redirect_handler(self):
        opener = ixigua._opener()
        guard = ixigua._ShareRedirect()
        opener.add_handler(guard)
        handlers = opener.handle_open.get('http', [])
        redirect_handlers = opener.handle_error['http'][302]
        self.assertIs(redirect_handlers[0], guard)

    def test_nonstandard_malformed_and_share_redirect_ports_are_rejected(self):
        for url in [URL.replace('www.ixigua.com', 'www.ixigua.com:8443'), URL.replace('www.ixigua.com', 'www.ixigua.com:bad'), 'https://[bad/']:
            self.assertIsNone(ixigua._identity(url))
            with patch.object(ixigua, 'read_text') as read, self.assertRaises(Failure) as exc:
                ixigua.resolve(url)
            self.assertEqual(exc.exception.code, 'invalid_url')
            read.assert_not_called()
        self.assertEqual(ixigua._identity(URL.replace('www.ixigua.com', 'www.ixigua.com:443')), ID)
        with self.assertRaises(Failure):
            ixigua._ShareRedirect().redirect_request(None, None, 302, '', {}, URL.replace('www.ixigua.com', 'www.ixigua.com:bad'))
