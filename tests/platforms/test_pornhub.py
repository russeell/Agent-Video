import json
import unittest
from unittest.mock import patch
from scripts import platforms
from scripts.platforms import pornhub


def page(data):
    return 'var flashvars_42 = ' + json.dumps({'link_url': 'https://cn.pornhub.com/view_video.php?viewkey=phabc123', **data}) + ';'


class PornhubTests(unittest.TestCase):
    def test_identity_is_strict_and_preserves_localized_host(self):
        self.assertEqual(pornhub._identity('https://cn.pornhub.com/embed/phabc123'), ('phabc123', 'cn.pornhub.com'))
        for address in ['https://pornhub.com/model/example', 'https://pornhubpremium.com/embed/phabc123',
                        'https://evil.test/view_video.php?viewkey=phabc123',
                        'https://pornhub.com/view_video.php?viewkey=phabc123&viewkey=phdef456']:
            with self.assertRaises(platforms.Failure):
                pornhub._identity(address)

    def test_json_only_no_javascript_evaluation_or_other_work(self):
        with self.assertRaises(platforms.Failure):
            pornhub._flashvars('var flashvars_42 = executeCode();', 'phabc123')
        with self.assertRaises(platforms.Failure):
            pornhub._flashvars(page({'link_url': 'https://pornhub.com/embed/phdef456'}), 'phabc123')
        self.assertEqual(pornhub._flashvars(page({'video_duration': 10}), 'phabc123')['video_duration'], 10)

    def test_info_only_does_not_request_media_metadata(self):
        data = {'video_duration': '10', 'video_unavailable': 'false', 'video_unavailable_country': 'false', 'mediaDefinitions': [{'format': 'mp4', 'videoUrl': 'https://cn.pornhub.com/video/get_media?id=42'}]}
        with patch.object(pornhub, 'read_text', return_value=page(data)) as read, patch.object(pornhub, 'read_json') as metadata:
            result = pornhub.resolve('https://cn.pornhub.com/embed/phabc123', need=['info'])
        self.assertEqual(read.call_count, 1)
        metadata.assert_not_called()
        self.assertEqual(result['formats'], [])
        self.assertEqual(result['metadata']['duration'], 10)
        self.assertEqual(result['source']['url'], 'https://cn.pornhub.com/view_video.php?viewkey=phabc123')

    def test_captions_are_native_srt_not_description(self):
        with patch.object(pornhub, 'read_text', return_value=page({'closedCaptionsFile': 'https://cdn.test/captions.srt'})):
            result = pornhub.resolve('https://cn.pornhub.com/embed/phabc123', need=['transcript'])
        self.assertEqual(result['subtitles'][0]['ext'], 'srt')
        self.assertEqual(result['subtitles'][0]['language'], '')
        self.assertEqual(result['formats'], [])

    def test_mp4_metadata_and_highest_quality(self):
        data = {'mediaDefinitions': [{'format': 'mp4', 'videoUrl': 'https://cn.pornhub.com/video/get_media?id=42'}]}
        resources = [{'format': 'mp4', 'quality': '720', 'videoUrl': 'https://cdn.test/720.mp4'},
                     {'format': 'mp4', 'quality': '1080', 'videoUrl': 'https://cdn.test/1080.mp4'}]
        with patch.object(pornhub, 'read_text', return_value=page(data)), patch.object(pornhub, 'read_json', return_value=resources):
            result = pornhub.resolve('https://cn.pornhub.com/embed/phabc123', need=['video'])
        chosen = platforms.select_formats(result['formats'], quality='source')[0]
        self.assertEqual(chosen['height'], 1080)
        self.assertIsNone(chosen['has_audio'])
        self.assertIsNone(result['metadata']['audio_expected'])
        self.assertEqual(chosen['headers']['Origin'], 'https://cn.pornhub.com')

    def test_mp4_metadata_reuses_page_session(self):
        data = {'mediaDefinitions': [{'format': 'mp4', 'videoUrl': 'https://cn.pornhub.com/video/get_media?id=42'}]}
        session = object()
        with patch.object(pornhub, '_opener', return_value=session), patch.object(pornhub, 'read_text', return_value=page(data)) as read, patch.object(pornhub, 'read_json', return_value=[]) as metadata:
            pornhub.resolve('https://cn.pornhub.com/embed/phabc123', need=['video'])
        self.assertIs(read.call_args.kwargs['opener'], session)
        self.assertIs(metadata.call_args.kwargs['opener'], session)

    def test_access_failure_preserves_info_and_expected_headers(self):
        data = {'video_duration': 10, 'mediaDefinitions': [{'format': 'hls', 'videoUrl': 'https://cdn.test/master.m3u8'}]}
        with patch.object(pornhub, 'read_text', return_value=page(data)), patch('scripts.streams._fetch', side_effect=platforms.Failure('access_denied', 'HTTP 412')) as fetch:
            result = pornhub.resolve('https://cn.pornhub.com/embed/phabc123', need=['video'])
        self.assertEqual(result['metadata']['duration'], 10)
        self.assertEqual(result['diagnostics'][0]['code'], 'access_denied')
        self.assertEqual(fetch.call_args.args[2]['Referer'], 'https://cn.pornhub.com/')

    def test_drm_is_not_offered_as_downloadable(self):
        data = {'mediaDefinitions': [{'format': 'hls', 'videoUrl': 'https://cdn.test/master.m3u8'}]}
        encrypted = '#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI="skd://protected"\n'
        with patch.object(pornhub, 'read_text', return_value=page(data)), patch('scripts.streams._fetch', return_value=('https://cdn.test/master.m3u8', encrypted)):
            result = pornhub.resolve('https://cn.pornhub.com/embed/phabc123', need=['video'])
        self.assertEqual(result['formats'], [])
        self.assertEqual(result['diagnostics'][0]['code'], 'encrypted_stream_unsupported')

    def test_explicit_unavailable_flag_denies_access(self):
        with patch.object(pornhub, 'read_text', return_value=page({'video_unavailable': 'true'})):
            with self.assertRaises(platforms.Failure) as error:
                pornhub.resolve('https://cn.pornhub.com/embed/phabc123', need=['info'])
        self.assertEqual(error.exception.code, 'access_denied')
