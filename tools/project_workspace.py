"""Persistent user-selected project; operation snapshots never follow later switches."""
from contextlib import contextmanager
from contextvars import ContextVar
import json
from pathlib import Path
import uuid

_snapshot = ContextVar('local_studio_project', default=None)


def validate(path):
    p = Path(path)
    if not p.is_absolute() or str(p).startswith('\\\\'):
        raise ValueError('Select an existing local project folder using an absolute path.')
    p = p.resolve(strict=True)
    if not p.is_dir() or p == Path(p.anchor):
        raise ValueError('Select a project folder, not a drive root or a file.')
    return p


def current(studio):
    pinned = _snapshot.get()
    if pinned is not None:
        return validate(pinned)
    state = studio.ROOT / 'data/project-workspace.json'
    if state.exists():
        # Invalid or disconnected selections must never silently fall back.
        return validate(json.loads(state.read_text(encoding='utf-8'))['path'])
    studio.WORK.mkdir(parents=True, exist_ok=True)
    return studio.WORK.resolve()


def info(studio):
    p = current(studio)
    return {'path': str(p), 'name': p.name, 'default': p == studio.WORK.resolve(),
            'scope': 'all_chats', 'note': 'File tools use this folder. Queued jobs keep their submitted project.'}


def select(studio, path=None):
    if path is None:
        studio.WORK.mkdir(parents=True, exist_ok=True)
        path = studio.WORK
    p = validate(path)
    state = studio.ROOT / 'data/project-workspace.json'
    state.parent.mkdir(parents=True, exist_ok=True)
    temporary = state.with_name(state.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps({'path': str(p)}, ensure_ascii=False), encoding='utf-8')
        temporary.replace(state)
    finally:
        temporary.unlink(missing_ok=True)
    return info(studio)


def resolve(studio, relative, root=None):
    root = current(studio) if root is None else validate(root)
    relative = str(relative)
    if relative.startswith(('\\\\', '//')):
        raise ValueError('Network paths are not project file paths.')
    p = (root / relative).resolve()
    suffix = relative[len(Path(relative).drive):]
    if ':' in suffix or not p.is_relative_to(root) or (Path(relative).root and not Path(relative).drive) or (Path(relative).drive and not Path(relative).is_absolute()):
        raise ValueError('Use a relative path inside the selected project; outside paths and links are rejected.')
    return p


@contextmanager
def use(path):
    token = _snapshot.set(validate(path))
    try:
        yield
    finally:
        _snapshot.reset(token)
