"""Offline preparation guards with tiny fake artifacts, never the live runtime."""
from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

SUPPORT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('swift_prepare_test', SUPPORT / 'scripts/Prepare-SwiftStrata.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)
MANIFEST = prepare.json_file(SUPPORT / 'config/swift-download-manifest.json')


class ManifestPins(unittest.TestCase):
    def test_real_manifest_matches_reviewed_model_runtime_and_mtp(self):
        prepare.verify_manifest(MANIFEST)

    def test_manifest_rejects_float_revisions_other_shards_and_other_mtp(self):
        for change in ('modelRevision', 'file', 'mtp', 'ple'):
            manifest = deepcopy(MANIFEST)
            if change == 'modelRevision':
                manifest['modelRevision'] = 'main'
            elif change == 'file':
                manifest['files'][1]['sha256'] = '0' * 64
            elif change == 'mtp':
                manifest['mtpReuse']['folder'] = 'models/another/mtp/rt'
            else:
                manifest['preparation']['pleShard'] = 2
            with self.subTest(change=change), self.assertRaises(ValueError):
                prepare.verify_manifest(manifest)


class Preparation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='swift-preparation-offline-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'runtime'
        self.root.mkdir()
        self.manifest = deepcopy(MANIFEST)
        self.commands = []
        files = []
        for index, (relative, _, _) in enumerate(prepare.MODEL_FILES + prepare.LICENSE_FILES):
            payload = ('synthetic-artifact-' + str(index)).encode()
            self.write(relative, payload)
            row = (relative, len(payload), hashlib.sha256(payload).hexdigest())
            files.append(row)
            for item in self.manifest['files']:
                if item['folder'] + '/' + item['name'] == relative:
                    item.update(size=row[1], sha256=row[2])
        self.model_files = tuple(files[:3])
        self.license_files = tuple(files[3:])
        mtp = []
        for name, _, _ in prepare.MTP_FILES:
            payload = ('synthetic-mtp-' + name).encode()
            self.write(prepare.OLD_DATA_REL + '/mtp/rt/' + name, payload)
            row = (name, len(payload), hashlib.sha256(payload).hexdigest())
            mtp.append(row)
            for item in self.manifest['mtpReuse']['files']:
                if item['name'] == name:
                    item.update(size=row[1], sha256=row[2])
        self.mtp_files = tuple(mtp)
        self.patches = [patch.object(prepare, 'MODEL_FILES', self.model_files),
                        patch.object(prepare, 'LICENSE_FILES', self.license_files),
                        patch.object(prepare, 'MTP_FILES', self.mtp_files)]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        source = prepare.SOURCE_REL
        for directory in ('.git', 'tools', 'engine', '.venv/Scripts',
                          'third_party/llama.cpp/gguf-py', '.venv/Lib/site-packages/nvidia/cu13/bin/x86_64'):
            (self.root / source / directory).mkdir(parents=True, exist_ok=True)
        for name in ('setup.py', 'requirements.txt', 'tools/iq_pack.py', 'tools/gguf_reader.py',
                     'tools/_paths.py', 'tools/strata_tokenizer.py', 'engine/strata.exe',
                     'engine/strata-vision.exe', '.venv/Scripts/python.exe', 'data/expert-profile.bin'):
            self.write(source + '/' + name, b'synthetic-source')
        self.write(source + '/engine/BUILD.json', prepare.encoded(
            {'version': '0.1.39', 'source': 'release', 'cuda': '13.0', 'vision': 'gpu',
             'archs': [89], 'vision_archs': [89]}))
        self.base = {
            'exe': str(self.root / source / 'engine/strata.exe'),
            'cwd': str(self.root / source),
            'args': [], 'host': '127.0.0.1', 'port': 18080, 'gpu': 0,
            'draft_vocab': 'cjk', 'open_browser': False,
            'tokenizer': str(self.root / prepare.OLD_DATA_REL / 'packs/iq3_s/tokenizer'),
            'model_name': 'qwen3.8-flash-next-iq3_s',
            'lib_dirs': [str(self.root / source / '.venv/Lib/site-packages/nvidia/cu13/bin/x86_64')],
            'log': str(self.root / source / 'strata-iq3_s.log'),
            'aliases': ['qwen3.8-27b-local'], 'fixture_preserved': {'setting': 'keep'},
        }
        values = {
            '--pack': str(self.root / prepare.OLD_DATA_REL / 'packs/iq3_s'),
            '--native': str(self.root / prepare.OLD_DATA_REL /
                'IQ3_S/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00001-of-00002.gguf'),
            '--ple-gguf': str(self.root / prepare.OLD_DATA_REL /
                'IQ3_S/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00002-of-00002.gguf'),
            '--expert-profile': str(self.root / source / 'data/expert-profile.bin'),
            '--expert-cache': 'auto', '--prefill': 'auto', '--spec': '4', '--spec-min-p': '0.5',
            '--mtp': str(self.root / prepare.OLD_DATA_REL / 'mtp/rt'),
            '--max-context': '131072', '--kv': 'int8', '--kv-resident': '32768',
            '--vram-reserve-mib': '1536',
        }
        self.base['args'] = [value for row in values.items() for value in row] + ['--vision']
        self.base['vision'] = {'exe': str(self.root / source / 'engine/strata-vision.exe'),
            'model': values['--native'], 'mmproj': str(self.root / prepare.OLD_DATA_REL /
                'mmproj-Qwen3.8-Flash-Next-BF16.gguf'), 'gpu': True, 'max_tokens': 1024}
        self.write(prepare.BASE_CONFIG_REL, prepare.encoded(self.base))
        self.config = {'target': {'root': str(self.root)}, 'strata': {'sourceRoot': str(self.root / source)}}
        self.git_head, self.git_diff = prepare.SOURCE_COMMIT, 0

    def write(self, relative, payload):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return path

    def runner(self, command, **kwargs):
        self.commands.append((list(command), kwargs))
        if command[0] == 'git':
            if 'rev-parse' in command:
                return SimpleNamespace(stdout=self.git_head + '\n', returncode=0)
            return SimpleNamespace(stdout='', returncode=self.git_diff if 'diff' in command else 0)
        stage = Path(command[command.index('--out') + 1])
        self.assertTrue(stage.is_relative_to(self.root / prepare.DATA_REL / 'packs'))
        self.assertEqual(command[command.index('--gguf') + 1], str(self.root / self.model_files[0][0]))
        self.assertNotIn('--base', command)
        self.assertNotIn('--experts-bin', command)
        self.assertEqual(kwargs['env']['HF_HUB_OFFLINE'], '1')
        self.assertEqual(kwargs['env']['PYTHONDONTWRITEBYTECODE'], '1')
        for name in ('native_experts.txt', 'index.txt', 'dense.bin'):
            (stage / name).write_bytes(b'synthetic-pack')
        (stage / 'native_experts.txt').write_text('13 18 20 0 8 1 2 3 ' +
            Path(self.model_files[1][0]).name + '\n', encoding='utf-8')
        (stage / 'tokenizer').mkdir()
        (stage / 'tokenizer/vocab.json').write_text('{"token": 1}', encoding='utf-8')
        (stage / 'tokenizer/tokenizer.json').write_text('{"model": {"type": "BPE"}}', encoding='utf-8')
        (stage / 'tokenizer/chat_template.jinja').write_text('{% for m in messages %}{{m}}{% endfor %}', encoding='utf-8')
        return SimpleNamespace(returncode=0)

    def planned(self):
        with redirect_stdout(io.StringIO()):
            return prepare.plan(self.config, self.manifest, run=self.runner)

    def apply(self, prepared):
        with redirect_stdout(io.StringIO()):
            return prepare.apply(prepared, run=self.runner)

    def test_default_plan_never_writes_pack_config_or_changes_base(self):
        before = (self.root / prepare.BASE_CONFIG_REL).read_bytes()
        prepared = self.planned()
        self.assertFalse(prepared['pack'].exists())
        self.assertFalse((self.root / prepare.OUTPUT_CONFIG_REL).exists())
        self.assertEqual(before, (self.root / prepare.BASE_CONFIG_REL).read_bytes())
        self.assertTrue(all(command[0] == 'git' for command, _ in self.commands))

    def test_source_pin_and_tracked_edits_fail_before_mutation(self):
        for head, dirty in [('wrong-commit', 0), (prepare.SOURCE_COMMIT, 1)]:
            self.git_head, self.git_diff = head, dirty
            with self.subTest(head=head, dirty=dirty), self.assertRaises(ValueError):
                self.planned()
        self.assertFalse((self.root / prepare.PACK_REL).exists())

    def test_corrupt_model_or_mtp_fails_before_any_output(self):
        for relative in (self.model_files[1][0], prepare.OLD_DATA_REL + '/mtp/rt/draft_vocab.bin'):
            path = self.root / relative
            before = path.read_bytes()
            path.write_bytes(b'X' * len(before))
            with self.subTest(relative=relative), self.assertRaisesRegex(ValueError, 'SHA256'):
                self.planned()
            path.write_bytes(before)
        self.assertFalse((self.root / prepare.PACK_REL).exists())

    def test_missing_license_and_truncated_model_are_retained(self):
        path = self.root / self.license_files[0][0]
        path.unlink()
        with self.assertRaisesRegex(ValueError, 'missing'):
            self.planned()
        self.write(self.license_files[0][0], b'synthetic-artifact-3')
        path = self.root / self.model_files[0][0]
        path.write_bytes(b'truncated')
        with self.assertRaisesRegex(ValueError, 'size mismatch'):
            self.planned()
        self.assertEqual(path.read_bytes(), b'truncated')

    def test_ple_shard1_own_paths_aliases_and_existing_settings_preserved(self):
        before = deepcopy(self.base)
        changed = prepare.server_config(self.root, self.base)
        args = prepare.parse_flags(changed['args'])
        self.assertEqual(args['--ple-gguf'], args['--native'])
        self.assertEqual(args['--pack'], str(self.root / prepare.PACK_REL))
        self.assertEqual(args['--expert-profile'], str(self.root / prepare.DATA_REL / 'expert-profile.bin'))
        self.assertEqual(args['--mtp'], str(self.root / prepare.OLD_DATA_REL / 'mtp/rt'))
        self.assertEqual(changed['aliases'], ['qwen3.8-27b-local', 'qwen3.8-flash-next-iq3_s'])
        self.assertEqual(changed['model_name'], prepare.MODEL_NAME)
        self.assertEqual(changed['fixture_preserved'], before['fixture_preserved'])
        self.assertEqual(before, self.base)

    def test_duplicate_option_network_executable_and_other_vision_are_rejected(self):
        for case in ('duplicate', 'network', 'vision', 'context'):
            base = deepcopy(self.base)
            if case == 'duplicate':
                base['args'] += ['--native', 'unexpected']
            elif case == 'network':
                base['exe'] = 'https://unexpected.invalid/engine.exe'
            elif case == 'vision':
                base['vision']['model'] = str(self.root / 'models/another.gguf')
            else:
                base['args'][base['args'].index('--max-context') + 1] = '262144'
            with self.subTest(case=case), self.assertRaises(ValueError):
                prepare.server_config(self.root, base)

    def test_absolute_ads_traversal_and_link_paths_rejected(self):
        for relative in ('../outside', '/outside', 'models/../outside', 'models/file:stream', 'models//unexpected'):
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                prepare.scoped(self.root, relative)
        with patch.object(prepare, 'reparse_path', lambda path: path == self.root / 'models'):
            with self.assertRaisesRegex(ValueError, 'reparse'):
                prepare.scoped(self.root, self.model_files[0][0])

    def test_foreign_pack_and_conflicting_config_are_retained(self):
        pack = self.root / prepare.PACK_REL
        pack.mkdir(parents=True)
        foreign = pack / 'user-data.bin'
        foreign.write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError, 'ownership'):
            self.planned()
        self.assertEqual(foreign.read_bytes(), b'keep')
        foreign.unlink()
        pack.rmdir()
        conflict = self.write(prepare.OUTPUT_CONFIG_REL, b'{"custom":true}')
        with self.assertRaisesRegex(ValueError, 'retained'):
            self.planned()
        self.assertEqual(conflict.read_bytes(), b'{"custom":true}')

    def test_apply_own_pack_only_and_idempotent_reuse(self):
        base_bytes = (self.root / prepare.BASE_CONFIG_REL).read_bytes()
        mtp_before = {name: (self.root / prepare.OLD_DATA_REL / 'mtp/rt' / name).read_bytes()
                      for name, _, _ in self.mtp_files}
        result = self.apply(self.planned())
        self.assertTrue(result['prepared'])
        self.assertFalse(result['active_model_changed'])
        output = prepare.json_file(self.root / prepare.OUTPUT_CONFIG_REL)
        self.assertEqual(output['model_name'], prepare.MODEL_NAME)
        self.assertEqual(prepare.json_file(self.root / prepare.SHARED_CONFIG_REL), {'reasoning_effort': 'none'})
        self.assertEqual(base_bytes, (self.root / prepare.BASE_CONFIG_REL).read_bytes())
        for name, content in mtp_before.items():
            self.assertEqual(content, (self.root / prepare.OLD_DATA_REL / 'mtp/rt' / name).read_bytes())
        self.commands.clear()
        self.apply(self.planned())
        self.assertTrue(all(command[0] == 'git' for command, _ in self.commands))

    def test_input_change_after_hash_prevents_builder_or_config_write(self):
        prepared = self.planned()
        path = self.root / self.model_files[0][0]
        path.write_bytes(b'changed')
        self.commands.clear()
        with self.assertRaisesRegex(ValueError, 'input changed'):
            self.apply(prepared)
        self.assertFalse(self.commands)
        self.assertFalse((self.root / prepare.PACK_REL).exists())

    def test_pack_corruption_is_not_reused_or_replaced(self):
        self.apply(self.planned())
        dense = self.root / prepare.PACK_REL / 'dense.bin'
        dense.write_bytes(b'corrupted-pack')
        with self.assertRaisesRegex(ValueError, 'output hashes'):
            self.planned()
        self.assertEqual(dense.read_bytes(), b'corrupted-pack')

    def test_existing_other_shared_settings_are_preserved(self):
        shared = {'reasoning_effort': 'none', 'temperature': 0.7}
        self.write(prepare.SHARED_CONFIG_REL, prepare.encoded(shared))
        self.apply(self.planned())
        self.assertEqual(prepare.json_file(self.root / prepare.SHARED_CONFIG_REL), shared)

    def test_failed_builder_retains_its_stage_and_never_publishes_config(self):
        prepared = self.planned()
        def failing(command, **kwargs):
            if command[0] == 'git':
                return self.runner(command, **kwargs)
            stage = Path(command[command.index('--out') + 1])
            (stage / 'partial.bin').write_bytes(b'partial')
            raise RuntimeError('synthetic builder failure')
        with self.assertRaisesRegex(RuntimeError, 'synthetic builder failure'):
            prepare.apply(prepared, run=failing)
        stages = list((self.root / prepare.DATA_REL / 'packs').glob('.swift-iq3_xxs-prepare-*'))
        self.assertEqual(len(stages), 1)
        self.assertEqual((stages[0] / 'partial.bin').read_bytes(), b'partial')
        self.assertFalse((self.root / prepare.PACK_REL).exists())
        self.assertFalse((self.root / prepare.OUTPUT_CONFIG_REL).exists())


if __name__ == '__main__':
    unittest.main()
