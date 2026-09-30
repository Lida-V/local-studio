"""Update only the toolkit and Qwen prompt-skill instruction; preserve live preset settings."""
import json
import copy
from pathlib import Path
import sys
from datetime import datetime
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from prompt_skills import install_instruction, guide


def main():
    config = json.loads((ROOT / 'config/support-config.json').read_text(encoding='utf-8-sig'))
    base = config['chatApp']['url'].rstrip('/')
    model_id = config['chatApp']['modelId']
    token = None

    def api(path, value=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        request = urllib.request.Request(base + path, headers=headers,
            data=json.dumps(value).encode() if value is not None else None)
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)

    if not guide('core')['ok']:
        raise RuntimeError('Install/link the prompt skill before deploying the toolkit.')
    api('/health')
    token = api('/api/v1/auths/signin', {'email': 'admin@localhost', 'password': 'admin'})['token']
    if api('/api/tasks').get('tasks') or api('/api/local-studio/activity').get('active_count'):
        raise RuntimeError('Local Studio is busy; preserve active work and deploy after it finishes.')
    tool = api('/api/v1/tools/id/local_studio')
    models = api('/api/v1/models/all')
    items = models.get('items', models.get('data', [])) if isinstance(models, dict) else models
    model = next(m for m in items if m['id'] == model_id)
    # Keep the entire previous objects privately for recovery, never print their contents.
    backup = Path(config['target']['root']) / 'runtime/maintenance-backups' / ('prompt-skill-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    backup.mkdir(parents=True)
    (backup / 'before.json').write_text(json.dumps({'tool': tool, 'model': model}, ensure_ascii=False, indent=2), encoding='utf-8')
    tool_form = {k: tool[k] for k in ('id', 'name', 'meta', 'access_grants') if k in tool}
    tool_form['content'] = (ROOT / 'tools/local_studio.py').read_text(encoding='utf-8')
    api('/api/v1/tools/id/local_studio/update', tool_form)
    model_form = copy.deepcopy({k: model[k] for k in ('id', 'base_model_id', 'name', 'params', 'meta', 'is_active', 'access_grants') if k in model})
    previous_system = model_form['params'].get('system', '')
    model_form['params']['system'] = install_instruction(previous_system)
    api('/api/v1/models/model/update?id=' + model_id, model_form)
    live_tool = api('/api/v1/tools/id/local_studio')
    live_models = api('/api/v1/models/all')
    live_items = live_models.get('items', live_models.get('data', [])) if isinstance(live_models, dict) else live_models
    live_model = next(m for m in live_items if m['id'] == model_id)
    assert live_tool['content'] == tool_form['content']
    assert live_model['params']['system'] == model_form['params']['system']
    assert {k: v for k, v in live_model['params'].items() if k != 'system'} == {k: v for k, v in model['params'].items() if k != 'system'}
    assert live_model['meta'] == model['meta']
    print(json.dumps({'tool': 'local_studio', 'model': model_id, 'guide_installed': True,
                      'other_preset_settings_preserved': True, 'backup_created': True,
                      'system_chars': len(live_model['params']['system'])}, ensure_ascii=False))


if __name__ == '__main__':
    main()
