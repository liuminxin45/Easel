"""Mechanical project skill import invariants; no model or production writes."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = load('builtin_migration', 'scripts/migrate_workbench_builtin_skills.py')
checker = load('builtin_byte_checker', 'skills/builtin/delivery-review/scripts/check_deliverables.py')
validator = load('upstream_skill_validator', 'scripts/validate_skills.py')


def frontmatter(path):
    return yaml.safe_load(path.read_text(encoding='utf-8').split('---', 2)[1])


def test_eight_actual_builtin_packages_follow_upstream_format_and_composition():
    for sid in migration.IDS:
        path = ROOT / 'skills/builtin' / sid / 'SKILL.md'
        assert not validator.validate(path)
        metadata = frontmatter(path)['metadata']['openclaw']['workbench']
        assert metadata['id'] == sid
        assert metadata['migration']['published_style_change'] is False
        for row in metadata['resources']:
            resource = migration.within(ROOT, row['path'])
            assert resource.is_file()
            if row.get('historical'):
                assert row['executable'] is False
    root = frontmatter(ROOT / 'skills/builtin/content-production/SKILL.md')['metadata']['openclaw']['workbench']
    assert root['executor'] == 'agent'
    assert root['composition']['requires'] == ['content-writing', 'image-production', 'delivery-review']


def test_migration_receipt_is_complete_and_style_and_assets_preserve_exact_bytes():
    receipt = json.loads((ROOT / migration.RECEIPT).read_text(encoding='utf-8'))
    assert receipt['purpose'] == 'read_only_migration_provenance_not_registry'
    for name, expected in receipt['files'].items():
        assert migration.sha(migration.within(ROOT, name).read_bytes()) == expected
    for row in receipt['mapping']:
        assert migration.sha(migration.within(ROOT, row['new_path']).read_bytes()) == row['new_sha256']
        if row['transformation'] == 'byte_copy':
            assert row['old_sha256'] == row['new_sha256']
    assert not any(name.endswith('.py') for name in receipt['files'] if '/provenance/' in name)


def test_apply_is_idempotent_and_refuses_modified_project_file(tmp_path):
    receipt = {'registry_sha256': 'synthetic', 'files': {'skills/builtin/local/SKILL.md': migration.sha(b'original')}}
    files = {'skills/builtin/local/SKILL.md': b'original', migration.RECEIPT: migration.packed(receipt).encode()}
    assert migration.apply(tmp_path, files, write=True)['changed']
    assert migration.apply(tmp_path, files, write=True)['idempotent']
    path = tmp_path / 'skills/builtin/local/SKILL.md'
    path.write_bytes(b'human-edited')
    with pytest.raises(ValueError, match='content changed'):
        migration.apply(tmp_path, files, write=True)
    assert path.read_bytes() == b'human-edited'


def test_source_drift_and_global_target_fail_before_writes(tmp_path):
    previous = tmp_path / migration.RECEIPT
    previous.parent.mkdir()
    previous.write_text(migration.packed({'registry_sha256': 'original', 'files': {}}), encoding='utf-8')
    with pytest.raises(ValueError, match='source registry changed'):
        migration.apply(tmp_path, {migration.RECEIPT: migration.packed({'registry_sha256': 'new'}).encode()}, write=True)
    with pytest.raises(ValueError, match='Global skill'):
        migration.apply(Path.home() / '.codex/skills/forbidden', {}, write=True)


def test_selected_json_resource_paths_resolve_inside_project():
    receipt = json.loads((ROOT / migration.RECEIPT).read_text(encoding='utf-8'))
    for row in receipt['mapping']:
        if row['transformation'] != 'json_project_path_rebase':
            continue
        document = json.loads((ROOT / row['new_path']).read_text(encoding='utf-8'))
        for reference in migration.file_references(document):
            assert reference.startswith(migration.SHARED)
            assert migration.within(ROOT, reference).is_file()


def test_read_only_byte_checker_distinguishes_files_identity_and_locked_text(tmp_path):
    path = tmp_path / '文章正文.md'
    path.write_text('保留原话。\n真实正文。', encoding='utf-8')
    row = {'path': path.name, 'sha256': migration.sha(path.read_bytes()), 'locked_text': ['保留原话。']}
    document = {'schema_version': 1, 'work_id': 'work-1', 'version': 'v2', 'artifacts': [row]}
    assert checker.check(tmp_path, document, work_id='work-1', version='v2')['status'] == 'passed'
    with pytest.raises(ValueError, match='identity mismatch'):
        checker.check(tmp_path, document, work_id='other', version='v2')
    row['locked_text'] = ['不存在的原话']
    with pytest.raises(ValueError, match='original text'):
        checker.check(tmp_path, document, work_id='work-1', version='v2')
    row['locked_text'] = []
    path.write_text('later change', encoding='utf-8')
    with pytest.raises(ValueError, match='bytes'):
        checker.check(tmp_path, document, work_id='work-1', version='v2')


@pytest.mark.parametrize('relative', ['../outside.txt', '/outside.txt', 'C:/outside.txt', 'nested\\file.txt'])
def test_byte_checker_refuses_paths_outside_explicit_output_root(tmp_path, relative):
    with pytest.raises(ValueError, match='path'):
        checker.check(tmp_path, {'schema_version': 1, 'artifacts': [{'path': relative, 'sha256': '0' * 64}]})
