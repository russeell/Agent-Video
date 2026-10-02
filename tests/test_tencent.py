import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from platforms import Failure, tencent

URL = 'https://v.qq.com/x/page/q326831cny0.html'


def response(name='hd', width=1280, height=720):
    return {'code': '0.0', 's': 'o',
            'fl': {'fi': [{'name': name, 'br': width, 'drm': 0, 'lmt': 0,
                          'video': 1, 'audio': 1, 'bandwidth': 1000000}]},
            'vl': {'vi': [{'ti': 'Public video', 'td': '215.96', 'drm': 0,
                           'iflag': 0, 'pl': [], 'br': width, 'vw': width, 'vh': height,
                           'fn': 'sample.mp4', 'fvkey': 'temporary-key', 'cl': {'fc': 0},
                           'ul': {'ui': [{'url': 'https://cdn.example/'},
                                         {'url': 'https://mirror.example/'}]}}]}}


class TencentTest(unittest.TestCase):
    def test_ckey_known_vector(self):
        encrypted = tencent._ckey('q326831cny0', URL, '0123456789abcdef', 1700000000)
        self.assertEqual(hashlib.sha256(bytes.fromhex(encrypted)).hexdigest(),
                         '8ffd02b8e75523d232ecca465017e4d9c1a6d5ef674e24d23ac0048721d1ead5')

    def test_direct_and_canonical_identity(self):
        with patch.object(tencent, '_api', return_value=response()) as api:
            result = tencent.resolve(URL + '?tracking=discarded', need=['info', 'video'])
        self.assertEqual(result['source'], {'platform': 'tencent', 'id': 'q326831cny0', 'url': URL})
        self.assertEqual(result['metadata']['duration'], 215.96)
        self.assertEqual(len(result['formats']), 1)
        self.assertEqual(result['formats'][0]['url'], 'https://cdn.example/sample.mp4?vkey=temporary-key')
        self.assertTrue(result['formats'][0]['has_audio'])
        self.assertNotIn('temporary-key', json.dumps(result['metadata']))
        self.assertEqual(api.call_count, 1)

    def test_actual_advertised_higher_quality_and_fallback(self):
        first = response()
        first['fl']['fi'].extend([{'name': 'fhd', 'br': 1920, 'drm': 0, 'lmt': 0},
                                  {'name': 'uhd', 'drm': 1, 'lmt': 0},
                                  {'name': 'vip', 'drm': 0, 'lmt': 1}])
        with patch.object(tencent, '_api', side_effect=[first, response('fhd', 1920, 1080)]) as api:
            result = tencent.resolve(URL, need=['video'])
        self.assertEqual([f['quality_id'] for f in result['formats']], ['hd', 'fhd'])
        self.assertEqual(api.call_args_list[1].args[3], 'fhd')
        with patch.object(tencent, '_api', side_effect=[first, response()]):
            downgraded = tencent.resolve(URL, need=['video'])
        self.assertEqual(len(downgraded['formats']), 1)

    def test_restricted_media_preserves_metadata_but_no_candidates(self):
        for field, value, code in [('drm', 1, 'drm_unsupported'),
                                    ('iflag', 1, 'preview_only'), ('pl', [90], 'preview_only')]:
            with self.subTest(field=field):
                data = response()
                data['vl']['vi'][0][field] = value
                with patch.object(tencent, '_api', return_value=data):
                    result = tencent.resolve(URL, need=['info', 'video'])
                self.assertEqual(result['metadata']['title'], 'Public video')
                self.assertEqual(result['formats'], [])
                self.assertEqual(result['diagnostics'][0]['code'], code)
        for field, value, code in [('drm', 1, 'drm_unsupported'),
                                    ('lmt', 1, 'membership_required'), ('preview', 90, 'preview_only')]:
            with self.subTest(format_field=field):
                data = response()
                data['fl']['fi'][0][field] = value
                with self.assertRaises(Failure) as caught:
                    tencent._formats(data)
                self.assertEqual(caught.exception.code, code)

    def test_hls_candidate_and_direct_clip_rejection(self):
        data = response()
        video = data['vl']['vi'][0]
        video['ul']['ui'] = [{'url': 'https://cdn.example/', 'hls': {'pt': 'vod.m3u8?key=ephemeral'}}]
        candidate = tencent._formats(data)[0]
        self.assertEqual(candidate['protocol'], 'hls')
        self.assertEqual(candidate['url'], 'https://cdn.example/vod.m3u8?key=ephemeral')
        direct = response()
        direct['vl']['vi'][0]['cl']['fc'] = 2
        with self.assertRaises(Failure) as caught:
            tencent._formats(direct)
        self.assertEqual(caught.exception.code, 'format_unsupported')

    def test_api_jsonp_and_restriction_diagnostics(self):
        with patch.object(tencent, '_ckey', return_value='signature'), patch.object(tencent, 'read_text',
                return_value='QZOutputJson=' + json.dumps(response()) + ';') as read:
            self.assertEqual(tencent._api('q326831cny0', URL, None, 'hd', None)['code'], '0.0')
            self.assertIn('drm=0', read.call_args.args[0])
        for message, code in [('not pay', 'membership_required'), ('need login', 'auth_required'),
                               ('您所在区域暂无此内容版权', 'geo_restricted')]:
            with patch.object(tencent, '_ckey', return_value='signature'), patch.object(tencent, 'read_text',
                    return_value='QZOutputJson=' + json.dumps({'code': '1.0', 's': 'f', 'msg': message}) + ';'):
                with self.assertRaises(Failure) as caught:
                    tencent._api('q326831cny0', URL, None, 'hd', None)
                self.assertEqual(caught.exception.code, code)

    def test_single_video_boundary_and_info_only(self):
        for url in ['https://v.qq.com/x/cover/series.html', 'https://v.qq.com.evil.test/x/page/q326831cny0.html']:
            with self.assertRaises(Failure):
                tencent.resolve(url)
        with self.assertRaises(Failure):
            tencent.resolve(URL, part=1)
        first = response()
        first['fl']['fi'].append({'name': 'fhd', 'drm': 0})
        with patch.object(tencent, '_api', return_value=first) as api:
            result = tencent.resolve(URL, need=['info'])
        self.assertEqual(result['formats'], [])
        self.assertEqual(api.call_count, 1)


if __name__ == '__main__':
    unittest.main()
