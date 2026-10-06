"""Run the upstream Strata server with fail-closed Windows process containment.

The venv python.exe may be a launcher for a second interpreter. Its real identity
is recorded separately, so stopping the launcher cannot leave a GPU worker alive.
No server source is copied or changed; the upstream main() and API stay intact.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import importlib
import json
import os
from pathlib import Path
import re
import sys
import threading

DOTNET_FILETIME_OFFSET = 504911232000000000


class WindowsJob:
    """A private, non-inherited handle owns this interpreter and its descendants."""

    def __init__(self):
        if os.name != 'nt':
            raise RuntimeError('Strata lifecycle containment requires Windows.')
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.GetCurrentProcess.restype = wintypes.HANDLE
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
        self.kernel.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD)
        self.kernel.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        self.kernel.IsProcessInJob.argtypes = (wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL))
        self.kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.kernel.GetProcessTimes.argtypes = (wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4))
        self.kernel.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in
                        ('ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
                         'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]

        class BasicLimits(ctypes.Structure):
            _fields_ = [('PerProcessUserTimeLimit', ctypes.c_longlong), ('PerJobUserTimeLimit', ctypes.c_longlong),
                        ('LimitFlags', wintypes.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                        ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
                        ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD), ('SchedulingClass', wintypes.DWORD)]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [('BasicLimitInformation', BasicLimits), ('IoInfo', IoCounters),
                        ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                        ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]

        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE; no BREAKAWAY flags
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.get_last_error()
            self.kernel.CloseHandle(self.handle)
            raise ctypes.WinError(error)
        if not self.kernel.AssignProcessToJobObject(self.handle, self.kernel.GetCurrentProcess()):
            error = ctypes.get_last_error()
            self.kernel.CloseHandle(self.handle)
            raise ctypes.WinError(error)
        # Do not close the handle ourselves: this interpreter is in the job too.
        # The OS closes it on normal exit, TerminateProcess, or an unexpected crash.

    def identity(self, handle, pid):
        created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if not self.kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                           ctypes.byref(kernel), ctypes.byref(user)):
            raise ctypes.WinError(ctypes.get_last_error())
        length = wintypes.DWORD(32768)
        executable = ctypes.create_unicode_buffer(length.value)
        if not self.kernel.QueryFullProcessImageNameW(handle, 0, executable, ctypes.byref(length)):
            raise ctypes.WinError(ctypes.get_last_error())
        ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
        return {'pid': int(pid), 'startUtcTicks': ticks + DOTNET_FILETIME_OFFSET,
                'executable': executable.value}

    def owns(self, process):
        member = wintypes.BOOL()
        if not self.kernel.IsProcessInJob(int(process._handle), self.handle, ctypes.byref(member)):
            raise ctypes.WinError(ctypes.get_last_error())
        return bool(member.value)


class ProcessRecorder:
    def __init__(self, job, path, token, source_root, config_path):
        self.job, self.path = job, Path(path)
        self.lock = threading.Lock()
        self.state = {'schemaVersion': 1, 'launchToken': token, 'backend': 'strata',
                      'jobContained': True, 'sourceRoot': str(source_root),
                      'serverConfigPath': str(config_path), 'parentPid': os.getppid(),
                      'server': job.identity(job.kernel.GetCurrentProcess(), os.getpid()),
                      'children': [], 'startedAt': datetime.now(timezone.utc).isoformat()}
        self.save()

    def save(self):
        temp = self.path.with_name(self.path.name + '.tmp-' + str(os.getpid()))
        temp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        temp.replace(self.path)

    def contain(self, process):
        """The upstream hook must succeed; never let a GPU child escape silently."""
        try:
            if not self.job.owns(process):
                raise RuntimeError('Strata child is outside the owned Windows Job Object.')
            identity = self.job.identity(int(process._handle), process.pid)
            with self.lock:
                self.state['children'].append(identity)
                self.save()
            return True
        except Exception:
            # This is the exact Popen just created by our server, never a PID lookup.
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            raise


def server_arguments(config_path, host, port):
    if host != '127.0.0.1' or not 1 <= port <= 65535:
        raise ValueError('Strata must bind to 127.0.0.1 on a valid port.')
    return ['--engine', 'strata', '--config', str(config_path), '--host', host, '--port', str(port)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', required=True, type=int)
    parser.add_argument('--process-state', required=True, type=Path)
    parser.add_argument('--launch-token', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[0-9a-f]{32}', args.launch_token):
        raise ValueError('Invalid launch token.')
    source = args.source_root.resolve(strict=True)
    config = args.config.resolve(strict=True)
    script = source / 'serve/server.py'
    if not script.is_file():
        raise FileNotFoundError(script)
    upstream_args = server_arguments(config, args.host, args.port)
    job = WindowsJob()  # Must succeed before importing or starting upstream workers.
    recorder = ProcessRecorder(job, args.process_state, args.launch_token, source, config)
    os.chdir(source)
    sys.path.insert(0, str(source))
    winjob = importlib.import_module('serve.winjob')
    winjob.contain = recorder.contain  # server and MCP imports both receive the strict hook.
    server = importlib.import_module('serve.server')
    sys.argv = [str(script), *upstream_args]
    return server.main()


if __name__ == '__main__':
    sys.exit(main())
