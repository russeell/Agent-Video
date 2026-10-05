"""Downloaded media must agree with the work duration, with rounding tolerance."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import platforms


class DownloadTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg and ffprobe required')
    def test_duration_mismatch_cleanup_and_unknown_duration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source.mp4'
            subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'lavfi',
                            '-i', 'color=size=64x48:rate=5:duration=4', '-f', 'lavfi',
                            '-i', 'sine=frequency=440:duration=4', '-c:v', 'mpeg4',
                            '-c:a', 'aac', '-shortest', str(source)], check=True)

            def fetch(url, path, **kwargs):
                path = Path(path)
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, path)
                return path

            for duration, code in [(200, 'download_incomplete'), (1, 'media_mismatch'),
                                   (3, None), (None, None)]:
                with self.subTest(duration=duration):
                    directory = root / str(duration)
                    resolved = {'metadata': {'duration': duration}, 'formats': [
                        {'url': 'https://cdn.example.test/work.mp4', 'ext': 'mp4',
                         'has_video': True, 'has_audio': True}]}
                    with patch.object(platforms, 'download_file', side_effect=fetch):
                        if code:
                            with self.assertRaises(platforms.Failure) as caught:
                                platforms.download(resolved, directory)
                            self.assertEqual(caught.exception.code, code)
                            self.assertFalse(list(directory.iterdir()))
                        else:
                            result = platforms.download(resolved, directory)
                            info = platforms.media.probe(result)
                            self.assertAlmostEqual(info['duration'], 4, places=1)
                            self.assertTrue(info['video'])
                            self.assertTrue(info['audio'])
                    self.assertTrue(source.is_file())


if __name__ == '__main__':
    unittest.main()
