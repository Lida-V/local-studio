"""Read installed model profiles and validate local artifacts without activation."""
from copy import deepcopy
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
from stat import S_ISREG


def artifacts(profile):
    """Named pinned artifacts, including all shards required by an optional backend."""
    result = {role: profile.get(role) for role in ('model', 'mmproj')}
    extra = profile.get('additionalArtifacts', [])
    if not isinstance(extra, list): raise ValueError('Additional artifacts must be a list.')
    for artifact in extra:
        if not isinstance(artifact, dict): raise ValueError('Additional artifacts must be objects.')
        key = artifact.get('key')
        if not isinstance(key, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,31}', key) or key in result:
            raise ValueError('Additional artifact keys must be unique identifiers.')
        result[key] = artifact
    return result


def _entries(catalog):
    if not isinstance(catalog, dict) or not isinstance(catalog.get('profiles'), list):
        raise ValueError('Model catalog must contain a profiles list.')
    entries = catalog['profiles']
    ids = []
    for profile in entries:
        if not isinstance(profile, dict) or not isinstance(profile.get('id'), str) or not profile['id']:
            raise ValueError('Each model profile needs a nonempty id.')
        ids.append(profile['id'])
        if not isinstance(profile.get('label'), str):
            raise ValueError('Each model profile needs a label.')
        for role, artifact in artifacts(profile).items():
            if not isinstance(artifact, dict) or not isinstance(artifact.get('path'), str):
                raise ValueError('Each model profile needs model and mmproj artifact paths.')
            if type(artifact.get('size')) is not int or artifact['size'] <= 0:
                raise ValueError('Artifact expected sizes must be positive integers.')
            if not isinstance(artifact.get('sha256'), str) or not re.fullmatch(r'[0-9a-fA-F]{64}', artifact['sha256']):
                raise ValueError('Artifact expected hashes must be SHA256 hex strings.')
        if not isinstance(profile.get('source'), dict):
            raise ValueError('Each model profile needs source metadata.')
    if len(set(ids)) != len(ids):
        raise ValueError('Model profile ids must be unique.')
    return entries


def read_catalog(support) -> dict:
    """Load only the supporter's fixed catalog file; never retrieve model files."""
    catalog = json.loads((Path(support) / 'config/model-profiles.json').read_text(encoding='utf-8-sig'))
    _entries(catalog)
    return catalog


def choose(catalog, profile_id) -> dict:
    """Return the named profile; an unknown id is never interpreted as a path."""
    entries = _entries(catalog)
    if not isinstance(profile_id, str):
        raise ValueError('Unknown model profile id.')
    matches = [profile for profile in entries if profile['id'] == profile_id]
    if len(matches) != 1:
        raise ValueError('Unknown model profile id.')
    return matches[0]


