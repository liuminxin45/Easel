"""Read-only authority for a new version after a proven native interruption.

This never clears a dispatch marker, retries a job, imports partial output or
opens a model connection. The original native read receipt remains authoritative.
"""
from __future__ import annotations

import hashlib
import json
import re


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def continuation(connection,job):
    if connection is None or not job:return None
    job=dict(job)
    if job.get('kind') not in ('create','change') or job.get('status')!='error' or not job.get('finished_at') or not job.get('dispatch_started'):return None
    tables={row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {'easel_chat_turns','easel_chat_sessions','easel_native_receipt_reconciliations','toolbox_review_inputs','toolbox_production_outcomes'}.issubset(tables):return None
    row=connection.execute('SELECT document FROM easel_chat_turns WHERE id=?',(job['id'],)).fetchone()
    if not row:return None
    turn=json.loads(row[0]);work=turn.get('work') or {};reference=turn.get('native_receipt_reconciliation') or {}
    if (turn.get('status')!='stopped' or turn.get('delivery_state')!='interrupted' or turn.get('interrupt_confirmed') is not True
        or turn.get('hook_status')!='completed' or work.get('work_id')!=job['work_id'] or work.get('version_id')!=job['id']
        or job.get('turn_id')!=turn.get('native_turn_id')):return None
    row=connection.execute('SELECT document FROM easel_native_receipt_reconciliations WHERE turn_id=?',(job['id'],)).fetchone()
    if not row:return None
    journal=json.loads(row[0]);proof=journal.get('native_proof') or {}
    if (journal.get('turn_id')!=job['id'] or journal.get('status')!='native_interruption_reconciled'
        or any(journal.get(key) is not False for key in ('replayed','completed','delivered'))
        or proof.get('method')!='thread/read' or proof.get('read_only') is not True or proof.get('new_model_turns')!=0
        or (proof.get('thread') or {}).get('id')!=turn.get('native_id')
        or (proof.get('turn') or {}).get('id')!=turn.get('native_turn_id')
        or (proof.get('turn') or {}).get('status')!='interrupted'
        or reference.get('kind')!='native_thread_read' or reference.get('native_status')!='interrupted'
        or reference.get('sha256')!=hashlib.sha256(canonical(proof).encode()).hexdigest()):return None
    row=connection.execute('SELECT document FROM toolbox_production_outcomes WHERE job_id=?',(job['id'],)).fetchone()
    outcome=json.loads(row[0]) if row else {}
    if outcome.get('code')!='native_interrupted' or outcome.get('native_receipt_reconciliation')!=reference:return None
    row=connection.execute('SELECT document FROM easel_chat_sessions WHERE id=?',(turn.get('session_id'),)).fetchone()
    session=json.loads(row[0]) if row else {}
    if not session or session.get('pendingTurnId') or session.get('sessionKey',session.get('id'))!=turn.get('session_key'):return None
    if connection.execute("SELECT 1 FROM toolbox_jobs WHERE work_id=? AND status IN ('queued','dispatching','running','uncertain','needs_desktop','parked') LIMIT 1",(job['work_id'],)).fetchone():return None
    row=connection.execute('SELECT document FROM toolbox_review_inputs WHERE job_id=?',(job['id'],)).fetchone()
    snapshot=(json.loads(row[0]).get('creator_snapshot') or {}) if row else {}
    if not snapshot or snapshot!=turn.get('snapshot'):return None
    root=next((skill for skill in snapshot.get('skills',[]) if skill.get('id')=='content-production'),{})
    version=root.get('version')
    if type(version) is not int or version<1 or any('change' not in skill.get('tasks',[]) for skill in snapshot.get('skills',[])):return None
    values={'session_id':turn['session_id'],'work_id':job['work_id'],'version_id':job['id'],'skill_id':'content-production',
            'skill_version':version,'profile_id':snapshot['profile']['id']}
    if any(not re.fullmatch(r'[A-Za-z0-9_-]{1,200}',values[key]) for key in ('session_id','work_id','version_id','profile_id')):return None
    return values
