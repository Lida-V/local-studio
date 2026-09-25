"""Focused tests for path boundaries, backups and command confirmation gates."""
import asyncio
import importlib.util
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
import io

spec = importlib.util.spec_from_file_location('local_studio', Path(__file__).resolve().parents[1] / 'tools/local_studio.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

async def main():
    with patch.object(module.urllib.request, 'urlopen', return_value=io.BytesIO(b'')):
        assert module.api('http://127.0.0.1:8188/free', {}) == {}
    with tempfile.TemporaryDirectory(prefix='local-studio-test-') as directory:
        module.ROOT = Path(directory)
        module.WORK = module.ROOT / 'workspace'
        (module.ROOT / 'runtime').mkdir()
        tool = module.Tools()
        with patch.object(module, 'api', return_value={'queue_running': [[123]], 'queue_pending': []}), patch.object(module, 'script') as launcher:
            try:
                module.generate('test', 512, 512, 42)
                raise AssertionError('Busy queue was accepted')
            except RuntimeError as error:
                assert 'busy' in str(error)
            launcher.assert_not_called()
        for bad in ['../outside.txt', 'C:/Windows/test.txt', 'note.txt:stream', '/outside.txt']:
            try:
                module.workspace_path(bad)
                raise AssertionError('Accepted outside path: ' + bad)
            except ValueError:
                pass
        await tool.write_workspace_file('drafts/sample.md', 'old 日本語')
        await tool.write_workspace_file('drafts/sample.md', 'new 日本語')
        assert await tool.read_workspace_file('drafts/sample.md') == 'new 日本語'
        assert list((module.ROOT / 'data/file-backups').glob('*'))[0].read_text(encoding='utf-8') == 'old 日本語'
        assert not (await tool.run_powershell("Write-Output 'SHOULD_NOT_RUN'"))['executed']
        async def deny(event):
            assert event['type'] == 'confirmation'
            return False
        assert not (await tool.run_powershell("Write-Output 'SHOULD_NOT_RUN'", __event_call__=deny))['executed']
        async def accept(event):
            assert "Write-Output 'LOCAL_STUDIO_TEST'" in event['data']['message']
            return True
        result = await tool.run_powershell("Write-Output 'LOCAL_STUDIO_TEST'", __event_call__=accept)
        assert result['exit_code'] == 0 and 'LOCAL_STUDIO_TEST' in result['stdout']
        print(json.dumps({'busy_comfy_queue_untouched': 'passed', 'empty_http_response': 'passed', 'path_boundary': 'passed', 'write_read_backup': 'passed', 'command_no_ui_and_deny': 'passed', 'confirmed_command': 'passed'}))

asyncio.run(main())
