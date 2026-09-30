"""Offline model-profile checks; tiny fixtures never load models or touch live settings."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / 'tools'))
import model_profiles


class ModelProfiles(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='model-profile-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'runtime-root'
        self.support = Path(self.temp.name) / 'support'
        (self.root / 'models').mkdir(parents=True)
        (self.support / 'config').mkdir(parents=True)
        self.base = self.root / 'models/base.gguf'
        self.candidate = self.root / 'models/candidate.gguf'
        self.projector = self.root / 'models/mmproj.gguf'
        self.base.write_bytes(b'base' * 8)
        self.candidate.write_bytes(b'candidate' * 8)
        self.projector.write_bytes(b'projector' * 4)
        self.config = {
            'target': {'root': str(self.root), 'executable': 'fixture-server'},
            'inference': {
                'modelPath': str(self.base), 'mmprojPath': str(self.projector),
                'host': '127.0.0.1', 'port': 18080, 'alias': 'stable-local-model',
                'contextSize': 8192, 'parallel': 1, 'gpuLayers': 99,
            },
            'chatApp': {'url': 'http://127.0.0.1:18081', 'modelId': 'fixture-agent'},
            'extra': {'nested': ['preserve', {'value': 42}]},
        }
        self.catalog = {'profiles': [self.profile('original', self.base), self.profile('candidate', self.candidate)]}
        self.write_catalog()

    def profile(self, profile_id, model):
        return {
            'id': profile_id, 'label': 'Fixture ' + profile_id,
            'model': {'path': 'models/' + model.name, 'size': model.stat().st_size, 'sha256': 'a' * 64},
            'mmproj': {'path': 'models/' + self.projector.name, 'size': self.projector.stat().st_size, 'sha256': 'b' * 64},
            'source': {'repo': 'fixture/' + profile_id, 'revision': 'c' * 40, 'url': 'https://example.test/' + profile_id},
            'license': 'apache-2.0',
        }

    def write_catalog(self):
        (self.support / 'config/model-profiles.json').write_text(json.dumps(self.catalog), encoding='utf-8')

    def test_catalog_and_unknown_profile(self):
        read = model_profiles.read_catalog(self.support)
        self.assertEqual(read, self.catalog)
        self.assertEqual(model_profiles.choose(read, 'candidate'), self.catalog['profiles'][1])
        for bad in ['missing', '../models/base.gguf', str(self.base), None, ['original']]:
            with self.subTest(profile_id=bad), self.assertRaises(ValueError):
                model_profiles.choose(read, bad)

    def test_size_and_paths_are_checked_without_reading_model_bytes(self):
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('Weight bytes must not be read')):
            result = model_profiles.paths(self.config, self.catalog['profiles'][1])
        self.assertEqual(result, {'model': self.candidate.resolve(), 'mmproj': self.projector.resolve()})

    def test_both_artifact_sizes_and_regular_file_type_are_required(self):
        for role in ('model', 'mmproj'):
            with self.subTest(role=role):
                profile = deepcopy(self.catalog['profiles'][0])
                profile[role]['size'] += 1
                with self.assertRaises(ValueError):
                    model_profiles.paths(self.config, profile)
        directory = self.root / 'models/not-a-file'
        directory.mkdir()
        profile = deepcopy(self.catalog['profiles'][0])
        profile['model']['path'] = 'models/not-a-file'
        profile['model']['size'] = max(directory.stat().st_size, 1)
        with self.assertRaises(ValueError):
            model_profiles.paths(self.config, profile)

    def test_identify_depends_on_active_model_path(self):
        self.assertEqual(model_profiles.identify(self.config, self.catalog), 'original')
        changed = deepcopy(self.config)
        changed['inference']['modelPath'] = str(self.candidate)
        changed['inference']['mmprojPath'] = str(self.root / 'models/other-projector.gguf')
        self.assertEqual(model_profiles.identify(changed, self.catalog), 'candidate')
        self.candidate.unlink()
        self.assertEqual(model_profiles.identify(changed, self.catalog), 'candidate')
        changed['inference']['modelPath'] = str(self.root / 'models/unknown.gguf')
        self.assertIsNone(model_profiles.identify(changed, self.catalog))

    def test_apply_is_immutable_and_preserves_every_other_setting(self):
        before = deepcopy(self.config)
        original_catalog = deepcopy(self.catalog)
        result = model_profiles.apply(self.config, self.catalog['profiles'][1])
        expected = deepcopy(before)
        expected['inference']['modelPath'] = str(self.candidate.resolve())
        expected['inference']['mmprojPath'] = str(self.projector.resolve())
        self.assertEqual(result, expected)
        self.assertEqual(self.config, before)
        self.assertEqual(self.catalog, original_catalog)
        result['extra']['nested'][1]['value'] = 100
        self.assertEqual(self.config['extra']['nested'][1]['value'], 42)

    def test_missing_and_mismatched_artifacts_are_not_installed(self):
        self.candidate.unlink()
        listed = model_profiles.profiles(self.support, self.config)
        self.assertTrue(listed[0]['installed'])
        self.assertTrue(listed[0]['active'])
        self.assertFalse(listed[1]['installed'])
        with self.assertRaises(FileNotFoundError):
            model_profiles.apply(self.config, self.catalog['profiles'][1])
        self.candidate.write_bytes(b'incomplete')
        with self.assertRaises(ValueError):
            model_profiles.paths(self.config, self.catalog['profiles'][1])
        self.assertFalse(model_profiles.profiles(self.support, self.config)[1]['installed'])
        self.projector.unlink()
        self.assertFalse(any(row['installed'] for row in model_profiles.profiles(self.support, self.config)))

    def test_catalog_listing_exposes_provenance_and_expected_bytes_without_mutation(self):
        before = deepcopy(self.catalog)
        listed = model_profiles.profiles(self.support, self.config)
        self.assertEqual([row['id'] for row in listed], ['original', 'candidate'])
        self.assertEqual([row['active'] for row in listed], [True, False])
        self.assertTrue(all(row['installed'] for row in listed))
        for row, entry in zip(listed, self.catalog['profiles']):
            self.assertEqual(row['model']['size'], entry['model']['size'])
            self.assertEqual(row['mmproj']['size'], entry['mmproj']['size'])
            self.assertEqual(row['source'], entry['source'])
            self.assertEqual(row['license'], entry['license'])
        listed[0]['source']['repo'] = 'changed'
        self.assertEqual(self.catalog, before)

    def test_traversal_absolute_drive_stream_and_non_model_paths_are_rejected(self):
        bad_paths = [
            '../outside.gguf', 'models/../models/base.gguf', 'models/../../outside.gguf',
            str(self.base), '/models/base.gguf', r'C:\models\base.gguf', r'C:models\base.gguf',
            r'\\server\share\base.gguf', 'models/base.gguf:secret', 'data/base.gguf', 'models',
        ]
        for bad in bad_paths:
            with self.subTest(path=bad):
                profile = deepcopy(self.catalog['profiles'][0])
                profile['model']['path'] = bad
                with self.assertRaises(ValueError):
                    model_profiles.paths(self.config, profile)

    def test_escaping_directory_junction_or_symlink_is_rejected(self):
        outside = Path(self.temp.name) / 'outside-models'
        outside.mkdir()
        (outside / 'base.gguf').write_bytes(self.base.read_bytes())
        link = self.root / 'models/escape'
        if os.name == 'nt':
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)], check=True, capture_output=True)
            self.addCleanup(lambda: link.rmdir() if link.exists() else None)
        else:
            link.symlink_to(outside, target_is_directory=True)
            self.addCleanup(lambda: link.unlink(missing_ok=True))
        profile = deepcopy(self.catalog['profiles'][0])
        profile['model']['path'] = 'models/escape/base.gguf'
        with self.assertRaises(ValueError):
            model_profiles.paths(self.config, profile)
        self.assertTrue((outside / 'base.gguf').exists())

    def test_models_root_junction_cannot_change_the_boundary(self):
        isolated = Path(self.temp.name) / 'isolated-root'
        isolated.mkdir()
        link = isolated / 'models'
        if os.name == 'nt':
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(self.root / 'models')], check=True, capture_output=True)
            self.addCleanup(lambda: link.rmdir() if link.exists() else None)
        else:
            link.symlink_to(self.root / 'models', target_is_directory=True)
            self.addCleanup(lambda: link.unlink(missing_ok=True))
        config = deepcopy(self.config)
        config['target']['root'] = str(isolated)
        with self.assertRaises(ValueError):
            model_profiles.paths(config, self.catalog['profiles'][0])
        self.assertTrue(self.base.exists())

    def test_malformed_catalog_metadata_is_rejected(self):
        for field, value in [('size', True), ('size', -1), ('size', '32'), ('sha256', 'invalid')]:
            with self.subTest(field=field, value=value):
                self.catalog['profiles'][0]['model'][field] = value
                self.write_catalog()
                with self.assertRaises(ValueError):
                    model_profiles.read_catalog(self.support)
                self.catalog = {'profiles': [self.profile('original', self.base), self.profile('candidate', self.candidate)]}
        self.catalog['profiles'].append(deepcopy(self.catalog['profiles'][0]))
        self.write_catalog()
        with self.assertRaises(ValueError):
            model_profiles.read_catalog(self.support)

    def test_helpers_make_no_network_or_process_calls(self):
        with patch('urllib.request.urlopen', side_effect=AssertionError('No network calls')), \
             patch('subprocess.run', side_effect=AssertionError('No process execution')), \
             patch('subprocess.Popen', side_effect=AssertionError('No process execution')):
            catalog = model_profiles.read_catalog(self.support)
            selected = model_profiles.choose(catalog, 'candidate')
            model_profiles.paths(self.config, selected)
            model_profiles.identify(self.config, catalog)
            model_profiles.apply(self.config, selected)
            model_profiles.profiles(self.support, self.config)


if __name__ == '__main__':
    unittest.main(verbosity=2)
