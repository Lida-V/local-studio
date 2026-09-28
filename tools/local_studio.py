"""
title: Local Studio
author: Local Studio contributors
description: Anima / Qwen Image 2.1 / MiniMax H3, workspace files and confirmed PowerShell commands.
version: 1.3.0
required_open_webui_version: 0.11.4
"""
import asyncio
import os
import base64
import json
from pathlib import Path
import shutil
import subprocess
import threading
import msvcrt
import time
import uuid
import urllib.request
import urllib.parse

ROOT = Path('C:/AI/LocalLLM')
WORK = ROOT / 'workspace'
SUPPORT = Path(os.environ.get('LOCAL_STUDIO_SOURCE', str(Path(__file__).resolve().parents[1])))
COMFY_SUPPORT = Path(os.environ['LOCAL_STUDIO_COMFY_SUPPORT']) if os.environ.get('LOCAL_STUDIO_COMFY_SUPPORT') else None
PWSH = shutil.which('pwsh') or 'pwsh'
COMFY = 'http://127.0.0.1:8188'
GENERATION_LOCK = threading.Lock()


def api(url, payload=None, timeout=15):
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
        return json.loads(body) if body else {}


def script(path):
    # Background Windows descendants can keep PIPE handles open after pwsh exits.
    # Use a real log file so waiting is tied to the launcher process, not pipe EOF.
    log_path = ROOT / 'logs' / ('studio-' + path.stem + '-' + uuid.uuid4().hex[:8] + '.log')
    with log_path.open('w', encoding='utf-8') as log:
        result = subprocess.run([PWSH, '-NoProfile', '-File', str(path), *(['-NoBrowser'] if path.name == 'Start-ComfyUI.ps1' else [])],
                                stdout=log, stderr=log, stdin=subprocess.DEVNULL, timeout=240,
                                creationflags=subprocess.CREATE_NO_WINDOW)
    output = log_path.read_text(encoding='utf-8', errors='replace')
    if result.returncode:
        raise RuntimeError(output[-3000:])
    return output


def project_module():
    import sys
    from types import SimpleNamespace
    if str(SUPPORT / 'tools') not in sys.path:
        sys.path.insert(0, str(SUPPORT / 'tools'))
    import project_workspace
    return project_workspace, SimpleNamespace(**globals())


def current_project():
    module, context = project_module()
    return module.current(context)


def workspace_path(relative):
    module, context = project_module()
    return module.resolve(context, relative)


def media_runtime():
    import sys
    from types import SimpleNamespace
    if str(SUPPORT / 'tools') not in sys.path:
        sys.path.insert(0, str(SUPPORT / 'tools'))
    import media_runtime as runtime
    context = SimpleNamespace(**globals())
    context.WORK = current_project()
    projects, _ = project_module()
    context.workspace_path = lambda relative: projects.resolve(context, relative, context.WORK)
    return runtime, context


def generate(prompt, width, height, seed, return_path=False, model='anima', seconds=2):
    runtime, context = media_runtime()
    return runtime.generate(context, prompt, width, height, seed, return_path, model, seconds)


async def background(function, *args, **kwargs):
    project_module()
    from webui_runtime import background_operation
    return await background_operation(function, *args, **kwargs)


