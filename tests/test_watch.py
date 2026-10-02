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


if __name__ == '__main__':
    unittest.main()
