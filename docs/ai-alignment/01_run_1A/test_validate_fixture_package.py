import contextlib
import hashlib
import importlib.util
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

D = Path(__file__).resolve().parent


class PackageValidationTests(unittest.TestCase):
    def load_validator(self):
        spec = importlib.util.spec_from_file_location('package_validator', D / 'validate_fixture_package.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_import_never_writes_or_runs_validation(self):
        with patch.object(Path, 'write_text', side_effect=AssertionError('Unexpected write')):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.load_validator()
        self.assertEqual(output.getvalue(), '')

    def test_missing_external_original_fails_explicitly(self):
        with self.assertRaisesRegex(FileNotFoundError, 'External original required'):
            self.load_validator().validate(D / 'not-provided')

    def test_manifest_has_only_existing_non_cache_files(self):
        manifest = json.loads((D.parent / 'MANIFEST_SHA256.json').read_text(encoding='utf-8'))
        for name, entry in manifest.items():
            with self.subTest(name=name):
                self.assertNotIn('__pycache__', name)
                self.assertFalse(name.endswith('.pyc'))
                data = (D.parent / name).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), entry['sha256'])
                self.assertEqual(len(data), entry['bytes'])


if __name__ == '__main__':
    unittest.main()
