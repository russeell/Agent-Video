"""Native Reddit post identity, direct MPD streams and honest caption limits."""
import unittest
from unittest.mock import patch
from scripts import platforms
from scripts.platforms import reddit

MPD = '''<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static"><Period>
<AdaptationSet><Representation mimeType="video/mp4" width="1280" height="720" bandwidth="1000"><BaseURL>video.mp4</BaseURL><SegmentBase/></Representation></AdaptationSet>
<AdaptationSet><Representation mimeType="audio/mp4" bandwidth="128"><BaseURL>original.m4a</BaseURL><SegmentBase/></Representation></AdaptationSet>
<AdaptationSet lang="en"><Representation mimeType="text/vtt"><BaseURL>captions.vtt</BaseURL></Representation></AdaptationSet>
</Period></MPD>'''


def post(video=None):
    return [{'data': {'children': [{'data': {'id': 'abc', 'title': 'Clip', 'author': 'author',
              'secure_media': {'reddit_video': video} if video else None}}]}}]


class RedditTests(unittest.TestCase):
    def test_direct_video_and_real_audio_addresses(self):
        formats, subtitles = reddit._mpd(MPD, 'https://v.redd.it/clip/DASHPlaylist.mpd')
        selected = platforms.select_formats(formats, quality='source')
        self.assertEqual([f['url'] for f in selected], ['https://v.redd.it/clip/video.mp4', 'https://v.redd.it/clip/original.m4a'])
        self.assertFalse(selected[0]['has_audio'])
        self.assertTrue(selected[1]['has_audio'])
        self.assertEqual(subtitles[0]['language'], 'en')

    def test_segmented_or_encrypted_resources_not_full_files(self):
        segmented = MPD.replace('<SegmentBase/>', '<SegmentTemplate media="part$Number$.m4s"/>')
        self.assertEqual(reddit._mpd(segmented, 'https://v.redd.it/clip/a.mpd')[0], [])
        encrypted = MPD.replace('<AdaptationSet>', '<AdaptationSet><ContentProtection/>')
        self.assertEqual(reddit._mpd(encrypted, 'https://v.redd.it/clip/a.mpd')[0], [])

    def test_info_does_not_fetch_manifests(self):
        with patch.object(reddit, 'read_json', return_value=post({'duration': 3, 'dash_url': 'https://v.redd.it/a.mpd'})), patch.object(reddit, 'read_text') as read:
            result = reddit.resolve('https://www.reddit.com/r/aww/comments/abc/clip/', need=['info'])
        read.assert_not_called()
        self.assertEqual(result['metadata']['duration'], 3)
        self.assertEqual(result['formats'], [])

    def test_failure_preserved_and_audio_never_forged(self):
        media = {'duration': 3, 'has_audio': True, 'fallback_url': 'https://v.redd.it/clip/DASH_720.mp4', 'dash_url': 'https://v.redd.it/clip/a.mpd'}
        with patch.object(reddit, 'read_json', return_value=post(media)), patch.object(reddit, 'read_text', side_effect=platforms.Failure('access_denied', 'HTTP 403')):
            result = reddit.resolve('https://www.reddit.com/comments/abc', need=['video', 'transcript'])
        self.assertEqual(len(result['formats']), 1)
        self.assertFalse(result['formats'][0]['has_audio'])
        self.assertEqual([d['code'] for d in result['diagnostics']], ['access_denied', 'audio_unavailable', 'subtitle_failed'])

    def test_crosspost_and_external_video_not_followed(self):
        data = post()
        data[0]['data']['children'][0]['data']['crosspost_parent_list'] = [{'secure_media': {'reddit_video': {'fallback_url': 'https://v.redd.it/other'}}}]
        with patch.object(reddit, 'read_json', return_value=data):
            result = reddit.resolve('https://www.reddit.com/comments/abc', need=['video'])
        self.assertEqual(result['formats'], [])

    def test_wrong_identity_and_feed_rejected(self):
        with self.assertRaises(platforms.Failure):
            reddit._post(post(), 'other')
        for url in ['https://www.reddit.com/r/aww/', 'https://v.redd.it/clip', 'https://evil.test/comments/abc']:
            with self.assertRaises(platforms.Failure):
                reddit._identity(url)

    def test_cold_denial_initializes_guest_once_and_reuses_scoped_opener(self):
        client = object()
        with patch.object(reddit, '_opener', return_value=client), patch.object(reddit, 'read_json',
                side_effect=[platforms.Failure('access_denied', 'HTTP 403'), post()]) as read_json, \
                patch.object(reddit, 'read_text', return_value='<html>Anonymous entry</html>') as read_text:
            result = reddit._load_post('https://www.reddit.com/comments/abc/', 'abc')
        self.assertEqual(result['id'], 'abc')
        self.assertEqual(read_json.call_count, 2)
        self.assertEqual(read_text.call_count, 1)
        self.assertEqual(read_text.call_args.args[0], 'https://old.reddit.com/')
        self.assertIs(read_text.call_args.kwargs['opener'], client)
        for call in read_json.call_args_list:
            self.assertIs(call.kwargs['opener'], client)
            self.assertEqual(call.args[0], 'https://www.reddit.com/comments/abc/.json?raw_json=1')
            self.assertNotIn('Cookie', call.kwargs.get('headers', {}))

    def test_guest_retry_is_bounded_and_does_not_assume_login_required(self):
        with patch.object(reddit, 'read_json', side_effect=platforms.Failure('access_denied', 'HTTP 403')) as read_json, \
                patch.object(reddit, 'read_text', return_value='<html>Anonymous entry</html>') as read_text:
            with self.assertRaises(platforms.Failure) as caught:
                reddit._load_post('https://www.reddit.com/comments/abc/', 'abc')
        self.assertEqual(read_json.call_count, 2)
        self.assertEqual(read_text.call_count, 1)
        self.assertEqual(caught.exception.code, 'access_denied')
        self.assertIn('does not establish a login requirement', caught.exception.next_action)

    def test_wrong_post_does_not_bootstrap_or_substitute_neighbors(self):
        with patch.object(reddit, 'read_json', return_value=post()), patch.object(reddit, 'read_text') as read_text:
            with self.assertRaises(platforms.Failure):
                reddit._load_post('https://www.reddit.com/comments/other/', 'other')
        read_text.assert_not_called()

    def test_hls_higher_resolution_keeps_actual_audio(self):
        video = {'dash_url': 'https://v.redd.it/clip/a.mpd', 'hls_url': 'https://v.redd.it/clip/master.m3u8'}
        master = '#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Audio",DEFAULT=YES,URI="audio.m3u8"\n#EXT-X-STREAM-INF:BANDWIDTH=3000,RESOLUTION=1920x1080,AUDIO="audio"\nhigh.m3u8\n'
        with patch.object(reddit, 'read_json', return_value=post(video)), patch.object(reddit, 'read_text', side_effect=[MPD, master]):
            result = reddit.resolve('https://www.reddit.com/comments/abc', need=['video'])
        selected = platforms.select_formats(result['formats'], quality='source')
        self.assertEqual((selected[0]['width'], selected[0]['height']), (1920, 1080))
        self.assertEqual(selected[0]['protocol'], 'hls')
        self.assertFalse(selected[0]['has_audio'])
        self.assertTrue(selected[1]['has_audio'])
        self.assertEqual(selected[1]['audio_group'], 'audio')