class Tools:
    async def current_project(self) -> dict:
        """Read the user-selected project folder. Call before file work; relative paths use this folder for all chats. Selecting a different folder is a user action in the desktop Project menu."""
        module, context = project_module()
        return module.info(context)

    async def training_guide(self) -> list:
        """Show LoRA preparation routes for Anima, Qwen Image 2.1, MiniMax H3 and Qwen3.8. Does not install, download or train."""
        _, context = media_runtime()
        import training_routes
        return training_routes.profiles(context)

    async def prepare_training(self, model: str, name: str) -> dict:
        """Create a LoRA preparation folder and dataset examples only. NO training or download. model: anima/qwen-image-2.1/minimax-h3/qwen3.8; name: ASCII letters/digits/-/_ up to 64."""
        _, context = media_runtime()
        import training_routes
        return training_routes.prepare(context, model, name)

    async def studio_status(self) -> dict:
        """Read local model routes, ComfyUI queues and workspace. Does not start anything."""
        def read():
            runtime, context = media_runtime()
            active = runtime.queues(context)
            return {'models': runtime.models(context), 'queues': active, 'workspace': str(context.WORK)}
        return await background(read)

    async def create_qwen_image(self, prompt: str, width: int = 1024, height: int = 1024, seed: int = 42, __event_emitter__=None) -> str:
        """Create a NEW image with Qwen Image 2.1 (not Qwen3.8). Does not edit an existing image. Dimensions 512–1536 by 64, <=1.5 MP. Qwen chat resumes after generation."""
        data = await background(generate, prompt, width, height, seed, False, 'qwen-image-2.1')
        image_url = 'data:image/png;base64,' + base64.b64encode(data).decode()
        if __event_emitter__:
            await __event_emitter__({'type': 'files', 'data': {'files': [{'type': 'image', 'name': 'Qwen-Image-2.1.png', 'url': image_url}]}})
        return image_url

    async def create_minimax_video(self, prompt: str, width: int = 608, height: int = 352, seconds: int = 2, seed: int = 42, __event_emitter__=None) -> dict:
        """Generate a NEW local MiniMax H3 video with sound. English prompt including motion and sound. 1–5 seconds, dimensions 256–1024 by 32, <=0.75 MP. Rounded to H3 frame geometry. Qwen resumes after generation. Include the returned video_embed marker verbatim in your final reply to display the video."""
        if __event_emitter__:
            await __event_emitter__({'type': 'status', 'data': {'description': 'MiniMax H3で音声付き動画を生成中', 'done': False}})
        try:
            path = await background(generate, prompt, width, height, seed, True, 'minimax-h3', seconds)
            def upload():
                import httpx
                base = 'http://127.0.0.1:18081'
                with httpx.Client(timeout=120) as client:
                    login = client.post(base + '/api/v1/auths/signin', json={'email': 'admin@localhost', 'password': 'admin'})
                    login.raise_for_status()
                    with Path(path).open('rb') as stream:
                        response = client.post(base + '/api/v1/files/?process=false', headers={'Authorization': 'Bearer ' + login.json()['token']}, files={'file': ('MiniMax-H3.mp4', stream, 'video/mp4')})
                    response.raise_for_status()
                    return response.json()
            file = await background(upload)
            url = '/api/v1/files/' + file['id'] + '/content'
            # A block HTML token is required by Open WebUI 0.11.4's video renderer.
            embed = '<div><video>' + url + '</video></div>'
            if __event_emitter__:
                await __event_emitter__({'type': 'files', 'data': {'files': [{'type': 'file', 'id': file['id'], 'name': 'MiniMax-H3.mp4', 'url': url, 'content_type': 'video/mp4'}]}})
                await __event_emitter__({'type': 'message', 'data': {'content': '\n\n' + embed + '\n\n'}})
            return {'video_path': path, 'download_url': url, 'video_embed': embed, 'model': 'MiniMax H3'}
        finally:
            if __event_emitter__:
                await __event_emitter__({'type': 'status', 'data': {'description': '動画生成処理を終了しました', 'done': True}})

    async def create_anima_image(self, prompt: str, width: int = 1024, height: int = 1024, seed: int = 42, __event_emitter__=None) -> str:
        """Generate one image locally with ComfyUI Anima. Temporarily pauses Qwen, then restores chat. Returns the actual image. Use detailed English image prompts. Does not edit an existing image.
        :param prompt: Full positive prompt describing the requested image.
        :param width: Image width, 512 to 1536, multiple of 64.
        :param height: Image height, 512 to 1536, multiple of 64.
        :param seed: Reproducible nonnegative integer seed.
        """
        if not prompt.strip() or len(prompt) > 12000:
            raise ValueError('Prompt must contain 1–12000 characters.')
        if any(n < 512 or n > 1536 or n % 64 for n in [width, height]) or width * height > 1572864:
            raise ValueError('Use multiples of 64 between 512 and 1536; at most 1.5 megapixels.')
        if seed < 0 or seed > 2**63 - 1:
            raise ValueError('Seed outside supported range.')
        if __event_emitter__:
            await __event_emitter__({'type': 'status', 'data': {'description': 'ComfyUIで画像生成中。Qwenは生成後に復帰します。', 'done': False}})
        try:
            data = await background(generate, prompt, width, height, seed)
        finally:
            if __event_emitter__:
                await __event_emitter__({'type': 'status', 'data': {'description': '画像生成処理を終了しました。', 'done': True}})
        image_url = 'data:image/png;base64,' + base64.b64encode(data).decode()
        if __event_emitter__:
            await __event_emitter__({'type': 'files', 'data': {'files': [
                {'type': 'image', 'name': 'Anima.png', 'url': image_url}
            ]}})
        return image_url

    async def open_workspace_image(self, path: str, __event_emitter__=None) -> str:
        """Open an existing PNG/JPEG/WebP image from the local workspace, display it in chat and inspect its actual content. Does not generate or edit images.
        :param path: Relative image file path inside the user-selected project folder.
        """
        p = workspace_path(path)
        if p.stat().st_size > 15000000:
            raise ValueError('Image exceeds 15 MB.')
        from PIL import Image
        with Image.open(p) as source:
            mime = {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'WEBP': 'image/webp'}.get(source.format)
            if not mime:
                raise ValueError('Use PNG, JPEG or WebP.')
            source.verify()
        image_url = 'data:' + mime + ';base64,' + base64.b64encode(p.read_bytes()).decode()
        if __event_emitter__:
            await __event_emitter__({'type': 'files', 'data': {'files': [{'type': 'image', 'name': p.name, 'url': image_url}]}})
        return image_url

    async def list_workspace(self, directory: str = '.', offset: int = 0) -> dict:
        """List a project directory, 60 entries per page. Continue with next_offset. Call current_project first."""
        project_module()
        import workspace_files
        from types import SimpleNamespace
        return await background(workspace_files.inspect, SimpleNamespace(**globals()), workspace_files.listing, directory, offset=offset)

    async def search_workspace(self, query: str, directory: str = '.', content: bool = False, offset: int = 0) -> dict:
        """Find project filenames (substring or glob). content=true searches literal text and returns first matching line per file. Skips caches/links/binary files; continue partial searches with next_offset."""
        project_module()
        import workspace_files
        from types import SimpleNamespace
        return await background(workspace_files.inspect, SimpleNamespace(**globals()), workspace_files.search, directory, query=query, content=content, offset=offset)

    async def read_workspace_file(self, path: str, start_line: int = 1, max_lines: int = 60, start_column: int = 0) -> dict:
        """Read a text excerpt (UTF-8/UTF-16/CP932), max 2400 characters. For truncated output continue with next_line AND next_column. Supports files up to 16 MB. Paths relative to current_project."""
        project_module()
        import workspace_files
        from types import SimpleNamespace
        return await background(workspace_files.inspect, SimpleNamespace(**globals()), workspace_files.read, path, start_line=start_line, max_lines=max_lines, start_column=start_column)

    async def write_workspace_file(self, path: str, content: str) -> dict:
        """Create or edit a UTF-8 text file in the user-selected project folder. Existing text is backed up before replacement.
        :param path: Relative file path in the workspace.
        :param content: Exact complete UTF-8 text to save.
        """
        p = workspace_path(path)
        if len(content) > 100000:
            raise ValueError('Content too large.')
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists():
            if p.stat().st_size > 100000:
                raise ValueError('Existing file too large to replace.')
            backups = ROOT / 'data/file-backups'
            backups.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, backups / (uuid.uuid4().hex + '-' + p.name))
        p.write_text(content, encoding='utf-8')
        return {'saved': str(p), 'characters': len(content)}

    async def run_powershell(self, command: str, __event_call__=None) -> dict:
        """Run a PowerShell command after the user approves the exact command in the chat confirmation dialog. Runs with Windows user permissions; working directory is NOT a sandbox. Timeout 60 seconds. Do not use to start long-running processes.
        :param command: Exact PowerShell code to show the user and execute.
        """
        if not __event_call__:
            return {'executed': False, 'reason': 'Interactive confirmation is required.'}
        project = current_project()
        from webui_runtime import phase
        phase('approval', 'run_powershell')
        approved = await __event_call__({'type': 'confirmation', 'data': {
            'title': 'PowerShellコマンドの実行',
            'message': 'Windowsユーザー権限で実行します。作業フォルダ: ' + str(project) + '（操作範囲はその外にも及びます）\n\n' + command,
        }})
        if approved is not True:
            return {'executed': False, 'reason': 'Cancelled by user.'}
        phase('tool', 'run_powershell')
        def run():
            with subprocess.Popen([PWSH, '-NoProfile', '-NonInteractive', '-Command', command], cwd=project,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='utf-8', errors='replace',
                                  creationflags=subprocess.CREATE_NO_WINDOW) as process:
                try:
                    out, err = process.communicate(timeout=60)
                except subprocess.TimeoutExpired:
                    import psutil
                    parent = psutil.Process(process.pid)
                    for child in parent.children(recursive=True):
                        try: child.kill()
                        except psutil.NoSuchProcess: pass
                    process.kill()
                    out, err = process.communicate()
                    return {'executed': True, 'timed_out': True, 'stdout': out[-12000:], 'stderr': err[-4000:]}
                return {'executed': True, 'exit_code': process.returncode, 'stdout': out[-12000:], 'stderr': err[-4000:]}
        return await background(run)
