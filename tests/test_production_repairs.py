import base64
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import production_repairs as repairs


class ProductionRepairsTests(unittest.TestCase):
    def setUp(self):
        self.snippet = '<link rel="canonical" href="https://example.com/">'
        self.desired = ('<html><head><title>Example</title>' + self.snippet + '</head></html>').encode()
        self.file = {'path': 'base.html', 'content_base64': base64.b64encode(self.desired).decode(),
                     'sha256': hashlib.sha256(self.desired).hexdigest(), 'recoverable_snippets': [self.snippet]}

    def test_recovers_only_missing_approved_metadata_and_is_idempotent(self):
        self.assertEqual(repairs.repair_bytes(self.desired.replace(self.snippet.encode(), b''), self.file), self.desired)
        self.assertIsNone(repairs.repair_bytes(self.desired, self.file))
        for data in [self.desired.replace(b'Example', b'New title'), self.desired + b'new content', b'']:
            with self.assertRaises(ValueError):
                repairs.repair_bytes(data, self.file)

    def test_corrupt_snapshot_and_unapproved_predecessor_rejected(self):
        with self.assertRaises(ValueError):
            repairs.repair_bytes(b'', {**self.file, 'sha256': '0' * 64})
        original = b'approved original template'
        file = {**self.file, 'approved_predecessors': [hashlib.sha256(original).hexdigest()]}
        self.assertEqual(repairs.repair_bytes(original, file), self.desired)

    def test_live_failure_restores_exact_original_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old = self.desired.replace(self.snippet.encode(), b'')
            path = root / 'base.html'; path.write_bytes(old)
            bundle = {'id': 'example', 'root': str(root), 'files': [self.file], 'services': ['example'], 'checks': []}
            with patch.object(repairs, 'reload_services') as reload, patch.object(repairs, 'verify', side_effect=ValueError('live failure')):
                with self.assertRaisesRegex(RuntimeError, 'rolled back'):
                    repairs.apply_bundle(bundle, root / 'backups', True)
                self.assertEqual(path.read_bytes(), old)
                self.assertEqual(reload.call_count, 2)
            self.assertTrue(list((root / 'backups').glob('*/base.html')))

    def test_successful_apply_is_verified_and_second_run_does_not_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old = self.desired.replace(self.snippet.encode(), b'')
            path = root / 'base.html'; path.write_bytes(old)
            bundle = {'id': 'example', 'root': str(root), 'files': [self.file], 'services': ['example'], 'checks': []}
            with patch.object(repairs, 'reload_services') as reload, patch.object(repairs, 'verify', return_value=[]):
                self.assertEqual(repairs.apply_bundle(bundle, root / 'backups', True)['status'], 'repaired')
                self.assertEqual(path.read_bytes(), self.desired)
                self.assertEqual(repairs.apply_bundle(bundle, root / 'backups', True)['status'], 'healthy')
                reload.assert_called_once_with(['example'])

    def test_all_files_are_validated_before_first_production_write(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old = self.desired.replace(self.snippet.encode(), b'')
            path = root / 'base.html'; path.write_bytes(old)
            (root / 'other.html').write_bytes(b'unrelated new code')
            bundle = {'id': 'example', 'root': str(root), 'files': [self.file, {**self.file, 'path': 'other.html'}]}
            with self.assertRaises(ValueError):
                repairs.apply_bundle(bundle, root / 'backups', True)
            self.assertEqual(path.read_bytes(), old)

    def test_dry_run_does_not_write_or_reload(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old = self.desired.replace(self.snippet.encode(), b'')
            path = root / 'base.html'; path.write_bytes(old)
            bundle = {'id': 'example', 'root': str(root), 'files': [self.file], 'services': [], 'checks': []}
            with patch.object(repairs, 'reload_services') as reload:
                self.assertEqual(repairs.apply_bundle(bundle, root / 'backups')['status'], 'would_repair')
                reload.assert_not_called()
            self.assertEqual(path.read_bytes(), old)

    def test_escape_outside_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'root'; root.mkdir()
            (root.parent / 'base.html').write_bytes(self.desired)
            bundle = {'root': str(root), 'files': [{**self.file, 'path': '../base.html'}]}
            with self.assertRaisesRegex(ValueError, 'escapes'):
                repairs.apply_bundle(bundle, root / 'backups')


if __name__ == '__main__':
    unittest.main()
