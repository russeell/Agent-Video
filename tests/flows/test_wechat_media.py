"""Synthetic media integration; official responses are mocked, not a platform pass."""
import contextlib
import http.server
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from scripts import media, watch
from scripts.platforms import wechat


class WechatFlowTests(unittest.TestCase):
    def call(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            code = watch.main(list(map(str, args)))
        return code, json.loads(output.getvalue())

    def test_partial_info_is_saved_and_reused_without_claiming_a_transcript(self):
        response = {'errCode': 0, 'data': {'feedInfo': {'description': 'Work description'}, 'errMsg': {'type': 0}}}
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', {'AGENT_VIDEO_ASR_MODEL': ''}):
            with patch.object(wechat, 'read_json', return_value=response) as api:
                code, result = self.call('https://weixin.qq.com/sph/PublicWork', '--get', 'info,video', '--out', directory)
            self.assertEqual(code, 2, result)
            self.assertEqual(api.call_count, 1)
            self.assertEqual([a['type'] for a in result['artifacts']], ['info'])
            metadata = json.loads(Path(result['artifacts'][0]['path']).read_text())
            self.assertEqual(metadata['description'], 'Work description')
            self.assertTrue(any(d['code'] == 'media_unavailable' for d in result['diagnostics']))
            with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('Saved info must not refetch')) as network:
                code, reused = self.call('--evidence', result['manifest'], '--get', 'info')
            self.assertEqual(code, 0, reused)
            self.assertEqual(reused['artifacts'], result['artifacts'])
            network.assert_not_called()

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg is required')
    def test_preview_download_frames_audio_and_network_free_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / 'source.mp4'
            subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                            'testsrc2=size=160x120:rate=5:duration=2', '-f', 'lavfi', '-i',
                            'sine=frequency=440:duration=2', '-c:v', 'mpeg4', '-c:a', 'aac',
                            '-shortest', str(original)], check=True)
            payload = original.read_bytes()
            requests = []
            class Handler(http.server.BaseHTTPRequestHandler):
                def do_GET(self):
                    requests.append(self.path)
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                def log_message(self, *args):
                    pass
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f'http://127.0.0.1:{server.server_port}/video.mp4?signature=ephemeral'
                response = {'errCode': 0, 'data': {'feedInfo': {'description': 'Synthetic demo',
                    'mediaType': 4, 'durationMs': 2000, 'h264VideoInfo': {
                        'videoUrl': url, 'width': 160, 'height': 120}}, 'errMsg': {'type': 0}}}
                preview = wechat.PREVIEW + 'feed?token=public-token&eid=export%2Fwork'
                with patch.object(wechat, 'read_json', return_value=response) as api, patch.object(
                        media, 'transcribe', side_effect=AssertionError('Downloading must not transcribe')):
                    code, result = self.call(preview, '--get', 'video', '--out', root / 'evidence')
                self.assertEqual(code, 0, result)
                self.assertEqual(api.call_count, 1)
                self.assertEqual(len(requests), 1)
                video = next(a['path'] for a in result['artifacts'] if a['type'] == 'video')
                info = media.probe(video)
                self.assertEqual((info['video']['width'], info['video']['height']), (160, 120))
                self.assertTrue(info['audio'])
                self.assertAlmostEqual(info['duration'], 2, delta=.1)
                subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', video, '-f', 'null', '-'], check=True, capture_output=True)
                saved = Path(result['manifest'])
                self.assertNotIn('signature=ephemeral', saved.read_text())
                before = Path(video).stat().st_mtime_ns
                with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('Follow-ups must reuse media')) as network:
                    code, followup = self.call('--evidence', saved, '--get', 'frames,audio,video', '--at', '00:01', '--width', '0')
                    self.assertEqual(code, 0, followup)
                    code, repeated = self.call('--evidence', saved, '--get', 'frames,audio,video', '--at', '00:01', '--width', '0')
                    self.assertEqual(code, 0, repeated)
                network.assert_not_called()
                self.assertEqual(Path(video).stat().st_mtime_ns, before)
                self.assertEqual(len(requests), 1)
                frame = next(a for a in json.loads(saved.read_text())['artifacts'] if a['type'] == 'frames')
                self.assertEqual(frame['actual_time'], 1)
                self.assertTrue(media.probe(next(a['path'] for a in followup['artifacts'] if a['type'] == 'audio'))['audio'])
                self.assertEqual(original.read_bytes(), payload)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
