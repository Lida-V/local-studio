"""Brief admission gate for local chat requests while an installed model switches."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import time
import uuid


def active(root) -> bool:
    marker = Path(root) / 'runtime/model-switch.json'
    if not marker.exists(): return False
    import psutil
    try:
        value = json.loads(marker.read_text(encoding='utf-8'))
        return abs(psutil.Process(value['pid']).create_time() - value['created']) < 0.01
    except (KeyError, TypeError, ValueError, OSError):
        return True  # Malformed state is unknown, not an idle switch.
    except psutil.NoSuchProcess:
        return False
    except psutil.Error:
        return True


@contextmanager
def switching(root):
    root = Path(root)
    marker = root / 'runtime/model-switch.json'
    marker.parent.mkdir(parents=True, exist_ok=True)
    if active(root): raise RuntimeError('Another model switch is active or its state is unknown.')
    import psutil
    token = uuid.uuid4().hex
    value = {'pid': os.getpid(), 'created': psutil.Process().create_time(), 'token': token, 'started': time.time()}
    temporary = marker.with_suffix('.tmp')
    temporary.write_text(json.dumps(value), encoding='utf-8')
    temporary.replace(marker)
    try: yield
    finally:
        if marker.exists() and json.loads(marker.read_text(encoding='utf-8')).get('token') == token:
            marker.unlink()


def install(app, root):
    """Wrap existing ASGI route handlers; can be installed by a live toolkit update."""
    def order_endpoint():
        routes = app.router.routes
        endpoint = next(route for route in routes if getattr(route, 'path', None) == '/api/local-studio/model-maintenance')
        routes.remove(endpoint)
        # Open WebUI mounts its SPA at /. Routes appended after it return HTML.
        index = next((i for i, route in enumerate(routes) if getattr(route, 'path', None) in ('', '/')), len(routes))
        routes.insert(index, endpoint)
    if getattr(app.state, 'studio_model_admission_gate', False):
        order_endpoint()
        return
    from starlette.responses import JSONResponse
    from fastapi import Depends
    from open_webui.utils.auth import get_verified_user
    targets = {'/api/chat/completions', '/api/v1/chat/completions'}
    matches = [route for route in app.router.routes if getattr(route, 'path', None) in targets]
    if {route.path for route in matches} != targets:
        raise RuntimeError('Expected Local Studio chat routes are missing; model switching disabled.')
    def wrap(original):
        async def gated(scope, receive, send):
            if active(root):
                response = JSONResponse({'detail': 'モデルを切り替えています。完了後に送信してください。'}, status_code=503, headers={'Retry-After': '5'})
                return await response(scope, receive, send)
            app.state.studio_admitted_chats += 1
            try: return await original(scope, receive, send)
            finally: app.state.studio_admitted_chats -= 1
        return gated
    app.state.studio_admitted_chats = 0
    for route in matches: route.app = wrap(route.app)

    async def state(user=Depends(get_verified_user)):
        return {'admission_gate': True, 'switching': active(root), 'admitted_chats': app.state.studio_admitted_chats}
    app.add_api_route('/api/local-studio/model-maintenance', state, methods=['GET'])
    order_endpoint()
    app.state.studio_model_admission_gate = True
