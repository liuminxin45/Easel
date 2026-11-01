"""Actual P1 boundary checks and negative controls, with read-only inventory."""
import importlib.util
from pathlib import Path

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
