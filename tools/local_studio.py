"""
title: Local Studio
author: Local Studio contributors
description: ComfyUI Anima generation, workspace files and confirmed PowerShell commands.
version: 1.0.0
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


def workspace_path(relative):
    WORK.mkdir(parents=True, exist_ok=True)
    p = (WORK / relative).resolve()
    if not p.is_relative_to(WORK.resolve()) or ':' in str(relative) or Path(relative).is_absolute():
        raise ValueError('Use a relative path inside C:/AI/LocalLLM/workspace; outside paths and links are rejected.')
    return p


def generate(prompt, width, height, seed, return_path=False):
    if not GENERATION_LOCK.acquire(blocking=False):
        raise RuntimeError('Another Local Studio generation is running.')
    lease = (ROOT / 'runtime/studio-generation.lock').open('a+b')
    try:
        lease.seek(0)
        msvcrt.locking(lease.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        lease.close()
        GENERATION_LOCK.release()
        raise RuntimeError('Another Local Studio generation is running.')
    stopped = False
    submitted = False
    job_done = False
    try:
        try:
            queue = api(COMFY + '/queue', timeout=3)
        except OSError:
            if COMFY_SUPPORT is None:
                raise RuntimeError('Start ComfyUI on 127.0.0.1:8188 before generating an image.')
            script(COMFY_SUPPORT / 'scripts/Start-ComfyUI.ps1')
            queue = api(COMFY + '/queue')
        if queue['queue_running'] or queue['queue_pending']:
            raise RuntimeError('ComfyUI is busy. Existing jobs were left untouched; retry when idle.')
        workflow = json.loads((SUPPORT / 'config/anima-chat-workflow.json').read_text(encoding='utf-8-sig'))
        for node_id, field in [('1', 'unet_name'), ('2', 'clip_name'), ('7', 'vae_name')]:
            node = workflow[node_id]
            info = api(COMFY + '/object_info/' + node['class_type'])
            if node['inputs'][field] not in info[node['class_type']]['input']['required'][field][0]:
                raise RuntimeError('Required model unavailable: ' + node['inputs'][field])
        workflow['3']['inputs']['text'] = prompt
        workflow['5']['inputs'].update(width=width, height=height)
        workflow['6']['inputs']['seed'] = seed
        run_id = time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6]
        workflow['9']['inputs']['filename_prefix'] = 'LocalLLM/' + run_id
        destination = WORK / 'images' / run_id
        destination.mkdir(parents=True)
        (destination / 'workflow.json').write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding='utf-8')
        script(SUPPORT / 'scripts/Stop-LocalLLM.ps1')
        stopped = True
        result = api(COMFY + '/prompt', {'prompt': workflow, 'client_id': 'local-llm-' + run_id})
        prompt_id = result['prompt_id']
        submitted = True
        (destination / 'job.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            history = api(COMFY + '/history/' + prompt_id)
            if prompt_id in history:
                job_done = True
                record = history[prompt_id]
                (destination / 'history.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
                if record.get('status', {}).get('status_str') == 'error':
                    raise RuntimeError('ComfyUI generation failed; see ' + str(destination / 'history.json'))
                images = record.get('outputs', {}).get('9', {}).get('images', [])
                if not images:
                    raise RuntimeError('No saved image returned by ComfyUI.')
                item = images[0]
                with urllib.request.urlopen(COMFY + '/view?' + urllib.parse.urlencode(item), timeout=30) as response:
                    data = response.read()
                (destination / 'image.png').write_bytes(data)
                return str(destination / 'image.png') if return_path else data
            time.sleep(1)
        raise TimeoutError('Generation still running. Do not start Qwen until ComfyUI is idle. Job: ' + prompt_id)
    finally:
        try:
            if stopped:
                queue = api(COMFY + '/queue')
                if (not submitted or job_done) and not queue['queue_running'] and not queue['queue_pending']:
                    api(COMFY + '/free', {'unload_models': True, 'free_memory': True})
                    time.sleep(2)
                    script(SUPPORT / 'scripts/Start-LocalLLM.ps1')
        finally:
            lease.seek(0)
            msvcrt.locking(lease.fileno(), msvcrt.LK_UNLCK, 1)
            lease.close()
            GENERATION_LOCK.release()


class Tools:
    async def studio_status(self) -> dict:
        """Read ComfyUI connection/queue status and local workspace location. Never starts or stops anything."""
        def read():
            try:
                queue = api(COMFY + '/queue', timeout=3)
                return {'comfyui': 'online', 'running': len(queue['queue_running']), 'pending': len(queue['queue_pending']), 'workspace': str(WORK)}
            except OSError:
                return {'comfyui': 'offline', 'workspace': str(WORK), 'can_start_for_generation': True}
        return await asyncio.to_thread(read)

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
            data = await asyncio.to_thread(generate, prompt, width, height, seed)
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
        :param path: Relative image file path under C:/AI/LocalLLM/workspace.
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

    async def list_workspace(self, directory: str = '.') -> list:
        """List files in a directory under C:/AI/LocalLLM/workspace. Paths are relative to that workspace."""
        p = workspace_path(directory)
        return [{'name': x.name, 'directory': x.is_dir()} for x in sorted(p.iterdir())][:150]

    async def read_workspace_file(self, path: str) -> str:
        """Read a UTF-8 text file under the local workspace. Maximum 24000 characters."""
        p = workspace_path(path)
        if p.stat().st_size > 100000:
            raise ValueError('File too large; use a smaller excerpt.')
        return p.read_text(encoding='utf-8-sig')[:24000]

    async def write_workspace_file(self, path: str, content: str) -> dict:
        """Create or edit a UTF-8 text file in C:/AI/LocalLLM/workspace. Existing text is backed up before replacement.
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
        approved = await __event_call__({'type': 'confirmation', 'data': {
            'title': 'PowerShellコマンドの実行',
            'message': 'Windowsユーザー権限で実行します。作業フォルダはC:\\AI\\LocalLLM\\workspaceですが、操作範囲はその外にも及びます。\n\n' + command,
        }})
        if approved is not True:
            return {'executed': False, 'reason': 'Cancelled by user.'}
        def run():
            WORK.mkdir(parents=True, exist_ok=True)
            with subprocess.Popen([PWSH, '-NoProfile', '-NonInteractive', '-Command', command], cwd=WORK,
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
        return await asyncio.to_thread(run)
