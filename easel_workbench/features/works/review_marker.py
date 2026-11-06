"""Project version decisions into their owned output directory; no archive jobs."""
import json
import os
import uuid
from pathlib import Path

NAME='【采纳状态】.md'

def receipt(c,vid):
    row=c.execute('SELECT value FROM toolbox_meta WHERE key=?',('native-review:'+vid,)).fetchone()
    return (json.loads(row[0]).get('receipt') or None) if row else None

def project(box,vid):
    with box.store.connect() as c:binding=receipt(c,vid)
    if not binding:return None
    from easel_workbench.paths import owned_output_path
    directory=owned_output_path(box.root,Path('outputs')/binding['session_id']/binding['version_id']/'products')
    if str(directory)!=binding['product_directory']:raise ValueError('采纳标记目录与准确版本不同')
    if not directory.is_dir():raise ValueError('本版产物目录不存在，未重建或猜测历史内容')
    from easel_workbench.runtime.feedback_ledger import locked
    # Serialize projections, then read the latest committed decision. A delayed
    # old request must never overwrite a later decision with its own state.
    with locked(directory/'.review-marker.lock',timeout=10):
        with box.store.connect() as c:
            row=c.execute("SELECT id,kind,text,scope,created_at FROM toolbox_jobs WHERE candidate_id=? AND work_id=? AND kind IN ('accept','reject') AND status='completed' ORDER BY rowid DESC LIMIT 1",(vid,binding['work_id'])).fetchone()
        value=dict(row) if row else None
        status='已采纳' if value and value['kind']=='accept' else '未采纳' if value else '未处理'
        scopes=json.loads(value['scope']) if value else []
        labels={'images':'图片','copy':'标题与配文','article':'正文'}
        scope='、'.join(labels.get(s,s) for s in scopes) or '未指定'
        content=f'# {status}\n\n作品：{binding["work_id"]}\n\n版本：{vid}\n'
        if value:
            content+=f'\n决定时间：{value["created_at"]}\n\n采纳范围：{scope}\n\n原始决定：\n\n```json\n'+json.dumps(value['text'],ensure_ascii=False)+'\n```\n'
        else:content+='\n尚未记录对此版本的采纳决定。\n'
        content+='\n此文件仅标记本版决定，不代表发布或 Git 提交。\n'
        path=directory/NAME
        if path.is_symlink() or getattr(path,'is_junction',lambda:False)():raise ValueError('状态文件不能经链接跳转')
        if not path.exists() or path.read_text(encoding='utf8')!=content:
            temporary=directory/('.review-state-'+uuid.uuid4().hex+'.tmp')
            try:
                with temporary.open('x',encoding='utf8',newline='\n') as f:f.write(content);f.flush();os.fsync(f.fileno())
                temporary.replace(path)
            finally:temporary.unlink(missing_ok=True)
        return {'status':status,'path':str(path),'scope':scopes,'decision_id':value['id'] if value else None}
