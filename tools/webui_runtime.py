"""Small version-checked Open WebUI adapter; installed package files stay untouched."""
import asyncio
from contextvars import ContextVar
from functools import wraps
import json
import time

current_run = ContextVar('studio_run', default=None)
runs = {}


def phase(value, tool=None):
    run = current_run.get()
    if run:
        run.update(phase=value, updated=time.time())
        if tool is not None:
            run['tool'] = tool


async def background_operation(function, *args, **kwargs):
    """Cancellation cannot kill a Python worker thread. Wait and show that fact."""
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(task)
            break
        except asyncio.CancelledError:
            cancelled = True
            phase('stopping')
            if task.done():
                break
        except Exception:
            if cancelled:
                raise asyncio.CancelledError()
            raise
    if cancelled:
        # Retrieve exceptions even when cancellation and completion coincide.
        if task.done() and not task.cancelled():
            task.exception()
        raise asyncio.CancelledError()
    return result


def estimate_tokens(value):
    # Upstream len(text)//4 undercounts Japanese; reserve space for native tools.
    if value is None:
        return 0
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False)
    non_ascii = sum(ord(c) > 127 for c in value)
    return max(1, (len(value) - non_ascii + 2) // 3 + (non_ascii * 3 + 1) // 2)


def bound_file_history(form):
    """Shorten older retrieved data only; never remove user/system instructions."""
    messages = form.get('messages', [])
    names = {c.get('id'): c.get('function', {}).get('name', '')
             for m in messages for c in m.get('tool_calls', [])}
    matches = [i for i, m in enumerate(messages) if m.get('role') == 'tool'
               and names.get(m.get('tool_call_id'), '').split('__')[-1] in
               {'read_workspace_file', 'search_workspace', 'list_workspace'}
               and isinstance(m.get('content'), str)]
    if len(matches) < 2:
        return form
    copy = [{**m} for m in messages]
    budget = 1200
    for i in reversed(matches[:-1]):
        content = copy[i]['content']
        limit = min(600, budget)
        budget -= min(limit, len(content))
        if len(content) > limit:
            copy[i]['content'] = content[:limit] + '\n[Older excerpt shortened to fit context. Re-read the source or search for details; this is not the whole file.]'
    return {**form, 'messages': copy}


def public_state(run):
    now = time.time()
    return {k: run[k] for k in ('chat_id', 'run_id', 'phase', 'tool', 'active', 'error')} | {
        'elapsed_seconds': int(now - run['started']),
        'quiet_seconds': int(now - run['updated']),
    }


def install():
    from importlib.metadata import version
    from pathlib import Path
    from fastapi import Depends
    from starlette.responses import JSONResponse, Response, StreamingResponse
    import open_webui.main as main
    import open_webui.utils.middleware as middleware
    import open_webui.utils.context_compaction as compaction
    from open_webui.utils.auth import get_verified_user
    from webui_queue_patch import patch_bundle

    if version('open-webui') != '0.11.4':
        raise RuntimeError('Local Studio adapter requires Open WebUI 0.11.4; review compatibility before upgrading.')
    asset = Path(main.__file__).parent / 'frontend/_app/immutable/chunks/DUmjoMyK.js'
    patched = patch_bundle(asset.read_text(encoding='utf-8'))
    compaction._estimate_tokens = estimate_tokens

    original_payload = main.process_chat_payload
    @wraps(original_payload)
    async def payload(request, form_data, user, metadata, model):
        chat = metadata.get('chat_id')
        if not chat:
            return await original_payload(request, form_data, user, metadata, model)
        run = {'chat_id': chat, 'run_id': metadata.get('message_id'), 'user_id': user.id,
               'phase': 'preparing', 'tool': '', 'active': True, 'error': '',
               'started': time.time(), 'updated': time.time()}
        # The native task owns this ContextVar; tool threads inherit its snapshot.
        current_run.set(run)
        runs[chat] = run
        for key in list(runs):
            if len(runs) <= 128:
                break
            if not runs[key]['active']:
                del runs[key]
        def ended(task):
            run['active'] = False
            run['updated'] = time.time()
            if task.cancelled():
                run['phase'] = 'stopped'
            elif run['phase'] != 'error':
                run['phase'] = 'error' if task.exception() else 'completed'
        asyncio.current_task().add_done_callback(ended)
        try:
            return await original_payload(request, form_data, user, metadata, model)
        except Exception:
            phase('error'); run['error'] = '送信準備に失敗しました。チャットのエラー表示を確認してください。'
            raise
    main.process_chat_payload = payload

    original_generate = main.chat_completion_handler
    @wraps(original_generate)
    async def generate(request, form_data, user, **kwargs):
        phase('thinking', '')
        try:
            response = await original_generate(request, bound_file_history(form_data), user, **kwargs)
            if isinstance(response, JSONResponse) and response.status_code >= 400:
                phase('error')
                run = current_run.get()
                if run:
                    detail = response.body.decode('utf-8', 'replace')
                    run['error'] = ('一度に読む量がモデルの上限を超えました。範囲を絞るか新しいチャットで続けてください。'
                                    if 'context' in detail.lower() else 'モデルへの要求が失敗しました。チャットのエラー表示を確認してください。')
            elif isinstance(response, StreamingResponse):
                original = response.body_iterator
                async def progress():
                    try:
                        async for chunk in original:
                            phase('generating')
                            yield chunk
                    finally:
                        if hasattr(original, 'aclose'):
                            await original.aclose()
                response.body_iterator = progress()
            return response
        except Exception:
            phase('error')
            run = current_run.get()
            if run:
                run['error'] = '応答の処理に失敗しました。チャットのエラー表示を確認してください。'
            raise
    main.chat_completion_handler = generate
    middleware.generate_chat_completion = generate

    original_response = main.process_chat_response
    @wraps(original_response)
    async def process_response(response, ctx):
        try:
            return await original_response(response, ctx)
        except Exception:
            phase('error')
            run = current_run.get()
            if run:
                run['error'] = '応答の処理に失敗しました。チャットのエラー表示を確認してください。'
            raise
    main.process_chat_response = process_response

    original_update = middleware.get_updated_tool_function
    @wraps(original_update)
    async def update(function, extra_params):
        result = await original_update(function, extra_params)
        name = getattr(getattr(function, '__function__', function), '__name__', 'tool')
        @wraps(result)
        async def tracked(*args, **kwargs):
            phase('tool', name)
            try:
                value = await result(*args, **kwargs)
                if isinstance(value, dict) and value.get('error'):
                    run = current_run.get()
                    if run:
                        run['error'] = 'ファイル調査で問題がありました。エージェントへ理由と次の確認方法を返しました。'
                return value
            finally:
                if current_run.get() and current_run.get()['phase'] != 'stopping':
                    phase('thinking', '')
        return tracked
    middleware.get_updated_tool_function = update

    @main.app.get('/api/local-studio/activity')
    async def activity(chat_id: str = '', user=Depends(get_verified_user)):
        available = [r for r in runs.values() if r['user_id'] == user.id]
        selected = next((r for r in available if r['chat_id'] == chat_id), None)
        return {'state': public_state(selected) if selected else None,
                'active_count': sum(r['active'] for r in available), 'queue_fix': True}
    main.app.router.routes.insert(0, main.app.router.routes.pop())

    @main.app.get('/_app/immutable/chunks/DUmjoMyK.js', include_in_schema=False)
    async def queue_asset():
        return Response(patched, media_type='application/javascript', headers={'Cache-Control': 'no-store'})
    main.app.router.routes.insert(0, main.app.router.routes.pop())
