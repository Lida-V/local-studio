"""Offline publication and syntax checks. Does not start models or access user data."""
import ast
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
excluded = {'.git','__pycache__','node_modules','.venv'}
count = 0
for path in ROOT.rglob('*'):
    if not path.is_file() or any(p in excluded for p in path.relative_to(ROOT).parts): continue
    relative = path.relative_to(ROOT).as_posix()
    if relative in {'config/support-config.json','.mcp.json','.codex/config.toml'}: continue
    assert path.suffix.lower() not in {'.db','.gguf','.safetensors','.exe','.zip','.log'}, relative
    text = path.read_text(encoding='utf-8-sig')
    if path.suffix == '.py': ast.parse(text, filename=relative)
    if path.suffix == '.json': json.loads(text)
    assert not re.search(r'[A-Z]:[/\\]Users[/\\][^/\\\s]+', text), relative
    assert not re.search(r'gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9]{24,}|BEGIN (?:RSA |OPENSSH )?PRIVATE KEY', text), relative
    count += 1
config = json.loads((ROOT/'config/support-config.example.json').read_text(encoding='utf-8'))
assert config['target']['root'] == 'C:\\AI\\LocalLLM'
assert config['chatApp']['host'] == config['inference']['host'] == '127.0.0.1'
manifest=json.loads((ROOT/'config/download-manifest.json').read_text(encoding='utf-8'))
for item in manifest['files']:
    assert re.fullmatch('[0-9a-f]{64}',item['sha256']) and item['size'] > 0
    assert item['url'].startswith(('https://github.com/','https://huggingface.co/'))
print(json.dumps({'source_files_checked':count,'syntax_and_json':'passed','local_profile_paths':'absent','credential_patterns':'absent','manifest':'passed'}))
