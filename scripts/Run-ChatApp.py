"""Local-only Open WebUI launcher. Configuration and data stay under C:/AI."""
import json
import os
from pathlib import Path
import secrets
import sys
import msvcrt

ROOT = Path('C:/AI/LocalLLM')
data = ROOT / 'data/open-webui'
data.mkdir(parents=True, exist_ok=True)
instance_lock = (ROOT / 'runtime/chatapp.lock').open('a+b')
instance_lock.seek(0)
try:
    msvcrt.locking(instance_lock.fileno(), msvcrt.LK_NBLCK, 1)
except OSError:
    raise SystemExit('Chat app launcher is already active.')
os.chdir(data)
settings = {
    'DATA_DIR': str(data), 'WEBUI_AUTH': 'False',
    'OPENAI_API_BASE_URL': 'http://127.0.0.1:18080/v1', 'OPENAI_API_KEY': 'local-only',
    'ENABLE_OLLAMA_API': 'False', 'OFFLINE_MODE': 'True', 'HF_HUB_OFFLINE': '1',
    'HF_HOME': str(ROOT / 'cache/huggingface'), 'SCARF_NO_ANALYTICS': 'true',
    'ANONYMIZED_TELEMETRY': 'False', 'DO_NOT_TRACK': 'True',
    'BYPASS_EMBEDDING_AND_RETRIEVAL': 'True', 'RAG_EMBEDDING_ENGINE': 'openai',
    'RAG_OPENAI_API_BASE_URL': 'http://127.0.0.1:18080/v1',
    'ENABLE_TITLE_GENERATION': 'False', 'ENABLE_FOLLOW_UP_GENERATION': 'False',
    'ENABLE_TAGS_GENERATION': 'False', 'ENABLE_AUTOCOMPLETE_GENERATION': 'False',
    'ENABLE_EVALUATION_ARENA_MODELS': 'False', 'DEFAULT_LOCALE': 'ja-JP',
    'DEFAULT_MODELS': 'local-studio-agent', 'CORS_ALLOW_ORIGIN': 'http://127.0.0.1:18081',
    'DEFAULT_MODEL_PARAMS': json.dumps({'function_calling': 'native', 'max_tokens': 2048}),
    'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8',
}
os.environ.update(settings)
os.environ['LOCAL_STUDIO_SOURCE'] = str(Path(__file__).resolve().parents[1])
secret = data / '.webui_secret_key'
if not secret.exists():
    secret.write_text(secrets.token_urlsafe(48), encoding='utf-8')
os.environ['WEBUI_SECRET_KEY'] = secret.read_text(encoding='utf-8')
# Optional ffmpeg is discovered from the user-configured PATH.
import psutil
p = psutil.Process()
(ROOT / 'runtime/chatapp.json').write_text(json.dumps({
    'pid': p.pid, 'created': p.create_time(), 'exe': p.exe(),
    'script': str(Path(__file__).resolve()), 'url': 'http://127.0.0.1:18081',
}), encoding='utf-8')
from open_webui import serve
serve(host='127.0.0.1', port=18081)
