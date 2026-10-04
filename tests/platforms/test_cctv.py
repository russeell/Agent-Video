import unittest
from unittest.mock import patch
from scripts.platforms import Failure, cctv

URL = 'https://tv.cctv.com/2016/02/05/VIDEexample160205.shtml'
GUID = 'efc5d49e5b3b4ab2b34f3a502b73d3ae'
PAGE = 'var guid = "' + GUID + '"; <meta name="description" content="Summary &amp; only">'
DATA = {'ack': 'yes', 'title': 'Sports short', 'video': {'totalLength': '37'},
        'public': '1', 'is_protected': '0', 'is_preview': '0'}


class CCTVTests(unittest.TestCase):
    def resolve(self, data=None, need=None):
        with patch.object(cctv, 'read_text', return_value=PAGE), patch.object(cctv, 'read_json', return_value=data or DATA):
            return cctv.resolve(URL, need=need or ['info'])

    def test_info_identity_and_no_media_requests(self):
        with patch('scripts.streams._fetch') as fetch:
            result = self.resolve()
        fetch.assert_not_called()
        self.assertEqual(result['source']['id'], GUID)
        self.assertEqual(result['metadata']['duration'], 37)
        self.assertEqual(result['metadata']['description'], 'Summary & only')

    def test_transcript_does_not_misrepresent_description(self):
        result = self.resolve(need=['transcript'])
        self.assertEqual(result['subtitles'], [])
        self.assertEqual(result['formats'], [])
        self.assertEqual(result['diagnostics'][0]['code'], 'subtitle_unavailable')

    def test_only_complete_single_chapter_is_usable(self):
        data = dict(DATA, video={'totalLength': '37',
            'lowChapters': [{'url': 'https://cdn.test/sample.mp4', 'duration': '10'}],
            'chapters': [{'url': 'https://cdn.test/part1.mp4', 'duration': '20'}, {'url': 'https://cdn.test/part2.mp4', 'duration': '17'}],
            'chapters2': [{'url': 'https://cdn.test/full.mp4', 'duration': '37'}]})
        result = self.resolve(data, ['video'])
        self.assertEqual([f['url'] for f in result['formats']], ['https://cdn.test/full.mp4'])

    def test_clear_hls_preserves_queries_and_best_dimensions(self):
        data = dict(DATA, hls_url='https://cdn.test/main.m3u8?token=keep&maxbr=2048')
        master = '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000,RESOLUTION=1920x1080\nfull.m3u8'
        leaf = '#EXTM3U\n#EXTINF:37,\n0.ts\n#EXT-X-ENDLIST'
        with patch('scripts.streams._fetch', side_effect=[('https://cdn.test/main.m3u8?token=keep', master), ('https://cdn.test/full.m3u8', leaf)]) as fetch:
            result = self.resolve(data, ['video'])
        self.assertEqual(fetch.call_args_list[0].args[0], 'https://cdn.test/main.m3u8?token=keep')
        self.assertEqual(result['formats'][0]['height'], 1080)

    def test_encrypted_live_and_discontinuous_leaf_not_offered(self):
        master = '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000,RESOLUTION=640x360\nfull.m3u8'
        for prefix, suffix, code in [('#EXT-X-KEY:METHOD=AES-128,URI="key"\n', '#EXT-X-ENDLIST', 'encrypted_stream_unsupported'),
                                     ('', '', 'live_unsupported'),
                                     ('#EXT-X-DISCONTINUITY\n', '#EXT-X-ENDLIST', 'hls_feature_unsupported')]:
            with self.subTest(code=code), patch('scripts.streams._fetch', side_effect=[('https://cdn.test/main.m3u8', master), ('https://cdn.test/full.m3u8', '#EXTM3U\n' + prefix + '#EXTINF:37,\n0.ts\n' + suffix)]):
                result = self.resolve(dict(DATA, hls_url='https://cdn.test/main.m3u8'), ['video'])
            self.assertEqual(result['formats'], [])
            self.assertEqual(result['diagnostics'][0]['code'], code)

    def test_restricted_preview_and_wrong_identity_rejected(self):
        for field, value in [('is_preview', '1'), ('is_protected', '1'), ('public', '0'), ('pid', 'a' * 32)]:
            with self.subTest(field=field), self.assertRaises(Failure):
                self.resolve(dict(DATA, **{field: value}))

    def test_hosts_paths_and_multiple_video_pages_rejected(self):
        for url in ['https://yangshipin.cn/video/123', 'https://tv.cctv.com.evil.test/2016/02/05/VIDEabc.shtml', 'https://tv.cctv.com/live/', 'https://tv.cctv.com/']:
            with patch.object(cctv, 'read_text') as read, self.assertRaises(Failure):
                cctv.resolve(url)
            read.assert_not_called()
        with patch.object(cctv, 'read_text', return_value=PAGE + '; var guid="' + 'a' * 32 + '"'), self.assertRaises(Failure):
            cctv.resolve(URL)

    def test_hls_master_without_resolution_offers_leaf_not_parent(self):
        master = '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000\nfull.m3u8'
        leaf = '#EXTM3U\n#EXTINF:37,\n0.ts\n#EXT-X-ENDLIST'
        with patch('scripts.streams._fetch', side_effect=[('https://cdn.test/main.m3u8', master), ('https://cdn.test/full.m3u8', leaf)]):
            result = self.resolve(dict(DATA, hls_url='https://cdn.test/main.m3u8'), ['video'])
        self.assertEqual(result['formats'][0]['url'], 'https://cdn.test/full.m3u8')
        self.assertIsNone(result['formats'][0]['height'])
        self.assertEqual(result['diagnostics'], [])

    def test_nonstandard_and_malformed_ports_rejected_before_request(self):
        for url in [URL.replace('tv.cctv.com', 'tv.cctv.com:8443'), URL.replace('tv.cctv.com', 'tv.cctv.com:bad'), 'https://[bad/']:
            with patch.object(cctv, 'read_text') as read, self.assertRaises(Failure) as exc:
                cctv.resolve(url)
            self.assertEqual(exc.exception.code, 'invalid_url')
            read.assert_not_called()
        self.assertTrue(cctv._valid_url(URL.replace('tv.cctv.com', 'tv.cctv.com:443')))
