"""Channels link identities, official API responses and partial evidence.

Fixtures contain invented links/tokens, never captured account or media secrets.
"""
import copy
import json
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from scripts.platforms import Failure, select_formats, wechat

SHARE = 'https://weixin.qq.com/sph/PublicWork'
PREVIEW = wechat.PREVIEW + 'feed?token=public%2Baccess%3D&eid=export%2Fwork'
INFO = {'errCode': 0, 'data': {'errMsg': {'type': 0}, 'authorInfo': {'nickname': 'Author'},
        'feedInfo': {'description': 'Work description, not spoken words', 'picInfo': [],
                     'createtime': 1700000000, 'likeCountFmt': '83', 'commentCountFmt': '1.2万'}}}


class WechatTests(unittest.TestCase):
    def test_share_and_preview_identity_preserve_work_access(self):
        for url in (SHARE + '?tracking=ignored', wechat.PREVIEW + 'sph?id=PublicWork'):
            self.assertEqual(wechat._identity(url), ('PublicWork', SHARE, None))
        identifier, canonical, token = wechat._identity(PREVIEW + '&tracking=ignored')
        self.assertEqual(identifier, 'export/work')
        self.assertEqual(token, 'public+access=')
        self.assertEqual(parse_qs(urlsplit(canonical).query), {'eid': ['export/work'], 'token': ['public+access=']})

    def test_nonwork_malformed_and_nonplatform_urls_never_request(self):
        urls = [wechat.ORIGIN, 'https://weixin.qq.com/', SHARE.replace('weixin.qq.com', 'weixin.qq.com.evil.test'),
                'https://user:secret@weixin.qq.com/sph/PublicWork',
                wechat.PREVIEW + 'sph?id=one&id=two', wechat.PREVIEW + 'sph?id=',
                wechat.PREVIEW + 'feed?eid=work', PREVIEW + '&token=duplicate']
        with patch.object(wechat, 'read_json', side_effect=AssertionError('No HTTP for invalid work links')) as network:
            for url in urls:
                with self.subTest(url=url), self.assertRaises(Failure) as caught:
                    wechat.resolve(url, need=['video'])
                self.assertEqual(caught.exception.code, 'invalid_url')
        network.assert_not_called()

    def test_info_only_uses_anonymous_native_short_uri(self):
        with patch.object(wechat, 'read_json', return_value=INFO) as network:
            result = wechat.resolve(SHARE, cookies='explicit-file', need=['info'])
        self.assertEqual(network.call_count, 1)
        endpoint, = network.call_args.args
        params = parse_qs(urlsplit(endpoint).query)
        self.assertIn('_rid', params)
        self.assertEqual(params['_pageUrl'], [wechat.PREVIEW + 'sph?id=PublicWork'])
        self.assertEqual(json.loads(network.call_args.kwargs['data']), {'baseReq': {'generalToken': ''}, 'shortUri': 'PublicWork'})
        self.assertEqual(network.call_args.kwargs['cookies'], 'explicit-file')
        self.assertEqual(result['metadata']['author'], 'Author')
        self.assertIsNone(result['metadata']['duration'])
        self.assertIsNone(result['metadata']['comment_count'])
        self.assertEqual(result['formats'], [])
        self.assertEqual(result['diagnostics'], [])

    def test_media_missing_credentials_preserves_info_and_does_not_fake_captions(self):
        with patch.object(wechat, 'read_json', return_value=INFO) as network:
            result = wechat.resolve(SHARE, need=['info', 'transcript', 'video'])
        self.assertEqual(network.call_count, 1)
        self.assertEqual(result['source']['url'], SHARE)
        self.assertEqual(result['subtitles'], [])
        self.assertEqual(result['formats'], [])
        self.assertEqual({d['code'] for d in result['diagnostics']}, {'auth_required', 'subtitle_failed'})

    def test_explicit_session_unlocks_playback_using_official_endpoints(self):
        playable = copy.deepcopy(INFO)
        playable['data']['feedInfo'].update(mediaType=4, durationMs=3000, videoUrl='https://cdn.test/video.mp4?signature=ephemeral')
        with patch.object(wechat, 'read_json', side_effect=[INFO,
            {'code': 0, 'data': {'wx_export_id': 'export/work', 'playable_url': PREVIEW}}, playable]) as network:
            result = wechat.resolve(SHARE, cookies='explicit-file', need=['video'])
        calls = network.call_args_list
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[1].args, (wechat.PARSE,))
        self.assertEqual(json.loads(calls[1].kwargs['data']), {'type': 'video_channel_url', 'url': SHARE, 'scene': 1})
        self.assertEqual(json.loads(calls[2].kwargs['data']), {'baseReq': {'generalToken': 'public+access='}, 'exportId': 'export/work'})
        self.assertTrue(all(c.kwargs['cookies'] == 'explicit-file' for c in calls))
        self.assertTrue(all('Cookie' not in c.kwargs['headers'] and 't-userid' not in c.kwargs['headers'] for c in calls))
        self.assertEqual(result['source']['url'], SHARE)
        self.assertEqual(result['metadata']['duration'], 3)
        self.assertIsNone(result['formats'][0]['has_audio'])
        self.assertNotIn('ephemeral', json.dumps(result['metadata']))
        self.assertNotIn('public+access=', json.dumps(result['source']))

    def test_playback_url_needs_no_yuanbao_request_and_keeps_native_variants(self):
        data = copy.deepcopy(INFO)
        data['data']['feedInfo'].update(mediaType=4, videoUrl='https://cdn.test/low',
            h264VideoInfo={'videoUrl': 'https://cdn.test/high?signature=keep', 'width': 1920, 'height': 1080},
            h265VideoInfo={'videoUrl': 'https://cdn.test/low'}, bgm={'videoUrl': 'https://cdn.test/background'})
        with patch.object(wechat, 'read_json', return_value=data) as network:
            result = wechat.resolve(PREVIEW, need=['video'])
        self.assertEqual(network.call_count, 1)
        self.assertEqual(len(result['formats']), 2)
        self.assertEqual(select_formats(result['formats'], quality='source')[0]['url'], 'https://cdn.test/high?signature=keep')
        self.assertTrue(all(f['has_audio'] is None for f in result['formats']))

    def test_rejected_session_and_network_errors_are_distinct_and_keep_info(self):
        for error, expected in [(Failure('access_denied', 'HTTP 401'), 'auth_required'),
                                (Failure('network_failed', 'TLS failed'), 'network_failed')]:
            with self.subTest(expected=expected), patch.object(wechat, 'read_json', side_effect=[INFO, error]) as network:
                result = wechat.resolve(SHARE, cookies='explicit-file', need=['video'])
            self.assertEqual(network.call_count, 2)
            self.assertEqual(result['diagnostics'][0]['code'], expected)
            self.assertEqual(result['metadata']['author'], 'Author')

    def test_preview_restriction_is_not_reported_as_removed_or_bad_credentials(self):
        data = {'errCode': 0, 'data': {'errMsg': {'type': 4, 'title': '可前往微信观看此内容'}}}
        with patch.object(wechat, 'read_json', return_value=data) as network, self.assertRaises(Failure) as caught:
            wechat.resolve(PREVIEW, need=['video'])
        self.assertEqual(network.call_count, 1)
        self.assertEqual(caught.exception.code, 'experimental_access_limited')
        self.assertIn('type 4', str(caught.exception))

    def test_invalid_playback_response_cannot_request_an_arbitrary_host(self):
        responses = [[], {'code': 0, 'data': {'playable_url': 'https://evil.test/play?token=secret&eid=work'}},
                     {'code': 0, 'data': {'playable_url': SHARE}},
                     {'code': 0, 'data': {'playable_url': 'https://['}}]
        for response in responses:
            with self.subTest(response=response), patch.object(wechat, 'read_json', return_value=response) as network, self.assertRaises(Failure):
                wechat._playback(SHARE, 'explicit-file')
            self.assertEqual(network.call_count, 1)

    def test_image_posts_do_not_turn_into_video_or_use_cover(self):
        data = copy.deepcopy(INFO)
        data['data']['feedInfo'].update(mediaType=2, picInfo=[{'url': 'https://cdn.test/photo'}])
        with patch.object(wechat, 'read_json', return_value=data), self.assertRaises(Failure) as caught:
            wechat.resolve(SHARE, need=['info'])
        self.assertEqual(caught.exception.code, 'unsupported_content')

    def test_bad_urls_and_inherited_scrambling_do_not_break_info_or_create_formats(self):
        for feed in ({'videoUrl': 'https://['}, {'videoUrl': 'https:///no-host'},
                     {'videoUrl': 'https://user:secret@cdn.test/video'},
                     {'decodeKey': '123', 'h264VideoInfo': {'videoUrl': 'https://cdn.test/scrambled'}},
                     {'h264VideoInfo': {'videoUrl': 'https://cdn.test/scrambled', 'decodeKey': '123'}}):
            data = copy.deepcopy(INFO)
            data['data']['feedInfo'].update(feed)
            with self.subTest(feed=feed), patch.object(wechat, 'read_json', return_value=data):
                result = wechat.resolve(PREVIEW, need=['info', 'video'])
            self.assertEqual(result['metadata']['author'], 'Author')
            self.assertEqual(result['formats'], [])
            self.assertEqual(result['diagnostics'][0]['code'], 'media_unavailable')
