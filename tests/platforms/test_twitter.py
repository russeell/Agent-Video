"""X single-status identity, attachment isolation and acquisition boundaries."""
import unittest
from unittest.mock import patch
from scripts import platforms
from scripts.platforms import twitter


def status(*details):
    return {'id_str': '123', 'text': 'A clip', 'user': {'name': 'Author'}, 'mediaDetails': list(details)}


def video(suffix='one', duration=1000):
    return {'type': 'video', 'video_info': {'duration_millis': duration, 'variants': [
        {'content_type': 'video/mp4', 'bitrate': 100, 'url': f'https://video.twimg.com/vid/320x180/{suffix}.mp4'},
        {'content_type': 'video/mp4', 'bitrate': 200, 'url': f'https://video.twimg.com/vid/1280x720/{suffix}.mp4'}]}}


class TwitterTests(unittest.TestCase):
    def test_info_does_not_parse_or_fetch_media(self):
        with patch.object(twitter, 'read_json', return_value=status(video())), patch.object(twitter, '_formats') as formats:
            result = twitter.resolve('https://twitter.com/author/status/123', need=['info'])
        formats.assert_not_called()
        self.assertEqual(result['formats'], [])
        self.assertEqual(result['metadata']['duration'], 1)

    def test_highest_available_muxed_media(self):
        with patch.object(twitter, 'read_json', return_value=status(video())):
            result = twitter.resolve('https://x.com/author/status/123', need=['video'])
        selected = platforms.select_formats(result['formats'], quality='source')[0]
        self.assertEqual((selected['width'], selected['height']), (1280, 720))
        self.assertTrue(selected['has_audio'])

    def test_requested_attachment_remains_distinct(self):
        data = status(video('one'), video('two', 3000))
        with patch.object(twitter, 'read_json', return_value=data):
            with self.assertRaises(platforms.Failure) as caught:
                twitter.resolve('https://x.com/a/status/123', need=['video'])
            self.assertEqual(caught.exception.code, 'media_ambiguous')
            result = twitter.resolve('https://x.com/a/status/123/video/2', need=['video'])
        self.assertTrue(result['source']['url'].endswith('/video/2'))
        self.assertEqual(result['metadata']['duration'], 3)
        self.assertTrue(all('/two.mp4' in f['url'] for f in result['formats']))

    def test_quoted_video_is_not_requested_status_media(self):
        data = status()
        data['quoted_tweet'] = status(video())
        with patch.object(twitter, 'read_json', return_value=data):
            result = twitter.resolve('https://x.com/a/status/123', need=['video', 'transcript'])
        self.assertEqual(result['formats'], [])
        self.assertEqual(result['diagnostics'][0]['code'], 'experimental_access_limited')
        self.assertEqual(result['diagnostics'][1]['code'], 'subtitle_failed')

    def test_wrong_status_and_non_status_rejected(self):
        with patch.object(twitter, 'read_json', return_value={'id_str': '456'}):
            with self.assertRaises(platforms.Failure):
                twitter.resolve('https://x.com/a/status/123')
        for url in ['https://x.com/a', 'https://evil.test/a/status/123', 'https://x.com/a/status/123/photo/1']:
            with self.assertRaises(platforms.Failure):
                twitter._identity(url)

    def test_hls_higher_resolution_participates_in_source_selection(self):
        detail = video()
        detail['video_info']['variants'].append({'content_type': 'application/x-mpegURL',
                                                 'url': 'https://video.twimg.com/master.m3u8'})
        master = '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=3000,RESOLUTION=1920x1080\nhigh.m3u8\n'
        with patch.object(twitter, 'read_json', return_value=status(detail)), patch.object(twitter, 'read_text', return_value=master):
            result = twitter.resolve('https://x.com/a/status/123', need=['video'])
        selected = platforms.select_formats(result['formats'], quality='source')[0]
        self.assertEqual((selected['width'], selected['height']), (1920, 1080))
        self.assertEqual(selected['protocol'], 'hls')

    def test_hls_access_failure_keeps_mp4_candidate_and_diagnostic(self):
        detail = video()
        detail['video_info']['variants'].append({'content_type': 'application/x-mpegURL',
                                                 'url': 'https://video.twimg.com/master.m3u8'})
        with patch.object(twitter, 'read_json', return_value=status(detail)), patch.object(twitter, 'read_text', side_effect=platforms.Failure('access_denied', 'HTTP 403')):
            result = twitter.resolve('https://x.com/a/status/123', need=['video'])
        self.assertEqual(len(result['formats']), 2)
        self.assertEqual(result['diagnostics'][0]['code'], 'access_denied')
