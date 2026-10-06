"""Offline MTP range/preservation tests using tiny temporary tensors only."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import ast
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SUPPORT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('local_mtp_wrapper_test', SUPPORT / 'scripts/Fetch-StrataMTP.py')
wrapper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wrapper)
REAL_MANIFEST = json.loads((SUPPORT / 'config/strata-download-manifest.json').read_text(encoding='utf-8-sig'))['mtp']
CONFIG_PATH = SUPPORT / 'config/support-config.json'
if not CONFIG_PATH.exists():
    CONFIG_PATH = SUPPORT / 'config/support-config.example.json'
CONFIG = json.loads(CONFIG_PATH.read_text(encoding='utf-8-sig'))
UPSTREAM = Path(CONFIG['target']['root']) / 'apps/Strata/source/tools/mtp_fetch.py'


class ManifestConsistency(unittest.TestCase):
    def test_actual_manifest_shape_ranges_totals_and_fixed_sources(self):
        tensors = REAL_MANIFEST['tensors']
        self.assertEqual(len(tensors), 31)
        self.assertEqual(len({row['name'] for row in tensors}), 31)
        self.assertEqual(len({row['shard'] for row in tensors}), 28)
        self.assertEqual(sum(row['size'] for row in tensors), REAL_MANIFEST['downloadBytes'])
        for row in tensors:
            self.assertEqual(row['dtype'], 'BF16')
            self.assertTrue(all(type(value) is int and value > 0 for value in row['shape']))
            self.assertEqual(2 * math.prod(row['shape']), row['size'])
            self.assertTrue(type(row['start']) is int and 0 <= row['start'] <= row['end'])
            self.assertEqual(row['end'] - row['start'] + 1, row['size'])
            self.assertRegex(row['shard'], r'^model-\d{5}-of-00131\.safetensors$')
        self.assertNotIn('/main/', REAL_MANIFEST['tensorUrlPrefix'])
        self.assertIn('/resolve/' + REAL_MANIFEST['revision'] + '/', REAL_MANIFEST['tensorUrlPrefix'])

    def test_preservation_proxy_never_changes_global_os(self):
        original_remove = os.remove
        proxy = wrapper.PreserveFiles()
        self.assertIs(proxy.path, os.path)
        with self.assertRaisesRegex(RuntimeError, 'retained'):
            proxy.remove('fixture')
        self.assertIs(os.remove, original_remove)

    def test_preparation_routes_only_pinned_mtp_fetch_to_reviewed_helper(self):
        code = (SUPPORT / 'scripts/Prepare-Strata.ps1').read_text(encoding='utf-8-sig')
        match = re.search(r"\$modelRunner = @'\n(.*?)\n'@", code, re.S)
        self.assertIsNotNone(match, 'Expected Python setup adapter is missing.')
        parsed = ast.parse(match.group(1))
        functions = [node for node in parsed.body if isinstance(node, ast.FunctionDef) and node.name == 'scoped_run']
        self.assertEqual(len(functions), 1)
        function_module = ast.Module(body=functions, type_ignores=[])
        with tempfile.TemporaryDirectory(prefix='strata-mtp-adapter-') as temp:
            root = Path(temp)
            source, data, helper = root / 'source', root / 'data', root / 'support/Fetch-StrataMTP.py'
            original = Mock()
            namespace = {'pathlib': __import__('pathlib'), 'source': source, 'expected_data': data,
                         'mtp_helper': helper, 'sys': SimpleNamespace(executable='fixture-python'), 'original_run': original}
            exec(compile(function_module, '<reviewed-setup-adapter>', 'exec'), namespace)
            run = namespace['scoped_run']
            environment = {'fixture': 'kept'}
            run(['fixture-python', str(source / 'tools/mtp_fetch.py'), 'fetch', '--out', str(data / 'mtp')], env=environment)
            original.assert_called_once_with(['fixture-python', '-B', '-X', 'utf8', str(helper)], env=environment)
            original.reset_mock()
            unchanged = ['fixture-python', str(source / 'tools/mtp_pack.py'), '--src', str(data / 'mtp')]
            run(unchanged, env=environment)
            original.assert_called_once_with(unchanged, env=environment)
            original.reset_mock()
            for tail in (['verify', '--out', str(data / 'mtp')], ['fetch', '--out', str(root / 'outside')],
                         ['fetch', '--out', str(data / 'mtp'), '--only', 'mtp.fc']):
                with self.assertRaises(SystemExit):
                    run(['fixture-python', str(source / 'tools/mtp_fetch.py'), *tail], env=environment)
            original.assert_not_called()


@unittest.skipUnless(UPSTREAM.is_file(), 'Pinned local Strata checkout required; no checkout is fetched by tests')
class MTPWrapper(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='strata-mtp-offline-')
        self.addCleanup(self.temp.cleanup)
        self.support = Path(self.temp.name) / 'support'
        self.root = Path(self.temp.name) / 'runtime-root'
        (self.support / 'config').mkdir(parents=True)
        self.out = self.root / 'models/Qwen3.8-Flash-Next/mtp'
        (self.out / 'tensors').mkdir(parents=True)
        (self.support / 'config/support-config.json').write_text(json.dumps({'target': {'root': str(self.root)}}), encoding='utf-8')
        spec = importlib.util.spec_from_file_location('mtp_fetch_pinned_offline', UPSTREAM)
        self.fetch = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.fetch)
        self.fetch.resolve_repo = Mock(side_effect=AssertionError('Floating repository resolution was attempted.'))
        self.fetch.inventory = Mock(side_effect=AssertionError('A full index/header fetch was attempted.'))
        self.payload = b'abcd'
        digest = hashlib.sha256(self.payload).hexdigest()
        self.manifest = deepcopy(REAL_MANIFEST)
        for index, row in enumerate(self.manifest['tensors']):
            row.update(dtype='BF16', shape=[2], start=128 + index * 8, end=131 + index * 8, size=4, sha256=digest)
            (self.out / 'tensors' / (row['name'] + '.bin')).write_bytes(self.payload)
        self.manifest['downloadBytes'] = 31 * 4
        self.fetch.SHA256 = {row['name']: digest for row in self.manifest['tensors']}
        self.first = self.manifest['tensors'][0]
        self.first_path = self.out / 'tensors' / (self.first['name'] + '.bin')
        self.requests = []
        self.read_sizes = []

    def response(self, request, timeout, status=206, encoded='', extra=b''):
        self.requests.append((request, timeout))
        start, end = [int(value) for value in re.fullmatch(r'bytes=(\d+)-(\d+)', request.get_header('Range')).groups()]
        row = next(row for row in self.manifest['tensors'] if row['start'] <= start <= row['end'])
        data = self.payload[start - row['start']:end - row['start'] + 1] + extra
        fixture = SimpleNamespace(status=status, headers={'Content-Range': f'bytes {start}-{end}/4000000000',
                                                         'Content-Encoding': encoded})
        fixture.read = lambda count: self.read_sizes.append(count) or data[:count]
        return SimpleNamespace(__enter__=lambda _: fixture, __exit__=lambda *_: None)

    def run_wrapper(self, opener=None):
        # A simple class provides Python's context manager special methods.
        owner = self
        class Response:
            def __init__(self, request, timeout):
                self.fixture = opener(request, timeout) if opener else owner.response(request, timeout)
            def __enter__(self):
                return self.fixture.__enter__(self.fixture)
            def __exit__(self, *args):
                return self.fixture.__exit__(self.fixture, *args)
        (self.support / 'config/strata-download-manifest.json').write_text(json.dumps({'mtp': self.manifest}), encoding='utf-8')
        fake_spec = SimpleNamespace(loader=SimpleNamespace(exec_module=lambda _: None))
        with patch.object(wrapper, 'SUPPORT', self.support), \
             patch.object(wrapper.subprocess, 'check_output', return_value='6f32ec070f23ced9f50e704d854d775da52591ab\n'), \
             patch.object(wrapper.subprocess, 'run', return_value=SimpleNamespace(returncode=0)), \
             patch.object(wrapper.importlib.util, 'spec_from_file_location', return_value=fake_spec), \
             patch.object(wrapper.importlib.util, 'module_from_spec', return_value=self.fetch), \
             patch.object(wrapper.urllib.request, 'urlopen', side_effect=Response), \
             redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            return wrapper.main()

    def test_good_existing_tensors_are_reused_without_any_network(self):
        self.run_wrapper()
        self.assertEqual(self.requests, [])
        self.fetch.resolve_repo.assert_not_called()
        self.fetch.inventory.assert_not_called()
        self.assertTrue((self.out / 'mtp-manifest.json').is_file())

    def test_good_partial_resumes_exact_range_and_is_finally_hashed(self):
        self.first_path.write_bytes(b'ab')
        self.run_wrapper()
        self.assertEqual(self.first_path.read_bytes(), self.payload)
        self.assertEqual(len(self.requests), 1)
        request, timeout = self.requests[0]
        self.assertEqual(request.get_header('Range'), f"bytes={self.first['start'] + 2}-{self.first['end']}")
        self.assertEqual(timeout, 45)
        self.assertEqual(request.get_header('Accept-encoding'), 'identity')
        self.assertEqual(self.read_sizes, [3])

    def test_corrupt_partial_is_retained_when_upstream_requests_deletion(self):
        self.first_path.write_bytes(b'WR')
        with self.assertRaisesRegex(RuntimeError, 'Unverified MTP tensor retained'):
            self.run_wrapper()
        self.assertEqual(self.first_path.read_bytes(), b'WRcd')
        self.assertEqual(len(self.requests), 1)
        self.assertFalse((self.out / 'mtp-manifest.json').exists())

    def test_complete_corrupt_or_oversized_tensor_is_refused_before_network(self):
        for payload in (b'WRNG', b'larger'):
            with self.subTest(payload=payload):
                self.first_path.write_bytes(payload)
                with self.assertRaisesRegex(RuntimeError, 'Existing incompatible tensor retained'):
                    self.run_wrapper()
                self.assertEqual(self.first_path.read_bytes(), payload)
                self.assertEqual(self.requests, [])

    def test_status_encoding_and_length_failures_keep_partial_with_two_attempt_limit(self):
        for kwargs in ({'status': 200}, {'encoded': 'gzip'}, {'extra': b'X'}):
            with self.subTest(kwargs=kwargs):
                self.first_path.write_bytes(b'ab')
                self.requests.clear()
                self.read_sizes.clear()
                with self.assertRaises(IOError):
                    self.run_wrapper(lambda request, timeout: self.response(request, timeout, **kwargs))
                self.assertEqual(self.first_path.read_bytes(), b'ab')
                self.assertEqual(len(self.requests), 2)
                self.assertTrue(all(timeout == 45 for _, timeout in self.requests))

    def test_incompatible_inventory_is_preserved_and_refused(self):
        inventory_path = self.out / 'mtp-inventory.json'
        before = b'{"repo":"a different revision"}'
        inventory_path.write_bytes(before)
        with self.assertRaisesRegex(RuntimeError, 'incompatible MTP inventory is retained'):
            self.run_wrapper()
        self.assertEqual(inventory_path.read_bytes(), before)
        self.assertEqual(self.requests, [])

    def test_manifest_hash_or_revision_changes_are_refused_before_network(self):
        self.manifest['tensors'][0]['sha256'] = '0' * 64
        with self.assertRaisesRegex(RuntimeError, 'range/hash differs'):
            self.run_wrapper()
        self.assertEqual(self.requests, [])
        self.manifest['tensors'][0]['sha256'] = self.fetch.SHA256[self.first['name']]
        self.manifest['revision'] = '0' * 40
        with self.assertRaisesRegex(RuntimeError, 'revisions differ'):
            self.run_wrapper()
        self.assertEqual(self.requests, [])

    def test_range_boundary_refuses_negative_reversed_noninteger_oversized_and_foreign_inputs(self):
        class Captured(Exception):
            pass
        def capture_fetch(*_):
            raise Captured()
        self.fetch.fetch = capture_fetch
        with self.assertRaises(Captured):
            self.run_wrapper()
        get = self.fetch.get
        valid_url = self.manifest['tensorUrlPrefix'] + self.first['shard']
        with patch.object(wrapper.urllib.request, 'urlopen') as network:
            for url, start, end in [(valid_url, -1, 0), (valid_url, 5, 4), (valid_url, None, 5),
                                    (valid_url, True, 5), (valid_url, 0, '5'), (valid_url, 0, 64 << 20),
                                    ('https://example.test/tensor', 0, 7)]:
                with self.subTest(url=url, start=start, end=end), self.assertRaises(ValueError):
                    get(url, start, end)
            network.assert_not_called()


if __name__ == '__main__':
    unittest.main()
