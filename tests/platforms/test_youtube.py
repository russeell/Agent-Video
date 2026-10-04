"""YouTube player request and subtitle provenance, without network requests."""
import json
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from scripts import streams
from scripts.platforms import Failure, select_formats, select_subtitle, youtube


class YouTubeTest(unittest.TestCase):
    def test_embedded_public_data(self):
        data = {'videoDetails': {'videoId': 'abcdefghijk', 'title': 'Video'}}
        self.assertEqual(youtube._player('ytInitialPlayerResponse = ' + json.dumps(data) + ';'), data)

    def watch_html(self, extra=None):
        player = {'videoDetails': {'title': 'Public video', 'lengthSeconds': '30'},
                  'playabilityStatus': {'status': 'OK'}}
        player.update(extra or {})
        return ('ytInitialPlayerResponse = ' + json.dumps(player) + ';'
                '"STS":20725,"VISITOR_DATA":"public-visitor","INNERTUBE_API_KEY":"web-key"')

    def test_one_player_request_and_exact_caption_format(self):
        player = {'playabilityStatus': {'status': 'OK'},
                  'captions': {'playerCaptionsTracklistRenderer': {'captionTracks': [
                      {'baseUrl': 'https://www.youtube.com/api/timedtext?v=abcdefghijk&fmt=srv3&fmt=vtt&lang=zh',
                       'languageCode': 'zh'},
                      {'baseUrl': 'https://www.youtube.com/api/timedtext?lang=en',
                       'languageCode': 'en', 'kind': 'asr'}]}},
                  'streamingData': {'formats': [{'url': 'https://example.com/video.mp4',
                                                'mimeType': 'video/mp4', 'audioChannels': 2}]}}
        with patch.object(youtube, 'read_text', return_value=self.watch_html()), \
             patch.object(youtube, 'read_json', return_value=player) as post:
            result = youtube.resolve('https://youtu.be/abcdefghijk', cookies='user-cookie-file',
                                     need=['info', 'video', 'transcript'])
        post.assert_called_once()
        endpoint = post.call_args.args[0]
        options = post.call_args.kwargs
        payload = json.loads(options['data'])
        self.assertEqual(parse_qs(urlsplit(endpoint).query), {'prettyPrint': ['false']})
        self.assertEqual(payload['context']['client']['clientName'], 'VISIONOS')
        self.assertEqual(payload['playbackContext']['contentPlaybackContext']['signatureTimestamp'], 20725)
        self.assertTrue(payload['contentCheckOk'])
        self.assertEqual(options['headers']['X-Goog-Visitor-Id'], 'public-visitor')
        self.assertEqual(options['cookies'], 'user-cookie-file')
        self.assertEqual(parse_qs(urlsplit(result['subtitles'][0]['url']).query)['fmt'], ['json3'])
        self.assertEqual([t['origin'] for t in result['subtitles']], ['platform_manual', 'platform_auto'])
        self.assertEqual(len(result['formats']), 1)

    def test_original_audio_metadata_survives_player_replacement(self):
        web = {'streamingData': {'adaptiveFormats': [{'signatureCipher': 'unusable',
                'audioTrack': {'id': 'zh-Hant.4', 'audioIsDefault': False,
                               'displayName': 'Chinese (Traditional) original'}}]}}
        player = {'playabilityStatus': {'status': 'OK'}, 'captions': {
            'playerCaptionsTracklistRenderer': {
                'audioTracks': [{'defaultCaptionTrackIndex': 1, 'captionTrackIndices': [0, 1]}],
                'captionTracks': [{'baseUrl': 'https://example.com/zh', 'languageCode': 'zh'},
                                 {'baseUrl': 'https://example.com/en', 'languageCode': 'en'}]}}}
        with patch.object(youtube, 'read_text', return_value=self.watch_html(web)), \
             patch.object(youtube, 'read_json', return_value=player):
            result = youtube.resolve('https://youtu.be/abcdefghijk', need=['transcript'])
        self.assertEqual(result['metadata']['original_language'], 'zh-Hant')
        self.assertEqual(select_subtitle(result['subtitles'], original_language='zh-Hant')['language'], 'zh')
        self.assertIsNone(youtube._original_language(player))
        self.assertIsNone(youtube._original_language({'streamingData': {'formats': [
            {'audioTrack': {'id': 'en.1', 'audioIsDefault': True, 'isAutoDubbed': True}}]}}))
        self.assertIsNone(youtube._original_language({'streamingData': {'formats': [
            {'audioTrack': {'id': 'en.1', 'audioIsDefault': True, 'isAutoDubbed': False,
                            'displayName': 'English dubbed'}}]}}))

    def test_info_only_and_failed_player_keep_information(self):
        with patch.object(youtube, 'read_text', return_value=self.watch_html()), \
             patch.object(youtube, 'read_json') as post:
            info = youtube.resolve('https://youtu.be/abcdefghijk', need=['info'])
        post.assert_not_called()
        self.assertEqual(info['metadata']['title'], 'Public video')
        with patch.object(youtube, 'read_text', return_value=self.watch_html()), \
             patch.object(youtube, 'read_json', return_value={
                 'playabilityStatus': {'status': 'LOGIN_REQUIRED', 'reason': 'Sign in'}}) as post:
            result = youtube.resolve('https://youtu.be/abcdefghijk', need=['info', 'transcript'])
        post.assert_called_once()
        self.assertEqual(result['metadata']['title'], 'Public video')
        self.assertEqual(result['subtitles'], [])
        self.assertEqual([(d['stage'], d['code']) for d in result['diagnostics']],
                         [('transcript', 'auth_required')])
        with self.subTest('player belongs to another video'), \
             patch.object(youtube, 'read_json', return_value={
                 'videoDetails': {'videoId': 'other-video'}, 'playabilityStatus': {'status': 'OK'}}):
            with self.assertRaises(Failure) as caught:
                youtube._innertube_player(self.watch_html(), 'abcdefghijk')
            self.assertEqual(caught.exception.code, 'parse_failed')


