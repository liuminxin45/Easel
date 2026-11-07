"""Capability governance rejects actual missing evidence in isolated Git trees."""
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

SPEC = importlib.util.spec_from_file_location('private_capability_check', Path(__file__).resolve().parents[1] / 'scripts/check_private_capabilities.py')
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def write(root, path, text):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding='utf-8')


def command(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, text=True, encoding='utf-8').strip()


def commit(root, message):
    command(root, 'add', '--all')
    command(root, '-c', 'user.name=Capability Test', '-c', 'user.email=capability@example.invalid', 'commit', '-qm', message)
    return command(root, 'rev-parse', 'HEAD')


def impact(mode='maintenance', ids='PC-01'):
    return f'Change isolated fixture\n\nPrivate-Change: {mode}\nPrivate-Capabilities: {ids}\nPrivate-Reason: Preserve the existing read contract while fixing validation.'


@pytest.fixture
def repository(tmp_path):
    command(tmp_path, 'init', '-q')
    command(tmp_path, 'config', 'core.autocrlf', 'false')
    write(tmp_path, 'easel/core.py', 'official = True\n')
    baseline = commit(tmp_path, 'Official fixture baseline')
    write(tmp_path, 'easel/core.py', 'official = True\nhost = None\n')
    write(tmp_path, 'easel_workbench/feature.py', 'value = 1\n')
    write(tmp_path, checker.INDEX, '# Index\n\n## 已确认能力\n\n| [PC-01 Demo](private-capabilities/PC-01-demo.md) | preserved |\n')
    write(tmp_path, f'{checker.CARDS}/PC-01-demo.md', '# PC-01 Demo\n\n- **状态：** 已确认保留\n\n需求依据 能力范围 官方复用 接口与状态归属 验证入口 登记记录 后续维护\n\n[source](../../../easel_workbench/feature.py)\n')
    write(tmp_path, 'docs/workbench/upstream-base.json', json.dumps({'upstream_commit': baseline}))
    ledger = {'schema_version': 1, 'upstream_commit': baseline,
              'scope': {'include': sorted(checker.SHARED_INCLUDE), 'exclude': sorted(checker.SHARED_EXCLUDE)},
              'entries': [{'path': 'easel/core.py', 'status': 'M', 'capabilities': ['PC-01'], 'kind': 'host-port',
                           'reason': 'Optional host parameter preserves the default.', 'upstream_check': 'Remove when upstream exposes this parameter.'}]}
    write(tmp_path, checker.LEDGER, json.dumps(ledger))
    head = commit(tmp_path, 'Initial inventory fixture')
    return tmp_path, head


def check(repository, base=None):
    root, _ = repository
    return checker.check_repository(root, base_ref=base)


def test_complete_registry_and_shared_diff_pass(repository):
    assert check(repository) == []


@pytest.mark.parametrize('mutation, expected', [
    ('broken-link', 'broken local link'), ('duplicate-id', 'duplicate capability ID'),
    ('orphan-card', 'unlisted maintenance card'), ('wrong-section', 'incorrect status section'),
])
def test_document_errors_are_not_silently_accepted(repository, mutation, expected):
    root, _ = repository
    if mutation == 'broken-link':
        path = root / f'{checker.CARDS}/PC-01-demo.md'
        path.write_text(path.read_text(encoding='utf-8') + '\n[missing](../../../missing.py)\n', encoding='utf-8')
    elif mutation == 'duplicate-id':
        path = root / checker.INDEX
        path.write_text(path.read_text(encoding='utf-8') + '\n| [PC-01 Again](private-capabilities/PC-01-demo.md) |\n', encoding='utf-8')
    elif mutation == 'orphan-card':
        write(root, f'{checker.CARDS}/PC-02-orphan.md', '# PC-02 Orphan\n')
    else:
        path = root / checker.INDEX
        path.write_text(path.read_text(encoding='utf-8').replace('## 已确认能力', '## 待核对存量'), encoding='utf-8')
    assert any(expected in error for error in check(repository))


def test_new_untracked_shared_source_must_be_registered(repository):
    root, _ = repository
    write(root, 'easel/new_shared.py', 'shared = True\n')
    assert any('unregistered shared-source difference: easel/new_shared.py' in error for error in check(repository))


def test_ledger_stale_or_unknown_capability_is_rejected(repository):
    root, _ = repository
    path = root / checker.LEDGER
    data = json.loads(path.read_text())
    data['entries'].append({**data['entries'][0], 'path': 'easel/deleted.py', 'capabilities': ['PC-99']})
    path.write_text(json.dumps(data))
    errors = check(repository)
    assert any('unknown/missing capability' in error for error in errors)
    assert any('stale shared-source difference' in error for error in errors)


def test_narrowed_ledger_scope_cannot_hide_an_official_source_difference(repository):
    root, _ = repository
    path = root / checker.LEDGER
    data = json.loads(path.read_text())
    data['scope']['include'] = ['web/app.py']
    data['entries'] = []
    path.write_text(json.dumps(data))
    assert any('do not hide differences by narrowing it' in error for error in check(repository))


