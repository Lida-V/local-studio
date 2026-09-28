"""Offline project routing regression checks; all writes use temporary fixtures."""
import asyncio
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / 'tools'))
import local_studio as studio
import project_workspace as projects


class Projects(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ['runtime', 'workspace', '日本語 project A', 'project B']:
            (self.root / name).mkdir()
        self.a, self.b = self.root / '日本語 project A', self.root / 'project B'
        for name, value in [('ROOT', self.root), ('WORK', self.root / 'workspace')]:
            mock = patch.object(studio, name, value); mock.start(); self.addCleanup(mock.stop)

    def test_persistent_selection_backup_and_reset(self):
        projects.select(studio, self.a)
        tool = studio.Tools()
        asyncio.run(tool.write_workspace_file('drafts/test.txt', 'before'))
        asyncio.run(tool.write_workspace_file('drafts/test.txt', 'after 日本語'))
        self.assertEqual(asyncio.run(tool.read_workspace_file('drafts/test.txt')), 'after 日本語')
        self.assertFalse((studio.WORK / 'drafts/test.txt').exists())
        self.assertEqual(next((self.root / 'data/file-backups').iterdir()).read_text(), 'before')
        saved = json.loads((self.root / 'data/project-workspace.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['path'], str(self.a))
        projects.select(studio)
        self.assertEqual(studio.current_project(), studio.WORK)
        self.assertTrue((self.a / 'drafts/test.txt').exists())

    def test_invalid_selection_and_boundary(self):
        projects.select(studio, self.a)
        for path in ['relative', self.root / 'missing', Path(self.root.anchor)]:
            with self.assertRaises((ValueError, FileNotFoundError)):
                projects.select(studio, path)
        for path in ['../project B/secret', 'C:/Windows/test.txt', 'test.txt:stream']:
            with self.assertRaises(ValueError): studio.workspace_path(path)
        # A real Windows junction must not extend the selected project's boundary.
        junction = self.a / 'link'
        # /c mklink creates only this temporary link; no deletion or moving through cmd.
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(junction), str(self.b)], check=True, capture_output=True)
        self.addCleanup(lambda: junction.rmdir() if junction.exists() else None)
        with self.assertRaises(ValueError): studio.workspace_path('link/secret')

    def test_missing_selection_never_falls_back(self):
        projects.select(studio, self.a)
        self.a.rmdir()
        with self.assertRaises(FileNotFoundError): studio.workspace_path('test.txt')
        projects.select(studio)
        self.assertEqual(studio.current_project(), studio.WORK)

    def test_media_and_training_snapshot(self):
        projects.select(studio, self.a)
        _, context = studio.media_runtime()
        projects.select(studio, self.b)
        self.assertEqual(context.WORK, self.a)
        self.assertEqual(context.workspace_path('training/sample'), self.a / 'training/sample')
        import training_routes
        prepared = training_routes.prepare(context, 'anima', 'fixture')
        self.assertTrue(Path(prepared['prepared']).is_relative_to(self.a))
        self.assertFalse(prepared['training_started'])

    def test_command_cwd_is_pinned_before_confirmation(self):
        projects.select(studio, self.a)
        async def approve(event):
            self.assertIn(str(self.a), event['data']['message'])
            projects.select(studio, self.b)
            return True
        with patch.object(studio.subprocess, 'Popen') as popen:
            child = popen.return_value.__enter__.return_value
            child.communicate.return_value = ('ok', '')
            child.returncode = 0
            asyncio.run(studio.Tools().run_powershell('Get-Location', __event_call__=approve))
            self.assertEqual(popen.call_args.kwargs['cwd'], self.a)

    def test_queued_job_keeps_submitted_project(self):
        spec = importlib.util.spec_from_file_location('studio_cli_test', SOURCE / 'scripts/Local-Studio.py')
        cli = importlib.util.module_from_spec(spec)
        original = Path.read_text
        def read(path, *args, **kwargs):
            if path == SOURCE / 'config/support-config.json' and not path.exists():
                return original(SOURCE / 'config/support-config.example.json', *args, **kwargs)
            return original(path, *args, **kwargs)
        with patch.object(Path, 'read_text', read): spec.loader.exec_module(cli)
        projects.select(studio, self.a)
        with patch.object(cli, 'daemon_running', return_value=True):
            job = cli.start_task('image', 'fixture', width=512, height=512)
        projects.select(studio, self.b)
        with patch.object(studio, 'generate', side_effect=lambda *a, **kw: str(studio.workspace_path('images/fixture.png'))):
            cli.worker(job['job_id'])
        result = cli.task_result(job['job_id'])
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(Path(result['image_path']), self.a / 'images/fixture.png')
        self.assertEqual(studio.current_project(), self.b)


if __name__ == '__main__': unittest.main()
