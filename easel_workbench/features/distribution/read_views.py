"""Metadata-only SQL projections; exact records stay behind explicit detail reads."""
import json


PUBLICATION_FIELDS=('id','revision','work_id','version_id','title','account','channel_id','status','url',
    'published_at','created_at','updated_at','registration_kind','publication_verification','remote_id')
FIELDS={
    'connections':('id','platform','account','label','enabled','revision','created_at','updated_at'),
    'revisions':('id','hash','work_id','version_id','publication_id','connection_id','connection_revision','platform','account','content_kind','title','created_at'),
    'approvals':('id','revision_id','revision_hash','batch_id','connection_id','account','platform','action','schedule_at','pilot','approved_at','actor'),
    'deliveries':('id','approval_id','batch_id','revision_id','publication_id','work_id','connection_id','account','platform','action','schedule_at','pilot','status','remote_state','verified','created_at','updated_at','error','blocked_reason'),
    'attempts':('id','delivery_id','status','phase','created_at','updated_at','finished_at','error'),
    'batches':('id','status','approved_at','actor','created_at'),
    'runners':('id','state','last_seen_at'),
}


def expression(fields):
    # Every field is a module-owned constant, never a request-controlled SQL name.
    return 'json_object('+','.join("'"+field+"',json_extract(document,'$."+field+"')" for field in fields)+')'


def publications(c,*,work_id=None):
    where="category='publications'";args=[]
    if work_id is not None:where+=" AND json_extract(document,'$.work_id')=?";args.append(work_id)
    sql='SELECT '+expression(PUBLICATION_FIELDS)+" AS summary,json_type(document,'$.registration_kind') AS registration_type,json_type(document,'$.publication_verification') AS verification_type,json_extract(document,'$.distribution_receipt.verified') AS verified,json_extract(document,'$.distribution_receipt.safe_url') AS safe_url FROM studio_records WHERE "+where+' ORDER BY created_at,rowid'
    result=[]
    for row in c.execute(sql,args):
        value=json.loads(row['summary']);value['distribution_receipt']={'verified':row['verified']==1,'safe_url':row['safe_url']}
        if row['registration_type'] is None:value.pop('registration_kind',None)
        if row['verification_type'] is None:value.pop('publication_verification',None)
        result.append(value)
    return result


def records(c,kind,*,work_id=None):
    fields=FIELDS[kind];where='1';args=[]
    if work_id is not None:
        direct="json_extract(document,'$.work_id')=?"
        if kind in ('revisions','deliveries'):where=direct
        elif kind=='approvals':where="json_extract(document,'$.revision_id') IN (SELECT id FROM distribution_revisions WHERE "+direct+')'
        elif kind=='attempts':where="json_extract(document,'$.delivery_id') IN (SELECT id FROM distribution_deliveries WHERE "+direct+')'
        elif kind=='batches':where="EXISTS(SELECT 1 FROM json_each(distribution_batches.document,'$.approval_ids') a JOIN distribution_approvals p ON p.id=a.value JOIN distribution_revisions r ON r.id=json_extract(p.document,'$.revision_id') WHERE json_extract(r.document,'$.work_id')=?)"
        if kind not in ('connections','runners'):args.append(work_id)
    extras=",json_type(document,'$.enabled') AS enabled_type,json_extract(document,'$.secret_ref') IS NOT NULL AND json_extract(document,'$.secret_ref')!='' AS configured" if kind=='connections' else ",coalesce(json_array_length(document,'$.approval_ids'),0) AS approval_count" if kind=='batches' else ''
    result=[]
    for row in c.execute('SELECT '+expression(fields)+' AS summary'+extras+' FROM distribution_'+kind+' WHERE '+where+' ORDER BY rowid',args):
        item=json.loads(row['summary'])
        for field in ('pilot','verified'):
            if type(item.get(field)) is int:item[field]=bool(item[field])
        if kind=='connections':item['enabled']=True if row['enabled_type'] is None else bool(item['enabled']);item['secret_configured']=bool(row['configured'])
        if kind=='batches':item['approval_count']=row['approval_count']
        result.append(item)
    return result
