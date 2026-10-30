"""Recoverable publication of frozen database releases to project SKILL sources.

The outbox is a filesystem delivery receipt, never a capability registry. Only
an explicitly published project-local release can create one. Original bytes
are retained as blobs before the database transaction commits.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import uuid

from .skill_catalog import parse_skill
from .runtime.desk import stamp
from .runtime.feedback_ledger import locked


def packed(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def digest(raw):return hashlib.sha256(raw).hexdigest()
FIELDS=('path','kind','label','required','scope','variant','approval','role')


def initialize(c):
    c.execute('CREATE TABLE IF NOT EXISTS creator_skill_source_outbox(id TEXT PRIMARY KEY,skill_id TEXT NOT NULL,version INTEGER NOT NULL,document TEXT NOT NULL)')


def managed(release):
    return release.get('entry')=='skills/builtin/'+release['id']+'/SKILL.md'


def _path(runtime,name):
    if not isinstance(name,str) or '\\' in name or '..' in Path(name).parts or Path(name).is_absolute():
        raise ValueError('技能同步路径无效')
    path=runtime.project/name
    for part in (path,*path.parents):
        if part==runtime.project:break
        if part.is_symlink() or getattr(part,'is_junction',lambda:False)():raise ValueError('技能同步不能经过链接')
    result=path.resolve()
    if not result.is_relative_to(runtime.project/'skills'):raise ValueError('技能同步只能写入本项目技能目录')
    return result


def _descriptors(resources):
    return {r['path']:{k:r[k] for k in FIELDS if k in r} for r in resources}


def declared_resources(release):
    metadata,_=parse_skill(release['prompt'])
    raw=metadata['metadata']['openclaw']['workbench'].get('resources',[])
    frozen={r['path']:r for r in release.get('resources',[])}
    return [frozen[r['path']] for r in raw if not r.get('historical') and r.get('executable') is not False
            and r.get('kind') not in ('legacy_script','legacy_operation','historical_index')]


def validate_metadata(release):
    metadata,_=parse_skill(release['prompt'])
    extra=metadata.get('metadata')
    openclaw=extra.get('openclaw') if isinstance(extra,dict) else None
    raw=openclaw.get('workbench') if isinstance(openclaw,dict) else None
    if not isinstance(raw,dict) or raw.get('schema_version')!=1:raise ValueError('项目技能缺少数据库能力元信息')
    if metadata.get('name')!=release['id'] or metadata.get('layer')!=release.get('layer') or metadata.get('description')!=release.get('description'):
        raise ValueError('技能名称、分层和用途须与已登记版本一致')
    for field in ('id','tasks','executor','input_contract','output_contract','acceptance_cases','composition'):
        if raw.get(field)!=release.get(field):raise ValueError('不能通过原始技能头部改变已登记的身份、任务、组合或合同：'+field)
    if raw.get('display_name',release['id'])!=release.get('name'):raise ValueError('技能显示名称与数据库版本不一致')
    resources=raw.get('resources',[])
    if not isinstance(resources,list) or any(not isinstance(r,dict) for r in resources):raise ValueError('技能资源声明无效')
    resources=[r for r in resources if not r.get('historical') and r.get('executable') is not False and r.get('kind') not in ('legacy_script','legacy_operation','historical_index')]
    # Default flags are normalized by CreatorRuntime._resource.
    normalized=[{**r,'kind':r.get('kind','reference'),'required':r.get('required',False)} for r in resources]
    declared,frozen=_descriptors(normalized),_descriptors(release.get('resources',[]))
    if any(frozen.get(name)!=descriptor for name,descriptor in declared.items()):
        raise ValueError('当前SKILL资源声明须与本版本冻结资源清单一致')


def stage(runtime,c,release,operation,previous):
    if not managed(release):return None  # legacy external entries stay external
    initialize(c);validate_metadata(release)
    desired={release['entry']:release['prompt'].encode('utf-8')}
    if previous and not managed(previous):
        current=_path(runtime,release['entry'])
        current_text=current.read_text(encoding='utf-8-sig') if current.is_file() else None
        for row in c.execute('SELECT version FROM creator_skill_versions WHERE skill_id=? ORDER BY version DESC',(release['id'],)).fetchall():
            known=runtime._skill(c,release['id'],row['version'],False)
            if managed(known) and known['status']=='published' and known['prompt']==current_text:
                previous=known;break
    prior_resources={r['path']:r for r in declared_resources(previous)} if previous and managed(previous) else {}
    source_resources=declared_resources(release)
    declared_paths={r['path'] for r in source_resources}
    frozen_paths={r['path'] for r in release.get('resources',[])}
    if any(name not in declared_paths and name in frozen_paths for name in prior_resources):
        raise ValueError('不能只从技能头部隐藏仍绑定的源码资源')
    for resource in source_resources:
        name=resource['path'];path=_path(runtime,name)
        own='skills/builtin/'+release['id']+'/'
        existing_identical=path.is_file() and digest(path.read_bytes())==resource.get('sha256')
        if not name.startswith(own) and (not name.startswith('skills/shared/workbench/') or name not in prior_resources and not existing_identical):
            raise ValueError('新资源请放在本技能目录；共享资源须已有明确登记')
        row=c.execute('SELECT bytes FROM creator_skill_blobs WHERE sha256=?',(resource.get('sha256'),)).fetchone()
        if not resource.get('available') or not row or digest(bytes(row[0]))!=resource['sha256']:
            raise ValueError('项目技能资源冻结字节不完整，不能同步')
        desired[name]=bytes(row[0])
    before_expected={}
    if previous and managed(previous):
        before_expected[previous['entry']]=previous['prompt'].encode('utf-8')
        for resource in declared_resources(previous):
            row=c.execute('SELECT bytes FROM creator_skill_blobs WHERE sha256=?',(resource.get('sha256'),)).fetchone()
            if row:before_expected[resource['path']]=bytes(row[0])
    files=[]
    for name,raw in desired.items():
        path=_path(runtime,name);current=path.read_bytes() if path.is_file() else None
        prior=before_expected.get(name)
        # Initial sources may have CRLF or a BOM; frozen prompt text is the
        # already-normalized instruction. Preserve actual original bytes too.
        prompt_matches=(name==release['entry'] and previous and current is not None and
                        current.decode('utf-8-sig').replace('\r\n','\n')==previous['prompt'])
        if current is not None and current!=raw and current!=prior and not prompt_matches:
            raise ValueError('当前技能原件已有未确认修改，未覆盖：'+name)
        if current is None and prior is not None:
            raise ValueError('已发布技能原件缺失，先核对后再发布：'+name)
        target_sha=digest(raw);c.execute('INSERT OR IGNORE INTO creator_skill_blobs VALUES(?,?)',(target_sha,raw))
        before_sha=digest(current) if current is not None else None
        if current is not None:c.execute('INSERT OR IGNORE INTO creator_skill_blobs VALUES(?,?)',(before_sha,current))
        files.append({'path':name,'sha256':target_sha,'before_sha256':before_sha})
    identifier=uuid.uuid4().hex
    document={'id':identifier,'operation_id':operation,'skill_id':release['id'],'version':release['version'],
              'release_sha256':release['sha256'],'status':'pending','files':files,'created_at':stamp()}
    c.execute('INSERT INTO creator_skill_source_outbox VALUES(?,?,?,?)',(identifier,release['id'],release['version'],packed(document)))
    return {'id':identifier,'status':'pending'}


def _atomic(path,raw):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(raw);stream.flush()
            __import__('os').fsync(stream.fileno())
        temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)


def apply(runtime,identifier):
    state=runtime.root/'data/creator-source-sync'
    try:
        with runtime.store.connect() as c:
            initialize(c)
            row=c.execute('SELECT document FROM creator_skill_source_outbox WHERE id=?',(identifier,)).fetchone()
            if not row:raise ValueError('找不到准确的技能同步记录')
            document=json.loads(row[0])
        with locked(state/(document['skill_id']+'.lock'),timeout=20):
            with runtime.store.connect() as c:
                c.execute('BEGIN IMMEDIATE')
                row=c.execute('SELECT document FROM creator_skill_source_outbox WHERE id=?',(identifier,)).fetchone();document=json.loads(row[0])
                if runtime._published(c,document['skill_id'])!=document['version']:raise ValueError('当前已发布技能版本已变化，不能恢复旧源码')
                release=runtime._skill(c,document['skill_id'],document['version'],False)
                if release['sha256']!=document['release_sha256']:raise ValueError('技能版本指纹变化')
                validate_metadata(release)
                if document.get('applied_at') and any(not _path(runtime,item['path']).is_file() or
                        digest(_path(runtime,item['path']).read_bytes())!=item['sha256'] for item in document['files']):
                    raise ValueError('已完成发布后的源码又被修改，请另存候选核对；不覆盖当前修改')
                # Resources first, SKILL.md last. Readers also require applied
                # outbox state, so a partial filesystem commit remains closed.
                for item in sorted(document['files'],key=lambda r:r['path']==release['entry']):
                    path=_path(runtime,item['path'])
                    row=c.execute('SELECT bytes FROM creator_skill_blobs WHERE sha256=?',(item['sha256'],)).fetchone()
                    if not row or digest(bytes(row[0]))!=item['sha256']:raise ValueError('待发布资源字节缺失')
                    raw=bytes(row[0]);current=path.read_bytes() if path.is_file() else None
                    current_sha=digest(current) if current is not None else None
                    if current_sha not in (item['sha256'],item['before_sha256']):raise ValueError('同步期间源码已有新修改，未覆盖')
                    if item['before_sha256'] is not None:
                        original=c.execute('SELECT bytes FROM creator_skill_blobs WHERE sha256=?',(item['before_sha256'],)).fetchone()
                        if not original or digest(bytes(original[0]))!=item['before_sha256']:raise ValueError('发布前原件证据缺失')
                        backup=state/identifier/'originals'/item['path']
                        if backup.is_file() and digest(backup.read_bytes())!=item['before_sha256']:raise ValueError('发布备份证据已变化')
                        if not backup.exists():_atomic(backup,bytes(original[0]))
                    if current_sha!=item['sha256']:_atomic(path,raw)
                    if digest(path.read_bytes())!=item['sha256']:raise ValueError('发布后源码核验失败')
                document['status']='applied';document.setdefault('applied_at',stamp());document.pop('error_type',None)
                c.execute('UPDATE creator_skill_source_outbox SET document=? WHERE id=?',(packed(document),identifier))
        return {'id':identifier,'status':'applied'}
    except Exception as error:
        with runtime.store.connect() as c:
            initialize(c)
            row=c.execute('SELECT document FROM creator_skill_source_outbox WHERE id=?',(identifier,)).fetchone()
            if row:
                document=json.loads(row[0]);document.update(status='blocked',error_type=type(error).__name__,checked_at=stamp())
                c.execute('UPDATE creator_skill_source_outbox SET document=? WHERE id=?',(packed(document),identifier))
        return {'id':identifier,'status':'blocked','error_type':type(error).__name__,
                'message':'技能发布已记录，当前源码同步待核对；未覆盖并发修改，不启动模型。'}


def finish_response(runtime,c,response):
    sync=response.get('result',{}).get('source_sync')
    if not sync:return response
    c.commit()  # the publication and its recovery intent must precede files
    response['result']['source_sync']=apply(runtime,sync['id'])
    c.execute('UPDATE creator_operations SET result=? WHERE id=?',(packed(response),response['id']))
    return response


def pending(runtime,c,skill_id,version):
    initialize(c)
    if type(version) is not int or version<1:raise ValueError('请选择准确的技能版本')
    if runtime._published(c,skill_id)!=version:raise ValueError('请选择当前准确的已发布版本')
    row=c.execute('SELECT id FROM creator_skill_source_outbox WHERE skill_id=? AND version=? ORDER BY rowid DESC LIMIT 1',(skill_id,version)).fetchone()
    if not row:raise ValueError('此版本没有待核对的项目技能同步')
    return {'id':row[0],'status':'pending'}


def matches_source(runtime,release,c=None):
    if not managed(release):return False
    if c is None:
        with runtime.store.connect() as connection:return matches_source(runtime,release,connection)
    try:
        validate_metadata(release)
        if c.execute("SELECT 1 FROM sqlite_master WHERE name='creator_skill_source_outbox'").fetchone():
            row=c.execute('SELECT document FROM creator_skill_source_outbox WHERE skill_id=? AND version=? ORDER BY rowid DESC LIMIT 1',(release['id'],release['version'])).fetchone()
            if row and json.loads(row[0]).get('status')!='applied':return False
        if _path(runtime,release['entry']).read_text(encoding='utf-8-sig')!=release['prompt']:return False
        return all(r.get('available') and digest(_path(runtime,r['path']).read_bytes())==r.get('sha256') for r in declared_resources(release))
    except (ValueError,OSError,KeyError,TypeError):return False
