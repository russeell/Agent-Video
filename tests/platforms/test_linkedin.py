import unittest
from unittest.mock import patch
from scripts.platforms import Failure, linkedin

URL = 'https://www.linkedin.com/posts/demo-activity-7151241570371948544-4Gu7'
PAGE = '''<meta property="og:title" content="Demo"><video data-sources='[{"src":"https://dms.licdn.com/mp4-720p-30fp/video?sig=secret","type":"video/mp4","data-bitrate":42}]' data-captions-url="https://cdn.test/captions.vtt" data-language="en"></video><script type="application/ld+json">{"@type":"VideoObject","creator":{"name":"Author"},"duration":"PT2M41S"}</script>'''


class LinkedInTests(unittest.TestCase):
    def test_info_does_not_offer_signed_media(self):
        with patch.object(linkedin, 'read_text', return_value=PAGE) as read:
            result = linkedin.resolve(URL + '?tracking=1', need=['info'])
        self.assertEqual(read.call_count, 1)
        self.assertEqual(result['formats'], [])
        self.assertEqual(result['subtitles'], [])
        self.assertEqual(result['metadata']['duration'], 161)
        self.assertEqual(result['metadata']['author'], 'Author')
        self.assertNotIn('secret', str(result['metadata']))
        self.assertNotIn('tracking', result['source']['url'])

    def test_native_media_height_and_caption_language(self):
        with patch.object(linkedin, 'read_text', return_value=PAGE):
            result = linkedin.resolve(URL, need=['video', 'transcript'])
        self.assertEqual(result['formats'][0]['height'], 720)
        self.assertIsNone(result['formats'][0]['has_audio'])
        self.assertEqual(result['subtitles'][0]['language'], 'en')
        self.assertIsNone(result['metadata']['original_language'])

    def test_unknown_language_not_assumed_english(self):
        with patch.object(linkedin, 'read_text', return_value=PAGE.replace(' data-language="en"', '')):
            result = linkedin.resolve(URL, need=['transcript'])
        self.assertEqual(result['subtitles'][0]['language'], '')
        self.assertEqual(result['formats'], [])

    def test_external_video_not_claimed_native(self):
        with patch.object(linkedin, 'read_text', return_value='<meta property="og:title" content="YouTube video">'), self.assertRaises(Failure):
            linkedin.resolve(URL)

    def test_learning_events_and_other_hosts_rejected(self):
        with patch.object(linkedin, 'read_text') as read:
            for url in ('https://linkedin.com/learning/test', 'https://linkedin.com/events/42', 'https://evil.test/posts/demo-7151241570371948544-4Gu7'):
                with self.assertRaises(Failure):
                    linkedin.resolve(url)
        read.assert_not_called()

    def test_returned_page_identity_must_match_when_exposed(self):
        wrong = 'https://www.linkedin.com/posts/other-activity-1234567890123456789-test'
        for identity in ('<meta property="og:url" content="' + wrong + '">', '<link rel="canonical" href="' + wrong + '">', '<script type="application/ld+json">{"@type":"VideoObject","@id":"' + wrong + '"}</script>'):
            with patch.object(linkedin, 'read_text', return_value=identity + PAGE), self.assertRaises(Failure) as error:
                linkedin.resolve(URL, need=['info'])
            self.assertEqual(error.exception.code, 'parse_failed')
        declaration = '<meta property="og:url" content="https://www.linkedin.com/feed/update/urn:li:activity:7151241570371948544">'
        with patch.object(linkedin, 'read_text', return_value=declaration + PAGE):
            result = linkedin.resolve(URL, need=['info'])
        self.assertEqual(result['source']['id'], '7151241570371948544')

    def test_distinct_native_players_are_rejected_but_duplicate_is_not(self):
        other = PAGE.replace('/video?sig=secret', '/other-video?sig=secret')
        with patch.object(linkedin, 'read_text', return_value=PAGE + other), self.assertRaises(Failure) as error:
            linkedin.resolve(URL, need=['video'])
        self.assertEqual(error.exception.code, 'media_ambiguous')
        with patch.object(linkedin, 'read_text', return_value=PAGE + PAGE):
            result = linkedin.resolve(URL, need=['video'])
        self.assertEqual(len(result['formats']), 1)
