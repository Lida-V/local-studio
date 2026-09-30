"""In-memory ASGI admission tests; no running server or production data is used."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / 'tools'))
import model_maintenance as maintenance
import psutil
import httpx
from fastapi import FastAPI
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, StreamingResponse
from starlette.routing import Mount, Route


class MarkerState(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='model-maintenance-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'runtime').mkdir()
        self.marker = self.root / 'runtime/model-switch.json'

    def test_owner_identity_stale_process_and_unknown_states(self):
        self.assertFalse(maintenance.active(self.root))
        self.marker.write_text(json.dumps({'pid': 1234, 'created': 1000.0}), encoding='utf-8')
        with patch.object(psutil, 'Process', return_value=SimpleNamespace(create_time=lambda: 1000.0)):
            self.assertTrue(maintenance.active(self.root))
        with patch.object(psutil, 'Process', return_value=SimpleNamespace(create_time=lambda: 1001.0)):
            self.assertFalse(maintenance.active(self.root))
        with patch.object(psutil, 'Process', side_effect=psutil.NoSuchProcess(1234)):
            self.assertFalse(maintenance.active(self.root))
        with patch.object(psutil, 'Process', side_effect=psutil.AccessDenied(1234)):
            self.assertTrue(maintenance.active(self.root))
        self.marker.write_text('invalid JSON', encoding='utf-8')
        self.assertTrue(maintenance.active(self.root))

    def test_switching_marker_is_cleared_on_success_and_exception(self):
        with maintenance.switching(self.root):
            self.assertTrue(maintenance.active(self.root))
            with self.assertRaisesRegex(RuntimeError, 'Another model switch'):
                with maintenance.switching(self.root): pass
        self.assertFalse(self.marker.exists())
        with self.assertRaisesRegex(RuntimeError, 'fixture failure'):
            with maintenance.switching(self.root):
                raise RuntimeError('fixture failure')
        self.assertFalse(self.marker.exists())

    def test_switching_does_not_remove_another_owners_marker(self):
        with maintenance.switching(self.root):
            content = json.loads(self.marker.read_text())
            content['token'] = 'different-owner'
            self.marker.write_text(json.dumps(content), encoding='utf-8')
        self.assertTrue(self.marker.exists())
        self.assertEqual(json.loads(self.marker.read_text())['token'], 'different-owner')


class AdmissionGate(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='model-gate-asgi-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.started, self.release = asyncio.Event(), asyncio.Event()
        self.stream = self.fail = False
        self.app = FastAPI()
        async def complete():
            if self.fail: raise RuntimeError('fixture handler failure')
            if self.stream:
                async def chunks():
                    self.started.set()
                    await self.release.wait()
                    yield b'fixture stream complete'
                return StreamingResponse(chunks(), media_type='text/plain')
            return {'fixture': 'complete'}
        for route in ['/api/chat/completions', '/api/v1/chat/completions']:
            self.app.add_api_route(route, complete, methods=['POST'])
        auth = ModuleType('open_webui.utils.auth')
        async def verified(): return SimpleNamespace(id='fixture-user')
        auth.get_verified_user = verified
        self.auth_modules = {'open_webui': ModuleType('open_webui'), 'open_webui.utils': ModuleType('open_webui.utils'), 'open_webui.utils.auth': auth}
        with patch.dict(sys.modules, self.auth_modules):
            maintenance.install(self.app, self.root)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app, raise_app_exceptions=False), base_url='http://fixture.invalid')
        self.addAsyncCleanup(self.client.aclose)

    async def test_both_chat_routes_reject_during_switch_then_resume(self):
        with maintenance.switching(self.root):
            for route in ['/api/chat/completions', '/api/v1/chat/completions']:
                response = await self.client.post(route, json={})
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.headers['Retry-After'], '5')
                self.assertEqual(self.app.state.studio_admitted_chats, 0)
            state = (await self.client.get('/api/local-studio/model-maintenance')).json()
            self.assertTrue(state['admission_gate'])
            self.assertTrue(state['switching'])
            self.assertEqual(state['admitted_chats'], 0)
        for route in ['/api/chat/completions', '/api/v1/chat/completions']:
            self.assertEqual((await self.client.post(route, json={})).status_code, 200)
        self.assertEqual(self.app.state.studio_admitted_chats, 0)

    async def test_admitted_stream_remains_counted_until_asgi_completion(self):
        self.stream = True
        pending = asyncio.create_task(self.client.post('/api/chat/completions', json={}))
        self.addAsyncCleanup(self.cancel_pending, pending)
        await asyncio.wait_for(self.started.wait(), timeout=2)
        self.assertEqual(self.app.state.studio_admitted_chats, 1)
        with maintenance.switching(self.root):
            self.assertEqual((await self.client.post('/api/v1/chat/completions', json={})).status_code, 503)
            state = (await self.client.get('/api/local-studio/model-maintenance')).json()
            self.assertEqual(state['admitted_chats'], 1)
            self.release.set()
            response = await asyncio.wait_for(pending, timeout=2)
            self.assertEqual(response.text, 'fixture stream complete')
            self.assertEqual(self.app.state.studio_admitted_chats, 0)

    async def cancel_pending(self, task):
        if not task.done():
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass

    async def test_handler_failure_releases_counter(self):
        self.fail = True
        response = await self.client.post('/api/chat/completions', json={})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.app.state.studio_admitted_chats, 0)

    async def test_install_is_idempotent_and_requires_both_routes(self):
        with patch.dict(sys.modules, self.auth_modules):
            maintenance.install(self.app, self.root)
            missing = FastAPI()
            missing.add_api_route('/api/chat/completions', lambda: {}, methods=['POST'])
            with self.assertRaisesRegex(RuntimeError, 'routes are missing'):
                maintenance.install(missing, self.root)
        self.assertEqual(sum(getattr(route, 'path', None) == '/api/local-studio/model-maintenance' for route in self.app.router.routes), 1)
        self.assertEqual((await self.client.post('/api/chat/completions', json={})).status_code, 200)
        self.assertEqual(self.app.state.studio_admitted_chats, 0)

    async def test_maintenance_api_precedes_spa_mount_on_first_and_repeated_install(self):
        app = FastAPI()
        async def complete(): return {'fixture': 'chat'}
        async def spa(request): return HTMLResponse('<html>fixture SPA fallback</html>')
        for path in ['/api/chat/completions', '/api/v1/chat/completions']:
            app.add_api_route(path, complete, methods=['POST'])
        root_mount = Mount('/', app=Starlette(routes=[Route('/{path:path}', spa)]))
        app.router.routes.append(root_mount)
        verified = self.auth_modules['open_webui.utils.auth'].get_verified_user
        authenticated = []
        async def override_verified():
            authenticated.append(True)
            return SimpleNamespace(id='fixture-authenticated-user')
        app.dependency_overrides[verified] = override_verified
        endpoint_path = '/api/local-studio/model-maintenance'
        with patch.dict(sys.modules, self.auth_modules):
            maintenance.install(app, self.root)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture.invalid') as client:
            response = await client.get(endpoint_path)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.headers['Content-Type'].startswith('application/json'))
            self.assertEqual(response.json(), {'admission_gate': True, 'switching': False, 'admitted_chats': 0})
            endpoint = next(route for route in app.router.routes if getattr(route, 'path', None) == endpoint_path)
            self.assertLess(app.router.routes.index(endpoint), app.router.routes.index(root_mount))
            self.assertEqual(len(authenticated), 1)

            # Reproduce an older live registration hidden behind the SPA mount.
            app.router.routes.remove(endpoint)
            app.router.routes.append(endpoint)
            hidden = await client.get(endpoint_path)
            self.assertEqual(hidden.status_code, 200)
            self.assertTrue(hidden.headers['Content-Type'].startswith('text/html'))
            self.assertEqual(len(authenticated), 1)
            with patch.dict(sys.modules, self.auth_modules):
                maintenance.install(app, self.root)
                maintenance.install(app, self.root)
            self.assertEqual(sum(getattr(route, 'path', None) == endpoint_path for route in app.router.routes), 1)
            self.assertLess(app.router.routes.index(endpoint), app.router.routes.index(root_mount))
            response = await client.get(endpoint_path)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.headers['Content-Type'].startswith('application/json'))
            self.assertEqual(response.json(), {'admission_gate': True, 'switching': False, 'admitted_chats': 0})
            self.assertEqual(len(authenticated), 2)
            for path in ['/api/chat/completions', '/api/v1/chat/completions']:
                self.assertEqual((await client.post(path, json={})).json(), {'fixture': 'chat'})
            self.assertEqual(app.state.studio_admitted_chats, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
