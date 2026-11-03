"""Bounded selectors; no production/version/body projection is performed here."""
import base64
import json

from easel_workbench.contracts.values import ident


FORMATS=('', 'poster','article','audio','video','music','image','transcript')


def read(box, *, limit=50, cursor='', profile_id='', format=''):
    if type(limit) is not int or not 1<=limit<=100:raise ValueError('每页数量需为 1 到 100')
    if format not in FORMATS:raise ValueError('制作类型无效')
    if profile_id:ident(profile_id)
    identity={'profile_id':profile_id,'format':format}
    after=None
    if cursor:
        try:
            if not isinstance(cursor,str) or len(cursor)>2048:raise ValueError()
            token=json.loads(base64.urlsafe_b64decode(cursor+'='*(-len(cursor)%4)))
            if token.get('identity')!=identity:raise ValueError()
            after=token['after']
            if not isinstance(after,list) or len(after)!=2 or any(not isinstance(v,str) or not v or len(v)>200 for v in after):raise ValueError()
        except Exception:raise ValueError('分页标识无效，请重新读取列表') from None
    # The newest accepted task snapshot determines work ownership, then the
    # immutable explicit owner, then the historical default. Large snapshot
    # documents stay in SQLite and are never decoded/copied by this reader.
    query="""WITH latest_run AS (
        SELECT work_id,max(rowid) AS rid FROM creator_task_runs GROUP BY work_id
    ), projected AS (
        SELECT w.id,w.title,w.updated_at,coalesce(o.format,'poster') AS format,
        CASE WHEN r.id IS NOT NULL THEN json_extract(r.document,'$.snapshot.profile.id')
             WHEN owner.work_id IS NOT NULL THEN owner.profile_id ELSE 'oil-pig' END AS creator_id,
        CASE WHEN r.id IS NOT NULL THEN json_extract(r.document,'$.snapshot.profile.name')
             WHEN owner.work_id IS NOT NULL THEN json_extract(owner.document,'$.profile.name') ELSE '油猪大侠' END AS creator_name,
        CASE WHEN r.id IS NOT NULL THEN json_extract(r.document,'$.snapshot.profile.revision')
             WHEN owner.work_id IS NOT NULL THEN owner.profile_revision ELSE NULL END AS creator_revision
        FROM toolbox_works w LEFT JOIN toolbox_work_options o ON o.work_id=w.id
        LEFT JOIN latest_run lr ON lr.work_id=w.id LEFT JOIN creator_task_runs r ON r.rowid=lr.rid
        LEFT JOIN creator_work_owners owner ON owner.work_id=w.id
    ) """
    where="(?='' OR format=?) AND (?='' OR creator_id=?)"
    args=[format,format,profile_id,profile_id]
    with box.store.connect() as c:
        c.execute('BEGIN')
        total=c.execute(query+'SELECT count(*) FROM projected WHERE '+where,args).fetchone()[0]
        if after:
            where+=' AND (updated_at<? OR (updated_at=? AND id<?))'
            args.extend((after[0],after[0],after[1]))
        rows=c.execute(query+'SELECT * FROM projected WHERE '+where+' ORDER BY updated_at DESC,id DESC LIMIT ?',(*args,limit+1)).fetchall()
    selected=rows[:limit]
    items=[{k:r[k] for k in ('id','title','format')}|{'creator':{'id':r['creator_id'],'name':r['creator_name'],'revision':r['creator_revision']}} for r in selected]
    next_cursor=None
    if selected and len(rows)>limit:
        last=selected[-1]
        next_cursor=base64.urlsafe_b64encode(json.dumps({'identity':identity,'after':[last['updated_at'],last['id']]},separators=(',',':')).encode()).decode().rstrip('=')
    return {'items':items,'next_cursor':next_cursor,'total':total}
