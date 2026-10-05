import unittest
from unittest.mock import patch
from scripts.platforms import Failure, missav

URL = 'https://missav.ws/en/studio-001'
HEAD = '<link rel="canonical" href="' + URL + '"><meta property="og:title" content="Fixture work">'
PACKED = '''eval(function(p,a,c,k,e,d){return p;}('0 1="2://3/4.5";',36,6,'var|source|https|cdn.test|video|m3u8'.split('|'),0,{}))'''


class MissavTests(unittest.TestCase):
    def test_strict_identity_rejects_listing_credentials_and_other_hosts(self):
        with patch.object(missav, 'read_text') as read:
            for url in ('https://missav.ws/en', 'https://missav.ws/en/search',
                        'https://evil.test/en/studio-001', 'https://user:pass@missav.ws/en/studio-001',
                        'https://missav.ws:invalid/en/studio-001', 'ftp://missav.ws/en/studio-001'):
                with self.assertRaises(Failure):
                    missav.resolve(url)
        read.assert_not_called()

    def test_info_does_not_unpack_or_request_media(self):
        page = HEAD + '<script>' + PACKED + '</script><script type="application/ld+json">{"@type":"VideoObject","url":"' + URL + '","duration":"PT1M2.5S"}</script>'
        with patch.object(missav, 'read_text', return_value=page) as read, patch.object(missav, '_unpack') as unpack, patch('scripts.streams._fetch') as fetch:
            result = missav.resolve(URL + '?tracking=1', need=['info'])
        self.assertEqual(read.call_count, 1)
        unpack.assert_not_called()
        fetch.assert_not_called()
        self.assertEqual(result['metadata']['duration'], 62.5)
        self.assertIsNone(result['metadata']['original_language'])
        self.assertEqual(result['formats'], [])
        self.assertEqual(result['subtitles'], [])
        self.assertEqual(result['source']['url'], URL)

    def test_static_packer_is_dictionary_driven_not_positional_url_construction(self):
        self.assertEqual(missav._unpack(PACKED), 'var source="https://cdn.test/video.m3u8";')
        permuted = PACKED.replace('0 1="2://3/4.5";', '4 2="5://1/0.3";').replace('var|source|https|cdn.test|video|m3u8', 'video|cdn.test|source|m3u8|var|https')
        self.assertEqual(missav._unpack(permuted), 'var source="https://cdn.test/video.m3u8";')

    def test_malformed_and_large_packer_are_controlled_failures(self):
        for script in (PACKED.replace(',36,6,', ',80,6,'), PACKED.replace(',36,6,', ',36,999999,'), PACKED.replace('.split', '.join'), 'x' * 512001):
            with self.assertRaises(Failure):
                missav._unpack(script)

    def test_packed_hls_fetch_and_ephemeral_url(self):
        playlist = '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=42,RESOLUTION=1280x720\nvideo.m3u8?sig=secret\n'
        with patch.object(missav, 'read_text', return_value=HEAD + '<script>' + PACKED + '</script>'), patch('scripts.streams._fetch', return_value=('https://cdn.test/video.m3u8', playlist)) as fetch:
            result = missav.resolve(URL, need=['video'])
        self.assertEqual(fetch.call_args.args[0], 'https://cdn.test/video.m3u8')
        self.assertEqual(result['formats'][0]['height'], 720)
        self.assertIsNone(result['formats'][0]['has_audio'])
        self.assertNotIn('secret', str(result['metadata']))

    def test_encrypted_hls_not_offered_or_key_fetched(self):
        for method in ('AES-128', 'SAMPLE-AES'):
            playlist = '#EXTM3U\n#EXT-X-KEY:METHOD=' + method + ',URI="https://cdn.test/key"\n#EXTINF:1,\nseg.ts\n#EXT-X-ENDLIST\n'
            with patch.object(missav, 'read_text', return_value=HEAD + '<video src="https://cdn.test/video.m3u8"></video>'), patch('scripts.streams._fetch', return_value=('https://cdn.test/video.m3u8', playlist)) as fetch:
                result = missav.resolve(URL, need=['video'])
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(result['formats'], [])
            self.assertEqual(result['diagnostics'][0]['code'], 'encrypted_stream_unsupported')

    def test_complete_media_playlist_accepted_but_live_rejected(self):
        page = HEAD + '<video src="https://cdn.test/video.m3u8"></video>'
        playlist = '#EXTM3U\n#EXTINF:2,\nsegment.ts\n#EXT-X-ENDLIST\n'
        with patch.object(missav, 'read_text', return_value=page), patch('scripts.streams._fetch', return_value=('https://cdn.test/video.m3u8', playlist)):
            result = missav.resolve(URL, need=['video'])
        self.assertEqual(result['formats'][0]['protocol'], 'hls')
        with patch.object(missav, 'read_text', return_value=page), patch('scripts.streams._fetch', return_value=('https://cdn.test/video.m3u8', playlist.replace('#EXT-X-ENDLIST', ''))):
            result = missav.resolve(URL, need=['video'])
        self.assertEqual(result['diagnostics'][0]['code'], 'live_unsupported')

    def test_captions_only_real_track_not_title_or_thumbnail_track(self):
        page = HEAD + '<video><track kind="metadata" src="https://cdn.test/thumbs.vtt"><track kind="captions" src="/captions/studio-001.vtt" srclang="ja"></video>'
        with patch.object(missav, 'read_text', return_value=page), patch('scripts.streams._fetch') as fetch:
            result = missav.resolve(URL, need=['transcript'])
        fetch.assert_not_called()
        self.assertEqual(len(result['subtitles']), 1)
        self.assertEqual(result['subtitles'][0]['language'], 'ja')
        self.assertEqual(result['formats'], [])

    def test_identity_mismatch_and_challenge_never_returns_title(self):
        for page in (HEAD.replace('studio-001', 'studio-002'), '<title>Challenge</title><script src="/cdn-cgi/challenge-platform"></script>', '<html>Unknown response</html>', HEAD + '<script type="application/ld+json">{"@type":"VideoObject","url":"https://missav.ws/en/studio-002"}</script>'):
            with patch.object(missav, 'read_text', return_value=page), self.assertRaises(Failure):
                missav.resolve(URL, need=['info'])

    def test_cloudflare_script_on_readable_work_is_not_a_challenge_page(self):
        page = HEAD + '<meta property="og:video:duration" content="62.5"><script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script><video src="https://cdn.test/work.mp4"></video>'
        with patch.object(missav, 'read_text', return_value=page):
            result = missav.resolve(URL, need=['video'])
        self.assertEqual(result['metadata']['id'], 'studio-001')
        self.assertEqual(result['metadata']['duration'], 62.5)
        self.assertEqual(result['formats'][0]['url'], 'https://cdn.test/work.mp4')

    def test_javascript_executable_text_is_never_executed(self):
        page = HEAD + '<script>throw new Error("do not execute");var source="https://cdn.test/work.mp4";</script>'
        with patch.object(missav, 'read_text', return_value=page):
            result = missav.resolve(URL, need=['video'])
        self.assertEqual(result['formats'][0]['url'], 'https://cdn.test/work.mp4')

    def test_http_access_failure_is_preserved(self):
        with patch.object(missav, 'read_text', side_effect=Failure('access_denied', 'HTTP 403: platform access was denied.')), self.assertRaises(Failure) as error:
            missav.resolve(URL)
        self.assertEqual(error.exception.code, 'access_denied')

    def test_master_without_video_dimensions_not_offered_as_media_playlist(self):
        playlist = '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=42\nchild.m3u8\n'
        with patch.object(missav, 'read_text', return_value=HEAD + '<video src="https://cdn.test/video.m3u8"></video>'), patch('scripts.streams._fetch', return_value=('https://cdn.test/video.m3u8', playlist)):
            result = missav.resolve(URL, need=['video'])
        self.assertEqual(result['formats'][0]['url'], 'https://cdn.test/child.m3u8')
        self.assertIsNone(result['formats'][0]['width'])
        self.assertIsNone(result['formats'][0]['height'])
        self.assertEqual(result['formats'][0]['headers']['Referer'], URL)
        self.assertEqual(result['diagnostics'], [])
