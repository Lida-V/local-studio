"""Adjust the existing Local Studio preset and compaction through guarded APIs.

Only the display name and four compaction keys change. Prompts, tools, other
parameters, retention settings, and saved conversations remain untouched.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
import urllib.parse
import urllib.request

SUPPORT = Path(__file__).resolve().parents[1]
MODEL_FIELDS = ('id', 'base_model_id', 'name', 'params', 'meta', 'is_active', 'access_grants')
COMPACTION_PREFIX = 'chat.context_compaction.'
DEFAULT_NAME = 'Local Studio · Qwen3.8 Flash Next · Strata'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, url):
        raise RuntimeError('Local API redirected; settings were not sent to the new origin.')


class LocalApi:
    def __init__(self, base):
        parsed = urllib.parse.urlsplit(base)
        if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1') or
                parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
            raise ValueError('Only loopback HTTP API roots are allowed.')
        self.base, self.token = base.rstrip('/'), None
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def __call__(self, path, value=None):
        if not isinstance(path, str) or not path.startswith('/') or path.startswith('//'):
            raise ValueError('API paths must be local absolute paths.')
        headers = {'Content-Type': 'application/json'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        request = urllib.request.Request(self.base + path, headers=headers,
            data=json.dumps(value).encode() if value is not None else None)
        with self.opener.open(request, timeout=30) as response:
            return json.load(response)


def compaction_patch(context_size, alias):
    """Leave substantial room for output, Japanese estimates, tools and images."""
    if type(context_size) is not int or not 8192 <= context_size <= 262144:
        raise ValueError('Context size must be an integer between 8192 and 262144.')
    if not isinstance(alias, str) or not alias.strip():
        raise ValueError('A model alias is required.')
    threshold = min(60000, context_size * 60000 // 131072 // 1000 * 1000)
    cap = min(90000, context_size * 90000 // 131072 // 1000 * 1000)
    if not 0 < threshold < cap < context_size:
        raise ValueError('Compaction reserves do not fit this context.')
    return {COMPACTION_PREFIX + 'enable': True, COMPACTION_PREFIX + 'token_threshold': threshold,
            COMPACTION_PREFIX + 'token_cap': cap, COMPACTION_PREFIX + 'model': alias}


def model_form(model):
    if not isinstance(model, dict) or not isinstance(model.get('params'), dict) or not isinstance(model.get('meta'), dict):
        raise ValueError('The existing model preset is missing required settings.')
    return deepcopy({key: model[key] for key in MODEL_FIELDS if key in model})


def transform(model, api_config, context_size, alias, display_name=DEFAULT_NAME):
    """Pure reviewed change, preserving every field except the display name."""
    if not isinstance(api_config, dict):
        raise ValueError('API configuration is not a JSON object.')
    if not isinstance(display_name, str) or not display_name.strip() or len(display_name) > 160:
        raise ValueError('Display name must contain 1–160 characters.')
    changed = model_form(model)
    if changed.get('base_model_id') != alias:
        raise ValueError('Existing preset does not use the configured compatibility alias.')
    patch = compaction_patch(context_size, alias)
    missing = set(patch) - set(api_config)
    if missing:
        # Config import only upserts; it cannot undo introducing an absent key.
        raise ValueError('Existing compaction configuration is incomplete; safe API-only restoration is unavailable.')
    changed['name'] = display_name
    return changed, patch, {key: deepcopy(api_config[key]) for key in patch}


def read_model(api, model_id):
    models = api('/api/v1/models/all')
    items = models.get('items', models.get('data', [])) if isinstance(models, dict) else models
    if not isinstance(items, list):
        raise RuntimeError('Model list is unavailable or malformed.')
    selected = [model for model in items if isinstance(model, dict) and model.get('id') == model_id]
    if len(selected) != 1:
        raise RuntimeError('The existing Local Studio preset was not found uniquely.')
    return selected[0]


def assert_idle(api, model_api, root, media_idle):
    queue = Path(root) / 'runtime/agent-queue'
    if queue.exists() and any(queue.iterdir()):
        raise RuntimeError('Agent work is queued or running; no chat settings changed.')
    media_idle()
    tasks, activity, gate = api('/api/tasks'), api('/api/local-studio/activity'), api('/api/local-studio/model-maintenance')
    if (not isinstance(tasks, dict) or not isinstance(tasks.get('tasks'), list) or tasks['tasks'] or
            not isinstance(activity, dict) or type(activity.get('active_count')) is not int or activity['active_count'] != 0 or
            not isinstance(gate, dict) or gate.get('admission_gate') is not True or gate.get('switching') is not True or
            type(gate.get('admitted_chats')) is not int or gate['admitted_chats'] != 0):
        raise RuntimeError('Chat activity or maintenance state is busy or unknown; no settings changed.')
    slots = model_api('/slots')
    if not isinstance(slots, list) or not slots or any(not isinstance(slot, dict) or slot.get('is_processing') is not False for slot in slots):
        raise RuntimeError('Model inference is busy or unknown; no chat settings changed.')


def verify_strata_context(model_api, context_size):
    health, props = model_api('/health'), model_api('/props')
    if (not isinstance(health, dict) or health.get('status') != 'ok' or health.get('service') != 'strata' or
            health.get('loaded') is not True or health.get('images') is not True or health.get('max_context') != context_size or
            not isinstance(props, dict) or (props.get('default_generation_settings') or {}).get('n_ctx') != context_size or
            (props.get('modalities') or {}).get('vision') is not True or props.get('is_sleeping') is not False):
        raise RuntimeError('Strata loaded context and vision do not match the requested configuration.')


def save_private(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def verify_settings(api, model_id, expected_model, expected_patch):
    live_model = model_form(read_model(api, model_id))
    live_config = api('/api/v1/configs/export')
    if live_model != expected_model:
        raise RuntimeError('Preset verification failed; preserved settings differed.')
    if not isinstance(live_config, dict) or any(live_config.get(key) != value for key, value in expected_patch.items()):
        raise RuntimeError('Compaction configuration verification failed.')


def update_settings(api, model_id, desired_model, desired_patch, before_model, before_patch, backup):
    endpoint = '/api/v1/models/model/update?id=' + urllib.parse.quote(model_id, safe='')
    model_attempted = config_attempted = False
    try:
        model_attempted = True
        api(endpoint, desired_model)
        config_attempted = True
        api('/api/v1/configs/import', {'config': desired_patch})
        verify_settings(api, model_id, desired_model, desired_patch)
    except Exception as original:
        failures = []
        if config_attempted:
            try:
                api('/api/v1/configs/import', {'config': before_patch})
            except Exception:
                failures.append('config')
        if model_attempted:
            try:
                api(endpoint, before_model)
            except Exception:
                failures.append('model')
        try:
            verify_settings(api, model_id, before_model, before_patch)
        except Exception:
            failures.append('verification')
        save_private(backup / 'result.json', {'ok': False, 'rollback_verified': not failures, 'failed_restore_parts': failures})
        if failures:
            raise RuntimeError('Chat settings update failed and restoration needs attention. Private backup: ' + str(backup)) from original
        raise RuntimeError('Chat settings update failed; the previous settings were restored and verified.') from original
    save_private(backup / 'result.json', {'ok': True, 'verified': True})


def deploy(api, config, guard, context_size, display_name=DEFAULT_NAME, restore=None, apply=False):
    """API orchestration with injected guard, allowing offline failure tests."""
    root = Path(config['target']['root']).resolve()
    model_id = config['chatApp']['modelId']
    backups = root / 'runtime/strata-chat/backups'
    if not backups.resolve().is_relative_to(root):
        raise ValueError('Private backups must stay inside the Local Studio root.')
    guard()
    current_model = read_model(api, model_id)
    current_config = api('/api/v1/configs/export')
    before_model = model_form(current_model)
    if restore:
        source = Path(restore).resolve(strict=True)
        if not source.is_relative_to(backups.resolve()) or not source.is_dir():
            raise ValueError('Restore path must be a private strata-chat backup directory.')
        snapshot = json.loads((source / 'before.json').read_text(encoding='utf-8'))
        if snapshot.get('schemaVersion') != 1 or Path(snapshot['root']).resolve() != root or snapshot.get('modelId') != model_id:
            raise ValueError('Backup identity does not match this Local Studio environment.')
        stored_model, desired_patch = model_form(snapshot['model']), snapshot['restoreConfig']
        desired_model = model_form(current_model)
        desired_model['name'] = stored_model['name']
        if not isinstance(desired_patch, dict) or set(desired_patch) != set(compaction_patch(131072, 'fixture')):
            raise ValueError('Backup contains unexpected configuration keys.')
        if stored_model.get('id') != model_id or not isinstance(current_config, dict) or not set(desired_patch).issubset(current_config):
            raise ValueError('Backup cannot be restored through the existing API settings.')
        before_patch = {key: deepcopy(current_config[key]) for key in desired_patch}
    else:
        desired_model, desired_patch, before_patch = transform(current_model, current_config, context_size,
                                                              config['inference']['alias'], display_name)
    result = {'ok': True, 'mode': 'restore' if restore else 'apply' if apply else 'plan', 'model': model_id,
              'context_size': context_size, 'token_threshold': desired_patch[COMPACTION_PREFIX + 'token_threshold'],
              'token_cap': desired_patch[COMPACTION_PREFIX + 'token_cap'], 'prompts_tools_parameters_preserved': True,
              'image_estimates_are_not_a_capacity_guarantee': True, 'per_chat_threshold_overrides_preserved': True}
    if not apply and not restore:
        return result
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    backup = backups / stamp
    backup.mkdir(parents=True, exist_ok=False)
    save_private(backup / 'before.json', {'schemaVersion': 1, 'root': str(root), 'modelId': model_id,
                                        'model': current_model, 'apiConfig': current_config, 'restoreConfig': before_patch})
    # Catch admissions/activity changes while reading and saving the private snapshot.
    guard()
    update_settings(api, model_id, desired_model, desired_patch, before_model, before_patch, backup)
    result.update(backup=str(backup), verified=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=SUPPORT / 'config/support-config.json')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--restore', type=Path)
    parser.add_argument('--context-size', type=int)
    parser.add_argument('--display-name', default=DEFAULT_NAME)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf-8-sig'))
    context_size = args.context_size if args.context_size is not None else config['inference']['contextSize']
    if not args.restore and (config['inference'].get('backend') != 'strata' or context_size != config['inference']['contextSize']):
        raise ValueError('Apply/plan must use the active Strata context from support-config.json.')
    api, model_api = LocalApi(config['chatApp']['url']), LocalApi(config['target']['defaultUrl'])
    api('/health')
    login = api('/api/v1/auths/signin', {'email': 'admin@localhost', 'password': 'admin'})
    api.token = login.get('token')
    if not isinstance(api.token, str) or not api.token:
        raise RuntimeError('Local admin authentication failed.')
    del login  # Never persist or print the auth response or token.
    sys.path.insert(0, str(SUPPORT / 'tools'))
    import local_studio as studio
    import model_maintenance
    if Path(config['target']['root']).resolve() != studio.ROOT.resolve():
        raise ValueError('Configured root differs from the installed Local Studio runtime.')
    spec = importlib.util.spec_from_file_location('studio_cli_for_chat_settings', SUPPORT / 'scripts/Local-Studio.py')
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    runtime, context = studio.media_runtime()
    with cli.submission_lock(), runtime.gpu_lease(context), model_maintenance.switching(studio.ROOT):
        def guard():
            assert_idle(api, model_api, studio.ROOT, lambda: runtime.assert_idle(context))
            if not args.restore:
                verify_strata_context(model_api, context_size)
        result = deploy(api, config, guard, context_size, args.display_name, args.restore, args.apply)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
