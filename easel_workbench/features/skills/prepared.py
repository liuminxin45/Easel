"""Validate already accepted snapshot identities without resolving current defaults."""
import copy
import hashlib
import json

def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else packed(value).encode()).hexdigest()

def validated_snapshot(snapshot, task, selection=None):
    """Internal prepared context: verify identity without resolving it again.

    HTTP payloads cannot supply this argument. An accepted operation may retain
    a candidate trial after the same version has subsequently been published.
    """
    if not isinstance(snapshot,dict) or snapshot.get('task')!=task:
        raise ValueError('冻结执行上下文与本次任务不一致')
    expected=snapshot.get('snapshot_sha256')
    if not isinstance(expected,str) or digest({k:v for k,v in snapshot.items() if k!='snapshot_sha256'})!=expected:
        raise ValueError('冻结执行上下文字节已变化')
    selection=selection or {}
    if selection.get('profile_id',snapshot['profile']['id'])!=snapshot['profile']['id']:
        raise ValueError('冻结执行画像不一致')
    if selection.get('profile_revision',snapshot['profile']['revision'])!=snapshot['profile']['revision']:
        raise ValueError('冻结执行画像修订不一致')
    refs=selection.get('skills')
    if refs is not None and refs!=[{'id':r['id'],'version':r['version']} for r in snapshot['skills']]:
        raise ValueError('冻结执行技能版本不一致')
    if 'trial' in selection and selection['trial'] is not snapshot.get('trial',False):
        raise ValueError('冻结执行试用身份不一致')
    return copy.deepcopy(snapshot)
