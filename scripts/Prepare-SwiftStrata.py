"""Prepare the pinned Swift IQ3_XXS pack without changing the active model.

The default invocation verifies and prints a plan. --apply creates only Swift's
own pack, expert profile, server config and shared settings under target.root.
No downloads, global installs, server lifecycle operations or source edits occur.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import uuid

SUPPORT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = '6f32ec070f23ced9f50e704d854d775da52591ab'
SWIFT_REVISION = '70238546d13a135459cf25d7647c3690cb7e1165'
MODEL_NAME = 'swift1.5-qwen3.8-flash-next-iq3_xxs'
DATA_REL = 'models/Swift-1.5-Qwen3.8-Flash-Next'
SOURCE_REL = 'apps/Strata/source'
PACK_REL = DATA_REL + '/packs/iq3_xxs'
OLD_DATA_REL = 'models/Qwen3.8-Flash-Next'
BASE_CONFIG_REL = SOURCE_REL + '/strata-iq3_s.json'
OUTPUT_CONFIG_REL = SOURCE_REL + '/strata-swift-iq3_xxs.json'
SHARED_CONFIG_REL = SOURCE_REL + '/strata-swift-iq3_xxs.shared-settings.json'
STAMP_NAME = '.swift-source.json'
MODEL_FILES = (
    (DATA_REL + '/IQ3_XXS/Swift-Qwen3.8-Flash-Next-GSQ-RCO-abliterated-IQ3_XXS-00001-of-00002.gguf',
     39771812960, '83f75959e296a6380c98d5b6e906a0cde175077ffac2419fd56e7e15969d55dd'),
    (DATA_REL + '/IQ3_XXS/Swift-Qwen3.8-Flash-Next-GSQ-RCO-abliterated-IQ3_XXS-00002-of-00002.gguf',
     36056143040, 'aa59f45eaa3c02069016903862a5f8d73adfdb7ca97f9cab25f7494e9ac4b1a3'),
    (DATA_REL + '/mmproj-Qwen3.8-Flash-Next-BF16.gguf',
     907542944, '2e788f8c511d8093c7b43cb87b2fd7e14228340318057f8fb20c86df2efe2355'),
)
LICENSE_FILES = (
    (DATA_REL + '/LICENSE-Swift', 13323,
     '7a3af3e6b43fcb7c486ea8167252a36a9532dcbdf02d1704a749881872ec551c'),
    (DATA_REL + '/LICENSE-Qwen', 3235,
     'a0dc422560841fd68e06d974907f8b4c709bca44a67daad2b528437bdf676c08'),
)
MTP_FILES = (
    ('dense.bin', 116099072, 'c724dc0b0822ada5d2977bf5bde821605feabaa64ea2e0045b67ca656329070a'),
    ('dense.txt', 1880, '8773c81ebb0986e37fe94a8a9933e87be48b1fabc6889a0106bcdab179d1c2ac'),
    ('draft_vocab.bin', 425196, 'b1e1d3a7a9e4bf862dcd5923ce661fb59bbd07907e594df5cf86a62ac235cb91'),
    ('experts.bin', 707788800, '09398406be61f1f54c93861f449e48b8df0bfccbc9ec9b2b7636775a6ea9244f'),
)
VALUE_FLAGS = {
    '--pack', '--native', '--ple-gguf', '--expert-profile', '--expert-cache',
    '--prefill', '--spec', '--spec-min-p', '--mtp', '--max-context', '--kv',
    '--kv-resident', '--vram-reserve-mib',
}
BOOLEAN_FLAGS = {'--vision'}


def json_file(path):
    value = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError(f'Expected a JSON object: {path}')
    return value


def reparse_path(path):
    info = path.lstat()
    return path.is_symlink() or bool(getattr(info, 'st_file_attributes', 0) &
        getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400))


def assert_unlinked(path):
    """Check ancestors too: a same-root junction is not a safe owned directory."""
    path = Path(path).absolute()
    for candidate in (path, *path.parents):
        if candidate.exists() or candidate.is_symlink():
            if reparse_path(candidate):
                raise ValueError(f'Linked/reparse path is not allowed: {candidate}')
    if path.resolve() != path:
        raise ValueError(f'Path must match its resolved location: {path}')
    return path


def target_root(config):
    value = config.get('target', {}).get('root')
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        raise ValueError('config.target.root must be an absolute existing directory.')
    raw = Path(value)
    if '..' in raw.parts:
        raise ValueError('config.target.root must not contain parent traversal.')
    root = assert_unlinked(raw)
    if not root.is_dir():
        raise ValueError('config.target.root does not exist.')
    return root


def scoped(root, relative):
    """Accept only explicit relative descendants of the configured installation."""
    relative = str(relative).replace('\\', '/')
    parts = relative.split('/')
    if (not relative or relative.startswith('/') or ':' in relative or
            any(part in ('', '.', '..') for part in parts)):
        raise ValueError('Preparation paths must be non-traversing relative paths.')
    root = assert_unlinked(root)
    path = assert_unlinked(root.joinpath(*parts))
    if not path.is_relative_to(root) or path == root:
        raise ValueError('Preparation path escaped the configured installation.')
    return path


def require_file(root, relative):
    path = scoped(root, relative)
    if not path.is_file():
        raise ValueError(f'Required file is missing: {relative}')
    return path


def same_path(value, expected):
    return isinstance(value, str) and Path(value).is_absolute() and assert_unlinked(Path(value)) == expected


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(16 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def stat_identity(path):
    info = path.stat()
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def verify_file(root, relative, size, digest):
    path = require_file(root, relative)
    before = stat_identity(path)
    if before[2] != size:
        raise ValueError(f'Pinned artifact size mismatch; retained unchanged: {relative}')
    if sha256(path) != digest or stat_identity(path) != before:
        raise ValueError(f'Pinned artifact SHA256 or identity mismatch; retained unchanged: {relative}')
    return path, before


def verify_source(root, run=subprocess.run):
    source = scoped(root, SOURCE_REL)
    require_file(root, SOURCE_REL + '/setup.py')
    for relative in ('.git', 'tools', 'engine', '.venv/Scripts', 'third_party/llama.cpp/gguf-py'):
        if not scoped(root, SOURCE_REL + '/' + relative).is_dir():
            raise ValueError(f'Pinned Strata checkout is incomplete: {relative}')
    for name in ('requirements.txt', 'tools/iq_pack.py', 'tools/gguf_reader.py',
                 'tools/_paths.py', 'tools/strata_tokenizer.py', 'engine/strata.exe',
                 'engine/strata-vision.exe', '.venv/Scripts/python.exe', 'data/expert-profile.bin'):
        require_file(root, SOURCE_REL + '/' + name)
    command = ['git', '-c', 'safe.directory=' + str(source), '-C', str(source)]
    head = run(command + ['rev-parse', 'HEAD'], check=True, capture_output=True, text=True)
    if head.stdout.strip() != SOURCE_COMMIT:
        raise ValueError('Strata must be pinned to ' + SOURCE_COMMIT)
    clean = run(command + ['diff', '--quiet', 'HEAD', '--'], capture_output=True)
    if clean.returncode != 0:
        raise ValueError('Pinned Strata source has tracked changes; retained unchanged.')
    run(command + ['ls-files', '--error-unmatch', 'tools/iq_pack.py', 'tools/gguf_reader.py',
                  'tools/_paths.py', 'tools/strata_tokenizer.py', 'data/expert-profile.bin'],
        check=True, capture_output=True)
    build = json_file(require_file(root, SOURCE_REL + '/engine/BUILD.json'))
    if (build.get('version') != '0.1.39' or build.get('source') != 'release' or
            build.get('cuda') != '13.0' or build.get('vision') != 'gpu' or
            89 not in build.get('archs', []) or 89 not in build.get('vision_archs', [])):
        raise ValueError('Strata engine must be the verified 0.1.39 CUDA13 text/vision sm89 release.')
    return source


def parse_flags(args):
    if not isinstance(args, list) or not all(isinstance(value, str) for value in args):
        raise ValueError('Engine args must be strings.')
    flags, index = {}, 0
    while index < len(args):
        flag = args[index]
        if flag in flags:
            raise ValueError('Duplicate engine option: ' + flag)
        if flag in BOOLEAN_FLAGS:
            flags[flag] = True
            index += 1
        elif flag in VALUE_FLAGS and index + 1 < len(args) and not args[index + 1].startswith('--'):
            flags[flag] = args[index + 1]
            index += 2
        else:
            raise ValueError('Unsupported or malformed engine option: ' + flag)
    if set(flags) != VALUE_FLAGS | BOOLEAN_FLAGS:
        raise ValueError('Base engine config must contain exactly the reviewed engine options.')
    return flags


def server_config(root, base):
    """Retain proven API/runtime settings while replacing model-owned paths."""
    source = scoped(root, SOURCE_REL)
    flags = parse_flags(base.get('args'))
    paths = {
        '--pack': OLD_DATA_REL + '/packs/iq3_s',
        '--native': OLD_DATA_REL + '/IQ3_S/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00001-of-00002.gguf',
        '--ple-gguf': OLD_DATA_REL + '/IQ3_S/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00002-of-00002.gguf',
        '--mtp': OLD_DATA_REL + '/mtp/rt',
        '--expert-profile': SOURCE_REL + '/data/expert-profile.bin',
    }
    for flag, relative in paths.items():
        if not same_path(flags[flag], scoped(root, relative)):
            raise ValueError('Base config has an unexpected owned path: ' + flag)
    for flag, value in {'--max-context': '131072', '--vram-reserve-mib': '1536', '--spec': '4',
                        '--kv': 'int8', '--kv-resident': '32768'}.items():
        if flags[flag] != value:
            raise ValueError('Base config does not match the verified 128K settings: ' + flag)
    if (not same_path(base.get('exe'), scoped(root, SOURCE_REL + '/engine/strata.exe')) or
            not same_path(base.get('cwd'), source) or base.get('host') != '127.0.0.1' or
            type(base.get('port')) is not int or base['port'] != 18080 or base.get('gpu') != 0 or
            base.get('draft_vocab') != 'cjk' or base.get('open_browser') is not False):
        raise ValueError('Base config must match the verified local Strata runtime.')
    if not same_path(base.get('tokenizer'), scoped(root, OLD_DATA_REL + '/packs/iq3_s/tokenizer')):
        raise ValueError('Base tokenizer path is unexpected.')
    libs = base.get('lib_dirs')
    expected_lib = scoped(root, SOURCE_REL + '/.venv/Lib/site-packages/nvidia/cu13/bin/x86_64')
    if not isinstance(libs, list) or not libs or any(not same_path(value, expected_lib) for value in libs):
        raise ValueError('CUDA library directories must remain inside the dedicated Strata venv.')
    vision = base.get('vision')
    if (not isinstance(vision, dict) or vision.get('gpu') is not True or vision.get('max_tokens') != 1024 or
            not same_path(vision.get('exe'), scoped(root, SOURCE_REL + '/engine/strata-vision.exe')) or
            not same_path(vision.get('model'), scoped(root, paths['--native'])) or
            not same_path(vision.get('mmproj'), scoped(root, OLD_DATA_REL + '/mmproj-Qwen3.8-Flash-Next-BF16.gguf'))):
        raise ValueError('Base config must match the verified GPU vision configuration.')
    out = deepcopy(base)
    replacements = {
        '--pack': str(scoped(root, PACK_REL)),
        '--native': str(scoped(root, MODEL_FILES[0][0])),
        '--ple-gguf': str(scoped(root, MODEL_FILES[0][0])),
        '--expert-profile': str(scoped(root, DATA_REL + '/expert-profile.bin')),
    }
    for flag, value in replacements.items():
        out['args'][out['args'].index(flag) + 1] = value
    out.update(tokenizer=str(scoped(root, PACK_REL + '/tokenizer')), model_name=MODEL_NAME,
               log=str(scoped(root, SOURCE_REL + '/strata-swift-iq3_xxs.log')),
               aliases=['qwen3.8-27b-local', 'qwen3.8-flash-next-iq3_s'])
    out['vision'].update(model=str(scoped(root, MODEL_FILES[0][0])), mmproj=str(scoped(root, MODEL_FILES[2][0])))
    return out


def expected_stamp():
    return {'schemaVersion': 1, 'strataCommit': SOURCE_COMMIT, 'modelRevision': SWIFT_REVISION,
            'modelFiles': [{'path': path, 'size': size, 'sha256': digest} for path, size, digest in MODEL_FILES],
            'mtpFiles': [{'name': name, 'size': size, 'sha256': digest} for name, size, digest in MTP_FILES]}


def verify_manifest(manifest):
    if (manifest.get('schemaVersion') != 1 or manifest.get('modelRevision') != SWIFT_REVISION or
            manifest.get('modelRepository') != 'SC117/Swift-1.5-Qwen3.8-Flash-Next-GSQ-RCO-abliterated-GGUF' or
            manifest.get('runtimeRevision') != SOURCE_COMMIT or manifest.get('runtimeRelease') != 'v0.1.39' or
            manifest.get('modelFolder') != DATA_REL):
        raise ValueError('Swift manifest does not match the fixed model/runtime pins.')
    rows = manifest.get('files')
    if not isinstance(rows, list) or len(rows) != len(MODEL_FILES) + len(LICENSE_FILES):
        raise ValueError('Swift manifest must contain exactly the reviewed artifacts and licenses.')
    actual = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('folder'), str) or not isinstance(row.get('name'), str):
            raise ValueError('Swift manifest has a malformed artifact.')
        relative = row['folder'] + '/' + row['name']
        if type(row.get('size')) is not int or not isinstance(row.get('sha256'), str):
            raise ValueError('Swift manifest has invalid size/hash values.')
        actual.append((relative, row['size'], row['sha256']))
    if set(actual) != set(MODEL_FILES + LICENSE_FILES) or len(set(actual)) != len(actual):
        raise ValueError('Swift manifest differs from the fixed artifact size/SHA pins.')
    mtp = manifest.get('mtpReuse')
    if (not isinstance(mtp, dict) or mtp.get('folder') != OLD_DATA_REL + '/mtp/rt' or
            mtp.get('sourceRevision') != SWIFT_REVISION or
            mtp.get('sourceRepository') != manifest['modelRepository']):
        raise ValueError('Swift manifest MTP reuse source/folder is unexpected.')
    rows = mtp.get('files')
    if not isinstance(rows, list) or len(rows) != len(MTP_FILES):
        raise ValueError('Swift manifest must name every reviewed MTP runtime file.')
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError('Swift manifest contains a malformed MTP runtime row.')
    actual = [(row.get('name'), row.get('size'), row.get('sha256')) for row in rows]
    if any(not isinstance(name, str) or type(size) is not int or not isinstance(digest, str)
           for name, size, digest in actual):
        raise ValueError('Swift manifest has invalid MTP name/size/hash values.')
    if set(actual) != set(MTP_FILES) or len(set(actual)) != len(actual):
        raise ValueError('Swift manifest differs from the fixed MTP size/SHA pins.')
    preparation = manifest.get('preparation', {})
    if (not isinstance(preparation, dict) or preparation.get('pleShard') != 1 or preparation.get('specTokens') != 4 or
            preparation.get('contextSize') != 131072):
        raise ValueError('Swift manifest does not match the reviewed engine settings.')


def check_tree(root, relative):
    directory = scoped(root, relative)
    for current, directories, files in os.walk(directory, followlinks=False):
        for name in directories + files:
            path = Path(current) / name
            scoped(root, path.relative_to(root).as_posix())


def verify_pack(root, relative):
    check_tree(root, relative)
    for name in ('native_experts.txt', 'index.txt', 'dense.bin', 'tokenizer/vocab.json',
                 'tokenizer/tokenizer.json', 'tokenizer/chat_template.jinja'):
        if require_file(root, relative + '/' + name).stat().st_size == 0:
            raise ValueError('Prepared pack is incomplete: ' + name)
    vocab = json_file(scoped(root, relative + '/tokenizer/vocab.json'))
    tokenizer = json_file(scoped(root, relative + '/tokenizer/tokenizer.json'))
    template = scoped(root, relative + '/tokenizer/chat_template.jinja').read_text(encoding='utf-8')
    if not vocab or not tokenizer or not template.strip():
        raise ValueError('Prepared tokenizer lacks vocabulary or the GGUF chat template.')
    experts = scoped(root, relative + '/native_experts.txt').read_text(encoding='utf-8')
    if 'Swift-Qwen3.8-Flash-Next-GSQ-RCO-abliterated-IQ3_XXS-00002-of-00002.gguf' not in experts:
        raise ValueError('Swift pack does not record its own second shard; do not reuse the Qwen pack.')


def pack_files(root, relative):
    directory = scoped(root, relative)
    check_tree(root, relative)
    return [{'path': path.relative_to(directory).as_posix(), 'size': path.stat().st_size,
             'sha256': sha256(path)} for path in sorted(directory.rglob('*'))
            if path.is_file() and path.name != STAMP_NAME]


def verify_owned_pack(root, relative, expected):
    directory = scoped(root, relative)
    if not directory.is_dir() or not (directory / STAMP_NAME).is_file():
        raise ValueError('Existing Swift pack has no matching ownership stamp; retained unchanged.')
    actual = json_file(scoped(root, relative + '/' + STAMP_NAME))
    if {key: actual.get(key) for key in expected} != expected or set(actual) != set(expected) | {'packFiles'}:
        raise ValueError('Existing Swift pack belongs to different inputs; retained unchanged.')
    verify_pack(root, relative)
    if actual.get('packFiles') != pack_files(root, relative):
        raise ValueError('Existing Swift pack output hashes differ; retained unchanged.')


def write_new(root, relative, data):
    """Create exclusively, using a sibling temporary file; never replace a file."""
    path = scoped(root, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    scoped(root, relative)
    if path.exists():
        if path.is_file() and path.read_bytes() == data:
            return
        raise ValueError('Existing output differs; retained unchanged: ' + relative)
    temporary = scoped(root, relative + '.new-' + uuid.uuid4().hex)
    with temporary.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.link(temporary, path)  # Atomic, exclusive creation on NTFS and Unix filesystems.
    except Exception:
        raise RuntimeError('Output creation failed; sibling temporary file is retained: ' + relative) from None
    temporary.unlink()  # Exact newly-created, verified sibling only; no recursive deletion.


def encoded(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode('utf-8')


def plan(config, manifest=None, run=subprocess.run):
    verify_manifest(manifest if manifest is not None else json_file(SUPPORT / 'config/swift-download-manifest.json'))
    root = target_root(config)
    source = verify_source(root, run)
    if 'sourceRoot' in config.get('strata', {}) and not same_path(config['strata']['sourceRoot'], source):
        raise ValueError('Configured Strata source root differs from the dedicated checkout.')
    identities = []
    for relative, size, digest in MODEL_FILES + LICENSE_FILES:
        print('Verifying pinned Swift artifact: ' + relative, flush=True)
        identities.append(verify_file(root, relative, size, digest))
    for name, size, digest in MTP_FILES:
        identities.append(verify_file(root, OLD_DATA_REL + '/mtp/rt/' + name, size, digest))
    base_path = require_file(root, BASE_CONFIG_REL)
    base_bytes = base_path.read_bytes()
    base = json_file(base_path)
    desired = server_config(root, base)
    pack = scoped(root, PACK_REL)
    stamp = expected_stamp()
    if pack.exists():
        verify_owned_pack(root, PACK_REL, stamp)
    profile = require_file(root, SOURCE_REL + '/data/expert-profile.bin').read_bytes()
    outputs = {DATA_REL + '/expert-profile.bin': profile, OUTPUT_CONFIG_REL: encoded(desired)}
    for relative, data in outputs.items():
        path = scoped(root, relative)
        if path.exists() and (not path.is_file() or path.read_bytes() != data):
            raise ValueError('Existing output differs; retained unchanged: ' + relative)
    shared = scoped(root, SHARED_CONFIG_REL)
    if shared.exists() and json_file(shared).get('reasoning_effort') != 'none':
        raise ValueError('Existing Swift shared settings select another reasoning mode; retained unchanged.')
    return {'root': root, 'source': source, 'pack': pack, 'stamp': stamp, 'identities': identities,
            'base_path': base_path, 'base_bytes': base_bytes, 'outputs': outputs, 'shared_exists': shared.exists()}


def assert_stable(prepared):
    root = prepared['root']
    for path, identity in prepared['identities']:
        if scoped(root, path.relative_to(root).as_posix()) != path or stat_identity(path) != identity:
            raise ValueError('A verified input changed during preparation; outputs will not be activated.')
    if prepared['base_path'].read_bytes() != prepared['base_bytes']:
        raise ValueError('The base server config changed during preparation; retained unchanged.')


def apply(prepared, run=subprocess.run):
    root, source, pack = prepared['root'], prepared['source'], prepared['pack']
    assert_stable(prepared)
    if not pack.exists():
        packs = scoped(root, DATA_REL + '/packs')
        packs.mkdir(parents=True, exist_ok=True)
        scoped(root, DATA_REL + '/packs')
        stage = Path(tempfile.mkdtemp(prefix='.swift-iq3_xxs-prepare-', dir=packs))
        stage_rel = stage.relative_to(root).as_posix()
        scoped(root, stage_rel)
        environment = os.environ.copy()
        environment.pop('PYTHONPATH', None)
        environment.update(PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1',
                           HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                           STRATA_GGUF_PY=str(scoped(root, SOURCE_REL + '/third_party/llama.cpp/gguf-py')))
        command = [str(require_file(root, SOURCE_REL + '/.venv/Scripts/python.exe')), '-B', '-X', 'utf8',
                   str(require_file(root, SOURCE_REL + '/tools/iq_pack.py')), '--gguf',
                   str(require_file(root, MODEL_FILES[0][0])), '--out', str(stage)]
        print('Building Swift native pack in its own staging directory.', flush=True)
        run(command, cwd=source, env=environment, check=True)
        verify_pack(root, stage_rel)
        verify_source(root, run)
        assert_stable(prepared)
        stamp = {**prepared['stamp'], 'packFiles': pack_files(root, stage_rel)}
        write_new(root, stage_rel + '/' + STAMP_NAME, encoded(stamp))
        scoped(root, PACK_REL)
        if pack.exists():
            raise ValueError('Swift final pack appeared while preparing; staged output is retained.')
        stage.rename(pack)
    verify_pack(root, PACK_REL)
    verify_owned_pack(root, PACK_REL, prepared['stamp'])
    verify_source(root, run)
    assert_stable(prepared)
    for relative, data in prepared['outputs'].items():
        write_new(root, relative, data)
    if not prepared['shared_exists']:
        write_new(root, SHARED_CONFIG_REL, encoded({'reasoning_effort': 'none'}))
    return {'prepared': True, 'active_model_changed': False, 'model': MODEL_NAME,
            'modelRevision': SWIFT_REVISION, 'contextSize': 131072,
            'serverConfig': str(scoped(root, OUTPUT_CONFIG_REL)), 'pack': str(pack), 'mtpReused': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=SUPPORT / 'config/support-config.json')
    parser.add_argument('--manifest', type=Path, default=SUPPORT / 'config/swift-download-manifest.json')
    parser.add_argument('--apply', action='store_true', help='Create Swift-owned outputs after all checks pass.')
    args = parser.parse_args()
    if os.name != 'nt':
        raise SystemExit('This preparer is restricted to the verified Windows/CUDA deployment.')
    prepared = plan(json_file(args.config), json_file(args.manifest))
    if args.apply:
        result = apply(prepared)
    else:
        result = {'verified': True, 'applied': False, 'model': MODEL_NAME,
                  'modelRevision': SWIFT_REVISION, 'serverConfig': str(scoped(prepared['root'], OUTPUT_CONFIG_REL)),
                  'pack': str(prepared['pack']), 'contextSize': 131072, 'mtpReused': True,
                  'next': 'Run again with --apply to create the dedicated pack and configuration.'}
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
