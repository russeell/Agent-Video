"""Evidence paths and schema validation, including the CLI trust boundary."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from scripts import manifest, watch


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.directory = self.root / 'evidence'
        self.directory.mkdir()
        self.file = self.directory / 'metadata.json'
        self.file.write_text('{"title": "Saved video"}', encoding='utf-8')
        self.outside = self.root / 'outside.json'
        self.outside.write_text('Private file', encoding='utf-8')
        self.path = self.directory / 'manifest.json'
        self.data = {'schema_version': 1,
                     'source': {'platform': 'youtube', 'url': 'https://www.youtube.com/watch?v=abcdefghijk'},
                     'artifacts': [{'id': 'info-1', 'type': 'info', 'path': 'metadata.json'}]}

    def call(self):
        self.path.write_text(json.dumps(self.data), encoding='utf-8')
        before = self.path.read_bytes()
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            code = watch.main(['--evidence', str(self.path), '--get', 'info'])
        result = json.loads(output.getvalue())
        if code == 64:
            self.assertEqual(self.path.read_bytes(), before)
            self.assertEqual(result['diagnostics'][0]['stage'], 'arguments')
            self.assertEqual(result['artifacts'], [])
        self.assertEqual(self.outside.read_text(encoding='utf-8'), 'Private file')
        return code, result

    def test_relative_artifact_add_load_and_cli_reuse(self):
        self.data['artifacts'] = []
        artifact = manifest.add(self.data, self.directory, 'info', self.file)
        self.assertEqual(artifact['path'], 'metadata.json')
        self.assertEqual(manifest.artifact_path(self.directory, artifact), self.file)
        code, result = self.call()
        self.assertEqual(code, 0, result)
        self.assertEqual(result['artifacts'], [{'type': 'info', 'path': str(self.file)}])
        self.assertEqual(manifest.load(self.path)[1]['artifacts'], [artifact])

    def test_traversal_and_absolute_paths_are_rejected_even_with_external_flag(self):
        for key in ('path', 'readable_path'):
            for value in ('../outside.json', str(self.outside), 'sub/../metadata.json'):
                with self.subTest(key=key, path=value):
                    self.data['artifacts'] = [{'id': 'info-1', 'type': 'info', 'path': 'metadata.json',
                                               'external': True, key: value}]
                    code, result = self.call()
                    self.assertEqual(code, 64, result)
        self.data['artifacts'] = [{'id': 'text-1', 'type': 'transcript', 'path': 'missing.json',
                                   'readable_path': '../outside.json'}]
        code, result = self.call()
        self.assertEqual(code, 64, result)

    def test_add_rejects_outside_missing_and_unsafe_companion_files(self):
        for path in (self.outside, self.directory / 'missing.json'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                manifest.add(self.data, self.directory, 'info', path, external=True)
        for companion in ('../outside.json', str(self.outside), 'missing.md'):
            with self.subTest(companion=companion), self.assertRaises(ValueError):
                manifest.add(self.data, self.directory, 'transcript', self.file, readable_path=companion)
        self.assertEqual(len(self.data['artifacts']), 1)

    def test_symlink_outside_evidence_is_rejected(self):
        link = self.directory / 'linked.json'
        link.symlink_to(self.outside)
        with self.assertRaises(ValueError):
            manifest.add(self.data, self.directory, 'info', link)
        self.data['artifacts'][0]['path'] = link.name
        code, result = self.call()
        self.assertEqual(code, 64, result)

    def test_unsupported_or_missing_schema_is_rejected_before_processing(self):
        for version in (2, None, '1', True, 1.0):
            with self.subTest(version=version):
                self.data['schema_version'] = version
                if version is None:
                    del self.data['schema_version']
                code, result = self.call()
                self.assertEqual(code, 64, result)
                self.assertIn('Unsupported evidence schema version', result['diagnostics'][0]['message'])
