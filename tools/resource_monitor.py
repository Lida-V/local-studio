"""Read-only, bounded PC telemetry and honest local task resource guidance.

No process enumeration, model scanning, credentials, or window titles.
No prompt/conversation fields are returned or stored in telemetry. Comfy queue
responses contain workflows; this reader retains only their job counts.
Missing measurements are null, never zero. The full GPU usage belongs to the PC,
not to a selected task. Known weight sizes are storage, not RAM requirements.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import csv
import ctypes
import io
import json
import math
import ntpath
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    import psutil
except ImportError:
    psutil = None

PSUTIL_ERROR = psutil.Error if psutil is not None else RuntimeError

MIB = 2 ** 20
GIB = 2 ** 30
NETWORK_TIMEOUT = 0.8
MAX_JSON_BYTES = 256 * 1024
_cache = {}
_cache_lock = threading.Lock()


def number(value, minimum=0, maximum=None):
    """Reject booleans, unavailable strings, infinities and impossible ranges."""
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result) or result < minimum or (maximum is not None and result > maximum):
        return None
    return result


def count(value):
    value = number(value)
    return int(value) if value is not None and value.is_integer() else None


def bounded_json(path):
    with Path(path).open('rb') as stream:
        data = stream.read(MAX_JSON_BYTES + 1)
    if len(data) > MAX_JSON_BYTES:
        raise ValueError('Metadata exceeds the bounded read size.')
    return json.loads(data.decode('utf-8-sig'))


def metadata(path, fallback=None):
    try:
        result = bounded_json(path)
        return result if isinstance(result, dict) else (fallback or {})
    except (OSError, ValueError):
        return fallback or {}


def object_field(value, key):
    child = value.get(key) if isinstance(value, dict) else None
    return child if isinstance(child, dict) else {}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Telemetry does not follow HTTP redirects.')


def local_json(url, timeout=NETWORK_TIMEOUT):
    """Only GET fixed loopback service metadata, without proxies or credentials."""
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ('/v1/status', '/health', '/queue')):
        raise ValueError('Telemetry URL must be a fixed loopback metadata endpoint.')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    deadline = time.monotonic() + timeout
    request = urllib.request.Request(url, method='GET', headers={'Accept': 'application/json'})
    with opener.open(request, timeout=timeout) as response:
        data = bytearray()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Telemetry response exceeded its deadline.')
            # Bound both the complete response and each socket read. Local HTTP
            # servers close their JSON responses; no event streams are accepted.
            sock = getattr(getattr(getattr(response, 'fp', None), 'raw', None), '_sock', None)
            if sock is not None:
                sock.settimeout(remaining)
            chunk = response.read1(min(8192, MAX_JSON_BYTES + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > MAX_JSON_BYTES:
                raise ValueError('Telemetry response exceeds its bounded read size.')
    result = json.loads(data.decode('utf-8-sig'))
    if not isinstance(result, dict):
        raise ValueError('Telemetry response must be an object.')
    return result


def cpu_memory():
    cpu = {'percent': None, 'logicalCores': os.cpu_count()}
    memory = dict.fromkeys(('totalBytes', 'usedBytes', 'availableBytes', 'percent'))
    warnings = []
    if psutil is None:
        return cpu, memory, ['CPU/RAM: 計測ライブラリが利用できません。']
    try:
        cpu['percent'] = number(psutil.cpu_percent(interval=0.08), maximum=100)
        cpu['logicalCores'] = count(psutil.cpu_count(logical=True))
    except (OSError, RuntimeError, ValueError, PSUTIL_ERROR):
        warnings.append('CPU: 使用率を取得できません。')
    try:
        info = psutil.virtual_memory()
        total = count(info.total)
        available = count(info.available)
        if total and available is not None and available <= total:
            # available accounts for reclaimable cache; used+available=total is
            # consistent across operating systems for this dashboard.
            memory.update(totalBytes=total, availableBytes=available,
                          usedBytes=total - available,
                          percent=round((total - available) * 100 / total, 1))
        else:
            warnings.append('RAM: 計測値が範囲外です。')
    except (OSError, RuntimeError, ValueError, AttributeError, PSUTIL_ERROR):
        warnings.append('RAM: 使用量を取得できません。')
    return cpu, memory, warnings


def native_program_files():
    """One Windows known-folder lookup; no registry/env/installation scanning."""
    if os.name != 'nt':
        return None
    try:
        shell = ctypes.WinDLL('shell32', use_last_error=True)
        lookup = shell.SHGetFolderPathW
        lookup.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p,
                           ctypes.c_ulong, ctypes.c_wchar_p]
        lookup.restype = ctypes.c_long
        buffer = ctypes.create_unicode_buffer(260)
        # CSIDL_PROGRAM_FILES, current folder. No folder creation flag.
        if lookup(None, 0x26, None, 0, buffer) != 0:
            return None
        folder = buffer.value
        drive, tail = ntpath.splitdrive(folder)
        if (not ntpath.isabs(folder) or not drive or not tail.strip('\\/')
                or '..' in re.split(r'[\\/]', folder)):
            return None
        return folder
    except (OSError, AttributeError, ValueError):
        return None


def gpu_environment():
    """Local child env copy; supplement only one Windows standard variable."""
    env = os.environ.copy()
    if os.name == 'nt':
        key = next((key for key in env if key.upper() == 'PROGRAMFILES'), None)
        if key is None or not env[key]:
            folder = native_program_files()
            if folder:
                # MCP's minimal environment omits this variable. NVML needs it
                # on some Windows hosts; the monitor must not mutate its parent
                # environment or load other settings/credentials to restore it.
                env[key or 'PROGRAMFILES'] = folder
    return env


def gpu_telemetry():
    executable = shutil.which('nvidia-smi')
    if not executable:
        return [], ['GPU: NVIDIA計測ツールが見つかりません（非NVIDIAも未対応）。']
    fields = 'name,utilization.gpu,memory.total,memory.used,memory.free,temperature.gpu'
    try:
        response = subprocess.run([executable, '--query-gpu=' + fields,
                                   '--format=csv,noheader,nounits'],
                                  stdin=subprocess.DEVNULL, capture_output=True,
                                  timeout=NETWORK_TIMEOUT, check=True,
                                  env=gpu_environment(),
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if len(response.stdout) > 32768:
            return [], ['GPU: 計測応答が大きすぎます。']
        result = []
        for row in csv.reader(io.StringIO(response.stdout.decode('utf-8', 'replace'))):
            if len(row) != 6:
                continue
            name, util, total, used, free, temperature = (item.strip() for item in row)
            sizes = [count(item) for item in (total, used, free)]
            if sizes[0] is not None and any(v is not None and v > sizes[0] for v in sizes[1:]):
                sizes = [sizes[0], None, None]
            result.append({'name': name[:160], 'utilizationPercent': number(util, maximum=100),
                           'memoryTotalBytes': sizes[0] * MIB if sizes[0] is not None else None,
                           'memoryUsedBytes': sizes[1] * MIB if sizes[1] is not None else None,
                           'memoryFreeBytes': sizes[2] * MIB if sizes[2] is not None else None,
                           'temperatureC': number(temperature, maximum=150)})
        return result, ([] if result else ['GPU: 有効な計測値がありません。'])
    except subprocess.TimeoutExpired:
        return [], ['GPU: 計測が時間内に完了しませんでした。']
    except (OSError, subprocess.CalledProcessError, ValueError):
        return [], ['GPU: 使用率を取得できません。']


def disk_telemetry(root, support):
    """Known runtime/source/project volumes only; no drive enumeration."""
    paths = [Path(root), Path(support)]
    project = metadata(Path(root) / 'data/project-workspace.json').get('path')
    if (isinstance(project, str) and Path(project).is_absolute()
            and not project.startswith(('\\\\', '//'))):
        paths.append(Path(project))
    seen, result, warnings = set(), [], []
    for path in paths:
        try:
            path = path.resolve()
            while not path.exists() and path.parent != path:
                path = path.parent
            volume = path.anchor if os.name == 'nt' else str(path.stat().st_dev)
            if volume.casefold() in seen:
                continue
            seen.add(volume.casefold())
            usage = shutil.disk_usage(path)
            total, used, free = (count(v) for v in usage)
            if not total or used is None or free is None or used > total or free > total:
                raise ValueError('Invalid disk usage.')
            result.append({'label': path.anchor.rstrip('\\/') or '/',
                           'totalBytes': total, 'usedBytes': used, 'freeBytes': free,
                           'percent': round(used * 100 / total, 1)})
        except (OSError, ValueError):
            warnings.append('DISK: 対象ボリュームの空き容量を取得できません。')
    return result, warnings


def same_path(left, right):
    return str(Path(left).resolve()).casefold() == str(Path(right).resolve()).casefold()


def owned_memory(root):
    """Inspect only nonce-owned exact PIDs; deny stale/reused identities."""
    result = {'memoryBytes': None, 'gpuMemoryBytes': None, 'processCount': None,
              'basis': '会話エンジンの所有PID・実exe・開始時刻を照合したRSS合計。共有ページを含み、最低必要RAMではありません。'}
    if psutil is None:
        return result
    root = Path(root).resolve()
    identity = metadata(root / 'runtime/server.json')
    token = identity.get('launchToken')
    if identity.get('backend') != 'strata' or not isinstance(token, str) or not re.fullmatch('[a-f0-9]{32}', token):
        return result
    state_path = root / 'runtime' / ('strata-process-' + token + '.json')
    try:
        if not same_path(identity.get('processStatePath', ''), state_path):
            return result
        state = bounded_json(state_path)
        if (state.get('launchToken') != token or state.get('jobContained') is not True
                or state.get('parentPid') != identity.get('pid')
                or state.get('backend') != 'strata'):
            return result
        children = state.get('children')
        if not isinstance(children, list) or len(children) > 16:
            return result
        # Check the owner too: a stale process-state file must not be trusted
        # simply because its children once belonged to this nonce.
        entries = [identity, state['server'], *children]
        total, seen = 0, set()
        for entry in entries:
            pid = count(entry.get('pid'))
            ticks = count(entry.get('startUtcTicks'))
            executable = entry.get('executable')
            if not pid or ticks is None or not isinstance(executable, str) or not Path(executable).is_absolute():
                return result
            if pid in seen:
                return result
            process = psutil.Process(pid)
            expected_created = (ticks - 621355968000000000) / 10_000_000
            if (not process.is_running() or abs(process.create_time() - expected_created) > 0.02
                    or not same_path(process.exe(), executable)):
                return result
            # psutil exposes the actual image, never argv[0] or a window title.
            rss = count(process.memory_info().rss)
            if rss is None:
                return result
            total += rss
            seen.add(pid)
        result.update(memoryBytes=total, processCount=len(seen))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, psutil.Error):
        pass
    return result


def safe_relative(root, relative):
    if not isinstance(relative, str) or not relative:
        raise ValueError('Missing relative artifact path.')
    path = Path(root) / relative.replace('\\', '/')
    root = Path(root).resolve()
    path = path.resolve()
    if path == root or root not in path.parents:
        raise ValueError('Artifact path is outside its root.')
    return path


def tested_hardware(config):
    hardware = object_field(object_field(config, 'observed'), 'hardware')
    if not isinstance(hardware, dict) or not hardware.get('gpu'):
        return None
    vram, ram = number(hardware.get('vramMiB')), number(hardware.get('ramGiB'))
    return {'gpuLabel': str(hardware['gpu'])[:160],
            'vramBytes': int(vram * MIB) if vram is not None else None,
            'ramBytes': int(ram * GIB) if ram is not None else None}


def requirements(**values):
    return dict(memoryBytes=None, gpuMemoryBytes=None, additionalDiskBytes=None,
                modelStorageBytes=None, contextTokens=None, vramReserveBytes=None) | values


def task_guidance(root, support, config):
    root, support = Path(root), Path(support)
    tested = tested_hardware(config)
    tasks = []
    inference = object_field(config, 'inference')
    profiles = metadata(support / 'config/model-profiles.json').get('profiles', [])
    active_path = inference.get('modelPath', '')
    current = None
    for profile in profiles if isinstance(profiles, list) else []:
        try:
            if same_path(safe_relative(root, profile['model']['path']), active_path):
                current = profile
                break
        except (ValueError, KeyError, TypeError, OSError):
            continue
    if current:
        artifacts = [object_field(current, 'model'), object_field(current, 'mmproj')]
        extra = current.get('additionalArtifacts')
        artifacts += [a for a in (extra if isinstance(extra, list) else [])
                      if isinstance(a, dict) and a.get('key') == 'shard2']
        sizes = [count(a.get('size')) for a in artifacts]
        storage = sum(sizes) if all(v is not None for v in sizes) else None
        req = requirements()
        req['modelStorageBytes'] = storage
        req['contextTokens'] = count(inference.get('contextSize'))
        strata_path = object_field(config, 'strata').get('serverConfigPath')
        engine = metadata(strata_path) if isinstance(strata_path, str) else {}
        args = engine.get('args', [])
        args = args if isinstance(args, list) else []
        try:
            reserve = number(args[args.index('--vram-reserve-mib') + 1])
            req['vramReserveBytes'] = int(reserve * MIB) if reserve is not None else None
        except (ValueError, IndexError, TypeError):
            pass
        tasks.append({'id': current.get('id', 'swift-flash-next'), 'label': current.get('label', '会話モデル'),
                      'kind': 'chat', 'requirements': req, 'testedOn': tested, 'configured': None,
                      'basis': ['config/model-profiles.json の会話重み・画像投影・分割重みの配布サイズ。',
                                'config/support-config.json と実engine設定の文脈長・VRAM予約。'],
                      'notes': ['重み保存容量はRAM使用量ではなく、pack/MTP/生成物を含みません。',
                                '最低RAM/VRAMは未測定。現在の使用量は会話エンジン実測RAMとPC全体のVRAMで確認します。',
                                '文脈長・画像入力で使用量が変わります。VRAM予約は必要VRAMではなく他の画面等に残す余裕です。']})
    else:
        tasks.append({'id': 'swift-flash-next', 'label': '会話・画像理解', 'kind': 'chat',
                      'requirements': requirements(), 'testedOn': None, 'configured': None,
                      'basis': ['現在の会話モデルを設定から特定できません。'],
                      'notes': ['モデルの導入・設定を確認後に必要量を評価してください。']})
    registry = metadata(support / 'config/media-models.json')
    for key, label, kind in [('anima', 'Anima', 'image'), ('qwen-image-2.1', 'Qwen Image 2.1', 'image'),
                             ('minimax-h3', 'MiniMax H3', 'video')]:
        media = object_field(registry, key)
        workflow_name = media.get('workflow', '')
        try:
            workflow = metadata(safe_relative(support / 'config', workflow_name))
        except ValueError:
            workflow = {}
        node = object_field(object_field(workflow, str(media.get('dimensions', ''))), 'inputs')
        configured = {'width': count(node.get('width')), 'height': count(node.get('height')),
                      'frames': count(node.get('length')), 'batchSize': count(node.get('batch_size'))}
        req = requirements()
        sizes = []
        loaders = media.get('loaders')
        for loader in (loaders[:16] if isinstance(loaders, list) else []):
            try:
                node_id, field = loader
                filename = workflow[str(node_id)]['inputs'][field]
                category = {'unet_name': 'diffusion_models', 'clip_name': 'text_encoders', 'vae_name': 'vae'}[field]
                candidates = [safe_relative(root.parent / folder / 'models' / category, filename)
                              for folder in ('ComfyUI', 'ComfyUI-core')]
                file = next((p for p in candidates if p.is_file()), None)
                sizes.append(file.stat().st_size if file else None)
            except (OSError, ValueError, KeyError, TypeError, StopIteration):
                sizes.append(None)
        if sizes and all(size is not None for size in sizes):
            req['modelStorageBytes'] = sum(sizes)
        tasks.append({'id': key, 'label': label, 'kind': kind, 'requirements': req,
                      'testedOn': tested if key in registry else None, 'configured': configured,
                      'basis': ['config/media-models.json と生成workflowの既定サイズ・既知モデルファイルのstat。',
                                '生成の動作確認記録（必要メモリのピークは未測定）。'],
                      'notes': ['会話モデルを一時解放してComfyUIとGPUを交代します。',
                                '最低RAM/VRAMと出力の追加容量は未測定。解像度・枚数・尺で変わります。',
                                '動作確認サイズ: ' + ('608×352・56フレーム（2026-09-25）' if kind == 'video' else '512×512・1枚（2026-09-25）') + '。既定サイズでの保証ではありません。']})
    tasks.append({'id': 'lora-preparation', 'label': 'LoRA学習の準備', 'kind': 'preparation',
                  'requirements': requirements(), 'testedOn': None, 'configured': None,
                  'basis': ['training_routes.py は素材フォルダと設定例の準備のみ。実学習は未検証。'],
                  'notes': ['準備のみではモデルをロードしません。素材整理にCPU・RAM・保存容量を使います。',
                            '実学習のRAM/VRAMはモデル・トレーナー・rank・解像度・文脈長を決めてから確認します。',
                            '生成用GGUFの動作確認PCを学習要件として扱いません。']})
    return tasks


def active_status(root, config, registry):
    inference_config = object_field(config, 'inference')
    registry = registry if isinstance(registry, dict) else {}
    result = {'taskId': None, 'modelId': None, 'modelLabel': None, 'backend': inference_config.get('backend'),
              'modelLoaded': None, 'state': 'unknown', 'runningJobs': None, 'queuedJobs': None,
              'inferenceRequests': None, 'pendingAgentJobs': None, 'usage': owned_memory(root)}
    warnings = []
    inference = object_field(config, 'target').get('defaultUrl', '')
    media_urls = sorted({registry[key].get('url') for key in ('anima', 'qwen-image-2.1', 'minimax-h3')
                         if isinstance(registry.get(key), dict) and isinstance(registry[key].get('url'), str)})
    requests = [('inference', str(inference).rstrip('/') + '/v1/status')]
    requests += [('comfy', url.rstrip('/') + '/queue') for url in media_urls]

    def probe(item):
        kind, url = item
        try:
            value = local_json(url)
            return (kind, value, None) if isinstance(value, dict) else (kind, None, kind)
        except (OSError, ValueError):
            return kind, None, kind

    with ThreadPoolExecutor(max_workers=4) as pool:
        probes = list(pool.map(probe, requests))
    media_running, media_queued, successful_media = 0, 0, 0
    for kind, data, error in probes:
        if error:
            warnings.append(('会話API' if kind == 'inference' else 'ComfyUI') + ': 実行状態を取得できません（停止・未起動・時間切れ等）。')
            continue
        if kind == 'inference':
            loaded = data.get('loaded')
            result['modelLoaded'] = loaded if isinstance(loaded, bool) else None
            activity = data.get('activity')
            inflight = count(activity.get('in_flight')) if isinstance(activity, dict) else None
            result['inferenceRequests'] = inflight
            if loaded is True:
                model = data.get('model')
                result['modelId'] = model[:160] if isinstance(model, str) else None
                result['modelLabel'] = '会話モデル'
            if inflight is not None:
                result['state'] = 'running' if inflight else 'idle'
            else:
                warnings.append('会話API: 実行件数が不明です。')
        else:
            running, queued = data.get('queue_running'), data.get('queue_pending')
            if not isinstance(running, list) or not isinstance(queued, list):
                warnings.append('ComfyUI: キュー計測値が不正です。')
                continue
            media_running += len(running)
            media_queued += len(queued)
            successful_media += 1
    if successful_media == len(media_urls) and media_urls:
        result.update(runningJobs=media_running, queuedJobs=media_queued)
    if media_running:
        result['state'] = 'running'
        # Shared Comfy ports do not identify Anima vs MiniMax. The UI's actual
        # tool phase can select a task; a busy device alone cannot.
    elif media_queued and result['state'] != 'running':
        result['state'] = 'queued'
    elif successful_media != len(media_urls) and result['state'] == 'idle':
        result['state'] = 'unknown'
    candidate = None
    if result['modelLoaded'] is True:
        active_model = inference_config.get('modelPath', '')
        catalog = metadata(Path(config.get('_support', '.')) / 'config/model-profiles.json').get('profiles', [])
        for profile in catalog if isinstance(catalog, list) else []:
            try:
                if same_path(safe_relative(root, profile['model']['path']), active_model):
                    expected = object_field(profile, 'backend').get('modelName')
                    if isinstance(expected, str) and expected != result['modelId']:
                        continue
                    candidate = profile['id']
                    label = profile.get('label')
                    result['modelLabel'] = label[:160] if isinstance(label, str) else '会話モデル'
                    break
            except (OSError, KeyError, TypeError, ValueError):
                continue
    queue = Path(root) / 'runtime/agent-queue'
    try:
        if queue.is_dir():
            # Only marker names/counts, never job request/result bodies.
            markers = 0
            for index, path in enumerate(queue.iterdir()):
                if index >= 1024:
                    warnings.append('エージェント: 待機件数が計測上限を超えています。')
                    break
                if re.fullmatch('[a-f0-9]{32}', path.name):
                    markers += 1
            else:
                result['pendingAgentJobs'] = markers
    except OSError:
        warnings.append('エージェント: 待機件数を取得できません。')
    pending = result['pendingAgentJobs']
    if pending is not None and pending > 0 and result['state'] != 'running':
        result['state'] = 'queued'
    elif pending is None and result['state'] == 'idle':
        result['state'] = 'unknown'
        warnings.append('エージェント: 待機件数が不明です。')
    if (candidate is not None and successful_media == len(media_urls)
            and not media_running and not media_queued
            and result['pendingAgentJobs'] == 0):
        # A loaded chat is a valid idle/running candidate only when no unknown
        # generation work is waiting on a shared port or the agent queue.
        result['taskId'] = candidate
    return result, list(dict.fromkeys(warnings))


def snapshot(root, support, *, cache_seconds=2):
    """JSON-ready dashboard contract. Root/support are explicit for portability."""
    root, support = Path(root).resolve(), Path(support).resolve()
    key = str(root), str(support)
    with _cache_lock:
        previous = _cache.get(key)
        if previous and time.monotonic() - previous[0] < cache_seconds:
            return json.loads(json.dumps(previous[1]))
        config = metadata(support / 'config/support-config.json')
        # Internal context only; it is never included in the returned JSON.
        config['_support'] = str(support)
        with ThreadPoolExecutor(max_workers=2) as pool:
            gpu = pool.submit(gpu_telemetry)
            activity = pool.submit(active_status, root, config, metadata(support / 'config/media-models.json'))
            cpu, memory, warnings = cpu_memory()
            disks, disk_warnings = disk_telemetry(root, support)
            gpus, gpu_warnings = gpu.result()
            active, activity_warnings = activity.result()
        warnings.extend(disk_warnings + gpu_warnings + activity_warnings)
        if not config.get('inference'):
            warnings.append('現在のモデル設定を取得できません。')
        result = {'schemaVersion': 1, 'timestamp': datetime.now(timezone.utc).isoformat(),
                  'cpu': cpu, 'memory': memory, 'disks': disks, 'gpus': gpus,
                  'tasks': task_guidance(root, support, config), 'active': active,
                  'warnings': list(dict.fromkeys(warnings))}
        _cache[key] = time.monotonic(), result
        return json.loads(json.dumps(result))
