"""Safety checks for the frozen-pair mobile browser acceptance harness."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

HARNESS = Path(__file__).with_name('workbench_mobile_return_browser.py')
spec = importlib.util.spec_from_file_location('mobile_return_harness_unit', HARNESS)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FrozenPairTests(unittest.TestCase):
    def test_accepts_the_actual_frozen_member_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve()
            (directory / 'app.js').write_bytes(b'TEMP compiled UI')
            manifest = {'release': 'TEMP-r2', 'files': {'app.js': hashlib.sha256(b'TEMP compiled UI').hexdigest()}}
            (directory / 'native-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            result = module.frozen(directory, 'native-manifest.json')
            self.assertEqual(result['release'], 'TEMP-r2')
            self.assertEqual(result['manifest_sha256'], module.sha(directory / 'native-manifest.json'))

    def test_modified_member_cannot_be_called_the_frozen_candidate(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve()
            (directory / 'app.js').write_bytes(b'changed')
            (directory / 'native-manifest.json').write_text(json.dumps({'files': {'app.js': '0' * 64}}), encoding='utf-8')
            with self.assertRaisesRegex(AssertionError, 'Frozen bytes changed'):
                module.frozen(directory, 'native-manifest.json')

    def test_manifest_cannot_read_an_outside_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary).resolve()
            directory = parent / 'release'
            directory.mkdir()
            outside = parent / 'secret.txt'
            outside.write_bytes(b'TEMP outside')
            (directory / 'native-manifest.json').write_text(json.dumps({'files': {'../secret.txt': module.sha(outside)}}), encoding='utf-8')
            with self.assertRaisesRegex(AssertionError, 'Frozen bytes changed'):
                module.frozen(directory, 'native-manifest.json')

    def test_manifest_without_member_hashes_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve()
            (directory / 'native-manifest.json').write_text('{"release":"TEMP"}', encoding='utf-8')
            with self.assertRaisesRegex(AssertionError, 'Missing frozen member hashes'):
                module.frozen(directory, 'native-manifest.json')


if __name__ == '__main__':
    unittest.main()
