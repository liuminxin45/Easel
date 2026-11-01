"""Existing record validation and JSON bytes, independent of storage services."""
import json
import re


def pack(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def ident(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value):
        raise ValueError('记录标识无效')
    return value


def text(value, limit, required=False):
    if not isinstance(value, str) or len(value) > limit or required and not value.strip():
        raise ValueError('内容为空或超过长度限制')
    return value
