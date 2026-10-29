"""Copy-only preview migration; never selects a release or starts a writer.

SQLite files use the online backup API, including nested queues. A preview is
not a cutover snapshot: final synchronization requires fenced source writers.
"""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

CONFIG_PATH_KEYS = {
    'collection-sources.json': ('profile_dir', 'state_root'),
    'feedback-config.json': ('profile_dir',),
}


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def _is_original(relative,originals=frozenset()):
    parts=relative.parts
    return (relative.as_posix() in originals or parts[0]=='artifacts'
            or len(parts)>2 and parts[:2]==('toolbox','files'))


def original_paths(source):
    """Identify persisted attachments without initializing any application tables."""
    database=source/'data/desk.sqlite';result=set()
    if not database.is_file():return result
    with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as connection:
        connection.execute('BEGIN')
        tables={r[0] for r in connection.execute("select name from sqlite_master where type='table'")}
        for table in ('artifacts','toolbox_files','wb_files','wb_host_files'):
            if table not in tables:continue
            columns={r[1] for r in connection.execute('pragma table_info('+_quoted(table)+')')}
            if 'path' not in columns:continue
            for (value,) in connection.execute('select path from '+_quoted(table)):
                if not isinstance(value,str):continue
                path=Path(value).resolve()
                if path.is_relative_to((source/'data').resolve()):result.add(path.relative_to(source/'data').as_posix())
    return result


def included(relative,*,originals=frozenset()):
    if _is_original(relative,originals):return True
    parts=relative.parts;name=parts[-1]
    return not (parts[0].startswith('build-') or parts[0]=='logs' or len(parts)==1 and name.startswith('active-')
        or name.endswith(('.lock','.pid','.log','.sqlite-wal','.sqlite-shm','.sqlite-journal','.db-wal','.db-shm','.db-journal'))
        or name=='pids.json' or name.endswith('-pids.json'))


def _quoted(value):
    return '"'+value.replace('"','""')+'"'


def _cell(value):
    """Type-preserving row encoding; blobs never appear in the public report."""
    if value is None:return ['null']
    if isinstance(value,bytes):return ['blob',value.hex()]
    if isinstance(value,int):return ['integer',str(value)]
    if isinstance(value,float):return ['real',value.hex()]
    if isinstance(value,str):return ['text',value]
    raise ValueError('Unsupported SQLite value type')


