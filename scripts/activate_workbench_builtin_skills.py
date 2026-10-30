"""Preview an atomic, mechanical v1 -> v2 migration to Easel builtins.

The default opens the selected database read-only. Package generation occurs in
a separate TEMP database. --apply additionally requires a reviewed plan hash,
paused workers, admission=false and a second idle/row/source check. No model,
global skill, task, feedback or existing version is modified by this tool.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import difflib
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
IDS = ('content-production', 'topic-research', 'content-writing', 'image-production',
       'reference-analysis', 'delivery-review', 'publication-analysis', 'experience-distillation')
OLD_PRODUCTION = ['content-writing', 'image-production', 'delivery-review']
TABLES = ('creator_skills', 'creator_skill_versions', 'creator_skill_pointers',
          'creator_skill_blobs', 'creator_skill_events', 'creator_profiles',
          'creator_profile_history', 'creator_operations')


def pack(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


@contextlib.contextmanager
def connect(path, *, write=False):
    path = Path(path).resolve()
    connection = sqlite3.connect(str(path) if write else path.as_uri() + '?mode=ro',
                                 uri=not write, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        if not write:
            connection.execute('PRAGMA query_only=ON')
        yield connection
    finally:
        connection.close()


class TempStore:
    def __init__(self, path):
        self.path = path

    @contextlib.contextmanager
    def connect(self):
        with connect(self.path, write=True) as connection:
            with connection:
                yield connection


def source_state(root):
    from easel_workbench.skill_catalog import ProjectSkillCatalog
    root = Path(root).resolve()
    receipt_path = root / 'skills/workbench-import.json'
    raw = receipt_path.read_bytes()
    receipt = json.loads(raw)
    if receipt.get('purpose') != 'read_only_migration_provenance_not_registry' or set(receipt['skill_ids']) != set(IDS):
        raise ValueError('Unexpected builtin import provenance')
    for relative, expected in receipt['files'].items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root / 'skills') or not path.is_file() or sha(path.read_bytes()) != expected:
            raise ValueError('Reviewed builtin source changed: ' + relative)
    catalog = ProjectSkillCatalog(root)
    if {row['id'] for row in catalog.entries()} != set(IDS):
        raise ValueError('Expected exactly eight project builtin capabilities')
    return {'catalog_revision': catalog.revision(), 'import_receipt_sha256': sha(raw),
            'file_set_sha256': sha(pack(receipt['files']))}, receipt


def generated_packages(root):
    """Use actual CreatorRuntime seed logic, with only TEMP database writes."""
    from easel_workbench.runtime.creator_runtime import CreatorRuntime
    with tempfile.TemporaryDirectory(prefix='easel-builtin-versions-') as directory:
        box = SimpleNamespace(root=Path(root).resolve(), store=TempStore(Path(directory) / 'seed.sqlite'))
        runtime = CreatorRuntime(box, project=root)
        with box.store.connect() as connection:
            descriptors = {row['id']: json.loads(row['document']) for row in connection.execute('SELECT * FROM creator_skills')}
            releases = {row['skill_id']: json.loads(row['document']) for row in connection.execute('SELECT * FROM creator_skill_versions WHERE version=1')}
            blobs = {row['sha256']: bytes(row['bytes']) for row in connection.execute('SELECT * FROM creator_skill_blobs')}
        return runtime, descriptors, releases, blobs


def exists(connection, table):
    return connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def busy(connection):
    result = []
    for table in ('toolbox_jobs', 'tasks'):
        if exists(connection, table):
            for row in connection.execute("SELECT id,status FROM " + table + " WHERE status IN ('queued','dispatching','running','uncertain','needs_desktop')"):
                result.append({'table': table, 'id': row['id'], 'status': row['status']})
        if table == 'toolbox_jobs' and exists(connection, table):
            columns = {row['name'] for row in connection.execute('PRAGMA table_info(toolbox_jobs)')}
            if {'dispatch_started', 'queue_id', 'turn_id', 'finished_at'} <= columns:
                for row in connection.execute("SELECT id,status FROM toolbox_jobs WHERE status IN ('error','blocked') AND finished_at IS NULL AND (dispatch_started OR queue_id IS NOT NULL OR turn_id IS NOT NULL)"):
                    result.append({'table': table, 'id': row['id'], 'status': 'unresolved_submitted_' + row['status']})
    for table in ('creator_model_calls', 'distribution_executions', 'distribution_attempts', 'media_install_jobs', 'easel_chat_turns'):
        if not exists(connection, table):
            continue
        columns = {row['name'] for row in connection.execute('PRAGMA table_info(' + table + ')')}
        if not {'id', 'document'} <= columns:
            continue
        for row in connection.execute('SELECT id,document FROM ' + table):
            document = json.loads(row['document']); state = document.get('status')
            active = state in ('running', 'dispatching', 'requested', 'sending', 'submitting', 'queued', 'accepted')
            if table == 'easel_chat_turns':
                active = active or state == 'unknown' or document.get('hook_status') == 'pending' or document.get('start_hook_status') == 'pending'
            if active:
                result.append({'table': table, 'id': row['id'], 'status': state})
    return result


def semantic_rules(value, mapping):
    """Ignore only source-location evidence, never instructions or scope."""
    if isinstance(value, list):
        return [semantic_rules(child, mapping) for child in value]
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            if key == 'provenance' and isinstance(child, dict):
                child = {name: field for name, field in child.items() if name not in ('path', 'sha256')}
            result[key] = semantic_rules(child, mapping)
        return result
    if isinstance(value, str):
        return mapping.get(value, value)
    return value


def binding(connection):
    result = {}
    for table in ('creator_skills', 'creator_skill_versions', 'creator_skill_pointers',
                  'creator_profiles', 'creator_profile_history', 'creator_skill_events', 'creator_operations'):
        rows = [list(row) for row in connection.execute('SELECT * FROM ' + table + ' ORDER BY rowid')]
        result[table] = sha(pack(rows))
    return result


def build_plan(connection, root, *, seed=None):
    from easel_workbench.runtime.creator_runtime import CreatorRuntime, validate_package
    state, receipt = source_state(root)
    revision = sha(pack(state))
    migration_id = 'builtin-project-' + revision[:40]
    prior = connection.execute('SELECT signature,result FROM creator_operations WHERE id=?', (migration_id,)).fetchone()
    if prior:
        result = json.loads(prior['result'])
        if result.get('migration_id') != migration_id or result.get('source_revision') != revision or prior['signature'] != result.get('plan_sha256'):
            raise ValueError('Builtin migration receipt identity is inconsistent')
        for item in result['skills']:
            row = connection.execute('SELECT document FROM creator_skill_versions WHERE skill_id=? AND version=2', (item['id'],)).fetchone()
            release = json.loads(row[0]) if row else None
            if not release or sha(row[0]) != item['new_document_sha256'] or release.get('sha256') != item['new_sha256'] or CreatorRuntime._release_hash(None, release) != item['new_sha256']:
                raise ValueError('Applied builtin migration receipt no longer matches immutable v2')
            old = connection.execute('SELECT document FROM creator_skill_versions WHERE skill_id=? AND version=1', (item['id'],)).fetchone()
            if not old or sha(old[0]) != item['old_document_sha256']:
                raise ValueError('Applied builtin migration receipt no longer matches immutable v1')
        return {'already_applied': True, 'migration_id': migration_id, 'source': state,
                'source_revision': revision, 'receipt': result, 'conflicts': [], 'affected_tables': []}, {}
    runtime, descriptors, releases, seed_blobs = seed or generated_packages(root)
    plan = {'already_applied': False, 'migration_id': migration_id, 'source': state,
            'source_revision': revision, 'database_binding': binding(connection),
            'conflicts': [], 'busy': busy(connection), 'skills': [], 'profiles': [],
            'affected_tables': list(TABLES), 'preserved': ['all existing skill version bytes',
                'all existing profile history bytes', 'all jobs and frozen inputs', 'original feedback', 'all other tables']}
    source_map = {row['old_path']: row for row in receipt['mapping']}
    path_map = {old: row['new_path'] for old, row in source_map.items()}
    blobs = {}
    for sid in IDS:
        rows = connection.execute('SELECT version,document FROM creator_skill_versions WHERE skill_id=? ORDER BY version', (sid,)).fetchall()
        pointer = connection.execute('SELECT revision,version FROM creator_skill_pointers WHERE skill_id=?', (sid,)).fetchone()
        current = connection.execute('SELECT document FROM creator_skills WHERE id=?', (sid,)).fetchone()
        if not pointer or pointer['version'] != 1 or len(rows) != 1 or rows[0]['version'] != 1 or not current:
            plan['conflicts'].append({'skill_id': sid, 'reason': 'current_pointer_or_versions_are_not_exact_v1'})
            continue
        old_raw = rows[0]['document']; old = json.loads(old_raw); new = copy.deepcopy(releases[sid])
        if old.get('status') != 'published' or old.get('sha256') != runtime._release_hash(old):
            plan['conflicts'].append({'skill_id': sid, 'reason': 'v1_not_published_or_hash_mismatch'})
            continue
        if semantic_rules(old.get('baseline_rules', []), path_map) != semantic_rules(new.get('baseline_rules', []), path_map):
            plan['conflicts'].append({'skill_id': sid, 'reason': 'baseline_instructions_or_confirmation_scope_changed'})
        if old.get('variants', []) != new.get('variants', []):
            plan['conflicts'].append({'skill_id': sid, 'reason': 'variant_identity_or_approval_changed'})
        old_resources = old.get('resources', [])
        for resource in old_resources:
            if resource.get('available'):
                old_blob = connection.execute('SELECT bytes FROM creator_skill_blobs WHERE sha256=?', (resource.get('sha256'),)).fetchone()
                if not old_blob or sha(bytes(old_blob[0])) != resource.get('sha256'):
                    plan['conflicts'].append({'skill_id': sid, 'path': resource['path'], 'reason': 'old_frozen_blob_missing_or_invalid'})
            origin = source_map.get(resource['path'])
            if origin and resource.get('available') and not resource.get('derived') and origin['kind'] == 'resource':
                if resource.get('sha256') != origin['old_sha256']:
                    plan['conflicts'].append({'skill_id': sid, 'path': resource['path'], 'reason': 'approved_reference_bytes_changed',
                                              'old_sha256': resource.get('sha256'), 'import_source_sha256': origin['old_sha256']})
        for resource in new['resources']:
            resource['path'] = path_map.get(resource['path'], resource['path'])
            old_match = next((row for row in old_resources if resource.get('variant') and row.get('variant') == resource.get('variant')
                              and row.get('kind') == resource.get('kind') and (row.get('role') or None) == (resource.get('role') or None)
                              and (row.get('label') or None) == (resource.get('label') or None)), None)
            if resource['path'].endswith('/references/confirmed-baseline.json'):
                old_match = next((row for row in old_resources if row['path'].endswith('/references/confirmed-baseline.json')), None)
            if old_match and old_match.get('derived'):
                if resource.get('kind') == 'prompt' and resource.get('sha256') != old_match.get('sha256'):
                    plan['conflicts'].append({'skill_id': sid, 'path': resource['path'], 'reason': 'effective_variant_prompt_changed'})
                destination = resource['path']; resource.clear(); resource.update(copy.deepcopy(old_match), path=destination)
            if resource.get('available'):
                old_blob = connection.execute('SELECT bytes FROM creator_skill_blobs WHERE sha256=?', (resource['sha256'],)).fetchone()
                raw = bytes(old_blob[0]) if old_blob else seed_blobs.get(resource['sha256'])
                if raw is None or sha(raw) != resource['sha256']:
                    plan['conflicts'].append({'skill_id': sid, 'path': resource['path'], 'reason': 'frozen_resource_blob_missing_or_invalid'})
                else:
                    blobs[resource['sha256']] = raw
        new.update(version=2, base_version=1, created_at=None, status='published',
                   baseline_rules=copy.deepcopy(old.get('baseline_rules', [])), variants=copy.deepcopy(old.get('variants', [])),
                   conditions=copy.deepcopy(old.get('conditions', {})), evidence_refs=copy.deepcopy(old.get('evidence_refs', [])),
                   reason='机械迁入 Easel 项目内置技能；不新增风格认可。',
                   migration={'id': migration_id, 'kind': 'project_builtin_mechanical', 'source_revision': revision,
                              'previous_release_sha256': old['sha256'], 'previous_document_sha256': sha(old_raw),
                              'style_instructions_changed': False})
        validate_package(new); new['sha256'] = runtime._release_hash(new)
        descriptor = json.loads(current[0])
        descriptor.update({key: copy.deepcopy(value) for key, value in descriptors[sid].items() if key != 'created_at'})
        descriptor['variants'] = copy.deepcopy(old.get('variants', []))
        plan['skills'].append({'id': sid, 'old_version': 1, 'new_version': 2, 'old_document_sha256': sha(old_raw),
            'old_sha256': old['sha256'], 'new_sha256': new['sha256'], 'pointer_revision': pointer['revision'],
            'old_entry': old['entry'], 'new_entry': new['entry'], 'release': new, 'descriptor': descriptor,
            'prompt_diff': ''.join(difflib.unified_diff(old['prompt'].splitlines(True), new['prompt'].splitlines(True),
                                                    fromfile=sid + '/v1', tofile=sid + '/v2'))})
    for row in connection.execute('SELECT * FROM creator_profiles ORDER BY id'):
        old = json.loads(row['document']); new = copy.deepcopy(old); changed = False
        for sid, version in new.get('skill_versions', {}).items():
            if sid in IDS:
                if version != 1:
                    plan['conflicts'].append({'profile_id': row['id'], 'skill_id': sid, 'reason': 'custom_skill_version_pin'})
                else:
                    new['skill_versions'][sid] = 2; changed = True
        for task, pins in new.get('task_skill_versions', {}).items():
            for sid, version in pins.items():
                if sid in IDS:
                    if version != 1:
                        plan['conflicts'].append({'profile_id': row['id'], 'task': task, 'skill_id': sid, 'reason': 'custom_task_version_pin'})
                    else:
                        pins[sid] = 2; changed = True
        for task in ('poster', 'article', 'change'):
            selected = new.get('default_skills', {}).get(task)
            if selected == OLD_PRODUCTION:
                new['default_skills'][task] = ['content-production', *selected]
                new.setdefault('skill_versions', {})['content-production'] = 2
                new.setdefault('task_skill_versions', {}).setdefault(task, {})['content-production'] = 2
                changed = True
            elif selected is not None and 'content-production' not in selected:
                plan['conflicts'].append({'profile_id': row['id'], 'task': task, 'reason': 'custom_production_defaults_require_scope_review'})
        if changed:
            new.update(revision=row['revision'] + 1, updated_at=None,
                       builtin_migration={'id': migration_id, 'source_revision': revision,
                                          'reason': '项目内置能力机械迁入并绑定真实内容生产根技能；不改变创作风格。'})
            for index, resource in enumerate(new.get('asset_refs', [])):
                resource['url'] = '/api/creator/profiles/' + row['id'] + '/assets/' + str(new['revision']) + '/' + str(index)
            if connection.execute('SELECT 1 FROM creator_profile_history WHERE id=? AND revision=?', (row['id'], new['revision'])).fetchone():
                plan['conflicts'].append({'profile_id': row['id'], 'reason': 'next_profile_history_revision_already_exists'})
            plan['profiles'].append({'id': row['id'], 'old_revision': row['revision'], 'new_revision': new['revision'],
                                     'old_document_sha256': sha(row['document']), 'document': new})
    if len(plan['skills']) != len(IDS):
        plan['conflicts'].append({'reason': 'not_all_eight_capabilities_can_migrate_atomically'})
    plan['plan_sha256'] = sha(pack(plan))
    return plan, blobs


def require_fence(root):
    state = Path(root) / '.local/workbench-deployment'
    admission = json.loads((state / 'admission.json').read_text(encoding='utf-8-sig'))
    if admission.get('workers') is not False or not (state / 'paused').is_file():
        raise ValueError('Applying builtin versions requires admission=false and paused workers')


def apply_plan(database, root, expected_plan_sha256):
    from easel_workbench.runtime.desk import stamp
    require_fence(root)
    if not Path(database).is_file():
        raise ValueError('The authoritative database must already exist')
    with connect(database, write=True) as connection:
        connection.execute('BEGIN IMMEDIATE')
        try:
            plan, blobs = build_plan(connection, root)
            if plan['already_applied']:
                connection.rollback()
                return plan
            if plan['plan_sha256'] != expected_plan_sha256:
                raise ValueError('Reviewed plan changed; no builtin versions were applied')
            if plan['conflicts'] or plan['busy']:
                raise ValueError('Conflicts or active execution prevent builtin migration')
            require_fence(root)
            current_source, _ = source_state(root)
            if current_source != plan['source']:
                raise ValueError('Project builtin source changed during preparation')
            immutable_versions = [tuple(row) for row in connection.execute('SELECT skill_id,version,document FROM creator_skill_versions')]
            immutable_profiles = [tuple(row) for row in connection.execute('SELECT id,revision,document FROM creator_profile_history')]
            now = stamp()
            new_documents = {}
            for identity, raw in blobs.items():
                existing = connection.execute('SELECT bytes FROM creator_skill_blobs WHERE sha256=?', (identity,)).fetchone()
                if existing and bytes(existing[0]) != raw:
                    raise ValueError('Existing blob does not match its immutable identity')
                connection.execute('INSERT OR IGNORE INTO creator_skill_blobs VALUES(?,?)', (identity, raw))
            for item in plan['skills']:
                release = copy.deepcopy(item['release']); release['created_at'] = now
                raw_release = pack(release); new_documents[item['id']] = sha(raw_release)
                connection.execute('INSERT INTO creator_skill_versions VALUES(?,?,?)', (item['id'], 2, raw_release))
                connection.execute('UPDATE creator_skills SET document=? WHERE id=?', (pack(item['descriptor']), item['id']))
                connection.execute('UPDATE creator_skill_pointers SET revision=revision+1,version=2 WHERE skill_id=?', (item['id'],))
                event = {'id': sha(plan['migration_id'] + ':' + item['id'])[:32], 'skill_id': item['id'], 'version': 2,
                         'action': 'publish', 'previous_version': 1, 'created_at': now,
                         'reason': 'authorized_project_builtin_mechanical_migration', 'source_revision': plan['source_revision']}
                connection.execute('INSERT INTO creator_skill_events VALUES(?,?,?,?,?,?)', (event['id'], item['id'], 2, 'publish', pack(event), now))
            for item in plan['profiles']:
                document = copy.deepcopy(item['document']); document['updated_at'] = now
                raw = pack(document)
                connection.execute('INSERT INTO creator_profile_history VALUES(?,?,?)', (item['id'], item['new_revision'], raw))
                connection.execute('UPDATE creator_profiles SET revision=?,document=? WHERE id=?', (item['new_revision'], raw, item['id']))
            receipt = {'migration_id': plan['migration_id'], 'source_revision': plan['source_revision'],
                       'source': plan['source'], 'plan_sha256': plan['plan_sha256'], 'applied_at': now,
                       'skills': [{**{key: row[key] for key in ('id', 'old_version', 'new_version', 'old_sha256', 'new_sha256', 'old_document_sha256')},
                                   'new_document_sha256': new_documents[row['id']]} for row in plan['skills']],
                       'profiles': [{key: row[key] for key in ('id', 'old_revision', 'new_revision')} for row in plan['profiles']],
                       'affected_tables': plan['affected_tables'], 'jobs_requeued': 0, 'old_versions_rewritten': 0}
            connection.execute('INSERT INTO creator_operations VALUES(?,?,?,?)', (plan['migration_id'], plan['plan_sha256'], pack(receipt), now))
            for sid, version, raw in immutable_versions:
                current = connection.execute('SELECT document FROM creator_skill_versions WHERE skill_id=? AND version=?', (sid, version)).fetchone()
                if not current or current[0] != raw:
                    raise ValueError('An existing immutable skill version changed; rolling back')
            for identity, revision, raw in immutable_profiles:
                current = connection.execute('SELECT document FROM creator_profile_history WHERE id=? AND revision=?', (identity, revision)).fetchone()
                if not current or current[0] != raw:
                    raise ValueError('An existing immutable profile revision changed; rolling back')
            connection.commit()
            return {'applied': True, **receipt}
        except BaseException:
            connection.rollback()
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--database', type=Path)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-plan-sha256')
    parser.add_argument('--report', required=True, type=Path)
    options = parser.parse_args()
    root = options.root.resolve(); database = options.database or root / 'data/desk.sqlite'
    if options.apply:
        if database.resolve() != (root / 'data/desk.sqlite').resolve():
            parser.error('--apply targets only the selected project data/desk.sqlite')
        if not options.expected_plan_sha256:
            parser.error('--apply requires --expected-plan-sha256')
        result = apply_plan(database, root, options.expected_plan_sha256)
    else:
        with connect(database) as connection:
            result, _ = build_plan(connection, root)
    options.report.parent.mkdir(parents=True, exist_ok=True)
    options.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: result.get(key) for key in ('already_applied', 'applied', 'migration_id', 'source_revision', 'plan_sha256', 'conflicts', 'busy', 'affected_tables')}, ensure_ascii=False))
    return 1 if result.get('conflicts') or result.get('busy') else 0


if __name__ == '__main__':
    raise SystemExit(main())
