"""Twitch clip/VOD isolation, query needs and original asset selection."""
import unittest
from unittest.mock import patch
from scripts import platforms
from scripts.platforms import twitch

CLIP = {'id': '123', 'slug': 'PublicClip', 'title': 'A clip', 'durationSeconds': 32,
        'broadcaster': {'displayName': 'Author'}, 'thumbnailURL': 'https://cdn.test/thumb.jpg'}
PLAYBACK = {'id': '123', 'slug': 'PublicClip', 'playbackAccessToken': {'value': 'temporary-token', 'signature': 'sig'},
            'assets': [{'aspectRatio': 16 / 9, 'videoQualities': [
                {'quality': '720', 'frameRate': 30, 'sourceURL': 'https://cdn.test/720.mp4'},
                {'quality': '1080', 'frameRate': 60, 'sourceURL': 'https://cdn.test/1080.mp4?keep=1'}]},
                {'aspectRatio': 9 / 16, 'videoQualities': [{'quality': '1920', 'sourceURL': 'https://cdn.test/crop.mp4'}]}]}
VOD = {'id': '456', 'title': 'A VOD', 'lengthSeconds': 11643,
       'previewThumbnailURL': 'https://cdn.test/thumb.jpg', 'broadcastType': 'ARCHIVE'}


class TwitchTests(unittest.TestCase):
    def test_supported_urls_and_live_rejection(self):
        self.assertEqual(twitch._identity('https://clips.twitch.tv/PublicClip'), ('clip', 'PublicClip'))
        self.assertEqual(twitch._identity('https://www.twitch.tv/author/clip/PublicClip'), ('clip', 'PublicClip'))
        self.assertEqual(twitch._identity('https://www.twitch.tv/videos/456?t=10s'), ('vod', '456'))
        with self.assertRaises(platforms.Failure) as caught:
            twitch._identity('https://www.twitch.tv/author')
        self.assertEqual(caught.exception.code, 'live_unsupported')
        for url in ['https://evil.test/videos/456', 'https://www.twitch.tv/author/videos', 'https://www.twitch.tv/collections/abc']:
            with self.assertRaises(platforms.Failure):
                twitch._identity(url)

    def test_info_never_requests_access_token_or_media(self):
        with patch.object(twitch, '_gql', return_value={'clip': CLIP}) as gql:
            result = twitch.resolve('https://clips.twitch.tv/PublicClip', need=['info'])
        self.assertEqual(gql.call_count, 1)
        self.assertNotIn('playbackAccessToken', gql.call_args.args[0])
        self.assertEqual(result['formats'], [])
        self.assertEqual(result['metadata']['duration'], 32)

    def test_source_quality_preserves_default_asset_and_signs_candidate_only(self):
        with patch.object(twitch, '_gql', side_effect=[{'clip': CLIP}, {'clip': PLAYBACK}]):
            result = twitch.resolve('https://clips.twitch.tv/PublicClip', need=['video'])
        selected = platforms.select_formats(result['formats'], quality='source')[0]
        self.assertEqual((selected['width'], selected['height'], selected['fps']), (1920, 1080, 60))
        self.assertIn('keep=1', selected['url'])
        self.assertIn('token=temporary-token', selected['url'])
        self.assertNotIn('temporary-token', str(result['source']) + str(result['metadata']))
        self.assertFalse(any('crop.mp4' in f['url'] for f in result['formats']))

    def test_playback_identity_cannot_replace_selected_clip(self):
        playback = {**PLAYBACK, 'id': '999'}
        with patch.object(twitch, '_gql', side_effect=[{'clip': CLIP}, {'clip': playback}]):
            result = twitch.resolve('https://clips.twitch.tv/PublicClip', need=['video'])
        self.assertEqual(result['formats'], [])
        self.assertEqual(result['diagnostics'][0]['code'], 'parse_failed')

    def test_caption_availability_unknown_preserves_info_without_media(self):
        with patch.object(twitch, '_gql', return_value={'clip': CLIP}) as gql:
            result = twitch.resolve('https://clips.twitch.tv/PublicClip', need=['transcript'])
        self.assertEqual(gql.call_count, 1)
        self.assertEqual(result['diagnostics'][0]['code'], 'subtitle_failed')
        self.assertEqual(result['formats'], [])

    def test_vod_info_does_not_download_long_archive(self):
        with patch.object(twitch, '_gql', return_value={'video': VOD}) as gql, patch.object(twitch, 'read_text') as read:
            result = twitch.resolve('https://www.twitch.tv/videos/456', need=['info'])
        read.assert_not_called()
        self.assertEqual(gql.call_count, 1)
        self.assertEqual(result['metadata']['duration'], 11643)

    def test_processing_live_archive_rejected(self):
        live = {**VOD, 'previewThumbnailURL': 'https://cdn.test/404_processing_320x180.png'}
        with patch.object(twitch, '_gql', return_value={'video': live}):
            with self.assertRaises(platforms.Failure) as caught:
                twitch.resolve('https://www.twitch.tv/videos/456', need=['video'])
        self.assertEqual(caught.exception.code, 'live_unsupported')

    def test_playback_failure_preserves_metadata(self):
        with patch.object(twitch, '_gql', side_effect=[{'clip': CLIP}, platforms.Failure('access_denied', 'HTTP 403')]):
            result = twitch.resolve('https://clips.twitch.tv/PublicClip', need=['video'])
        self.assertEqual(result['metadata']['title'], 'A clip')
        self.assertEqual(result['diagnostics'][0]['code'], 'access_denied')
        self.assertEqual(result['formats'], [])
