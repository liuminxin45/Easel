"""Read-only source relocation for original historical SQL/AST audit functions.

Bindings name exact retirement receipts; no directory search, source import,
business execution, evidence rewrite or unknown-status exception is performed.
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import threading

_LOCK = threading.RLock()
_META = ('plan.json', 'inventory.jsonl', 'backup.json', 'retirement/review.json', 'retirement/receipt.json')
_FOLDERS = ('releases', 'native-releases', 'backend-releases', 'workbench-releases')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def fenced(base, relative):
    parts = Path(relative).parts
    if Path(relative).is_absolute() or not parts or any(p in ('.', '..') or ':' in p for p in parts):
        raise ValueError('Invalid historical evidence member')
    path = Path(base)
    for part in parts:
        path /= part
        if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
            raise ValueError('Historical evidence links are forbidden')
    if not path.resolve().is_relative_to(Path(base).resolve()):raise ValueError('Historical evidence escapes root')
    return path


def bind_retirements(root, archive_ids):
    """Create a new local binding from explicitly supplied completed retirements."""
    root = Path(root).resolve(); rows = []
    for name in archive_ids:
        directory = fenced(root, '.local/workbench-archives/' + name)
        receipt = read(directory / 'retirement/receipt.json')
        if receipt.get('passed') is not True or receipt.get('mode') != 'retired-by-same-volume-rename':
            raise ValueError('Retirement was not completed')
        rows.append({'archive_id': name, 'metadata': {name: sha(directory / name) for name in _META}})
    value = {'schema': 1, 'archives': rows}
    path = fenced(root, '.local/workbench-archives/historical-source-bindings.json')
    with path.open('xb') as stream:stream.write(json.dumps(value, sort_keys=True).encode('utf-8'))
    return path


class ArchivedEvidence:
    def __init__(self, root, legacy):
        self.root, self.legacy = Path(root).resolve(), Path(legacy).resolve()
        self.records = None

    def _load(self):
        value = read(fenced(self.root, '.local/workbench-archives/historical-source-bindings.json'))
        if value.get('schema') != 1:raise ValueError('Unknown historical archive binding')
        records = []
        for binding in value['archives']:
            directory = fenced(self.root, '.local/workbench-archives/' + binding['archive_id'])
            if set(binding.get('metadata', {})) != set(_META):raise ValueError('Incomplete retirement binding')
            for name in _META:
                if sha(fenced(directory, name)) != binding['metadata'][name]:raise ValueError('Retirement metadata changed')
            plan, backup = read(directory / 'plan.json'), read(directory / 'backup.json')
            review, receipt = read(directory / 'retirement/review.json'), read(directory / 'retirement/receipt.json')
            if (receipt.get('passed') is not True or receipt.get('mode') != 'retired-by-same-volume-rename'
                    or receipt.get('databases_modified') is not False or receipt.get('historical_documents_rewritten') is not False
                    or review.get('plan_sha256') != binding['metadata']['plan.json']
                    or backup.get('plan_sha256') != binding['metadata']['plan.json']
                    or backup.get('inventory_sha256') != binding['metadata']['inventory.jsonl']
                    or plan.get('inventory_sha256') != binding['metadata']['inventory.jsonl']):
                raise ValueError('Retirement receipt/index binding changed')
            index = {}
            with (directory / 'inventory.jsonl').open(encoding='utf-8') as stream:
                for line in stream:
                    row = json.loads(line)
                    if 'sha256' in row:index.setdefault(row['package'], {})[row['path']] = row['sha256']
            entries = {e['key']: e for e in plan['entries']}
            for moved in receipt['moved']:
                key = moved['package']; entry = entries[key]
                owner = self.root if entry['root_alias'] == 'project' else self.legacy
                if (entry['folder'] not in _FOLDERS or Path(plan['roots'][entry['root_alias']]).resolve() != owner
                        or Path(entry['source']) != owner / entry['folder'] / entry['name']
                        or moved['original'] != entry['source']):raise ValueError('Retirement source identity changed')
                target = fenced(directory, 'retired/' + key)
                if Path(moved['archive']) != target:raise ValueError('Retirement target identity changed')
                records.append((Path(entry['source']), target, index[key]))
        self.records = records

    def resolve(self, path):
        path = Path(path)
        if not path.is_absolute():raise ValueError('Historical reads must use absolute paths')
        owner = next((p for p in (self.root, self.legacy) if path.is_relative_to(p)), None)
        if owner is None:raise ValueError('Historical read outside configured source roots')
        original = fenced(owner, path.relative_to(owner))
        relative = original.relative_to(owner).parts
        if original.exists():return original
        if len(relative) < 3 or relative[0] not in _FOLDERS:raise FileNotFoundError(original)
        if owner == self.root:
            for selector in (self.root / 'data').glob('active*.json'):
                selected = read(selector)
                if selected.get('release') == relative[1]:raise ValueError('Current active version cannot use archive fallback')
        if self.records is None:self._load()
        matches = [(source, target, index) for source, target, index in self.records if original.is_relative_to(source)]
        if len(matches) != 1:raise ValueError('Historical source has no unique retired origin')
        source, target, index = matches[0]; member = original.relative_to(source).as_posix()
        actual = fenced(target, member); expected = index.get(member)
        if expected is None or sha(actual) != expected:raise ValueError('Archived historical member changed')
        manifests = [name for name in ('backend-release.json', 'workbench-release.json', 'release.json', 'native-manifest.json') if name in index]
        if not manifests:raise ValueError('Historical package has no indexed manifest')
        manifest_name = manifests[0]; manifest_path = fenced(target, manifest_name)
        if sha(manifest_path) != index[manifest_name]:raise ValueError('Historical package manifest changed')
        if member != manifest_name and read(manifest_path).get('files', {}).get(member) != expected:
            raise ValueError('Historical source is not the original manifest member')
        return actual


@contextmanager
def archived_reads(root, legacy, *modules):
    """Temporarily adapt only read APIs; always restore exact original objects."""
    with _LOCK:
        resolver = ArchivedEvidence(root, legacy); saved = []
        try:
            seen = set()
            for module in modules:
                if id(module) in seen:continue
                seen.add(id(module))
                for name in ('digest', 'read', 'source_system'):
                    original = getattr(module, name, None)
                    if not callable(original):continue
                    saved.append((module, name, original))
                    def redirected(path, *args, _original=original, **kwargs):
                        return _original(resolver.resolve(path), *args, **kwargs)
                    setattr(module, name, redirected)
            yield resolver
        finally:
            for module, name, original in reversed(saved):setattr(module, name, original)
