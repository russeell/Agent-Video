"""Shared candidate selection and required-audio delivery boundaries."""
import unittest
from unittest.mock import patch

from scripts import platforms


class PlatformsTest(unittest.TestCase):
    def test_native_original_without_dimensions_beats_known_transcode(self):
        original = {'url': 'original', 'is_original': True, 'has_video': True, 'has_audio': None}
        transcode = {'url': '720p', 'width': 1280, 'height': 720, 'has_video': True, 'has_audio': True}
        for quality, want_video, width in [('source', True, 768), ('auto', True, 768), ('auto', 'frames', 0)]:
            with self.subTest(quality=quality, want_video=want_video):
                chosen = platforms.select_formats([transcode, original], quality=quality, want_video=want_video, width=width)
                self.assertEqual(chosen[0]['url'], 'original')
        self.assertEqual(platforms.select_formats([transcode, original], want_video='frames', width=768)[0]['url'], '720p')
        # A label alone is not proof that this is the native original.
        unverified = {**original, 'is_original': False, 'format_id': 'original'}
        self.assertEqual(platforms.select_formats([transcode, unverified])[0]['url'], '720p')

    def test_resolution_labels_without_width_select_highest_available(self):
        formats = [{'url': f'https://example.test/{height}.mp4', 'height': height,
                    'has_video': True, 'has_audio': True} for height in (720, 2160, 1080)]
        for quality, height in [('source', 2160), ('auto', 2160), ('1080p', 1080)]:
            with self.subTest(quality=quality):
                chosen = platforms.select_formats(formats, quality=quality)[0]
                self.assertEqual(chosen['height'], height)
                self.assertNotIn('width', chosen)

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

    def test_no_formats_preserves_confirmed_media_access_restriction(self):
        restriction = {'stage': 'media', 'code': 'auth_required',
                       'message': 'This work requires an authorized account.',
                       'next_action': 'Provide your own authorized Cookie file.'}
        resolved = {'formats': [], 'diagnostics': [restriction]}
        for want_video in (True, False, 'frames'):
            with self.subTest(want_video=want_video), \
                 patch.object(platforms, 'download_file') as fetch, \
                 self.assertRaises(platforms.Failure) as caught:
                platforms.download(resolved, 'unused', want_video=want_video)
            self.assertEqual(caught.exception.code, 'auth_required')
            self.assertEqual(str(caught.exception), restriction['message'])
            self.assertEqual(caught.exception.next_action, restriction['next_action'])
            fetch.assert_not_called()
        # A subtitle-only restriction must not be mistaken for denied media.
        resolved['diagnostics'] = [{**restriction, 'stage': 'transcript'}]
        with self.assertRaises(platforms.Failure) as caught:
            platforms.download(resolved, 'unused')
        self.assertEqual(caught.exception.code, 'media_unavailable')

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
