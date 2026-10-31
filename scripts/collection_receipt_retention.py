"""Review a closed, tool-disabled collection call without resolving or replaying it.

The receipt and ledger remain unknown. Only an exact, immutable local audit may
retain this nonrunning request during deployment; changed evidence fails closed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
KIND = 'retained_nonrunning_readonly_ephemeral_unknown'
POLICY_SOURCES = {
    'easel_workbench/runtime/collection_model.py': '6fadc654c166709c1dc538425cf7c9022638d39a890871b0245053933140c582',
    'easel_workbench/runtime/readonly_codex.py': '970f9191b9f3619c7eff653fa57aa893fa1d27d48afd98cb6c1d6953a154a36e',
}
DISABLED = ('shell_tool', 'unified_exec', 'apps', 'plugins', 'hooks', 'browser_use',
            'browser_use_external', 'computer_use', 'image_generation', 'multi_agent',
            'code_mode_host', 'skill_search', 'memories')
SEMANTIC = ('backend', 'model', 'base_url', 'reasoning_effort', 'max_tokens', 'json_mode')
WRAPPED_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['json'],
                  'properties': {'json': {'type': 'string'}}}


def _sha(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        raise ValueError('Cannot hash retention evidence: ' + Path(path).name) from None


def _read(path):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise ValueError('Cannot read retention evidence: ' + Path(path).name) from None
    if not isinstance(value, dict):
        raise ValueError('Retention evidence must be an object')
    return value


def _inside(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Retention evidence escapes the project')
    return path


def _fingerprint(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value):
        raise ValueError('Invalid collection fingerprint')
    return value


def _finished(value):
    if not isinstance(value, str):
        raise ValueError('A finished timestamp is required')
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        raise ValueError('Invalid finished timestamp') from None
    if parsed.tzinfo is None or parsed > dt.datetime.now(dt.timezone.utc):
        raise ValueError('Finished timestamp is not an observed past instant')
    return value


def process_inventory():
    from easel_workbench.processes import rows
    return rows()


def _no_process(fingerprint, directory, inventory):
    try:
        inventory = process_inventory() if inventory is None else inventory
    except Exception:
        raise ValueError('Cannot inspect current collection process ownership') from None
    entries = inventory.values() if isinstance(inventory, dict) else inventory
    markers = (fingerprint, directory.name.lower(), str(directory).replace('\\', '/').lower())
    for row in entries:
        pid = row.get('pid', row.get('ProcessId'))
        name = str(row.get('name', row.get('Name', ''))).lower()
        if pid == os.getpid() or name not in ('codex.exe', 'node.exe', 'python.exe', 'pythonw.exe'):
            continue
        command = row.get('command', row.get('CommandLine'))
        if not isinstance(command, str) or not command:
            raise ValueError('Cannot verify arguments of a possible collection process')
        command = command.replace('\\', '/').lower()
        if any(marker in command for marker in markers):
            raise ValueError('The original collection execution may still be running')


def _policy(root):
    active = _read(_inside(root, 'data/active-workbench.json'))
    release = active.get('release', '')
    if not isinstance(release, str) or not re.fullmatch(r'workbench-[A-Za-z0-9_-]+', release):
        raise ValueError('Invalid active runtime')
    package = _inside(root, 'workbench-releases/' + release)
    manifest_path = _inside(root, str(package.relative_to(root) / 'workbench-release.json'))
    if _sha(manifest_path) != active.get('manifest_sha256'):
        raise ValueError('Active runtime manifest changed')
    manifest = _read(manifest_path)
    if manifest.get('schema') != 1 or manifest.get('release') != release or manifest.get('architecture') != 'easel-workbench-extension':
        raise ValueError('Unexpected active runtime manifest')
    for relative, expected in POLICY_SOURCES.items():
        source = _inside(root, relative)
        frozen = _inside(root, str(package.relative_to(root) / relative))
        if manifest.get('files', {}).get(relative) != expected or _sha(source) != expected or _sha(frozen) != expected:
            raise ValueError('Collection execution policy requires a new review')
    return {'release': release, 'manifest_sha256': active['manifest_sha256']}


def inspect_receipt(root, fingerprint, *, inventory=None):
    root = Path(root).resolve()
    fingerprint = _fingerprint(fingerprint)
    cache_path = _inside(root, 'data/collection/model-cache/' + fingerprint + '.json')
    cache = _read(cache_path)
    if cache.get('status') != 'uncertain' or cache.get('input_sha256') != fingerprint or cache.get('error_type') != 'ModelError':
        raise ValueError('Only the exact closed uncertain collection receipt can be retained')
    _finished(cache.get('finished_at'))
    relative = cache.get('request_dir')
    if not isinstance(relative, str) or not re.fullmatch('model-attempts/' + fingerprint + '/[a-f0-9]{32}', relative):
        raise ValueError('Invalid original request directory')
    directory = _inside(root, 'data/collection/' + relative)
    if not directory.is_dir() or {p.name for p in directory.iterdir()} != {'request-binding.json', 'schema.json'}:
        raise ValueError('Original attempt contains unexpected files or a possible result')
    binding_path = _inside(root, str(directory.relative_to(root) / 'request-binding.json'))
    schema_path = _inside(root, str(directory.relative_to(root) / 'schema.json'))
    binding = _read(binding_path)
    schema = _read(schema_path)
    if binding.get('input_sha256') != fingerprint or binding.get('backend') != 'codex_subscription' or type(binding.get('wrapped')) is not bool:
        raise ValueError('Original request binding does not match')
    snapshot = _fingerprint(binding.get('creator_snapshot_sha256'))
    config = _read(_inside(root, 'data/collection-model.json'))
    if config.get('backend') != 'codex_subscription' or any(key in config for key in ('api_key', 'token', 'password')):
        raise ValueError('Only credential-free subscription metadata is supported')
    semantic = {key: config.get(key) for key in SEMANTIC}
    if any(isinstance(value, (dict, list)) for value in semantic.values()):
        raise ValueError('Invalid semantic model metadata')
    if semantic['base_url'] is not None:
        if not isinstance(semantic['base_url'], str):
            raise ValueError('Invalid model URL metadata')
        url = urlsplit(semantic['base_url'])
        if url.username or url.password or url.query or url.fragment:
            raise ValueError('Model URL metadata must not contain credentials')
    database = _inside(root, 'data/desk.sqlite')
    matches = []
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as connection:
        connection.execute('PRAGMA query_only=ON')
        for ident, task_id, raw, updated_at in connection.execute("SELECT id,task_id,document,updated_at FROM creator_model_calls WHERE json_type(document,'$.input')='object'"):
            call = json.loads(raw)
            original = call.get('input')
            if not isinstance(original, dict) or set(original) != {'system', 'payload', 'schema'}:
                continue
            key = hashlib.sha256(json.dumps({**original, 'model': semantic}, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            if key == fingerprint:
                matches.append((ident, task_id, raw, updated_at, call))
    if len(matches) != 1:
        raise ValueError('The original model call must have one exact input match')
    ident, task_id, raw, updated_at, call = matches[0]
    if call.get('id') != ident or task_id is not None or call.get('task_id') is not None or call.get('task') != 'news_enhancement' or call.get('status') != 'unknown' or call.get('error') != 'ModelError':
        raise ValueError('Original model call is not a closed unknown collection call')
    _finished(call.get('finished_at'))
    if call.get('snapshot', {}).get('snapshot_sha256') != snapshot:
        raise ValueError('Frozen creator snapshot does not match the request binding')
    requested_schema = call['input']['schema']
    if requested_schema is not None and not isinstance(requested_schema, dict):
        raise ValueError('Invalid original output schema')
    if binding['wrapped'] != (requested_schema is None) or schema != (requested_schema or WRAPPED_SCHEMA):
        raise ValueError('Original schema and wrapping do not match the frozen input')
    active = _policy(root)
    _no_process(fingerprint, directory, inventory)
    return {'root': str(root), 'fingerprint': fingerprint,
            'cache': {'path': cache_path.relative_to(root).as_posix(), 'sha256': _sha(cache_path), 'status': 'uncertain', 'finished_at': cache['finished_at']},
            'request': {'request_dir': relative, 'binding_sha256': _sha(binding_path), 'schema_sha256': _sha(schema_path)},
            'ledger': {'id': ident, 'document_sha256': hashlib.sha256(raw.encode()).hexdigest(),
                       'row_sha256': hashlib.sha256(json.dumps({'id': ident, 'task_id': task_id, 'document': raw, 'updated_at': updated_at}, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
                       'updated_at': updated_at, 'status': 'unknown', 'finished_at': call['finished_at']},
            'semantic_model': semantic,
            'policy': {'sources': dict(POLICY_SOURCES), 'argv_contract': {'mode': 'exec', 'ephemeral': True, 'sandbox': 'read-only', 'ignore_user_config': True, 'tools_disabled': list(DISABLED), 'input': 'stdin', 'output_schema': 'schema.json', 'output_last_message': 'answer.json'}},
            'process_check': {'matching_processes': 0}, 'observed_active_runtime': active}


def _audit_path(root, fingerprint):
    return _inside(root, '.local/workbench-deployment/collection-retentions/' + fingerprint + '.json')


def _stable(proof):
    return {key: value for key, value in proof.items() if key != 'observed_active_runtime'}


def retained(root, fingerprint, cache_path, *, inventory=None):
    root = Path(root).resolve()
    fingerprint = _fingerprint(fingerprint)
    expected = _inside(root, 'data/collection/model-cache/' + fingerprint + '.json')
    if Path(cache_path).resolve() != expected:
        raise ValueError('Retention cache path does not match its fingerprint')
    path = _audit_path(root, fingerprint)
    if not path.exists():
        return None
    audit = _read(path)
    if set(audit) != {'schema_version', 'kind', 'fingerprint', 'proof', 'retained_at'} or audit.get('schema_version') != 1 or audit.get('kind') != KIND or audit.get('fingerprint') != fingerprint:
        raise ValueError('Invalid immutable collection retention audit')
    _finished(audit['retained_at'])
    try:
        proof = inspect_receipt(root, fingerprint, inventory=inventory)
    except Exception as error:
        raise ValueError('Retained collection evidence is unavailable or invalid') from error
    if not isinstance(audit.get('proof'), dict) or _stable(audit['proof']) != _stable(proof):
        raise ValueError('Retained collection evidence changed; a new review is required')
    return {**proof, 'audit_path': path.relative_to(root).as_posix(), 'audit_sha256': _sha(path)}


def retain(root, fingerprint, *, apply=False, expected_cache_sha256=None, inventory=None):
    root = Path(root).resolve()
    fingerprint = _fingerprint(fingerprint)
    proof = inspect_receipt(root, fingerprint, inventory=inventory)
    if expected_cache_sha256 is not None and proof['cache']['sha256'] != _fingerprint(expected_cache_sha256):
        raise ValueError('Original cache SHA changed; inspect again')
    if apply and expected_cache_sha256 is None:
        raise ValueError('Applying retention requires the reviewed cache SHA')
    path = _audit_path(root, fingerprint)
    prior = retained(root, fingerprint, root / proof['cache']['path'], inventory=inventory)
    if apply and prior is None:
        path.parent.mkdir(parents=True, exist_ok=True)
        audit = {'schema_version': 1, 'kind': KIND, 'fingerprint': fingerprint, 'proof': proof,
                 'retained_at': dt.datetime.now(dt.timezone.utc).isoformat()}
        # Exclusive creation never overwrites a previous review, including a
        # partial or invalid file. Such a file must fail closed on the next read.
        with path.open('x', encoding='utf-8') as stream:
            json.dump(audit, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
    return {'passed': True, 'applied': bool(apply), 'already_retained': prior is not None,
            'audit_path': path.relative_to(root).as_posix(), 'audit_sha256': _sha(path) if path.is_file() else None, 'proof': proof}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--fingerprint', required=True)
    parser.add_argument('--expected-cache-sha256')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(retain(args.root, args.fingerprint, apply=args.apply,
                            expected_cache_sha256=args.expected_cache_sha256), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
