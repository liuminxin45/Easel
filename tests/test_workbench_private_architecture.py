"""Actual P1 boundary checks and negative controls, with read-only inventory."""
import importlib.util
import copy
import json
from pathlib import Path
import sqlite3

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('private_architecture_audit', ROOT / 'scripts/audit_workbench_private_architecture.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def check(source, path):
    return audit.boundary_errors(audit.inspect_source(path, source.encode()))


@pytest.mark.parametrize('source', [
    'import sqlite3', 'from fastapi import Request',
    'def hidden():\n from ..runtime import toolbox_store',
    "importlib.import_module('easel_workbench.' + 'runtime.native_api')",
    'import_module(variable_module)',
    "def hidden():\n return open('private-file').read()",
])
def test_contract_guard_detects_io_and_dynamic_reverse_dependencies(source):
    assert check(source, 'easel_workbench/contracts/example.py')


@pytest.mark.parametrize('source', [
    'from easel_workbench.runtime.toolbox_store import ident as identifier',
    'def delayed():\n from .toolbox_store import text as bounded_text',
    'from .toolbox_store import *',
    "import easel_workbench.runtime.toolbox_store as store\nstore.ident('id')",
    "from . import toolbox_store as store\nstore.pack({})",
    "getattr(import_module('easel_workbench.runtime.toolbox_store'), 'pack')",
    "__import__('easel_workbench.runtime.toolbox_store', fromlist=['ident']).ident('id')",
    "import easel_workbench.runtime.toolbox_store\neasel_workbench.runtime.toolbox_store.ident('id')",
    "def local():\n import easel_workbench.runtime.toolbox_store\n return easel_workbench.runtime.toolbox_store.text('x', 1)",
    "from importlib import import_module\nstore=import_module('easel_workbench.runtime.toolbox_store')\nstore.pack({})",
    "from importlib import import_module as load\nstore=load('easel_workbench.runtime.toolbox_store')\nstore.ident('id')",
    "import easel_workbench.runtime.toolbox_store as store\nother=store\nother.pack({})",
    "__import__('easel_workbench.runtime.toolbox_store').runtime.toolbox_store.ident('id')",
    "__import__('easel_workbench.runtime.toolbox_store', fromlist=[]).runtime.toolbox_store.ident('id')",
    "__import__('easel_workbench.runtime.toolbox_store', fromlist=None).runtime.toolbox_store.ident('id')",
])
def test_guard_rejects_validation_imported_from_storage(source):
    assert check(source, 'easel_workbench/runtime/task_runtime.py')


@pytest.mark.parametrize('source', [
    'from .native_api import is_host_media_protocol',
    "__import__('easel_workbench.runtime.native_api')",
    'from easel_workbench.http import downloads',
    'from . import native_api',
])
def test_download_guard_detects_route_dependency_even_inside_local_imports(source):
    assert check(source, 'easel_workbench/runtime/download_delivery.py')


def test_guards_allow_actual_leaf_dependencies_and_storage_class_consumers():
    assert not check('import json\nimport re', 'easel_workbench/contracts/values.py')
    assert not check('from .toolbox_store import Toolbox', 'easel_workbench/runtime/poster_executor.py')
    assert not check('from easel_workbench.contracts.media_paths import is_host_media_protocol',
                     'easel_workbench/runtime/download_delivery.py')


@pytest.mark.parametrize('source', [
    'import easel_workbench.runtime.toolbox_store as store\ndef use(store):\n return store.pack({})',
    'def first():\n from . import toolbox_store as store\n return store.Toolbox\ndef second(store):\n return store.text()',
    'from . import toolbox_store as store\nstore=other_service\nstore.pack({})',
])
def test_guard_respects_function_parameters_local_aliases_and_rebinding(source):
    assert not check(source, 'easel_workbench/runtime/example.py')


def test_current_checkout_obeys_migrated_private_boundaries():
    report = audit.inventory(ROOT)
    assert not report['violations'], report['violations']
    entry = next(module for module in report['modules'] if module['path'] == 'easel_workbench/entry.py')
    assert set(entry['declared_roles']) == {'server', 'worker', 'collector', 'publisher', 'learning', 'local', 'feedback'}
    assert {role['role'] for role in entry['role_targets']} == {'worker', 'collector', 'publisher', 'learning', 'local', 'feedback'}
    store = next(module for module in report['modules'] if module['path'].endswith('/toolbox_store.py'))
    assert any('toolbox_jobs' in effect['created_tables'] for effect in store['sql_effects'])
    assert not any(symbol['name'] in {'ident', 'pack', 'text'} for symbol in store['symbols'])


def test_inventory_keeps_symbol_ownership_unresolved_imports_and_resource_risks():
    source = '''
from .toolbox_store import Toolbox
def execute(c):
 c.execute("UPDATE toolbox_jobs SET status=?", ('unknown',))
 import_module(dynamic_worker)
 return Path(__file__).with_name('resource.json')
'''
    record = audit.inspect_source('easel_workbench/runtime/example.py', source.encode())
    assert record['symbols'][0]['name'] == 'execute'
    assert record['sql_effects'][0]['symbol'] == 'execute'
    assert record['sql_effects'][0]['verbs'] == ['UPDATE']
    assert record['references'][-1]['kind'] == 'dynamic-unresolved'
    assert record['path_sensitive']


def test_sql_inventory_matches_real_sqlite_writers_without_value_or_upsert_false_targets():
    statements = [
        "INSERT INTO items VALUES(1,'original')",
        "INSERT INTO items VALUES(1,'updated') ON CONFLICT(id) DO UPDATE SET value=excluded.value",
        "UPDATE items SET value='UPDATE phantom SET data=1; DELETE FROM fake' WHERE id=1",
        'REPLACE INTO items VALUES(2,\'replacement\')',
        'DELETE FROM items WHERE id=2',
    ]
    for statement in statements:
        actual = set()
        with sqlite3.connect(':memory:') as connection:
            connection.execute('CREATE TABLE items(id INTEGER PRIMARY KEY,value TEXT)')
            connection.execute("INSERT INTO items VALUES(1,'seed')")
            if statement == statements[0]:
                connection.execute('DELETE FROM items')
            connection.set_authorizer(lambda action, table, *rest:
                (actual.add(table) if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE) else None)
                or sqlite3.SQLITE_OK)
            connection.execute(statement)
        source = 'def write(c):\n c.execute(' + repr(statement) + ')\n'
        record = audit.inspect_source('easel_workbench/runtime/example.py', source.encode())
        assert set(record['sql_effects'][0]['write_tables']) == actual == {'items'}


