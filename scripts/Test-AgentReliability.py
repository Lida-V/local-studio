"""File exploration, context bounds and cancellation regression fixtures."""
import asyncio
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / 'tools'))
import local_studio as studio
import workspace_files as files
import webui_runtime as runtime
from webui_queue_patch import OLD, NEW, STALE, patch_bundle


class FileInspection(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name, value in [('ROOT', self.root), ('WORK', self.root / 'project')]:
            mock = patch.object(studio, name, value); mock.start(); self.addCleanup(mock.stop)
        self.project = studio.current_project()
        self.tool = studio.Tools()

    async def test_large_japanese_file_pages_and_long_line(self):
        content = '長い一行の資料です。' * 12000 + '\n末尾の合言葉\n'
        (self.project / 'large.txt').write_text(content, encoding='utf8')
        result = await self.tool.read_workspace_file('large.txt')
        self.assertLessEqual(len(result['content']), 2400)
        self.assertTrue(result['truncated'])
        next_page = await self.tool.read_workspace_file('large.txt', result['next_line'], start_column=result['next_column'])
        self.assertEqual(result['content'] + next_page['content'], content[:4800])
        tail = await self.tool.read_workspace_file('large.txt', 2)
        self.assertIn('合言葉', tail['content'])
        self.assertFalse(tail['truncated'])

    async def test_encodings_binary_missing_and_outside(self):
        for encoding in ('utf8', 'utf-16', 'cp932'):
            path = self.project / (encoding + '.txt')
            path.write_bytes('日本語テスト'.encode(encoding))
            self.assertEqual((await self.tool.read_workspace_file(str(path)))['content'], '日本語テスト')
        (self.project / 'binary.bin').write_bytes(b'\0\x80data')
        for path in ['missing.txt', 'binary.bin', '../outside', '.', 'C:/Windows/system.ini', 'C:relative.txt', 'file:stream']:
            result = await self.tool.read_workspace_file(path)
            self.assertIn('error', result)
            self.assertIn('next_step', result)

    async def test_directory_pagination_no_silent_cutoff(self):
        for i in range(170): (self.project / f'{i:03d}.txt').touch()
        names, offset = [], 0
        while offset is not None:
            result = await self.tool.list_workspace(offset=offset)
            names += [e['name'] for e in result['entries']]
            offset = result['next_offset']
        self.assertEqual(len(names), 170)
        self.assertEqual(len(set(names)), 170)

    async def test_search_nested_content_and_ignored_folders(self):
        (self.project / '資料').mkdir()
        (self.project / '資料/a.txt').write_text('先頭\n合言葉は青い鳥\n', encoding='cp932')
        (self.project / 'node_modules').mkdir()
        (self.project / 'node_modules/hidden.txt').write_text('合言葉', encoding='utf8')
        found = await self.tool.search_workspace('*.txt')
        self.assertEqual([m['path'] for m in found['matches']], ['資料/a.txt'])
        result = await self.tool.search_workspace('合言葉', content=True)
        self.assertEqual(result['matches'][0]['line'], 2)
        self.assertEqual(len(result['matches']), 1)
        self.assertGreater(result['skipped'], 0)

    async def test_search_pagination(self):
        for i in range(70): (self.project / f'{i:03d}.txt').touch()
        results, offset = [], 0
        while offset is not None:
            page = await self.tool.search_workspace('txt', offset=offset)
            results += [m['path'] for m in page['matches']]
            offset = page['next_offset']
        self.assertEqual(len(set(results)), 70)
        self.assertEqual(len(results), 70)


class Lifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_waits_for_real_thread_completion(self):
        ready, release = threading.Event(), threading.Event()
        run = {'phase': 'tool'}
        token = runtime.current_run.set(run)
        try:
            def work():
                ready.set(); release.wait(3); return 'finished'
            task = asyncio.create_task(runtime.background_operation(work))
            await asyncio.to_thread(ready.wait, 2)
            task.cancel()
            await asyncio.sleep(.02)
            self.assertFalse(task.done())
            self.assertEqual(run['phase'], 'stopping')
            release.set()
            with self.assertRaises(asyncio.CancelledError): await task
        finally:
            release.set(); runtime.current_run.reset(token)

    def test_japanese_estimate_and_user_instructions_preserved(self):
        self.assertGreaterEqual(runtime.estimate_tokens('日本語' * 500), 1500)
        user = {'role': 'user', 'content': '変更しない指示' * 300}
        system = {'role': 'system', 'content': 'important'}
        messages = [system, user]
        for i in range(5):
            messages += [{'role': 'assistant', 'tool_calls': [{'id': str(i), 'function': {'name': 'read_workspace_file'}}]},
                         {'role': 'tool', 'tool_call_id': str(i), 'content': '資料' * 3000}]
        result = runtime.bound_file_history({'messages': messages})['messages']
        self.assertEqual(result[:2], [system, user])
        self.assertEqual(messages[3]['content'], '資料' * 3000)  # Source history untouched.
        self.assertLess(sum(len(m.get('content','')) for m in result[2:-1]), 2000)
        self.assertEqual(result[-1], messages[-1])

    def test_queue_patch_guards_build(self):
        self.assertIn(NEW, patch_bundle(OLD + ';' + STALE))
        with self.assertRaises(RuntimeError): patch_bundle('different upstream build')


if __name__ == '__main__': unittest.main()
