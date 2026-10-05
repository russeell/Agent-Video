import unittest
import json
from unittest.mock import patch
from scripts.platforms import Failure, select_formats, vimeo


class VimeoTests(unittest.TestCase):
    def test_denied_config_uses_matching_embed_json_with_public_hash(self):
        config = {'video': {'id': 42, 'title': 'Public demo', 'duration': 82},
                  'request': {'text_tracks': [{'url': '/captions/en.vtt', 'lang': 'en'}]}}
        page = '<script>var playerConfig = ' + json.dumps(config) + '; initialize(playerConfig);</script>'
        with (patch.object(vimeo, 'read_json', side_effect=Failure('access_denied', 'HTTP 403')),
              patch('scripts.platforms.read_browser_text', return_value=page) as read):
            result = vimeo.resolve('https://player.vimeo.com/video/42?h=abc', need=['transcript'], cookies='explicit.txt')
        self.assertEqual(result['metadata']['duration'], 82)
        self.assertEqual(result['formats'], [])
        self.assertEqual(result['subtitles'][0]['language'], 'en')
        read.assert_called_once_with('https://player.vimeo.com/video/42?h=abc', cookies='explicit.txt',
                                     headers={'Referer': 'https://vimeo.com/42/abc'})

    def test_embed_fallback_rejects_wrong_identity_and_non_json(self):
        for page in ('<script>var playerConfig = {"video":{"id":99}};</script>',
                     '<script>var playerConfig = {"video":"unexpected"};</script>',
                     '<script>var playerConfig = makePlayerData();</script>'):
            with (self.subTest(page=page), patch.object(vimeo, 'read_json', side_effect=Failure('access_denied', 'HTTP 403')),
                  patch('scripts.platforms.read_browser_text', return_value=page)):
                with self.assertRaises(Failure) as error:
                    vimeo.resolve('https://vimeo.com/42', need=['info'])
            self.assertEqual(error.exception.code, 'parse_failed')

    def test_embed_fallback_does_not_retry_other_failures(self):
        with (patch.object(vimeo, 'read_json', side_effect=Failure('network_failed', 'HTTP 404')),
              patch('scripts.platforms.read_browser_text') as read):
            with self.assertRaises(Failure) as error:
                vimeo.resolve('https://vimeo.com/42', need=['info'])
        self.assertEqual(error.exception.code, 'network_failed')
        read.assert_not_called()

    def test_info_and_transcript_do_not_request_media(self):
        config = {'video': {'id': 42, 'title': 'Demo', 'duration': 7}, 'request': {
            'text_tracks': [{'url': '/captions/42.vtt', 'lang': 'en'}],
            'files': {'progressive': [{'url': 'https://cdn.test/video.mp4', 'width': 1920, 'height': 1080}]}}}
        with patch.object(vimeo, 'read_json', return_value=config) as read:
            result = vimeo.resolve('https://player.vimeo.com/video/42?h=abc', need=['transcript'])
        self.assertEqual(read.call_count, 1)
        self.assertIn('h=abc', read.call_args.args[0])
        self.assertEqual(result['formats'], [])
        self.assertEqual(result['subtitles'][0]['url'], 'https://player.vimeo.com/captions/42.vtt')
        self.assertEqual(result['source']['url'], 'https://vimeo.com/42/abc')

    def test_highest_progressive_audio_is_unknown_without_declaration(self):
        config = {'video': {'id': 42}, 'request': {'files': {'progressive': [
            {'url': 'https://cdn.test/720.mp4', 'width': 1280, 'height': 720},
            {'url': 'https://cdn.test/2160.mp4', 'width': 3840, 'height': 2160}]}}}
        with patch.object(vimeo, 'read_json', return_value=config):
            result = vimeo.resolve('https://vimeo.com/42', need=['video'])
        selected = select_formats(result['formats'], quality='source')
        self.assertEqual(selected[0]['height'], 2160)
        self.assertIsNone(selected[0]['has_audio'])
        self.assertIsNone(result['metadata']['audio_expected'])

    def test_wrong_identity_and_non_single_video(self):
        with patch.object(vimeo, 'read_json', return_value={'video': {'id': 99}}):
            with self.assertRaises(Failure):
                vimeo.resolve('https://vimeo.com/42')
        with self.assertRaises(Failure):
            vimeo.resolve('https://vimeo.com/channels/staffpicks')

    def test_drm_not_offered_as_downloadable_candidate(self):
        config = {'video': {'id': 42}, 'request': {'files': {'hls': {'cdns': {
            'default': {'url': 'https://cdn.test/drm/cbcs/master.m3u8'}}}}}}
        with patch.object(vimeo, 'read_json', return_value=config):
            result = vimeo.resolve('https://vimeo.com/42', need=['video'])
        self.assertEqual(result['formats'], [])
        self.assertEqual(result['diagnostics'][0]['code'], 'encrypted_stream_unsupported')

    def test_explicit_channel_layout_preserves_audio_expectation(self):
        with patch.object(vimeo, 'read_json', return_value={'video': {'id': 42, 'channel_layout': 'stereo'}}):
            result = vimeo.resolve('https://vimeo.com/42', need=['info'])
        self.assertTrue(result['metadata']['audio_expected'])

    def test_explicit_video_only_hls_remains_video_only(self):
        config = {'video': {'id': 42}, 'request': {'files': {'hls': {'cdns': {
            'default': {'url': 'https://cdn.test/master.m3u8'}}}}}}
        video = {'url': 'https://cdn.test/video.m3u8', 'protocol': 'hls', 'ext': 'm3u8',
                 'has_video': True, 'has_audio': False, 'width': 1280, 'height': 720}
        with patch.object(vimeo, 'read_json', return_value=config), patch('scripts.streams._fetch', return_value=('https://cdn.test/master.m3u8', '#EXTM3U')), patch('scripts.streams.hls_formats', return_value=([video], None)):
            result = vimeo.resolve('https://vimeo.com/42', need=['frames'])
        self.assertFalse(result['formats'][0]['has_audio'])
        self.assertIsNone(result['metadata']['audio_expected'])
        with self.assertRaises(Failure) as error:
            select_formats(result['formats'], want_video=False)
        self.assertEqual(error.exception.code, 'no_audio')

    def test_signed_separate_hls_url_is_not_rewritten(self):
        address = 'https://cdn.test/signed/sep/video/master.m3u8?sig=original'
        config = {'video': {'id': 42}, 'request': {'files': {'hls': {'cdns': {'default': {'url': address}}}}}}
        with patch.object(vimeo, 'read_json', return_value=config), patch('scripts.streams._fetch', return_value=(address, '#EXTM3U')) as fetch, patch('scripts.streams.hls_formats', return_value=([], None)):
            vimeo.resolve('https://vimeo.com/42', need=['video'])
        self.assertEqual(fetch.call_args.args[0], address)
