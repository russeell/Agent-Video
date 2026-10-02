"""Shared candidate selection and lightweight embedded-page parsing."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import platforms
from platforms import youtube, tiktok


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

    def test_video_resolution_then_fps_then_bitrate(self):
        base = {'url': '30fps', 'width': 1920, 'height': 1080,
                'has_video': True, 'has_audio': True, 'fps': 30, 'bitrate': 10000}
        smooth = {**base, 'url': '60fps', 'fps': 60, 'bitrate': 5000}
        sharp = {**base, 'url': '4k', 'width': 3840, 'height': 2160, 'fps': 24, 'bitrate': 1000}
        self.assertEqual(platforms.select_formats([base, smooth])[0]['url'], '60fps')
        self.assertEqual(platforms.select_formats([base, smooth, sharp])[0]['url'], '4k')
        self.assertEqual(platforms.select_formats([base, smooth, sharp], quality='1080p')[0]['url'], '60fps')
        self.assertEqual(platforms.select_formats([base, {**base, 'url': 'higher', 'bitrate': 20000}])[0]['url'], 'higher')

    def test_embedded_public_data(self):
        data = {'videoDetails': {'videoId': 'abcdefghijk', 'title': 'Video'}}
        self.assertEqual(youtube._player('ytInitialPlayerResponse = ' + json.dumps(data) + ';'), data)
        item = {'id': '123', 'video': {'duration': 7}}
        html = '<script id="SIGI_STATE">' + json.dumps({'ItemModule': {'123': item}}) + '</script>'
        self.assertEqual(tiktok._item(tiktok._embedded(html), '123'), item)

if __name__ == '__main__':
    unittest.main()
