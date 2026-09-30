"""Offline switch failure injection; only temporary configs and tiny artifacts are used."""
from contextlib import nullcontext, redirect_stdout
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import urllib.error

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / 'tools'))
spec = importlib.util.spec_from_file_location('switch_model_offline_test', SOURCE / 'scripts/Switch-Model.py')
switch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(switch)


class ApiBoundary(unittest.TestCase):
    def test_local_roots_disable_proxies_and_redirects(self):
        for root in ['http://127.0.0.1:18081', 'http://localhost:18081/', 'http://[::1]:18081']:
            with self.subTest(root=root), patch.object(switch.urllib.request, 'build_opener') as build:
                api = switch.LocalApi(root)
                self.assertEqual(api.base, root.rstrip('/'))
                proxy, redirect = build.call_args.args
                self.assertEqual(proxy.proxies, {})
                self.assertIsInstance(redirect, switch.NoRedirect)
        for root in ['https://127.0.0.1', 'http://example.test', 'http://localhost.example.test',
                     'http://user:password@127.0.0.1', 'http://127.0.0.1/path',
                     'http://127.0.0.1?secret=yes', 'http://127.0.0.1#part']:
            with self.subTest(root=root), patch.object(switch.urllib.request, 'build_opener') as build:
                with self.assertRaises(ValueError):
                    switch.LocalApi(root)
                build.assert_not_called()

    def test_paths_and_redirects_cannot_change_origin(self):
        with patch.object(switch.urllib.request, 'build_opener') as build:
            api = switch.LocalApi('http://127.0.0.1:18081')
            for path in ['https://example.test', '//example.test/api', 'relative']:
                with self.subTest(path=path), self.assertRaises(ValueError):
                    api(path)
            build.return_value.open.assert_not_called()
        with self.assertRaisesRegex(RuntimeError, 'redirected'):
            switch.NoRedirect().redirect_request(None, None, 302, '', {}, 'http://example.test/')