class YouTubeMediaTest(unittest.TestCase):
    def test_direct_formats_use_full_range_only_for_known_positive_size(self):
        for length, expected in [('7285379', 'bytes=0-7285378'), (1, 'bytes=0-0'),
                                 (None, None), ('', None), ('unknown', None),
                                 ('-1', None), ('1.5', None), ('0', None), (0, None)]:
            raw = [{'url': 'https://example.com/audio', 'mimeType': 'audio/webm',
                    'contentLength': length}]
            with self.subTest(length=length):
                formats, _, diagnostics, _ = youtube._media_formats({'streamingData': {'adaptiveFormats': raw}})
                self.assertEqual(formats[0]['headers'].get('Range'), expected)
                self.assertEqual(formats[0]['headers']['User-Agent'], youtube.VISIONOS_CLIENT['userAgent'])
                self.assertEqual(diagnostics, [])

    def test_original_direct_audio_precedes_higher_bitrate_dubbed_audio(self):
        raw = [{'url': 'https://example.com/video', 'mimeType': 'video/mp4',
                'width': 1080, 'height': 1920, 'fps': 30},
               {'url': 'https://example.com/original', 'mimeType': 'audio/webm', 'bitrate': 120000,
                'audioTrack': {'id': 'zh-Hant.4', 'audioIsDefault': True,
                               'displayName': 'Chinese (Traditional) original (default)'}},
               {'url': 'https://example.com/dubbed', 'mimeType': 'audio/webm', 'bitrate': 200000,
                'audioTrack': {'id': 'en-US.10', 'audioIsDefault': True, 'isAutoDubbed': True}}]
        with patch.object(streams, '_fetch') as fetch:
            formats, language, diagnostics, expected_audio = youtube._media_formats(
                {'streamingData': {'adaptiveFormats': raw, 'hlsManifestUrl': 'https://example.com/master'}},
                want_video=False)
        fetch.assert_not_called()
        self.assertEqual(select_formats(formats, want_video=False)[0]['url'], 'https://example.com/original')
        self.assertEqual(language, 'zh-Hant')
        self.assertTrue(expected_audio)
        self.assertEqual(diagnostics, [])
        with self.subTest('a manual dub is not original merely because it is not auto dubbed'):
            raw[-1]['audioTrack'].update(isAutoDubbed=False, displayName='English dubbed')
            with patch.object(streams, '_fetch'):
                formats, language, diagnostics, expected_audio = youtube._media_formats(
                    {'streamingData': {'adaptiveFormats': raw}}, want_video=False)
            self.assertEqual(select_formats(formats, want_video=False)[0]['url'], 'https://example.com/original')

    def test_direct_original_audio_does_not_drop_matching_hls_rendition(self):
        player = {'streamingData': {'adaptiveFormats': [
            {'url': 'https://example.com/direct-video', 'mimeType': 'video/mp4',
             'width': 1080, 'height': 1920, 'fps': 30, 'bitrate': 2000000},
            {'url': 'https://example.com/direct-original', 'mimeType': 'audio/mp4',
             'bitrate': 130000, 'audioTrack': {'id': 'zh-Hant.4', 'audioIsDefault': True,
                'displayName': 'Chinese (Traditional) original'}}],
            'hlsManifestUrl': 'https://example.com/master.m3u8'}}
        master = '''#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="234",NAME="English dubbed-auto",LANGUAGE="en-US",DEFAULT=NO,URI="dub.m3u8"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="234",NAME="Chinese original",LANGUAGE="zh-Hant",DEFAULT=NO,URI="original.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=5713164,RESOLUTION=1080x1920,FRAME-RATE=30,AUDIO="234"
premium.m3u8
'''
        with patch.object(streams, '_fetch', return_value=('https://example.com/master.m3u8', master)):
            formats, language, diagnostics, expected_audio = youtube._media_formats(player)
        selected = select_formats(formats, quality='source')
        self.assertEqual([f['url'] for f in selected],
                         ['https://example.com/premium.m3u8', 'https://example.com/original.m3u8'])
        self.assertEqual(language, 'zh-Hant')
        self.assertTrue(expected_audio)
        self.assertEqual(diagnostics, [])

    def test_hls_external_audio_uses_original_from_best_variant_group(self):
        master = '''#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="low",NAME="American English - dubbed-auto",LANGUAGE="en-US",DEFAULT=NO,URI="dub-low.m3u8"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="low",NAME="zh-Hant - original",LANGUAGE="zh-Hant",DEFAULT=NO,URI="original-low.m3u8"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="high",NAME="American English - dubbed-auto",LANGUAGE="en-US",DEFAULT=NO,URI="dub-high.m3u8"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="high",NAME="zh-Hant - original",LANGUAGE="zh-Hant",DEFAULT=NO,URI="original-high.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=400000,CODECS="avc1.4d4015,mp4a.40.5",RESOLUTION=240x426,FRAME-RATE=30,AUDIO="low"
low.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2900000,CODECS="vp09.00.40.08,mp4a.40.2",RESOLUTION=1080x1920,FRAME-RATE=30,AUDIO="high"
normal.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=5713164,CODECS="vp09.00.40.08,mp4a.40.2",RESOLUTION=1080x1920,FRAME-RATE=30,AUDIO="high"
premium.m3u8
'''
        with patch.object(streams, '_fetch', return_value=('https://example.com/master.m3u8', master)) as fetch:
            formats, language, diagnostics, expected_audio = youtube._media_formats(
                {'streamingData': {'hlsManifestUrl': 'https://example.com/master.m3u8'}}, cookies='explicit-cookies')
        fetch.assert_called_once()
        self.assertEqual(fetch.call_args.args[1], 'explicit-cookies')
        selected = select_formats(formats)
        self.assertEqual([f['url'] for f in selected],
                         ['https://example.com/premium.m3u8', 'https://example.com/original-high.m3u8'])
        self.assertFalse(selected[0]['has_audio'])
        self.assertTrue(selected[1]['has_audio'])
        self.assertFalse(selected[1]['has_video'])
        self.assertEqual(language, 'zh-Hant')
        self.assertTrue(expected_audio)
        self.assertEqual(diagnostics, [])
        with self.subTest('unknown multiple audio tracks must not be guessed'):
            ambiguous = master.replace('zh-Hant - original', 'Chinese')
            with self.assertRaises(Failure) as caught:
                youtube._hls_formats(ambiguous, 'https://example.com/master.m3u8')
            self.assertEqual(caught.exception.code, 'audio_ambiguous')
        with self.subTest('pure frames do not require selecting ambiguous HLS audio'):
            html = 'ytInitialPlayerResponse = ' + json.dumps({
                'videoDetails': {'title': 'Frames video', 'lengthSeconds': '30'}}) + ';'
            player = {'playabilityStatus': {'status': 'OK'},
                      'streamingData': {'hlsManifestUrl': 'https://example.com/master.m3u8'}}
            for needs, require_audio in [(['frames', 'info'], False), (['frames', 'media'], False),
                                        (['video'], True), (['frames', 'transcript'], True), (['media'], True)]:
                with self.subTest(needs=needs), \
                     patch.object(youtube, 'read_text', return_value=html), \
                     patch.object(youtube, 'read_json', return_value=player), \
                     patch.object(streams, '_fetch', return_value=('https://example.com/master.m3u8', ambiguous)):
                    result = youtube.resolve('https://youtu.be/abcdefghijk', need=needs)
                self.assertTrue(result['metadata']['audio_expected'])
                if require_audio:
                    self.assertIn('audio_ambiguous', [d['code'] for d in result['diagnostics']])
                    self.assertEqual(result['formats'], [])
                else:
                    self.assertEqual(len(result['formats']), 3)
                    self.assertTrue(all(f['has_video'] and f['has_audio'] is False for f in result['formats']))
                    self.assertEqual(result['diagnostics'], [])
        with self.subTest('undeclared audio stays unknown'):
            unknown = master.replace(',AUDIO="low"', '').replace(',AUDIO="high"', '')
            with patch.object(streams, '_fetch', return_value=('https://example.com/master.m3u8', unknown)):
                formats, language, diagnostics, expected_audio = youtube._media_formats(
                    {'streamingData': {'hlsManifestUrl': 'https://example.com/master.m3u8'}}, want_audio=False)
            self.assertIsNone(expected_audio)

    def test_hls_failure_retains_direct_video_and_missing_audio_diagnostic(self):
        player = {'streamingData': {'hlsManifestUrl': 'https://example.com/master', 'adaptiveFormats': [
            {'url': 'https://example.com/video', 'mimeType': 'video/mp4', 'width': 1080, 'height': 1920},
            {'signatureCipher': 'unsupported', 'mimeType': 'audio/webm',
             'audioTrack': {'id': 'zh.1', 'audioIsDefault': True, 'displayName': 'Chinese original'}}]}}
        with patch.object(streams, '_fetch', side_effect=Failure('network_failed', 'HLS request failed.')):
            formats, language, diagnostics, expected_audio = youtube._media_formats(player)
        self.assertEqual([f['url'] for f in formats], ['https://example.com/video'])
        self.assertTrue(expected_audio)
        self.assertEqual([d['code'] for d in diagnostics], ['network_failed', 'audio_unavailable'])
        with self.subTest('ambiguous HLS audio cannot turn a direct video into a silent full delivery'):
            player['streamingData']['adaptiveFormats'] = player['streamingData']['adaptiveFormats'][:1]
            with patch.object(streams, '_fetch', return_value=('https://example.com/master', '#EXTM3U')), \
                 patch.object(youtube, '_hls_formats', side_effect=Failure('audio_ambiguous', 'No original audio identified.')):
                formats, language, diagnostics, expected_audio = youtube._media_formats(player)
            self.assertEqual([f['url'] for f in formats], ['https://example.com/video'])
            self.assertTrue(expected_audio)
            self.assertEqual(diagnostics[0]['code'], 'audio_ambiguous')
            with patch.object(streams, '_fetch', side_effect=Failure('network_failed', 'Master unavailable.')):
                formats, language, diagnostics, expected_audio = youtube._media_formats(player)
            self.assertIsNone(expected_audio)
            self.assertEqual([f['url'] for f in formats], ['https://example.com/video'])
            self.assertEqual([d['code'] for d in diagnostics], ['network_failed', 'audio_unavailable'])


if __name__ == '__main__':
    unittest.main()
