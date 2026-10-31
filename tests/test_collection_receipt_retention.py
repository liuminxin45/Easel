"""TEMP-only retention proofs and the real deployment/inference boundaries.

No provider, credential, native CLI or production data is read. Only unrelated
legacy-project loading and host process enumeration are replaced by fixtures.
"""
from contextlib import nullcontext
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
from types import SimpleNamespace

import pytest

PROJECT = Path(__file__).resolve().parents[1]
POLICIES = ('easel_workbench/runtime/collection_model.py',
            'easel_workbench/runtime/readonly_codex.py')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def receipt(tmp_path_factory, monkeypatch):
    monkeypatch.syspath_prepend(str(PROJECT / 'scripts'))
    import collection_receipt_retention as retention

    root = tmp_path_factory.mktemp('receipt') / 'p'
    root.mkdir()
    now = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)).isoformat()
    cfg = {'enabled': True, 'backend': 'codex_subscription', 'model': 'fixture-model',
           'reasoning_effort': 'low'}
    schema = {'type': 'object', 'additionalProperties': False,
              'required': ['ok'], 'properties': {'ok': {'type': 'boolean'}}}
    system = 'Exact original collection contract'
    trusted = 'Frozen approved skill prompt'
    wrapped_system = trusted + '\n\n## 本次受信执行合同\n' + system
    payload = {'news': [{'id': 'fixture-source', 'title': 'Original input'}]}
    original = {'system': wrapped_system, 'payload': payload, 'schema': schema}
    semantic = {key: cfg.get(key) for key in
                ('backend', 'model', 'base_url', 'reasoning_effort', 'max_tokens', 'json_mode')}
    fingerprint = hashlib.sha256(packed({**original, 'model': semantic}).encode()).hexdigest()
    directory = root / 'data/collection/model-attempts' / fingerprint / ('a' * 32)
    binding = {'input_sha256': fingerprint, 'backend': 'codex_subscription',
               'wrapped': False, 'creator_snapshot_sha256': 'b' * 64,
               'skills': [{'id': 'fixture-skill', 'version': 1}]}
    write(directory / 'request-binding.json', binding)
    write(directory / 'schema.json', schema)
    cache = root / 'data/collection/model-cache' / (fingerprint + '.json')
    write(cache, {'status': 'uncertain', 'input_sha256': fingerprint,
                  'error_type': 'ModelError', 'finished_at': now,
                  'request_dir': directory.relative_to(root / 'data/collection').as_posix()})
    write(root / 'data/collection-model.json', cfg)
    ledger = {'schema_version': 1, 'id': 'fixture-call', 'task_id': None,
              'task': 'news_enhancement', 'status': 'unknown', 'error': 'ModelError',
              'finished_at': now, 'input': original, 'prompt': wrapped_system,
              'input_sha256': 'c' * 64,
              'snapshot': {'snapshot_sha256': 'b' * 64, 'prompt_text': trusted,
                           'skills': binding['skills']}}
    database = root / 'data/desk.sqlite'
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE creator_model_calls(id TEXT PRIMARY KEY,task_id TEXT,document TEXT NOT NULL,updated_at TEXT NOT NULL)')
        connection.execute('INSERT INTO creator_model_calls VALUES(?,?,?,?)',
                           (ledger['id'], None, packed(ledger), now))
    package = root / 'workbench-releases/workbench-fixture'
    files = {}
    for name in POLICIES:
        source = PROJECT / name
        # Build the exact reviewed LF artifact even when a fresh Windows Git
        # checkout converts working files to CRLF. Production still validates
        # raw source/frozen bytes; the fixture does not relax that boundary.
        reviewed = source.read_bytes().replace(b'\r\n', b'\n')
        assert hashlib.sha256(reviewed).hexdigest() == retention.POLICY_SOURCES[name]
        for base in (root, package):
            target = base / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(reviewed)
        files[name] = hashlib.sha256(reviewed).hexdigest()
    manifest = {'schema': 1, 'release': 'workbench-fixture',
                'architecture': 'easel-workbench-extension', 'files': files}
    write(package / 'workbench-release.json', manifest)
    active = {'release': manifest['release'], 'manifest_sha256': sha(package / 'workbench-release.json')}
    write(root / 'data/active-workbench.json', active)
    write(root / 'data/migration-owner.json', {'target_root': str(root), **active})
    inventory = {}
    monkeypatch.setattr(retention, 'process_inventory', lambda: inventory)
    idle = load('receipt_idle_fixture', PROJECT / 'scripts/activate_workbench.py')
    old = root.parent / 'old'
    historical = old / 'evidence/simplify-workbench-20261029'
    write(historical / 'audit.json', {})
    ref = {'path': 'evidence/simplify-workbench-20261029/audit.json',
           'sha256': sha(historical / 'audit.json')}
    write(historical / 'activation-evidence.json',
          {'historical_unknown_audit': ref, 'collection_historical_unknown_audit': ref})
    monkeypatch.setattr(idle, 'ROOT', root)
    monkeypatch.setattr(idle, 'STATE', root / '.local/workbench-deployment')
    monkeypatch.setattr(idle, 'OLD', old)
    base = SimpleNamespace(exists_table=lambda c, table: c.execute(
        'SELECT 1 FROM sqlite_master WHERE type=\'table\' AND name=?', (table,)).fetchone() is not None)
    legacy = SimpleNamespace(busy_state=lambda *_: {'busy': False, 'retained_collection_unknown': []})
    monkeypatch.setattr(idle, 'legacy', lambda: (base, legacy))
    monkeypatch.setattr(idle, 'archived_reads', lambda *_: nullcontext())
    return SimpleNamespace(root=root, retention=retention, idle=idle, database=database,
                           fingerprint=fingerprint, directory=directory, cache=cache,
                           binding=binding, ledger=ledger, cfg=cfg, schema=schema,
                           system=system, trusted=trusted, payload=payload,
                           package=package, manifest=manifest, inventory=inventory)


