import unittest
from unittest.mock import patch
from scripts.platforms import Failure, bluesky


def post():
    return {'thread': {'post': {'uri': 'at://did:plc:abc/app.bsky.feed.post/abc', 'author': {'did': 'did:plc:abc', 'handle': 'demo.test'},
        'record': {'text': 'Demo', 'langs': ['en'], 'embed': {'$type': 'app.bsky.embed.video',
            'video': {'ref': {'$link': 'videocid'}, 'mimeType': 'video/mp4'},
            'captions': [{'lang': 'en', 'file': {'ref': {'$link': 'captioncid'}, 'mimeType': 'text/vtt'}}]}},
        'embed': {'$type': 'app.bsky.embed.video#view', 'cid': 'videocid', 'playlist': 'https://cdn.test/master.m3u8'}}}}


class BlueskyTests(unittest.TestCase):
    def test_info_only_no_pds_or_playlist(self):
        with patch.object(bluesky, 'read_json', return_value=post()) as read, patch('scripts.streams._fetch') as fetch:
            result = bluesky.resolve('https://bsky.app/profile/demo.test/post/abc', need=['info'])
        self.assertEqual(read.call_count, 1)
        fetch.assert_not_called()
        self.assertIsNone(result['metadata']['original_language'])
        self.assertEqual(result['subtitles'], [])

    def test_captions_no_media_and_record_with_media(self):
        data = post()
        p = data['thread']['post']
        p['embed'] = {'$type': 'app.bsky.embed.recordWithMedia#view', 'media': p['embed']}
        p['record']['embed'] = {'$type': 'app.bsky.embed.recordWithMedia', 'media': p['record']['embed']}
        with patch.object(bluesky, 'read_json', side_effect=[data, {'service': [{'type': 'AtprotoPersonalDataServer', 'serviceEndpoint': 'https://pds.test'}]}]), patch('scripts.streams._fetch') as fetch:
            result = bluesky.resolve('https://bsky.app/profile/demo.test/post/abc', need=['transcript'])
        fetch.assert_not_called()
        self.assertEqual(result['subtitles'][0]['language'], 'en')
        self.assertIn('captioncid', result['subtitles'][0]['url'])
        self.assertEqual(result['formats'], [])

    def test_hls_and_unknown_encoded_dimensions(self):
        master = '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000000,RESOLUTION=1920x1080\nvideo.m3u8'
        with patch.object(bluesky, 'read_json', side_effect=[post(), {'service': [{'type': 'AtprotoPersonalDataServer', 'serviceEndpoint': 'https://pds.test'}]}]), patch('scripts.streams._fetch', return_value=('https://cdn.test/master.m3u8', master)):
            result = bluesky.resolve('https://bsky.app/profile/demo.test/post/abc', need=['video'])
        self.assertTrue(result['formats'][0]['is_original'])
        self.assertIsNone(result['formats'][0]['width'])
        self.assertIsNone(result['formats'][0]['has_audio'])
        self.assertEqual(result['formats'][1]['width'], 1920)

    def test_external_quoted_wrong_identity_and_route(self):
        for kind in ['app.bsky.embed.external#view', 'app.bsky.embed.record#view']:
            data = post(); data['thread']['post']['embed']['$type'] = kind
            with patch.object(bluesky, 'read_json', return_value=data), self.assertRaises(Failure) as exc:
                bluesky.resolve('https://bsky.app/profile/demo.test/post/abc')
            self.assertEqual(exc.exception.code, 'native_video_absent')
        with patch.object(bluesky, 'read_json', return_value=post()), self.assertRaises(Failure):
            bluesky.resolve('https://bsky.app/profile/other.test/post/abc')
        for url in ['https://evil.test/profile/demo.test/post/abc', 'https://bsky.app/profile/demo.test', 'https://bsky.app/profile/demo.test/post/abc/extra']:
            with self.assertRaises(Failure): bluesky.resolve(url)
