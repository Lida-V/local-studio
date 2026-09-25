"""Local ComfyUI routing. The caller provides configuration and process helpers."""
import json
import math
import msvcrt
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import contextmanager


def models(studio):
    return json.loads((studio.SUPPORT / 'config/media-models.json').read_text(encoding='utf-8-sig'))


def validate(studio, model, prompt, width, height, seed, seconds):
    registry = models(studio)
    if model not in registry:
        raise ValueError('Unknown model: ' + model)
    if not prompt.strip() or len(prompt) > 12000 or not 0 <= seed <= 2**63 - 1:
        raise ValueError('Prompt: 1–12000 characters; seed: 0–2^63-1.')
    video = registry[model]['kind'] == 'video'
    lo, hi, grid, pixels = (256, 1024, 32, 786432) if video else (512, 1536, 64, 1572864)
    if any(n < lo or n > hi or n % grid for n in (width, height)) or width * height > pixels:
        raise ValueError(f'Dimensions: {lo}–{hi}, multiples of {grid}, <= {pixels} pixels.')
    if not 1 <= seconds <= 5:
        raise ValueError('Video duration must be 1–5 seconds.')
    return registry[model]


def queues(studio):
    result = {}
    # 8190 is an optional local experimental ComfyUI that shares the same GPU.
    urls = {m['url'] for m in models(studio).values()} | {'http://127.0.0.1:8190'}
    for url in sorted(urls):
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost'):
            raise ValueError('Media servers must use loopback HTTP.')
        try:
            result[url] = studio.api(url + '/queue', timeout=3)
        except urllib.error.URLError as error:
            # A timeout or malformed response is unknown, not evidence of an idle GPU.
            if not isinstance(error.reason, ConnectionRefusedError) and getattr(error.reason, 'winerror', None) != 10061:
                raise RuntimeError('Cannot determine media queue state: ' + url) from error
    return result


def assert_idle(studio):
    active = queues(studio)
    if any(q['queue_running'] or q['queue_pending'] for q in active.values()):
        raise RuntimeError('ComfyUI is busy. Existing jobs were left untouched; retry when idle.')
    return active


def free_idle(studio):
    for url in assert_idle(studio):
        studio.api(url + '/free', {'unload_models': True, 'free_memory': True})


@contextmanager
def gpu_lease(studio):
    if not studio.GENERATION_LOCK.acquire(blocking=False):
        raise RuntimeError('Another Local Studio GPU task is running.')
    lease = None
    locked = False
    try:
        (studio.ROOT / 'runtime').mkdir(parents=True, exist_ok=True)
        lease = (studio.ROOT / 'runtime/studio-generation.lock').open('a+b')
        try:
            lease.seek(0)
            msvcrt.locking(lease.fileno(), msvcrt.LK_NBLCK, 1)
            locked = True
        except OSError:
            raise RuntimeError('Another Local Studio GPU task is running.')
        yield
    finally:
        if lease:
            if locked:
                lease.seek(0)
                msvcrt.locking(lease.fileno(), msvcrt.LK_UNLCK, 1)
            lease.close()
        studio.GENERATION_LOCK.release()


def generate(studio, prompt, width, height, seed, return_path=False, model='anima', seconds=2):
    entry = validate(studio, model, prompt, width, height, seed, seconds)
    url = entry['url']
    with gpu_lease(studio):
        stopped = submitted = job_done = False
        try:
            active = assert_idle(studio)
            if url not in active:
                if studio.COMFY_SUPPORT is None:
                    raise RuntimeError('Start the configured ComfyUI server: ' + url)
                studio.script(studio.COMFY_SUPPORT / 'scripts' / entry['startScript'])
                deadline = time.monotonic() + 180
                while time.monotonic() < deadline:
                    try:
                        studio.api(url + '/queue', timeout=3)
                        break
                    except urllib.error.URLError:
                        time.sleep(2)
                else:
                    raise RuntimeError('ComfyUI startup did not become ready: ' + url)
            assert_idle(studio)
            graph = json.loads((studio.SUPPORT / 'config' / entry['workflow']).read_text(encoding='utf-8-sig'))
            for node_id, field in entry['loaders']:
                node = graph[node_id]
                info = studio.api(url + '/object_info/' + node['class_type'])
                choices = info.get(node['class_type'], {}).get('input', {}).get('required', {}).get(field, [[]])[0]
                if node['inputs'][field] not in choices:
                    raise RuntimeError('Required model unavailable: ' + node['inputs'][field])
            node, field = entry['prompt']
            graph[node]['inputs'][field] = prompt
            graph[entry['dimensions']]['inputs'].update(width=width, height=height)
            node, field = entry['seed']
            graph[node]['inputs'][field] = seed
            if model == 'qwen-image-2.1':
                graph['4']['inputs']['resolution'] = max(width, height)
            if entry['kind'] == 'video':
                # H3 audiovisual timing requires 17*n+5 pixel frames.
                graph['8']['inputs']['length'] = 17 * math.ceil((seconds * 24 - 5) / 17) + 5
            run_id = time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6]
            graph[entry['output']]['inputs']['filename_prefix'] = 'LocalStudio/' + model + '/' + run_id
            destination = studio.WORK / ('videos' if entry['kind'] == 'video' else 'images') / run_id
            destination.mkdir(parents=True)
            (destination / 'workflow.json').write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding='utf-8')
            studio.script(studio.SUPPORT / 'scripts/Stop-LocalLLM.ps1')
            stopped = True
            free_idle(studio)
            response = studio.api(url + '/prompt', {'prompt': graph, 'client_id': 'local-studio-' + run_id})
            prompt_id = response['prompt_id']
            submitted = True
            (destination / 'job.json').write_text(json.dumps(response), encoding='utf-8')
            deadline = time.monotonic() + 1800
            while time.monotonic() < deadline:
                history = studio.api(url + '/history/' + prompt_id)
                if prompt_id in history:
                    job_done = True
                    record = history[prompt_id]
                    (destination / 'history.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
                    if record.get('status', {}).get('status_str') == 'error':
                        raise RuntimeError('ComfyUI generation failed; see ' + str(destination / 'history.json'))
                    output = record.get('outputs', {}).get(entry['output'], {})
                    files = output.get('images') or output.get('videos') or output.get('gifs') or []
                    if not files:
                        raise RuntimeError('No saved media returned by ComfyUI.')
                    item = {k: files[0][k] for k in ('filename','subfolder','type') if k in files[0]}
                    with urllib.request.urlopen(url + '/view?' + urllib.parse.urlencode(item), timeout=120) as response:
                        data = response.read()
                    target = destination / ('video.mp4' if entry['kind'] == 'video' else 'image.png')
                    target.write_bytes(data)
                    return str(target) if return_path else data
                time.sleep(1)
            raise TimeoutError('Generation remains active. Check ComfyUI before restarting Qwen: ' + prompt_id)
        finally:
            if stopped and (not submitted or job_done):
                free_idle(studio)
                time.sleep(2)
                studio.script(studio.SUPPORT / 'scripts/Start-LocalLLM.ps1')
