import unittest
from unittest.mock import patch
from scripts.platforms import Failure, googledrive, select_formats

ID = 'a' * 28
URL = 'https://drive.google.com/file/d/' + ID + '/view'
VIDEO = {'mediaMetadata': {'title': 'Demo.mp4', 'duration': '9.999s'}, 'timedTextDetails': {'timedTextBaseUrl': 'https://drive.google.com/timedtext?sig=secret'}}


class GoogleDriveTests(unittest.TestCase):
    def test_info_no_caption_or_download_request(self):
        with patch.object(googledrive, 'read_json', return_value=VIDEO) as read, patch.object(googledrive, 'read_text') as text:
            result = googledrive.resolve(URL, need=['info'])
        self.assertEqual(read.call_count, 1)
        text.assert_not_called()
        self.assertEqual(result['metadata']['duration'], 9.999)
        self.assertNotIn('secret', str(result['metadata']))
        self.assertEqual(result['formats'], [])

    def test_resource_key_preserved(self):
        with patch.object(googledrive, 'read_json', return_value=VIDEO) as read:
            result = googledrive.resolve('https://drive.google.com/open?id=' + ID + '&resourcekey=abc', need=['info'])
        self.assertTrue(result['source']['url'].endswith('resourcekey=abc'))
        self.assertEqual(read.call_args.kwargs['headers']['X-Goog-Drive-Resource-Keys'], ID + '/abc')

    def test_captions_are_need_aware(self):
        with patch.object(googledrive, 'read_json', return_value=VIDEO), patch.object(googledrive, 'read_text', return_value='<transcript_list><track lang_code="ko" kind="asr" name="a b"/></transcript_list>'):
            result = googledrive.resolve(URL, need=['transcript'])
        self.assertEqual(result['subtitles'][0]['origin'], 'platform_auto')
        self.assertIn('name=a+b', result['subtitles'][0]['url'])
        self.assertEqual(result['formats'], [])

    def test_adaptive_tracks_preserve_audio_presence(self):
        streams = [{'url': 'https://cdn.test/video', 'transcodeMetadata': {'mimeType': 'video/mp4', 'width': 1920, 'height': 1080, 'videoCodecString': 'avc1'}}, {'url': 'https://cdn.test/audio', 'transcodeMetadata': {'mimeType': 'audio/mp4', 'audioCodecString': 'mp4a'}}]
        with patch.object(googledrive, 'read_json', return_value={**VIDEO, 'mediaStreamingData': {'formatStreamingData': {'adaptiveTranscodes': streams}}}):
            result = googledrive.resolve(URL, need=['video'])
        self.assertFalse(result['formats'][0]['has_audio'])
        self.assertTrue(result['formats'][1]['has_audio'])
        self.assertEqual(len(select_formats(result['formats'])), 2)

    def test_folder_is_rejected(self):
        with patch.object(googledrive, 'read_json') as read, self.assertRaises(Failure):
            googledrive.resolve('https://drive.google.com/drive/folders/' + ID)
        read.assert_not_called()

    def test_progressive_unknown_codecs_keep_native_video_and_unknown_audio(self):
        entry = {'url': 'https://cdn.test/progressive', 'transcodeMetadata': {'mimeType': 'video/mp4', 'width': 640, 'height': 360}}
        with patch.object(googledrive, 'read_json', return_value={**VIDEO, 'mediaStreamingData': {'formatStreamingData': {'progressiveTranscodes': [entry]}}}):
            result = googledrive.resolve(URL, need=['video'])
        candidate = result['formats'][0]
        self.assertTrue(candidate['has_video'])
        self.assertIsNone(candidate['has_audio'])
        self.assertIsNone(result['metadata']['audio_expected'])
        self.assertEqual(select_formats(result['formats'], want_video=False), [candidate])

    def test_adaptive_mime_roles_preserve_separation_without_codec_fields(self):
        entries = [{'url': 'https://cdn.test/video', 'transcodeMetadata': {'mimeType': 'video/mp4'}},
                   {'url': 'https://cdn.test/audio', 'transcodeMetadata': {'mimeType': 'audio/mp4'}}]
        with patch.object(googledrive, 'read_json', return_value={**VIDEO, 'mediaStreamingData': {'formatStreamingData': {'adaptiveTranscodes': entries}}}):
            result = googledrive.resolve(URL, need=['video'])
        self.assertTrue(result['formats'][0]['has_video'])
        self.assertFalse(result['formats'][0]['has_audio'])
        self.assertFalse(result['formats'][1]['has_video'])
        self.assertTrue(result['formats'][1]['has_audio'])