def preserve(fixture):
    return fixture.retention.retain(fixture.root, fixture.fingerprint, apply=True,
                                    expected_cache_sha256=sha(fixture.cache), inventory={})


def audit_path(fixture):
    return fixture.root / '.local/workbench-deployment/collection-retentions' / (fixture.fingerprint + '.json')


def ledger_bytes(fixture):
    with sqlite3.connect(fixture.database) as connection:
        return connection.execute('SELECT id,task_id,document,updated_at FROM creator_model_calls ORDER BY id').fetchall()


def test_unaudited_unknown_still_blocks_the_real_deployment_seam(receipt):
    f = receipt
    assert f.retention.retained(f.root, f.fingerprint, f.cache, inventory={}) is None
    result = f.idle.idle(f.database)
    assert result['busy'] is True
    assert result['additional'] == [{'table': 'collection_model_receipt', 'id': f.fingerprint, 'status': 'uncertain'}]


def test_exact_audit_retains_one_closed_unknown_without_changing_cache_or_ledger(receipt):
    f = receipt
    before_cache, before_ledger = f.cache.read_bytes(), ledger_bytes(f)
    rehearsal = f.retention.retain(f.root, f.fingerprint, inventory={})
    assert rehearsal['passed'] and not rehearsal['applied'] and not audit_path(f).exists()
    result = preserve(f)
    assert result['passed'] and result['applied'] and not result['already_retained']
    original_audit = audit_path(f).read_bytes()
    proof = f.retention.retained(f.root, f.fingerprint, f.cache, inventory={})
    assert proof['fingerprint'] == f.fingerprint
    assert proof['cache']['status'] == 'uncertain' and proof['ledger']['status'] == 'unknown'
    assert f.idle.idle(f.database)['busy'] is False
    assert preserve(f)['already_retained'] is True
    assert f.cache.read_bytes() == before_cache and ledger_bytes(f) == before_ledger
    assert audit_path(f).read_bytes() == original_audit


def test_another_unknown_is_never_covered_by_the_exact_audit(receipt):
    f = receipt
    preserve(f)
    other = 'd' * 64
    write(f.cache.parent / (other + '.json'), {'status': 'uncertain', 'input_sha256': other})
    result = f.idle.idle(f.database)
    assert result['busy'] is True
    assert result['additional'] == [{'table': 'collection_model_receipt', 'id': other, 'status': 'uncertain'}]


@pytest.mark.parametrize('member', ['cache', 'request-binding.json', 'schema.json', 'ledger_document', 'ledger_updated_at'])
def test_any_audited_original_byte_or_ledger_row_change_fails_closed(receipt, member):
    f = receipt
    preserve(f)
    if member in ('cache', 'request-binding.json', 'schema.json'):
        path = f.cache if member == 'cache' else f.directory / member
        path.write_bytes(path.read_bytes() + b'\n')
    else:
        with sqlite3.connect(f.database) as connection:
            if member == 'ledger_document':
                connection.execute("UPDATE creator_model_calls SET document=document||' '")
            else:
                connection.execute("UPDATE creator_model_calls SET updated_at=updated_at||' changed'")
    with pytest.raises(ValueError):
        f.retention.retained(f.root, f.fingerprint, f.cache, inventory={})
    with pytest.raises(ValueError):
        f.idle.idle(f.database)


