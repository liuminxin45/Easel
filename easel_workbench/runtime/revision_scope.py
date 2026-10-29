"""Per-round text boundaries and deterministic, narrow conflict checks. No AI."""
import re

CONFLICT_CODES={'FROZEN_TEXT_SCOPE_CONFLICT','TEXT_SCOPE_CONFLICT'}
LABELS={'title':'标题','body':'配文／正文'}

def is_scope_conflict(value):
    return isinstance(value,dict) and value.get('code') in CONFLICT_CODES

def can_continue_partial(c,job):
    if not job or job['status']!='blocked' or not job['finished_at']:return False
    row=c.execute('SELECT document FROM toolbox_production_outcomes WHERE job_id=?',(job['id'],)).fetchone()
    if not row:return False
    import json
    return is_scope_conflict(json.loads(row[0])) and bool(c.execute('SELECT 1 FROM artifacts WHERE task_id=?',(job['id'],)).fetchone())

def scope_summary(creation):
    policy=creation.get('text_policy')
    return [{'field':key,'label':LABELS[key],'mode':('preserve' if creation.get('target')=='images' else policy.get(key,'follow_request')) if policy is not None else ('preserve' if key in creation.get('text',{}) or creation.get('target')=='images' else 'follow_request')} for key in LABELS]

def conflicts(creation,request):
    """Flag explicit edit requests against frozen text, never infer consent."""
    if not isinstance(request,str) or not request.strip():return []
    locked={row['field'] for row in scope_summary(creation) if row['mode']=='preserve'}
    found=set()
    verbs=r'(?:修改|调整|改写|重写|优化|润色|重做|改一下|改一改|改成|改为)'
    for clause in re.split(r'[，,。；;！!？?\n]',request):
        for field,names in [('title',r'(?:标题|题目)'),('body',r'(?:配文|正文|文案)')]:
            if field not in locked:continue
            # Negated edits and explicit preservation are not positive requests.
            if re.search(r'(?:不要|不用|不必|无需|不需要|别|不能|禁止|不再|不想).{0,10}'+verbs+r'.{0,10}'+names,clause):continue
            if re.search(names+r'.{0,8}(?:不要|不用|不必|无需|不需要|不能|不再|不想|不改)',clause):continue
            if re.search(r'(?:保留|保持).{0,8}'+names+r'(?:原样|原文|不变|不动)?',clause):continue
            if re.search(names+r'.{0,12}'+verbs,clause) or re.search(verbs+r'.{0,12}'+names,clause):found.add(field)
    return [{'code':'TEXT_SCOPE_CONFLICT','field':key,'message':LABELS[key]+'已选择保留原文，但修改意见明确要求调整。请将这一项改为“按修改意见”，或调整意见。'} for key in LABELS if key in found]
