"""Platform routing rejects unknown sources before any HTTP request."""
import unittest
from unittest.mock import patch
from scripts import platforms
from scripts.platforms import (bilibili, dailymotion, douyin, instagram, kuaishou,
                              pornhub, reddit, ted, tiktok, twitch, twitter, vimeo, weibo,
                              wechat, xiaohongshu, youtube)


class RoutingTest(unittest.TestCase):
    def test_known_sources_dispatch_to_dedicated_platform_adapters(self):
        routes = [(bilibili, 'https://www.bilibili.com/video/BVexample', 2),
                  (youtube, 'https://www.youtube.com/shorts/abcdefghijk', None),
                  (tiktok, 'https://vm.tiktok.com/short/', None),
                  (douyin, 'https://v.douyin.com/short/', None),
                  (douyin, 'https://www.iesdouyin.com/share/video/123/', None),
                  (twitter, 'https://x.com/example/status/1234', None),
                  (twitter, 'https://twitter.com/example/status/1234/video/2', None),
                  (reddit, 'https://www.reddit.com/r/videos/comments/abc123/title/', None),
                  (reddit, 'https://m.reddit.com/comments/abc123/', None),
                  (instagram, 'https://www.instagram.com/reel/example/', None),
                  (xiaohongshu, 'https://xhslink.com/example', None),
                  (kuaishou, 'https://v.kuaishou.com/example', None),
                  (kuaishou, 'https://v.m.chenzhongtech.com/fw/photo/example', None),
                  (vimeo, 'https://player.vimeo.com/video/1234', None),
                  (dailymotion, 'https://dai.ly/abc123', None),
                  (ted, 'https://www.ted.com/talks/example', None),
                  (twitch, 'https://clips.twitch.tv/example', None),
                  (weibo, 'https://m.weibo.cn/status/1234', None),
                  (wechat, 'https://weixin.qq.com/sph/PublicWork', None),
                  (wechat, 'https://channels.weixin.qq.com/finder-preview/pages/sph?id=PublicWork', None),
                  (wechat, 'https://channels.weixin.qq.com/finder-preview/pages/feed?token=public&eid=work', None),
                  (pornhub, 'https://cn.pornhub.com/view_video.php?viewkey=ph1234', None)]
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
                   ('https://www.facebook.com/watch/?v=1234', 'unsupported_source'),
                   ('https://www.netflix.com/title/1234', 'unsupported_source'),
                   ('https://weixin.qq.com.evil.test/sph/PublicWork', 'unsupported_source'),
                   ('https://x.com.evil.test/example/status/1234', 'unsupported_source'),
                   ('https://pornhub.com.evil.test/view_video.php?viewkey=ph1234', 'unsupported_source'),
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
