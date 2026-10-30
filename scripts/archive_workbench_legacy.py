"""Audit and verify legacy version backups; never move originals or restore DBs.

Default operation writes only a plan and complete file hashes. --backup adds
verified ZIPs under .local/workbench-archives/<id>. --execute-retirement requires
an exact reviewed plan, selected entries, a deployed new runtime and a fresh
process/pending-task audit. It renames originals into the archive, never deletes
them or restores a DB. No application module is imported or business DB copied.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import zipfile

VERSION_FOLDERS = ('releases', 'native-releases', 'workbench-releases', 'backend-releases')
DEFAULT_LEGACY = Path('D:/Projects/ai-news-desk')
FORBIDDEN_SUFFIXES = ('.sqlite', '.sqlite-wal', '.sqlite-shm', '.db', '.db-wal', '.db-shm')
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,100}')
# Explicit 2026-10-31 integration review; these are historical evidence, never
# live DB rollback inputs. No other database/data path can use this exception.
REVIEWED_PACKAGE_EXCEPTIONS = {
    'legacy/releases/production-queue-20261017-111939': {
        'desk-before.sqlite': {'bytes': 17956864, 'mtime_ns': 1792207179598629200,
            'sha256': '03a0db0edb5d0ffa7fefc6fcb944d2246f1984ee6d615a6e05663caa6d1d5c36'}},
    'legacy/backend-releases/toolbox-content-studio-20261025-100247': {
        'data/artifacts/9197abcd5fae9d262ccb6c799894bc62085ca1d07a15e573c2ae613aec43e525/标题与配文.txt': {
            'bytes': 44, 'mtime_ns': 1792898054357014000,
            'sha256': '8c49d36a7c383874e744496fe6bc728e2bef772022227caec78fe5e46af85960'}}}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def linked(path):
    return path.is_symlink() or getattr(path, 'is_junction', lambda: False)()


def absolute(path):
    path = Path(path)
    if not path.is_absolute() or linked(path):
        raise ValueError('An absolute, non-link path is required: ' + str(path))
    return path.resolve()


def fenced(path, base):
    """Check every existing path segment before any write, not only resolve()."""
    path, base = Path(path), absolute(base)
    if not path.is_absolute() or not path.is_relative_to(base) or path == base:
        raise ValueError('Path leaves the explicit fence: ' + str(path))
    current = base
    for part in path.relative_to(base).parts:
        current /= part
        if linked(current):
            raise ValueError('Links/junctions are not archive members: ' + str(current))
    resolved = path.resolve()
    if not resolved.is_relative_to(base):
        raise ValueError('Resolved path leaves archive fence')
    return resolved


def safe_member(name):
    parts = name.replace('\\', '/').split('/')
    reserved = {'CON', 'PRN', 'AUX', 'NUL', *[f'{prefix}{n}' for prefix in ('COM', 'LPT') for n in range(1, 10)]}
    return bool(parts) and all(part and part not in ('.', '..') and ':' not in part
                               and part.rstrip(' .') == part and part.split('.')[0].upper() not in reserved
                               for part in parts) and not name.startswith(('/', '\\'))


def prohibited(relative):
    parts = Path(relative).parts
    return ('skill-inputs' in parts or parts[0] in ('data', 'outputs')
            or str(relative).lower().endswith(FORBIDDEN_SUFFIXES))


def version_directories(roots):
    entries = []
    for alias, root in roots.items():
        for folder in VERSION_FOLDERS:
            base = root / folder
            if not base.exists():
                continue
            if linked(base):
                raise ValueError('Version container is a link: ' + str(base))
            for child in sorted(base.iterdir()):
                if not child.is_dir() and not linked(child):
                    continue
                if not NAME.fullmatch(child.name):
                    raise ValueError('Invalid version directory name: ' + str(child))
                entries.append({'key': alias + '/' + folder + '/' + child.name,
                                'root_alias': alias, 'folder': folder, 'name': child.name,
                                'source': str(child), 'holds': [], 'bytes': 0, 'files': 0})
    return entries


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def controls(roots):
    """Live selectors only; historical validation reports are not selectors."""
    result = []
    for alias, root in roots.items():
        paths = set((root / 'data').glob('active*.json'))
        paths.update(p for p in (root / 'data').glob('*candidate*.json'))
        for name in ('migration-owner.json', 'local-first-pids.json', 'pids.json',
                     'collection-pids.json', 'distribution-pids.json'):
            if (root / 'data' / name).is_file():
                paths.add(root / 'data' / name)
        state = root / '.local/workbench-deployment'
        if state.exists():
            paths.update(p for p in state.glob('*.json') if 'candidate' in p.name
                         or p.name in ('admission.json', 'activation.json', 'upgrade.json'))
        for path in sorted(paths):
            if linked(path):
                raise ValueError('Control file is a link: ' + str(path))
            result.append({'root_alias': alias, 'path': str(path), 'sha256': digest(path),
                           'value': read_json(path)})
    return result


def process_inventory():
    if os.name != 'nt':
        return []
    command = ('Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,CreationDate,CommandLine '
               '| ConvertTo-Json -Compress -Depth 3')
    raw = subprocess.check_output(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                                  encoding='utf-8', errors='replace')
    value = json.loads(raw or '[]')
    return value if isinstance(value, list) else [value]


def path_values(text, roots):
    """Extract path strings from JSON without writing feedback/credential bodies."""
    def collect(value):
        if isinstance(value, str):
            normal = re.sub('/+', '/', value.replace('\\', '/'))
            prefixes = [str(root).replace('\\', '/') + '/' for root in roots.values()]
            if normal.startswith(('outputs/', 'data/', *[folder + '/' for folder in VERSION_FOLDERS])) or any(normal.lower().startswith(p.lower()) for p in prefixes):
                if len(normal) <= 4096 and '\n' not in normal and '\r' not in normal:
                    yield normal
        elif isinstance(value, dict):
            for item in value.values():
                yield from collect(item)
        elif isinstance(value, list):
            for item in value:
                yield from collect(item)
    try:
        value = json.loads(text)
    except (ValueError, RecursionError):
        value = text
    try:
        return sorted(set(collect(value)))
    except RecursionError:
        return []


def scan_references(roots, entries, processes, emit):
    names = defaultdict(list)
    sources = {e['key']: e['source'].replace('\\', '/').lower() for e in entries}
    for entry in entries:
        names[entry['name'].lower()].append(entry['key'])
    prefixes = sorted({name.split('-')[0] for name in names})
    token = re.compile(r'(?<![A-Za-z0-9_.-])(?:' + '|'.join(re.escape(p) for p in prefixes) + r')[A-Za-z0-9_.-]{1,120}', re.IGNORECASE) if prefixes else re.compile(r'(?!)')
    hits, statistics = defaultdict(list), Counter()

    def examine(text, origin, location):
        if isinstance(text, bytes):
            try:
                text = text.decode('utf-8')
            except UnicodeDecodeError:
                statistics['binary_cells_not_text'] += 1
                return
        if not isinstance(text, str):
            return
        statistics['text_cells'] += 1
        lowered = text.lower()
        if not any(prefix in lowered for prefix in prefixes) and not any(marker in lowered for marker in ('skill-inputs', 'outputs/', 'outputs\\', 'data/', 'data\\', ':/', ':\\')):
            return
        matched = sorted({key for name in token.findall(text) for key in names.get(name.lower(), ())})
        normalized = re.sub('/+', '/', text.replace('\\', '/')).lower()
        legacy_paths = 'legacy' in roots and str(roots['legacy']).replace('\\', '/').lower() in normalized
        frozen = 'skill-inputs/' in normalized
        paths = path_values(text, roots) if any(p in normalized for p in ('path', 'outputs/', 'data/', ':/')) else []
        if not (matched or legacy_paths or frozen or paths):
            return
        reference = {'origin': origin, 'location': location, 'releases': matched,
                     'legacy_root_reference': bool(legacy_paths), 'frozen_input_reference': frozen,
                     'paths': paths, 'value_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest()}
        emit(reference)
        statistics[origin + '_references'] += 1
        statistics['frozen_input_references'] += int(frozen)
        statistics['legacy_root_references'] += int(legacy_paths)
        for key in matched:
            source = sources[key]
            direct_path = any(p.lower() == source or p.lower().startswith(source + '/') for p in paths)
            hits[key].append({'origin': origin, 'location': location, 'path_reference': direct_path})

    selectors = controls(roots)
    for selector in selectors:
        name = Path(selector['path']).name
        origin = ('selector' if selector['root_alias'] == 'project' else 'legacy_selector') if name.startswith('active') or 'candidate' in name else 'ownership_history'
        examine(json.dumps(selector['value']), origin, selector['path'])
    for process in processes:
        command = process.get('CommandLine') or ''
        examine(command, 'process', {'pid': process.get('ProcessId'), 'created': process.get('CreationDate')})
    # Read-only transactions include WAL, unlike immutable=1. Never backup a DB.
    database_report = []
    for alias, root in roots.items():
        for db in sorted((root / 'data').glob('*.sqlite')):
            if linked(db):
                raise ValueError('Database is a link')
            report = {'path': str(db), 'mode': 'ro', 'bytes': db.stat().st_size, 'tables': 0, 'rows': 0}
            with sqlite3.connect(db.as_uri() + '?mode=ro', uri=True, timeout=10) as connection:
                connection.execute('PRAGMA query_only=ON')
                connection.execute('BEGIN')
                for (table,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
                    quote = lambda name: '"' + name.replace('"', '""') + '"'
                    columns = [row[1] for row in connection.execute('PRAGMA table_info(' + quote(table) + ')')]
                    report['tables'] += 1
                    for number, row in enumerate(connection.execute('SELECT * FROM ' + quote(table)), 1):
                        report['rows'] += 1
                        for column, cell in zip(columns, row):
                            examine(cell, 'database', {'database': str(db), 'table': table,
                                                       'row_ordinal': number, 'column': column})
                connection.rollback()
            database_report.append(report)
    # Actual package source (not reports/tests) may pin an immutable asset URL.
    source_paths = set()
    for alias, root in roots.items():
        for folder in ('easel_workbench', 'scripts', 'web'):
            base = root / folder
            if base.exists():
                for current, dirs, files in os.walk(base, followlinks=False):
                    dirs[:] = [d for d in dirs if d not in ('node_modules', '__pycache__', 'dist') and not linked(Path(current) / d)]
                    for name in files:
                        path = Path(current) / name
                        if path.suffix in ('.py', '.pyw', '.js', '.mjs', '.ts', '.tsx', '.html', '.json', '.css'):
                            source_paths.add(path)
        source_paths.update(root.glob('*.py'))
        source_paths.update(root.glob('*.pyw'))
    for path in sorted(source_paths):
        if linked(path):
            raise ValueError('Source file is a link')
        try:
            examine(path.read_text(encoding='utf-8-sig'), 'source', str(path))
        except UnicodeDecodeError:
            statistics['non_utf8_source_files'] += 1
    # Propagate dependency protection only from held runtime packages, not all old manifests.
    manifests = {}
    for entry in entries:
        for name in ('workbench-release.json', 'native-manifest.json', 'release.json', 'backend-manifest.json'):
            path = Path(entry['source']) / name
            if path.is_file() and not linked(path):
                manifests[entry['key']] = path
                break
    protected = {key for key, refs in hits.items() if any(r['origin'] in ('selector', 'process') for r in refs)}
    pending = list(protected)
    while pending:
        key = pending.pop()
        if key not in manifests:
            continue
        value = manifests[key].read_text(encoding='utf-8-sig')
        dependencies = {other for name in token.findall(value) for other in names.get(name.lower(), ()) if other != key}
        for other in dependencies:
            hits[other].append({'origin': 'protected_package_dependency', 'location': key})
            if other not in protected:
                protected.add(other)
                pending.append(other)
    return hits, selectors, database_report, dict(statistics)


def enumerate_members(entry, emit):
    source = Path(entry['source'])
    if linked(source):
        entry['holds'].append({'origin': 'unsafe_link', 'location': str(source)})
        entry.update(backup_allowed=False, member_index_sha256=None)
        return
    hashes, problems, count, size = hashlib.sha256(), [], 0, 0
    reviewed = entry.get('reviewed_exception_members', {})
    for current, dirs, files in os.walk(source, followlinks=False):
        for name in sorted(dirs + files):
            path = Path(current) / name
            relative = path.relative_to(source).as_posix()
            allowed_parent = path.is_dir() and any(p.startswith(relative + '/') for p in reviewed)
            allowed_file = relative in reviewed and not path.is_dir()
            reason = 'unsafe_link' if linked(path) else 'prohibited_live_state' if prohibited(relative) and not (allowed_parent or allowed_file) else None
            if reason:
                problems.append({'origin': reason, 'location': relative})
                if name in dirs:
                    dirs.remove(name)
                emit({'package': entry['key'], 'path': relative, 'excluded': reason})
                continue
            if path.is_dir():
                continue
            if not safe_member(relative) or not path.resolve().is_relative_to(source.resolve()):
                raise ValueError('Unsafe archive member: ' + str(path))
            before = path.stat()
            checksum = digest(path)
            if allowed_file and ({'bytes': before.st_size, 'mtime_ns': before.st_mtime_ns, 'sha256': checksum} != reviewed[relative]
                    or any(Path(str(path) + suffix).exists() for suffix in ('-wal', '-shm'))):
                raise ValueError('Reviewed historical exception changed or has WAL/SHM: ' + str(path))
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError('Version changed during inventory: ' + str(path))
            member = {'package': entry['key'], 'path': relative, 'bytes': before.st_size,
                      'mtime_ns': before.st_mtime_ns, 'mode': before.st_mode, 'sha256': checksum}
            emit(member)
            hashes.update(encoded(member) + b'\n')
            count += 1
            size += before.st_size
    entry.update(files=count, bytes=size, member_index_sha256=hashes.hexdigest(), backup_allowed=not problems)
    entry['holds'].extend(problems)


def create_plan(root, legacy, archive_id, *, processes=(), keep=(), only=(), reviewed_exceptions=()):
    root = absolute(root)
    roots = {'project': root}
    if legacy is not None:
        legacy = absolute(legacy)
        if legacy == root or legacy.is_relative_to(root) or root.is_relative_to(legacy):
            raise ValueError('Source roots must be distinct and non-nested')
        roots['legacy'] = legacy
    if not NAME.fullmatch(archive_id) or archive_id.split('.')[0].upper() in ('CON', 'PRN', 'AUX', 'NUL'):
        raise ValueError('Invalid archive ID')
    base = fenced(root / '.local/workbench-archives', root)
    target = fenced(base / archive_id, root)
    entries = version_directories(roots)
    if only:
        if set(only) - {e['key'] for e in entries}:raise ValueError('Unknown exact selected package')
        entries = [e for e in entries if e['key'] in only]
    if set(reviewed_exceptions) - set(REVIEWED_PACKAGE_EXCEPTIONS):
        raise ValueError('Historical exception is not explicitly allowlisted')
    for entry in entries:
        if entry['key'] in reviewed_exceptions:
            entry['reviewed_exception_members'] = REVIEWED_PACKAGE_EXCEPTIONS[entry['key']]
    # Never reuse an evidence directory or overwrite an existing backup.
    target.mkdir(parents=True, exist_ok=False)
    with (target / 'references.jsonl').open('xb') as stream:
        emit = lambda row: stream.write(encoded(row) + b'\n')
        hits, selectors, databases, reference_stats = scan_references(roots, entries, processes, emit)
    keep = validate_kept_paths(root, keep)
    for entry in entries:
        if keep and not linked(Path(entry['source'])) and str(absolute(entry['source'])) in keep:
            hits[entry['key']].append({'origin': 'explicit_keep', 'location': entry['source']})
    with (target / 'inventory.jsonl').open('xb') as stream:
        emit = lambda row: stream.write(encoded(row) + b'\n')
        for entry in entries:
            entry['holds'].extend(hits[entry['key']])
            if entry.get('reviewed_exception_members') and any(h['origin'] == 'process' for h in entry['holds']):
                raise ValueError('Reviewed historical evidence has a process reference')
            if entry['folder'] in ('native-releases', 'releases'):
                entry['holds'].append({'origin': 'legacy_asset_route_review_required', 'location': entry['folder']})
            enumerate_members(entry, emit)
            entry['unreferenced_in_scanned_sources'] = not entry['holds']
            entry['retirement_allowed'] = False  # No move/delete until integration closes references.
    snapshots = []
    for alias, source_root in roots.items():
        frozen = source_root / 'outputs/_sessions/skill-inputs'
        if frozen.exists():
            snapshots.append({'root_alias': alias, 'path': str(frozen),
                              'snapshots': sum(p.is_dir() for p in frozen.iterdir()),
                              'excluded_from_archive': True})
    plan = {'schema': 1, 'created_at': datetime.now(timezone.utc).isoformat(), 'mode': 'dry-run',
            'root': str(root), 'archive_directory': str(target), 'roots': {k: str(v) for k, v in roots.items()},
            'originals_modified': False, 'database_backup_or_rollback': False,
            'explicit_keep_paths': keep,
            'reviewed_historical_exceptions': list(reviewed_exceptions),
            'retirement_enabled': False, 'offline_client_asset_references_not_provable': True,
            'coverage': 'All text/UTF-8 BLOB cells in every data/*.sqlite table; selected source and live selectors. Binary BLOBs are counted, not guessed.',
            'selectors': [{k: row[k] for k in ('root_alias', 'path', 'sha256')} for row in selectors],
            'databases_read_only': databases, 'reference_statistics': reference_stats, 'frozen_inputs': snapshots,
            'entries': entries, 'totals': {'packages': len(entries), 'files': sum(e['files'] for e in entries),
                'bytes': sum(e['bytes'] for e in entries), 'backup_allowed': sum(e['backup_allowed'] for e in entries),
                'unreferenced': sum(e['unreferenced_in_scanned_sources'] for e in entries)},
            'inventory_sha256': digest(target / 'inventory.jsonl'), 'references_sha256': digest(target / 'references.jsonl')}
    (target / 'plan.json').write_bytes(encoded(plan))
    (target / 'plan.sha256').write_text(digest(target / 'plan.json') + '\n', encoding='ascii')
    return plan


def members_by_package(target):
    result = defaultdict(list)
    with (target / 'inventory.jsonl').open(encoding='utf-8') as stream:
        for line in stream:
            row = json.loads(line)
            if 'sha256' in row:
                result[row['package']].append(row)
    return result


def backup(plan):
    root, target = absolute(plan['root']), absolute(plan['archive_directory'])
    fenced(target, root)
    fenced(target, root / '.local/workbench-archives')
    if (read_json(target / 'plan.json') != plan
            or digest(target / 'plan.json') != (target / 'plan.sha256').read_text(encoding='ascii').strip()
            or digest(target / 'inventory.jsonl') != plan['inventory_sha256']
            or digest(target / 'references.jsonl') != plan['references_sha256']):
        raise ValueError('Plan/index changed before backup')
    index = members_by_package(target)
    total = sum(entry['bytes'] for entry in plan['entries'] if entry['backup_allowed'])
    if shutil.disk_usage(target).free < total + 100 * 1024 * 1024:
        raise ValueError('Insufficient free disk for conservative uncompressed backup budget')
    results = []
    for entry in plan['entries']:
        if not entry['backup_allowed']:
            continue
        source = absolute(entry['source'])
        source_root = absolute(plan['roots'][entry['root_alias']])
        fenced(source, source_root)
        fenced(source, source_root / entry['folder'])
        destination = fenced(target / 'backups' / (entry['key'] + '.zip'), target)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as archive:
            for member in index[entry['key']]:
                reviewed = REVIEWED_PACKAGE_EXCEPTIONS.get(entry['key'], {}).get(member['path']) if entry.get('reviewed_exception_members') else None
                if (prohibited(member['path']) and not reviewed) or not safe_member(member['path']):
                    raise ValueError('Prohibited backup member')
                path = fenced(source / member['path'], source)
                before = path.stat()
                if reviewed and (reviewed != {k: member[k] for k in ('bytes', 'mtime_ns', 'sha256')}
                        or any(Path(str(path) + suffix).exists() for suffix in ('-wal', '-shm'))):
                    raise ValueError('Historical exception proof or WAL state changed')
                if before.st_size != member['bytes'] or before.st_mtime_ns != member['mtime_ns']:
                    raise ValueError('Source changed since plan: ' + str(path))
                checksum = hashlib.sha256()
                with path.open('rb') as original, archive.open(member['path'], 'w', force_zip64=True) as copied:
                    for block in iter(lambda: original.read(1024 * 1024), b''):
                        copied.write(block)
                        checksum.update(block)
                after = path.stat()
                if checksum.hexdigest() != member['sha256'] or after.st_mtime_ns != before.st_mtime_ns or after.st_size != before.st_size:
                    raise ValueError('Source changed while copying: ' + str(path))
        results.append({'package': entry['key'], 'path': destination.relative_to(target).as_posix(),
                        'bytes': destination.stat().st_size, 'sha256': digest(destination)})
    historical_databases = sum(member['path'].lower().endswith(('.sqlite', '.db')) for entry in plan['entries']
        if entry['backup_allowed'] for member in index[entry['key']])
    receipt = {'schema': 1, 'mode': 'verified-copy-only', 'plan_sha256': digest(target / 'plan.json'),
               'inventory_sha256': digest(target / 'inventory.jsonl'), 'backups': results,
               'originals_modified': False, 'databases_copied': bool(historical_databases), 'activation_performed': False,
               'historical_evidence_exceptions': plan.get('reviewed_historical_exceptions', []),
               'historical_database_snapshots_copied': historical_databases,
               'live_databases_copied': False, 'rollback_performed': False}
    (target / 'backup.json').write_bytes(encoded(receipt))
    return verify_backup(target)


def verify_backup(directory):
    target = absolute(directory)
    plan, receipt = read_json(target / 'plan.json'), read_json(target / 'backup.json')
    fenced(target, absolute(plan['root']))
    fenced(target, absolute(plan['root']) / '.local/workbench-archives')
    if digest(target / 'plan.json') != (target / 'plan.sha256').read_text(encoding='ascii').strip():
        raise ValueError('Reviewed plan hash changed')
    if digest(target / 'plan.json') != receipt['plan_sha256'] or digest(target / 'inventory.jsonl') != receipt['inventory_sha256']:
        raise ValueError('Archive metadata changed')
    if digest(target / 'inventory.jsonl') != plan['inventory_sha256'] or digest(target / 'references.jsonl') != plan['references_sha256']:
        raise ValueError('Archive indexes changed')
    index = members_by_package(target)
    expected_packages = {entry['key'] for entry in plan['entries'] if entry['backup_allowed']}
    if {item['package'] for item in receipt['backups']} != expected_packages or len(receipt['backups']) != len(expected_packages):
        raise ValueError('Incomplete/duplicate package backup')
    files = size = 0
    for item in receipt['backups']:
        path = fenced(target / item['path'], target)
        if digest(path) != item['sha256']:
            raise ValueError('ZIP bytes changed: ' + item['path'])
        members = {member['path']: member for member in index[item['package']]}
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or set(names) != set(members) or not all(safe_member(n) for n in names):
                raise ValueError('Unexpected/unsafe ZIP members')
            for name in names:
                h = hashlib.sha256()
                with archive.open(name) as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        h.update(block)
                if h.hexdigest() != members[name]['sha256'] or archive.getinfo(name).file_size != members[name]['bytes']:
                    raise ValueError('Restoration bytes differ from source inventory')
                files += 1
                size += members[name]['bytes']
    historical_databases = sum(member['path'].lower().endswith(('.sqlite', '.db'))
        for key in expected_packages for member in index[key])
    result = {'passed': True, 'packages': len(expected_packages), 'files': files, 'original_bytes': size,
              'zip_bytes': sum(item['bytes'] for item in receipt['backups']), 'originals_modified': False,
              'databases_copied': bool(historical_databases), 'live_databases_copied': False,
              'historical_database_snapshots_copied': historical_databases,
              'rollback_performed': False, 'activation_performed': False}
    (target / 'verification.json').write_bytes(encoded(result))
    return result


def validate_kept_paths(root, paths):
    result = []
    for value in paths:
        path = absolute(value)
        if path.parent.name not in VERSION_FOLDERS or path.parent.parent != root or not path.is_dir():
            raise ValueError('Keep must name an exact existing project version directory')
        fenced(path, root)
        result.append(str(path))
    return sorted(set(result))


def atomic_json(path, value):
    temporary = path.with_name(path.name + '.archive-new')
    with temporary.open('xb') as stream:
        stream.write(encoded(value)); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, path)


def pending_references(roots, entries):
    """Only execution rows can hold a runtime; completed provenance stays unchanged."""
    execution = {'tasks', 'creator_task_runs', 'creator_model_calls', 'media_jobs', 'easel_chat_turns',
                 'collection_tasks', 'distribution_attempts', 'distribution_deliveries', 'easel_native_corrections'}
    terminal = {'completed', 'done', 'failed', 'stopped', 'cancelled', 'canceled', 'expired', 'succeeded', 'success'}
    hits = []
    names = defaultdict(list)
    for entry in entries:names[entry['name'].lower()].append(entry['key'])
    prefixes = sorted({name.split('-')[0] for name in names})
    token = re.compile(r'(?<![a-z0-9_.-])(?:' + '|'.join(re.escape(p) for p in prefixes) + r')[a-z0-9_.-]{1,120}') if prefixes else re.compile(r'(?!)')
    for alias, root in roots.items():
        for db in (root / 'data').glob('*.sqlite'):
            with sqlite3.connect(db.as_uri() + '?mode=ro', uri=True, timeout=10) as connection:
                connection.execute('PRAGMA query_only=ON'); connection.execute('BEGIN')
                tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                for table in sorted(execution & tables):
                    columns = [r[1] for r in connection.execute('PRAGMA table_info("' + table + '")')]
                    for number, row in enumerate(connection.execute('SELECT * FROM "' + table + '"'), 1):
                        record = dict(zip(columns, row))
                        if isinstance(record.get('document'), str):
                            try:
                                document = json.loads(record['document'])
                                if isinstance(document, dict): record.update(document)
                            except ValueError:
                                pass
                        state = record.get('status', record.get('state'))
                        if isinstance(state, str) and state in terminal and all(record.get(hook) in (None, 'completed', 'failed', 'stopped') for hook in ('hook_status', 'start_hook_status')):
                            continue
                        text = json.dumps(record, default=str).lower()
                        if not any(prefix in text for prefix in prefixes):continue
                        for key in {key for name in token.findall(text) for key in names.get(name, ())}:
                            hits.append({'package': key, 'database': str(db), 'table': table,
                                         'row_ordinal': number, 'state': state or 'unknown'})
                connection.rollback()
    return hits


def check_members(directory, expected, reviewed=None):
    actual = {}
    for current, dirs, files in os.walk(directory, followlinks=False):
        if any(linked(Path(current) / name) for name in dirs + files):
            raise ValueError('Version acquired a link since backup')
        for name in files:
            path = Path(current) / name; relative = path.relative_to(directory).as_posix()
            if prohibited(relative) and relative not in (reviewed or {}):raise ValueError('Version contains live state')
            if relative in (reviewed or {}) and any(Path(str(path) + suffix).exists() for suffix in ('-wal', '-shm')):
                raise ValueError('Historical evidence acquired WAL/SHM')
            actual[relative] = digest(path)
            if relative in (reviewed or {}) and (actual[relative] != reviewed[relative]['sha256'] or path.stat().st_size != reviewed[relative]['bytes']):
                raise ValueError('Reviewed historical evidence bytes changed')
    if actual != {row['path']: row['sha256'] for row in expected}:
        raise ValueError('Version bytes/member set changed since backup: ' + str(directory))


def retire(directory, review_path, *, keep=(), processes=None):
    """Explicit integration-only rename with pinned review and a recovery journal."""
    target = absolute(directory); plan = read_json(target / 'plan.json')
    root = absolute(plan['root']); fenced(target, root); fenced(target, root / '.local/workbench-archives')
    if target.parent != root / '.local/workbench-archives' or str(target) != plan['archive_directory']:
        raise ValueError('Retirement must use the original direct archive directory')
    review_path = absolute(review_path)
    review = read_json(review_path)
    if (review.get('schema') != 1 or review.get('plan_sha256') != digest(target / 'plan.json')
            or review.get('admission_and_process_identity_verified') is not True):
        raise ValueError('An exact reviewed plan and cutover identity audit are required')
    active_path = root / 'data/active-workbench.json'; active = read_json(active_path)
    if active != review.get('deployed_runtime'):
        raise ValueError('New reviewed backend must be active before retirement')
    runtime = root / 'workbench-releases' / active['release']
    fenced(runtime, root)
    if digest(runtime / 'workbench-release.json') != active.get('manifest_sha256'):
        raise ValueError('Deployed runtime manifest changed')
    runtime_files = read_json(runtime / 'workbench-release.json').get('files', {})
    for relative in ('easel_workbench/runtime/archive_assets.py', 'easel_workbench/runtime/web_assets.py',
                     'easel_workbench/runtime/native_preview.py', 'easel_workbench/runtime/pwa_assets.py'):
        if runtime_files.get(relative) != digest(runtime / relative):
            raise ValueError('Deployed runtime lacks pinned archive support: ' + relative)
    if review.get('static_archive_fallback_verified') is not True:
        raise ValueError('Static archive fallback must be verified in the deployed runtime')
    keys = review.get('entries')
    all_entries = {e['key']: e for e in plan['entries']}
    if not isinstance(keys, list) or not keys or len(keys) != len(set(keys)) or set(keys) - set(all_entries):
        raise ValueError('Review must name an exact unique package list')
    selected = [all_entries[key] for key in keys]
    kept = set(validate_kept_paths(root, [*plan.get('explicit_keep_paths', []), *review.get('keep_paths', []), *keep]))
    roots = {k: absolute(v) for k, v in plan['roots'].items()}
    current_controls = controls(roots)
    obsolete_controls = []
    for control in review.get('retire_candidate_controls', []):
        path = absolute(control['path']); fenced(path, root)
        if (path.parent != root / '.local/workbench-deployment' or 'candidate' not in path.name
                or path.name == 'candidate.json' or path.suffix != '.json'
                or digest(path) != control.get('sha256')):
            raise ValueError('Obsolete candidate control must be an exact reviewed non-primary selector')
        if any(Path(p).name in path.read_text(encoding='utf-8') for p in kept):
            raise ValueError('Candidate control still names a kept version')
        obsolete_controls.append({'path': str(path), 'sha256': control['sha256']})
    if len({c['path'] for c in obsolete_controls}) != len(obsolete_controls):
        raise ValueError('Duplicate obsolete control')
    obsolete_paths = {c['path'] for c in obsolete_controls}
    process_rows = process_inventory() if processes is None else processes
    # The invoking shell may contain the planned paths as literal arguments.
    # Exclude only our verified ancestor chain, never other service processes.
    process_map = {p.get('ProcessId'): p for p in process_rows}
    ancestor_ids = set(); ancestor = os.getpid()
    while ancestor and ancestor not in ancestor_ids:
        ancestor_ids.add(ancestor); ancestor = process_map.get(ancestor, {}).get('ParentProcessId')
    process_rows = [p for p in process_rows if p.get('ProcessId') not in ancestor_ids]
    pending = pending_references(roots, selected)
    if pending:
        (target / 'pending-retirement-holds.json').write_bytes(encoded(pending))
        raise ValueError('Pending/unknown task still references a selected old runtime')
    original_web = root / 'data/active-web.json'
    web = read_json(original_web) if original_web.is_file() else {}
    retire_web = review.get('retire_web_pin')
    if retire_web and ('project/releases/' + str(retire_web.get('release')) not in keys or web != retire_web):
        raise ValueError('Retiring the web pin requires its exact selected package')
    registry_path = fenced(root / '.local/workbench-archives/registry.json', root)
    registry = read_json(registry_path) if registry_path.exists() else {'schema': 1, 'entries': {}, 'static_aliases': {}}
    if registry.get('schema') != 1 or not isinstance(registry.get('entries'), dict):
        raise ValueError('Invalid existing archive registry')
    index = members_by_package(target)
    for entry in selected:
        source = absolute(entry['source']); fenced(source, roots[entry['root_alias']])
        if (entry['folder'] not in VERSION_FOLDERS or not NAME.fullmatch(entry['name'])
                or source != roots[entry['root_alias']] / entry['folder'] / entry['name']
                or entry['key'] != '/'.join((entry['root_alias'], entry['folder'], entry['name']))):
            raise ValueError('Selected source is not an exact version directory')
        if not entry.get('backup_allowed') or str(source) in kept:
            raise ValueError('Selected version is protected/excluded: ' + entry['key'])
        for selector in current_controls:
            if selector['path'] in obsolete_paths:continue
            value = json.dumps(selector['value'])
            if not re.search(r'(?<![A-Za-z0-9_.-])' + re.escape(entry['name']) + r'(?![A-Za-z0-9_.-])', value, re.IGNORECASE):continue
            selector_name = Path(selector['path']).name
            if selector['root_alias'] == 'legacy':
                if str(roots['legacy']) not in review.get('retired_source_roots', []):
                    raise ValueError('Legacy source selectors have not been retired')
                continue
            if not (selector_name.startswith('active') or 'candidate' in selector_name):continue
            if selector_name == 'active-web.json' and retire_web == web and web.get('release') == entry['name']:
                continue
            raise ValueError('Active/candidate selector protects ' + entry['key'])
        for process in process_rows:
            command = (process.get('CommandLine') or '').replace('\\', '/').lower()
            name_hit = re.search(r'(?<![a-z0-9_.-])' + re.escape(entry['name'].lower()) + r'(?![a-z0-9_.-])', command)
            legacy_root_hit = entry['root_alias'] == 'legacy' and str(roots['legacy']).replace('\\', '/').lower() in command and 'archive_workbench_legacy.py' not in command
            if name_hit or legacy_root_hit:
                raise ValueError('Running process protects ' + entry['key'])
        check_members(source, index[entry['key']], REVIEWED_PACKAGE_EXCEPTIONS.get(entry['key']) if entry.get('reviewed_exception_members') else None)
        destination = fenced(target / 'retired' / entry['key'], target)
        if destination.exists() or source.stat().st_dev != target.stat().st_dev:
            raise ValueError('Only new same-volume rename destinations are supported')
        if entry['root_alias'] == 'project' and entry['folder'] in ('releases', 'native-releases'):
            manifest_name = 'release.json' if entry['folder'] == 'releases' else 'native-manifest.json'
            manifest_file = source / manifest_name; manifest = read_json(manifest_file)
            expected = {row['path']: row['sha256'] for row in index[entry['key']]}
            if not isinstance(manifest.get('files'), dict) or any(not safe_member(p) or expected.get(p) != checksum for p, checksum in manifest['files'].items()):
                raise ValueError('Static manifest cannot preserve exact archived members')
            registry_key = entry['folder'] + '/' + entry['name']
            registered = {'path': target.name + '/retired/' + entry['key'], 'manifest': manifest_name,
                          'manifest_sha256': digest(manifest_file)}
            if registry_key in registry['entries'] and registry['entries'][registry_key] != registered:
                raise ValueError('Registry already names a different immutable archive')
            registry['entries'][registry_key] = registered
            if retire_web and entry['folder'] == 'releases' and retire_web.get('release') == entry['name']:
                if registered['manifest_sha256'] != retire_web.get('manifest_sha256'):
                    raise ValueError('Legacy auth aliases must pin the exact old manifest')
                for name in manifest['files']:
                    if name in ('auth-app.js', 'auth-ui.js', 'ui-vendor.js') or name.startswith('icons/'):
                        registry.setdefault('static_aliases', {})['/' + name] = registry_key + '/' + name
    verify_backup(target)
    # Destination registry is published before same-volume renames. Originals
    # remain available until each atomic rename; absent originals then resolve
    # only their pinned static members in the archive. No old HTML is published.
    audit = target / 'retirement'; audit.mkdir(exist_ok=False)
    (audit / 'review.json').write_bytes(encoded(review))
    if registry_path.exists():shutil.copy2(registry_path, audit / 'registry-before.json')
    if retire_web:
        if web != retire_web:raise ValueError('Legacy web selector changed')
        shutil.copy2(original_web, audit / 'active-web-before.json')
    atomic_json(registry_path, registry)
    for control in obsolete_controls:
        source = Path(control['path']); destination = audit / 'obsolete-controls' / source.name
        destination.parent.mkdir(exist_ok=True)
        if digest(source) != control['sha256']:raise ValueError('Candidate selector changed before retirement')
        source.rename(destination)
    atomic_json(audit / 'obsolete-controls.json', obsolete_controls)
    moved = []
    for entry in selected:
        source = absolute(entry['source']); destination = fenced(target / 'retired' / entry['key'], target)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() or source.stat().st_dev != destination.parent.stat().st_dev:
            raise ValueError('Only new same-volume rename destinations are supported')
        source.rename(destination)
        moved.append({'package': entry['key'], 'original': str(source), 'archive': str(destination)})
        atomic_json(audit / 'moves.json', moved)
    if retire_web:
        if read_json(original_web) != retire_web:raise ValueError('Legacy selector changed before retirement')
        atomic_json(original_web, {'schema': 1, 'status': 'retired', 'replacement': '/native/'})
    result = {'passed': True, 'mode': 'retired-by-same-volume-rename', 'moved': moved,
              'databases_modified': False, 'historical_documents_rewritten': False,
              'deployed_runtime': active, 'registry_sha256': digest(registry_path),
              'old_web_selector_retired': bool(retire_web)}
    atomic_json(audit / 'receipt.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--legacy-root', type=Path, default=DEFAULT_LEGACY if DEFAULT_LEGACY.exists() else None)
    parser.add_argument('--archive-id', default='legacy-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    parser.add_argument('--backup', action='store_true', help='Copy immutable version files; never move/delete originals')
    parser.add_argument('--keep', action='append', type=Path, default=[], help='Exact active/verified candidate directory to retain')
    parser.add_argument('--only-entry', action='append', default=[], help='Plan only this exact package key')
    parser.add_argument('--reviewed-exception', action='append', default=[], help='Opt into one of the two exact reviewed historical evidence packages')
    parser.add_argument('--backup-plan', type=Path, help='Backup an already hashed plan directory')
    parser.add_argument('--execute-retirement', type=Path, help='Archive directory with verified ZIP backup and reviewed move list')
    parser.add_argument('--review', type=Path, help='Exact plan SHA, deployed runtime and cutover review JSON')
    parser.add_argument('--verify', type=Path, help='Verify a previous backup without reading business DBs')
    args = parser.parse_args()
    if args.execute_retirement:
        if args.review is None:parser.error('--execute-retirement requires --review')
        result = retire(args.execute_retirement, args.review, keep=args.keep)
    elif args.backup_plan:
        result = backup(read_json(absolute(args.backup_plan) / 'plan.json'))
    elif args.verify:
        result = verify_backup(args.verify)
    else:
        process_rows = [p for p in process_inventory() if 'archive_workbench_legacy.py' not in (p.get('CommandLine') or '')]
        plan = create_plan(args.root, args.legacy_root, args.archive_id, processes=process_rows, keep=args.keep,
                           only=args.only_entry, reviewed_exceptions=args.reviewed_exception)
        result = {'archive_directory': plan['archive_directory'], 'mode': plan['mode'], 'totals': plan['totals'],
                  'retirement_enabled': False}
        if args.backup:
            result['backup'] = backup(plan)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
