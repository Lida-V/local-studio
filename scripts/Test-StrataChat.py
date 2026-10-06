"""Offline compaction/preset preservation and API rollback failure tests."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

SUPPORT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('strata_chat_deploy', SUPPORT / 'scripts/Deploy-StrataChat.py')
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)
spec = importlib.util.spec_from_file_location('strata_chat_existing_adapter', SUPPORT / 'tools/webui_runtime.py')
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)
PREFIX = deploy.COMPACTION_PREFIX


class Transforms(unittest.TestCase):
    def fixture(self):
        model = {'id': 'fixture', 'name': 'Before', 'base_model_id': 'stable-alias',
                 'params': {'system': '日本語の制作指示。画像は必要な1枚ずつ確認します。', 'max_tokens': 2048,
                            'temperature': 0.2, 'compact_token_threshold': 42000},
                 'meta': {'toolIds': ['local_studio'], 'custom': {'retain': True}},
                 'is_active': True, 'access_grants': [], 'created_at': 123}
        config = {PREFIX + 'enable': True, PREFIX + 'token_threshold': 2400, PREFIX + 'token_cap': 3200,
                  PREFIX + 'model': 'stable-alias', PREFIX + 'retention_percentage': 20,
                  PREFIX + 'prompt_template': 'Keep this summary prompt.', 'unrelated': 'preserve'}
        return model, config

    def test_context_reserves_at_128k_and_32k(self):
        for size, threshold, cap in [(131072, 60000, 90000), (32768, 15000, 22000), (262144, 60000, 90000)]:
            values = deploy.compaction_patch(size, 'stable-alias')
            self.assertEqual(values[PREFIX + 'token_threshold'], threshold)
            self.assertEqual(values[PREFIX + 'token_cap'], cap)
            self.assertLess(cap + 2048, size)
        for size in [0, True, 8191, 262145, '131072']:
            with self.assertRaises(ValueError):
                deploy.compaction_patch(size, 'stable-alias')

    def test_pure_transform_preserves_prompt_tools_and_every_other_model_setting(self):
        model, config = self.fixture()
        originals = deepcopy((model, config))
        changed, patch, before = deploy.transform(model, config, 131072, 'stable-alias')
        self.assertEqual((model, config), originals)
        self.assertEqual(changed['name'], deploy.DEFAULT_NAME)
        self.assertEqual({k: v for k, v in changed.items() if k != 'name'},
                         {k: v for k, v in deploy.model_form(model).items() if k != 'name'})
        self.assertEqual(set(patch), {PREFIX + key for key in ['enable', 'token_threshold', 'token_cap', 'model']})
        self.assertEqual(before[PREFIX + 'token_threshold'], 2400)
        self.assertNotIn(PREFIX + 'retention_percentage', patch)
        self.assertNotIn(PREFIX + 'prompt_template', patch)

    def test_missing_old_key_is_refused_because_import_has_no_delete(self):
        model, config = self.fixture()
        del config[PREFIX + 'model']
        with self.assertRaisesRegex(ValueError, 'safe API-only restoration'):
            deploy.transform(model, config, 131072, 'stable-alias')

    def test_existing_japanese_estimate_and_file_history_policy_remain_in_force(self):
        self.assertGreaterEqual(adapter.estimate_tokens('日本語の文章'), 9)
        form = {'messages': [
            {'role': 'system', 'content': 'Keep the user instructions.'},
            {'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'fixture-image'}}]},
            {'role': 'assistant', 'tool_calls': [{'id': 'old', 'function': {'name': 'read_workspace_file'}},
                                               {'id': 'latest', 'function': {'name': 'read_workspace_file'}}]},
            {'role': 'tool', 'tool_call_id': 'old', 'content': 'x' * 2000},
            {'role': 'tool', 'tool_call_id': 'latest', 'content': 'y' * 2000}]}
        bounded = adapter.bound_file_history(form)
        self.assertEqual(bounded['messages'][:3], form['messages'][:3])
        self.assertEqual(bounded['messages'][-1], form['messages'][-1])
        self.assertLess(len(bounded['messages'][-2]['content']), 1000)
        self.assertEqual(form['messages'][-2]['content'], 'x' * 2000)


class ApiOrchestration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='strata-chat-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model, self.api_config = Transforms().fixture()
        self.original_model, self.original_config = deepcopy(self.model), deepcopy(self.api_config)
        self.config = {'target': {'root': str(self.root)}, 'chatApp': {'modelId': 'fixture'},
                       'inference': {'alias': 'stable-alias', 'backend': 'strata', 'contextSize': 131072}}
        self.calls, self.failure = [], None
        self.guard = Mock()

    def api(self, path, value=None):
        self.calls.append((path, deepcopy(value)))
        if path == '/api/v1/models/all':
            return {'items': [deepcopy(self.model)]}
        if path == '/api/v1/configs/export':
            return deepcopy(self.api_config)
        if path.startswith('/api/v1/models/model/update?'):
            self.model = deepcopy(value)
            if self.failure == 'model':
                self.failure = None
                raise RuntimeError('Fixture update applied before failure.')
            return deepcopy(self.model)
        if path == '/api/v1/configs/import':
            self.api_config.update(deepcopy(value['config']))
            if self.failure == 'config':
                self.failure = None
                raise RuntimeError('Fixture config applied before failure.')
            return deepcopy(self.api_config)
        raise AssertionError('Unexpected endpoint')

    def test_plan_is_read_only_and_never_creates_private_backup(self):
        result = deploy.deploy(self.api, self.config, self.guard, 131072)
        self.assertEqual(result['mode'], 'plan')
        self.assertFalse((self.root / 'runtime/strata-chat').exists())
        self.assertTrue(all(value is None for _, value in self.calls))

    def test_apply_saves_exact_private_snapshot_and_changes_only_reviewed_fields(self):
        result = deploy.deploy(self.api, self.config, self.guard, 131072, apply=True)
        self.assertTrue(result['verified'])
        self.assertEqual(self.guard.call_count, 2)
        snapshot = json.loads((Path(result['backup']) / 'before.json').read_text(encoding='utf-8'))
        self.assertEqual(snapshot['model'], self.original_model)
        self.assertEqual(snapshot['apiConfig'], self.original_config)
        self.assertEqual(self.model['params'], self.original_model['params'])
        self.assertEqual(self.model['meta'], self.original_model['meta'])
        self.assertEqual(self.api_config['unrelated'], 'preserve')
        self.assertEqual(self.api_config[PREFIX + 'retention_percentage'], 20)
        self.assertNotIn('token', snapshot)

    def test_post_mutation_model_or_config_error_restores_old_values(self):
        for failure in ('model', 'config'):
            with self.subTest(failure=failure):
                self.model, self.api_config = deepcopy(self.original_model), deepcopy(self.original_config)
                self.failure = failure
                with self.assertRaisesRegex(RuntimeError, 'restored and verified'):
                    deploy.deploy(self.api, self.config, self.guard, 131072, apply=True)
                self.assertEqual(deploy.model_form(self.model), deploy.model_form(self.original_model))
                self.assertEqual(self.api_config, self.original_config)

    def test_restore_returns_name_and_compaction_without_erasing_later_prompt_changes(self):
        applied = deploy.deploy(self.api, self.config, self.guard, 131072, apply=True)
        self.model['params']['system'] = 'A later user instruction must survive restoration.'
        restored = deploy.deploy(self.api, self.config, self.guard, 131072, restore=applied['backup'])
        self.assertEqual(restored['mode'], 'restore')
        self.assertEqual(self.model['name'], self.original_model['name'])
        self.assertEqual(self.model['params']['system'], 'A later user instruction must survive restoration.')
        self.assertEqual(self.api_config, self.original_config)

    def test_second_idle_check_stops_update_after_snapshot(self):
        self.guard.side_effect = [None, RuntimeError('Fixture new work')]
        with self.assertRaisesRegex(RuntimeError, 'Fixture new work'):
            deploy.deploy(self.api, self.config, self.guard, 131072, apply=True)
        self.assertTrue(all(value is None for _, value in self.calls))

    def test_restore_outside_private_backup_root_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'private strata-chat backup'):
            deploy.deploy(self.api, self.config, self.guard, 131072, restore=self.root)
        self.assertTrue(all(value is None for _, value in self.calls))


class GuardsAndBoundary(unittest.TestCase):
    def test_idle_gate_denies_unknown_or_active_chat_and_model_state(self):
        with tempfile.TemporaryDirectory(prefix='strata-idle-test-') as temp:
            replies = {'/api/tasks': {'tasks': []}, '/api/local-studio/activity': {'active_count': 0},
                       '/api/local-studio/model-maintenance': {'admission_gate': True, 'switching': True, 'admitted_chats': 0}}
            api = lambda path: deepcopy(replies[path])
            media_idle = Mock()
            deploy.assert_idle(api, lambda _: [{'is_processing': False}], Path(temp), media_idle)
            for path, changed in [('/api/tasks', {'tasks': ['active']}), ('/api/local-studio/activity', {'active_count': None}),
                                  ('/api/local-studio/model-maintenance', {'admission_gate': True, 'switching': False, 'admitted_chats': 0})]:
                previous, replies[path] = replies[path], changed
                with self.assertRaises(RuntimeError):
                    deploy.assert_idle(api, lambda _: [{'is_processing': False}], Path(temp), media_idle)
                replies[path] = previous
            for slots in ([], [{'is_processing': True}], [{'unknown': True}]):
                with self.assertRaises(RuntimeError):
                    deploy.assert_idle(api, lambda _: slots, Path(temp), media_idle)

    def test_real_loaded_context_and_vision_must_match_before_threshold_expands(self):
        health = {'status': 'ok', 'service': 'strata', 'loaded': True, 'images': True, 'max_context': 131072}
        props = {'default_generation_settings': {'n_ctx': 131072}, 'modalities': {'vision': True}, 'is_sleeping': False}
        api = lambda path: health if path == '/health' else props
        deploy.verify_strata_context(api, 131072)
        with self.assertRaises(RuntimeError):
            deploy.verify_strata_context(api, 32768)
        health['loaded'] = False
        with self.assertRaises(RuntimeError):
            deploy.verify_strata_context(api, 131072)

    def test_loopback_api_never_uses_proxy_or_redirect(self):
        with patch.object(deploy.urllib.request, 'build_opener') as build:
            deploy.LocalApi('http://127.0.0.1:18081')
            proxy, redirect = build.call_args.args
            self.assertEqual(proxy.proxies, {})
            self.assertIsInstance(redirect, deploy.NoRedirect)
        for base in ('https://127.0.0.1', 'http://example.test', 'http://user:pass@127.0.0.1', 'http://127.0.0.1/path'):
            with self.assertRaises(ValueError):
                deploy.LocalApi(base)
        with self.assertRaises(RuntimeError):
            deploy.NoRedirect().redirect_request(None, None, 302, '', {}, 'http://example.test')


if __name__ == '__main__':
    unittest.main()
