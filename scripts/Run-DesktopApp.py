"""Own the temporary Chromium directory for exactly the lifetime of this desktop window."""
import json
import msvcrt
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time

SUPPORT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((SUPPORT / 'config/support-config.json').read_text(encoding='utf-8-sig'))
ROOT = Path(CONFIG['target']['root'])
CACHE = ROOT / 'cache/desktop-session'
APP = ROOT / 'apps/local-studio-desktop'
EXE = APP / 'node_modules/electron/dist/electron.exe'
PWSH = shutil.which('pwsh') or 'pwsh'

def clear_owned_cache():
    # Validate all resolved paths and reject reparse points before recursive deletion.
    if CACHE.resolve() != ROOT.resolve() / 'cache/desktop-session':
        raise RuntimeError('Unexpected cache target')
    for p in [ROOT / 'cache', CACHE]:
        if p.exists() and p.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise RuntimeError('Cache parent cannot be a junction or symlink')
    if CACHE.exists():
        for parent, dirs, files in os.walk(CACHE, followlinks=False):
            for name in dirs + files:
                p = Path(parent) / name
                if p.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                    raise RuntimeError('Refusing cache cleanup containing a reparse point')
                if not p.resolve().is_relative_to(CACHE.resolve()):
                    raise RuntimeError('Cache path escapes its root')
        shutil.rmtree(CACHE)

def main():
    (ROOT / 'runtime').mkdir(exist_ok=True)
    env = os.environ.copy()
    env.pop('ELECTRON_RUN_AS_NODE', None)
    env['LOCAL_STUDIO_SOURCE'] = str(SUPPORT)
    with (ROOT / 'runtime/desktop.lock').open('a+b') as lock:
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            # Electron focuses its existing instance; never clean a live profile.
            subprocess.Popen([str(EXE), str(APP)], env=env, creationflags=subprocess.CREATE_NO_WINDOW)
            return
        clear_owned_cache()
        with (ROOT / 'logs/desktop-launch.log').open('w', encoding='utf-8') as log:
            result = subprocess.run([PWSH, '-NoProfile', '-File', str(SUPPORT / 'scripts/Start-ChatApp.ps1')], stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:
                raise RuntimeError('Backend startup failed; see logs/desktop-launch.log')
            try:
                child = subprocess.Popen([str(EXE), str(APP)], env=env, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
                child.wait()
            finally:
                for attempt in range(15):
                    try:
                        clear_owned_cache()
                        break
                    except PermissionError:
                        if attempt == 14: raise
                        time.sleep(1)
                (ROOT / 'runtime/desktop.json').unlink(missing_ok=True)
                (ROOT / 'runtime/desktop-cleanup.json').write_text(json.dumps({'cache_removed': not CACHE.exists(), 'at': time.time()}), encoding='utf-8')

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, str(error), 'Local Studio', 0x10)
        sys.exit(1)
