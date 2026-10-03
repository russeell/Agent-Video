"""Weibo exact post/TV identity, guest bootstrap and highest media selection."""
import json
import unittest
from unittest.mock import patch
from scripts import platforms
from scripts.platforms import weibo

POST = {'id': 123, 'id_str': '123', 'mblogid': 'AbCd', 'text_raw': 'A clip',
        'user': {'screen_name': 'Author'}, 'page_info': {'object_id': '1034:1234567890123456',
        'page_pic': 'https://cdn.test/thumb.jpg', 'media_info': {'duration': 4, 'playback_list': [
            {'play_info': {'url': 'https://cdn.test/720.mp4', 'width': 1280, 'height': 720, 'audio_codecs': 'aac', 'fps': 30}},
            {'play_info': {'url': 'https://cdn.test/1080.mp4', 'width': 1920, 'height': 1080, 'audio_codecs': 'aac', 'fps': 30}}]}}}


class WeiboTests(unittest.TestCase):
    def test_single_work_urls_and_feed_rejection(self):
        self.assertEqual(weibo._identity('https://weibo.com/123/AbCd'), ('status', 'AbCd'))
        self.assertEqual(weibo._identity('https://m.weibo.cn/detail/123'), ('status', '123'))
        self.assertEqual(weibo._identity('https://weibo.com/tv/show/1034:1234567890123456'), ('tv', '1034:1234567890123456'))
        for url in ['https://weibo.com/u/123', 'https://weibo.com/123', 'https://evil.test/123/AbCd']:
            with self.assertRaises(platforms.Failure):
                weibo._identity(url)

    def test_info_does_not_parse_or_download_media(self):
        with patch.object(weibo, '_json', return_value=POST), patch.object(weibo, '_formats') as formats:
            result = weibo._resolve('https://weibo.com/123/AbCd', need=['info'])
        formats.assert_not_called()
        self.assertEqual(result['source']['id'], '123')
        self.assertEqual(result['formats'], [])
        self.assertEqual(result['metadata']['duration'], 4)

    def test_highest_returned_quality_and_original_audio(self):
        with patch.object(weibo, '_json', return_value=POST):
            result = weibo._resolve('https://m.weibo.cn/status/123', need=['video'])
        selected = platforms.select_formats(result['formats'], quality='source')[0]
        self.assertEqual((selected['width'], selected['height']), (1920, 1080))
        self.assertTrue(selected['has_audio'])
        self.assertTrue(result['metadata']['audio_expected'])

    def test_tv_cross_checks_actual_work_object(self):
        component = {'data': {'Component_Play_Playinfo': {'mid': '123'}}}
        with patch.object(weibo, '_json', side_effect=[component, POST]):
            result = weibo._resolve('https://weibo.com/tv/show/1034:1234567890123456', need=['info'])
        self.assertEqual(result['source']['url'], 'https://weibo.com/tv/show/1034:1234567890123456')
        with patch.object(weibo, '_json', side_effect=[component, POST]):
            with self.assertRaises(platforms.Failure) as caught:
                weibo._resolve('https://weibo.com/tv/show/1034:9999999999999999', need=['video'])
        self.assertEqual(caught.exception.code, 'parse_failed')

    def test_multiple_videos_never_implicitly_downloaded(self):
        post = {**POST, 'mix_media_info': {'items': [
            {'type': 'video', 'data': {'object_id': 'one'}},
            {'type': 'video', 'data': {'object_id': 'two'}}]}}
        with patch.object(weibo, '_json', return_value=post):
            with self.assertRaises(platforms.Failure) as caught:
                weibo._resolve('https://m.weibo.cn/status/123', need=['video'])
        self.assertEqual(caught.exception.code, 'media_ambiguous')

    def test_visitor_handshake_once_without_raw_cookie_header(self):
        blocked = '<title>Sina Visitor System</title>'
        responses = [blocked, 'window.gen_callback && gen_callback({"retcode":20000000,"data":{"tid":"anonymous-visitor","new_tid":true}});',
                     'cross_domain({"retcode":20000000});', json.dumps(POST)]
        with patch.object(weibo, 'read_text', side_effect=responses) as read:
            result = weibo._json('https://weibo.com/ajax/statuses/show?id=123')
        self.assertEqual(result['id'], 123)
        self.assertEqual(read.call_count, 4)
        for call in read.call_args_list:
            self.assertNotIn('Cookie', call.kwargs.get('headers', {}))
            self.assertNotIn('Authorization', call.kwargs.get('headers', {}))

    def test_repeated_visitor_page_is_access_failure(self):
        blocked = '<title>Sina Visitor System</title>'
        with patch.object(weibo, 'read_text', return_value=blocked) as read, patch.object(weibo, '_bootstrap') as bootstrap:
            with self.assertRaises(platforms.Failure) as caught:
                weibo._json('https://weibo.com/ajax/statuses/show?id=123')
        self.assertEqual(caught.exception.code, 'access_denied')
        self.assertEqual(bootstrap.call_count, 1)
        self.assertEqual(read.call_count, 2)

    def test_wrong_post_and_missing_captions_preserve_uncertainty(self):
        with self.assertRaises(platforms.Failure):
            weibo._status(POST, 'different')
        with patch.object(weibo, '_json', return_value=POST):
            result = weibo._resolve('https://m.weibo.cn/detail/123', need=['transcript'])
        self.assertEqual(result['diagnostics'][0]['code'], 'subtitle_failed')
        self.assertEqual(result['formats'], [])

    def test_jsonp_is_only_decoded_not_executed(self):
        self.assertEqual(weibo._jsonp('window.gen_callback && gen_callback({"data":{"tid":"guest"}});', 'gen_callback')['data']['tid'], 'guest')
        with self.assertRaises(platforms.Failure):
            weibo._jsonp('gen_callback(alert("execute"));', 'gen_callback')
