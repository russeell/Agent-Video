"""An audio export keeps source track identity when its stream is renumbered."""
from array import array
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
class AudioReuseTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.video = self.root / 'source.mp4'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                        'testsrc2=size=160x120:rate=5:duration=3', '-f', 'lavfi', '-i',
                        'sine=frequency=440:duration=3', '-f', 'lavfi', '-i',
                        'sine=frequency=880:duration=3', '-map', '0:v', '-map', '1:a',
                        '-map', '2:a', '-c:v', 'mpeg4', '-c:a', 'aac',
                        '-disposition:a:0', 'default', '-disposition:a:1', '0',
                        str(self.video)], check=True)

    def call(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = watch.main(list(args))
        return code, json.loads(out.getvalue())

    def save_audio(self, *selection):
        code, first = self.call(str(self.video), '--out', str(self.root / 'evidence'),
                                '--get', 'audio', *selection)
        self.assertEqual(code, 0, first)
        self.manifest = Path(first['manifest'])
        self.saved = Path(next(a['path'] for a in first['artifacts'] if a['type'] == 'audio'))
        self.assertEqual([s['index'] for s in media.probe(self.saved)['audio']], [0])
        self.source_end = media.probe(self.video)['duration']
        self.video.rename(self.root / 'moved.mp4')
        return first

    def artifacts(self, kind):
        return [a for a in json.loads(self.manifest.read_text())['artifacts'] if a['type'] == kind]

    def tone(self, path):
        samples = array('h', subprocess.check_output([
            'ffmpeg', '-v', 'error', '-i', str(path), '-ss', '0.1', '-t', '0.5',
            '-ac', '1', '-ar', '16000', '-f', 's16le', '-']))
        return sum(a <= 0 < b for a, b in zip(samples, samples[1:])) * 16000 / len(samples)

    def derive(self, source_track, default, frequency, *selection):
        def transcribe(path, info, start, end, language, track, model):
            self.assertEqual(Path(path), self.saved)
            self.assertEqual(track, 0, 'FFmpeg must use the export index, not its source index')
            self.assertEqual([s['index'] for s in info['audio']], [0])
            self.assertEqual(end, self.source_end)
            pcm = self.root / 'asr.wav'
            media.export_audio(path, pcm, info, start, end, track, asr=True)
            self.assertAlmostEqual(self.tone(pcm), frequency, delta=5)
            return {'segments': [{'start': start + .2, 'end': start + .8, 'text': 'test speech'}],
                    'language': 'en'}

        with (patch.dict('os.environ', {'AGENT_VIDEO_ASR_MODEL': str(self.root)}),
              patch.object(media, 'asr_ready', return_value=True),
              patch.object(media, 'transcribe', side_effect=transcribe) as asr,
              patch('scripts.platforms.resolve', side_effect=AssertionError('No lookup')),
              patch('scripts.platforms.download', side_effect=AssertionError('No download'))):
            code, transcript = self.call('--evidence', str(self.manifest), '--get', 'transcript',
                                         *selection)
            self.assertEqual(code, 0, transcript)
            self.assertEqual(asr.call_count, 1)
            # Original-track selection continues to find the derived transcript.
            code, cached = self.call('--evidence', str(self.manifest), '--get', 'transcript',
                                     *selection)
            self.assertEqual(code, 0, cached)
            self.assertEqual(asr.call_count, 1)
        text = self.artifacts('transcript')[-1]
        self.assertEqual(text['audio_track'], source_track)
        self.assertIs(text['audio_track_default'], default)
        self.assertEqual(text['source_range'], {'start': 0, 'end': self.source_end})

        code, clip = self.call('--evidence', str(self.manifest), '--get', 'audio',
                               '--start', '1', '--end', '2', *selection)
        self.assertEqual(code, 0, clip)
        artifact = self.artifacts('audio')[-1]
        self.assertEqual(artifact['audio_track'], source_track)
        self.assertIs(artifact['audio_track_default'], default)
        self.assertEqual(artifact['source_range'], {'start': 1, 'end': 2})
        path = Path(next(a['path'] for a in clip['artifacts'] if a['type'] == 'audio'))
        self.assertAlmostEqual(media.probe(path)['duration'], 1, delta=.02)
        self.assertAlmostEqual(self.tone(path), frequency, delta=5)
        audio_count = len(self.artifacts('audio'))
        repeat_selections = [selection]
        if default:
            repeat_selections.append(('--audio-track', str(source_track)))
        with patch.object(media, 'export_audio', side_effect=AssertionError('No repeated audio export')):
            for repeated in repeat_selections:
                code, cached_clip = self.call('--evidence', str(self.manifest), '--get', 'audio',
                                              '--start', '1', '--end', '2', *repeated)
                self.assertEqual(code, 0, cached_clip)
                self.assertEqual(Path(next(a['path'] for a in cached_clip['artifacts'] if a['type'] == 'audio')), path)
                self.assertEqual(len(self.artifacts('audio')), audio_count)
        code, selected_text = self.call('--evidence', str(self.manifest), '--get', 'transcript',
                                        '--start', '1', '--end', '2', *selection)
        self.assertEqual(code, 0, selected_text)
        self.assertEqual(self.artifacts('transcript')[-1]['source_range'], {'start': 1, 'end': 2})
        text_path = Path(next(a['path'] for a in selected_text['artifacts'] if a['type'] == 'transcript'))
        self.assertEqual(json.loads(text_path.read_text())['segments'], [])
        text_count = len(self.artifacts('transcript'))
        with patch.object(media, 'transcript_files', side_effect=AssertionError('No repeated transcript write')):
            for repeated in repeat_selections:
                code, cached_text = self.call('--evidence', str(self.manifest), '--get', 'transcript',
                                              '--start', '1', '--end', '2', *repeated)
                self.assertEqual(code, 0, cached_text)
                self.assertEqual(Path(next(a['path'] for a in cached_text['artifacts'] if a['type'] == 'transcript')), text_path)
                self.assertEqual(len(self.artifacts('transcript')), text_count)

    def test_default_audio_reuses_remapped_stream_and_preserves_source_time(self):
        self.save_audio()
        self.derive(1, True, 440)

    def test_explicit_source_track_reuses_remapped_nondefault_stream(self):
        self.save_audio('--audio-track', '2')
        self.derive(2, False, 880, '--audio-track', '2')

    def test_wrong_or_default_selection_does_not_use_nondefault_export(self):
        self.save_audio('--audio-track', '2')
        with (patch.dict('os.environ', {'AGENT_VIDEO_ASR_MODEL': str(self.root)}),
              patch.object(media, 'asr_ready', return_value=True),
              patch.object(media, 'transcribe', side_effect=AssertionError('Wrong track ASR'))):
            for selection in ([], ['--audio-track', '1'], ['--audio-track', '0']):
                with self.subTest(selection=selection):
                    code, result = self.call('--evidence', str(self.manifest), '--get', 'transcript,audio',
                                             '--start', '1', '--end', '2', *selection)
                    self.assertEqual(code, 2, result)
                    self.assertEqual([a['type'] for a in result['artifacts']], ['info'])
                    self.assertTrue(all(d['code'] == 'source_unavailable' for d in result['diagnostics']))

    def test_unknown_provenance_or_multiple_audio_streams_are_rejected(self):
        self.save_audio()
        original_manifest = self.manifest.read_text()
        for missing in ('audio_track', 'audio_track_default'):
            with self.subTest(missing=missing):
                data = json.loads(original_manifest)
                next(a for a in data['artifacts'] if a['type'] == 'audio').pop(missing)
                self.manifest.write_text(json.dumps(data))
                code, result = self.call('--evidence', str(self.manifest), '--get', 'audio',
                                         '--start', '1', '--end', '2', '--audio-track', '1')
                self.assertEqual(code, 2, result)
                self.assertEqual(result['diagnostics'][0]['code'], 'source_unavailable')
        self.manifest.write_text(original_manifest)
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', str(self.root / 'moved.mp4'),
                        '-map', '0:a', '-c:a', 'copy', str(self.saved)], check=True)
        code, result = self.call('--evidence', str(self.manifest), '--get', 'audio', '--start', '1', '--end', '2')
        self.assertEqual(code, 2, result)
        self.assertEqual(result['diagnostics'][0]['code'], 'source_unavailable')

    def test_partial_success_keeps_asr_when_saved_audio_cannot_supply_frames(self):
        self.save_audio()
        with (patch.dict('os.environ', {'AGENT_VIDEO_ASR_MODEL': str(self.root)}),
              patch.object(media, 'asr_ready', return_value=True),
              patch.object(media, 'transcribe', return_value={
                  'segments': [{'start': 1.2, 'end': 1.8, 'text': 'speech'}], 'language': 'en'})):
            code, result = self.call('--evidence', str(self.manifest), '--get', 'transcript,frames',
                                     '--start', '1', '--end', '2')
        self.assertEqual(code, 2, result)
        self.assertEqual({a['type'] for a in result['artifacts']}, {'info', 'transcript'})
        self.assertEqual(result['diagnostics'][0]['code'], 'source_unavailable')
        text = self.artifacts('transcript')[-1]
        self.assertEqual(text['source_range'], {'start': 1, 'end': 2})
        self.assertEqual(json.loads((self.manifest.parent / text['path']).read_text())['segments'][0]['start'], 1.2)
