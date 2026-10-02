"""Offline behavior checks; real FFmpeg outputs, ASR worker boundary mocked."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import media


class SubtitleTests(unittest.TestCase):
    def test_rolling_and_real_repetition(self):
        text = 'WEBVTT\n\n00:00.000 --> 00:02.000\n<v speaker>Hello &amp; welcome</v>\n\n00:01.000 --> 00:03.000\nHello &amp; welcome\nNext line\n\n00:05.000 --> 00:06.000\nHello &amp; welcome\n'
        segments = media.parse_subtitles(text, 'vtt')
        self.assertEqual([s['text'] for s in segments], ['Hello & welcome', 'Next line', 'Hello & welcome'])
        self.assertEqual(media.subtitle_range(segments, 4, 7)[0]['start'], 5)
        self.assertEqual(media.subtitle_range(segments, 3, 4), [])

    def test_json3_growing_line_and_language(self):
        data = {'events': [{'tStartMs': 0, 'dDurationMs': 2000, 'segs': [{'utf8': 'hello'}]}, {'tStartMs': 1000, 'dDurationMs': 2000, 'segs': [{'utf8': 'hello world'}]}, {'tStartMs': 5000, 'dDurationMs': 1000, 'segs': [{'utf8': 'hello'}]}]}
        segments = media.parse_subtitles(json.dumps(data), 'json3')
        self.assertEqual([s['text'] for s in segments], ['hello', 'world', 'hello'])
        with tempfile.TemporaryDirectory(dir='/tmp') as tmp:
            path, readable = media.transcript_files(tmp, segments, 'en', 'platform_auto', {'start': 0, 'end': 6})
            out = json.loads(path.read_text())
            self.assertEqual(out['language'], 'en')
            self.assertEqual(out['origin'], 'platform_auto')
            self.assertIn('[5.000–6.000] hello', readable.read_text())

    def test_clock_and_bilibili(self):
        self.assertEqual(media.clock('01:02:03.5'), 3723.5)
        for value in ('nan', '-1', '1:60', '1:2:3:4'):
            with self.assertRaises(ValueError):
                media.clock(value)
        self.assertEqual(media.parse_subtitles('{"body":[{"from":1,"to":2,"content":"你好"}]}', 'json')[0]['text'], '你好')

    def test_invalid_json_subtitle_responses_are_not_absent_subtitles(self):
        for ext in ('json', 'json3'):
            for text in ('', ' \n\t', '<html>Unavailable</html>', '{"events":'):
                with self.subTest(ext=ext, text=text), self.assertRaises(media.Failure) as caught:
                    media.parse_subtitles(text, ext)
                self.assertEqual(caught.exception.code, 'invalid_subtitles')
                self.assertTrue(caught.exception.next_action)
                if text.strip():
                    self.assertNotIn(text.strip(), str(caught.exception))
            with self.subTest(ext=ext, valid_empty=True):
                self.assertEqual(media.parse_subtitles('{"events":[]}', ext), [])


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg and ffprobe required')
class RealMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='agent-video-test-', dir='/tmp')
        cls.root = Path(cls.tmp.name)
        cls.source = cls.root / 'source.mp4'
        media.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10:duration=3', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=3', '-c:v', 'mpeg4', '-c:a', 'aac', '-y', cls.source])
        cls.info = media.probe(cls.source)
        cls.vfr = cls.root / 'vfr.mkv'
        # Irregular retained frame timestamps plus a nonzero original start.
        media.run(['ffmpeg', '-v', 'error', '-i', cls.source, '-vf', r'select=eq(n\,0)+eq(n\,2)+eq(n\,7)+eq(n\,13)+eq(n\,21)+eq(n\,29),setpts=PTS+5/TB', '-an', '-fps_mode', 'vfr', '-c:v', 'ffv1', '-y', cls.vfr])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_frames_actual_pts_no_upscale_and_partial(self):
        results = list(media.frames(self.source, self.root / 'frames', [0.15, 99, 1.05], 768, self.info))
        self.assertAlmostEqual(results[0]['actual_time'], .2)
        self.assertEqual((results[0]['width'], results[0]['height']), (160, 90))
        self.assertEqual(results[1]['error']['code'], 'frame_unavailable')
        self.assertAlmostEqual(results[2]['actual_time'], 1.1)
        self.assertTrue(results[0]['path'].exists())
        small = next(media.frames(self.source, self.root / 'frames', [.4], 80, self.info))
        self.assertEqual((small['width'], small['height']), (80, 45))

    def test_vfr_and_nonzero_start(self):
        info = media.probe(self.vfr)
        self.assertEqual(info['start_time'], 5)
        self.assertAlmostEqual(info['duration'], 3)
        results = list(media.frames(self.vfr, self.root / 'vfr-frames', [.21, 1.1, 2.2], 0, info))
        for result, expected in zip(results, [.7, 1.3, 2.9]):
            self.assertAlmostEqual(result['actual_time'], expected)
            self.assertGreaterEqual(result['actual_time'], result['requested_time'])

    def test_audio_copy_clip_and_asr_pcm(self):
        full = self.root / 'audio.mka'
        result = media.export_audio(self.source, full, self.info)
        self.assertFalse(result['transcoded'])
        self.assertEqual(media.probe(full)['audio'][0]['codec_name'], 'aac')
        clip = self.root / 'audio.flac'
        media.export_audio(self.source, clip, self.info, .7, 1.8)
        self.assertAlmostEqual(media.probe(clip)['duration'], 1.1, delta=.03)
        wav = self.root / 'speech.wav'
        media.export_audio(self.source, wav, self.info, .7, 1.8, asr=True)
        audio = media.probe(wav)['audio'][0]
        self.assertEqual((audio['codec_name'], audio['channels'], audio['sample_rate']), ('pcm_s16le', 1, '16000'))

    def test_video_full_selected_track_copy_and_clip(self):
        full = self.root / 'full.mp4'
        media.export_video(self.source, full, self.info)
        self.assertEqual(full.read_bytes(), self.source.read_bytes())
        selected = self.root / 'selected.mp4'
        result = media.export_video(self.source, selected, self.info, track=1)
        self.assertFalse(result['transcoded'])
        self.assertEqual(media.probe(selected)['video']['codec_name'], 'mpeg4')
        clip = self.root / 'clip.mp4'
        result = media.export_video(self.source, clip, self.info, .7, 1.8)
        self.assertTrue(result['transcoded'])
        actual = media.probe(clip)
        self.assertTrue(actual['video'] and actual['audio'])
        self.assertAlmostEqual(actual['duration'], 1.1, delta=.12)
        media.run(['ffmpeg', '-v', 'error', '-i', clip, '-f', 'null', '-'])

    def test_no_audio_and_silent_video_export(self):
        info = media.probe(self.vfr)
        with self.assertRaises(media.Failure) as caught:
            media.export_audio(self.vfr, self.root / 'absent.mka', info)
        self.assertEqual(caught.exception.code, 'no_audio')
        with self.assertRaises(media.Failure) as caught:
            media.transcribe(self.vfr, info, 0, 1, None, None, None)
        self.assertEqual(caught.exception.code, 'no_audio')
        clip = self.root / 'silent.mp4'
        media.export_video(self.vfr, clip, info, .2, 1.3)
        self.assertFalse(media.probe(clip)['audio'])

    def test_source_protection_and_fingerprint(self):
        before = self.source.read_bytes()
        for dest in (self.source, self.root / 'source-link.mp4'):
            if dest != self.source:
                dest.symlink_to(self.source)
            with self.assertRaises(media.Failure) as caught:
                media.export_video(self.source, dest, self.info)
            self.assertEqual(caught.exception.code, 'unsafe_path')
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(set(media.fingerprint(self.source)), {'size', 'mtime_ns'})

    def test_asr_worker_offset_once_and_no_speech(self):
        real_run = media.run
        def worker(args, timeout=300):
            if '--asr-worker' not in args:
                return real_run(args, timeout)
            pcm = media.probe(args[3])
            self.assertAlmostEqual(pcm['duration'], 1, delta=.01)
            media.atomic_json(args[4], {'language': 'zh', 'segments': [{'start': .1, 'end': .7, 'text': '测试'}]})
            return '', ''
        with patch.object(media, 'asr_ready', return_value=True), patch.object(media, 'run', side_effect=worker):
            result = media.transcribe(self.source, self.info, 1, 2, 'zh', None, 'mock-model')
        self.assertEqual(result['language'], 'zh')
        self.assertEqual(result['segments'][0]['start'], 1.1)
        self.assertEqual(result['segments'][0]['end'], 1.7)
        def silent(args, timeout=300):
            if '--asr-worker' in args:
                media.atomic_json(args[4], {'language': 'en', 'segments': []})
                return '', ''
            return real_run(args, timeout)
        with patch.object(media, 'asr_ready', return_value=True), patch.object(media, 'run', side_effect=silent):
            with self.assertRaises(media.Failure) as caught:
                media.transcribe(self.source, self.info, 1, 2, None, None, 'mock-model')
        self.assertEqual(caught.exception.code, 'no_speech')


if __name__ == '__main__':
    unittest.main()
