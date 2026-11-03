"""Project draft/discussion topic descriptors without constructing every work."""
import hashlib
import json
from pathlib import Path

from easel_workbench.contracts.legacy_jobs import ACTIVE
from easel_workbench.contracts.values import pack


def _changed_discussion(c,wid):
    # This is freeze()'s original all-rounds token, excluding frozen_options
    # which is intentionally not part of that stable token contract.
    rounds=[{'id':row['id'],'version_id':row['candidate_id'],'question':row['text'],
             'answer':row['reply'] or '','files':json.loads(row['files'])}
            for row in c.execute("SELECT id,candidate_id,text,reply,files FROM toolbox_jobs WHERE work_id=? AND kind='discuss' AND status='completed' ORDER BY rowid",(wid,))]
    token=hashlib.sha256(pack(rounds).encode()).hexdigest()
    row=c.execute("SELECT json_extract(i.document,'$.discussion_token'),json_type(i.document,'$.discussion_token') FROM toolbox_article_inputs i JOIN toolbox_jobs j ON j.id=i.job_id WHERE j.work_id=? AND j.kind IN ('create','change') ORDER BY j.rowid DESC LIMIT 1",(wid,)).fetchone()
    previous=row[0] if row and row[1] is not None else hashlib.sha256(b'[]').hexdigest()
    return token!=previous


def drafts(c,box):
    active=','.join('?' for _ in ACTIVE);params=sorted(ACTIVE)
    tables={row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    media=" AND NOT EXISTS(SELECT 1 FROM media_jobs m WHERE m.work_id=w.id)" if 'media_jobs' in tables else ''
    rows=c.execute("""SELECT w.id,w.title,coalesce(o.format,'poster') AS format,d.revision,d.submitted_revision,
        EXISTS(SELECT 1 FROM toolbox_jobs j WHERE j.work_id=w.id AND j.status IN ("""+active+""")) AS busy,
        EXISTS(SELECT 1 FROM toolbox_jobs j WHERE j.work_id=w.id AND j.kind='discuss' AND j.status IN ("""+active+""")) AS discussing
        FROM toolbox_works w LEFT JOIN toolbox_article_drafts d ON d.work_id=w.id
        LEFT JOIN toolbox_work_options o ON o.work_id=w.id
        WHERE NOT EXISTS(SELECT 1 FROM toolbox_jobs j WHERE j.work_id=w.id AND j.kind IN ('accept','reject'))"""+media+"""
        AND (coalesce(d.revision,0)>0 OR EXISTS(SELECT 1 FROM toolbox_jobs j WHERE j.work_id=w.id AND j.kind='discuss' AND j.status IN ("""+active+"""))) ORDER BY w.updated_at DESC,w.id DESC""",params*3).fetchall()
    result=[]
    for row in rows:
        if not row['discussing'] and (row['busy'] or not row['revision'] or row['revision']==row['submitted_revision'] and not _changed_discussion(c,row['id'])):continue
        title=row['title']
        from easel_workbench.runtime.production_outcome import read as read_outcome,assess
        latest=None
        for job in c.execute("SELECT * FROM toolbox_jobs WHERE work_id=? AND kind IN ('create','change') AND status='completed' ORDER BY rowid DESC",(row['id'],)):
            recorded=read_outcome(c,job['id'])
            if recorded and recorded['status'] in ('blocked','error'):continue
            if assess(box,c,dict(job),summary=True)['status']=='completed':latest=job;break
        if latest:
            from easel_workbench.runtime.production_title import from_artifacts
            files=c.execute('SELECT name,path,mime FROM artifacts WHERE task_id=?',(latest['id'],)).fetchall()
            title=from_artifacts(files,Path(box.root)/'data/artifacts',row['format']) or title
            authored=c.execute("SELECT json_extract(document,'$.text.title') FROM toolbox_text_versions WHERE job_id=?",(latest['id'],)).fetchone()
            if authored and authored[0]:title=authored[0]
        result.append({'id':row['id'],'title':title})
    return result
