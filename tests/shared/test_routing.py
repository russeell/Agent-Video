"""Platform routing rejects unknown sources before any HTTP request."""
import unittest
from unittest.mock import patch
from scripts import platforms
from scripts.platforms import bilibili, douyin, tiktok, youtube


class RoutingTest(unittest.TestCase):
    def test_known_sources_dispatch_to_dedicated_platform_adapters(self):
        routes = [(bilibili, 'https://www.bilibili.com/video/BVexample', 2),
                  (youtube, 'https://www.youtube.com/shorts/abcdefghijk', None),
                  (tiktok, 'https://vm.tiktok.com/short/', None),
                  (douyin, 'https://v.douyin.com/short/', None),
                  (douyin, 'https://www.iesdouyin.com/share/video/123/', None)]
        with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('Routing must not access HTTP')) as network:
            for adapter, source, part in routes:
                expected = {'source': {'url': source}}
                with self.subTest(platform=adapter.__name__), patch.object(adapter, 'resolve', return_value=expected) as resolve:
                    self.assertIs(platforms.resolve(source, part=part, cookies='explicit-cookie-file', need=['info']), expected)
                resolve.assert_called_once_with(source, part=part, cookies='explicit-cookie-file', need=['info'])
        network.assert_not_called()

    def test_unsupported_sources_are_rejected_without_network(self):
        sources = [('https://example.test/video.mp4', 'unsupported_source'),
                   ('https://example.test/page.html', 'unsupported_source'),
                   ('https://example.test/vod.m3u8', 'unsupported_source'),
                   ('https://youtube.com.evil.test/watch?v=abcdefghijk', 'unsupported_source'),
                   ('https://v.qq.com/x/page/q326831cny0.html', 'unsupported_source'),
                   ('https://m.v.qq.com/x/page/q326831cny0.html', 'unsupported_source'),
                   ('ftp://www.youtube.com/watch?v=abcdefghijk', 'invalid_url'),
                   ('file://www.youtube.com/watch?v=abcdefghijk', 'invalid_url')]
        with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('Unknown sources must not access HTTP')) as network:
            for source, code in sources:
                with self.subTest(source=source), self.assertRaises(platforms.Failure) as caught:
                    platforms.resolve(source, need=['info', 'video'])
                self.assertEqual(caught.exception.code, code)
        network.assert_not_called()


if __name__ == '__main__':
    unittest.main()
