"""Evidence-indexed creative learning, with one canonical strategy document.

SQLite contains provenance, candidate proposals, queue receipts and immutable
execution snapshots. Only an explicit preview/confirm can change project policy.
Importing or constructing this service never starts a process or calls an AI.
"""
from __future__ import annotations

import base64
import contextlib
import copy
import datetime as dt
import difflib
import hashlib
import json
import mimetypes
import math
import os
from pathlib import Path
import re
import time
import threading
import uuid

from easel_workbench.runtime.feedback_ledger import locked

POLICY_PATH = '规范/创作策略.json'

CONDITIONS = {'format', 'channel', 'topic', 'work_id', 'version_id', 'purpose', 'content_type', 'visual_role', 'column'}

RELATIONSHIPS = ('different_conditions', 'composable', 'mutually_exclusive', 'insufficient_evidence')

TERMINAL = {'completed', 'failed', 'blocked', 'cancelled'}

TEXT_SUFFIXES = {'.md', '.json', '.txt', '.html', '.csv'}

MEDIA_SUFFIXES = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.pdf', '.mp4', '.webm', '.mp3'}

SECRET_NAME = re.compile(r'(?:^|[._-])(?:credentials?|secrets?|cookies?|tokens?|passwords?|\.env)(?:[._-]|$)', re.I)

SECRET_TEXT = re.compile(r'(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|session[_-]?cookie)[\"\']?\s*[=:]\s*[\"\']?[A-Za-z0-9_+/=-]{6,}|\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,})', re.I)

FORBIDDEN_PARTS = {'obsidian', 'llm-wiki', 'wiki', '.obsidian', '.git', '.runtime', 'node_modules', '__pycache__'}

def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

def sha(value):
    return hashlib.sha256(value).hexdigest()

def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def identity(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value):
        raise ValueError('学习记录标识无效')
    return value

def bounded(value, limit=10000, required=False):
    if not isinstance(value, str) or len(value) > limit or required and not value.strip():
        raise ValueError('学习内容为空或超过长度限制')
    if SECRET_TEXT.search(value):
        raise ValueError('不能将凭据或秘密写入学习记录')
    return value

def atomic_bytes(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()

def original_mime(path):
    guessed = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
    if not guessed.startswith('image/'):
        return guessed
    try:
        from PIL import Image
        with Image.open(path) as source:
            source.verify()
            return Image.MIME.get(source.format, 'application/octet-stream')
    except Exception:
        return 'application/octet-stream'

class LearningConflict(ValueError):
    pass