def test_sql_inventory_keeps_dynamic_targets_unresolved_and_constant_targets_visible():
    source = '''
def write(c, table, suffix):
 c.execute('UPDATE ' + table + ' SET value=?', ('x',))
 c.execute('UPDATE items SET value=? ' + suffix, ('x',))
'''
    record = audit.inspect_source('easel_workbench/runtime/example.py', source.encode())
    assert record['sql_effects'][0]['dynamic_sql']
    assert record['sql_effects'][0]['write_tables'] == []
    assert record['sql_effects'][1]['write_tables'] == ['items']
    assert '{dynamic}' in record['sql_effects'][0]['template']


def test_aliased_dynamic_loader_is_inventoried():
    record = audit.inspect_source('easel_workbench/runtime/example.py',
        b"from importlib import import_module as load\nworker=load('easel_workbench.runtime.server')\n")
    assert any(edge['kind'] == 'dynamic' and edge['module'] == 'easel_workbench.runtime.server'
               for edge in record['references'])


def review_fixture():
    module = audit.inspect_source('easel_workbench/runtime/example.py',
        b'class Service:\n def execute(self):\n  def nested(): return 1\n  return nested()\n')
    module['static_callers'] = []
    entry = {'path': module['path'], 'reviewed_sha256': module['sha256'],
             'symbol_groups': [{'area': 'composition', 'members': ['Service']},
                               {'area': 'features/works', 'members': ['Service.execute']}]}
    return {'modules': [module]}, {'focus_paths': [module['path']], 'modules': [entry]}


def test_review_requires_method_ownership_and_retains_nested_function_owner():
    report, review = review_fixture()
    result = audit.review_coverage(report, review)
    assert not result['errors']
    assert result['modules'][0]['symbol_owners']['Service.execute.nested'] == ['features/works']
    review['modules'][0]['symbol_groups'].pop()
    assert any(error.get('symbol') == 'Service.execute' for error in audit.review_coverage(report, review)['errors'])


def test_review_detects_missing_source_conflicting_owners_and_stale_evidence():
    report, review = review_fixture()
    conflict = copy.deepcopy(review)
    conflict['modules'][0]['symbol_groups'].append({'area': 'http', 'members': ['Service.execute']})
    assert any(error['error'] == 'conflicting symbol owners' for error in audit.review_coverage(report, conflict)['errors'])
    assert audit.review_coverage({'modules': []}, review)['errors']
    review['modules'][0]['reviewed_sha256'] = '0' * 64
    assert audit.review_coverage(report, review)['modules'][0]['source_changed_since_review']


def test_reviewed_responsibilities_cover_the_remaining_modules_and_real_symbols():
    review = json.loads((ROOT / 'docs/workbench/private-architecture-review.json').read_text(encoding='utf-8'))
    report = audit.inventory(ROOT)
    result = audit.review_coverage(report, review)
    assert not result['errors'], result['errors']
    assert {entry['path'] for entry in result['modules']} == set(review['focus_paths'])
    assert all(entry['responsibility'] and entry['state_contract'] and entry['lifecycle'] for entry in result['modules'])
    unresolved = {(module['path'], edge['scope']) for module in report['modules']
                  for edge in module['references'] if edge['kind'] == 'dynamic-unresolved'}
    contracts = {(entry['path'], entry['symbol']) for entry in review['dynamic_import_contracts']}
    assert unresolved <= contracts
    assert all(entry['choices'] and entry['resolution'] for entry in review['dynamic_import_contracts'])
    assert all((ROOT / member).is_file() for member in review['required_release_members'])
