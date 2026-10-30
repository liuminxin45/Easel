"""TEMP-only source relocation, integrity failures and scoped reader restoration."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location('archived_evidence_test', Path(__file__).resolve().parents[1] / 'scripts/archived_evidence.py')
audit = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(audit)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value), encoding='utf-8')


def fixture(tmp_path, alias='legacy'):
    root, legacy = tmp_path / 'project', tmp_path / 'legacy'; root.mkdir(); legacy.mkdir()
    package = alias + '/backend-releases/backend-history'
    original = (legacy if alias == 'legacy' else root) / 'backend-releases/backend-history'
    directory = root / '.local/workbench-archives/reviewed'; target = directory / 'retired' / package
    target.mkdir(parents=True)
    source = target / 'collection_sources.py'
    source.write_text('SYSTEM="exact frozen system"\nraise RuntimeError("MUST NEVER EXECUTE")\n', encoding='utf-8')
    write(target / 'backend-release.json', {'files': {'collection_sources.py': audit.sha(source)}})
    index = directory / 'inventory.jsonl'
    index.write_text('\n'.join(json.dumps({'package': package, 'path': name, 'sha256': audit.sha(target / name)}) for name in ('collection_sources.py', 'backend-release.json')) + '\n', encoding='utf-8')
    write(directory / 'plan.json', {'roots': {'project': str(root), 'legacy': str(legacy)},
        'inventory_sha256': audit.sha(index), 'entries': [{'key': package, 'root_alias': alias,
          'folder': 'backend-releases', 'name': 'backend-history', 'source': str(original)}]})
    plan_sha = audit.sha(directory / 'plan.json')
    write(directory / 'backup.json', {'plan_sha256': plan_sha, 'inventory_sha256': audit.sha(index)})
    write(directory / 'retirement/review.json', {'plan_sha256': plan_sha})
    write(directory / 'retirement/receipt.json', {'passed': True, 'mode': 'retired-by-same-volume-rename',
        'databases_modified': False, 'historical_documents_rewritten': False,
        'moved': [{'package': package, 'original': str(original), 'archive': str(target)}]})
    audit.bind_retirements(root, ['reviewed'])
    return root, legacy, directory, original, source


def system(path):
    tree = ast.parse(Path(path).read_text(encoding='utf-8'))
    return ast.literal_eval(tree.body[0].value)


def test_original_digest_and_ast_reader_use_exact_retired_bytes_without_execution(tmp_path):
    root, legacy, directory, original, source = fixture(tmp_path)
    module = SimpleNamespace(digest=audit.sha, source_system=system)
    old_digest, old_system = module.digest, module.source_system
    with audit.archived_reads(root, legacy, module):
        assert module.digest(original / source.name) == audit.sha(source)
        assert module.source_system(original / source.name) == 'exact frozen system'
    assert module.digest is old_digest and module.source_system is old_system
    assert not original.exists()


@pytest.mark.parametrize('tamper', ['source', 'manifest', 'receipt', 'inventory'])
def test_integrity_failure_restores_readers_and_fails_closed(tmp_path, tamper):
    root, legacy, directory, original, source = fixture(tmp_path)
    path = {'source': source, 'manifest': source.parent / 'backend-release.json',
            'receipt': directory / 'retirement/receipt.json', 'inventory': directory / 'inventory.jsonl'}[tamper]
    path.write_bytes(path.read_bytes() + b'changed')
    module = SimpleNamespace(digest=audit.sha, source_system=system)
    original_digest = module.digest
    with pytest.raises((ValueError, json.JSONDecodeError)):
        with audit.archived_reads(root, legacy, module):module.digest(original / source.name)
    assert module.digest is original_digest and module.source_system is system


def test_caller_failure_restores_all_aliases_and_missing_data_never_falls_back(tmp_path):
    root, legacy, directory, original, source = fixture(tmp_path)
    first = SimpleNamespace(digest=audit.sha); second = SimpleNamespace(digest=audit.sha, source_system=system)
    with pytest.raises(RuntimeError, match='unknown gate unchanged'):
        with audit.archived_reads(root, legacy, first, second):
            assert first.digest(original / source.name) == second.digest(original / source.name)
            raise RuntimeError('unknown gate unchanged')
    assert first.digest is audit.sha and second.digest is audit.sha and second.source_system is system
    with pytest.raises(FileNotFoundError):audit.ArchivedEvidence(root, legacy).resolve(legacy / 'data/cache/missing.json')


def test_current_active_package_cannot_be_forged_as_historical_archive(tmp_path):
    root, legacy, directory, original, source = fixture(tmp_path, 'project')
    write(root / 'data/active-workbench.json', {'release': 'backend-history'})
    with pytest.raises(ValueError, match='Current active'):
        audit.ArchivedEvidence(root, legacy).resolve(original / source.name)
    with pytest.raises(ValueError, match='outside'):
        audit.ArchivedEvidence(root, legacy).resolve(tmp_path / 'outside.py')
