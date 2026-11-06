"""Read an exact Codex terminal receipt; no RPC, resume, interrupt or model execution.

The bounded rollout tail is evidence only. Missing/truncated evidence stays unknown.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3

UUID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
TAIL_BYTES = 4 * 1024 * 1024


def terminal(home, turn):
    thread, native_turn = turn.get('native_id'), turn.get('native_turn_id')
    if turn.get('runtime') != 'codex' or not isinstance(thread,str) or not isinstance(native_turn,str) or not UUID.fullmatch(thread) or not UUID.fullmatch(native_turn):
        return None
    home = Path(home).resolve()
    database = home / 'state_5.sqlite'
    if not database.is_file(): return None
    try:
        with closing(sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True,timeout=1)) as c:
            row = c.execute('SELECT rollout_path FROM threads WHERE id=?',(thread,)).fetchone()
        if not row: return None
        path = Path(row[0]).resolve(strict=True)
        if not path.is_relative_to(home/'sessions') or not path.is_file(): return None
        with path.open('rb') as stream:
            first = stream.readline(65536)
            meta = json.loads(first)
            if not isinstance(meta,dict) or not isinstance(meta.get('payload'),dict) or meta.get('type') != 'session_meta' or meta['payload'].get('id') != thread: return None
            if Path(meta['payload'].get('cwd','')).resolve() != Path(turn['cwd']).resolve(): return None
            size = stream.seek(0,2)
            offset = max(0,size-TAIL_BYTES)
            stream.seek(offset)
            if offset: stream.readline()  # An incomplete prefix cannot become evidence.
            raw = stream.read(TAIL_BYTES)
        found = None
        for line in raw.splitlines(keepends=True):
            if not line.endswith(b'\n'): continue  # Writer may still be appending.
            try: event = json.loads(line)
            except (ValueError,UnicodeError): continue
            if not isinstance(event,dict): continue
            payload = event.get('payload',{})
            if not isinstance(payload,dict) or event.get('type')!='event_msg' or payload.get('turn_id')!=native_turn: continue
            kind = payload.get('type')
            if kind not in ('task_complete','turn_aborted'): continue
            # A completion without a final message may follow cancellation;
            # it cannot overwrite a proven interruption or manufacture success.
            reply = payload.get('last_agent_message')
            if kind=='task_complete' and (not isinstance(reply,str) or not reply.strip()): continue
            status = 'completed' if kind=='task_complete' else 'stopped'
            candidate={'status':status,'output':reply if status=='completed' else None,
                       'evidence':{'kind':'codex_rollout','native_id':thread,'native_turn_id':native_turn,
                                   'status':status,'sha256':hashlib.sha256(line).hexdigest()}}
            if found and found['status']!=status: return None  # Conflicting evidence is unresolved.
            found=candidate
        return found
    except (OSError,ValueError,KeyError,TypeError,sqlite3.Error):
        return None
