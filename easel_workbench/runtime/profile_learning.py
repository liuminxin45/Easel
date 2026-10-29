"""Evidence-backed profile suggestions, independent from skill candidates."""
import copy
import difflib
import json

from easel_workbench.runtime.desk import stamp
from easel_workbench.runtime.creator_runtime import CreatorConflict, key, text, digest, packed

FIELDS = {'identity': '作者身份', 'audience': '目标读者', 'voice': '表达偏好', 'boundaries': '边界'}


def propose(runtime, c, payload, result, task_id):
    changes = result.get('profile_changes', [])
    if not isinstance(changes, list) or len(changes) > 4:
        raise ValueError('画像候选字段无效')
    if not changes:
        return None
    ids = {m['id'] for m in payload['members']}
    profile = payload['creator_snapshot']['profile']
    fields, before, reasons = {}, {}, {}
    evidence = set()
    for change in changes:
        if not isinstance(change, dict) or set(change) != {'field', 'value', 'reason', 'evidence_refs'}:
            raise ValueError('画像候选需要原始依据和完整字段')
        field = change['field']
        if field not in FIELDS or field in fields:
            raise ValueError('画像候选只能修改身份、读者、表达或边界')
        refs = change['evidence_refs']
        if not isinstance(refs, list) or not refs or len(set(refs)) != len(refs) or not set(refs) <= ids:
            raise ValueError('画像候选必须引用本轮真实依据')
        fields[field] = text(change['value'], 12000, True)
        before[field] = profile.get(field, '')
        reasons[field] = text(change['reason'], 12000, True)
        evidence.update(refs)
    identity = 'profile-proposal-' + digest(packed({'task_id': task_id, 'changes': changes}))[:24]
    document = {'id': identity, 'profile_id': profile['id'], 'base_revision': profile['revision'], 'task_id': task_id,
                'status': 'candidate', 'fields': fields, 'before': before, 'reasons': reasons, 'evidence_refs': sorted(evidence),
                'source_members': [copy.deepcopy(m) for m in payload['members'] if m['id'] in evidence], 'created_at': stamp(),
                'diff': {f: ''.join(difflib.unified_diff(before[f].splitlines(True), fields[f].splitlines(True), fromfile='修改前', tofile='候选')) for f in fields}}
    c.execute('INSERT OR IGNORE INTO creator_profile_proposals VALUES(?,?)', (identity, packed(document)))
    return identity


def get(c, identity):
    row = c.execute('SELECT document FROM creator_profile_proposals WHERE id=?', (key(identity),)).fetchone()
    if not row:
        raise ValueError('画像候选不存在')
    return json.loads(row['document'])


def confirm(runtime, c, value, revert=False):
    proposal = get(c, value.get('proposal_id'))
    if value.get('confirm') is not True:
        raise ValueError('请明确确认画像字段与适用范围')
    profile = runtime._profile(c, proposal['profile_id'])
    expected = proposal.get('applied_revision') if revert else proposal['base_revision']
    if profile['revision'] != expected or value.get('base_revision') != expected:
        raise CreatorConflict('画像已有其他修订，请重新核对候选差异')
    if proposal['status'] != ('applied' if revert else 'candidate'):
        raise CreatorConflict('画像候选的处理状态已经变化')
    selected = proposal.get('selected_fields', []) if revert else value.get('fields')
    if not isinstance(selected, list) or not selected or len(set(selected)) != len(selected) or not set(selected) <= set(proposal['fields']):
        raise ValueError('请选择本次确认的画像字段')
    document = {f: proposal['before'][f] if revert else proposal['fields'][f] for f in selected}
    result = runtime._save_profile(c, {'id': value['id'], 'profile_id': profile['id'], 'base_revision': expected, 'document': document})
    proposal.update(status='reverted' if revert else 'applied', selected_fields=selected, applied_revision=result['profile']['revision'], confirmed_at=stamp())
    c.execute('UPDATE creator_profile_proposals SET document=? WHERE id=?', (packed(proposal), proposal['id']))
    return {**result, 'proposal': proposal}
