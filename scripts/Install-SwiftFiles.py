"""Download pinned Swift files without activating, overwriting or deleting models."""
import importlib.util
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import sys

SUPPORT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SUPPORT / 'tools'))
from range_download import download

spec = importlib.util.spec_from_file_location('strata_files', SUPPORT / 'scripts/Install-StrataFiles.py')
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)


def confined(root, relative, area):
    raw = root / relative
    resolved = raw.resolve()
    if not resolved.is_relative_to((root / area).resolve()) or os.path.normcase(str(raw.absolute())) != os.path.normcase(str(resolved)):
        raise ValueError('Artifact escaped its dedicated directory or crosses a link.')
    return resolved


def install(root, entries):
    destinations = []
    remaining = 0
    for entry in entries:
        if Path(entry['name']).name != entry['name'] or '/' in entry['name'] or '\\' in entry['name']:
            raise ValueError('Manifest name is not a plain filename.')
        dest = confined(root, str(Path(entry['folder']) / entry['name']), 'models/Swift-1.5-Qwen3.8-Flash-Next')
        partial = confined(root, 'downloads/swift/' + entry['name'] + '.part', 'downloads/swift')
        if (dest.exists() and not dest.is_file()) or (partial.exists() and not partial.is_file()):
            raise ValueError('Artifact path must be a regular file.')
        partial_size = partial.stat().st_size if partial.exists() else 0
        if partial_size > entry['size']:
            raise RuntimeError('Oversized partial preserved for inspection.')
        if not dest.exists(): remaining += entry['size'] - partial_size
        destinations.append((entry, dest, partial))
    if shutil.disk_usage(root).free < remaining + 15 * 1024**3:
        raise RuntimeError('Insufficient space including preparation and 15GiB margin.')
    if len({dest for _, dest, _ in destinations}) != len(destinations):
        raise ValueError('Duplicate destination in manifest.')
    state = confined(root, 'runtime/swift-download.json', 'runtime')
    state.write_text(json.dumps({'phase': 'download', 'files': [e['name'] for e, _, _ in destinations], 'parallel_files': 2}), encoding='utf-8')

    def fetch(item):
        entry, dest, partial = item
        dest.parent.mkdir(parents=True, exist_ok=True)
        partial.parent.mkdir(parents=True, exist_ok=True)
        print(json.dumps({'phase': 'download', 'file': entry['name'], 'expected_bytes': entry['size']}), flush=True)
        if not dest.exists():
            if entry['name'].lower().endswith('.gguf'): download(entry, partial)
            else:
                for attempt in range(2):
                    try:
                        helpers.simple_download(entry, partial)
                        break
                    except Exception:
                        if attempt: raise
            print(json.dumps({'phase': 'sha256', 'file': entry['name']}), flush=True)
            if partial.stat().st_size != entry['size'] or helpers.digest(partial) != entry['sha256']:
                raise RuntimeError('Size/SHA256 mismatch; partial preserved: ' + entry['name'])
            if dest.exists(): raise RuntimeError('Destination appeared; both files preserved.')
            partial.rename(dest)
        elif dest.stat().st_size != entry['size'] or helpers.digest(dest) != entry['sha256']:
            raise RuntimeError('Existing file differs; retained: ' + entry['name'])
        print(json.dumps({'phase': 'verified', 'file': entry['name'], 'sha256': entry['sha256']}), flush=True)
    # Two independent files, each with a four-range / 256MiB bounded window.
    # At most eight requests and 512MiB of range buffers; a single OS lease
    # prevents competing installers. Only the parent writes the state file.
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix='swift-file') as pool:
        futures = [pool.submit(fetch, item) for item in destinations]
        failures = []
        for future in futures:
            try: future.result()
            except Exception as error:
                failures.append(type(error).__name__ + ': ' + str(error))
                error.__traceback__ = error.__context__ = error.__cause__ = None
        if failures: raise RuntimeError('; '.join(failures))
    state.write_text(json.dumps({'phase': 'verified', 'files': len(entries)}), encoding='utf-8')
    print(json.dumps({'files_verified': len(entries), 'activated': False, 'existing_models_preserved': True}), flush=True)


def main():
    import msvcrt
    config = json.loads((SUPPORT / 'config/support-config.json').read_text(encoding='utf-8-sig'))
    root = Path(config['target']['root']).resolve()
    manifest = json.loads((SUPPORT / 'config/swift-download-manifest.json').read_text(encoding='utf-8-sig'))
    lock_path = confined(root, 'runtime/swift-download.lock', 'runtime')
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open('a+b') as lease:
        lease.seek(0)
        msvcrt.locking(lease.fileno(), msvcrt.LK_NBLCK, 1)
        try: install(root, manifest['files'])
        finally:
            lease.seek(0)
            msvcrt.locking(lease.fileno(), msvcrt.LK_UNLCK, 1)


if __name__ == '__main__': main()
