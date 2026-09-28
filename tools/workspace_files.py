"""Bounded, paged file exploration. Never follow links outside a project."""
import codecs
import fnmatch
import os
from pathlib import Path
import stat
import time

TEXT_LIMIT = 16 * 1024 * 1024
OUTPUT_LIMIT = 2400
LINE_LIMIT = 120
SKIP_DIRS = {'.git', '.venv', 'venv', 'node_modules', '__pycache__', '.cache'}


def text_file(path, limit=TEXT_LIMIT):
    if not path.is_file():
        raise ValueError('Specify a file, not a folder. Use list_workspace or search_workspace first.')
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f'Text exceeds the {limit // 1024 // 1024} MB inspection limit; narrow the file first.')
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return raw.decode('utf-16'), 'utf-16'
    if b'\0' in raw:
        raise ValueError('Binary file: use open_workspace_image for images; text reading cannot parse PDF/Office/archive files.')
    for encoding in ('utf-8-sig', 'cp932'):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            pass
    raise ValueError('Unsupported text encoding. Supported: UTF-8, UTF-16 with BOM, CP932.')


def read(root, path, start_line=1, max_lines=60, start_column=0):
    if start_line < 1 or max_lines < 1 or start_column < 0:
        raise ValueError('start_line >= 1, max_lines >= 1, start_column >= 0.')
    requested_lines = max_lines
    max_lines = min(max_lines, LINE_LIMIT)
    text, encoding = text_file(path)
    lines = text.splitlines(keepends=True)
    if start_line > max(1, len(lines)):
        raise ValueError(f'File has {len(lines)} lines; start_line is beyond EOF.')
    index, column, left, parts = start_line - 1, start_column, OUTPUT_LIMIT, []
    if lines and column > len(lines[index]):
        raise ValueError('start_column is beyond this line.')
    while index < len(lines) and index < start_line - 1 + max_lines and left:
        piece = lines[index][column:column + left]
        parts.append(piece); left -= len(piece); column += len(piece)
        if column == len(lines[index]):
            index += 1; column = 0
    more = index < len(lines)
    return {'path': path.relative_to(root).as_posix(), 'encoding': encoding, 'total_lines': len(lines),
            'start_line': start_line, 'start_column': start_column, 'content': ''.join(parts),
            'requested_max_lines': requested_lines, 'effective_max_lines': max_lines,
            'character_limit': OUTPUT_LIMIT,
            'truncated': more, 'next_line': index + 1 if more else None,
            'next_column': column if more else None}


def listing(root, path, offset=0):
    if offset < 0:
        raise ValueError('offset must be >= 0.')
    entries = sorted(path.iterdir(), key=lambda p: p.name.casefold())
    items, size = [], 0
    for item in entries[offset:offset + 60]:
        name = item.name
        if items and size + len(name) > OUTPUT_LIMIT:
            break
        is_link = bool(item.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
        items.append({'name': name, 'directory': item.is_dir(), 'link': is_link})
        size += len(name)
    end = offset + len(items)
    return {'directory': path.relative_to(root).as_posix(), 'entries': items, 'total': len(entries),
            'next_offset': end if end < len(entries) else None}


def search(root, path, query, content=False, offset=0):
    if not query.strip() or len(query) > 200 or offset < 0:
        raise ValueError('Use a nonempty query up to 200 characters and offset >= 0.')
    if not path.is_dir():
        raise ValueError('Search directory does not exist or is not a folder.')
    matches, skipped, visited, size, read_bytes = [], 0, 0, 0, 0
    deadline = time.monotonic() + 4
    needle = query.casefold()
    pattern = needle if any(x in needle for x in '*?[') else '*' + needle + '*'
    def walk_error(_):
        nonlocal skipped
        skipped += 1
    for parent, dirs, files in os.walk(path, followlinks=False, onerror=walk_error):
        safe_dirs = []
        for name in sorted(dirs, key=str.casefold):
            p = Path(parent) / name
            try:
                if name not in SKIP_DIRS and not p.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                    safe_dirs.append(name)
                else:
                    skipped += 1
            except OSError:
                skipped += 1
        dirs[:] = safe_dirs
        for name in sorted(files, key=str.casefold):
            visited += 1
            if visited <= offset:
                continue
            if visited - offset > 3000 or len(matches) >= 30 or size >= OUTPUT_LIMIT or read_bytes >= TEXT_LIMIT or time.monotonic() > deadline:
                return {'matches': matches, 'next_offset': visited - 1, 'skipped': skipped,
                        'partial': True, 'note': 'Continue with next_offset; narrow directory/query for large projects.'}
            p = Path(parent) / name
            try:
                if p.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT or not p.resolve().is_relative_to(root):
                    skipped += 1; continue
                relative = p.relative_to(root).as_posix()
                if not content:
                    if fnmatch.fnmatchcase(relative.casefold(), pattern):
                        matches.append({'path': relative}); size += len(relative)
                else:
                    length = p.stat().st_size
                    if length > 2 * 1024 * 1024:
                        skipped += 1; continue
                    read_bytes += length
                    text, encoding = text_file(p, 2 * 1024 * 1024)
                    for number, line in enumerate(text.splitlines(), 1):
                        found = line.casefold().find(needle)
                        if found >= 0:
                            snippet = line[max(0, found - 60):found + 160]
                            matches.append({'path': relative, 'line': number, 'snippet': snippet})
                            size += len(relative) + len(snippet)
                            break  # First matching line per file; read the excerpt for more.
            except (OSError, ValueError, UnicodeError):
                skipped += 1
    return {'matches': matches, 'next_offset': None, 'skipped': skipped, 'partial': False,
            'note': 'Content search returns the first matching line per file. Binary/large/inaccessible files and cache folders are skipped.'}


def inspect(studio, operation, path='.', **kwargs):
    # Return actionable errors to the model instead of opaque tool exceptions.
    try:
        root = studio.current_project()
        projects, context = studio.project_module()
        target = projects.resolve(context, path, root)
        return operation(root, target, **kwargs)
    except (OSError, ValueError, UnicodeError) as error:
        reason = str(error)
        return {'error': type(error).__name__, 'reason': reason,
                'next_step': 'Check current_project, then list_workspace or search_workspace. Use a returned path; do not repeat the same failed call.'}
