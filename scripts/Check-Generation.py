"""Exit 3 while a generation owns the GPU handoff lease; otherwise exit 0."""
from pathlib import Path
import msvcrt
import sys

with Path('C:/AI/LocalLLM/runtime/studio-generation.lock').open('a+b') as handle:
    try:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        sys.exit(3)
    handle.seek(0)
    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
