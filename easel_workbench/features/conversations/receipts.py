"""Existing chat identities, serialization and receipt states; byte-compatible."""
import hashlib
import json
import re

TERMINAL = frozenset(('completed', 'stopped', 'failed', 'unknown'))


class ChatConflict(ValueError):
    pass


def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else packed(value).encode('utf-8')).hexdigest()


def identity(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', value):
        raise ValueError('对话标识无效')
    return value


def text(value, limit, required=False):
    if not isinstance(value, str) or len(value) > limit or '\x00' in value or required and not value.strip():
        raise ValueError('对话文字为空或过长')
    return value


def now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
