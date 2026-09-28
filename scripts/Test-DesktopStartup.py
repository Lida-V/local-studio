"""Startup regressions without starting models, servers or desktop windows."""
import importlib.util
import io
import json
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('desktop_launcher', SOURCE / 'scripts/Run-DesktopApp.py')
desktop = importlib.util.module_from_spec(spec)
original_read_text = Path.read_text
def fixture_config(path, *args, **kwargs):
    if path == SOURCE / 'config/support-config.json':
        return json.dumps({'target': {'root': 'C:/AI/LocalLLM'}})
    return original_read_text(path, *args, **kwargs)
with patch.object(Path, 'read_text', fixture_config):
    spec.loader.exec_module(desktop)


class DesktopStartup(unittest.TestCase):
    def test_launcher_success_still_requires_live_health(self):
        with patch.object(desktop.subprocess, 'run', return_value=SimpleNamespace(returncode=0)):
            for payload in ({'status': True}, {'status': False}):
                with patch.object(desktop.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(payload).encode())):
                    if payload['status']:
                        desktop.ensure_backend(io.StringIO())
                    else:
                        with self.assertRaises(RuntimeError): desktop.ensure_backend(io.StringIO())
            with patch.object(desktop.urllib.request, 'urlopen', side_effect=ConnectionRefusedError):
                with self.assertRaises(RuntimeError): desktop.ensure_backend(io.StringIO())

    def test_reopen_recovers_backend_before_focus_without_clearing_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'logs').mkdir()
            for fails in (False, True):
                calls = []
                def ensure(_):
                    calls.append('backend')
                    if fails: raise RuntimeError('offline')
                with patch.object(desktop, 'ROOT', root), \
                     patch.object(desktop.msvcrt, 'locking', side_effect=OSError), \
                     patch.object(desktop, 'ensure_backend', side_effect=ensure), \
                     patch.object(desktop, 'clear_owned_cache') as cleanup, \
                     patch.object(desktop.subprocess, 'Popen', side_effect=lambda *a, **k: calls.append('focus')):
                    if fails:
                        with self.assertRaises(RuntimeError): desktop.main()
                        self.assertEqual(calls, ['backend'])
                    else:
                        desktop.main()
                        self.assertEqual(calls, ['backend', 'focus'])
                    cleanup.assert_not_called()

    def run_chat_launcher(self, generation_code, early_exit=False):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                port = listener.getsockname()[1]
            code = (SOURCE / 'scripts/Start-ChatApp.ps1').read_text(encoding='utf8')
            code = code.replace("$root='C:\\AI\\LocalLLM'", "$root='" + str(root) + "'")
            code = code.replace('18081', str(port))
            python = sys.executable
            code = code.replace('"$root\\apps\\open-webui\\.venv\\Scripts\\python.exe"', "'" + python + "'")
            (root / 'Start-ChatApp.ps1').write_text(code, encoding='utf8')
            (root / 'Start-AgentWorker.ps1').write_text('# isolated fixture', encoding='utf8')
            (root / 'Check-Generation.py').write_text(f'import sys; sys.exit({generation_code})', encoding='utf8')
            (root / 'Start-LocalLLM.ps1').write_text("Write-Output 'QWEN_CALLED'; exit 0", encoding='utf8')
            harness = '''
$ErrorActionPreference='Stop'
$script:checks=0
function Start-Sleep { param($Seconds) }
function Invoke-RestMethod {
    param($Uri, $TimeoutSec)
    $script:checks++
    if ($script:checks -eq 1 -or EARLY_EXIT) { throw 'not ready' }
    @{status=$true}
}
function Start-Process {
    param($FilePath,$ArgumentList,$WindowStyle,$WorkingDirectory,$RedirectStandardOutput,$RedirectStandardError,[switch]$PassThru)
    if (-not $PassThru -or $WindowStyle -ne 'Hidden') { throw 'Invalid launch' }
    Write-Host 'CHAT_STARTED'
    [pscustomobject]@{HasExited=EARLY_EXIT}
}
& (Join-Path $PSScriptRoot 'Start-ChatApp.ps1')
'''.replace('EARLY_EXIT', '$true' if early_exit else '$false')
            entry = root / 'harness.ps1'
            entry.write_text(harness, encoding='utf8')
            return subprocess.run([desktop.PWSH, '-NoProfile', '-File', str(entry)], capture_output=True, text=True, encoding='utf8', errors='replace', timeout=20)

    def test_media_busy_starts_chat_without_starting_qwen(self):
        result = self.run_chat_launcher(3)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('QWEN_CALLED', result.stdout)
        self.assertIn('CHAT_STARTED', result.stdout)
        self.assertIn('Chat app ready:', result.stdout)

    def test_idle_starts_qwen_and_waits_for_chat(self):
        result = self.run_chat_launcher(0)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('QWEN_CALLED', result.stdout)
        self.assertIn('Chat app ready:', result.stdout)

    def test_early_server_exit_fails_without_waiting_for_timeout(self):
        result = self.run_chat_launcher(3, early_exit=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('exited before becoming ready', result.stderr)
        self.assertNotIn('Chat app ready:', result.stdout)


if __name__ == '__main__': unittest.main()
