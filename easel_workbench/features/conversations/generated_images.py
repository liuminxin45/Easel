"""Receive Codex image-generation results using the exact native turn receipt."""
from __future__ import annotations

import base64
import binascii
import hashlib
from contextlib import closing
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3

from easel_workbench.paths import owned_output_path

LINK = re.compile(r'\[([^\]\n]+)\]\((<?)([^)\n]+?)(>?)\)')
UUID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
NAME = re.compile(r'^exec-[0-9a-f-]{36}\.png$')


def _home():
    return Path(os.environ.get('CODEX_HOME') or Path.home()/'.codex').resolve()


def _candidate(value, home, thread):
    try:
        path = Path(value).resolve(strict=True)
        folder = (home/'generated_images'/thread).resolve(strict=True)
        if not folder.is_relative_to(home/'generated_images') or path.parent != folder or not NAME.fullmatch(path.name) or not path.is_file():
            return None
        with path.open('rb') as stream: signature = stream.read(8)
        if path.stat().st_size > 64*1024*1024 or signature != b'\x89PNG\r\n\x1a\n':
            return None
        return path
    except (OSError, ValueError):
        return None


def _receipt(home, thread, native_turn):
    """Return only paths recorded in completed image-generation events for this turn."""
    db = home/'state_5.sqlite'
    if not db.is_file(): return {}
    with closing(sqlite3.connect(db.resolve().as_uri()+'?mode=ro', uri=True)) as c:
        row = c.execute('SELECT rollout_path FROM threads WHERE id=?', (thread,)).fetchone()
    if not row: return {}
    rollout = Path(row[0]).resolve()
    if not rollout.is_relative_to((home/'sessions').resolve()) or not rollout.is_file(): return {}
    found = {}
    with rollout.open(encoding='utf-8') as stream:
        for line in stream:
            if 'image_gen.generation' not in line or native_turn not in line: continue
            try: payload = json.loads(line).get('payload', {})
            except ValueError: continue
            item = payload.get('item') or {}
            if (payload.get('type') == 'item_completed' and payload.get('thread_id') == thread
                    and payload.get('turn_id') == native_turn and item.get('kind') == 'image_gen.generation'
                    and item.get('status') == 'completed'):
                path = _candidate(item.get('savedPath', ''), home, thread)
                result = item.get('result')
                if path and item.get('id') == path.stem and isinstance(result,str) and len(result) <= 90*1024*1024:
                    try: image = base64.b64decode(result,validate=True)
                    except (ValueError,binascii.Error): continue
                    found[path] = hashlib.sha256(image).hexdigest()
    return found


def receive(root, store, turn, *, home=None):
    if turn.get('runtime') != 'codex' or turn.get('status') != 'completed': return 0
    thread, native_turn = turn.get('native_id', ''), turn.get('native_turn_id', '')
    if not UUID.fullmatch(thread) or not UUID.fullmatch(native_turn): return 0
    output = turn.get('output', '')
    if 'generated_images' not in output: return 0
    home = Path(home).resolve() if home else _home()
    mentioned = {}
    for match in LINK.finditer(output):
        path = _candidate(match.group(3), home, thread)
        if path: mentioned[path] = match.group(3)
    if not mentioned: return 0
    verified = _receipt(home, thread, native_turn)
    count = 0
    for source in mentioned.keys() & verified.keys():
        data = source.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        if sha != verified[source]: continue
        target = owned_output_path(root, Path('outputs')/turn['session_id']/turn['id']/'products'/source.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != sha:
            raise ValueError('已接收的原生产物内容不一致')
        if not target.exists():
            with target.open('xb') as stream: stream.write(data)
        artifact_id = hashlib.sha256((turn['id']+'\0'+source.name+'\0'+sha).encode()).hexdigest()
        stored = Path(root)/'data/artifacts'/artifact_id/source.name
        stored.parent.mkdir(parents=True, exist_ok=True)
        if not stored.exists(): shutil.copy2(target, stored)
        if hashlib.sha256(stored.read_bytes()).hexdigest() != sha: raise ValueError('产物副本校验失败')
        with store.connect() as c:
            c.execute('CREATE TABLE IF NOT EXISTS easel_generated_image_sources (turn_id TEXT NOT NULL, source TEXT NOT NULL, artifact_id TEXT NOT NULL, sha256 TEXT NOT NULL, PRIMARY KEY(turn_id,source))')
            prior = c.execute('SELECT artifact_id,sha256 FROM easel_generated_image_sources WHERE turn_id=? AND source=?',(turn['id'], mentioned[source])).fetchone()
            if prior and tuple(prior) != (artifact_id,sha): raise ValueError('回合产物来源已变化')
            c.execute('INSERT OR IGNORE INTO artifacts VALUES(?,?,?,?,?)',(artifact_id,turn['id'],source.name,str(stored),'image/png'))
            c.execute('INSERT OR IGNORE INTO easel_generated_image_sources VALUES(?,?,?,?)',(turn['id'],mentioned[source],artifact_id,sha))
        count += 1
    return count


def display(content, mappings):
    """Project local image links without changing stored assistant text."""
    def replace(match):
        target = match.group(3)
        normalized = target.replace('\\','/')
        if '/generated_images/' not in normalized or not (normalized.startswith('/') or re.match(r'^[A-Za-z]:/',normalized)):
            return match.group(0)
        artifact = mappings.get(target)
        return '['+match.group(1)+'](/api/files/'+artifact+')' if artifact else match.group(1)+'（图片暂不可用）'
    return LINK.sub(replace, content)