def _artifact_path(config, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or '\x00' in relative:
        raise ValueError('Artifact paths must be relative paths below models.')
    windows = PureWindowsPath(relative)
    portable = PurePosixPath(relative.replace('\\', '/'))
    if windows.drive or windows.root or portable.is_absolute() or ':' in relative:
        raise ValueError('Absolute, drive-relative and stream artifact paths are rejected.')
    if '..' in portable.parts or len(portable.parts) < 2 or portable.parts[0].casefold() != 'models':
        raise ValueError('Artifact paths must stay below the models folder without traversal.')
    configured_root = Path(config['target']['root'])
    if not configured_root.is_absolute() or str(configured_root).startswith(('\\\\', '//')):
        raise ValueError('The configured model root must be an absolute local folder.')
    root = configured_root.resolve()
    models_root = (root / 'models').resolve()
    if models_root == root or not models_root.is_relative_to(root):
        raise ValueError('The models folder resolves outside the configured root.')
    artifact_path = (root / Path(*portable.parts)).resolve()
    if artifact_path == models_root or not artifact_path.is_relative_to(models_root):
        raise ValueError('Artifact path or link resolves outside the models folder.')
    return artifact_path


def paths(config, profile) -> dict:
    """Validate files and exact expected sizes; activation performs SHA256 separately."""
    result = {}
    for role, artifact in artifacts(profile).items():
        if type(artifact.get('size')) is not int or artifact['size'] <= 0:
            raise ValueError('Artifact expected sizes must be positive integers.')
        path = _artifact_path(config, artifact['path'])
        info = path.stat()
        if not S_ISREG(info.st_mode):
            raise ValueError(role + ' artifact must be a file.')
        if info.st_size != artifact['size']:
            raise ValueError(role + ' artifact size does not match the catalog.')
        result[role] = path
    return result


def identify(config, catalog):
    """Return the profile id matching the active model path, even if its file is missing."""
    entries = _entries(catalog)
    active = config.get('inference', {}).get('modelPath')
    if not isinstance(active, str) or not active or not Path(active).is_absolute():
        return None
    active = Path(active).resolve()
    for profile in entries:
        try:
            candidate = _artifact_path(config, profile['model']['path'])
        except (OSError, ValueError):
            continue
        if active == candidate:
            return profile['id']
    return None


def runtime_path(config, relative, folder, directory=False):
    """Resolve optional backend paths only inside the dedicated installation."""
    if not isinstance(relative, str) or not relative or ':' in relative or '\x00' in relative:
        raise ValueError('Backend paths must be relative installation paths.')
    portable = PurePosixPath(relative.replace('\\', '/'))
    windows = PureWindowsPath(relative)
    if portable.is_absolute() or windows.root or windows.drive or '..' in portable.parts or not portable.parts or portable.parts[0] != folder:
        raise ValueError('Backend path escaped its dedicated installation folder.')
    configured_root = Path(config['target']['root'])
    if not configured_root.is_absolute() or str(configured_root).startswith(('\\\\', '//')):
        raise ValueError('The configured runtime root must be an absolute local folder.')
    root = configured_root.resolve()
    path = (root / Path(*portable.parts)).resolve()
    boundary = (root / folder).resolve()
    if boundary == root or not boundary.is_relative_to(root) or path == boundary or not path.is_relative_to(boundary):
        raise ValueError('Backend path or link escaped the configured root.')
    if not (path.is_dir() if directory else path.is_file()):
        raise FileNotFoundError('Backend file/directory is not prepared: ' + relative)
    return path


def apply(config, profile) -> dict:
    """Preserve unrelated settings and select a validated optional runtime, if specified."""
    resolved = paths(config, profile)
    result = deepcopy(config)
    result['inference']['modelPath'] = str(resolved['model'])
    result['inference']['mmprojPath'] = str(resolved['mmproj'])
    backend = profile.get('backend')
    if backend is not None:
        if not isinstance(backend, dict) or backend.get('kind') not in ('llama.cpp', 'strata'):
            raise ValueError('Unknown model runtime backend.')
        context = backend.get('contextSize')
        if type(context) is not int or not 8192 <= context <= 262144:
            raise ValueError('Backend context must be within the native supported range.')
        kind = backend['kind']
        folder = 'apps' if kind == 'strata' else 'bin'
        result['target']['executable'] = str(runtime_path(config, backend.get('executable'), folder))
        result['inference']['backend'] = kind
        result['inference']['contextSize'] = context
        if kind == 'strata':
            result['strata'] = {**result.get('strata', {}),
                'sourceRoot': str(runtime_path(config, backend.get('sourceRoot'), 'apps', True)),
                'serverConfigPath': str(runtime_path(config, backend.get('serverConfigPath'), 'apps'))}
    return result


def profiles(support, config) -> list:
    """List catalog status without loading a model, hashing it, or changing settings."""
    catalog = read_catalog(support)
    active = identify(config, catalog)
    result = []
    for profile in catalog['profiles']:
        row = {
            'id': profile['id'], 'label': profile['label'],
            'active': profile['id'] == active, 'installed': False,
            'model': deepcopy(profile['model']), 'mmproj': deepcopy(profile['mmproj']),
            'source': deepcopy(profile['source']), 'license': deepcopy(profile.get('license')),
        }
        if 'backend' in profile: row['backend'] = deepcopy(profile['backend'])
        if 'additionalArtifacts' in profile: row['additionalArtifacts'] = deepcopy(profile['additionalArtifacts'])
        try:
            apply(config, profile)
        except (OSError, ValueError) as error:
            row['unavailable_reason'] = type(error).__name__
        else:
            row['installed'] = True
        result.append(row)
    return result
