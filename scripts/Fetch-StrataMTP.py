"""Fetch only the pinned 31 MTP tensors, retaining the upstream pack format."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

SUPPORT = Path(__file__).resolve().parents[1]


class PreserveFiles:
    """Keep a corrupt resumed tensor for inspection instead of upstream deletion."""
    def __getattr__(self, name):
        return getattr(os, name)

    def remove(self, path):
        raise RuntimeError('Unverified MTP tensor retained; inspect before retrying: ' + str(path))


def main():
    config = json.loads((SUPPORT / 'config/support-config.json').read_text(encoding='utf-8-sig'))
    configured = Path(config['target']['root'])
    if not configured.is_absolute() or str(configured).startswith(('\\\\', '//')):
        raise ValueError('A dedicated absolute local root is required.')
    root = configured.resolve()
    source = (root / 'apps/Strata/source').resolve()
    out = (root / 'models/Qwen3.8-Flash-Next/mtp').resolve()
    if not source.is_relative_to(root / 'apps') or not out.is_relative_to(root / 'models'):
        raise ValueError('Strata source or MTP data escaped its dedicated folder.')
    for relative in ('tensors', 'mtp-inventory.json', 'mtp-manifest.json'):
        if not (out / relative).resolve().is_relative_to(out):
            raise ValueError('MTP path escapes through a link.')
    head = subprocess.check_output(['git', '-c', 'safe.directory=' + str(source), '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if head != '6f32ec070f23ced9f50e704d854d775da52591ab':
        raise RuntimeError('MTP fetch requires the pinned Strata 0.1.39 checkout.')
    subprocess.run(['git', '-c', 'safe.directory=' + str(source), '-C', str(source), 'diff', '--quiet', 'HEAD', '--'], check=True)
    manifest = json.loads((SUPPORT / 'config/strata-download-manifest.json').read_text(encoding='utf-8-sig'))['mtp']
    spec = importlib.util.spec_from_file_location('pinned_mtp_fetch', source / 'tools/mtp_fetch.py')
    fetch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fetch)
    fetch.os = PreserveFiles()
    expected_prefix = 'https://huggingface.co/Qwen/Qwen3.8-Flash-Next/resolve/' + fetch.PINNED_REVISION + '/'
    if manifest['tensorUrlPrefix'] != expected_prefix or manifest['revision'] != fetch.PINNED_REVISION:
        raise RuntimeError('MTP manifest and pinned source revisions differ.')
    rows = []
    for tensor in manifest['tensors']:
        if fetch.SHA256.get(tensor['name']) != tensor['sha256'] or tensor['end'] - tensor['start'] + 1 != tensor['size']:
            raise RuntimeError('MTP tensor range/hash differs from the fixed manifest.')
        path = (out / 'tensors' / (tensor['name'] + '.bin')).resolve()
        if not path.is_relative_to(out / 'tensors'):
            raise ValueError('MTP tensor path escaped its folder.')
        if path.exists() and (path.stat().st_size > tensor['size'] or
                path.stat().st_size == tensor['size'] and fetch.sha256_of(path) != tensor['sha256']):
            raise RuntimeError('Existing incompatible tensor retained: ' + tensor['name'])
        rows.append({key: tensor[key] for key in ('name', 'shard', 'dtype', 'shape', 'start', 'end')} | {'bytes': tensor['size']})
    if len(rows) != 31 or len({r['name'] for r in rows}) != 31 or sum(r['bytes'] for r in rows) != manifest['downloadBytes']:
        raise RuntimeError('Incomplete pinned MTP manifest.')
    inventory = {'repo': expected_prefix, 'total_bytes': manifest['downloadBytes'], 'tensors': rows}
    out.mkdir(parents=True, exist_ok=True)
    inventory_path = out / 'mtp-inventory.json'
    if inventory_path.exists():
        if json.loads(inventory_path.read_text(encoding='utf-8')) != inventory:
            raise RuntimeError('An incompatible MTP inventory is retained; inspect it before retrying.')
    else:
        inventory_path.write_text(json.dumps(inventory, indent=1), encoding='utf-8')
    fetch.REPO = fetch.PINNED = expected_prefix
    allowed_urls = {expected_prefix + r['shard'] for r in rows}

    def bounded_range(url, start=None, end=None, retries=2):
        if (url not in allowed_urls or type(start) is not int or type(end) is not int or
                start < 0 or end < start or end - start + 1 > 64 << 20):
            raise ValueError('Only bounded ranges from the pinned checkpoint are allowed.')
        for attempt in range(2):
            try:
                request = urllib.request.Request(url, headers={'User-Agent': 'LocalStudio-MTP/1.0',
                    'Range': f'bytes={start}-{end}', 'Accept-Encoding': 'identity'})
                with urllib.request.urlopen(request, timeout=45) as response:
                    fetch.check_range(response.status, response.headers.get('Content-Range'), start, end)
                    if response.headers.get('Content-Encoding', '').lower() not in ('', 'identity'):
                        raise IOError('Encoded MTP range rejected.')
                    data = response.read(end - start + 2)
                if len(data) != end - start + 1:
                    raise IOError('Incomplete or oversized MTP range.')
                return data
            except Exception:
                if attempt: raise

    fetch.get = bounded_range
    # Call fetch directly: never use resolve_repo's fallback to a floating main.
    fetch.fetch(str(out), None)
    for tensor in manifest['tensors']:
        path = out / 'tensors' / (tensor['name'] + '.bin')
        if path.stat().st_size != tensor['size'] or fetch.sha256_of(path) != tensor['sha256']:
            raise RuntimeError('Final MTP size/hash verification failed.')
    print(json.dumps({'mtp_tensors_verified': 31, 'bytes': manifest['downloadBytes'],
                      'revision': manifest['revision'], 'full_checkpoint_downloaded': False}), flush=True)


if __name__ == '__main__':
    import msvcrt
    config = json.loads((SUPPORT / 'config/support-config.json').read_text(encoding='utf-8-sig'))
    lock_path = Path(config['target']['root']) / 'runtime/strata-mtp.lock'
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open('a+b') as lease:
        lease.seek(0)
        msvcrt.locking(lease.fileno(), msvcrt.LK_NBLCK, 1)
        try: main()
        finally:
            lease.seek(0)
            msvcrt.locking(lease.fileno(), msvcrt.LK_UNLCK, 1)