@pytest.mark.parametrize('member,value', [('schema_version', 2), ('kind', 'completed'), ('fingerprint', 'e' * 64)])
def test_changed_audit_schema_or_identity_is_rejected(receipt, member, value):
    f = receipt
    preserve(f)
    path = audit_path(f)
    document = json.loads(path.read_text(encoding='utf-8'))
    document[member] = value
    write(path, document)
    with pytest.raises(ValueError):
        f.retention.retained(f.root, f.fingerprint, f.cache, inventory={})


@pytest.mark.parametrize('name', ['answer.json', 'model-result.json', 'tool-output.txt'])
def test_a_possible_result_or_tool_artifact_cannot_be_retained(receipt, name):
    f = receipt
    preserve(f)
    write(f.directory / name, {'ok': True})
    with pytest.raises(ValueError):
        f.retention.inspect_receipt(f.root, f.fingerprint, inventory={})
    with pytest.raises(ValueError):
        f.idle.idle(f.database)


@pytest.mark.parametrize('mutation', ['ephemeral', 'read-only', 'shell_tool'])
def test_non_ephemeral_writable_or_tool_enabled_policy_cannot_gain_audit(receipt, mutation):
    f = receipt
    relative = POLICIES[1]
    source = f.root / relative
    content = source.read_text(encoding='utf-8')
    if mutation == 'ephemeral':
        changed = content.replace("'--ephemeral',", '')
    elif mutation == 'read-only':
        changed = content.replace("'read-only'", "'workspace-write'")
    else:
        changed = content.replace("'shell_tool',", '')
    assert changed != content
    for base in (f.root, f.package):
        (base / relative).write_text(changed, encoding='utf-8')
    manifest = json.loads((f.package / 'workbench-release.json').read_text(encoding='utf-8'))
    manifest['files'][relative] = sha(source)
    write(f.package / 'workbench-release.json', manifest)
    write(f.root / 'data/active-workbench.json', {'release': manifest['release'], 'manifest_sha256': sha(f.package / 'workbench-release.json')})
    with pytest.raises(ValueError):
        f.retention.retain(f.root, f.fingerprint, apply=True,
                           expected_cache_sha256=sha(f.cache), inventory={})
    assert not audit_path(f).exists()


@pytest.mark.parametrize('identity', ['fingerprint', 'directory', 'missing_arguments'])
def test_live_or_unverifiable_collection_process_refuses_retention(receipt, identity):
    f = receipt
    preserve(f)
    marker = f.fingerprint if identity == 'fingerprint' else str(f.directory)
    command = None if identity == 'missing_arguments' else 'codex.exe exec --cd "' + marker + '"'
    f.inventory[123456789] = {'pid': 123456789, 'name': 'codex.exe', 'command': command}
    with pytest.raises(ValueError):
        f.retention.retained(f.root, f.fingerprint, f.cache, inventory=f.inventory)
    with pytest.raises(ValueError):
        f.idle.idle(f.database)


@pytest.mark.parametrize('member,value', [('request_dir', '../outside'), ('request_dir', 'model-attempts/../../outside'), ('input_sha256', 'f' * 64)])
def test_path_escape_or_different_fingerprint_is_rejected_before_review(receipt, member, value):
    f = receipt
    document = json.loads(f.cache.read_text(encoding='utf-8'))
    document[member] = value
    write(f.cache, document)
    with pytest.raises(ValueError):
        f.retention.inspect_receipt(f.root, f.fingerprint, inventory={})


@pytest.mark.parametrize('mutation', ['input_hash', 'snapshot', 'backend', 'wrapped', 'schema'])
def test_initial_request_binding_must_agree_with_original_ledger_schema(receipt, mutation):
    f = receipt
    binding = dict(f.binding)
    if mutation == 'input_hash': binding['input_sha256'] = 'f' * 64
    elif mutation == 'snapshot': binding['creator_snapshot_sha256'] = 'f' * 64
    elif mutation == 'backend': binding['backend'] = 'openai_compatible'
    elif mutation == 'wrapped': binding['wrapped'] = True
    else: write(f.directory / 'schema.json', {'type': 'object', 'properties': {'different': {'type': 'number'}}})
    write(f.directory / 'request-binding.json', binding)
    with pytest.raises(ValueError):
        f.retention.inspect_receipt(f.root, f.fingerprint, inventory={})


