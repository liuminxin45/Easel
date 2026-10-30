"""Explicit, manifest-pinned legacy static files; never an archived UI entry."""
import hashlib
import json
from pathlib import Path
import re

MIMES = {'.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
         '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif',
         '.webp': 'image/webp', '.svg': 'image/svg+xml', '.ico': 'image/x-icon',
         '.woff': 'font/woff', '.woff2': 'font/woff2', '.ttf': 'font/ttf', '.otf': 'font/otf'}
ALIASES = {'/auth-app.js', '/auth-ui.js', '/ui-vendor.js', '/icons/app.svg', '/icons/icon-192.png',
           '/icons/icon-512.png', '/icons/maskable-512.png', '/icons/apple-touch-icon.png'}


def _link(path):
    return path.is_symlink() or getattr(path, 'is_junction', lambda: False)()


def _parts(value):
    if not isinstance(value, str) or '\\' in value or ':' in value:
        raise FileNotFoundError()
    parts = value.split('/')
    reserved = {'CON', 'PRN', 'AUX', 'NUL', *[f'{prefix}{n}' for prefix in ('COM', 'LPT') for n in range(1, 10)]}
    if any(not part or part in ('.', '..') or part.rstrip(' .') != part
           or part.split('.')[0].upper() in reserved for part in parts):
        raise FileNotFoundError()
    return parts


def _fenced(root, relative):
    root = Path(root).resolve()
    path = root
    for part in _parts(relative):
        path /= part
        if _link(path):
            raise RuntimeError('Archived static path is a link')
    if not path.resolve().is_relative_to(root):
        raise RuntimeError('Archived static path leaves its root')
    return path


def _registry(project):
    path = _fenced(project, '.local/workbench-archives/registry.json')
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema') != 1 or not isinstance(data.get('entries'), dict):
        raise RuntimeError('Invalid archive registry')
    return data


def _asset(project, registry, kind, release, member):
    if kind not in ('releases', 'native-releases') or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,100}', release):
        raise FileNotFoundError()
    _parts(member)
    basename = Path(member).name.lower()
    mime = MIMES.get(Path(member).suffix.lower())
    if not mime or basename in ('sw.js', 'service-worker.js', 'toolbox-boot.js'):
        raise FileNotFoundError()
    key = kind + '/' + release
    entry = registry['entries'].get(key)
    if entry is None:
        return None
    if not isinstance(entry, dict):
        raise RuntimeError('Invalid archived static entry')
    expected_manifest = 'release.json' if kind == 'releases' else 'native-manifest.json'
    relative = entry.get('path')
    parts = _parts(relative)
    if len(parts) != 5 or parts[1:] != ['retired', 'project', kind, release] or entry.get('manifest') != expected_manifest:
        raise RuntimeError('Archive registry selects an unexpected version path')
    checksum = entry.get('manifest_sha256')
    if not isinstance(checksum, str) or not re.fullmatch(r'[a-f0-9]{64}', checksum):
        raise RuntimeError('Archive manifest is not pinned')
    base = '.local/workbench-archives/' + relative
    manifest_path = _fenced(project, base + '/' + expected_manifest)
    raw = manifest_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != checksum:
        raise RuntimeError('Archive manifest integrity mismatch')
    manifest = json.loads(raw)
    member_sha = manifest.get('files', {}).get(member)
    if not isinstance(member_sha, str) or not re.fullmatch(r'[a-f0-9]{64}', member_sha):
        raise FileNotFoundError()
    body = _fenced(project, base + '/' + member).read_bytes()
    if hashlib.sha256(body).hexdigest() != member_sha:
        raise RuntimeError('Archived static member integrity mismatch')
    return body, mime


def archived_asset(project, kind, release, member):
    registry = _registry(project)
    return None if registry is None else _asset(project, registry, kind, release, member)


def archived_alias(project, path):
    """Fixed legacy auth/icon aliases only; no old boot, SW, HTML or manifest."""
    if path not in ALIASES:
        return None
    registry = _registry(project)
    if registry is None:
        return None
    aliases = registry.get('static_aliases', {})
    if not isinstance(aliases, dict):
        raise RuntimeError('Invalid archive aliases')
    selected = aliases.get(path)
    if selected is None:
        return None
    parts = _parts(selected)
    if len(parts) < 3 or '/'.join(parts[2:]) != path.lstrip('/'):
        raise RuntimeError('Archive alias does not name its exact static file')
    return _asset(project, registry, parts[0], parts[1], '/'.join(parts[2:]))
