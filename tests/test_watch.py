"""Offline user flows using real tiny media; mocks isolate platform network calls."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import watch, media


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg is required')
class WatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.video = self.root / 'sample.mp4'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                        'testsrc2=size=160x120:rate=5:duration=2', '-f', 'lavfi', '-i',
                        'sine=frequency=440:duration=2', '-c:v', 'mpeg4', '-c:a', 'aac', '-shortest', self.video], check=True)
        self.video.with_suffix('.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\nHello world\n\n2\n00:00:01,000 --> 00:00:02,000\nAgain\n')

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = watch.main(list(args))
        return code, json.loads(out.getvalue())

    def new(self, *args):
        return self.call(str(self.video), '--out', str(self.root / 'out'), *args)

    def test_followup_subtitle_frames_video_and_source_unchanged(self):
        original = self.video.read_bytes()
        code, result = self.new()
        self.assertEqual(code, 0)
        evidence = result['manifest']
        text = next(a for a in result['artifacts'] if a['type'] == 'transcript')
        self.assertEqual(json.loads(Path(text['path']).read_text())['segments'][0]['text'], 'Hello world')
        code, result = self.call('--evidence', evidence, '--get', 'frames', '--at', '0.2', '--width', '80')
        self.assertEqual(code, 0, result)
        frame = next(a for a in result['artifacts'] if a['type'] == 'frames')
        self.assertEqual(media.probe(frame['path'])['video']['width'], 80)
        code, repeated = self.call('--evidence', evidence, '--get', 'frames', '--at', '0.2', '--width', '80')
        self.assertEqual(next(a['path'] for a in repeated['artifacts'] if a['type'] == 'frames'), frame['path'])
        code, result = self.call('--evidence', evidence, '--get', 'video,audio')
        self.assertEqual(code, 0, result)
        movie = next(a for a in result['artifacts'] if a['type'] == 'video')
        self.assertTrue(media.probe(movie['path'])['audio'])
        self.assertEqual(self.video.read_bytes(), original)
        code, result = self.call('--evidence', evidence, '--get', 'transcript', '--start', '1', '--end', '1.8')
        self.assertEqual(code, 0)
        transcript = next(a for a in result['artifacts'] if a['type'] == 'transcript')
        self.assertEqual(json.loads(Path(transcript['path']).read_text())['segments'][0]['start'], 1)

    def test_partial_and_invalid_inputs(self):
        self.video.with_suffix('.srt').unlink()
        with patch.dict('os.environ', {'AGENT_VIDEO_ASR_MODEL': ''}):
            code, result = self.new('--get', 'transcript,frames', '--at', '0.2')
        self.assertEqual(code, 2)
        self.assertEqual(result['status'], 'partial')
        self.assertTrue(any(a['type'] == 'frames' for a in result['artifacts']))
        code, result = self.new('--get', 'frames', '--at', '0,1', '--max-frames', '1')
        self.assertEqual(code, 64)

    def test_source_change_removes_index_preserves_old_files(self):
        code, result = self.new()
        evidence = result['manifest']
        old = next(a['path'] for a in result['artifacts'] if a['type'] == 'transcript')
        import os
        stat = self.video.stat()
        os.utime(self.video, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000))
        code, result = self.call('--evidence', evidence)
        self.assertEqual(code, 0)
        current = json.loads(Path(evidence).read_text())
        self.assertNotIn(Path(old).name, [a['path'] for a in current['artifacts']])
        self.assertTrue(Path(old).exists())

    def test_language_change_and_path_protection(self):
        self.video.with_suffix('.srt').unlink()
        self.video.with_suffix('.en.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\nEnglish\n')
        self.video.with_suffix('.zh.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\n中文\n')
        code, result = self.new('--language', 'en')
        self.assertEqual(code, 0)
        evidence = result['manifest']
        code, result = self.call('--evidence', evidence, '--language', 'zh')
        self.assertEqual(code, 0)
        artifact = next(a for a in result['artifacts'] if a['type'] == 'transcript')
        self.assertEqual(json.loads(Path(artifact['path']).read_text())['language'], 'zh')
        data = json.loads(Path(evidence).read_text())
        data['artifacts'][0]['path'] = '../outside.json'
        Path(evidence).write_text(json.dumps(data))
        self.assertEqual(self.call('--evidence', evidence)[0], 64)

    def test_platform_combination_downloads_once_and_reuses(self):
        from scripts import platforms
        copied = self.root / 'download.mp4'
        def download(resolved, directory, **kwargs):
            directory.mkdir(parents=True, exist_ok=True)
            dest = directory / copied.name
            shutil.copy2(self.video, dest)
            return dest
        resolved = {'source': {'platform': 'bilibili', 'id': 'BVdemo', 'url': 'https://www.bilibili.com/video/BVdemo', 'part': 1},
                    'metadata': {'duration': 2, 'title': 'demo'}, 'subtitles': [], 'formats': [], 'diagnostics': []}
        with patch.object(platforms, 'resolve', return_value=resolved), patch.object(platforms, 'download', side_effect=download) as fetch:
            code, result = self.call('https://www.bilibili.com/video/BVdemo', '--out', str(self.root / 'out'), '--get', 'video,audio,frames', '--at', '0.2')
            self.assertEqual(code, 0, result)
            self.assertEqual(fetch.call_count, 1)

            code, result = self.call('--evidence', result['manifest'], '--get', 'video')
            self.assertEqual(code, 0)
            self.assertEqual(fetch.call_count, 1)

    def test_insufficient_quality_reuses_ceiling_and_upgrades_with_new_credentials(self):
        from scripts import platforms
        larger = self.root / 'larger.mp4'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', self.video,
                        '-vf', 'scale=320:240', '-c:v', 'mpeg4', '-c:a', 'copy', larger], check=True)
        resolved = {'source': {'platform': 'bilibili', 'id': 'BVdemo', 'url': 'https://www.bilibili.com/video/BVdemo', 'part': 1},
                    'metadata': {'duration': 2}, 'subtitles': [], 'diagnostics': [],
                    'formats': [{'url': 'https://example.test/video', 'width': 160, 'height': 120,
                                 'has_video': True, 'has_audio': False}]}
        def download(resolved, directory, **kwargs):
            directory.mkdir(parents=True, exist_ok=True)
            dest = directory / f'download-{fetch.call_count}.mp4'
            shutil.copy2(larger if kwargs.get('cookies') else self.video, dest)
            return dest
        def resolve_source(*args, **kwargs):
            if kwargs.get('cookies'):
                return {**resolved, 'formats': [{**resolved['formats'][0], 'width': 320, 'height': 240}]}
            return resolved
        with patch.object(platforms, 'resolve', side_effect=resolve_source) as resolve, patch.object(platforms, 'download', side_effect=download) as fetch:
            code, result = self.call(resolved['source']['url'], '--out', str(self.root / 'out'),
                                     '--get', 'frames', '--at', '0.2', '--width', '1280')
            self.assertEqual(code, 0, result)
            evidence = result['manifest']
            self.assertEqual(fetch.call_count, 1)
            self.assertTrue(any(d['code'] == 'quality_insufficient' and '160×120' in d['message'] for d in result['diagnostics']))
            code, result = self.call('--evidence', evidence, '--get', 'frames', '--at', '0.4', '--width', '1280')
            self.assertEqual(code, 0, result)
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(resolve.call_count, 1)
            # Old evidence can learn the ceiling through one resolve without another download.
            data = json.loads(Path(evidence).read_text())
            for a in data['artifacts']:
                a.pop('available_max_width', None)
            Path(evidence).write_text(json.dumps(data))
            self.call('--evidence', evidence, '--get', 'frames', '--at', '0.6', '--width', '1280')
            self.assertEqual(resolve.call_count, 2)
            self.assertEqual(fetch.call_count, 1)
            # Explicit higher quality checks availability, even if no larger format exists.
            self.call('--evidence', evidence, '--get', 'frames', '--at', '0.2', '--width', '1280', '--quality', 'source')
            self.assertEqual(resolve.call_count, 3)
            self.assertEqual(fetch.call_count, 2)
            cookie = self.root / 'explicit-cookies.txt'
            cookie.write_text('# Netscape HTTP Cookie File\n')
            code, result = self.call('--evidence', evidence, '--get', 'frames', '--at', '0.2',
                                     '--width', '1280', '--cookies', str(cookie))
            self.assertEqual(code, 0, result)
            self.assertEqual(fetch.call_count, 3)
            upgraded_frame = next(a['path'] for a in result['artifacts'] if a['type'] == 'frames')
            self.assertEqual(media.probe(upgraded_frame)['video']['width'], 320)
            self.call('--evidence', evidence, '--get', 'frames', '--at', '0.8', '--width', '1280', '--cookies', str(cookie))
            self.assertEqual(fetch.call_count, 3)
            # A frame dependency is still not a complete video delivery.
            code, result = self.call('--evidence', evidence, '--get', 'video')
            self.assertEqual(code, 0, result)
            self.assertEqual(fetch.call_count, 4)
            delivered = next(a['path'] for a in result['artifacts'] if a['type'] == 'video')
            self.assertTrue(media.probe(delivered)['audio'])

    def test_source_quality_does_not_promote_same_size_lower_bitrate_video(self):
        from scripts import platforms
        source = {'platform': 'bilibili', 'id': 'BVdemo', 'url': 'https://www.bilibili.com/video/BVdemo', 'part': 1}
        low = {'url': 'https://example.test/low', 'width': 160, 'height': 120,
               'has_video': True, 'has_audio': True, 'bitrate': 100}
        high = {**low, 'url': 'https://example.test/high', 'bitrate': 1000}
        base = {'source': source, 'metadata': {'duration': 2}, 'subtitles': [], 'diagnostics': []}
        selected_bitrates = []
        def download(resolved, directory, **kwargs):
            selected_bitrates.append(platforms.select_formats(resolved['formats'],
                want_video=kwargs['want_video'], quality=kwargs['quality'], width=kwargs['width'])[0]['bitrate'])
            directory.mkdir(parents=True, exist_ok=True)
            dest = directory / f'video-{len(selected_bitrates)}.mp4'
            shutil.copy2(self.video, dest)
            return dest
        with patch.object(platforms, 'resolve', side_effect=[{**base, 'formats': [low]},
                    {**base, 'formats': [low, high]}]) as resolve, patch.object(platforms, 'download', side_effect=download) as fetch:
            code, result = self.call(source['url'], '--out', str(self.root / 'out'), '--get', 'video')
            self.assertEqual(code, 0, result)
            evidence = result['manifest']
            old_id = next(a['id'] for a in json.loads(Path(evidence).read_text())['artifacts'] if a['type'] == 'video')
            code, result = self.call('--evidence', evidence, '--get', 'video', '--quality', 'source')
            self.assertEqual(code, 0, result)
            self.assertEqual(selected_bitrates, [100, 1000])
            data = json.loads(Path(evidence).read_text())
            self.assertEqual(next(a['quality'] for a in data['artifacts'] if a['id'] == old_id), 'auto')
            code, result = self.call('--evidence', evidence, '--get', 'frames', '--at', '0.2', '--width', '0', '--quality', 'source')
            self.assertEqual(code, 0, result)
            frame = next(a['path'] for a in result['artifacts'] if a['type'] == 'frames')
            data = json.loads(Path(evidence).read_text())
            for a in data['artifacts']:
                if a['type'] == 'video':
                    (Path(evidence).parent / a['path']).unlink()
            # Source-sized frames remain usable after their source media is removed.
            code, result = self.call('--evidence', evidence, '--get', 'frames', '--at', '0.2', '--width', '0')
            self.assertEqual(code, 0, result)
            self.assertEqual(next(a['path'] for a in result['artifacts'] if a['type'] == 'frames'), frame)
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(resolve.call_count, 2)

    def test_bilibili_advertised_quality_is_not_available_quality(self):
        from scripts.platforms import bilibili
        view = {'bvid': 'BVdemo', 'pages': [{'page': 1, 'cid': 1, 'duration': 2,
                'dimension': {'width': 1920, 'height': 1080}}]}
        play = {'quality': 64, 'support_formats': [{'quality': 80, 'new_description': '1080P'},
                {'quality': 64, 'new_description': '720P'}, {'quality': 32, 'new_description': '480P'}],
                'dash': {'video': [{'id': 32, 'width': 852, 'height': 480, 'baseUrl': 'https://example.test/signed?secret=redacted'}]}}
        with patch.object(bilibili, '_api', side_effect=[view, play]):
            resolved = bilibili.resolve('https://www.bilibili.com/video/BVdemo', need=['frames'])
        quality = resolved['metadata']['quality_info']
        self.assertEqual(quality['available_quality_ids'], [32])
        self.assertEqual(quality['available_sizes'], [(852, 480)])
        self.assertEqual(resolved['metadata']['declared_dimensions']['width'], 1920)
        self.assertNotIn('secret', json.dumps(quality))
        self.assertEqual(resolved['diagnostics'][0]['code'], 'quality_unavailable')


if __name__ == '__main__':
    unittest.main()