class SwitchRecovery(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='model-switch-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'runtime-root'
        self.support = Path(self.temp.name) / 'support'
        for path in [self.root / 'models', self.root / 'runtime/agent-queue', self.support / 'config']:
            path.mkdir(parents=True)
        self.base = self.root / 'models/base.gguf'
        self.candidate = self.root / 'models/candidate.gguf'
        self.projector = self.root / 'models/mmproj.gguf'
        for path, data in [(self.base, b'base'), (self.candidate, b'candidate'), (self.projector, b'projector')]:
            path.write_bytes(data)
        self.config_path = self.support / 'config/support-config.json'
        self.config = {
            'target': {'root': str(self.root), 'executable': str(self.root / 'fixture-server.exe'), 'defaultUrl': 'http://127.0.0.1:18080'},
            'inference': {'modelPath': str(self.base), 'mmprojPath': str(self.projector), 'alias': 'stable-alias', 'contextSize': 8192, 'port': 18080},
            'chatApp': {'url': 'http://127.0.0.1:18081', 'modelId': 'fixture-agent'},
        }
        self.original = (json.dumps(self.config, ensure_ascii=False, indent=2) + '\n').encode()
        self.config_path.write_bytes(self.original)
        def entry(profile_id, path):
            artifact = lambda p: {'path': str(p.relative_to(self.root)), 'size': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
            return {'id': profile_id, 'label': 'Fixture ' + profile_id, 'model': artifact(path), 'mmproj': artifact(self.projector),
                    'source': {'repo': 'fixture/' + profile_id, 'revision': 'a' * 40, 'url': 'https://example.test/' + profile_id}, 'license': 'apache-2.0'}
        self.catalog = {'profiles': [entry('original', self.base), entry('candidate', self.candidate)]}
        self.catalog_path = self.support / 'config/model-profiles.json'
        self.catalog_path.write_text(json.dumps(self.catalog), encoding='utf-8')
        self.before_model = {'id': 'fixture-agent', 'name': 'Original fixture', 'base_model_id': 'stable-alias',
                             'params': {'system': 'Preserve fixture instruction.', 'temperature': 0.3},
                             'meta': {'toolIds': ['local_studio']}, 'is_active': True, 'access_grants': []}
        self.live_model = deepcopy(self.before_model)
        self.api_calls, self.script_calls, self.preset_updates = [], [], []
        self.tasks, self.activity, self.slots = {'tasks': []}, {'active_count': 0}, [{'is_processing': False}]
        self.gate = {'admission_gate': True, 'admitted_chats': 0}
        self.app_offline = False
        self.running_model = self.base.resolve()
        self.failures = {}
        self.stop_count = self.start_count = 0
        self.runtime = SimpleNamespace(assert_idle=Mock(), free_idle=Mock(), gpu_lease=Mock(side_effect=lambda context: nullcontext()))
        self.fake_cli = SimpleNamespace(submission_lock=lambda: nullcontext())
        self.fake_spec = SimpleNamespace(loader=SimpleNamespace(exec_module=lambda module: None))
        self.state_path = self.root / 'runtime/server.json'
        self.process = SimpleNamespace(create_time=lambda: 1000.0, cmdline=self.command)
        self.output = io.StringIO()

    def command(self):
        return [self.config['target']['executable'], '--model', str(self.running_model), '--mmproj', str(self.projector)]

    def save_state(self):
        self.state_path.write_text(json.dumps({'pid': 1234, 'startUtcTicks': int((62135596800 + 1000) * 10000000)}), encoding='utf-8')

    def api_factory(self, base):
        owner = self
        class FixtureApi:
            token = None
            def __call__(self, path, value=None):
                owner.api_calls.append((base, path))
                if base.endswith(':18080'):
                    return deepcopy(owner.slots)
                if owner.app_offline:
                    raise urllib.error.URLError(ConnectionRefusedError())
                if path == '/health': return {'status': True}
                if path == '/api/v1/auths/signin': return {'token': 'fixture-token'}
                if path == '/api/tasks': return deepcopy(owner.tasks)
                if path == '/api/local-studio/activity': return deepcopy(owner.activity)
                if path == '/api/local-studio/model-maintenance': return deepcopy(owner.gate)
                if path == '/api/v1/models/all': return {'items': [deepcopy(owner.live_model)]}
                if path.startswith('/api/v1/models/model/update'):
                    owner.preset_updates.append(deepcopy(value))
                    owner.live_model = deepcopy(value)
                    if len(owner.preset_updates) == 1 and owner.failures.get('preset_update'):
                        raise RuntimeError('preset update failed after applying')
                    if len(owner.preset_updates) > 1 and owner.failures.get('preset_restore'):
                        raise RuntimeError('preset restore failed')
                    return deepcopy(owner.live_model)
                raise AssertionError('Unexpected fixture endpoint')
        return FixtureApi()

    def launcher(self, path):
        name = path.name
        self.script_calls.append(name)
        if name == 'Stop-LocalLLM.ps1':
            self.stop_count += 1
            if self.stop_count == 2 and self.failures.get('rollback_stop'):
                raise RuntimeError('failed new profile would not stop')
            self.running_model = None
            if self.stop_count == 1 and self.failures.get('first_stop'):
                raise RuntimeError('old process stopped but cleanup failed')
        elif name == 'Start-LocalLLM.ps1':
            self.start_count += 1
            self.running_model = Path(json.loads(self.config_path.read_text())['inference']['modelPath']).resolve()
            self.save_state()
            if self.start_count == 1 and self.failures.get('new_start'):
                raise RuntimeError('new startup failed')
            if self.start_count == 2 and self.failures.get('old_restart'):
                raise RuntimeError('previous profile restart failed')
        else:
            raise AssertionError('Unexpected fixture process launch')

    def run_switch(self, profile='candidate'):
        with patch.object(switch, 'SUPPORT', self.support), \
             patch.object(switch, 'LocalApi', side_effect=self.api_factory), \
             patch.object(switch.studio, 'ROOT', self.root), \
             patch.object(switch.studio, 'script', side_effect=self.launcher), \
             patch.object(switch.studio, 'media_runtime', return_value=(self.runtime, SimpleNamespace())), \
             patch.object(switch.importlib.util, 'spec_from_file_location', return_value=self.fake_spec), \
             patch.object(switch.importlib.util, 'module_from_spec', return_value=self.fake_cli), \
             patch('psutil.Process', return_value=self.process), \
             patch.object(switch.urllib.request, 'urlopen', side_effect=AssertionError('No real network calls')), \
             patch('subprocess.run', side_effect=AssertionError('No real subprocesses')), \
             patch('subprocess.Popen', side_effect=AssertionError('No real subprocesses')), \
             patch.object(sys, 'argv', ['Switch-Model.py', profile]), redirect_stdout(self.output):
            switch.main()

    def assert_original_recovered(self):
        self.assertEqual(self.config_path.read_bytes(), self.original)
        self.assertEqual(self.running_model, self.base.resolve())
        self.assertEqual(self.live_model, self.before_model)
        self.assertFalse((self.root / 'runtime/model-switch.json').exists())

    def test_success_preserves_other_config_and_preset_fields(self):
        self.run_switch()
        changed = json.loads(self.config_path.read_text())
        expected = deepcopy(self.config)
        expected['inference']['modelPath'] = str(self.candidate.resolve())
        expected['inference']['mmprojPath'] = str(self.projector.resolve())
        self.assertEqual(changed, expected)
        self.assertEqual(self.live_model['params'], self.before_model['params'])
        self.assertEqual(self.live_model['meta'], self.before_model['meta'])
        self.assertEqual(json.loads(self.output.getvalue())['active_profile'], 'candidate')
        self.assertFalse((self.root / 'runtime/model-switch.json').exists())
        backups = list((self.root / 'runtime/maintenance-backups').glob('*/support-config.json'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), self.original)

    def test_bad_hash_and_unknown_profile_never_stop_or_write(self):
        with self.assertRaises(ValueError): self.run_switch('unknown')
        self.catalog['profiles'][1]['model']['sha256'] = '0' * 64
        self.catalog_path.write_text(json.dumps(self.catalog), encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'SHA256'): self.run_switch()
        self.assertEqual(self.script_calls, [])
        self.assertEqual(self.api_calls, [])
        self.assertEqual(self.config_path.read_bytes(), self.original)

    def test_projector_hash_is_verified_before_switching(self):
        self.catalog['profiles'][1]['mmproj']['sha256'] = '0' * 64
        self.catalog_path.write_text(json.dumps(self.catalog), encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'SHA256'): self.run_switch()
        self.assertEqual(self.script_calls, [])
        self.assertEqual(self.api_calls, [])
        self.assertEqual(self.config_path.read_bytes(), self.original)

    def test_queued_cli_job_is_preserved(self):
        marker = self.root / 'runtime/agent-queue/fixture-job'
        marker.write_text('queued', encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'Agent tasks'): self.run_switch()
        self.assertEqual(marker.read_text(), 'queued')
        self.assertEqual(self.script_calls, [])
        self.assertEqual(self.config_path.read_bytes(), self.original)
        self.assertFalse((self.root / 'runtime/model-switch.json').exists())

    def test_media_busy_guard_never_stops_existing_model(self):
        self.runtime.assert_idle.side_effect = RuntimeError('ComfyUI is busy')
        with self.assertRaisesRegex(RuntimeError, 'busy'): self.run_switch()
        self.assertEqual(self.script_calls, [])
        self.runtime.free_idle.assert_not_called()

    def test_chat_and_admission_unknown_states_are_rejected(self):
        cases = [('tasks', {'tasks': ['running']}), ('tasks', {}), ('activity', {'active_count': 1}),
                 ('activity', {}), ('activity', {'active_count': False}),
                 ('gate', {'admission_gate': True, 'admitted_chats': 1}),
                 ('gate', {'admission_gate': True})]
        for attribute, value in cases:
            with self.subTest(attribute=attribute, value=value):
                original = getattr(self, attribute)
                setattr(self, attribute, value)
                try:
                    with self.assertRaisesRegex(RuntimeError, 'active|unknown'): self.run_switch()
                    self.assertEqual(self.script_calls, [])
                    self.assertFalse((self.root / 'runtime/model-switch.json').exists())
                finally:
                    setattr(self, attribute, original)

    def test_slots_need_explicit_idle_booleans(self):
        for slots in [[], {}, [{}], [{'is_processing': None}], [{'is_processing': 0}], [{'is_processing': True}]]:
            with self.subTest(slots=slots):
                self.slots = slots
                with self.assertRaisesRegex(RuntimeError, 'active|unknown'): self.run_switch()
                self.assertEqual(self.script_calls, [])

    def test_stop_failure_after_termination_restarts_previous_model(self):
        self.failures['first_stop'] = True
        with self.assertRaisesRegex(RuntimeError, 'cleanup failed'): self.run_switch()
        self.assert_original_recovered()

    def test_free_failure_after_stop_restarts_previous_model(self):
        self.runtime.free_idle.side_effect = RuntimeError('free failed')
        with self.assertRaisesRegex(RuntimeError, 'free failed'): self.run_switch()
        self.assert_original_recovered()

    def test_new_start_failure_restores_original_config_and_preset(self):
        self.failures['new_start'] = True
        with self.assertRaisesRegex(RuntimeError, 'new startup failed'): self.run_switch()
        self.assert_original_recovered()

    def test_preset_unknown_outcome_is_recovered_independently(self):
        self.failures['preset_update'] = True
        with self.assertRaisesRegex(RuntimeError, 'preset update failed'): self.run_switch()
        self.assertEqual(len(self.preset_updates), 2)
        self.assert_original_recovered()

    def test_rollback_stop_failure_keeps_live_new_config_and_original_backup(self):
        self.failures.update(new_start=True, rollback_stop=True)
        with self.assertRaisesRegex(RuntimeError, 'new startup failed.*recovery incomplete.*would not stop'): self.run_switch()
        self.assertEqual(json.loads(self.config_path.read_text())['inference']['modelPath'], str(self.candidate.resolve()))
        self.assertEqual(self.running_model, self.candidate.resolve())
        self.assertEqual(self.live_model, self.before_model)
        self.assertEqual(self.start_count, 1)
        self.assertEqual(next((self.root / 'runtime/maintenance-backups').glob('*/support-config.json')).read_bytes(), self.original)
        self.assertFalse((self.root / 'runtime/model-switch.json').exists())

    def test_previous_restart_failure_still_attempts_preset_restore(self):
        self.failures.update(new_start=True, old_restart=True, preset_update=True)
        with self.assertRaisesRegex(RuntimeError, 'recovery incomplete.*previous profile restart failed'): self.run_switch()
        self.assertTrue(self.preset_updates, 'Preset recovery must run even when restart fails')
        self.assertEqual(self.config_path.read_bytes(), self.original)
        self.assertFalse((self.root / 'runtime/model-switch.json').exists())

    def test_config_restore_failure_reports_backup_and_still_restores_preset(self):
        self.failures['new_start'] = True
        original_atomic = switch.atomic_config
        calls = []
        def failing_restore(path, data):
            calls.append(data)
            if len(calls) > 1: raise RuntimeError('restore config failed')
            return original_atomic(path, data)
        with patch.object(switch, 'atomic_config', side_effect=failing_restore):
            with self.assertRaisesRegex(RuntimeError, 'new startup failed.*recovery incomplete.*restore config failed.*maintenance-backups'):
                self.run_switch()
        self.assertTrue(self.preset_updates)
        self.assertEqual(self.live_model, self.before_model)
        self.assertEqual(self.start_count, 1)
        self.assertEqual(next((self.root / 'runtime/maintenance-backups').glob('*/support-config.json')).read_bytes(), self.original)
        self.assertFalse((self.root / 'runtime/model-switch.json').exists())

    def test_app_offline_does_not_skip_artifact_or_model_guards(self):
        self.app_offline = True
        self.run_switch()
        self.assertEqual(self.running_model, self.candidate.resolve())
        self.assertEqual(self.preset_updates, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
