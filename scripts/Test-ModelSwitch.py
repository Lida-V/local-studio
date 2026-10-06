"""Offline switch failure injection; only temporary configs and tiny artifacts are used."""
from contextlib import nullcontext, redirect_stdout
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
import os
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
        self.running_backend = 'llama.cpp'
        self.process_requests = []
        self.failures = {}
        self.stop_count = self.start_count = 0
        self.runtime = SimpleNamespace(assert_idle=Mock(), free_idle=Mock(), gpu_lease=Mock(side_effect=lambda context: nullcontext()))
        self.fake_cli = SimpleNamespace(submission_lock=lambda: nullcontext())
        self.fake_spec = SimpleNamespace(loader=SimpleNamespace(exec_module=lambda module: None))
        self.state_path = self.root / 'runtime/server.json'
        self.process = SimpleNamespace(create_time=lambda: 1000.0, cmdline=self.command)
        self.output = io.StringIO()

    def command(self):
        if self.running_backend == 'strata':
            config = json.loads(self.config_path.read_text(encoding='utf-8'))
            server_config = config['strata']['serverConfigPath']
            if self.failures.get('launcher_config'):
                server_config = str(self.root / 'apps/wrong.json')
            return [config['target']['executable'], '--config', server_config]
        return [self.config['target']['executable'], '--model', str(self.running_model), '--mmproj', str(self.projector)]

    def save_state(self):
        state = {'pid': 1234, 'startUtcTicks': int((62135596800 + 1000) * 10000000)}
        if self.running_backend == 'strata':
            config = json.loads(self.config_path.read_text(encoding='utf-8'))
            token = 'a' * 32
            process_state = self.root / f'runtime/strata-process-{token}.json'
            state.update(launchToken=token, processStatePath=str(process_state))
            identity = {'launchToken': token, 'backend': 'strata', 'jobContained': True,
                        'sourceRoot': config['strata']['sourceRoot'],
                        'serverConfigPath': config['strata']['serverConfigPath'],
                        'server': {'pid': 1235, 'startUtcTicks': int((62135596800 + 1001) * 10000000),
                                   'executable': str(self.strata_interpreter)}}
            if self.failures.get('launcher_pid'): state['pid'] = 9999
            if self.failures.get('launcher_ticks'): state['startUtcTicks'] += 20000000
            if self.failures.get('launch_token'): state['launchToken'] = 'not-a-launch-nonce'
            if self.failures.get('process_state_path'): state['processStatePath'] = str(self.root / 'runtime/unrelated.json')
            if self.failures.get('identity_token'): identity['launchToken'] = 'b' * 32
            if self.failures.get('identity_backend'): identity['backend'] = 'llama.cpp'
            if self.failures.get('identity_job'): identity['jobContained'] = False
            if self.failures.get('identity_config'): identity['serverConfigPath'] = str(self.root / 'apps/wrong.json')
            if self.failures.get('identity_source'): identity['sourceRoot'] = str(self.root / 'apps/wrong-source')
            if self.failures.get('identity_pid'): identity['server']['pid'] = 9999
            if self.failures.get('identity_ticks'): identity['server']['startUtcTicks'] += 20000000
            if self.failures.get('identity_executable'): identity['server']['executable'] = str(self.root / 'apps/wrong.exe')
            process_state.write_text(json.dumps(identity), encoding='utf-8')
        self.state_path.write_text(json.dumps(state), encoding='utf-8')

    def fixture_process(self, pid=None):
        if pid is None or pid == os.getpid(): return self.process
        self.process_requests.append(pid)
        if pid == 1234: return self.process
        if pid == 1235: return self.strata_server_process
        raise RuntimeError('Recorded process does not exist')

    def install_strata_fixture(self):
        self.strata_interpreter = self.root / 'apps/Strata/source/python-base.exe'
        self.strata_interpreter.parent.mkdir(parents=True, exist_ok=True)
        self.strata_interpreter.write_bytes(b'fixture interpreter')
        self.strata_config = self.strata_interpreter.parent / 'strata-fixture.json'
        self.shard = self.root / 'models/ngram-shard.gguf'
        self.shard.write_bytes(b'fixture ngram shard')
        self.server_config = {'model_name': 'fixture-strata-canonical',
            'args': ['--native', str(self.candidate), '--ple-gguf', str(self.shard)],
            'vision': {'model': str(self.candidate), 'mmproj': str(self.projector)}}
        self.strata_config.write_text(json.dumps(self.server_config), encoding='utf-8')
        profile = deepcopy(self.catalog['profiles'][1])
        profile.update(id='strata', label='Fixture Strata')
        profile['additionalArtifacts'] = [{'key': 'shard2', 'path': 'models/ngram-shard.gguf',
            'size': self.shard.stat().st_size, 'sha256': hashlib.sha256(self.shard.read_bytes()).hexdigest()}]
        profile['backend'] = {'kind': 'strata', 'executable': 'apps/Strata/source/python-base.exe',
            'sourceRoot': 'apps/Strata/source', 'serverConfigPath': 'apps/Strata/source/strata-fixture.json',
            'contextSize': 131072, 'modelName': 'fixture-strata-canonical', 'pleArtifact': 'shard2'}
        self.catalog['profiles'].append(profile)
        self.catalog_path.write_text(json.dumps(self.catalog), encoding='utf-8')
        self.strata_server_process = SimpleNamespace(create_time=lambda: 1001.0,
                                                     exe=lambda: str(self.strata_interpreter))
        self.strata_health = {'service': 'strata', 'loaded': True, 'images': True,
                              'max_context': 131072, 'model': 'fixture-strata-canonical'}
        return profile

    def api_factory(self, base):
        owner = self
        class FixtureApi:
            token = None
            def __call__(self, path, value=None):
                owner.api_calls.append((base, path))
                if base.endswith(':18080'):
                    if path == '/health': return deepcopy(owner.strata_health)
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
            active = json.loads(self.config_path.read_text())
            self.running_model = Path(active['inference']['modelPath']).resolve()
            self.running_backend = active['inference'].get('backend', 'llama.cpp')
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
             patch('psutil.Process', side_effect=self.fixture_process), \
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

    def test_strata_config_mismatch_never_stops_writes_or_calls_live_api(self):
        profile = self.install_strata_fixture()
        expected_server = deepcopy(self.server_config)
        expected_backend = deepcopy(profile['backend'])
        cases = ('native', 'duplicate_native', 'missing_native_value', 'relative_native',
                 'vision_model', 'vision_mmproj', 'ple', 'duplicate_ple', 'canonical',
                 'missing_model_name', 'unknown_ple_key')
        for case in cases:
            with self.subTest(case=case):
                server = deepcopy(expected_server)
                profile['backend'] = deepcopy(expected_backend)
                if case == 'native':
                    server['args'][1] = str(self.base)
                elif case == 'duplicate_native':
                    server['args'] += ['--native', str(self.base)]
                elif case == 'missing_native_value':
                    server['args'] = ['--native']
                elif case == 'relative_native':
                    server['args'][1] = 'models/candidate.gguf'
                elif case == 'vision_model':
                    server['vision']['model'] = str(self.base)
                elif case == 'vision_mmproj':
                    server['vision']['mmproj'] = str(self.base)
                elif case == 'ple':
                    server['args'][3] = str(self.candidate)
                elif case == 'duplicate_ple':
                    server['args'] += ['--ple-gguf', str(self.candidate)]
                elif case == 'canonical':
                    server['model_name'] = 'another-canonical'
                elif case == 'missing_model_name':
                    del profile['backend']['modelName']
                elif case == 'unknown_ple_key':
                    profile['backend']['pleArtifact'] = 'unexpected'
                self.strata_config.write_text(json.dumps(server), encoding='utf-8')
                self.catalog_path.write_text(json.dumps(self.catalog), encoding='utf-8')
                with patch.object(switch, 'atomic_config', wraps=switch.atomic_config) as config_write:
                    with self.assertRaises(ValueError):
                        self.run_switch('strata')
                    config_write.assert_not_called()
                self.assertEqual(self.script_calls, [])
                self.assertEqual(self.api_calls, [])
                self.assertEqual(self.config_path.read_bytes(), self.original)
                self.assertFalse((self.root / 'runtime/maintenance-backups').exists())
                self.assertFalse((self.root / 'runtime/model-switch.json').exists())

    def test_strata_ple_can_use_the_main_artifact_for_swift(self):
        profile = self.install_strata_fixture()
        profile['backend']['pleArtifact'] = 'model'
        self.server_config['args'][3] = str(self.candidate)
        self.strata_config.write_text(json.dumps(self.server_config), encoding='utf-8')
        self.catalog_path.write_text(json.dumps(self.catalog), encoding='utf-8')
        self.run_switch('strata')
        self.assertEqual(self.running_backend, 'strata')

    def test_strata_optional_ple_metadata_does_not_break_existing_profiles(self):
        profile = self.install_strata_fixture()
        del profile['backend']['pleArtifact']
        self.catalog_path.write_text(json.dumps(self.catalog), encoding='utf-8')
        self.run_switch('strata')
        self.assertEqual(self.running_backend, 'strata')

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

    def test_missing_incomplete_and_wrong_hash_shard_never_stop_or_write(self):
        profile = self.install_strata_fixture()
        original_bytes = self.shard.read_bytes()
        for condition in ['missing', 'incomplete', 'same-size-corruption', 'wrong-catalog-hash']:
            with self.subTest(condition=condition):
                self.shard.write_bytes(original_bytes)
                profile['additionalArtifacts'][0]['sha256'] = hashlib.sha256(original_bytes).hexdigest()
                if condition == 'missing': self.shard.unlink()
                if condition == 'incomplete': self.shard.write_bytes(b'x')
                if condition == 'same-size-corruption': self.shard.write_bytes(b'x' * len(original_bytes))
                if condition == 'wrong-catalog-hash': profile['additionalArtifacts'][0]['sha256'] = '0' * 64
                self.catalog_path.write_text(json.dumps(self.catalog), encoding='utf-8')
                with self.assertRaises((FileNotFoundError, ValueError, RuntimeError)):
                    self.run_switch('strata')
                self.assertEqual(self.script_calls, [])
                self.assertEqual(self.api_calls, [])
                self.assertEqual(self.config_path.read_bytes(), self.original)
                self.assertFalse((self.root / 'runtime/maintenance-backups').exists())

    def test_strata_success_uses_real_server_identity_and_ready_health(self):
        self.install_strata_fixture()
        self.run_switch('strata')
        changed = json.loads(self.config_path.read_text(encoding='utf-8'))
        self.assertEqual(changed['inference']['backend'], 'strata')
        self.assertEqual(changed['inference']['alias'], 'stable-alias')
        self.assertEqual(changed['inference']['contextSize'], 131072)
        self.assertEqual(changed['strata']['serverConfigPath'], str(self.strata_config.resolve()))
        self.assertEqual(self.process_requests, [1234, 1235])
        self.assertIn(('http://127.0.0.1:18080', '/health'), self.api_calls)
        self.assertEqual(self.live_model['params'], self.before_model['params'])
        self.assertEqual(self.live_model['meta'], self.before_model['meta'])
        self.assertEqual(json.loads(self.output.getvalue())['active_profile'], 'strata')

    def test_strata_owned_process_failures_restore_legacy_backend(self):
        self.install_strata_fixture()
        for failure in ['launcher_pid', 'launcher_ticks', 'launcher_config', 'launch_token',
                        'process_state_path', 'identity_token', 'identity_backend', 'identity_job',
                        'identity_config', 'identity_source', 'identity_pid', 'identity_ticks',
                        'identity_executable']:
            with self.subTest(failure=failure):
                self.failures = {failure: True}
                with self.assertRaises((AssertionError, RuntimeError, KeyError, ValueError)):
                    self.run_switch('strata')
                self.assert_original_recovered()
                self.assertEqual(self.running_backend, 'llama.cpp')
                self.assertNotIn('backend', json.loads(self.config_path.read_text())['inference'])
                self.assertNotIn('strata', json.loads(self.config_path.read_text()))

    def test_strata_readiness_requires_service_loaded_images_and_context(self):
        self.install_strata_fixture()
        ready = deepcopy(self.strata_health)
        for field, value in [('service', 'llama.cpp'), ('loaded', False), ('loaded', 1),
                             ('images', False), ('images', 1), ('max_context', 8192), ('model', 'another-canonical')]:
            with self.subTest(field=field, value=value):
                self.strata_health = {**ready, field: value}
                with self.assertRaises(AssertionError):
                    self.run_switch('strata')
                self.assert_original_recovered()
        for field in ready:
            with self.subTest(missing=field):
                self.strata_health = {key: value for key, value in ready.items() if key != field}
                with self.assertRaises(AssertionError):
                    self.run_switch('strata')
                self.assert_original_recovered()

    def test_strata_start_failure_restores_original_runtime_config_and_preset(self):
        self.install_strata_fixture()
        self.failures['new_start'] = True
        with self.assertRaisesRegex(RuntimeError, 'new startup failed'):
            self.run_switch('strata')
        self.assert_original_recovered()
        self.assertEqual(self.running_backend, 'llama.cpp')

    def test_uppercase_catalog_hashes_verify_all_shards(self):
        profile = self.install_strata_fixture()
        for artifact in switch.model_profiles.artifacts(profile).values():
            artifact['sha256'] = artifact['sha256'].upper()
        self.catalog_path.write_text(json.dumps(self.catalog), encoding='utf-8')
        self.run_switch('strata')
        self.assertEqual(self.running_backend, 'strata')

    def test_strata_to_explicit_llama_profile_restores_executable_and_context(self):
        self.install_strata_fixture()
        old_server = self.root / 'bin/llama/llama-server.exe'
        old_server.parent.mkdir(parents=True)
        old_server.write_bytes(b'fixture old executable')
        self.catalog['profiles'][0]['backend'] = {'kind': 'llama.cpp',
            'executable': 'bin/llama/llama-server.exe', 'contextSize': 8192}
        self.catalog_path.write_text(json.dumps(self.catalog), encoding='utf-8')
        self.run_switch('strata')
        self.run_switch('original')
        restored = json.loads(self.config_path.read_text(encoding='utf-8'))
        self.assertEqual(restored['target']['executable'], str(old_server.resolve()))
        self.assertEqual(restored['inference']['backend'], 'llama.cpp')
        self.assertEqual(restored['inference']['contextSize'], 8192)
        self.assertEqual(restored['inference']['modelPath'], str(self.base.resolve()))
        self.assertEqual(self.running_backend, 'llama.cpp')
        self.assertEqual(self.live_model['params'], self.before_model['params'])
        self.assertEqual(self.live_model['meta'], self.before_model['meta'])
        self.assertEqual(self.process_requests, [1234, 1235, 1234])


if __name__ == '__main__':
    unittest.main(verbosity=2)
