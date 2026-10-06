"""Offline range-download checks; no models, publisher traffic, or live files."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.parse

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / 'tools'))
import range_download


class Response(io.BytesIO):
    def __init__(self, fixture, start, end, body, status=206, headers=None, invalid_count=False):
        super().__init__(body)
        self.fixture, self.start = fixture, start
        self.status = status
        self.headers = {'Content-Range': f'bytes {start}-{end}/{len(fixture.payload)}',
                        'Content-Length': str(end - start + 1)}
        self.headers.update(headers or {})
        self.invalid_count = invalid_count
        self.waited = False
        self.completed = False

    def readinto(self, buffer):
        if self.start == self.fixture.blocked_start and not self.waited:
            self.waited = True
            if not self.fixture.release_first.wait(5):
                raise AssertionError('Fixture concurrent ranges did not complete.')
        if self.invalid_count:
            return len(buffer) + 1
        # Fragmented reads exercise byte accounting without large allocations.
        return super().readinto(buffer[:min(len(buffer), 2)])

    def read(self, size=-1):
        result = super().read(size)
        if not self.completed:
            self.completed = True
            self.fixture.completed(self.start)
        return result

    def __exit__(self, *args):
        with self.fixture.lock:
            self.fixture.active -= 1
        return super().__exit__(*args)


class Fixture:
    def __init__(self, payload, blocked_start=None, failures=None):
        self.payload = payload
        self.blocked_start = blocked_start
        self.failures = failures or {}
        self.release_first = threading.Event()
        self.lock = threading.Lock()
        self.requests = []
        self.completions = []
        self.attempts = {}
        self.active = self.max_active = 0

    def completed(self, start):
        with self.lock:
            self.completions.append(start)
            # Permit the first range only after two later ranges have finished.
            if len([offset for offset in self.completions if offset != self.blocked_start]) >= 2:
                self.release_first.set()

    def __call__(self, request, timeout):
        match = re.fullmatch(r'bytes=(\d+)-(\d+)', request.get_header('Range'))
        if not match:
            raise AssertionError('Every request must be bounded.')
        start, end = map(int, match.groups())
        with self.lock:
            self.requests.append((start, end, request.full_url, timeout, dict(request.header_items())))
            self.attempts[start] = self.attempts.get(start, 0) + 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        override = self.failures.get(start, {})
        body = override.get('body', self.payload[start:end + 1])
        return Response(self, start, end, body, status=override.get('status', 206),
                        headers=override.get('headers'), invalid_count=override.get('invalid_count', False))


class RangeDownload(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='range-download-test-')
        self.addCleanup(self.temp.cleanup)
        self.partial = Path(self.temp.name) / 'fixture.gguf.part'
        self.payload = bytes(range(43))
        self.entry = {'url': 'https://publisher.example.test/revision/model.gguf',
                      'size': len(self.payload), 'name': 'fixture.gguf'}
        self.output = io.StringIO()

    def download(self, fixture, **kwargs):
        with patch.object(range_download.urllib.request, 'urlopen', fixture), redirect_stdout(self.output):
            return range_download.download(self.entry, self.partial, **kwargs)

    def test_failed_future_tracebacks_release_range_buffers(self):
        fixture = Fixture(self.payload, failures={0: {'invalid_count': True}})
        failure = None
        try:
            self.download(fixture, workers=4, chunk_size=5)
        except range_download.RangeDownloadError as error:
            failure = error
        self.assertIsNotNone(failure)
        frame = failure.__traceback__
        inspected = set()
        while frame:
            name = frame.tb_frame.f_code.co_name
            values = frame.tb_frame.f_locals
            if frame.tb_frame.f_code is range_download.download.__code__:
                inspected.add(name)
                self.assertEqual(len(values['pending']), 0)
                self.assertIsNone(values['data'])
                self.assertIsNone(values['future'])
            if frame.tb_frame.f_code is range_download._read_range.__code__:
                inspected.add(name)
                self.assertIsNone(values['data'])
            frame = frame.tb_next
        self.assertEqual(inspected, {'download', '_read_range'})
        self.assertLessEqual(self.partial.stat().st_size, len(self.payload))

    def test_failed_disk_sync_traceback_releases_append_buffer(self):
        failure = None
        with patch.object(range_download.os, 'fsync', side_effect=OSError('synthetic sync failure')):
            try:
                self.download(Fixture(self.payload), workers=4, chunk_size=5)
            except OSError as error:
                failure = error
        self.assertIsNotNone(failure)
        frame = failure.__traceback__
        inspected = False
        while frame:
            if frame.tb_frame.f_code is range_download._append.__code__:
                self.assertIsNone(frame.tb_frame.f_locals['data'])
                inspected = True
            frame = frame.tb_next
        self.assertTrue(inspected)
        self.assertEqual(self.partial.read_bytes(), self.payload[:5])

    def test_resumed_out_of_order_ranges_append_contiguously(self):
        self.partial.write_bytes(self.payload[:3])
        fixture = Fixture(self.payload, blocked_start=3)
        before_append = []
        real_append = range_download._append

        def inspect_append(stream, data):
            current = self.partial.read_bytes()
            before_append.append(len(current))
            self.assertEqual(current, self.payload[:len(current)])
            self.assertEqual(data, self.payload[len(current):len(current) + len(data)])
            real_append(stream, data)

        with patch.object(range_download, '_append', inspect_append):
            result = self.download(fixture, workers=4, chunk_size=5)
        self.assertEqual(result, self.partial)
        self.assertEqual(self.partial.read_bytes(), self.payload)
        self.assertEqual(before_append, list(range(3, len(self.payload), 5)))
        self.assertNotEqual(fixture.completions[0], 3)
        self.assertGreater(fixture.max_active, 1)
        self.assertLessEqual(fixture.max_active, 4)
        self.assertEqual(sorted(fixture.attempts), list(range(3, len(self.payload), 5)))
        progress = [json.loads(line) for line in self.output.getvalue().splitlines()]
        self.assertEqual([item['bytes'] for item in progress], list(range(8, len(self.payload) + 1, 5)))
        self.assertEqual(progress[-1]['percent'], 100.0)

    def test_window_does_not_fetch_a_fifth_range_before_first_append(self):
        fixture = Fixture(self.payload, blocked_start=0)
        initial_window = []
        real_append = range_download._append

        def inspect_append(stream, data):
            if not initial_window:
                with fixture.lock:
                    initial_window.extend(start for start, *_ in fixture.requests)
                self.assertEqual(self.partial.stat().st_size, 0)
            real_append(stream, data)

        with patch.object(range_download, '_append', inspect_append):
            self.download(fixture, workers=4, chunk_size=5)
        self.assertEqual(sorted(initial_window), [0, 5, 10, 15])

    def test_failure_retains_only_completed_contiguous_prefix_and_resumes(self):
        fixture = Fixture(self.payload, blocked_start=0, failures={5: {'body': b'\x05'}})
        with self.assertRaises(range_download.RangeDownloadError):
            self.download(fixture, workers=4, chunk_size=5)
        self.assertEqual(self.partial.read_bytes(), self.payload[:5])
        self.assertEqual(fixture.attempts[5], 2)
        self.assertEqual([json.loads(line)['bytes'] for line in self.output.getvalue().splitlines()], [5])
        resumed = Fixture(self.payload)
        self.download(resumed, workers=4, chunk_size=5)
        self.assertEqual(self.partial.read_bytes(), self.payload)
        self.assertEqual(min(resumed.attempts), 5)

    def test_rejects_invalid_range_status_headers_encoding_and_byte_counts(self):
        cases = [
            {'status': 200},
            {'headers': {'Content-Range': 'bytes 1-5/43'}},
            {'headers': {'Content-Range': 'bytes 0-4/*'}},
            {'headers': {'Content-Range': 'bytes 0-4/44'}},
            {'headers': {'Content-Length': '6'}},
            {'headers': {'Content-Length': 'invalid'}},
            {'headers': {'Content-Encoding': 'gzip'}},
            {'body': b'\x00\x01'},
            {'body': self.payload[:6]},
            {'invalid_count': True},
        ]
        for override in cases:
            with self.subTest(override=override):
                self.partial.write_bytes(b'')
                fixture = Fixture(self.payload, failures={0: override})
                with self.assertRaises(range_download.RangeDownloadError):
                    self.download(fixture, workers=1, chunk_size=5)
                self.assertEqual(self.partial.read_bytes(), b'')
                self.assertEqual(fixture.attempts, {0: 2})

    def test_one_retry_recovers_without_appending_failed_range_bytes(self):
        fixture = Fixture(self.payload, failures={0: {'body': b'\x00'}})
        real_open = fixture

        def opener(request, timeout):
            if fixture.attempts.get(0) == 1:
                fixture.failures.clear()
            return real_open(request, timeout)

        self.download(opener, workers=1, chunk_size=5)
        self.assertEqual(self.partial.read_bytes(), self.payload)
        self.assertEqual(fixture.attempts[0], 2)

    def test_cache_query_preserves_existing_query_and_uses_exact_offsets(self):
        self.entry['url'] += '?token=fixture%2Bvalue&download=false&range_start=999'
        original = dict(self.entry)
        self.partial.write_bytes(self.payload[:7])
        fixture = Fixture(self.payload)
        self.download(fixture, workers=2, chunk_size=9)
        for start, end, url, timeout, headers in fixture.requests:
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            self.assertEqual(query, {'token': ['fixture+value'], 'download': ['true'], 'range_start': [str(start)]})
            self.assertEqual(timeout, 45)
            self.assertEqual(headers['Accept-encoding'], 'identity')
            self.assertLessEqual(end - start + 1, 9)
        self.assertEqual(self.entry, original)
        self.assertEqual(self.partial.read_bytes(), self.payload)

    def test_oversized_partial_is_refused_without_request_or_modification(self):
        self.partial.write_bytes(self.payload + b'extra')
        with patch.object(range_download.urllib.request, 'urlopen', side_effect=AssertionError('No remote request')):
            with self.assertRaises(range_download.RangeDownloadError):
                range_download.download(self.entry, self.partial)
        self.assertEqual(self.partial.read_bytes(), self.payload + b'extra')

    def test_completed_partial_is_preserved_without_request(self):
        self.partial.write_bytes(self.payload)
        with patch.object(range_download.urllib.request, 'urlopen', side_effect=AssertionError('No remote request')):
            self.assertEqual(range_download.download(self.entry, self.partial), self.partial)
        self.assertEqual(self.partial.read_bytes(), self.payload)

    def test_worker_returned_offset_is_verified_before_append(self):
        with patch.object(range_download, '_read_range', return_value=(1, bytearray(self.payload[:5]))):
            with self.assertRaises(range_download.RangeDownloadError):
                range_download.download(self.entry, self.partial, workers=1, chunk_size=5)
        self.assertEqual(self.partial.read_bytes(), b'')

    def test_invalid_configuration_is_refused_before_creating_partial(self):
        for options in ({'workers': 0}, {'workers': 5}, {'workers': True}, {'chunk_size': 0},
                        {'chunk_size': range_download.MAX_CHUNK_SIZE + 1}, {'chunk_size': True}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                range_download.download(self.entry, self.partial, **options)
        for field, value in (('url', 'http://publisher.example.test/model'), ('url', 'https://user:secret@example.test/model'),
                             ('url', 'https://publisher.example.test/model#fragment'), ('size', -1), ('size', True), ('name', '')):
            entry = dict(self.entry, **{field: value})
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                range_download.download(entry, self.partial)
        self.assertFalse(self.partial.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
