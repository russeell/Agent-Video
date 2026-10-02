"""Douyin single-work public data and honest challenge diagnostics."""
import json
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import quote
from scripts import platforms
from scripts.platforms import douyin


class DouyinPublicDataTests(unittest.TestCase):
    def test_single_video_entry_points_have_one_identity(self):
        identifier = '7678365009231056166'
        sources = [f'https://www.douyin.com/video/{identifier}',
                   f'https://www.douyin.com/jingxuan?modal_id={identifier}',
                   f'https://www.douyin.com/?modal_id={identifier}&previous_page=app',
                   f'https://www.iesdouyin.com/share/video/{identifier}/']
        item = {'aweme_id': identifier, 'desc': 'Video', 'video': {'duration': 2000}}
        page = '<script id="RENDER_DATA">' + quote(json.dumps(item)) + '</script>'
        canonical = f'https://www.douyin.com/video/{identifier}'
        for source in sources:
            with self.subTest(source=source), patch.object(douyin, 'read_text', return_value=page) as read, \
                    patch.object(douyin, '_browser_item') as browser:
                result = platforms.resolve(source, need={'info'})
                self.assertEqual(result['source'], {'platform': 'douyin', 'id': identifier, 'url': canonical})
                read.assert_called_once_with(canonical, cookies=None)
                browser.assert_not_called()
        for destination in (sources[1], sources[3]):
            with self.subTest(redirect=destination), patch.object(douyin, 'request') as request:
                response = request.return_value.__enter__.return_value
                response.geturl.return_value = destination
                self.assertEqual(douyin._identifier('https://v.douyin.com/example/', 'explicit-cookies.txt'), identifier)
                request.assert_called_once_with('https://v.douyin.com/example/', cookies='explicit-cookies.txt')

    def test_invalid_or_ambiguous_identity_never_reads_a_page(self):
        sources = ['https://www.douyin.com/jingxuan',
                   'https://www.douyin.com/jingxuan?modal_id=not-a-video',
                   'https://www.douyin.com/video/123?modal_id=456',
                   'https://www.douyin.com/?modal_id=123&modal_id=456',
                   'https://www.douyin.com/video/123/other']
        with patch.object(douyin, 'read_text') as read:
            for source in sources:
                with self.subTest(source=source), self.assertRaises(platforms.Failure) as caught:
                    douyin.resolve(source)
                self.assertEqual(caught.exception.code, 'invalid_url')
            read.assert_not_called()
        for destination in ('https://douyin.com.evil.test/video/123',
                            'https://example.test/share/video/123'):
            with self.subTest(redirect=destination), patch.object(douyin, 'request') as request:
                request.return_value.__enter__.return_value.geturl.return_value = destination
                with self.assertRaises(platforms.Failure) as caught:
                    douyin._identifier('https://v.douyin.com/example/')
                self.assertEqual(caught.exception.code, 'invalid_url')

    def test_signature_challenge_is_not_authentication_or_absent_subtitles(self):
        page = '<script>window.byted_acrawler; var __ac_signature;</script>'
        with self.assertRaises(platforms.Failure) as caught:
            douyin._embedded(page)
        self.assertEqual(caught.exception.code, 'player_challenge_unsupported')
        self.assertIn(str(len(page.encode('utf-8'))), str(caught.exception))
        self.assertNotIn('auth_required', str(caught.exception))

    def test_embedded_data_keeps_exact_single_work_identity(self):
        item = {'aweme_id': '123', 'video': {'duration': 2000}}
        data = {'loaderData': {'page': {'item_list': [item]}}}
        pages = ['<script id="RENDER_DATA">' + quote(json.dumps(data)) + '</script>']
        for page in pages:
            with self.subTest(page=page[:30]):
                extracted = douyin._embedded(page)
                self.assertEqual(douyin._find(extracted, '123'), item)
                self.assertIsNone(douyin._find(extracted, '456'))
        with self.assertRaises(platforms.Failure) as caught:
            douyin._embedded('<script id="RENDER_DATA">not json</script>')
        self.assertEqual(caught.exception.code, 'parse_failed')

    def test_challenge_browser_work_normalizes_media_and_forwards_cookies(self):
        identifier = '123'
        canonical = 'https://www.douyin.com/video/' + identifier
        item = {'aweme_id': identifier, 'desc': 'Synthetic tutorial', 'author': {'nickname': 'Example'},
                'music': {'play_url': {'url_list': ['https://example.test/music.mp3']}},
                'video': {'duration': 2000, 'width': 720, 'height': 1280,
                          'play_addr': {'url_list': ['https://example.test/base.mp4'], 'width': 720, 'height': 1280},
                          'play_addr_h264': {'url_list': ['https://example.test/h264.mp4'], 'width': 1080, 'height': 1920},
                          'bit_rate': [{'bit_rate': 4000000, 'FPS': 30, 'is_h265': 0,
                                        'play_addr': {'url_list': ['https://example.test/high.mp4'],
                                                      'width': 1440, 'height': 2560, 'data_size': 1000000}},
                                       {'format': 'dash', 'play_addr': {'url_list': ['https://example.test/dash.mp4'],
                                                                       'width': 2160, 'height': 3840}},
                                       {'is_bytevc2': 1, 'play_addr': {'url_list': ['https://example.test/bytevc2.mp4'],
                                                                      'width': 2160, 'height': 3840}}]}}
        page = '<script>window.byted_acrawler; var __ac_signature;</script>'
        with patch.object(douyin, 'read_text', return_value=page), \
                patch.object(douyin, '_browser_item', return_value=item) as browser:
            result = douyin.resolve(canonical, cookies='explicit-cookies.txt', need={'info', 'video'})
        browser.assert_called_once_with(identifier, cookies='explicit-cookies.txt')
        self.assertEqual(result['source'], {'platform': 'douyin', 'id': identifier, 'url': canonical})
        self.assertEqual(result['metadata']['title'], item['desc'])
        self.assertEqual(result['metadata']['author'], 'Example')
        self.assertEqual(result['metadata']['duration'], 2)
        self.assertNotIn('https://example.test/music.mp3', [f['url'] for f in result['formats']])
        selected = platforms.select_formats(result['formats'], quality='source')
        self.assertEqual(selected[0]['url'], 'https://example.test/high.mp4')
        self.assertEqual((selected[0]['width'], selected[0]['height']), (1440, 2560))
        self.assertTrue(selected[0]['has_video'] and selected[0]['has_audio'])
        with patch.object(douyin, 'read_text', return_value=page), \
                patch.object(douyin, '_browser_item', return_value=item):
            info = douyin.resolve(canonical, need={'info'})
        self.assertEqual(info['formats'], [])
        self.assertIs(info['metadata']['audio_expected'], True)

    def test_browser_result_cannot_substitute_another_work_or_image_post(self):
        page = '<script>window.byted_acrawler; var __ac_signature;</script>'
        items = [{'aweme_id': '456', 'video': {'duration': 1000}},
                 {'aweme_id': '123', 'aweme_type': 68, 'images': [{'url_list': ['https://example.test/image.jpg']}],
                  'video': {'duration': 1000, 'play_addr': {'url_list': ['https://example.test/image-animation.mp4']}}}]
        for item in items:
            with self.subTest(kind='wrong_id' if item['aweme_id'] == '456' else 'images'), \
                    patch.object(douyin, 'read_text', return_value=page), \
                    patch.object(douyin, '_browser_item', return_value=item), \
                    self.assertRaises(platforms.Failure) as caught:
                douyin.resolve('https://www.douyin.com/video/123', need={'info', 'video'})
            self.assertEqual(caught.exception.code, 'parse_failed' if item['aweme_id'] == '456' else 'unsupported_content')

    def test_h264_address_dimensions_override_base_video_dimensions(self):
        video = {'width': 360, 'height': 640,
                 'play_addr': {'url_list': ['https://example.test/base.mp4'], 'width': 360, 'height': 640},
                 'play_addr_h264': {'url_list': ['https://example.test/h264.mp4'], 'width': 1080, 'height': 1920}}
        formats = douyin._formats(video, 'https://www.douyin.com/video/123')
        selected = platforms.select_formats(formats, quality='source')
        self.assertEqual(selected[0]['url'], 'https://example.test/h264.mp4')
        self.assertEqual((selected[0]['width'], selected[0]['height']), (1080, 1920))

    def test_browser_target_response_and_broken_pipe_cleanup(self):
        from collections import deque
        events = deque()
        sent = []
        socket, process = Mock(), Mock()
        process.wait.return_value = 0
        def response(request, url):
            return json.dumps({'method': 'Network.responseReceived',
                               'params': {'requestId': request, 'response': {'url': url}}})
        def finished(request):
            return json.dumps({'method': 'Network.loadingFinished', 'params': {'requestId': request}})
        endpoint = 'https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id='
        events.extend([response('other', endpoint + '456'), finished('other'),
                       response('bad', endpoint + '123'), finished('bad'),
                       response('good', endpoint + '123'), finished('good')])
        expected = {'aweme_id': '123', 'video': {'duration': 1000}}
        def send(raw):
            message = json.loads(raw)
            sent.append(message)
            if message['method'] == 'Network.getResponseBody':
                item = expected if message['params']['requestId'] == 'good' else {'aweme_id': '456'}
                events.append(json.dumps({'id': message['id'], 'result': {
                    'body': json.dumps({'aweme_detail': item}), 'base64Encoded': False}}))
            if message['method'] == 'Browser.close':
                raise BrokenPipeError('Synthetic browser already exited')
        socket.send.side_effect = send
        socket.recv.side_effect = events.popleft
        socket.close.side_effect = OSError('Synthetic closed socket')
        with tempfile.TemporaryDirectory() as temporary:
            browser = Path(temporary) / 'fake-chrome'
            browser.touch()
            profiles = []
            def launch(args, **kwargs):
                profile = Path(next(a.split('=', 1)[1] for a in args if a.startswith('--user-data-dir=')))
                profiles.append(profile)
                (profile / 'DevToolsActivePort').write_text('12345\n/devtools/browser/example\n')
                self.assertEqual(args[-1], 'about:blank')
                self.assertIn('--remote-debugging-address=127.0.0.1', args)
                self.assertTrue(kwargs['start_new_session'])
                return process
            local = Mock()
            local.open.return_value.__enter__ = Mock(return_value=io.StringIO(json.dumps([
                {'type': 'page', 'webSocketDebuggerUrl': 'ws://127.0.0.1:12345/devtools/page/example'}])))
            local.open.return_value.__exit__ = Mock(return_value=False)
            with patch.object(douyin.shutil, 'which', return_value=str(browser)), \
                    patch.object(douyin.subprocess, 'Popen', side_effect=launch), \
                    patch.object(douyin, 'build_opener', return_value=local), \
                    patch('websocket.create_connection', return_value=socket):
                self.assertEqual(douyin._browser_item('123'), expected)
            self.assertFalse(profiles[0].exists())
            local.open.assert_called_once_with('http://127.0.0.1:12345/json/list', timeout=3)
        self.assertEqual([m['params']['requestId'] for m in sent if m['method'] == 'Network.getResponseBody'], ['bad', 'good'])
        self.assertFalse(any(m['method'] == 'Network.setCookies' for m in sent))
        self.assertTrue(any(m['method'] == 'Network.setBlockedURLs' and '*://*.douyinvod.com/*' in m['params']['urls'] for m in sent))
        self.assertIn({'url': 'https://www.douyin.com/video/123'}, [m['params'] for m in sent if m['method'] == 'Page.navigate'])
        socket.close.assert_called_once()
        process.wait.assert_called_once_with(timeout=3)

    def test_browser_failures_clean_up_and_missing_chrome_is_explicit(self):
        with patch.object(douyin.shutil, 'which', return_value=None), \
                patch.object(douyin.Path, 'is_file', return_value=False), \
                patch.object(douyin.subprocess, 'Popen') as launch:
            with self.subTest(case='missing_chrome'), self.assertRaises(platforms.Failure) as caught:
                douyin._browser_item('123')
            self.assertEqual(caught.exception.code, 'dependency_missing')
            launch.assert_not_called()
        with tempfile.TemporaryDirectory() as temporary:
            browser = Path(temporary) / 'fake-chrome'
            browser.touch()
            for scenario in ('connection_error', 'timeout'):
                process, socket, local = Mock(), Mock(), Mock()
                process.wait.side_effect = [subprocess.TimeoutExpired('chrome', 3),
                                            subprocess.TimeoutExpired('chrome', 3), 0]
                local.open.return_value.__enter__ = Mock(return_value=io.StringIO(json.dumps([
                    {'type': 'page', 'webSocketDebuggerUrl': 'ws://127.0.0.1:12345/devtools/page/example'}])))
                local.open.return_value.__exit__ = Mock(return_value=False)
                profiles = []
                def launch(args, **kwargs):
                    profile = Path(next(a.split('=', 1)[1] for a in args if a.startswith('--user-data-dir=')))
                    profiles.append(profile)
                    (profile / 'DevToolsActivePort').write_text('12345\n')
                    return process
                with self.subTest(case=scenario), \
                        patch.object(douyin.shutil, 'which', return_value=str(browser)), \
                        patch.object(douyin.subprocess, 'Popen', side_effect=launch), \
                        patch.object(douyin, 'build_opener', return_value=local), \
                        patch('websocket.create_connection', side_effect=OSError('Synthetic connection failure') if scenario == 'connection_error' else None,
                              return_value=socket), \
                        patch.object(douyin.time, 'monotonic', side_effect=[0, 0, 21]), \
                        patch.object(douyin.os, 'killpg', side_effect=ProcessLookupError, create=True) as kill, \
                        self.assertRaises(platforms.Failure) as caught:
                    douyin._browser_item('123')
                self.assertEqual(caught.exception.code, 'browser_failed' if scenario == 'connection_error' else 'experimental_access_limited')
                self.assertFalse(profiles[0].exists())
                self.assertEqual(process.wait.call_count, 3)
                if os.name == 'posix':
                    self.assertEqual(kill.call_count, 2)
                if scenario == 'timeout':
                    socket.close.assert_called_once()
                    socket.recv.assert_not_called()


if __name__ == '__main__':
    unittest.main()
