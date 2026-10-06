"""Fetch pinned HTTPS artifacts with an ordered, bounded range-download window.

Only complete, verified ranges are appended to the existing partial file.  This
module deliberately does not rename files or verify the whole-artifact SHA256;
the installer must perform that verification before accepting the artifact.
"""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import threading
import urllib.parse
import urllib.request

MIB = 1024 * 1024
MAX_WORKERS = 4
MAX_CHUNK_SIZE = 64 * MIB
MAX_BUFFER_BYTES = 256 * MIB
READ_SIZE = MIB
ATTEMPTS = 2
TIMEOUT = 45


class RangeDownloadError(RuntimeError):
    """The remote response cannot safely extend the contiguous partial file."""


def _request_url(url, start):
    parts = urllib.parse.urlsplit(url)
    query = [(key, value) for key, value in urllib.parse.parse_qsl(
        parts.query, keep_blank_values=True) if key not in ('download', 'range_start')]
    query.extend((('download', 'true'), ('range_start', str(start))))
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))


def _read_range(url, start, end, total, cancelled):
    expected = end - start + 1
    data = None
    for attempt in range(ATTEMPTS):
        if cancelled.is_set():
            raise RangeDownloadError('Download cancelled after another range failed.')
        try:
            request = urllib.request.Request(_request_url(url, start), headers={
                'Range': f'bytes={start}-{end}',
                'Accept-Encoding': 'identity',
                'User-Agent': 'LocalLLM-Installer/1.0',
            })
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',
                                    response.headers.get('Content-Range', ''))
                if response.status != 206 or not match or tuple(map(int, match.groups())) != (start, end, total):
                    raise RangeDownloadError('Server did not confirm the exact requested byte range.')
                encoding = response.headers.get('Content-Encoding', '').strip().lower()
                if encoding not in ('', 'identity'):
                    raise RangeDownloadError('Server encoded the byte-range response.')
                content_length = response.headers.get('Content-Length')
                if content_length is not None and (not content_length.isdecimal() or int(content_length) != expected):
                    raise RangeDownloadError('Byte-range Content-Length differs from the requested length.')
                # Reuse the same bounded allocation on retry. readinto avoids
                # accumulating or copying another chunk-sized bytes object.
                if data is None:
                    data = bytearray(expected)
                received = 0
                view = memoryview(data)
                try:
                    while received < expected:
                        if cancelled.is_set():
                            raise RangeDownloadError('Download cancelled after another range failed.')
                        window = view[received:min(received + READ_SIZE, expected)]
                        try:
                            count = response.readinto(window)
                            if not isinstance(count, int) or isinstance(count, bool) or not 0 < count <= len(window):
                                raise RangeDownloadError('Transfer ended early or returned an invalid byte count.')
                            received += count
                        finally:
                            window.release()
                    if response.read(1):
                        raise RangeDownloadError('Server returned bytes beyond the requested range.')
                finally:
                    view.release()
            return start, data
        except Exception:
            if cancelled.is_set() or attempt + 1 == ATTEMPTS:
                # A Future retains its exception traceback. Do not let that
                # traceback retain a failed range's large bytearray.
                data = None
                raise
    raise AssertionError('Unreachable range retry state.')


def _append(stream, data):
    view = memoryview(data)
    try:
        written = 0
        while written < len(view):
            window = view[written:]
            try:
                count = stream.write(window)
                if not isinstance(count, int) or isinstance(count, bool) or not 0 < count <= len(window):
                    raise RangeDownloadError('Partial-file write did not complete.')
                written += count
            finally:
                window.release()
    finally:
        view.release()
        data = None
    stream.flush()
    os.fsync(stream.fileno())


def download(entry, partial, workers=4, chunk_size=64 * MIB):
    """Append verified ranges in order and return ``Path(partial)``.

    ``entry`` must contain the fixed publisher HTTPS ``url``, integer ``size``,
    and display ``name`` from the reviewed manifest. At most four requests and
    256 MiB of range payload buffers are retained, without chunk-sized copies.
    Existing partial bytes are trusted only for resumption; whole-file size and
    SHA256 validation remain mandatory in the caller. Failed transfers preserve
    the contiguous prefix, and never preallocate, rename, truncate, or delete it.
    """
    url, total, name = entry['url'], entry['size'], entry['name']
    if not isinstance(url, str):
        raise ValueError('Manifest URL must be an HTTPS string.')
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.fragment:
        raise ValueError('Manifest URL must be a fixed HTTPS publisher URL without credentials or fragment.')
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        raise ValueError('Manifest size must be a nonnegative integer.')
    if not isinstance(name, str) or not name:
        raise ValueError('Manifest name must be a nonempty string.')
    if not isinstance(workers, int) or isinstance(workers, bool) or not 1 <= workers <= MAX_WORKERS:
        raise ValueError('workers must be an integer between 1 and 4.')
    if not isinstance(chunk_size, int) or isinstance(chunk_size, bool) or not 1 <= chunk_size <= MAX_CHUNK_SIZE:
        raise ValueError('chunk_size must be between 1 byte and 64 MiB.')
    if workers * chunk_size > MAX_BUFFER_BYTES:
        raise ValueError('Range buffers would exceed 256 MiB.')
    partial = Path(partial)
    if partial.exists() and not partial.is_file():
        raise ValueError('Partial path must be a regular file.')
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > total:
        raise RangeDownloadError('Partial file exceeds expected size; retained for inspection.')
    if offset == total and partial.exists():
        return partial
    cancelled = threading.Event()
    pending = deque()
    executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='gguf-range')
    next_start = offset
    data = future = None
    try:
        # Unbuffered append never creates holes or reserves the final file size.
        with partial.open('ab', buffering=0) as stream:
            if os.fstat(stream.fileno()).st_size != offset:
                raise RangeDownloadError('Partial-file size changed before download; preserved.')
            while next_start < total and len(pending) < workers:
                end = min(next_start + chunk_size, total) - 1
                future = executor.submit(_read_range, url, next_start, end, total, cancelled)
                pending.append((next_start, end, future))
                next_start = end + 1
            while pending:
                start, end, future = pending.popleft()
                returned_start, data = future.result()
                if start != offset or returned_start != offset or len(data) != end - start + 1:
                    raise RangeDownloadError('Completed range does not match the contiguous append offset.')
                if os.fstat(stream.fileno()).st_size != offset:
                    raise RangeDownloadError('Partial-file size changed during download; preserved.')
                _append(stream, data)
                offset = end + 1
                if os.fstat(stream.fileno()).st_size != offset:
                    raise RangeDownloadError('Partial-file size differs after append; preserved.')
                print(json.dumps({'file': name, 'bytes': offset, 'total': total,
                                  'percent': round(offset / total * 100, 1)}), flush=True)
                # Drop both references before replenishing the window. Futures
                # retain their results, so keeping one would exceed the budget.
                del data, future
                if next_start < total:
                    end = min(next_start + chunk_size, total) - 1
                    future = executor.submit(_read_range, url, next_start, end, total, cancelled)
                    pending.append((next_start, end, future))
                    next_start = end + 1
    finally:
        cancelled.set()
        for _, _, future in pending:
            future.cancel()
        try:
            executor.shutdown(wait=True, cancel_futures=True)
        finally:
            # Completed Futures retain successful buffers too. Clear both the
            # pending window and the popped/local references on failure.
            pending.clear()
            data = future = None
    return partial
