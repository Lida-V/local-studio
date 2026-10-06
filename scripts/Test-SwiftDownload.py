"""Offline failure-preservation checks; no weights, network or runtime changes."""
import contextlib
import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('swift_download', Path(__file__).with_name('Install-SwiftFiles.py'))
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class PreservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / 'runtime').mkdir()
        self.data = b'pinned synthetic weights'
        self.entry = {'folder': 'models/Swift-1.5-Qwen3.8-Flash-Next/IQ3_XXS',
                      'name': 'synthetic.gguf', 'size': len(self.data),
                      'sha256': hashlib.sha256(self.data).hexdigest(),
                      'url': 'https://example.invalid/pinned/synthetic.gguf'}
        self.dest = self.root / self.entry['folder'] / self.entry['name']
        self.partial = self.root / 'downloads/swift/synthetic.gguf.part'

    def run_install(self):
        with contextlib.redirect_stdout(io.StringIO()):
            installer.install(self.root, [self.entry])

    def test_verified_transfer_moves_only_own_file(self):
        preserved = self.root / 'models/stock/weights.gguf'
        preserved.parent.mkdir(parents=True)
        preserved.write_bytes(b'stock')
        with patch.object(installer, 'download', side_effect=lambda _, p: p.write_bytes(self.data)):
            self.run_install()
        self.assertEqual(self.dest.read_bytes(), self.data)
        self.assertEqual(preserved.read_bytes(), b'stock')
        self.assertFalse(self.partial.exists())

    def test_bad_hash_preserves_partial(self):
        with patch.object(installer, 'download', side_effect=lambda _, p: p.write_bytes(b'x' * len(self.data))):
            with self.assertRaisesRegex(RuntimeError, 'SHA256 mismatch'): self.run_install()
        self.assertFalse(self.dest.exists())
        self.assertEqual(self.partial.read_bytes(), b'x' * len(self.data))

    def test_existing_wrong_artifact_never_overwritten(self):
        self.dest.parent.mkdir(parents=True)
        self.dest.write_bytes(b'x' * len(self.data))
        with patch.object(installer, 'download') as transfer:
            with self.assertRaisesRegex(RuntimeError, 'Existing file differs'): self.run_install()
            transfer.assert_not_called()
        self.assertEqual(self.dest.read_bytes(), b'x' * len(self.data))

    def test_existing_valid_artifact_no_transfer(self):
        self.dest.parent.mkdir(parents=True)
        self.dest.write_bytes(self.data)
        with patch.object(installer, 'download') as transfer:
            self.run_install()
            transfer.assert_not_called()

    def test_oversized_partial_preserved(self):
        self.partial.parent.mkdir(parents=True)
        self.partial.write_bytes(self.data + b'excess')
        with self.assertRaisesRegex(RuntimeError, 'Oversized partial'): self.run_install()
        self.assertEqual(self.partial.read_bytes(), self.data + b'excess')

    def test_folder_escape_rejected_before_transfer(self):
        self.entry['folder'] = 'models/stock'
        with patch.object(installer, 'download') as transfer:
            with self.assertRaises(ValueError): self.run_install()
            transfer.assert_not_called()

    def test_filename_escape_rejected(self):
        self.entry['name'] = '../escape.gguf'
        with self.assertRaises(ValueError): self.run_install()


if __name__ == '__main__': unittest.main()
