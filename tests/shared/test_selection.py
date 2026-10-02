"""Shared candidate selection and required-audio delivery boundaries."""
import unittest
from unittest.mock import patch

from scripts import platforms


class PlatformsTest(unittest.TestCase):
    def test_subtitle_language_and_origin(self):
        tracks = [{'url': 'a', 'language': 'en', 'origin': 'platform_auto'},
                  {'url': 'b', 'language': 'en', 'origin': 'platform_manual'},
                  {'url': 'c', 'language': 'zh', 'origin': 'platform_manual'},
                  {'url': 'd', 'language': 'live_chat', 'origin': 'platform_manual'}]
        self.assertEqual(platforms.select_subtitle(tracks, 'en')['url'], 'b')
        with self.assertRaises(platforms.Failure) as caught:
            platforms.select_subtitle(tracks)
        self.assertEqual(caught.exception.code, 'subtitle_ambiguous')
        self.assertIn('en, zh', str(caught.exception))
        self.assertIsNone(platforms.select_subtitle([tracks[-1]]))

    def test_quality_and_required_audio(self):
        tracks = [{'url': str(w), 'width': w, 'height': h, 'has_video': True, 'has_audio': False}
                  for w, h in [(640, 360), (1280, 720), (1920, 1080), (3840, 2160)]]
        tracks += [{'url': 'audio', 'has_video': False, 'has_audio': True}]
        self.assertEqual([f['url'] for f in platforms.select_formats(tracks)], ['3840', 'audio'])
        self.assertEqual([f['url'] for f in platforms.select_formats(tracks, quality='1080p')], ['1920', 'audio'])
        self.assertEqual(platforms.select_formats(tracks, quality='source')[0]['width'], 3840)
        self.assertEqual(platforms.select_formats(tracks, want_video='frames', width=768)[0]['width'], 1280)
        self.assertEqual(platforms.select_formats(tracks, want_video=False)[0]['url'], 'audio')
        portrait = [{'url': 'p', 'width': 1080, 'height': 1920, 'has_video': True, 'has_audio': True}]
        self.assertEqual(platforms.select_formats(portrait)[0]['url'], 'p')

    def test_expected_audio_prevents_silent_video_delivery(self):
        resolved = {'metadata': {'audio_expected': True}, 'formats': [
            {'url': 'https://example.test/video', 'has_video': True, 'has_audio': False}]}
        with patch.object(platforms, 'download_file') as fetch:
            with self.assertRaises(platforms.Failure) as caught:
                platforms.download(resolved, 'unused')
        self.assertEqual(caught.exception.code, 'no_audio')
        fetch.assert_not_called()
        resolved['metadata']['audio_expected'] = None
        resolved['diagnostics'] = [{'stage': 'media', 'code': 'audio_unavailable',
                                    'message': 'Audio availability could not be verified.'}]
        with patch.object(platforms, 'download_file') as fetch:
            with self.assertRaises(platforms.Failure) as caught:
                platforms.download(resolved, 'unused')
        self.assertEqual(caught.exception.code, 'audio_unavailable')
        fetch.assert_not_called()

    def test_video_resolution_then_fps_then_bitrate(self):
        base = {'url': '30fps', 'width': 1920, 'height': 1080,
                'has_video': True, 'has_audio': True, 'fps': 30, 'bitrate': 10000}
        smooth = {**base, 'url': '60fps', 'fps': 60, 'bitrate': 5000}
        sharp = {**base, 'url': '4k', 'width': 3840, 'height': 2160, 'fps': 24, 'bitrate': 1000}
        self.assertEqual(platforms.select_formats([base, smooth])[0]['url'], '60fps')
        self.assertEqual(platforms.select_formats([base, smooth, sharp])[0]['url'], '4k')
        self.assertEqual(platforms.select_formats([base, smooth, sharp], quality='1080p')[0]['url'], '60fps')
        self.assertEqual(platforms.select_formats([base, {**base, 'url': 'higher', 'bitrate': 20000}])[0]['url'], 'higher')


if __name__ == '__main__':
    unittest.main()