def test_existing_bugfix_can_use_maintenance_without_rewriting_card(repository):
    root, before = repository
    write(root, 'easel_workbench/feature.py', 'value = 2\n')
    commit(root, impact())
    assert check(repository, before) == []


def test_deleted_source_uses_parent_ownership(repository):
    root, before = repository
    (root / 'easel_workbench/feature.py').unlink()
    card = root / checker.CARDS / 'PC-01-demo.md'
    card.write_text(card.read_text(encoding='utf-8').replace(
        '[source](../../../easel_workbench/feature.py)', 'Source removed.'), encoding='utf-8')
    commit(root, impact())
    assert check(repository, before) == []


def test_source_change_without_impact_trailers_is_rejected(repository):
    root, before = repository
    write(root, 'easel_workbench/feature.py', 'value = 2\n')
    commit(root, 'Unregistered implementation')
    errors = check(repository, before)
    assert any('Private-Change' in error for error in errors)
    assert any('Private-Capabilities' in error for error in errors)


def test_feature_requires_both_card_and_index_in_same_commit(repository):
    root, before = repository
    write(root, 'easel_workbench/feature.py', 'new_capability = True\n')
    commit(root, impact('feature'))
    errors = check(repository, before)
    assert any('update the capability index in the same commit' in error for error in errors)
    assert any('update PC-01 card in the same commit' in error for error in errors)


def test_new_private_helper_requires_owning_card_even_in_maintenance(repository):
    root, before = repository
    write(root, 'easel_workbench/helper.py', 'helper = True\n')
    commit(root, impact())
    errors = check(repository, before)
    assert any('lacks a declared owning capability: easel_workbench/helper.py' in error for error in errors)


def test_non_ascii_source_paths_cannot_bypass_registration(repository):
    root, before = repository
    write(root, 'easel_workbench/工具/新增 能力.py', 'helper = True\n')
    commit(root, impact())
    assert any('lacks a declared owning capability: easel_workbench/工具/新增 能力.py' in error for error in check(repository, before))


def test_new_skill_cannot_avoid_registration_by_using_a_new_directory(repository):
    root, before = repository
    write(root, 'skills/builtin/new-private/SKILL.md', '# New private workflow\n')
    commit(root, impact())
    assert any('lacks a declared owning capability: skills/builtin/new-private/SKILL.md' in error for error in check(repository, before))


def test_registered_feature_with_card_index_and_code_together_passes(repository):
    root, before = repository
    write(root, 'easel_workbench/helper.py', 'helper = True\n')
    path = root / f'{checker.CARDS}/PC-01-demo.md'
    path.write_text(path.read_text(encoding='utf-8') + '\n[new helper](../../../easel_workbench/helper.py)\n', encoding='utf-8')
    path = root / checker.INDEX
    path.write_text(path.read_text(encoding='utf-8') + '\nScope includes the explicitly requested helper.\n', encoding='utf-8')
    commit(root, impact('feature'))
    assert check(repository, before) == []


def test_later_document_commit_cannot_repair_missing_same_commit_registration(repository):
    root, before = repository
    write(root, 'easel_workbench/feature.py', 'new_capability = True\n')
    commit(root, impact('feature'))
    path = root / checker.INDEX
    path.write_text(path.read_text(encoding='utf-8') + '\nLate documentation.\n', encoding='utf-8')
    commit(root, 'Document after implementation')
    assert any('same commit' in error for error in check(repository, before))


def test_document_only_commit_requires_no_business_impact_declaration(repository):
    root, before = repository
    write(root, 'docs/note.md', '# Maintenance note\n')
    commit(root, 'Document actual sources')
    assert check(repository, before) == []


def test_official_history_is_preserved_but_fork_sync_commit_declares_impact(repository):
    root, before = repository
    private_branch = command(root, 'symbolic-ref', '--short', 'HEAD')
    old_base = json.loads((root / 'docs/workbench/upstream-base.json').read_text())['upstream_commit']
    command(root, 'switch', '-q', '-c', 'official-upgrade', old_base)
    write(root, 'easel/upstream_feature.py', 'official_feature = True\n')
    official = commit(root, 'Official upstream feature without fork-only trailers')
    command(root, 'switch', '-q', private_branch)
    command(root, 'merge', '--no-ff', '--no-commit', 'official-upgrade')
    write(root, 'docs/workbench/upstream-base.json', json.dumps({'upstream_commit': official}))
    path = root / checker.LEDGER
    ledger = json.loads(path.read_text())
    ledger['upstream_commit'] = official
    path.write_text(json.dumps(ledger))
    path = root / checker.INDEX
    path.write_text(path.read_text(encoding='utf-8') + '\n| [PC-20 Upstream](private-capabilities/PC-20-upstream.md) |\n', encoding='utf-8')
    write(root, f'{checker.CARDS}/PC-20-upstream.md', '# PC-20 Upstream\n\n- **状态：** 已确认保留\n\n需求依据 能力范围 官方复用 接口与状态归属 验证入口 登记记录 后续维护\n')
    commit(root, impact(ids='PC-20'))
    assert check(repository, before) == []
