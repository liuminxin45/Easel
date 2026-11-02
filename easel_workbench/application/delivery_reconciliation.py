"""Explicit, SHA-bound correction of a completed turn's failed file receipt.

No executor or transport is called. Original job/outcome evidence is appended
before the existing deterministic receiver runs behind the deployment fence.
"""
from pathlib import Path
import hashlib
import json
import sqlite3

from easel_workbench.features.conversations.receipts import identity,packed,sha,now


def preview(root,turn_id):
    from easel_workbench.runtime.bridge import delivery_paths,allowed_artifact
    root=Path(root).resolve();turn_id=identity(turn_id)
    with sqlite3.connect((root/'data/desk.sqlite').as_uri()+'?mode=ro',uri=True) as c:
        c.row_factory=sqlite3.Row
        row=c.execute('SELECT document FROM easel_chat_turns WHERE id=?',(turn_id,)).fetchone()
        if not row:raise ValueError('准确原生回合不存在')
        turn=json.loads(row[0]);work=turn.get('work') or {}
        job=c.execute('SELECT * FROM toolbox_jobs WHERE id=?',(turn_id,)).fetchone()
        outcome=c.execute('SELECT document FROM toolbox_production_outcomes WHERE job_id=?',(turn_id,)).fetchone()
        if not job or not outcome:raise ValueError('原始接收记录不存在')
        job=dict(job);outcome=json.loads(outcome[0])
    if turn['status']!='completed' or turn.get('hook_status')!='completed' or job['status']!='error' or outcome.get('code')!='missing_deliverables':
        raise ValueError('只允许纠正明确完成且缺失文件登记的回合；未知/中断/已完成记录不可重放')
    if work.get('version_id')!=turn_id or work.get('work_id')!=job['work_id'] or job['turn_id']!=turn.get('native_turn_id') or not job['turn_id']:
        raise ValueError('任务、作品版本与原生完成身份不同')
    if hashlib.sha256(turn['actual_prompt'].encode()).hexdigest()!=turn['actual_prompt_sha256']:raise ValueError('原冻结输入已变化')
    folder=root/'outputs'/turn['session_id']/turn_id/'products'
    files=[]
    for path in delivery_paths(job['reply']):
        if not allowed_artifact(path,[folder]):raise ValueError('明确交付文件不在原任务成品范围')
        files.append({'path':str(path.resolve()),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'size':path.stat().st_size})
    if not files:raise ValueError('没有可核对的明确交付文件')
    manifest=folder/('文章交付.json' if turn.get('snapshot',{}).get('task')=='article' else '贴图交付.json')
    binding=None
    if manifest.is_file():
        if manifest.is_symlink() or getattr(manifest,'is_junction',lambda:False)():raise ValueError('交付清单不能经链接跳转')
        if manifest.stat().st_size>256*1024:raise ValueError('交付清单超出核对范围')
        metadata=json.loads(manifest.read_bytes())
        if metadata.get('schema_version')!=1 or metadata.get('work_id')!=work['work_id'] or metadata.get('version')!=turn_id:
            raise ValueError('交付清单不属于准确原版本')
        if isinstance(metadata.get('artifacts'),list):
            declared={item.get('path'):item for item in metadata['artifacts'] if isinstance(item,dict)}
            for file in files:
                reference=declared.get(Path(file['path']).relative_to(folder).as_posix())
                if not reference or reference.get('sha256')!=file['sha256'] or reference.get('size')!=file['size']:
                    raise ValueError('原交付清单与文件指纹不同')
        binding={'path':str(manifest),'sha256':hashlib.sha256(manifest.read_bytes()).hexdigest()}
    document={'schema':1,'root':str(root),'turn_id':turn_id,'session_id':turn['session_id'],'work_id':work['work_id'],
              'native_turn_id':job['turn_id'],'turn_sha256':sha(turn),'job':job,'outcome':outcome,'files':files,'delivery_manifest':binding}
    return {**document,'plan_sha256':sha(document)}


def apply(root,plan,expected):
    root=Path(root).resolve()
    if plan.get('plan_sha256')!=expected or sha({k:v for k,v in plan.items() if k!='plan_sha256'})!=expected or plan['root']!=str(root):
        raise ValueError('接收纠正预览身份无效')
    read=lambda p:json.loads(p.read_bytes())
    state=root/'.local/workbench-deployment'
    try:fenced=read(state/'admission.json').get('workers') is False and read(state/'cutover.json').get('phase')=='fenced'
    except (OSError,ValueError):fenced=False
    if not fenced:
        raise ValueError('接收纠正必须在正式部署停写期间执行')
    database=root/'data/desk.sqlite'
    with sqlite3.connect(database) as c:
        from easel_workbench.infrastructure.storage.schema import initialize_delivery_reconciliations
        initialize_delivery_reconciliations(c)
        old=c.execute('SELECT document FROM toolbox_delivery_reconciliations WHERE id=?',(expected,)).fetchone()
    if old:
        old=json.loads(old[0])
        if old['status']=='completed':return old
        raise ValueError('原接收纠正仍待核对，不重放')
    if preview(root,plan['turn_id'])!=plan:raise ValueError('原任务或交付字节已变化，请重新核对预览')
    receipt={'id':expected,'status':'prepared','created_at':now(),'original':plan,'model_replayed':False}
    with sqlite3.connect(database) as c:c.execute('INSERT INTO toolbox_delivery_reconciliations VALUES(?,?)',(expected,packed(receipt)))
    from easel_workbench.runtime.desk import Store
    from easel_workbench.runtime.toolbox_store import Toolbox
    from easel_workbench.runtime.production_delivery import record_delivery
    box=Toolbox(Store(database),root)
    result=record_delivery(box,plan['turn_id'],plan['job']['reply'],plan['native_turn_id'],
        product_roots=[root/'outputs'/plan['session_id']/plan['turn_id']/'products'])
    if result['status']!='completed':raise ValueError('原成品接收仍未完成；保留纠正证据，不重新制作')
    for file in plan['files']:
        if hashlib.sha256(Path(file['path']).read_bytes()).hexdigest()!=file['sha256']:raise ValueError('原文件发生变化')
    binding=plan.get('delivery_manifest')
    if binding and hashlib.sha256(Path(binding['path']).read_bytes()).hexdigest()!=binding['sha256']:raise ValueError('原交付清单发生变化')
    receipt.update(status='completed',finished_at=now(),result=result)
    with sqlite3.connect(database) as c:c.execute('UPDATE toolbox_delivery_reconciliations SET document=? WHERE id=?',(packed(receipt),expected))
    return receipt
