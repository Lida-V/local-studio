"""Offline regression tests for GPU coordination and preparation-only training routes."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import local_studio as studio
import media_runtime as media
import training_routes

class Routes(unittest.TestCase):
    def test_supported_models_and_geometry(self):
        self.assertEqual(set(media.models(studio)), {'anima','qwen-image-2.1','minimax-h3'})
        media.validate(studio,'minimax-h3','a boat',608,352,42,2)
        for args in [('minimax-h3','a boat',1024,1024,42,2), ('qwen-image-2.1','a cup',513,512,42,2), ('anima','',512,512,42,2)]:
            with self.assertRaises(ValueError): media.validate(studio,*args)

    def test_queue_unknown_does_not_mean_idle(self):
        with patch.object(studio,'api',side_effect=urllib.error.URLError(TimeoutError())):
            with self.assertRaises(RuntimeError): media.assert_idle(studio)

    def test_other_server_busy_blocks_free(self):
        def api(url, *args, **kwargs):
            return {'queue_running':[1] if ':8191/' in url else [], 'queue_pending':[]}
        with patch.object(studio,'api',side_effect=api) as call:
            with self.assertRaises(RuntimeError): media.free_idle(studio)
            self.assertFalse(any('/free' in c.args[0] for c in call.call_args_list))

    def test_gpu_lock_released_after_failure(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(studio,'ROOT',Path(temp)):
            with self.assertRaises(ValueError), media.gpu_lease(studio): raise ValueError('fixture')
            with media.gpu_lease(studio): pass

    def test_preparation_has_no_execution_and_rejects_reuse(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(studio,'WORK',Path(temp)), patch.object(studio.subprocess,'run') as run:
            for model in training_routes.PROFILES:
                result=training_routes.prepare(studio,model,model.replace('.', '-'))
                self.assertFalse(result['training_started'])
                self.assertFalse(result['download_started'])
                self.assertTrue((Path(result['prepared'])/'README.md').is_file())
                with self.assertRaises(FileExistsError): training_routes.prepare(studio,model,model.replace('.', '-'))
            for name in ['../outside','C:/escape','bad:name','']:
                with self.assertRaises(ValueError): training_routes.prepare(studio,'anima',name)
            run.assert_not_called()

if __name__=='__main__': unittest.main()
