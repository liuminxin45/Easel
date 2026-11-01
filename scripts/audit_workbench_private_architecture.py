"""Read-only source inventory for incremental private architecture changes.

This maintenance report is never a runtime registry or proof of reachability.
It records symbols, static references, SQL effects, role targets and path-sensitive
code without importing the application or opening its business database.
"""
from __future__ import annotations

import argparse
import ast
from collections import defaultdict
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'easel_workbench'
PURE_VALUES = {'ident', 'pack', 'text', 'ACTIVE', 'KINDS'}


def literal(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = literal(node.left), literal(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def inspect_source(path, raw):
    source = raw.decode('utf-8-sig')
    tree = ast.parse(source)
    name = '.'.join(Path(path).with_suffix('').parts)
    package = name.removesuffix('.__init__') if name.endswith('.__init__') else name.rsplit('.', 1)[0]
    result = {'path': path, 'sha256': hashlib.sha256(raw).hexdigest(),
              'lines': len(source.splitlines()), 'symbols': [], 'references': [],
              'sql_effects': [], 'path_sensitive': [], 'role_targets': [], 'declared_roles': []}
    aliases = {}

    def module_value(node):
        if isinstance(node, ast.Name):
            return aliases.get(node.id)
        if isinstance(node, ast.Call) and (getattr(node.func, 'id', None) or getattr(node.func, 'attr', None)) in ('__import__', 'import_module') and node.args:
            return literal(node.args[0])
        return None

    def visit(node, scope=''):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            scope = scope + '.' + node.name if scope else node.name
            result['symbols'].append({'name': scope, 'line': node.lineno, 'end': node.end_lineno,
                                      'kind': type(node).__name__})
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    aliases[alias.asname] = alias.name
            result['references'].extend({'module': a.name, 'symbol': None, 'kind': 'import',
                                         'line': node.lineno, 'scope': scope} for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = importlib.util.resolve_name('.' * node.level + (node.module or ''), package) if node.level else node.module or ''
            for alias in node.names:
                aliases[alias.asname or alias.name] = module + '.' + alias.name
            result['references'].extend({'module': module, 'symbol': a.name, 'kind': 'from',
                                         'line': node.lineno, 'scope': scope} for a in node.names)
        elif isinstance(node, ast.Call):
            call = getattr(node.func, 'id', None) or getattr(node.func, 'attr', None)
            if isinstance(node.func, ast.Name) and call in ('open', 'exec', 'eval'):
                result['references'].append({'module': '<builtin>', 'symbol': call,
                    'kind': 'execution', 'line': node.lineno, 'scope': scope})
            if call == 'getattr' and len(node.args) >= 2:
                module, symbol = module_value(node.args[0]), literal(node.args[1])
                if module and symbol:
                    result['references'].append({'module': module, 'symbol': symbol,
                        'kind': 'attribute', 'line': node.lineno, 'scope': scope})
            if call in ('__import__', 'import_module') and node.args:
                module = literal(node.args[0])
                result['references'].append({'module': module, 'symbol': None,
                    'kind': 'dynamic' if module is not None else 'dynamic-unresolved',
                    'line': node.lineno, 'scope': scope})
            if call in ('execute', 'executemany', 'executescript') and node.args:
                sql = literal(node.args[0])
                verbs = sorted(set(re.findall(r'\b(INSERT|UPDATE|DELETE|REPLACE|CREATE|ALTER|DROP)\b', sql or '', re.I)))
                if sql is None or verbs:
                    tables = sorted(set(re.findall(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w]+)', sql or '', re.I)))
                    result['sql_effects'].append({'symbol': scope, 'line': node.lineno,
                        'verbs': [v.upper() for v in verbs], 'created_tables': tables,
                        'dynamic_sql': sql is None})
            if call == 'add_argument' and node.args and literal(node.args[0]) == 'role':
                for keyword in node.keywords:
                    if keyword.arg == 'choices':
                        result['declared_roles'] = list(ast.literal_eval(keyword.value))
        elif isinstance(node, ast.Attribute):
            module = module_value(node.value)
            if module:
                result['references'].append({'module': module, 'symbol': node.attr,
                    'kind': 'attribute', 'line': node.lineno, 'scope': scope})
        # Keep exact historical role targets, including the dynamic import prefix.
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Dict):
            try:
                mapping = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                mapping = {}
            if isinstance(mapping, dict):
                for role, target in mapping.items():
                    if role in {'worker', 'collector', 'publisher', 'learning', 'local', 'feedback'} and isinstance(target, tuple) and len(target) == 2:
                        result['role_targets'].append({'role': role, 'module': PREFIX + '.runtime.' + target[0], 'function': target[1]})
        for child in ast.iter_child_nodes(node):
            visit(child, scope)

    visit(tree)
    for number, line in enumerate(source.splitlines(), 1):
        if '__file__' in line or 'with_name(' in line:
            result['path_sensitive'].append({'line': number, 'source': line.strip()})
    return result


def boundary_errors(record):
    """Enforce only migrated boundaries; legacy feature cycles stay inventoried."""
    errors = []
    for edge in record['references']:
        module = edge['module'] or ''
        if record['path'].startswith('easel_workbench/contracts/'):
            allowed = ('json', 're', 'typing', 'dataclasses', 'enum', PREFIX + '.contracts')
            if not any(module == part or module.startswith(part + '.') for part in allowed):
                errors.append({'rule': 'pure-contract', **edge})
        if module == PREFIX + '.runtime.toolbox_store' and edge['symbol'] in PURE_VALUES | {'*'}:
            errors.append({'rule': 'values-import-storage', **edge})
        target = module + '.' + edge['symbol'] if edge['symbol'] else module
        if record['path'] == 'easel_workbench/runtime/download_delivery.py' and (
            module.startswith(PREFIX + '.http') or any(part in (module, target) for part in (
                PREFIX + '.runtime.native_api', PREFIX + '.runtime.toolbox_server'))
        ):
            errors.append({'rule': 'download-policy-import-http', **edge})
    return errors


def inventory(root=ROOT, revision=None):
    root = Path(root)
    source_revision = subprocess.check_output(['git', 'rev-parse', '--verify', '--end-of-options', (revision or 'HEAD') + '^{commit}'], cwd=root, text=True).strip()
    if revision:
        names = subprocess.check_output(['git', 'ls-tree', '-rz', '--name-only', source_revision, '--', PREFIX], cwd=root).decode().split('\0')
        sources = [(name, subprocess.check_output(['git', 'show', source_revision + ':' + name], cwd=root))
                   for name in names if name.endswith('.py') and '/vendor/' not in name]
    else:
        sources = [(p.relative_to(root).as_posix(), p.read_bytes())
                   for p in sorted((root / PREFIX).rglob('*.py')) if 'vendor' not in p.relative_to(root).parts]
    records = [inspect_source(name, raw) for name, raw in sources]
    module_names = {record['path'].removesuffix('.py').replace('/', '.').removesuffix('.__init__') for record in records}
    callers = defaultdict(set)
    for record in records:
        for edge in record['references']:
            if edge['module']:
                target = edge['module'] + '.' + edge['symbol'] if edge['symbol'] else edge['module']
                callers[target if target in module_names else edge['module']].add(record['path'])
    for record in records:
        module = record['path'].removesuffix('.py').replace('/', '.').removesuffix('.__init__')
        record['static_callers'] = sorted(callers[module])
    violations = [{'path': record['path'], **error} for record in records for error in boundary_errors(record)]
    return {'schema': 1, 'source_revision': source_revision, 'source_kind': 'committed' if revision else 'working-tree',
            'scope': 'private Python excluding vendor; static evidence, not a runtime registry',
            'module_count': len(records), 'violations': violations, 'modules': records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', help='Exact committed baseline; omit to inspect the current checkout')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--check', action='store_true', help='Require the migrated P1 boundaries')
    args = parser.parse_args()
    report = inventory(revision=args.revision)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'module_count': report['module_count'], 'source_revision': report['source_revision'],
                      'violation_count': len(report['violations']),
                      'violations': report['violations'] if args.check else [],
                      'output': str(args.output) if args.output else None}))
    return 1 if args.check and report['violations'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
