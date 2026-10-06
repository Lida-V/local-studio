"""Switch installed Qwen profiles when idle, with exact-process stop and rollback."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request
import urllib.parse

SUPPORT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SUPPORT / 'tools'))
import local_studio as studio
import model_profiles
import model_maintenance


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, url):
        raise RuntimeError('Local API redirected; model switching aborted.')


class LocalApi:
    def __init__(self, base):
        parsed = urllib.parse.urlsplit(base)
        if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1') or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
            raise ValueError('Model switching accepts loopback HTTP API roots only.')
        self.base = base.rstrip('/')
        self.token = None
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def __call__(self, path, value=None):
        if not path.startswith('/') or path.startswith('//'):
            raise ValueError('API paths must be local absolute paths.')
        headers = {'Content-Type': 'application/json'}
        if self.token: headers['Authorization'] = 'Bearer ' + self.token
        request = urllib.request.Request(self.base + path, headers=headers,
            data=json.dumps(value).encode() if value is not None else None)
        with self.opener.open(request, timeout=15) as response: return json.load(response)


def digest(path):
    import hashlib
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(16 * 1024 * 1024): sha.update(block)
    return sha.hexdigest()


def atomic_config(path, data):
    temp = path.with_suffix('.profile.tmp')
    temp.write_bytes(data)
    temp.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile')
    args = parser.parse_args()
    config_path = SUPPORT / 'config/support-config.json'
    original = config_path.read_bytes()
    config = json.loads(original.decode('utf-8-sig'))
    if Path(config['target']['root']).resolve() != studio.ROOT.resolve():
        raise ValueError('Configured root differs from the installed Local Studio runtime.')
    api = LocalApi(config['chatApp']['url'])
    model_api = LocalApi(config['target']['defaultUrl'])
    catalog = model_profiles.read_catalog(SUPPORT)
    profile = model_profiles.choose(catalog, args.profile)
    artifacts = model_profiles.paths(config, profile)
    metadata = model_profiles.artifacts(profile)
    for key, path in artifacts.items():
        if digest(path) != metadata[key]['sha256'].lower():
            raise RuntimeError('Installed artifact failed SHA256 verification; nothing switched.')
    changed = model_profiles.apply(config, profile)
    spec = importlib.util.spec_from_file_location('studio_cli_for_switch', SUPPORT / 'scripts/Local-Studio.py')
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    runtime, context = studio.media_runtime()
    app_available = False

    def assert_idle():
        queue = studio.ROOT / 'runtime/agent-queue'
        if queue.exists() and any(queue.iterdir()):
            raise RuntimeError('Agent tasks are queued or running. Finish them before switching models.')
        runtime.assert_idle(context)
        if app_available:
            tasks, activity, gate = api('/api/tasks'), api('/api/local-studio/activity'), api('/api/local-studio/model-maintenance')
            if not isinstance(tasks.get('tasks'), list) or type(activity.get('active_count')) is not int or activity['active_count'] != 0 or tasks['tasks'] or gate.get('admission_gate') is not True or type(gate.get('admitted_chats')) is not int or gate['admitted_chats'] != 0:
                raise RuntimeError('Local Studio work is active or its state is unknown. Nothing switched.')
        try:
            slots = model_api('/slots')
        except urllib.error.URLError as error:
            if not isinstance(error.reason, ConnectionRefusedError) and getattr(error.reason, 'winerror', None) != 10061:
                raise RuntimeError('Cannot confirm the model is idle; nothing switched.') from error
        else:
            if not isinstance(slots, list) or not slots or any(not isinstance(slot, dict) or slot.get('is_processing') is not False for slot in slots):
                raise RuntimeError('Model inference is active or its state is unknown; nothing switched.')

    try:
        api('/health')
        app_available = True
        api.token = api('/api/v1/auths/signin', {'email': 'admin@localhost', 'password': 'admin'})['token']
        if api('/api/local-studio/model-maintenance').get('admission_gate') is not True:
            raise RuntimeError('Deploy the updated Local Studio toolkit before switching models.')
    except urllib.error.URLError as error:
        if not isinstance(error.reason, ConnectionRefusedError) and getattr(error.reason, 'winerror', None) != 10061:
            raise
    with cli.submission_lock(), runtime.gpu_lease(context), model_maintenance.switching(studio.ROOT):
        assert_idle()
        before_model = None
        if app_available:
            models = api('/api/v1/models/all')
            items = models.get('items', models.get('data', [])) if isinstance(models, dict) else models
            before_model = next(model for model in items if model['id'] == config['chatApp']['modelId'])
        backup = studio.ROOT / 'runtime/maintenance-backups' / ('model-switch-' + time.strftime('%Y%m%d-%H%M%S') + '-' + str(time.time_ns()))
        backup.mkdir(parents=True)
        (backup / 'support-config.json').write_bytes(original)
        if before_model:
            (backup / 'preset.json').write_text(json.dumps(before_model, ensure_ascii=False), encoding='utf-8')
        configured = stop_attempted = False
        try:
            # A second check catches work started while reading the current preset.
            assert_idle()
            stop_attempted = True
            studio.script(SUPPORT / 'scripts/Stop-LocalLLM.ps1')
            runtime.free_idle(context)
            atomic_config(config_path, (json.dumps(changed, ensure_ascii=False, indent=2) + '\n').encode())
            configured = True
            studio.script(SUPPORT / 'scripts/Start-LocalLLM.ps1')
            state = json.loads((studio.ROOT / 'runtime/server.json').read_text(encoding='utf-8-sig'))
            import psutil
            process = psutil.Process(state['pid'])
            assert abs(process.create_time() - (state['startUtcTicks'] / 10000000 - 62135596800)) < 0.01
            command = process.cmdline()
            if changed['inference'].get('backend') == 'strata':
                expected_config = Path(changed['strata']['serverConfigPath']).resolve()
                assert Path(command[command.index('--config') + 1]).resolve() == expected_config
                token = state['launchToken']
                assert len(token) == 32 and all(c in '0123456789abcdef' for c in token)
                process_state = studio.ROOT / 'runtime' / ('strata-process-' + token + '.json')
                assert Path(state['processStatePath']).resolve() == process_state.resolve()
                identity = json.loads(process_state.read_text(encoding='utf-8'))
                assert identity['launchToken'] == token and identity['backend'] == 'strata' and identity['jobContained'] is True
                assert Path(identity['serverConfigPath']).resolve() == expected_config
                assert Path(identity['sourceRoot']).resolve() == Path(changed['strata']['sourceRoot']).resolve()
                server = psutil.Process(identity['server']['pid'])
                assert abs(server.create_time() - (identity['server']['startUtcTicks'] / 10000000 - 62135596800)) < 0.01
                assert Path(server.exe()).resolve() == Path(identity['server']['executable']).resolve()
                health = model_api('/health')
                assert health.get('service') == 'strata' and health.get('loaded') is True and health.get('images') is True
                assert health.get('max_context') == changed['inference']['contextSize']
            else:
                assert Path(command[command.index('--model') + 1]).resolve() == artifacts['model']
            if before_model:
                model_form = copy.deepcopy({key: before_model[key] for key in ('id', 'base_model_id', 'name', 'params', 'meta', 'is_active', 'access_grants') if key in before_model})
                model_form['name'] = 'Local Studio · ' + profile['label']
                api('/api/v1/models/model/update?id=' + model_form['id'], model_form)
            print(json.dumps({'active_profile': profile['id'], 'label': profile['label'],
                'context_size': changed['inference']['contextSize'], 'artifacts_verified': True,
                'previous_model_preserved': True, 'preset_settings_preserved': True}, ensure_ascii=False))
        except BaseException as initial:
            errors = []
            def recover(name, action):
                try: action()
                except BaseException as error: errors.append(name + ': ' + str(error))
            if stop_attempted:
                if configured:
                    recover('stop failed profile', lambda: studio.script(SUPPORT / 'scripts/Stop-LocalLLM.ps1'))
                    # Keep the live config describing a surviving new process; retain the
                    # original backup rather than claim it is restored while still running.
                    if not errors:
                        recover('restore config', lambda: atomic_config(config_path, original))
                if not errors:
                    recover('restart previous profile', lambda: studio.script(SUPPORT / 'scripts/Start-LocalLLM.ps1'))
                if before_model:
                    previous_form = {key: before_model[key] for key in ('id', 'base_model_id', 'name', 'params', 'meta', 'is_active', 'access_grants') if key in before_model}
                    recover('restore preset', lambda: api('/api/v1/models/model/update?id=' + previous_form['id'], previous_form))
            if errors:
                raise RuntimeError('Model switch failed: ' + str(initial) + '; recovery incomplete: ' + '; '.join(errors) + '; original settings retained in maintenance-backups.') from initial
            raise


if __name__ == '__main__': main()
