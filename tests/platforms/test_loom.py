import unittest
from unittest.mock import patch
from scripts.platforms import Failure, loom

ID = 'a' * 32
URL = 'https://www.loom.com/share/' + ID
VIDEO = {'__typename': 'RegularUserVideo', 'id': ID, 'name': 'Demo', 'video_properties': {'duration': 7}}


class LoomTests(unittest.TestCase):
    def test_info_never_fetches_media_or_subtitles(self):
        with patch.object(loom, '_graphql', return_value={'getVideo': VIDEO}) as call, patch.object(loom, 'read_json') as read:
            result = loom.resolve(URL, need=['info'])
        self.assertEqual(call.call_count, 1)
        read.assert_not_called()
        self.assertEqual(result['formats'], [])
        self.assertIsNone(result['metadata']['original_language'])

    def test_caption_language_unknown_and_transcript_does_not_get_media(self):
        with patch.object(loom, '_graphql', side_effect=[{'getVideo': VIDEO}, {'fetchVideoTranscript': {'captions_source_url': 'https://cdn.test/sub.vtt'}}]), patch.object(loom, 'read_json') as read:
            result = loom.resolve(URL, need=['transcript'])
        read.assert_not_called()
        self.assertEqual(result['subtitles'][0]['language'], '')
        self.assertEqual(result['formats'], [])

    def test_public_identity_required(self):
        for video in ({'__typename': 'PrivateVideo'}, {**VIDEO, 'id': 'b' * 32}):
            with patch.object(loom, '_graphql', return_value={'getVideo': video}), self.assertRaises(Failure):
                loom.resolve(URL)

    def test_progressive_is_ephemeral(self):
        with patch.object(loom, '_graphql', return_value={'getVideo': VIDEO}), patch.object(loom, 'read_json', return_value={'url': 'https://cdn.test/video.mp4?sig=secret'}):
            result = loom.resolve(URL, need=['video'])
        self.assertEqual(result['formats'][0]['ext'], 'mp4')
        self.assertTrue(result['formats'][0]['is_original'])
        self.assertIsNone(result['formats'][0]['has_audio'])
        self.assertNotIn('secret', str(result['metadata']))

    def test_reject_folder_and_other_host_before_network(self):
        with patch.object(loom, '_graphql') as call:
            for url in ('https://loom.com/share/folder/' + ID, 'https://evil.test/share/' + ID):
                with self.assertRaises(Failure):
                    loom.resolve(url)
        call.assert_not_called()

    def test_json_only_is_not_claimed_absent_or_title_used_as_transcript(self):
        with patch.object(loom, '_graphql', side_effect=[{'getVideo': VIDEO}, {'fetchVideoTranscript': {'source_url': 'https://cdn.test/transcript.json'}}]):
            result = loom.resolve(URL, need=['transcript'])
        self.assertEqual(result['subtitles'], [])
        self.assertEqual(result['diagnostics'][0]['code'], 'subtitle_format_unsupported')

    def test_signed_hls_passes_explicit_child_query_and_track_declarations(self):
        address = 'https://cdn.test/master.m3u8?Signature=secret'
        formats = [{'url': 'https://cdn.test/video.m3u8?Signature=secret', 'has_video': True, 'has_audio': False},
                   {'url': 'https://cdn.test/audio.m3u8?Signature=secret', 'has_video': False, 'has_audio': True}]
        with patch.object(loom, '_graphql', return_value={'getVideo': VIDEO}), patch.object(loom, 'read_json', return_value={'url': address}) as api, patch('scripts.streams._fetch', return_value=(address, '#EXTM3U')), patch('scripts.streams.hls_formats', return_value=(formats, None)) as hls:
            result = loom.resolve(URL, need=['video'])
        self.assertIn('/raw-url', api.call_args.args[0])
        self.assertEqual(hls.call_args.kwargs['segment_query'], 'Signature=secret')
        self.assertFalse(result['formats'][0]['has_audio'])
        self.assertTrue(result['formats'][1]['has_audio'])
        self.assertNotIn('secret', str(result['metadata']))

    def test_redirected_hls_does_not_forward_original_signature_to_other_origin(self):
        address = 'https://cdn.test/master.m3u8?Signature=private'
        for final, expected in [('https://other.test/master.m3u8', None), ('https://other.test/master.m3u8?cdn=own', 'cdn=own')]:
            with patch.object(loom, '_graphql', return_value={'getVideo': VIDEO}), patch.object(loom, 'read_json', return_value={'url': address}), patch('scripts.streams._fetch', return_value=(final, '#EXTM3U')), patch('scripts.streams.hls_formats', return_value=([{'url': final, 'has_video': True}], None)) as hls:
                loom.resolve(URL, need=['video'])
            self.assertEqual(hls.call_args.kwargs['segment_query'], expected)
