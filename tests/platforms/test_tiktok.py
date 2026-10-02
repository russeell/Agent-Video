"""TikTok single-work identity, media candidates and information boundaries."""
import json
import unittest
from unittest.mock import patch
from scripts import platforms
from scripts.platforms import tiktok


class TikTokTest(unittest.TestCase):
    def test_embedded_public_data(self):
        item = {'id': '123', 'video': {'duration': 7}}
        html = '<script id="SIGI_STATE">' + json.dumps({'ItemModule': {'123': item}}) + '</script>'
        self.assertEqual(tiktok._item(tiktok._embedded(html), '123'), item)


class TikTokAcquisitionTests(unittest.TestCase):
    def test_bitrate_play_endpoint_preferred_without_music_audio(self):
        video = {'width': 576, 'height': 1024, 'bitrateInfo': [
            {'CodecType': 'h264', 'Bitrate': 1900000, 'BitrateFPS': 30,
             'PlayAddr': {'Width': 576, 'Height': 1024,
                          'UrlList': ['https://v16.tiktok.com/video/clip',
                                      'https://www.tiktok.com/aweme/v1/play/?video_id=clip']}},
            {'CodecType': 'bytevc2', 'Bitrate': 9999999,
             'PlayAddr': {'UrlList': ['https://v16.tiktok.com/unsupported']}}]}
        formats = tiktok._formats(video)
        selected = platforms.select_formats(formats, quality='source')
        self.assertEqual(selected[0]['url'], 'https://www.tiktok.com/aweme/v1/play/?video_id=clip')
        self.assertEqual((selected[0]['width'], selected[0]['height'], selected[0]['fps']), (576, 1024, 30))
        self.assertTrue(selected[0]['has_audio'])
        self.assertNotIn('https://v16.tiktok.com/unsupported', [f['url'] for f in formats])
        self.assertEqual(tiktok._formats({}), [])

    def test_info_does_not_expose_signed_thumbnail_or_claim_silent_video(self):
        item = {'id': '123', 'desc': 'Test', 'video': {
            'duration': 2, 'cover': 'https://example.test/cover?x-signature=secret',
            'playAddr': 'https://example.test/media'},
            'music': {'playUrl': 'https://example.test/soundtrack'}}
        page = '<script id="SIGI_STATE">' + json.dumps({'ItemModule': {'123': item}}) + '</script>'
        with patch.object(tiktok, 'read_text', return_value=page):
            result = tiktok.resolve('https://www.tiktok.com/@author/video/123', need=['info'])
        self.assertIsNone(result['metadata']['thumbnail'])
        self.assertIsNone(result['metadata']['audio_expected'])
        self.assertEqual(result['formats'], [])

    def test_known_video_only_hevc_does_not_claim_audio(self):
        formats = tiktok._formats({'bitrateInfo': [{'CodecType': 'bytevc1',
            'PlayAddr': {'UrlList': ['https://cdn.test/media-video-hvc1/']}}]})
        self.assertFalse(formats[0]['has_audio'])


if __name__ == '__main__':
    unittest.main()
