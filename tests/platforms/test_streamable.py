import unittest
from unittest.mock import patch
from scripts.platforms import Failure, streamable


class StreamableTests(unittest.TestCase):
    def test_need_identity_and_ephemeral_urls(self):
        data = {'shortcode': 'moo', 'status': 2, 'title': 'Cow', 'duration': 12,
                'thumbnail_url': 'https://cdn.test/image?Signature=secret', 'audio_channels': 2,
                'files': {'mp4': {'url': '//cdn.test/video.mp4?Signature=secret', 'width': 852, 'height': 480}}}
        with patch.object(streamable, 'read_json', return_value=data) as read:
            info = streamable.resolve('https://streamable.com/e/moo', need=['info'])
            media = streamable.resolve('https://streamable.com/s/moo/token', need=['video', 'transcript'])
        self.assertEqual(read.call_count, 2)
        self.assertEqual(info['formats'], [])
        self.assertNotIn('secret', str(info['metadata']))
        self.assertIsNone(info['metadata']['original_language'])
        self.assertTrue(media['formats'][0]['has_audio'])
        self.assertEqual(media['diagnostics'][0]['code'], 'subtitle_absent')

    def test_reject_wrong_route_unavailable_and_identity(self):
        for url in ['https://evil.test/moo', 'https://streamable.com/moo/other', 'file://streamable.com/moo']:
            with self.assertRaises(Failure):
                streamable.resolve(url)
        for data in [{'status': 1}, {'status': 2, 'shortcode': 'other'}]:
            with patch.object(streamable, 'read_json', return_value=data), self.assertRaises(Failure):
                streamable.resolve('https://streamable.com/moo')

    def test_unknown_audio_and_nonempty_captions(self):
        with patch.object(streamable, 'read_json', return_value={'status': 2, 'captions': [{'unknown': True}],
                'files': {'mp4': {'url': 'https://cdn.test/v.mp4'}, 'hls': {'url': 'https://cdn.test/v.m3u8'}}}):
            result = streamable.resolve('https://streamable.com/moo')
        self.assertIsNone(result['formats'][0]['has_audio'])
        self.assertEqual(len(result['formats']), 1)
        self.assertEqual(result['diagnostics'][0]['code'], 'subtitle_unsupported')
