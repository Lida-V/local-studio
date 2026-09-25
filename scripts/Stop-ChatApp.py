import json
from pathlib import Path
import psutil
import msvcrt
import subprocess
import sys
subprocess.run([sys.executable, '-X', 'utf8', str(Path(__file__).with_name('Local-Studio.py')), 'stop-worker'], check=True)
lease = Path('C:/AI/LocalLLM/runtime/studio-generation.lock').open('a+b')
lease.seek(0)
try:
    msvcrt.locking(lease.fileno(), msvcrt.LK_NBLCK, 1)
except OSError:
    raise SystemExit('Image generation is active. Wait until it completes before stopping the app.')
state = Path('C:/AI/LocalLLM/runtime/chatapp.json')
if state.exists():
    s = json.loads(state.read_text(encoding='utf-8'))
    try:
        p = psutil.Process(s['pid'])
        if p.create_time() != s['created'] or p.exe() != s['exe'] or s['script'] not in p.cmdline():
            raise RuntimeError('Process identity mismatch; nothing stopped')
        p.terminate()
        p.wait(20)
        print('Chat app stopped (chat data retained).')
    except psutil.NoSuchProcess:
        print('Chat app is already stopped.')
