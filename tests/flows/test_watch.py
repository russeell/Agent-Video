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
        metadata = json.loads(Path(next(a['path'] for a in result['artifacts'] if a['type'] == 'info')).read_text())
        for field in ('view_count', 'like_count', 'comment_count'):
            self.assertIn(field, metadata)
            self.assertIsNone(metadata[field])
        self.assertTrue({'views', 'likes', 'comments'}.isdisjoint(metadata))
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
        for kind in ('video', 'audio', 'transcript'):
            for bounds in (['--start', '0.2', '--end', '99'], ['--start', '2']):
                with self.subTest(kind=kind, bounds=bounds):
                    with patch.object(watch.Watch, 'acquire', side_effect=AssertionError('Known bad ranges must not acquire media')):
                        code, bad = self.new('--get', kind, *bounds)
                    self.assertEqual(code, 2, bad)
                    self.assertTrue(any(d['code'] == 'range_out_of_bounds' for d in bad['diagnostics']))
                    self.assertEqual([a['type'] for a in bad['artifacts']], ['info'])
                    data = json.loads(Path(bad['manifest']).read_text())
                    self.assertEqual([a['type'] for a in data['artifacts']], ['info'])

    def test_legacy_transcript_reports_actual_text_span_without_reacquisition(self):
        self.video.with_suffix('.srt').write_text('1\n00:00:00,200 --> 00:00:00,700\nBrief speech\n')
        code, first = self.new()
        self.assertEqual(code, 0, first)
        evidence = Path(first['manifest'])
        data = json.loads(evidence.read_text())
        artifact = next(a for a in data['artifacts'] if a['type'] == 'transcript')
        artifact.pop('text_span', None)
        transcript = evidence.parent / artifact['path']
        body = json.loads(transcript.read_text())
        body.pop('text_span', None)
        transcript.write_text(json.dumps(body))
        evidence.write_text(json.dumps(data))
        original = transcript.read_bytes()
        expected = {'start': .2, 'end': .7}
        with patch.object(watch, 'choose_local', side_effect=AssertionError('Cached subtitles must be reused')), \
             patch.object(watch.Watch, 'acquire', side_effect=AssertionError('No media needed')), \
             patch.object(media, 'transcribe', side_effect=AssertionError('No ASR needed')):
            code, reused = self.call('--evidence', str(evidence))
            self.assertEqual(code, 0, reused)
            returned = next(a for a in reused['artifacts'] if a['type'] == 'transcript')
            self.assertEqual(returned['text_span'], expected)
            self.assertEqual(Path(returned['path']), transcript)
            self.assertEqual(transcript.read_bytes(), original)
            code, subset = self.call('--evidence', str(evidence), '--start', '.3', '--end', '.5')
        self.assertEqual(code, 0, subset)
        returned = next(a for a in subset['artifacts'] if a['type'] == 'transcript')
        self.assertEqual(returned['text_span'], expected)
        saved = json.loads(evidence.read_text())
        full = next(a for a in saved['artifacts'] if a['id'] == artifact['id'])
        self.assertEqual(full['source_range'], artifact['source_range'])
        self.assertEqual(full['text_span'], expected)

    def test_supporter_only_media_preserves_info_and_one_access_diagnostic(self):
        from scripts import platforms
        from scripts.platforms import bilibili
        view = {'bvid': 'BVexample', 'title': 'Supporter-only work',
                'is_upower_exclusive': True, 'is_upower_play': False,
                'pages': [{'page': 1, 'cid': 7, 'duration': 16}]}
        with patch.object(bilibili, '_api', return_value=view), \
             patch.object(bilibili, '_playinfo') as player, \
             patch.object(platforms, 'download_file') as fetch:
            code, result = self.call('https://www.bilibili.com/video/BVexample',
                                     '--get', 'video,audio', '--out', str(self.root / 'restricted'))
        self.assertEqual(code, 2)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual([a['type'] for a in result['artifacts']], ['info'])
        self.assertEqual([d['code'] for d in result['diagnostics']], ['auth_required'])
        self.assertTrue(json.loads(Path(result['artifacts'][0]['path']).read_text())['supporter_only'])
        player.assert_not_called()
        fetch.assert_not_called()

    def test_invalid_subtitle_response_preserves_frames_and_allows_retry(self):
        from scripts import platforms
        source = {'platform': 'youtube', 'id': 'abcdefghijk',
                  'url': 'https://www.youtube.com/watch?v=abcdefghijk'}
        resolved = {'source': source, 'metadata': {'duration': 2, 'original_language': 'en'},
                    'subtitles': [{'url': 'https://example.test/captions', 'ext': 'json3',
                                   'language': 'en', 'origin': 'platform_manual'}],
                    'formats': [{'url': 'https://example.test/video', 'has_video': True,
                                 'has_audio': True, 'width': 160, 'height': 120}], 'diagnostics': []}
        valid = json.dumps({'events': [{'tStartMs': 200, 'dDurationMs': 800,
                                       'segs': [{'utf8': 'Actual subtitle text'}]}]})
        def download(resolved, directory, **kwargs):
            directory.mkdir(parents=True, exist_ok=True)
            dest = directory / 'source.mp4'
            shutil.copy2(self.video, dest)
            return dest
        with patch.dict('os.environ', {'AGENT_VIDEO_ASR_MODEL': ''}), \
                patch.object(platforms, 'resolve', return_value=resolved), \
                patch.object(platforms, 'fetch_subtitle', side_effect=['', valid]) as subtitles, \
                patch.object(platforms, 'download', side_effect=download) as fetch:
            code, first = self.call(source['url'], '--out', str(self.root / 'out'),
                                    '--get', 'transcript,frames', '--at', '0.2')
            self.assertEqual(code, 2, first)
            self.assertEqual([a['type'] for a in first['artifacts']], ['info', 'frames'])
            self.assertTrue(any(d['code'] == 'invalid_subtitles' for d in first['diagnostics']))
            frame = Path(next(a['path'] for a in first['artifacts'] if a['type'] == 'frames'))
            original = frame.read_bytes()
            code, recovered = self.call('--evidence', first['manifest'], '--get', 'transcript')
            self.assertEqual(code, 0, recovered)
            text = next(a['path'] for a in recovered['artifacts'] if a['type'] == 'transcript')
            self.assertEqual(json.loads(Path(text).read_text())['segments'][0]['start'], .2)
            self.assertEqual(frame.read_bytes(), original)
            self.assertEqual(subtitles.call_count, 2)
            self.assertEqual(fetch.call_count, 1)

    def test_selected_audio_track_does_not_replace_default_in_followups(self):
        multi = self.root / 'two-tracks.mp4'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', self.video,
                        '-f', 'lavfi', '-i', 'sine=frequency=880:duration=2',
                        '-map', '0:v', '-map', '0:a', '-map', '1:a', '-c:v', 'copy',
                        '-c:a', 'aac', '-disposition:a:0', 'default', '-disposition:a:1', '0', multi], check=True)
        code, selected = self.call(str(multi), '--out', str(self.root / 'out'),
                                   '--get', 'video,audio', '--audio-track', '2')
        self.assertEqual(code, 0, selected)
        evidence = selected['manifest']
        old = {a['type']: a['path'] for a in selected['artifacts']}
        code, default = self.call('--evidence', evidence, '--get', 'video,audio')
        self.assertEqual(code, 0, default)
        current = {a['type']: a['path'] for a in default['artifacts']}
        self.assertNotEqual(current['audio'], old['audio'])
        self.assertNotEqual(current['video'], old['video'])
        self.assertEqual(len(media.probe(current['video'])['audio']), 2)
        def tone_frequency(path):
            from array import array
            samples = array('h', subprocess.check_output([
                'ffmpeg', '-v', 'error', '-i', path, '-ss', '0.1', '-t', '1', '-ac', '1',
                '-ar', '16000', '-f', 's16le', '-']))
            crossings = sum(a <= 0 < b for a, b in zip(samples, samples[1:]))
            return crossings * 16000 / len(samples)
        self.assertAlmostEqual(tone_frequency(current['audio']), 440, delta=5)
        self.assertAlmostEqual(tone_frequency(old['audio']), 880, delta=5)
        for track, expected in [(None, current), ('2', old)]:
            args = ['--evidence', evidence, '--get', 'video,audio']
            if track:
                args += ['--audio-track', track]
            code, reused = self.call(*args)
            self.assertEqual(code, 0, reused)
            self.assertEqual({a['type']: a['path'] for a in reused['artifacts']}, expected)
        def transcribe(path, info, start, end, language, track, model):
            return {'segments': [{'start': 0, 'end': 1, 'text': f'track {track}'}],
                    'language': language or 'en'}
        with patch.dict('os.environ', {'AGENT_VIDEO_ASR_MODEL': str(self.root)}), \
                patch.object(media, 'asr_ready', return_value=True), \
                patch.object(media, 'transcribe', side_effect=transcribe) as asr:
            code, selected_text = self.call('--evidence', evidence, '--get', 'transcript', '--audio-track', '2')
            self.assertEqual(code, 0, selected_text)
            code, default_text = self.call('--evidence', evidence, '--get', 'transcript')
            self.assertEqual(code, 0, default_text)
            text_path = next(a['path'] for a in default_text['artifacts'] if a['type'] == 'transcript')
            self.assertEqual(json.loads(Path(text_path).read_text())['segments'][0]['text'], 'track 1')
            self.assertEqual(asr.call_count, 2)
            self.call('--evidence', evidence, '--get', 'transcript')
            self.assertEqual(asr.call_count, 2)
            # A known single-track export maps stream 0 to source default 1;
            # unknown legacy selection still requires the original media.
            from scripts import platforms
            for legacy in (False, True):
                with self.subTest(legacy=legacy):
                    directory = self.root / ('remote-legacy' if legacy else 'remote-derived')
                    shutil.copytree(Path(evidence).parent, directory)
                    remote_manifest = directory / 'manifest.json'
                    data = json.loads(remote_manifest.read_text())
                    old_asr = next(a for a in data['artifacts'] if a['type'] == 'transcript' and a.get('audio_track') == 2)
                    data['source'] = {'platform': 'youtube', 'id': 'abcdefghijk',
                                      'url': 'https://www.youtube.com/watch?v=abcdefghijk'}
                    data['artifacts'] = [a for a in data['artifacts'] if a['type'] == 'info' or
                                         a['type'] == 'audio' and a.get('audio_track_default') is True]
                    if legacy:
                        data['artifacts'].append(old_asr)
                        for a in data['artifacts']:
                            a.pop('audio_track_default', None)
                            a.pop('requested_language', None)
                    remote_manifest.write_text(json.dumps(data))
                    resolved = {'source': data['source'], 'metadata': {'duration': 2}, 'subtitles': [], 'formats': []}
                    def download(resolved, dest, **kwargs):
                        dest.mkdir(parents=True, exist_ok=True)
                        path = dest / 'full-source.mp4'
                        shutil.copy2(multi, path)
                        return path
                    with patch.object(platforms, 'resolve', return_value=resolved), \
                            patch.object(platforms, 'download', side_effect=download) as fetch:
                        code, text = self.call('--evidence', str(remote_manifest), '--get', 'transcript')
                    self.assertEqual(code, 0, text)
                    self.assertEqual(fetch.call_count, 1 if legacy else 0)
                    self.assertEqual(asr.call_args.args[5], 1 if legacy else 0)
                    saved_text = next(a for a in json.loads(remote_manifest.read_text())['artifacts']
                                      if a['type'] == 'transcript' and a.get('audio_track_default') is True)
                    self.assertEqual(saved_text['audio_track'], 1)

    def test_explicit_transcript_language_does_not_resolve_default_ambiguity(self):
        self.video.with_suffix('.srt').unlink()
        for language, text in [('en', 'English'), ('zh', '中文')]:
            self.video.with_suffix(f'.{language}.srt').write_text(
                f'1\n00:00:00,000 --> 00:00:01,000\n{text}\n')
        with patch.object(media, 'transcribe', side_effect=AssertionError('Subtitles must not run ASR')), \
                patch.object(watch.Watch, 'acquire', side_effect=AssertionError('Subtitles must not acquire media')):
            code, first = self.new('--language', 'en')
            self.assertEqual(code, 0, first)
            for legacy in (False, True):
                with self.subTest(legacy=legacy):
                    if legacy:
                        path = Path(first['manifest'])
                        data = json.loads(path.read_text())
                        for artifact in data['artifacts']:
                            artifact.pop('requested_language', None)
                        path.write_text(json.dumps(data))
                    code, unspecified = self.call('--evidence', first['manifest'])
                    self.assertEqual(code, 2, unspecified)
                    self.assertTrue(any(d['code'] == 'subtitle_language_ambiguous' for d in unspecified['diagnostics']))
                    self.assertFalse(any(a['type'] == 'transcript' for a in unspecified['artifacts']))
                    code, reused = self.call('--evidence', first['manifest'], '--language', 'en')
                    self.assertEqual(code, 0, reused)
                    self.assertEqual(reused['artifacts'], first['artifacts'])

    def test_requested_language_alias_reuses_actual_variant_without_leaking_to_other_requests(self):
        from scripts import platforms
        source = {'platform': 'tiktok', 'id': '123', 'url': 'https://www.tiktok.com/@author/video/123'}
        tracks = [{'url': 'https://example.test/en-US', 'ext': 'json3', 'language': 'en-US', 'origin': 'platform_auto'},
                  {'url': 'https://example.test/fr', 'ext': 'json3', 'language': 'fr', 'origin': 'platform_manual'}]
        resolved = {'source': source, 'metadata': {'duration': 2}, 'subtitles': tracks,
                    'formats': [], 'diagnostics': []}
        text = json.dumps({'events': [{'tStartMs': 0, 'dDurationMs': 1000, 'segs': [{'utf8': 'Actual English'}]}]})
        with patch.object(platforms, 'resolve', return_value=resolved) as resolve, \
             patch.object(platforms, 'fetch_subtitle', return_value=text) as fetch_subtitle, \
             patch.object(platforms, 'download', side_effect=AssertionError('A subtitle request must not download media')) as download, \
             patch.object(media, 'transcribe', side_effect=AssertionError('Available subtitles must not run ASR')) as asr:
            code, first = self.call(source['url'], '--out', str(self.root / 'out'), '--language', 'en')
            self.assertEqual(code, 0, first)
            evidence = first['manifest']
            original = next(a['path'] for a in first['artifacts'] if a['type'] == 'transcript')
            self.assertEqual(json.loads(Path(original).read_text())['language'], 'en-US')
            for bounds in ([], ['--start', '.2', '--end', '.8']):
                with self.subTest(bounds=bounds):
                    code, reused = self.call('--evidence', evidence, '--language', 'en', *bounds)
                    self.assertEqual(code, 0, reused)
            self.assertEqual((resolve.call_count, fetch_subtitle.call_count), (1, 1))
            code, regional = self.call('--evidence', evidence, '--language', 'en-GB')
            self.assertEqual(code, 0, regional)
            self.assertEqual((resolve.call_count, fetch_subtitle.call_count), (2, 2))
            code, unspecified = self.call('--evidence', evidence)
            self.assertEqual(code, 2, unspecified)
            self.assertEqual(resolve.call_count, 3)
            self.assertEqual(fetch_subtitle.call_count, 2)
            self.assertTrue(any(d['code'] == 'subtitle_ambiguous' for d in unspecified['diagnostics']))
            self.assertFalse(any(a['type'] == 'transcript' for a in unspecified['artifacts']))
            download.assert_not_called()
            asr.assert_not_called()

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
            self.assertEqual(fetch.call_args.kwargs['quality'], 'source')

            code, result = self.call('--evidence', result['manifest'], '--get', 'video')
            self.assertEqual(code, 0)
            self.assertEqual(fetch.call_count, 1)

    def test_frames_then_video_fetches_only_missing_audio_and_preserves_cached_track(self):
        from scripts import platforms
        silent = self.root / 'silent.mp4'
        audio = self.root / 'audio.m4a'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', self.video,
                        '-map', '0:v:0', '-c', 'copy', silent], check=True)
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', self.video,
                        '-map', '0:a:0', '-c', 'copy', audio], check=True)
        source = {'platform': 'bilibili', 'id': 'BVdemo', 'part': 1,
                  'url': 'https://www.bilibili.com/video/BVdemo'}
        resolved = {'source': source, 'metadata': {'duration': 2}, 'subtitles': [], 'diagnostics': [],
                    'formats': [{'url': 'https://example.test/video', 'ext': 'mp4',
                                 'has_video': True, 'has_audio': False, 'width': 160, 'height': 120},
                                {'url': 'https://example.test/audio', 'ext': 'm4a',
                                 'has_video': False, 'has_audio': True}]}
        def fetch_track(url, path, **kwargs):
            shutil.copy2(audio if url.endswith('/audio') else silent, path)
            return path
        with patch.object(platforms, 'resolve', return_value=resolved), \
                patch.object(platforms, 'download_file', side_effect=fetch_track) as fetch:
            code, first = self.call(source['url'], '--out', str(self.root / 'out'),
                                    '--get', 'frames', '--at', '0.2', '--width', '0')
            self.assertEqual(code, 0, first)
            self.assertEqual([c.args[0] for c in fetch.call_args_list], ['https://example.test/video'])
            evidence = first['manifest']
            data = json.loads(Path(evidence).read_text())
            cached = Path(evidence).parent / next(a['path'] for a in data['artifacts'] if a['type'] == 'video')
            original = cached.read_bytes()
            self.assertFalse(media.probe(cached)['audio'])
            run = media.run
            def fail_merge(args, **kwargs):
                if '1:a:0' in args:
                    raise media.Failure('command_failed', 'Merge failed.')
                return run(args, **kwargs)
            for failure in ('audio', 'merge'):
                with self.subTest(failure=failure):
                    if failure == 'audio':
                        context = patch.object(platforms, 'download_file', side_effect=media.Failure('network_failed', 'Audio failed.'))
                    else:
                        context = patch.object(media, 'run', side_effect=fail_merge)
                    with context:
                        code, failed = self.call('--evidence', evidence, '--get', 'video')
                    self.assertEqual(code, 2, failed)
                    self.assertEqual(cached.read_bytes(), original)
                    self.assertEqual(list(cached.parent.iterdir()), [cached])
            fetch.reset_mock()
            code, saved = self.call('--evidence', evidence, '--get', 'video')
            self.assertEqual(code, 0, saved)
            self.assertEqual([c.args[0] for c in fetch.call_args_list], ['https://example.test/audio'])
            complete = next(a['path'] for a in saved['artifacts'] if a['type'] == 'video')
            self.assertTrue(media.probe(complete)['audio'])
            self.assertEqual(cached.read_bytes(), original)
            fetch.reset_mock()
            code, repeated = self.call('--evidence', evidence, '--get', 'video')
            self.assertEqual(code, 0, repeated)
            self.assertEqual(next(a['path'] for a in repeated['artifacts'] if a['type'] == 'video'), complete)
            fetch.assert_not_called()

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

    def test_default_video_upgrades_historical_auto_and_reuses_best(self):
        from scripts import platforms
        larger = self.root / 'larger.mp4'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', self.video,
                        '-vf', 'scale=320:240', '-c:v', 'mpeg4', '-c:a', 'copy', larger], check=True)
        source = {'platform': 'bilibili', 'id': 'BVdemo', 'url': 'https://www.bilibili.com/video/BVdemo', 'part': 1}
        low = {'url': 'low', 'width': 160, 'height': 120, 'has_video': True, 'has_audio': True}
        high = {**low, 'url': 'high', 'width': 320, 'height': 240}
        base = {'source': source, 'metadata': {'duration': 2}, 'subtitles': [], 'diagnostics': []}
        def download(resolved, directory, **kwargs):
            chosen = platforms.select_formats(resolved['formats'], want_video=kwargs['want_video'],
                                              quality=kwargs['quality'], width=kwargs['width'])[0]
            directory.mkdir(parents=True, exist_ok=True)
            dest = directory / (chosen['url'] + '.mp4')
            shutil.copy2(larger if chosen['url'] == 'high' else self.video, dest)
            return dest
        with patch.object(platforms, 'resolve', side_effect=[{**base, 'formats': [low]},
                    {**base, 'formats': [low, high]}]) as resolve, patch.object(platforms, 'download', side_effect=download) as fetch:
            code, first = self.call(source['url'], '--out', str(self.root / 'out'), '--get', 'video', '--quality', '1080p')
            self.assertEqual(code, 0, first)
            evidence = first['manifest']
            data = json.loads(Path(evidence).read_text())
            for artifact in data['artifacts']:
                if artifact['type'] == 'video':
                    artifact['quality'] = 'auto'  # Evidence from the former default.
            Path(evidence).write_text(json.dumps(data))
            code, upgraded = self.call('--evidence', evidence, '--get', 'video,audio')
            self.assertEqual(code, 0, upgraded)
            delivered = next(a['path'] for a in upgraded['artifacts'] if a['type'] == 'video')
            self.assertEqual(media.probe(delivered)['video']['width'], 320)
            self.assertTrue(media.probe(delivered)['audio'])
            self.assertEqual(fetch.call_args.kwargs['quality'], 'source')
            code, repeated = self.call('--evidence', evidence, '--get', 'video')
            self.assertEqual(code, 0, repeated)
            self.assertEqual(next(a['path'] for a in repeated['artifacts'] if a['type'] == 'video'), delivered)
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(resolve.call_count, 2)

    def test_missing_expected_audio_is_not_delivered_or_reused(self):
        from scripts import platforms
        silent = self.root / 'silent.mp4'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', self.video,
                        '-an', '-c:v', 'copy', silent], check=True)
        base = {'source': {'platform': 'bilibili', 'id': 'BVdemo', 'url': 'https://www.bilibili.com/video/BVdemo', 'part': 1},
                'metadata': {'duration': 2}, 'subtitles': [], 'diagnostics': [],
                'formats': [{'url': 'media', 'width': 160, 'height': 120, 'has_video': True, 'has_audio': True}]}
        def download(resolved, directory, **kwargs):
            directory.mkdir(parents=True, exist_ok=True)
            dest = directory / f'download-{fetch.call_count}.mp4'
            shutil.copy2(silent if fetch.call_count == 1 else self.video, dest)
            return dest
        with patch.object(platforms, 'resolve', return_value=base), patch.object(platforms, 'download', side_effect=download) as fetch:
            code, failed = self.call(base['source']['url'], '--out', str(self.root / 'out'), '--get', 'video')
            self.assertEqual(code, 2, failed)
            self.assertFalse(any(a['type'] == 'video' for a in failed['artifacts']))
            self.assertTrue(any(d['code'] == 'invalid_media' for d in failed['diagnostics']))
            code, good = self.call('--evidence', failed['manifest'], '--get', 'video')
            self.assertEqual(code, 0, good)
            delivered = next(a['path'] for a in good['artifacts'] if a['type'] == 'video')
            shutil.copy2(silent, delivered)  # A cached file has lost its promised audio.
            code, repaired = self.call('--evidence', good['manifest'], '--get', 'video')
            self.assertEqual(code, 0, repaired)
            repaired_path = next(a['path'] for a in repaired['artifacts'] if a['type'] == 'video')
            self.assertTrue(media.probe(repaired_path)['audio'])
            self.assertEqual(fetch.call_count, 3)
            code, audio = self.call('--evidence', good['manifest'], '--get', 'audio')
            self.assertEqual(code, 0, audio)
            audio_path = next(a['path'] for a in audio['artifacts'] if a['type'] == 'audio')
            shutil.copy2(silent, audio_path)
            code, repaired_audio = self.call('--evidence', good['manifest'], '--get', 'audio')
            self.assertEqual(code, 0, repaired_audio)
            restored = next(a['path'] for a in repaired_audio['artifacts'] if a['type'] == 'audio')
            self.assertTrue(media.probe(restored)['audio'])
            self.assertNotEqual(restored, audio_path)
            self.assertEqual(fetch.call_count, 3)

    def test_saved_silent_video_does_not_refetch_for_audio(self):
        from scripts import platforms
        silent = self.root / 'silent.mp4'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', self.video,
                        '-an', '-c:v', 'copy', silent], check=True)
        source = {'platform': 'reddit', 'id': 'abc', 'url': 'https://www.reddit.com/comments/abc/'}
        resolved = {'source': source, 'metadata': {'duration': 2, 'audio_expected': False},
                    'subtitles': [], 'diagnostics': [],
                    'formats': [{'url': 'media', 'width': 160, 'height': 120,
                                 'has_video': True, 'has_audio': False}]}
        def download(resolved, directory, **kwargs):
            directory.mkdir(parents=True, exist_ok=True)
            dest = directory / 'silent.mp4'
            shutil.copy2(silent, dest)
            return dest
        with patch.object(platforms, 'resolve', return_value=resolved), \
                patch.object(platforms, 'download', side_effect=download):
            code, first = self.call(source['url'], '--get', 'video', '--out', str(self.root / 'out'))
        self.assertEqual(code, 0, first)
        with patch.object(platforms, 'resolve', side_effect=AssertionError('Unexpected resolve')) as resolve, \
                patch.object(platforms, 'download', side_effect=AssertionError('Unexpected download')) as fetch:
            code, followup = self.call('--evidence', first['manifest'], '--get', 'audio,frames', '--at', '0.2', '--width', '0')
        self.assertEqual(code, 2, followup)
        self.assertEqual([d['code'] for d in followup['diagnostics']], ['no_audio'])
        self.assertTrue(any(a['type'] == 'frames' for a in followup['artifacts']))
        resolve.assert_not_called()
        fetch.assert_not_called()
        # A frames-only source or a changed access context can omit available
        # audio. Neither is evidence that the source is silent.
        data = json.loads(Path(first['manifest']).read_text())
        for frames_only in (True, False):
            with self.subTest(frames_only=frames_only):
                for a in data['artifacts']:
                    if a.get('internal'):
                        a['frames_only'] = frames_only
                Path(first['manifest']).write_text(json.dumps(data))
                cookie = self.root / 'cookies.txt'
                cookie.write_text('# Netscape HTTP Cookie File\n')
                extra = [] if frames_only else ['--cookies', str(cookie)]
                with patch.object(platforms, 'resolve', side_effect=media.Failure('network_failed', 'New source required.')) as resolve:
                    code, followup = self.call('--evidence', first['manifest'], '--get', 'audio', *extra)
                resolve.assert_called_once()
                self.assertEqual([d['code'] for d in followup['diagnostics']], ['network_failed'])
    def test_bilibili_old_source_quality_upgrades_video_frames_and_metadata_once(self):
        from scripts import platforms
        samples = {}
        for name, size in [('low', '852:480'), ('high', '1920:1080')]:
            samples[name] = self.root / (name + '.mp4')
            subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', self.video,
                            '-vf', 'scale=' + size, '-c:v', 'mpeg4', '-c:a', 'copy', samples[name]], check=True)
        source = {'platform': 'bilibili', 'id': 'BVdemo', 'url': 'https://www.bilibili.com/video/BVdemo', 'part': 1}
        low = {'url': 'low', 'width': 852, 'height': 480, 'has_video': True, 'has_audio': True}
        high = {**low, 'url': 'high', 'width': 1920, 'height': 1080}
        def resolved(candidate):
            return {'source': source, 'metadata': {'duration': 2,
                    'quality_info': {'available_sizes': [[candidate['width'], candidate['height']]]}},
                    'subtitles': [], 'diagnostics': [], 'formats': [candidate]}
        def download(data, directory, **kwargs):
            directory.mkdir(parents=True, exist_ok=True)
            name = data['formats'][0]['url']
            dest = directory / (name + '.mp4')
            shutil.copy2(samples[name], dest)
            return dest
        with patch.object(platforms, 'resolve', side_effect=[resolved(low), resolved(high)]) as resolve, \
                patch.object(platforms, 'download', side_effect=download) as fetch:
            request = ('--get', 'video,frames', '--at', '0.2', '--width', '0')
            code, first = self.call(source['url'], '--out', str(self.root / 'out'), *request)
            self.assertEqual(code, 0, first)
            evidence = first['manifest']
            old_frame = next(a['path'] for a in first['artifacts'] if a['type'] == 'frames')
            old_video = next(a['path'] for a in first['artifacts'] if a['type'] == 'video')
            data = json.loads(Path(evidence).read_text())
            info_id = next(a['id'] for a in data['artifacts'] if a['type'] == 'info')
            for artifact in data['artifacts']:
                artifact.pop('quality_revision', None)
            Path(evidence).write_text(json.dumps(data))
            code, upgraded = self.call('--evidence', evidence, *request)
            self.assertEqual(code, 0, upgraded)
            new_video = next(a['path'] for a in upgraded['artifacts'] if a['type'] == 'video')
            new_frame = next(a['path'] for a in upgraded['artifacts'] if a['type'] == 'frames')
            self.assertEqual(media.probe(new_video)['video']['width'], 1920)
            self.assertEqual(media.probe(new_frame)['video']['width'], 1920)
            self.assertTrue(media.probe(new_video)['audio'])
            self.assertTrue(Path(old_video).exists())
            self.assertTrue(Path(old_frame).exists())
            self.assertNotEqual(new_frame, old_frame)
            info = next(a for a in upgraded['artifacts'] if a['type'] == 'info')
            data = json.loads(Path(evidence).read_text())
            self.assertEqual(next(a['id'] for a in data['artifacts'] if a['type'] == 'info'), info_id)
            self.assertEqual(json.loads(Path(info['path']).read_text())['quality_info']['available_sizes'], [[1920, 1080]])
            code, repeated = self.call('--evidence', evidence, *request)
            self.assertEqual(code, 0, repeated)
            self.assertEqual(next(a['path'] for a in repeated['artifacts'] if a['type'] == 'video'), new_video)
            self.assertEqual(next(a['path'] for a in repeated['artifacts'] if a['type'] == 'frames'), new_frame)
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(resolve.call_count, 2)

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
            code, result = self.call(source['url'], '--out', str(self.root / 'out'), '--get', 'video', '--quality', '1080p')
            self.assertEqual(code, 0, result)
            evidence = result['manifest']
            old_id = next(a['id'] for a in json.loads(Path(evidence).read_text())['artifacts'] if a['type'] == 'video')
            code, result = self.call('--evidence', evidence, '--get', 'video', '--quality', 'source')
            self.assertEqual(code, 0, result)
            self.assertEqual(selected_bitrates, [100, 1000])
            data = json.loads(Path(evidence).read_text())
            self.assertEqual(next(a['quality'] for a in data['artifacts'] if a['id'] == old_id), '1080p')
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
                'dash': {'video': [{'id': 32, 'width': 852, 'height': 480, 'frameRate': '60000/1001',
                                    'baseUrl': 'https://example.test/signed?secret=redacted'}]}}
        with patch.object(bilibili, '_api', side_effect=[view, play]):
            resolved = bilibili.resolve('https://www.bilibili.com/video/BVdemo', need=['frames'])
        quality = resolved['metadata']['quality_info']
        self.assertEqual(quality['available_quality_ids'], [32])
        self.assertEqual(quality['available_sizes'], [(852, 480)])
        self.assertAlmostEqual(resolved['formats'][0]['fps'], 60000 / 1001)
        self.assertEqual(resolved['metadata']['declared_dimensions']['width'], 1920)
        self.assertNotIn('secret', json.dumps(quality))
        self.assertEqual(resolved['diagnostics'][0]['code'], 'quality_unavailable')


if __name__ == '__main__':
    unittest.main()
