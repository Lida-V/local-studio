"""Download the pinned, optional Huihui GGUF; preserve the existing model and app data."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import urllib.request

SUPPORT = Path(__file__).resolve().parents[1]
MANIFEST = SUPPORT / 'config/huihui-download-manifest.json'
sys.path.insert(0, str(SUPPORT / 'tools'))
from range_download import download


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(16 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def main():
    config = json.loads((SUPPORT / 'config/support-config.json').read_text(encoding='utf-8-sig'))
    root = Path(config['target']['root']).resolve()
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8-sig'))
    entry = manifest['files'][0]
    destination = (root / entry['folder'] / entry['name']).resolve()
    partial = (root / 'downloads/huihui' / (entry['name'] + '.part')).resolve()
    if not destination.is_relative_to(root / 'models') or not partial.is_relative_to(root / 'downloads'):
        raise ValueError('Manifest artifact escaped the model/download directories.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.stat().st_size != entry['size'] or sha256(destination) != entry['sha256']:
            raise RuntimeError('Existing destination differs; it was preserved for inspection.')
    else:
        remaining = entry['size'] - (partial.stat().st_size if partial.exists() else 0)
        if shutil.disk_usage(root).free < remaining + 5 * 1024**3:
            raise RuntimeError('Insufficient space for the optional model and a 5 GiB margin.')
        download(entry, partial)
        print('Verifying complete artifact size and SHA256...', flush=True)
        if partial.stat().st_size != entry['size'] or sha256(partial) != entry['sha256']:
            raise RuntimeError('Downloaded artifact failed verification; partial retained.')
        if destination.exists():
            raise RuntimeError('Destination appeared during download; both files preserved.')
        partial.rename(destination)
    # Keep the upstream license with this installed artifact; execute no remote code.
    license_path = destination.parent / 'LICENSE'
    expected_license_hash = 'bbedc3fda3305820b977265f01b8619d87570a6739de3a5582c3464840f1e57a'
    if not license_path.exists():
        url = 'https://huggingface.co/huihui-ai/Huihui-Qwen3.8-27B-abliterated/resolve/739e3c5b89849f6c238ce1e5b70008612ae42cdd/LICENSE'
        with urllib.request.urlopen(url, timeout=45) as response:
            data = response.read(20000)
        if hashlib.sha256(data).hexdigest() != expected_license_hash:
            raise RuntimeError('Upstream license differs from the reviewed revision.')
        with license_path.open('xb') as stream:
            stream.write(data)
    elif sha256(license_path) != expected_license_hash:
        raise RuntimeError('Existing license differs; it was preserved.')
    print(json.dumps({'installed': True, 'model': entry['name'], 'bytes': entry['size'],
        'sha256_verified': True, 'license_retained': True,
        'existing_model_preserved': True, 'activated': False}), flush=True)


if __name__ == '__main__': main()
