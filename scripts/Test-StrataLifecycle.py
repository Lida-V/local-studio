"""Offline ownership/readiness regressions: tiny temporary processes, no models or servers."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

SCRIPTS = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('strata_launcher', SCRIPTS / 'Run-StrataServer.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)
PWSH = shutil.which('pwsh')


class Containment(unittest.TestCase):
    def test_arguments_preserve_loopback_and_do_not_open_browser(self):
        self.assertEqual(launcher.server_arguments(Path('strata.json'), '127.0.0.1', 18080),
                         ['--engine', 'strata', '--config', 'strata.json', '--host', '127.0.0.1', '--port', '18080'])
        for host, port in [('0.0.0.0', 18080), ('127.0.0.1', 0)]:
            with self.assertRaises(ValueError):
                launcher.server_arguments(Path('strata.json'), host, port)

    def test_child_containment_failure_ends_only_the_created_child(self):
        recorder = launcher.ProcessRecorder.__new__(launcher.ProcessRecorder)
        recorder.job = SimpleNamespace(owns=lambda _: False)
        child = Mock(pid=125, _handle=126)
        child.poll.return_value = None
        with self.assertRaisesRegex(RuntimeError, 'outside the owned'):
            recorder.contain(child)
        child.kill.assert_called_once_with()
        child.wait.assert_called_once_with(timeout=10)

    def test_recorder_contains_exact_server_and_child_identities(self):
        with tempfile.TemporaryDirectory(prefix='strata-ownership-') as temp:
            state_path = Path(temp) / 'process.json'
            job = SimpleNamespace(kernel=SimpleNamespace(GetCurrentProcess=lambda: 1), owns=lambda _: True,
                                  identity=lambda handle, pid: {'pid': pid, 'startUtcTicks': handle + 100, 'executable': 'fixture.exe'})
            recorder = launcher.ProcessRecorder(job, state_path, 'a' * 32, Path('source'), Path('strata.json'))
            child = Mock(pid=125, _handle=126)
            recorder.contain(child)
            state = json.loads(state_path.read_text(encoding='utf-8'))
            self.assertTrue(state['jobContained'])
            self.assertEqual(state['launchToken'], 'a' * 32)
            self.assertEqual(state['server']['pid'], os.getpid())
            self.assertEqual(state['children'], [{'pid': 125, 'startUtcTicks': 226, 'executable': 'fixture.exe'}])
            child.kill.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'Windows Job Objects only')
    def test_abrupt_interpreter_exit_ends_its_descendants(self):
        # Use the base interpreter so killing the test parent cannot merely kill
        # a venv redirector. The production wrapper records this distinction.
        python = getattr(sys, '_base_executable', None) or sys.executable
        code = textwrap.dedent(f'''
            import importlib.util, subprocess, sys, time
            spec = importlib.util.spec_from_file_location('launcher', {str(SCRIPTS / 'Run-StrataServer.py')!r})
            mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
            job = mod.WindowsJob()
            child_code = "import subprocess, sys, time; g=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); print(g.pid, flush=True); time.sleep(30)"
            child = subprocess.Popen([sys.executable, '-c', child_code], stdout=subprocess.PIPE, text=True)
            print(child.pid, child.stdout.readline().strip(), flush=True)
            time.sleep(30)
        ''')
        parent = subprocess.Popen([python, '-u', '-c', code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        child = grandchild = None
        try:
            line = parent.stdout.readline().strip()
            if not line:
                self.fail(parent.stderr.read())
            child, grandchild = [int(value) for value in line.split()]
            job_probe = launcher.ctypes.WinDLL('kernel32', use_last_error=True)
            job_probe.OpenProcess.restype = launcher.wintypes.HANDLE
            job_probe.OpenProcess.argtypes = (launcher.wintypes.DWORD, launcher.wintypes.BOOL, launcher.wintypes.DWORD)
            job_probe.CloseHandle.argtypes = (launcher.wintypes.HANDLE,)
            def running(pid):
                handle = job_probe.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE
                if not handle:
                    return False
                try:
                    return job_probe.WaitForSingleObject(launcher.wintypes.HANDLE(handle), 0) == 258
                finally:
                    job_probe.CloseHandle(handle)
            self.assertTrue(running(child) and running(grandchild))
            parent.kill(); parent.wait(timeout=10)
            deadline = time.monotonic() + 10
            while (running(child) or running(grandchild)) and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertFalse(running(child), 'Contained child outlived its interpreter.')
            self.assertFalse(running(grandchild), 'Contained grandchild outlived its interpreter.')
        finally:
            if parent.poll() is None:
                parent.kill()
            parent.wait(timeout=10)
            parent.stdout.close(); parent.stderr.close()


@unittest.skipUnless(PWSH, 'PowerShell 7 required')
class PowerShellLifecycle(unittest.TestCase):
    def run_fixture(self, entry, health_loaded=True, vision=True, reused_server=False, busy=False, wrong_token=False,
                    launcher_alive=True, unload_unavailable=False, legacy=False):
        with tempfile.TemporaryDirectory(prefix='strata-lifecycle-') as temp:
            root = Path(temp)
            (root / 'runtime').mkdir()
            token = 'a' * 32
            cfg = {'target': {'root': str(root), 'executable': 'fixture-launcher.exe', 'defaultUrl': 'http://127.0.0.1:18080'},
                   'inference': {'host': '127.0.0.1', 'port': 18080, 'alias': 'stable-alias'},
                   'strata': {'sourceRoot': str(root / 'source'), 'serverConfigPath': str(root / 'strata.json')}}
            if not legacy:
                cfg['inference']['backend'] = 'strata'
            config_path = root / 'fixture.json'
            config_path.write_text(json.dumps(cfg), encoding='utf-8')
            process_path = root / f'runtime/strata-process-{token}.json'
            state = {'pid': 101, 'startUtcTicks': 111, 'executable': 'fixture-launcher.exe'}
            if not legacy:
                state.update(backend='strata', launchToken=token, processStatePath=str(process_path))
            (root / 'runtime/server.json').write_text(json.dumps(state), encoding='utf-8')
            process_path.write_text(json.dumps({'launchToken': ('b' * 32 if wrong_token else token), 'jobContained': True,
                'sourceRoot': cfg['strata']['sourceRoot'], 'serverConfigPath': cfg['strata']['serverConfigPath'], 'parentPid': 101,
                'server': {'pid': 102, 'startUtcTicks': 222, 'executable': 'fixture-interpreter.exe'},
                'children': [{'pid': 103, 'startUtcTicks': 333, 'executable': 'fixture-engine.exe'}]}), encoding='utf-8')
            bool_ps = lambda value: '$true' if value else '$false'
            harness = textwrap.dedent('''
                $ErrorActionPreference='Stop'
                $script:stopped=$false
                function Start-Sleep {param($Seconds,$Milliseconds)}
                function Get-Process {
                    param($Id,$ErrorAction)
                    if($script:stopped){return $null}
                    $pidValue=[int]$Id
                    if($pidValue -eq 101 -and -not LAUNCHER_ALIVE){return $null}
                    $ticks=if($pidValue -eq 101){111}elseif($pidValue -eq 102){SERVER_TICKS}else{333}
                    $path=if($pidValue -eq 101){'fixture-launcher.exe'}elseif($pidValue -eq 102){'fixture-interpreter.exe'}else{'fixture-engine.exe'}
                    $p=[pscustomobject]@{Id=$pidValue;Path=$path;StartTime=[datetime]::new($ticks,[DateTimeKind]::Utc)}
                    $p | Add-Member ScriptMethod WaitForExit {param($Timeout) return $true}
                    return $p
                }
                function Invoke-RestMethod {
                    param($Uri,$TimeoutSec,$Method,$ContentType,$Body)
                    if($Uri.EndsWith('/health')){return @{status='ok';loaded=HEALTH_LOADED}}
                    if($Uri.EndsWith('/v1/models')){return @{data=@(@{id='stable-alias'})}}
                    if($Uri.EndsWith('/props')){return @{modalities=@{vision=VISION};is_sleeping=$false}}
                    if($Uri.EndsWith('/v1/unload')){
                        Write-Host 'UNLOAD_CALLED'
                        if(UNLOAD_UNAVAILABLE){throw 'fixture HTTP not ready'}
                        return @{status=BUSY_STATUS;loaded=$false}
                    }
                    throw 'Unexpected API'
                }
                function Stop-Process {param($Id) Write-Host "STOP_CALLED:$Id"; $script:stopped=$true}
                & ENTRY -ConfigPath CONFIG TIMEOUT
            ''').replace('LAUNCHER_ALIVE', bool_ps(launcher_alive)).replace('SERVER_TICKS', '999' if reused_server else '222')
            harness = harness.replace('HEALTH_LOADED', bool_ps(health_loaded)).replace('VISION', bool_ps(vision))
            harness = harness.replace('UNLOAD_UNAVAILABLE', bool_ps(unload_unavailable)).replace('BUSY_STATUS', "'busy'" if busy else "'unloaded'")
            quote_ps = lambda value: "'" + str(value).replace("'", "''") + "'"
            harness = harness.replace('ENTRY', quote_ps(SCRIPTS / entry)).replace('CONFIG', quote_ps(config_path))
            harness = harness.replace('TIMEOUT', '-TimeoutSeconds 0' if entry.startswith('Start-') else '')
            path = root / 'harness.ps1'
            path.write_text(harness, encoding='utf-8')
            result = subprocess.run([PWSH, '-NoProfile', '-File', str(path)], capture_output=True, text=True,
                                    encoding='utf-8', errors='replace', timeout=20)
            result.stop_record = (root / 'runtime/stop-request.json').exists()
            return result

    def test_start_requires_loaded_model_vision_and_owned_interpreter(self):
        ready = self.run_fixture('Start-LocalLLM.ps1')
        self.assertEqual(ready.returncode, 0, ready.stderr)
        self.assertIn('Ready:', ready.stdout)
        for kwargs in ({'health_loaded': False}, {'vision': False}, {'reused_server': True}, {'wrong_token': True}):
            with self.subTest(kwargs=kwargs):
                failed = self.run_fixture('Start-LocalLLM.ps1', **kwargs)
                self.assertNotEqual(failed.returncode, 0)
                self.assertNotIn('Ready:', failed.stdout)

    def test_stop_unloads_before_stopping_real_interpreter_and_tracks_job_children(self):
        result = self.run_fixture('Stop-LocalLLM.ps1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(result.stdout.index('UNLOAD_CALLED'), result.stdout.index('STOP_CALLED:102'))
        self.assertNotIn('STOP_CALLED:103', result.stdout)
        self.assertTrue(result.stop_record)

    def test_busy_unload_does_not_stop_or_create_stop_request(self):
        result = self.run_fixture('Stop-LocalLLM.ps1', busy=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Strata is busy', result.stderr)
        self.assertNotIn('STOP_CALLED', result.stdout)
        self.assertFalse(result.stop_record)

    def test_reused_interpreter_or_wrong_token_never_unloads_or_stops(self):
        for kwargs in ({'reused_server': True}, {'wrong_token': True}):
            with self.subTest(kwargs=kwargs):
                result = self.run_fixture('Stop-LocalLLM.ps1', **kwargs)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('UNLOAD_CALLED', result.stdout)
                self.assertNotIn('STOP_CALLED', result.stdout)
                self.assertFalse(result.stop_record)

    def test_failed_startup_is_stoppable_for_rollback(self):
        result = self.run_fixture('Stop-LocalLLM.ps1', unload_unavailable=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('owned Windows Job Object', result.stdout)
        self.assertIn('STOP_CALLED:102', result.stdout)

    def test_orphaned_redirector_still_stops_owned_interpreter(self):
        result = self.run_fixture('Stop-LocalLLM.ps1', launcher_alive=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('STOP_CALLED:102', result.stdout)

    def test_absent_backend_preserves_llama_start_and_stop(self):
        ready = self.run_fixture('Start-LocalLLM.ps1', legacy=True)
        self.assertEqual(ready.returncode, 0, ready.stderr)
        stopped = self.run_fixture('Stop-LocalLLM.ps1', legacy=True)
        self.assertEqual(stopped.returncode, 0, stopped.stderr)
        self.assertIn('STOP_CALLED:101', stopped.stdout)
        self.assertNotIn('UNLOAD_CALLED', stopped.stdout)


if __name__ == '__main__':
    unittest.main()
