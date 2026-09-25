"""Resume one verified manifest entry using bounded HTTP byte ranges."""
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

manifest_path, file_name, partial_path = sys.argv[1:]
manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8-sig'))
entry = next(item for item in manifest['files'] if item['name'] == file_name)
partial = Path(partial_path)
total = entry['size']
offset = partial.stat().st_size if partial.exists() else 0
if offset > total:
    raise RuntimeError('Partial file exceeds expected size; retained for inspection.')
while offset < total:
    end = min(offset + 64 * 1024 * 1024, total) - 1
    for attempt in range(2):
        try:
            # The query avoids stale cached redirect URLs for successive range requests.
            request = urllib.request.Request(entry['url'] + '?download=true&range_start=' + str(offset),
                                             headers={'Range': f'bytes={offset}-{end}', 'User-Agent': 'LocalLLM-Installer/1.0'})
            with urllib.request.urlopen(request, timeout=45) as response:
                content_range = response.headers.get('Content-Range', '')
                match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', content_range)
                if response.status != 206 or not match or tuple(map(int, match.groups())) != (offset, end, total):
                    raise RuntimeError('Server did not confirm the requested byte range.')
                received = 0
                with partial.open('ab') as dest:
                    while received < end - offset + 1:
                        data = response.read(min(1024 * 1024, end - offset + 1 - received))
                        if not data:
                            raise RuntimeError('Transfer ended before the requested byte range completed.')
                        dest.write(data)
                        received += len(data)
            offset = partial.stat().st_size
            print(json.dumps({'file': file_name, 'bytes': offset, 'total': total, 'percent': round(offset / total * 100, 1)}), flush=True)
            break
        except Exception:
            if attempt:
                raise
            offset = partial.stat().st_size if partial.exists() else 0
            if offset > end:
                break
            time.sleep(2)
