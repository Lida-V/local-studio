"""Download and verify pinned Strata/Qwen assets; never activate or remove a model."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import urllib.request

SUPPORT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SUPPORT / 'tools'))
from range_download import download


def digest(path):
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(16 * 1024 * 1024): sha.update(block)
    return sha.hexdigest()


def simple_download(entry, partial):
    """Small release ZIP/license: streaming 200 or exact resumed range, never a hole."""
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > entry['size']: raise RuntimeError('Partial file exceeds pinned size; preserved.')
    if offset == entry['size']: return
    headers = {'User-Agent': 'LocalStudio-Installer/1.0', 'Accept-Encoding': 'identity'}
    if offset: headers['Range'] = f"bytes={offset}-{entry['size'] - 1}"
    request = urllib.request.Request(entry['url'], headers=headers)
    with urllib.request.urlopen(request, timeout=45) as response:
        if offset and (response.status != 206 or response.headers.get('Content-Range') != f"bytes {offset}-{entry['size'] - 1}/{entry['size']}"):
            raise RuntimeError('Server did not confirm the exact resumed range; partial preserved.')
        if not offset and response.status != 200:
            raise RuntimeError('Unexpected whole-file download response.')
        if response.headers.get('Content-Encoding', '').lower() not in ('', 'identity'):
            raise RuntimeError('Encoded download rejected.')
        with partial.open('ab', buffering=0) as stream:
            while block := response.read(1024 * 1024):
                if offset + len(block) > entry['size']: raise RuntimeError('Response exceeds pinned size.')
                stream.write(block)
                offset += len(block)
            os.fsync(stream.fileno())
    if offset != entry['size']: raise RuntimeError('Transfer incomplete; contiguous partial preserved.')


def main():
    config = json.loads((SUPPORT / 'config/support-config.json').read_text(encoding='utf-8-sig'))
    root = Path(config['target']['root']).resolve()
    manifest = json.loads((SUPPORT / 'config/strata-download-manifest.json').read_text(encoding='utf-8-sig'))
    entries = list(manifest['files'])
    entries.append({**manifest['license']['upstream'], 'name': 'LICENSE',
                    'folder': 'models/Qwen3.8-Flash-Next'})
    remaining = 0
    for entry in entries:
        destination = (root / entry['folder'] / entry['name']).resolve()
        partial = root / 'downloads/strata' / (entry['name'] + '.part')
        if not destination.is_relative_to(root / 'models') and not destination.is_relative_to(root / 'downloads/strata'):
            raise ValueError('Artifact escaped the dedicated model/download directories.')
        if not destination.exists(): remaining += entry['size'] - (partial.stat().st_size if partial.exists() else 0)
    if shutil.disk_usage(root).free < remaining + 15 * 1024**3:
        raise RuntimeError('Insufficient space for pinned assets, preparation and a 15GiB margin.')
    state = root / 'runtime/strata-download.json'
    state.parent.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        destination = (root / entry['folder'] / entry['name']).resolve()
        partial = root / 'downloads/strata' / (entry['name'] + '.part')
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps({'phase': 'download', 'file': entry['name'], 'bytes_expected': entry['size']}), encoding='utf-8')
        print(json.dumps({'phase': 'download', 'file': entry['name'], 'expected_bytes': entry['size']}), flush=True)
        if not destination.exists():
            if entry['name'].lower().endswith('.gguf'): download(entry, partial)
            else:
                for attempt in range(2):
                    try:
                        simple_download(entry, partial)
                        break
                    except Exception:
                        if attempt: raise
            print(json.dumps({'phase': 'sha256', 'file': entry['name']}), flush=True)
            if partial.stat().st_size != entry['size'] or digest(partial) != entry['sha256']:
                raise RuntimeError('Artifact failed complete size/SHA256 verification; partial retained: ' + entry['name'])
            if destination.exists(): raise RuntimeError('Destination appeared during download; both files preserved.')
            partial.rename(destination)
        elif destination.stat().st_size != entry['size'] or digest(destination) != entry['sha256']:
            raise RuntimeError('Existing destination differs; retained: ' + entry['name'])
        print(json.dumps({'phase': 'verified', 'file': entry['name'], 'sha256': entry['sha256']}), flush=True)
    state.write_text(json.dumps({'phase': 'verified', 'files': len(entries)}), encoding='utf-8')
    print(json.dumps({'files_verified': len(entries), 'activated': False, 'old_models_preserved': True}), flush=True)


if __name__ == '__main__':
    import msvcrt
    config = json.loads((SUPPORT / 'config/support-config.json').read_text(encoding='utf-8-sig'))
    lock_path = Path(config['target']['root']) / 'runtime/strata-download.lock'
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open('a+b') as lease:
        lease.seek(0)
        msvcrt.locking(lease.fileno(), msvcrt.LK_NBLCK, 1)
        try: main()
        finally:
            lease.seek(0)
            msvcrt.locking(lease.fileno(), msvcrt.LK_UNLCK, 1)
