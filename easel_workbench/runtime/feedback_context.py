"""Immediate, version-bound human inputs. No inference and no model calls."""
import hashlib
import json


def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def collect(connection, work_id, candidate_id=None, exclude_job_id=None):
    if not work_id:
        return {'revision': hashlib.sha256(b'[]').hexdigest(), 'items': [], 'last_decision': None}
    rows = [dict(row) for row in connection.execute(
        'SELECT rowid AS received_sequence,id,work_id,kind,text,candidate_id,scope,created_at '
        'FROM toolbox_jobs WHERE work_id=? ORDER BY rowid', (work_id,))]
    internal = set()
    if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='learning_correction_links'").fetchone():
        internal = {row[0] for row in connection.execute('SELECT child_job_id FROM learning_correction_links')}
    human = [row for row in rows if row['id'] != exclude_job_id and row['id'] not in internal
             and row['kind'] in ('create', 'change', 'feedback', 'accept', 'reject')]
    # Queue completion and model receipts do not change the human input revision.
    revision = hashlib.sha256(packed([row for row in human if row['kind']!='create']).encode()).hexdigest()
    decisions = [row for row in human if row['kind'] in ('accept', 'reject')]
    latest = decisions[-1] if decisions else None
    by_id = {row['id']: row for row in rows}
    ancestors, current = set(), candidate_id
    while current and current not in ancestors and current in by_id:
        ancestors.add(current)
        current = by_id[current]['candidate_id']
    if candidate_id and candidate_id not in by_id:
        # Direct pre-bind may refer only to a validated existing version; callers
        # own that validation. Never fall back to the globally newest work.
        ancestors.add(candidate_id)
    items = []
    for row in human:
        applies = (not candidate_id or row['id'] in ancestors or
                   row['kind'] in ('feedback', 'accept', 'reject') and row['candidate_id'] in ancestors)
        if not applies or not row['text'].strip():
            continue
        scope = json.loads(row['scope'] or '[]')
        items.append({
            'id': 'raw-' + row['id'], 'kind': 'raw_user_feedback', 'dimension': 'style',
            'text': row['text'], 'operation_id': row['id'], 'work_id': work_id,
            'version_id': row['candidate_id'] or row['id'], 'action_kind': row['kind'],
            'received_sequence': row['received_sequence'], 'created_at': row['created_at'],
            'scope': 'version_chain' if candidate_id else 'work_preview', 'approval_scope': scope,
            'state': 'recorded_uninterpreted', 'authority': 'human_original',
            'decision_history': row['kind'] in ('accept', 'reject') and (not latest or row['id'] != latest['id']),
            'is_current_decision': bool(latest and row['id'] == latest['id']),
            'source': {'kind': 'database', 'table': 'toolbox_jobs', 'record_id': row['id'], 'field': 'text'},
            'instructions': '原话尚未提炼。按作品、版本链和本轮指令判断适用性；历史决定不是通用偏好，采纳也不表示所有维度都好。未采用或发生分歧时说明原因。',
        })
    last_decision = None if not latest else {
        key: latest[key] for key in ('id', 'kind', 'candidate_id', 'received_sequence', 'created_at')}
    if last_decision is not None:
        last_decision.update(approval_scope=json.loads(latest['scope'] or '[]'), reason_provided=bool(latest['text'].strip()))
    return {'revision': revision, 'candidate_id': candidate_id, 'items': items,
            'last_decision': last_decision, 'interpretation': 'originals_not_long_term_rules'}
