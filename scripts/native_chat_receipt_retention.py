"""Read-only validation of an individually reviewed, nonrunning unknown turn.

Retention never resolves the receipt, mutates a session, or authorizes replay.
Any changed or absent evidence fails closed; a bare ID list has no authority.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time

from easel.harnesses.store import binding_path
from easel.timeouts import TIMEOUT_CHAT

KIND='retained_nonrunning_native_chat_unknown'
GRACE_SECONDS=600


def _inside(root,relative):
    if not isinstance(relative,(str,Path)):raise ValueError('invalid path')
    value=Path(relative)
    if value.is_absolute() or value.drive or '..' in value.parts:raise ValueError('outside root')
    path=root
    for part in value.parts:
        path=path/part
        if path.is_symlink() or getattr(path,'is_junction',lambda:False)():raise ValueError('linked evidence')
    if not path.resolve().is_relative_to(root):raise ValueError('outside root')
    return path


def _bytes(path):
    if not path.is_file() or path.stat().st_size>4*1024*1024:raise ValueError('invalid evidence file')
    return path.read_bytes()


def _sha(raw):return hashlib.sha256(raw).hexdigest()


def _read(path):
    value=json.loads(_bytes(path))
    if not isinstance(value,dict):raise ValueError('evidence must be an object')
    return value


def _stamp(value):
    if not isinstance(value,str):raise ValueError('timestamp required')
    parsed=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    if parsed.tzinfo is None:raise ValueError('timezone required')
    return parsed.timestamp()


def _epoch(value):
    if type(value) not in (int,float) or not math.isfinite(value) or value<=0:raise ValueError('invalid epoch')
    return value


def _cwd(root,value):
    return isinstance(value,str) and bool(value) and Path(value).is_absolute() and Path(value).resolve()==root


def _evidence(root,descriptor):
    if not isinstance(descriptor,dict) or set(descriptor)!={'path','sha256'}:raise ValueError('missing evidence')
    if not isinstance(descriptor['path'],str) or not descriptor['path'].replace('\\','/').startswith('.local/'):
        raise ValueError('review evidence must be local')
    raw=_bytes(_inside(root,descriptor['path']))
    if _sha(raw)!=descriptor['sha256']:raise ValueError('evidence changed')
    return raw


def retained(root,turn_id,rawdocument):
    """Return exact retention metadata or None. No SQL/filesystem writes or RPC."""
    try:
        if not isinstance(turn_id,str) or not re.fullmatch('[A-Za-z0-9_-]{1,128}',turn_id):return None
        if not isinstance(rawdocument,str):return None
        root=Path(root).resolve()
        audit_path=_inside(root,'.local/workbench-deployment/native-chat-retentions/'+turn_id+'.json')
        audit=_read(audit_path)
        if set(audit)!={'schema_version','kind','turn_id','session_id','turn_document_sha256','session_document_sha256','binding','events','native_proof','retained_at'}:return None
        if type(audit['schema_version']) is not int or audit['schema_version']!=1 or audit['kind']!=KIND or audit['turn_id']!=turn_id:return None
        if audit['turn_document_sha256']!=_sha(rawdocument.encode('utf-8')):return None
        turn=json.loads(rawdocument)
        if not isinstance(turn,dict) or turn.get('id')!=turn_id or turn.get('status')!='unknown' or turn.get('runtime')!='codex':return None
        session_id=turn.get('session_id')
        if not isinstance(session_id,str) or not re.fullmatch('[A-Za-z0-9_-]{1,128}',session_id) or session_id!=audit['session_id']:return None
        if turn.get('hook_status')!='completed' or turn.get('pending_hooks') or any(value in ('pending','running') for key,value in turn.items() if key.endswith('hook_status')):return None
        if turn.get('work') is not None or turn.get('native_id') not in (None,'') or turn.get('native_turn_id') not in (None,'') or turn.get('execution_identity'):return None
        if turn.get('output')!='' or not _cwd(root,turn.get('cwd')):return None
        if turn.get('session_key',session_id)!=session_id:return None
        created=_stamp(turn['created_at']);reviewed=_stamp(audit['retained_at']);now=time.time()
        if created<=0 or reviewed>now+30 or now-created<=TIMEOUT_CHAT+GRACE_SECONDS or reviewed-created<=TIMEOUT_CHAT+GRACE_SECONDS:return None
        database=_inside(root,'data/desk.sqlite')
        with contextlib.closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True,timeout=.5)) as c:
            c.execute('PRAGMA query_only=ON')
            current=c.execute('SELECT document FROM easel_chat_turns WHERE id=?',(turn_id,)).fetchone()
            row=c.execute('SELECT document FROM easel_chat_sessions WHERE id=?',(session_id,)).fetchone()
        if not current or current[0]!=rawdocument or not row or _sha(row[0].encode('utf-8'))!=audit['session_document_sha256']:return None
        session=json.loads(row[0])
        if session.get('id')!=session_id or session.get('runtime')!='codex' or session.get('pendingTurnId')!=turn_id or session.get('pendingSubmissionId'):return None
        binding_file=binding_path(root/'outputs/_sessions',session_id)
        actual_binding=_read(_inside(root,binding_file.relative_to(root)))
        if actual_binding!=audit['binding'] or actual_binding.get('runtime')!='codex' or not isinstance(actual_binding.get('native_id'),str) or not re.fullmatch('[A-Za-z0-9_-]{1,128}',actual_binding['native_id']):return None
        events_raw=_evidence(root,audit['events'])
        if events_raw!=_bytes(_inside(root,'outputs/_sessions/jobs/'+turn_id+'.jsonl')):return None
        events=[json.loads(line) for line in events_raw.splitlines() if line.strip()]
        if len(events)<2 or any(not isinstance(event,dict) or type(event.get('id')) is not int or event['id']!=i+1 for i,event in enumerate(events)):return None
        done=events[-1]
        if done.get('event')!='done' or done.get('data')!={'sessionKey':session_id}:return None
        if any(event.get('event')!='activity' for event in events[:-1]):return None
        proof=json.loads(_evidence(root,audit['native_proof']))
        if not isinstance(proof,dict) or proof.get('read_only') is not True or type(proof.get('new_model_turns')) is not int or proof['new_model_turns']!=0 or proof.get('method')!='thread/read':return None
        if proof.get('turn_document_sha256')!=audit['turn_document_sha256'] or proof.get('binding')!=actual_binding or proof.get('thread_id')!=actual_binding['native_id']:return None
        if not _cwd(root,proof.get('cwd')) or proof.get('thread_status',{}).get('type') not in ('notLoaded','idle'):return None
        prompt=turn.get('actual_prompt');message=turn.get('message')
        if not isinstance(prompt,str) or not prompt or not isinstance(message,str) or not message:return None
        prompt_sha=_sha(prompt.encode('utf-8'))
        if turn.get('actual_prompt_sha256')!=prompt_sha:return None
        turns=proof.get('turns')
        if not isinstance(turns,list) or not turns:return None
        seen=set()
        for native in turns:
            if not isinstance(native,dict) or not isinstance(native.get('id'),str) or not native['id'] or native['id'] in seen:return None
            seen.add(native['id'])
            if native.get('status') not in ('completed','failed','interrupted','cancelled'):return None
            if not _epoch(native.get('startedAt'))<=_epoch(native.get('completedAt'))<created:return None
            digest=native.get('input_sha256')
            if not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest) or digest in (prompt_sha,_sha(message.encode('utf-8'))):return None
            if native.get('matches_exact_input') is not False or native.get('contains_exact_input') is not False:return None
        return {'kind':KIND,'turn_id':turn_id,'session_id':session_id,'audit_path':audit_path.relative_to(root).as_posix(),
                'audit_sha256':_sha(_bytes(audit_path)),'turn_document_sha256':audit['turn_document_sha256'],
                'session_document_sha256':audit['session_document_sha256'],'events_sha256':audit['events']['sha256'],
                'native_proof_sha256':audit['native_proof']['sha256'],'replayed':False,'retained_unknown':True}
    except (OSError,ValueError,TypeError,KeyError,AttributeError,sqlite3.Error,OverflowError):
        return None
