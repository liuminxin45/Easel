"""TEMP-only archive proofs; no production DB, process, login or deployment."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import zipfile

import pytest


SPEC = importlib.util.spec_from_file_location('archive_workbench_legacy_test',
    Path(__file__).resolve().parents[1] / 'scripts/archive_workbench_legacy.py')
archive = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(archive)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


def version(root, folder, name, **manifest):
    directory = root / folder / name
    directory.mkdir(parents=True)
    (directory / 'index.html').write_text('TEMP original ' + name, encoding='utf-8')
    write(directory / 'workbench-release.json', manifest)
    return directory


@pytest.fixture
def environment(tmp_path):
    root, legacy = tmp_path / 'project', tmp_path / 'legacy'
    root.mkdir(); legacy.mkdir()
    version(root, 'workbench-releases', 'workbench-active', native={'release': 'native-paired'})
    version(root, 'native-releases', 'native-paired')
    version(root, 'workbench-releases', 'workbench-old')
    version(root, 'workbench-releases', 'workbench-candidate')
    version(legacy, 'backend-releases', 'backend-historical')
    write(root / 'data/active-workbench.json', {'release': 'workbench-active'})
    write(root / '.local/workbench-deployment/candidate.json', {'release': 'workbench-candidate'})
    db = root / 'data/desk.sqlite'
    with sqlite3.connect(db) as connection:
        connection.execute('CREATE TABLE "historical tasks"(id TEXT, document TEXT)')
        connection.execute('INSERT INTO "historical tasks" VALUES(?,?)', ('task-own-id', json.dumps({
            'release': 'backend-historical', 'frozen': 'outputs/_sessions/skill-inputs/exact-own-version/input.md',
            'path': str(legacy / 'data/artifacts/original.png'), 'feedback': 'PRIVATE ORIGINAL FEEDBACK',
            'credential': 'SECRET MUST NOT BE IN AUDIT'})))
    return root, legacy


def entries(plan):
    return {entry['name']: entry for entry in plan['entries']}


def test_default_plan_preserves_selectors_database_tasks_and_frozen_refs(environment):
    root, legacy = environment
    db = root / 'data/desk.sqlite'; before = archive.digest(db)
    plan = archive.create_plan(root, legacy, 'test-plan', processes=[{
        'ProcessId': 42, 'CreationDate': 'precise-created', 'CommandLine': 'python workbench-old/launch.py'}])
    selected = entries(plan)
    assert plan['mode'] == 'dry-run' and not plan['retirement_enabled']
    assert not list(Path(plan['archive_directory']).rglob('*.zip'))
    assert all(not e['retirement_allowed'] for e in selected.values())
    assert any(h['origin'] == 'selector' for h in selected['workbench-active']['holds'])
    assert any(h['origin'] == 'selector' for h in selected['workbench-candidate']['holds'])
    assert any(h['origin'] == 'protected_package_dependency' for h in selected['native-paired']['holds'])
    assert any(h['origin'] == 'process' and h['location']['created'] == 'precise-created'
               for h in selected['workbench-old']['holds'])
    assert any(h['origin'] == 'database' for h in selected['backend-historical']['holds'])
    assert plan['reference_statistics']['frozen_input_references'] == 1
    assert archive.digest(db) == before
    refs = (Path(plan['archive_directory']) / 'references.jsonl').read_text(encoding='utf-8')
    assert 'original.png' in refs
    assert 'SECRET MUST NOT' not in refs and 'PRIVATE ORIGINAL FEEDBACK' not in refs


def test_backup_proves_every_file_and_never_copies_database_or_moves_versions(environment):
    root, legacy = environment
    plan = archive.create_plan(root, legacy, 'test-copy')
    originals = {e['source']: archive.digest(Path(e['source']) / 'index.html') for e in plan['entries']}
    result = archive.backup(plan)
    assert result['passed'] and result['packages'] == len(plan['entries'])
    assert not result['originals_modified'] and not result['databases_copied']
    assert not result['activation_performed']
    for source, checksum in originals.items():
        assert archive.digest(Path(source) / 'index.html') == checksum
    target = Path(plan['archive_directory'])
    inventory = [json.loads(line) for line in (target / 'inventory.jsonl').read_text(encoding='utf-8').splitlines()]
    assert all(not row['path'].endswith('.sqlite') for row in inventory)
    assert archive.verify_backup(target) == result
    for zip_path in target.rglob('*.zip'):
        with zipfile.ZipFile(zip_path) as copied:
            assert copied.read('index.html').startswith(b'TEMP original')


@pytest.mark.parametrize('relative', ['data/desk.sqlite', 'nested/private.SQLITE',
    'outputs/_sessions/skill-inputs/exact/input.md', 'nested/skill-inputs/exact/input.md'])
def test_live_state_inside_version_blocks_entire_backup(environment, relative):
    root, legacy = environment
    path = root / 'workbench-releases/workbench-old' / relative
    path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'LIVE STATE DO NOT COPY')
    plan = archive.create_plan(root, legacy, 'test-protected')
    selected = entries(plan)['workbench-old']
    assert not selected['backup_allowed']
    assert any(h['origin'] == 'prohibited_live_state' for h in selected['holds'])
    archive.backup(plan)
    assert not (Path(plan['archive_directory']) / 'backups/project/workbench-releases/workbench-old.zip').exists()
    assert path.read_bytes() == b'LIVE STATE DO NOT COPY'


def test_changed_source_aborts_without_replacing_or_removing_it(environment):
    root, legacy = environment
    plan = archive.create_plan(root, legacy, 'test-source-change')
    source = root / 'native-releases/native-paired/index.html'
    source.write_text('Changed deliberately after audit', encoding='utf-8')
    with pytest.raises(ValueError, match='Source changed'):
        archive.backup(plan)
    assert source.read_text(encoding='utf-8') == 'Changed deliberately after audit'
    assert not (Path(plan['archive_directory']) / 'backup.json').exists()


def test_corrupted_zip_cannot_pass_restore_byte_proof(environment):
    root, legacy = environment
    plan = archive.create_plan(root, legacy, 'test-corrupt')
    archive.backup(plan)
    zip_path = next(Path(plan['archive_directory']).rglob('*.zip'))
    zip_path.write_bytes(zip_path.read_bytes() + b'tampered')
    with pytest.raises(ValueError, match='ZIP bytes changed'):
        archive.verify_backup(plan['archive_directory'])


def test_missing_package_receipt_cannot_claim_complete_backup(environment):
    root, legacy = environment
    plan = archive.create_plan(root, legacy, 'test-incomplete')
    archive.backup(plan)
    path = Path(plan['archive_directory']) / 'backup.json'
    receipt = archive.read_json(path); receipt['backups'].pop()
    write(path, receipt)
    with pytest.raises(ValueError, match='Incomplete/duplicate'):
        archive.verify_backup(path.parent)


def test_absolute_fence_and_ancestor_link_are_checked_before_writes(environment, monkeypatch):
    root, legacy = environment
    with pytest.raises(ValueError):
        archive.create_plan(Path('relative'), legacy, 'test')
    for name in ('../outside', '/outside', 'CON'):
        with pytest.raises(ValueError):
            archive.create_plan(root, legacy, name)
    original = archive.linked
    monkeypatch.setattr(archive, 'linked', lambda path: Path(path).name == 'pointer' or original(path))
    with pytest.raises(ValueError, match='Links/junctions'):
        archive.fenced(root / 'pointer/outside', root)
    assert not (root / 'pointer').exists()


def test_inventory_reuse_never_overwrites_prior_evidence(environment):
    root, legacy = environment
    plan = archive.create_plan(root, legacy, 'test-unique')
    checksum = archive.digest(Path(plan['archive_directory']) / 'plan.json')
    with pytest.raises(FileExistsError):
        archive.create_plan(root, legacy, 'test-unique')
    assert archive.digest(Path(plan['archive_directory']) / 'plan.json') == checksum


def deployed_review(root, plan, keys, **extra):
    runtime = root / 'workbench-releases/workbench-new'; runtime.mkdir()
    files = {}
    project = Path(__file__).resolve().parents[1]
    for name in ('archive_assets', 'web_assets', 'native_preview', 'pwa_assets'):
        relative = 'easel_workbench/runtime/' + name + '.py'
        path = runtime / relative; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((project / relative).read_bytes()); files[relative] = archive.digest(path)
    write(runtime / 'workbench-release.json', {'files': files})
    selected = {'release': runtime.name, 'manifest_sha256': archive.digest(runtime / 'workbench-release.json')}
    write(root / 'data/active-workbench.json', selected)
    review = {'schema': 1, 'plan_sha256': archive.digest(Path(plan['archive_directory']) / 'plan.json'),
              'admission_and_process_identity_verified': True, 'deployed_runtime': selected,
              'static_archive_fallback_verified': True, 'entries': keys, **extra}
    path = root / 'review.json'; write(path, review)
    return path


def test_exact_keep_does_not_protect_every_newer_unregistered_version(environment):
    root, legacy = environment
    kept = root / 'workbench-releases/workbench-candidate'
    plan = archive.create_plan(root, legacy, 'test-exact-keep', keep=[kept])
    selected = entries(plan)
    assert str(kept) in plan['explicit_keep_paths']
    assert any(h['origin'] == 'explicit_keep' for h in selected['workbench-candidate']['holds'])
    assert not any(h['origin'] == 'newer_unregistered_candidate' for e in selected.values() for h in e['holds'])
    with pytest.raises(ValueError, match='exact existing'):
        archive.validate_kept_paths(root, [root / 'data'])


def test_retirement_moves_only_reviewed_old_version_and_leaves_db_originals(environment):
    root, legacy = environment
    plan = archive.create_plan(root, legacy, 'test-move'); archive.backup(plan)
    key = 'project/workbench-releases/workbench-old'
    review = deployed_review(root, plan, [key])
    before = archive.digest(root / 'data/desk.sqlite')
    result = archive.retire(plan['archive_directory'], review, processes=[])
    moved = Path(plan['archive_directory']) / 'retired' / key
    assert result['passed'] and moved.is_dir()
    assert not (root / 'workbench-releases/workbench-old').exists()
    assert (root / 'workbench-releases/workbench-new').is_dir()
    assert archive.digest(root / 'data/desk.sqlite') == before
    assert archive.read_json(Path(plan['archive_directory']) / 'retirement/moves.json')[0]['package'] == key


@pytest.mark.parametrize('reason', ['process', 'pending', 'candidate', 'keep'])
def test_fresh_in_use_guards_block_move_before_original_mutation(environment, reason):
    root, legacy = environment
    plan = archive.create_plan(root, legacy, 'test-hold'); archive.backup(plan)
    source = root / 'workbench-releases/workbench-old'; key = 'project/workbench-releases/workbench-old'
    review = deployed_review(root, plan, [key]); processes = []; keep = []
    if reason == 'process':
        processes = [{'CommandLine': 'python ' + str(source / 'launch.py'), 'ProcessId': 2, 'CreationDate': 'exact'}]
    elif reason == 'pending':
        with sqlite3.connect(root / 'data/desk.sqlite') as connection:
            connection.execute('CREATE TABLE tasks(status TEXT,output_path TEXT)')
            connection.execute('INSERT INTO tasks VALUES(?,?)', ('unknown', str(source / 'skills/exact.md')))
    elif reason == 'candidate':
        write(root / '.local/workbench-deployment/candidate.json', {'release': source.name})
    else:
        keep = [source]
    with pytest.raises(ValueError):
        archive.retire(plan['archive_directory'], review, keep=keep, processes=processes)
    assert source.is_dir()
    assert not (Path(plan['archive_directory']) / 'retirement').exists()


def test_old_web_pin_is_preserved_then_retired_and_exact_alias_reads_archive(environment):
    from easel_workbench.runtime.archive_assets import archived_alias
    root, legacy = environment
    old = version(root, 'releases', 'toolbox-old')
    (old / 'auth-app.js').write_bytes(b'reviewed auth code')
    write(old / 'release.json', {'files': {'auth-app.js': archive.digest(old / 'auth-app.js'),
                                         'index.html': archive.digest(old / 'index.html')}})
    pin = {'release': 'toolbox-old', 'manifest_sha256': archive.digest(old / 'release.json')}
    write(root / 'data/active-web.json', pin)
    pin_bytes = (root / 'data/active-web.json').read_bytes()
    plan = archive.create_plan(root, legacy, 'test-web-retire'); archive.backup(plan)
    review = deployed_review(root, plan, ['project/releases/toolbox-old'], retire_web_pin=pin)
    archive.retire(plan['archive_directory'], review, processes=[])
    assert (Path(plan['archive_directory']) / 'retirement/active-web-before.json').read_bytes() == pin_bytes
    assert archive.read_json(root / 'data/active-web.json') == {'schema': 1, 'status': 'retired', 'replacement': '/native/'}
    assert archived_alias(root, '/auth-app.js')[0] == b'reviewed auth code'
    assert archived_alias(root, '/index.html') is None


def test_move_requires_deployed_backend_that_contains_pinned_archive_support(environment):
    root, legacy = environment
    plan = archive.create_plan(root, legacy, 'test-not-deployed'); archive.backup(plan)
    review = root / 'review.json'
    write(review, {'schema': 1, 'plan_sha256': archive.digest(Path(plan['archive_directory']) / 'plan.json'),
                   'admission_and_process_identity_verified': True, 'deployed_runtime': {'release': 'not-active'}})
    with pytest.raises(ValueError, match='must be active'):
        archive.retire(plan['archive_directory'], review, processes=[])
    assert (root / 'workbench-releases/workbench-old').is_dir()


def historical_policy(environment, monkeypatch):
    root, legacy = environment
    key = 'legacy/releases/production-queue-20261017-111939'
    directory = version(legacy, 'releases', 'production-queue-20261017-111939')
    snapshot = directory / 'desk-before.sqlite'; snapshot.write_bytes(b'TEMP historical evidence only')
    policy = {'bytes': snapshot.stat().st_size, 'mtime_ns': snapshot.stat().st_mtime_ns, 'sha256': archive.digest(snapshot)}
    monkeypatch.setattr(archive, 'REVIEWED_PACKAGE_EXCEPTIONS', {key: {'desk-before.sqlite': policy}})
    return root, legacy, key, snapshot


def test_only_reviewed_historical_fingerprint_can_copy_snapshot(environment, monkeypatch):
    root, legacy, key, snapshot = historical_policy(environment, monkeypatch)
    before = archive.digest(snapshot)
    plan = archive.create_plan(root, legacy, 'test-history-copy', only=[key], reviewed_exceptions=[key])
    result = archive.backup(plan)
    assert result['historical_database_snapshots_copied'] == 1 and result['databases_copied']
    assert not result['live_databases_copied'] and not result['rollback_performed']
    assert archive.digest(snapshot) == before
    with pytest.raises(ValueError, match='not explicitly allowlisted'):
        archive.create_plan(root, legacy, 'test-any-db', reviewed_exceptions=['legacy/releases/anything'])


@pytest.mark.parametrize('change', ['wal', 'bytes', 'process'])
def test_historical_exception_never_ignores_mutation_wal_or_process(environment, monkeypatch, change):
    root, legacy, key, snapshot = historical_policy(environment, monkeypatch)
    if change == 'wal':Path(str(snapshot) + '-wal').write_bytes(b'active writer')
    if change == 'bytes':snapshot.write_bytes(b'changed historical content')
    processes = [{'ProcessId': 92, 'CreationDate': 'actual', 'CommandLine': 'python ' + str(snapshot)}] if change == 'process' else []
    with pytest.raises(ValueError):
        archive.create_plan(root, legacy, 'test-invalid-history', only=[key],
                            reviewed_exceptions=[key], processes=processes)
    assert snapshot.exists()


@pytest.mark.parametrize('relative', ['.local/workbench-deployment/news-old-candidate.json', 'data/cache-hint-candidate.json'])
def test_obsolete_candidate_control_is_archived_exactly_without_touching_primary(environment, relative):
    root, legacy = environment
    obsolete = root / relative
    write(obsolete, {'release': 'workbench-old'})
    original = obsolete.read_bytes(); primary = root / '.local/workbench-deployment/candidate.json'
    primary_bytes = primary.read_bytes()
    plan = archive.create_plan(root, legacy, 'test-obsolete-control'); archive.backup(plan)
    review = deployed_review(root, plan, ['project/workbench-releases/workbench-old'],
                             retire_candidate_controls=[{'path': str(obsolete), 'sha256': archive.digest(obsolete)}])
    archive.retire(plan['archive_directory'], review, processes=[])
    assert not obsolete.exists() and primary.read_bytes() == primary_bytes
    assert (Path(plan['archive_directory']) / 'retirement/obsolete-controls' / obsolete.name).read_bytes() == original


@pytest.mark.parametrize('relative', ['.local/workbench-deployment/candidate.json', 'data/candidate.json',
                                      'data/active-native-candidate.json', 'data/active-native.json'])
def test_primary_or_active_selector_cannot_be_retired_as_obsolete(environment, relative):
    root, legacy = environment
    plan = archive.create_plan(root, legacy, 'test-primary-control'); archive.backup(plan)
    primary = root / relative
    if not primary.exists():write(primary, {'release': 'workbench-old'})
    review = deployed_review(root, plan, ['project/workbench-releases/workbench-old'],
                             retire_candidate_controls=[{'path': str(primary), 'sha256': archive.digest(primary)}])
    with pytest.raises(ValueError, match='non-primary'):
        archive.retire(plan['archive_directory'], review, processes=[])
    assert primary.is_file() and (root / 'workbench-releases/workbench-old').is_dir()
