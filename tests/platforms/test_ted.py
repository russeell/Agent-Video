import json
import unittest
from unittest.mock import patch
from scripts.platforms import Failure, ted


def page(talk):
    return '<script id="__NEXT_DATA__" type="application/json">' + json.dumps({'props': {'pageProps': {'videoData': talk}}}) + '</script>'


class TEDTests(unittest.TestCase):
    def test_transcript_uses_native_full_vtt_not_description(self):
        talk = {'id': '42', 'slug': 'demo', 'description': 'Not a transcript', 'videoPlayerData': {
            'nativeLanguage': 'en', 'resources': {'hls': {'metadata': 'https://hls.ted.com/metadata', 'stream': 'https://hls.ted.com/master'}}}}
        with patch.object(ted, 'read_text', return_value=page(talk)) as read, patch.object(ted, 'read_json', return_value={
            'subtitles': [{'code': 'en', 'webvtt': 'https://hls.ted.com/en/full.vtt'}]}):
            result = ted.resolve('https://www.ted.com/talks/demo/transcript', need=['transcript'])
        self.assertEqual(read.call_count, 1)
        self.assertEqual(result['formats'], [])
        self.assertEqual(result['subtitles'][0]['url'], 'https://hls.ted.com/en/full.vtt')
        self.assertEqual(result['metadata']['description'], 'Not a transcript')

    def test_info_does_not_fetch_subtitle_metadata(self):
        talk = {'id': '42', 'slug': 'demo', 'videoPlayerData': {'resources': {'hls': {'metadata': 'https://hls.ted.com/metadata'}}}}
        with patch.object(ted, 'read_text', return_value=page(talk)), patch.object(ted, 'read_json') as read:
            ted.resolve('https://www.ted.com/talks/demo', need=['info'])
        read.assert_not_called()

    def test_external_host_and_wrong_talk_are_explicit(self):
        talk = {'id': '42', 'slug': 'demo', 'videoPlayerData': {'external': {'service': 'YouTube', 'code': 'abcdefghijk'}}}
        with patch.object(ted, 'read_text', return_value=page(talk)):
            result = ted.resolve('https://www.ted.com/talks/demo', need=['video'])
        self.assertEqual(result['diagnostics'][0]['code'], 'external_host_unsupported')
        self.assertEqual(result['source']['platform'], 'ted')
        with patch.object(ted, 'read_text', return_value=page(talk)):
            with self.assertRaises(Failure):
                ted.resolve('https://www.ted.com/talks/another')

    def test_unsupported_hls_keeps_native_progressive(self):
        talk = {'id': '42', 'slug': 'demo', 'videoPlayerData': {'resources': {
            'h264': [{'file': 'https://cdn.test/fallback.mp4', 'bitrate': 1200}],
            'hls': {'stream': 'https://hls.ted.com/master'}}}}
        master = '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000000,RESOLUTION=854x480\nvideo.m3u8'
        leaf = '#EXTM3U\n#EXT-X-DISCONTINUITY\n#EXTINF:2,\nsegment.ts\n#EXT-X-ENDLIST'
        with patch.object(ted, 'read_text', return_value=page(talk)), patch('scripts.streams._fetch', side_effect=[('https://hls.ted.com/master', master), ('https://hls.ted.com/video.m3u8', leaf)]):
            result = ted.resolve('https://www.ted.com/talks/demo', need=['video'])
        self.assertEqual(len(result['formats']), 1)
        self.assertEqual(result['formats'][0]['url'], 'https://cdn.test/fallback.mp4')
        self.assertIsNone(result['formats'][0]['has_audio'])
        self.assertIsNone(result['metadata']['audio_expected'])
        self.assertEqual(result['diagnostics'][0]['code'], 'hls_feature_unsupported')

    def test_native_audio_resource_preserves_actual_track_signal(self):
        talk = {'id': '42', 'slug': 'demo', 'audioDownload': 'https://cdn.test/audio.mp3'}
        with patch.object(ted, 'read_text', return_value=page(talk)):
            result = ted.resolve('https://www.ted.com/talks/demo', need=['audio'])
        self.assertTrue(result['formats'][0]['has_audio'])
        self.assertFalse(result['formats'][0]['has_video'])
        self.assertTrue(result['metadata']['audio_expected'])
