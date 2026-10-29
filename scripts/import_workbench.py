"""Import an attested production runtime without importing a dirty workspace.

Only Python import names change. Business records and frozen prompts are never
compiled or rewritten by this tool. Source hashes remain in the provenance file.
"""
from pathlib import Path
import ast
import hashlib
import json
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path('D:/Projects/ai-news-desk')
PREFIX = 'easel_workbench.runtime'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rewrite(raw, names):
    text = raw.decode('utf-8-sig')
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    changes = []
    def position(line, column):
        return offsets[line-1] + len(lines[line-1].encode('utf-8')[:column].decode('utf-8'))
    for node in ast.walk(ast.parse(text)):
        if (isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='__import__'
                and node.args and isinstance(node.args[0],ast.Constant) and isinstance(node.args[0].value,str)
                and node.args[0].value.split('.')[0] in names):
            replacement=f"__import__({(PREFIX+'.'+node.args[0].value)!r},fromlist=['*'])"
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module and node.module.split('.')[0] in names:
            original = ast.get_source_segment(text, node)
            replacement = original.replace('from '+node.module, 'from '+PREFIX+'.'+node.module, 1)
        elif isinstance(node, ast.Import) and any(a.name.split('.')[0] in names for a in node.names):
            pieces = []
            for alias in node.names:
                if alias.name.split('.')[0] in names:
                    if '.' in alias.name:
                        module, member = alias.name.rsplit('.', 1)
                        pieces.append(f'from {PREFIX}.{module} import {member} as {alias.asname or alias.name.split(".")[0]}')
                    else:
                        pieces.append(f'from {PREFIX} import {alias.name} as {alias.asname or alias.name}')
                else:
                    pieces.append('import '+alias.name+(' as '+alias.asname if alias.asname else ''))
            replacement = '; '.join(pieces)
        else:
            continue
        changes.append((position(node.lineno,node.col_offset),position(node.end_lineno,node.end_col_offset),replacement))
    for start, end, value in sorted(changes, reverse=True):
        text = text[:start]+value+text[end:]
    ast.parse(text)
    return text.encode('utf-8')


def main():
    selected = json.loads((SOURCE/'data/active-backend.json').read_text(encoding='utf-8'))
    source = SOURCE/'backend-releases'/selected['release']
    manifest_path = source/'backend-release.json'
    if sha(manifest_path) != selected['manifest_sha256']:
        raise ValueError('Production manifest changed')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    names = {Path(p).parts[0].removesuffix('.py') for p in manifest['files'] if p.endswith('.py')}
    target = ROOT/'easel_workbench/runtime'
    if target.exists():
        raise ValueError('Import destination already exists; review existing import first')
    target.mkdir()
    (target/'__init__.py').write_text('"""Versioned workflow compatibility services."""\n',encoding='utf-8')
    records = {}
    for member, expected in manifest['files'].items():
        original = source/member
        if sha(original) != expected:
            raise ValueError('Production member changed: '+member)
        destination = target/member
        destination.parent.mkdir(parents=True,exist_ok=True)
        if member.endswith('.py') and not member.startswith('vendor/'):
            destination.write_bytes(rewrite(original.read_bytes(), names))
        else:
            shutil.copy2(original,destination)
        records[member] = {'source_sha256':expected,'imported_sha256':sha(destination)}
    (ROOT/'docs/workbench/import-baseline.json').write_text(json.dumps({
        'easel_base':'514caf8089f89b4793063aeae867690cc69bf8b8',
        'official_base':'5a597e5f3ef5b01098b53f36caf719dd9a32b7bf',
        'production':selected,'namespace':PREFIX,'files':records,
        'data_copied':False,'production_changed':False,
    },ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'imported_files':len(records),'production_changed':False}))


if __name__ == '__main__':
    main()