def test_a_new_runtime_with_identical_reviewed_policy_keeps_only_the_same_receipt(receipt):
    f = receipt
    preserve(f)
    destination = f.root / 'workbench-releases/workbench-next'
    shutil.copytree(f.package, destination)
    manifest = json.loads((destination / 'workbench-release.json').read_text(encoding='utf-8'))
    manifest['release'] = 'workbench-next'
    write(destination / 'workbench-release.json', manifest)
    write(f.root / 'data/active-workbench.json', {'release': manifest['release'], 'manifest_sha256': sha(destination / 'workbench-release.json')})
    assert f.retention.retained(f.root, f.fingerprint, f.cache, inventory={})['observed_active_runtime']['release'] == 'workbench-next'
    assert f.idle.idle(f.database)['busy'] is False


def test_same_fingerprint_stays_blocked_in_real_invoke_after_retention(receipt, monkeypatch):
    from easel_workbench.runtime import collection_model, task_runtime
    f = receipt
    preserve(f)
    before_cache, before_ledger = f.cache.read_bytes(), ledger_bytes(f)
    named = []
    def prompt(*args, **kwargs):
        named.append(args)
        return '', {'snapshot_sha256': 'b' * 64, 'prompt_text': f.trusted,
                    'skills': [{'id': 'fixture-skill', 'version': 1}]}
    monkeypatch.setattr(task_runtime, 'named_prompt', prompt)
    transports = []
    def transport(*args, **kwargs):
        transports.append((args, kwargs))
        raise AssertionError('Unknown original must never reach any transport')
    with pytest.raises(collection_model.ModelError, match='同一模型请求的回执仍待核对'):
        collection_model.invoke(f.system, f.payload, f.root / 'consumer', root=f.root,
                                config=f.cfg, transport=transport, schema=f.schema)
    assert len(named) == 1 and transports == []
    assert f.cache.read_bytes() == before_cache and ledger_bytes(f) == before_ledger
    assert not (f.root / 'consumer/model-result.json').exists()


def test_apply_requires_exact_previously_reviewed_cache_sha(receipt):
    f = receipt
    with pytest.raises(ValueError):
        f.retention.retain(f.root, f.fingerprint, apply=True, inventory={})
    with pytest.raises(ValueError):
        f.retention.retain(f.root, f.fingerprint, apply=True,
                           expected_cache_sha256='0' * 64, inventory={})
    assert not audit_path(f).exists()


def test_original_none_schema_uses_the_exact_json_string_wrapper_contract(receipt):
    f = receipt
    ledger = dict(f.ledger)
    ledger['input'] = {**ledger['input'], 'schema': None}
    semantic = {key: f.cfg.get(key) for key in
                ('backend', 'model', 'base_url', 'reasoning_effort', 'max_tokens', 'json_mode')}
    fingerprint = hashlib.sha256(packed({**ledger['input'], 'model': semantic}).encode()).hexdigest()
    directory = f.root / 'data/collection/model-attempts' / fingerprint / ('a' * 32)
    write(directory / 'request-binding.json',
          {**f.binding, 'input_sha256': fingerprint, 'wrapped': True})
    write(directory / 'schema.json', {'type': 'object', 'additionalProperties': False,
          'required': ['json'], 'properties': {'json': {'type': 'string'}}})
    cache = f.cache.parent / (fingerprint + '.json')
    write(cache, {**json.loads(f.cache.read_text(encoding='utf-8')),
                 'input_sha256': fingerprint,
                 'request_dir': directory.relative_to(f.root / 'data/collection').as_posix()})
    with sqlite3.connect(f.database) as connection:
        connection.execute('UPDATE creator_model_calls SET document=?', (packed(ledger),))
    f.fingerprint, f.directory, f.cache = fingerprint, directory, cache
    assert preserve(f)['passed']
    assert f.retention.retained(f.root, f.fingerprint, f.cache, inventory={})['cache']['status'] == 'uncertain'


def test_invalid_existing_audit_is_never_overwritten_or_repaired_by_apply(receipt):
    f = receipt
    path = audit_path(f)
    path.parent.mkdir(parents=True)
    original = b'{"schema_version":'
    path.write_bytes(original)
    before_cache, before_ledger = f.cache.read_bytes(), ledger_bytes(f)
    with pytest.raises(ValueError):
        preserve(f)
    assert path.read_bytes() == original
    assert f.cache.read_bytes() == before_cache and ledger_bytes(f) == before_ledger
