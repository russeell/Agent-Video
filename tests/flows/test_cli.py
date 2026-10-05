"""Exercise the installed console script from outside the source directory."""
import json
from importlib.metadata import version
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import unittest


class ConsoleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='agent video cli ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.command = Path(sysconfig.get_path('scripts')) / ('agent-video.exe' if os.name == 'nt' else 'agent-video')
        self.assertTrue(self.command.is_file(), 'Install the project with python -m pip install -e . before running tests.')

    def call(self, *args):
        environment = os.environ.copy()
        environment.pop('PYTHONPATH', None)
        environment['AGENT_VIDEO_ASR_MODEL'] = ''
        return subprocess.run([str(self.command), *map(str, args)], cwd=self.root,
                              env=environment, capture_output=True, text=True, check=False)

    def test_help_and_argument_exit_code(self):
        help_result = self.call('--help')
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn('--evidence', help_result.stdout)
        # The README delegates these formats to --help; flag names alone are insufficient.
        help_text = ' '.join(help_result.stdout.split())
        for usage in ('MM:SS or HH:MM:SS', '0 keeps source size', 'Bilibili part number',
                      'Netscape Cookie file', '2 partial success'):
            with self.subTest(usage=usage):
                self.assertIn(usage, help_text)
        invalid = self.call('--get', 'invalid')
        self.assertEqual(invalid.returncode, 64, invalid.stderr)
        result = json.loads(invalid.stdout)
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['diagnostics'][0]['stage'], 'arguments')
        direct = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[2] / 'scripts/watch.py'), '--help'],
                                cwd=self.root, capture_output=True, text=True, check=False)
        self.assertEqual(direct.returncode, 0, direct.stderr)
        self.assertIn('--evidence', direct.stdout)

    def test_version_and_source_checkout_fallback(self):
        expected = 'agent-video ' + version('agent-video')
        installed = self.call('--version')
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.assertEqual(installed.stdout.strip(), expected)
        # -S excludes installed distribution metadata, exercising the checkout.
        environment = os.environ.copy()
        environment.pop('PYTHONPATH', None)
        direct = subprocess.run([sys.executable, '-S',
                                 str(Path(__file__).resolve().parents[2] / 'scripts/watch.py'), '--version'],
                                cwd=self.root, env=environment, capture_output=True, text=True, check=False)
        self.assertEqual(direct.returncode, 0, direct.stderr)
        self.assertEqual(direct.stdout.strip(), expected)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg is required')
    def test_timestamp_flags_keep_all_times_and_enforce_budget(self):
        video = self.root / 'timestamps.mp4'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                        'color=size=64x48:rate=5:duration=1', '-c:v', 'mpeg4', str(video)], check=True)
        for index, flags in enumerate([
            ['--at', '.2,.4,.6'],
            ['--at', '.2', '--at', '.4,.6'],
        ]):
            with self.subTest(flags=flags):
                run = self.call(video, '--get', 'frames', *flags, '--width', '0', '--out', self.root / str(index))
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                result = json.loads(run.stdout)
                frames = [a for a in result['artifacts'] if a['type'] == 'frames']
                self.assertEqual(len(frames), 3)
                self.assertTrue(all(Path(a['path']).is_file() for a in frames))
                saved = json.loads(Path(result['manifest']).read_text(encoding='utf-8'))
                actual = [a for a in saved['artifacts'] if a['type'] == 'frames']
                self.assertEqual([a['requested_time'] for a in actual], [.2, .4, .6])
                for a in actual:
                    self.assertAlmostEqual(a['actual_time'], a['requested_time'], places=3)
        for flags in [
            ['--at', '.2,.4', '--at', '.6', '--max-frames', '2'],
            ['--at', 'invalid', '--at', '.6'],
        ]:
            with self.subTest(invalid=flags):
                run = self.call(video, '--get', 'frames', *flags)
                self.assertEqual(run.returncode, 64, run.stdout + run.stderr)
                self.assertIsNone(json.loads(run.stdout)['manifest'])

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg is required')
    def test_local_subtitles_and_manifest_reuse(self):
        video = self.root / 'local video.mp4'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                        'color=size=64x48:rate=5:duration=1', '-c:v', 'mpeg4', str(video)], check=True)
        original = video.read_bytes()
        subtitle = video.with_suffix('.srt')
        subtitle.write_text('1\n00:00:00,000 --> 00:00:01,000\nLocal subtitle text\n', encoding='utf-8')
        first = self.call(video, '--get', 'transcript', '--out', self.root / 'saved evidence')
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        result = json.loads(first.stdout)
        manifest = Path(result['manifest'])
        self.assertTrue(manifest.is_absolute() and manifest.is_file())
        transcript = next(a['path'] for a in result['artifacts'] if a['type'] == 'transcript')
        self.assertEqual(json.loads(Path(transcript).read_text(encoding='utf-8'))['segments'][0]['text'], 'Local subtitle text')
        subtitle.unlink()
        repeated = self.call('--evidence', manifest, '--get', 'transcript')
        self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
        reused = json.loads(repeated.stdout)
        self.assertEqual(reused['manifest'], str(manifest))
        self.assertEqual(next(a['path'] for a in reused['artifacts'] if a['type'] == 'transcript'), transcript)
        self.assertEqual(video.read_bytes(), original)
