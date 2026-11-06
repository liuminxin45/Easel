"""Reviewed retirement of a legacy unknown turn during an identity-fenced upgrade.

Only an exact reviewed row can pass the pre-stop gate. No result is invented;
the original native binding and unknown outcome remain available for audit.
"""
from __future__ import annotations

import contextlib
import json
from pathlib import Path
import sqlite3

from .receipts import sha, now


def eligible(plan, identifier, raw):
    value = json.loads(raw)
    return (identifier == plan.get('turn_id') and sha(raw.encode()) == plan.get('turn_sha256')
            and value.get('status') == 'unknown' and value.get('runtime') == 'codex'
            and value.get('stop_requested') is True and value.get('hook_status') != 'pending'
            and value.get('start_hook_status') != 'pending')


def retired(turn):
    receipt = turn.get('controlled_retirement') or {}
    proof = receipt.get('process_exit') or {}
    return bool(turn.get('id') and receipt.get('turn_id') == turn['id'] and receipt.get('outcome') == 'unknown'
            and receipt.get('replayed') is False and proof.get('exited') is True
            and proof.get('source') == 'identity_fenced_profile_retirement'
            and bool(proof.get('processes')) and receipt.get('plan_sha256')
            and receipt.get('native_session_key') == turn.get('native_session_key', turn.get('session_id')))


def _rows(root):
    return sqlite3.connect((Path(root)/'data/desk.sqlite').resolve().as_uri()+'?mode=ro', uri=True, timeout=3)


def preview(root, turn_id, *, inventory=None):
    root = Path(root)
    with contextlib.closing(_rows(root)) as c:
        row = c.execute('SELECT document FROM easel_chat_turns WHERE id=?', (turn_id,)).fetchone()
        if not row:raise ValueError('Unknown chat turn')
        turn = json.loads(row[0])
        plan = {'schema': 1, 'turn_id': turn_id, 'turn_sha256': sha(row[0].encode())}
        if not eligible(plan, turn_id, row[0]):raise ValueError('Only a finalized stopped legacy unknown is eligible')
        session_raw = c.execute('SELECT document FROM easel_chat_sessions WHERE id=?', (turn['session_id'],)).fetchone()[0]
        session = json.loads(session_raw)
        if session.get('pendingTurnId') != turn_id:raise ValueError('Pending turn changed')
    key = turn.get('native_session_key', turn['session_id'])
    from easel.harnesses import store
    binding = store.binding(root/'outputs/_sessions', key)
    if binding.get('native_id') != turn.get('native_id') or binding.get('runtime') != 'codex':
        raise ValueError('Original native binding changed')
    owner = json.loads((root/'.local/workbench-deployment/pids.json').read_text(encoding='utf-8'))
    if inventory is None:
        from easel_workbench.processes import rows
        inventory = rows()
    owners = []
    for pid in (owner['manager'], owner['roles']['server']):
        row = inventory[pid]
        owners.append({'pid': pid, 'creation_ticks': str(row['creation_ticks']),
                       'command_sha256': sha(row['command'].encode())})
    plan.update(session_id=turn['session_id'], session_sha256=sha(session_raw.encode()),
                native_session_key=key, native_binding=binding, owners=owners,
                base_runtime=json.loads((root/'data/active-workbench.json').read_text(encoding='utf-8')))
    plan['plan_sha256'] = sha(plan)
    return plan


def apply(root, plan, proof):
    """Run after exact profile shutdown and before admitting the new runtime."""
    root = Path(root)
    if proof.get('source') != 'identity_fenced_profile_retirement' or proof.get('exited') is not True:
        raise ValueError('Exact process exit proof is required')
    for expected in plan['owners']:
        if not any(item['pid'] == expected['pid'] and int(item['creation_ticks'])//10 == int(expected['creation_ticks'])//10
                   and item.get('command_sha256')==expected['command_sha256']
                   for item in proof.get('processes', [])):
            raise ValueError('Reviewed owner was not retired')
    from easel.harnesses import store
    if store.binding(root/'outputs/_sessions', plan['native_session_key']) != plan['native_binding']:
        raise ValueError('Native binding changed after review')
    with sqlite3.connect(root/'data/desk.sqlite', timeout=3) as c:
        c.execute('BEGIN IMMEDIATE')
        raw = c.execute('SELECT document FROM easel_chat_turns WHERE id=?', (plan['turn_id'],)).fetchone()[0]
        session_raw = c.execute('SELECT document FROM easel_chat_sessions WHERE id=?', (plan['session_id'],)).fetchone()[0]
        if not eligible(plan,plan['turn_id'],raw) or sha(session_raw.encode()) != plan['session_sha256']:
            raise ValueError('Original chat changed after review')
        turn, session = json.loads(raw), json.loads(session_raw)
        turn['controlled_retirement'] = {'turn_id': turn['id'], 'plan_sha256': plan['plan_sha256'],
            'native_session_key': plan['native_session_key'], 'process_exit': proof, 'observed_at': now(),
            'outcome': 'unknown', 'replayed': False}
        from .local_execution import release
        if not release(session, turn):raise ValueError('Execution generation changed')
        c.execute('UPDATE easel_chat_turns SET document=? WHERE id=?', (json.dumps(turn,ensure_ascii=False),turn['id']))
        c.execute('UPDATE easel_chat_sessions SET document=? WHERE id=?', (json.dumps(session,ensure_ascii=False),session['id']))
    return {'turn_id':turn['id'],'outcome':'unknown','pending_released':True,'replayed':False,
            'native_session_key':session['native_session_key'],'plan_sha256':plan['plan_sha256']}
