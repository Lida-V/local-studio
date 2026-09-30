"""Read installed model profiles and validate local artifacts without activation."""
from copy import deepcopy
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
from stat import S_ISREG


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
        for role in ('model', 'mmproj'):
            artifact = profile.get(role)
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
    for role in ('model', 'mmproj'):
        artifact = profile[role]
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


def apply(config, profile) -> dict:
    """Return a new configuration with only modelPath and mmprojPath replaced."""
    artifacts = paths(config, profile)
    result = deepcopy(config)
    result['inference']['modelPath'] = str(artifacts['model'])
    result['inference']['mmprojPath'] = str(artifacts['mmproj'])
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
        try:
            paths(config, profile)
        except (OSError, ValueError) as error:
            row['unavailable_reason'] = type(error).__name__
        else:
            row['installed'] = True
        result.append(row)
    return result
