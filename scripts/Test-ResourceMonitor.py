"""Offline boundary checks for read-only resource telemetry; no real GPU tasks."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import resource_monitor as monitor


class ResourceMonitorTests(unittest.TestCase):
    def test_unknown_and_impossible_numbers_never_become_zero(self):
        for value in (None, 'N/A', '[Not Supported]', float('nan'), float('inf'), -1, True):
            self.assertIsNone(monitor.number(value))
        self.assertIsNone(monitor.number(101, maximum=100))
        self.assertEqual(monitor.number('0'), 0)
        self.assertIsNone(monitor.count(1.5))

    def test_gpu_missing_and_timeout_are_explicit(self):
        with patch.object(monitor.shutil, 'which', return_value=None):
            data, warnings = monitor.gpu_telemetry()
            self.assertEqual(data, [])
            self.assertTrue(warnings)
        with patch.object(monitor.shutil, 'which', return_value='nvidia-smi'), \
                patch.object(monitor.subprocess, 'run', side_effect=subprocess.TimeoutExpired('nvidia-smi', .8)) as run:
            data, warnings = monitor.gpu_telemetry()
            self.assertEqual(data, [])
            self.assertIn('時間内', warnings[0])
            self.assertLessEqual(run.call_args.kwargs['timeout'], 1)
            self.assertFalse(run.call_args.kwargs.get('shell', False))

    def test_gpu_csv_keeps_unknown_fields_and_rejects_range(self):
        output = b'GPU A, 50, 24564, 19000, 5500, 43\nGPU B, N/A, 4096, 5000, 100, 999\n'
        with patch.object(monitor.shutil, 'which', return_value='nvidia-smi'), \
                patch.object(monitor.subprocess, 'run', return_value=SimpleNamespace(stdout=output)):
            gpus, warnings = monitor.gpu_telemetry()
        self.assertEqual(len(gpus), 2)
        self.assertEqual(gpus[0]['memoryUsedBytes'], 19000 * monitor.MIB)
        self.assertIsNone(gpus[1]['utilizationPercent'])
        self.assertIsNone(gpus[1]['memoryUsedBytes'])
        self.assertIsNone(gpus[1]['temperatureC'])

    def test_gpu_child_supplements_only_missing_programfiles(self):
        minimal = {'PATH': 'minimal-path', 'SYSTEMROOT': 'windows'}
        output = b'GPU A, 0, 24564, 19000, 5500, 43\n'
        with patch.object(monitor.os, 'name', 'nt'), \
                patch.dict(monitor.os.environ, minimal, clear=True), \
                patch.object(monitor, 'native_program_files', return_value=r'Z:\Apps') as lookup, \
                patch.object(monitor.shutil, 'which', return_value='nvidia-smi'), \
                patch.object(monitor.subprocess, 'run', return_value=SimpleNamespace(stdout=output)) as run:
            gpus, warnings = monitor.gpu_telemetry()
            self.assertEqual(len(gpus), 1)
            self.assertFalse(warnings)
            self.assertEqual(run.call_args.kwargs['env'], minimal | {'PROGRAMFILES': r'Z:\Apps'})
            self.assertEqual(dict(monitor.os.environ), minimal)
            lookup.assert_called_once()
        with patch.object(monitor.os, 'name', 'nt'), \
                patch.dict(monitor.os.environ, minimal | {'PROGRAMFILES': r'Y:\Existing'}, clear=True), \
                patch.object(monitor, 'native_program_files') as lookup:
            env = monitor.gpu_environment()
            self.assertEqual(env['PROGRAMFILES'], r'Y:\Existing')
            lookup.assert_not_called()
        with patch.object(monitor.os, 'name', 'nt'), \
                patch.dict(monitor.os.environ, minimal, clear=True), \
                patch.object(monitor, 'native_program_files', return_value=None), \
                patch.object(monitor.shutil, 'which', return_value='nvidia-smi'), \
                patch.object(monitor.subprocess, 'run', side_effect=subprocess.CalledProcessError(255, 'nvidia-smi')) as run:
            gpus, warnings = monitor.gpu_telemetry()
            self.assertEqual(run.call_args.kwargs['env'], minimal)
            self.assertEqual(gpus, [])
            self.assertTrue(warnings)

    def test_programfiles_known_folder_api_validates_native_results(self):
        lookup = Mock()
        def reply(owner, folder_id, token, flags, buffer):
            self.assertIsNone(owner)
            self.assertEqual(folder_id, 0x26)
            self.assertEqual(flags, 0)
            buffer.value = r'Z:\Apps'
            return 0
        lookup.side_effect = reply
        shell = SimpleNamespace(SHGetFolderPathW=lookup)
        with patch.object(monitor.os, 'name', 'nt'), \
                patch.object(monitor.ctypes, 'WinDLL', return_value=shell, create=True) as load:
            self.assertEqual(monitor.native_program_files(), r'Z:\Apps')
            load.assert_called_with('shell32', use_last_error=True)
            self.assertEqual(lookup.argtypes[1], monitor.ctypes.c_int)
            lookup.side_effect = None
            lookup.return_value = -1
            self.assertIsNone(monitor.native_program_files())
            def relative(owner, folder_id, token, flags, buffer):
                buffer.value = 'relative/apps'
                return 0
            lookup.side_effect = relative
            self.assertIsNone(monitor.native_program_files())
        with patch.object(monitor.os, 'name', 'nt'), \
                patch.object(monitor.ctypes, 'WinDLL', side_effect=OSError('native unavailable'), create=True):
            self.assertIsNone(monitor.native_program_files())

    def test_loopback_credential_and_redirect_boundaries(self):
        with patch.object(monitor.urllib.request, 'build_opener') as opener:
            for url in ('https://127.0.0.1/queue', 'http://example.com/queue',
                        'http://user:secret@127.0.0.1/queue', 'http://127.0.0.1/queue?token=secret',
                        'http://127.0.0.1/status', 'http://127.0.0.1/v1/chat/completions'):
                with self.assertRaises(ValueError):
                    monitor.local_json(url)
            opener.assert_not_called()
        with self.assertRaises(ValueError):
            monitor.NoRedirect().redirect_request(None, None, 302, '', {}, 'http://example.com')

    def test_cpu_library_missing_and_invalid_ram(self):
        with patch.object(monitor, 'psutil', None):
            cpu, memory, warnings = monitor.cpu_memory()
            self.assertIsNone(cpu['percent'])
            self.assertIsNone(memory['usedBytes'])
            self.assertTrue(warnings)
        psutil = SimpleNamespace(cpu_percent=lambda interval: 50, cpu_count=lambda logical: 16,
                                 virtual_memory=lambda: SimpleNamespace(total=100, available=101))
        with patch.object(monitor, 'psutil', psutil):
            cpu, memory, warnings = monitor.cpu_memory()
            self.assertIsNone(memory['usedBytes'])
            self.assertEqual(cpu['percent'], 50)

    def test_psutil_error_is_a_measurement_failure_not_an_exception(self):
        if monitor.psutil is None:
            self.skipTest('Optional library unavailable.')
        with patch.object(monitor.psutil, 'cpu_percent', side_effect=monitor.PSUTIL_ERROR()), \
                patch.object(monitor.psutil, 'virtual_memory', side_effect=monitor.PSUTIL_ERROR()):
            cpu, memory, warnings = monitor.cpu_memory()
        self.assertIsNone(cpu['percent'])
        self.assertIsNone(memory['usedBytes'])
        self.assertEqual(len(warnings), 2)

    def test_metadata_read_limit_and_artifact_escape(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            oversized = root / 'metadata.json'
            oversized.write_bytes(b' ' * (monitor.MAX_JSON_BYTES + 1))
            with self.assertRaises(ValueError):
                monitor.bounded_json(oversized)
            with self.assertRaises(ValueError):
                monitor.safe_relative(root, '../other/model.gguf')
            self.assertEqual(monitor.safe_relative(root, 'model.gguf'), root / 'model.gguf')

    def test_stale_pid_and_actual_image_mismatch_deny_owned_ram(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'runtime').mkdir()
            token = 'a' * 32
            state_path = root / 'runtime' / ('strata-process-' + token + '.json')
            image = str(root / 'python.exe')
            ticks = 621355968000000000 + 100 * 10_000_000
            owner = dict(backend='strata', launchToken=token, pid=1,
                         startUtcTicks=ticks, executable=image, processStatePath=str(state_path))
            server = dict(pid=2, startUtcTicks=ticks, executable=image)
            state = dict(backend='strata', launchToken=token, jobContained=True,
                         parentPid=1, server=server, children=[])
            (root / 'runtime/server.json').write_text(json.dumps(owner), encoding='utf-8')
            state_path.write_text(json.dumps(state), encoding='utf-8')
            class Process:
                created, actual = 100, image
                def __init__(self, pid): self.pid = pid
                def is_running(self): return True
                def create_time(self): return self.created
                def exe(self): return self.actual
                def memory_info(self): return SimpleNamespace(rss=2048)
            psutil = SimpleNamespace(Process=Process, Error=RuntimeError)
            with patch.object(monitor, 'psutil', psutil):
                result = monitor.owned_memory(root)
                self.assertEqual(result['memoryBytes'], 4096)
                self.assertEqual(result['processCount'], 2)
                self.assertIsNone(result['gpuMemoryBytes'])
                Process.created = 101
                self.assertIsNone(monitor.owned_memory(root)['memoryBytes'])
                Process.created, Process.actual = 100, str(root / 'other.exe')
                self.assertIsNone(monitor.owned_memory(root)['memoryBytes'])
                Process.actual = image
                state['launchToken'] = 'b' * 32
                state_path.write_text(json.dumps(state), encoding='utf-8')
                self.assertIsNone(monitor.owned_memory(root)['memoryBytes'])

    def test_partial_media_timeout_does_not_claim_idle_or_zero(self):
        registry = {'anima': {'url': 'http://127.0.0.1:8188'},
                    'qwen-image-2.1': {'url': 'http://127.0.0.1:8191'}}
        config = {'target': {'defaultUrl': 'http://127.0.0.1:18080'}, 'inference': {'backend': 'strata'}}
        def probe(url):
            if url.endswith('/v1/status'):
                return {'loaded': True, 'model': 'safe-model', 'activity': {'in_flight': 0}}
            if ':8191' in url:
                raise TimeoutError()
            return {'queue_running': [], 'queue_pending': []}
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(monitor, 'local_json', side_effect=probe), \
                patch.object(monitor, 'owned_memory', return_value={}):
            active, warnings = monitor.active_status(Path(folder), config, registry)
        self.assertEqual(active['state'], 'unknown')
        self.assertIsNone(active['runningJobs'])
        self.assertIsNone(active['queuedJobs'])
        self.assertTrue(warnings)

    def test_malformed_activity_is_unknown_and_never_reaches_output(self):
        config = {'target': {'defaultUrl': 'http://127.0.0.1:18080'}, 'inference': {'backend': 'strata'}}
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(monitor, 'local_json', return_value={'loaded': True, 'activity': 'not-an-object'}), \
                patch.object(monitor, 'owned_memory', return_value={}):
            active, warnings = monitor.active_status(Path(folder), config, {})
        self.assertEqual(active['state'], 'unknown')
        self.assertIsNone(active['inferenceRequests'])
        self.assertTrue(warnings)
        self.assertNotIn('not-an-object', json.dumps(active))

    def test_chat_candidate_requires_known_idle_media_and_agent_queues(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'config').mkdir()
            (root / 'runtime/agent-queue').mkdir(parents=True)
            catalog = {'profiles': [{'id': 'swift-flash-next', 'label': 'Swift 会話モデル',
                        'model': {'path': 'model.gguf'}, 'backend': {'modelName': 'swift-canonical'}}]}
            (root / 'config/model-profiles.json').write_text(json.dumps(catalog), encoding='utf-8')
            config = {'target': {'defaultUrl': 'http://127.0.0.1:18080'}, '_support': str(root),
                      'inference': {'backend': 'strata', 'modelPath': str(root / 'model.gguf')}}
            registry = {'anima': {'url': 'http://127.0.0.1:8188'}}
            pending = []
            def probe(url):
                if url.endswith('/v1/status'):
                    return {'loaded': True, 'model': 'swift-canonical', 'activity': {'in_flight': 2}}
                return {'queue_running': [], 'queue_pending': pending.copy()}
            with patch.object(monitor, 'local_json', side_effect=probe), \
                    patch.object(monitor, 'owned_memory', return_value={}):
                active, _ = monitor.active_status(root, config, registry)
                self.assertEqual(active['taskId'], 'swift-flash-next')
                self.assertEqual(active['modelId'], 'swift-canonical')
                self.assertEqual(active['modelLabel'], 'Swift 会話モデル')
                self.assertEqual(active['state'], 'running')
                pending.append(['generation'])
                active, _ = monitor.active_status(root, config, registry)
                self.assertIsNone(active['taskId'])
                pending.clear()
                (root / 'runtime/agent-queue' / ('a' * 32)).touch()
                active, _ = monitor.active_status(root, config, registry)
                self.assertIsNone(active['taskId'])
                self.assertEqual(active['pendingAgentJobs'], 1)

    def test_malformed_media_metadata_has_unknown_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'config').mkdir()
            media = {'anima': None, 'qwen-image-2.1': {'workflow': 'workflow.json',
                     'dimensions': '1', 'loaders': None}}
            (root / 'config/media-models.json').write_text(json.dumps(media), encoding='utf-8')
            (root / 'config/workflow.json').write_text('{"1":{"inputs":null}}', encoding='utf-8')
            tasks = monitor.task_guidance(root, root, {'inference': None, 'observed': None})
        qwen = next(task for task in tasks if task['id'] == 'qwen-image-2.1')
        self.assertIsNone(qwen['configured']['width'])
        self.assertIsNone(qwen['requirements']['modelStorageBytes'])

    def test_response_privacy_and_busy_shared_port_not_model_guess(self):
        registry = {'anima': {'url': 'http://127.0.0.1:8188'}}
        config = {'target': {'defaultUrl': 'http://127.0.0.1:18080'}, 'inference': {'backend': 'strata'}}
        secret = 'NEVER_RETURN_PROMPT_OR_API_KEY'
        def probe(url):
            if url.endswith('/v1/status'):
                return {'loaded': True, 'model': 'safe-model', 'activity': {'in_flight': 0},
                        'last_answer': secret, 'api_key': secret}
            return {'queue_running': [[1, 'id', {'prompt': secret}]], 'queue_pending': []}
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(monitor, 'local_json', side_effect=probe), \
                patch.object(monitor, 'owned_memory', return_value={}):
            active, warnings = monitor.active_status(Path(folder), config, registry)
        self.assertEqual(active['state'], 'running')
        self.assertEqual(active['runningJobs'], 1)
        self.assertIsNone(active['taskId'])
        self.assertNotIn(secret, json.dumps(active))

    def test_task_guidance_unknown_specs_never_borrow_hardware_as_minimum(self):
        with tempfile.TemporaryDirectory() as folder:
            tasks = monitor.task_guidance(Path(folder), Path(folder), {})
        self.assertEqual([task['id'] for task in tasks],
                         ['swift-flash-next', 'anima', 'qwen-image-2.1', 'minimax-h3', 'lora-preparation'])
        for task in tasks:
            self.assertIsNone(task['requirements']['memoryBytes'])
            self.assertIsNone(task['requirements']['gpuMemoryBytes'])
            self.assertIsNone(task['testedOn'])

    def test_cached_snapshot_returns_copy_with_original_measurement_time(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(monitor, 'cpu_memory', return_value=({'percent': 1}, {}, [])), \
                patch.object(monitor, 'gpu_telemetry', return_value=([], [])) as gpu, \
                patch.object(monitor, 'disk_telemetry', return_value=([], [])), \
                patch.object(monitor, 'active_status', return_value=({}, [])), \
                patch.object(monitor, 'task_guidance', return_value=[]):
            root = Path(folder)
            first = monitor.snapshot(root, root)
            first['cpu']['percent'] = 999
            second = monitor.snapshot(root, root)
            self.assertEqual(second['cpu']['percent'], 1)
            self.assertEqual(first['timestamp'], second['timestamp'])
            self.assertEqual(gpu.call_count, 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