def database_fingerprint(connection):
    """Hash schema and every complete row, independent of physical row order.

    Hashes form a multiset: duplicate rows contribute repeatedly. Sorting only
    fixed-size row digests keeps large history tables bounded in memory.
    The caller owns a stable read transaction when comparing a live source.
    """
    schema=connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name,tbl_name").fetchall()
    schema_sha=hashlib.sha256(json.dumps(schema,ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest()
    tables={}
    for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall():
        cursor=connection.execute('SELECT * FROM '+_quoted(name))
        columns=[item[0] for item in cursor.description]
        row_hashes=[]
        for row in cursor:
            raw=json.dumps([_cell(value) for value in row],ensure_ascii=False,separators=(',',':')).encode('utf-8')
            row_hashes.append(hashlib.sha256(raw).digest())
        h=hashlib.sha256(json.dumps(columns,ensure_ascii=False,separators=(',',':')).encode('utf-8'))
        for row_hash in sorted(row_hashes):h.update(row_hash)
        tables[name]={'rows':len(row_hashes),'sha256':h.hexdigest(),'columns':columns}
    return {'schema_sha256':schema_sha,'tables':tables}


def _rebase_config(raw, relative, source, target):
    keys=CONFIG_PATH_KEYS.get(relative.as_posix())
    if not keys:return raw,[]
    value=json.loads(raw.decode('utf-8-sig'))
    if not isinstance(value,dict):raise ValueError('Invalid mutable path configuration: '+str(relative))
    changed=[]
    owned=(source/'data').resolve()
    for key in keys:
        original=value.get(key)
        if not isinstance(original,str) or not original:continue
        path=Path(original)
        if not path.is_absolute():continue
        path=path.resolve()
        if path.is_relative_to(owned):
            value[key]=str(target/'data'/path.relative_to(owned));changed.append(key)
    if not changed:return raw,[]
    return (json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8'),changed


def validate(source,target,*,compare_source=True,manifest=None):
    """Read-only verification suitable for a fenced final migration.

    With compare_source=True, reject additions, removals, changed files or rows
    since the source snapshot. This detects a writer that escaped cutover fencing.
    The report may be passed explicitly after moving a staged data directory.
    """
    source=Path(source).resolve();target=Path(target).resolve()
    report=manifest or json.loads((target/'migration-report.json').read_text(encoding='utf-8'))
    originals=original_paths(source) if compare_source else set()
    errors=[];fingerprints=report.get('database_fingerprints',{});files=report.get('files',{})
    source_files=report.get('source_files',{})
    for member,expected in files.items():
        relative=Path(member);destination=(target/'data'/relative).resolve()
        if not destination.is_relative_to((target/'data').resolve()):
            errors.append({'file':member,'reason':'path_outside_target'});continue
        if not destination.is_file():errors.append({'file':member,'reason':'missing_target'});continue
        if digest(destination)!=expected:errors.append({'file':member,'reason':'target_file_changed'})
        if member in fingerprints:
            try:
                with closing(sqlite3.connect(destination.as_uri()+'?mode=ro',uri=True)) as connection:
                    if connection.execute('pragma integrity_check').fetchall()!=[('ok',)]:
                        errors.append({'file':member,'reason':'target_integrity_failed'})
                    if database_fingerprint(connection)!=fingerprints[member]:
                        errors.append({'file':member,'reason':'target_rows_changed'})
            except sqlite3.Error:errors.append({'file':member,'reason':'target_database_unreadable'})
        if compare_source:
            original=source/'data'/relative
            if not original.is_file():errors.append({'file':member,'reason':'missing_source'});continue
            if member in fingerprints:
                with closing(sqlite3.connect(original.as_uri()+'?mode=ro',uri=True)) as connection:
                    connection.execute('BEGIN')
                    if database_fingerprint(connection)!=fingerprints[member]:
                        errors.append({'file':member,'reason':'source_rows_changed'})
            elif member not in source_files or digest(original)!=source_files[member]:
                errors.append({'file':member,'reason':'source_file_changed'})
    if compare_source:
        current={p.relative_to(source/'data').as_posix() for p in (source/'data').rglob('*') if p.is_file() and included(p.relative_to(source/'data'),originals=originals)}
        for member in sorted(current-set(files)):errors.append({'file':member,'reason':'source_file_added'})
        if not source_files or not fingerprints:errors.append({'reason':'missing_source_fingerprints'})
    return {'passed':not errors,'errors':errors,'files':len(files),'databases':len(fingerprints),
            'compared_source':compare_source,'read_only':True}


def migrate(source,target,*,runtime_root=None):
    source=Path(source).resolve();target=Path(target).resolve()
    runtime_root=Path(runtime_root).resolve() if runtime_root is not None else target
    if target==source or target.is_relative_to(source) or source.is_relative_to(target):
        raise ValueError('Migration requires independent source and target directories')
    if target.exists():raise ValueError('Target must be new; never overwrite a previous migration')
    target.mkdir(parents=True)
    records={};databases={};fingerprints={};source_files={};rewrites={}
    originals=original_paths(source)
    for original in sorted((source/'data').rglob('*')):
        if not original.is_file():continue
        relative=original.relative_to(source/'data')
        if not included(relative,originals=originals):continue
        if not original.resolve().is_relative_to((source/'data').resolve()):
            raise ValueError('Linked source file outside owned data: '+str(relative))
        destination=target/'data'/relative;destination.parent.mkdir(parents=True,exist_ok=True)
        if original.suffix in ('.sqlite','.db') and not _is_original(relative,originals):
            with closing(sqlite3.connect(original.as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(destination)) as dst:
                src.execute('BEGIN')
                expected=database_fingerprint(src)
                src.backup(dst)
                check=dst.execute('pragma integrity_check').fetchall()
                if check!=[('ok',)]:raise ValueError('Migrated SQLite failed integrity check: '+str(relative))
                actual=database_fingerprint(dst)
                if expected!=actual:raise ValueError('SQLite row or schema mismatch: '+str(relative))
                fingerprints[relative.as_posix()]=expected
                databases[relative.as_posix()]={name:detail['rows'] for name,detail in expected['tables'].items()}
        else:
            before=digest(original);shutil.copy2(original,destination)
            if before!=digest(destination) or before!=digest(original):raise ValueError('Source changed while copying: '+str(relative))
            source_files[relative.as_posix()]=before
            raw,changed=_rebase_config(destination.read_bytes(),relative,source,runtime_root)
            if changed:
                destination.write_bytes(raw);rewrites[relative.as_posix()]=changed
        records[relative.as_posix()]=digest(destination)
    report={'source':str(source),'target':str(target),'runtime_root':str(runtime_root),'kind':'online-preview-copy','production_changed':False,
        'live':False,'files':records,'source_files':source_files,'databases':databases,
        'database_fingerprints':fingerprints,'mutable_config_rewrites':rewrites,
        'frozen_input_policy':'Preserve source bytes; do not rewrite historical prompts or receipts',
        'cutover_requires':'Fence every source writer, repeat final copy, verify records and files, then atomically change routing'}
    (target/'migration-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'copied_files':len(records),'databases':len(databases),'target':str(target),'live':False}))
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--target',type=Path,required=True)
    p.add_argument('--runtime-root',type=Path)
    a=p.parse_args();migrate(a.source,a.target,runtime_root=a.runtime_root)
