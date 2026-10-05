"""Saved local evidence remains usable after a temporary input is moved."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import media, watch


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg is required')
class LocalReuseTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.video = self.root / 'temporary screen.mp4'
        self.create_video(2)
        self.video.with_suffix('.srt').write_text(
            '1\n00:00:00,000 --> 00:00:02,000\nSaved speech\n', encoding='utf-8')

    def create_video(self, duration):
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                        f'testsrc2=size=160x120:rate=5:duration={duration}', '-f', 'lavfi', '-i',
                        f'sine=frequency=440:duration={duration}', '-c:v', 'mpeg4', '-c:a', 'aac',
                        '-shortest', str(self.video)], check=True)

    def call(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = watch.main(list(args))
        return code, json.loads(out.getvalue())

    def new(self, *args):
        return self.call(str(self.video), '--out', str(self.root / 'evidence'), *args)

    def test_missing_original_reuses_saved_media_and_derives_new_evidence(self):
        code, first = self.new('--get', 'transcript,frames,video', '--at', '.2', '--width', '0')
        self.assertEqual(code, 0, first)
        paths = {a['type']: a['path'] for a in first['artifacts']}
        saved_video = Path(paths['video'])
        original = saved_video.read_bytes()
        moved = self.video.rename(self.root / 'moved.mp4')
        self.video.with_suffix('.srt').unlink()
        probe = media.probe

        def saved_probe(path):
            self.assertNotEqual(Path(path), self.video, 'Do not probe the unavailable original')
            return probe(path)

        with (patch('scripts.platforms.resolve', side_effect=AssertionError('No source lookup')) as resolve,
              patch('scripts.platforms.download', side_effect=AssertionError('No download')) as download,
              patch.object(media, 'transcribe', side_effect=AssertionError('No repeated ASR')) as asr,
              patch.object(media, 'probe', side_effect=saved_probe)):
            code, cached = self.call('--evidence', first['manifest'], '--get', 'transcript,frames,video',
                                     '--at', '.2', '--width', '0')
            self.assertEqual(code, 0, cached)
            self.assertEqual({a['type']: a['path'] for a in cached['artifacts']}, paths)
            code, derived = self.call('--evidence', first['manifest'], '--get', 'frames,audio',
                                      '--at', '1.2', '--width', '0')
            self.assertEqual(code, 0, derived)
            audio = next(a['path'] for a in derived['artifacts'] if a['type'] == 'audio')
            self.assertTrue(probe(audio)['audio'])
            resolve.assert_not_called()
            download.assert_not_called()
            asr.assert_not_called()
        data = json.loads(Path(first['manifest']).read_text())
        frame = next(a for a in data['artifacts'] if a['type'] == 'frames' and a['requested_time'] == 1.2)
        self.assertAlmostEqual(frame['actual_time'], 1.2, places=3)
        self.assertEqual(saved_video.read_bytes(), original)
        self.assertEqual(moved.read_bytes(), original)

    def test_missing_media_is_partial_without_discarding_saved_text_and_frame(self):
        code, first = self.new('--get', 'transcript,frames', '--at', '.2', '--width', '0')
        self.assertEqual(code, 0, first)
        self.video.rename(self.root / 'moved.mp4')
        with (patch('scripts.platforms.resolve', side_effect=AssertionError('No local network lookup')),
              patch.object(media, 'transcribe', side_effect=AssertionError('No unnecessary ASR'))):
            code, partial = self.call('--evidence', first['manifest'], '--get', 'transcript,frames,audio',
                                      '--at', '.2', '--width', '0')
            self.assertEqual(code, 2, partial)
            self.assertEqual({a['type'] for a in partial['artifacts']}, {'info', 'transcript', 'frames'})
            self.assertEqual([d['code'] for d in partial['diagnostics']], ['source_unavailable'])
            code, missing = self.call('--evidence', first['manifest'], '--get', 'frames', '--at', '1.2')
            self.assertEqual(code, 2, missing)
            self.assertEqual([a['type'] for a in missing['artifacts']], ['info'])
            self.assertEqual([d['code'] for d in missing['diagnostics']], ['source_unavailable'])

    def test_changed_original_still_invalidates_previous_evidence(self):
        code, first = self.new('--get', 'video')
        self.assertEqual(code, 0, first)
        old_path = Path(next(a['path'] for a in first['artifacts'] if a['type'] == 'video'))
        original = old_path.read_bytes()
        self.create_video(3)
        code, changed = self.call('--evidence', first['manifest'], '--get', 'frames', '--at', '2.4', '--width', '0')
        self.assertEqual(code, 0, changed)
        data = json.loads(Path(first['manifest']).read_text())
        self.assertFalse(any(a['type'] == 'video' for a in data['artifacts']))
        self.assertEqual(data['source']['fingerprint'], media.fingerprint(self.video))
        self.assertEqual(old_path.read_bytes(), original)
        metadata = json.loads(Path(next(a['path'] for a in changed['artifacts'] if a['type'] == 'info')).read_text())
        self.assertAlmostEqual(metadata['duration'], 3, places=2)

    def test_saved_silent_video_can_supply_clips_but_reports_no_audio(self):
        silent = self.root / 'silent.mp4'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', str(self.video),
                        '-an', '-c:v', 'copy', str(silent)], check=True)
        self.video = silent
        code, first = self.new('--get', 'video')
        self.assertEqual(code, 0, first)
        self.video.rename(self.root / 'moved-silent.mp4')
        code, clip = self.call('--evidence', first['manifest'], '--get', 'video', '--start', '.2', '--end', '1.4')
        self.assertEqual(code, 0, clip)
        path = next(a['path'] for a in clip['artifacts'] if a['type'] == 'video')
        info = media.probe(path)
        self.assertTrue(info['video'])
        self.assertFalse(info['audio'])
        self.assertAlmostEqual(info['duration'], 1.2, delta=.21)
        artifact_count = len(json.loads(Path(first['manifest']).read_text())['artifacts'])
        with patch.object(media, 'export_video', side_effect=AssertionError('No repeated video export')):
            code, cached_clip = self.call('--evidence', first['manifest'], '--get', 'video',
                                          '--start', '.2', '--end', '1.4')
        self.assertEqual(code, 0, cached_clip)
        self.assertEqual(next(a['path'] for a in cached_clip['artifacts'] if a['type'] == 'video'), path)
        self.assertEqual(len(json.loads(Path(first['manifest']).read_text())['artifacts']), artifact_count)
        for kind, selected in (('audio', []), ('audio', ['--audio-track', '1']),
                               ('video', ['--audio-track', '1'])):
            with self.subTest(kind=kind, selected=selected):
                code, audio = self.call('--evidence', first['manifest'], '--get', kind, *selected)
                self.assertEqual(code, 2, audio)
                self.assertEqual([a['type'] for a in audio['artifacts']], ['info'])
                self.assertEqual([d['code'] for d in audio['diagnostics']], ['no_audio'])
