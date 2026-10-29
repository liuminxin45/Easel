"""Frozen shared platform metadata, never proof of account access.

Release packaging copies the JSON at the same relative path. A packaged backend
does not fall back to mutable project-root configuration.
"""
from __future__ import annotations

import json
import pathlib
import re
from urllib.parse import urlsplit


CATALOG_PATH = pathlib.Path(__file__).resolve().parent / 'packages/core/src/distribution-platforms.json'
IDENTITY_KINDS = frozenset({'provider_user_id', 'reported_username'})
IDENTITY_STATUSES = frozenset({'resolved', 'not_provided', 'timeout', 'unavailable', 'unconfirmed'})


def plain_text(value):
    if not isinstance(value, str) or len(value) > 200:
        return None
    if any(ord(char) < 32 or 127 <= ord(char) <= 159 or '\u202a' <= char <= '\u202e' or '\u2066' <= char <= '\u2069' for char in value):
        return None
    if re.search(r'[<>]|[A-Za-z][A-Za-z0-9+.-]*://|^(?:javascript|data):', value, re.I):
        return None
    return value


def identity_metadata(row):
    """Optional observations only; old records acquire no invented fields."""
    result = {}
    name = plain_text(row.get('account_name'))
    if name and name.strip():
        result['account_name'] = name
    if isinstance(row.get('identity_kind'), str) and row['identity_kind'] in IDENTITY_KINDS:
        result['identity_kind'] = row['identity_kind']
    if isinstance(row.get('identity_status'), str) and row['identity_status'] in IDENTITY_STATUSES:
        result['identity_status'] = row['identity_status']
    return result


def load_catalog(path=CATALOG_PATH):
    value = json.loads(pathlib.Path(path).read_text(encoding='utf8'))
    if not isinstance(value, dict) or value.get('schema_version') != 1 or not isinstance(value.get('providers'), dict) or not isinstance(value.get('platforms'), list):
        raise ValueError('分发平台目录格式无效')
    providers, platforms, seen = value['providers'], value['platforms'], set()
    for key, provider in providers.items():
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', key) or not isinstance(provider, dict) or not plain_text(provider.get('name')):
            raise ValueError('分发平台提供方格式无效')
        if provider.get('identity_lookup') not in (None, 'checkAuth'):
            raise ValueError('分发平台身份查询格式无效')
        if provider.get('login_url') is not None:
            url = urlsplit(provider['login_url'])
            if url.scheme != 'https' or not url.hostname or '.' not in url.hostname or url.username or url.password or url.port or url.query or url.fragment:
                raise ValueError('分发平台固定登录入口无效')
    for platform in platforms:
        if not isinstance(platform, dict) or not isinstance(platform.get('id'), str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', platform['id']) or platform['id'] in seen:
            raise ValueError('分发内容类型格式无效')
        seen.add(platform['id'])
        if platform.get('provider') not in providers or not plain_text(platform.get('name')) or not isinstance(platform.get('channel_id'), str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', platform['channel_id']):
            raise ValueError('分发内容渠道格式无效')
        kinds = platform.get('content_kinds')
        if not isinstance(kinds, list) or not kinds or any(kind not in ('article', 'note', 'image_post','video','audio','music') for kind in kinds) or len(kinds) != len(set(kinds)) or type(platform.get('draft')) is not bool:
            raise ValueError('分发内容能力格式无效')
    by_id = {platform['id']: platform for platform in platforms}
    for key, provider in providers.items():
        default = provider.get('default_platform')
        if default is not None and (default not in by_id or by_id[default]['provider'] != key):
            raise ValueError('分发平台默认类型不匹配')
    return value


CATALOG = load_catalog()
PLATFORMS = tuple(CATALOG['platforms'])
PLATFORM_IDS = frozenset(row['id'] for row in PLATFORMS)
PROVIDERS = CATALOG['providers']
PROVIDER_NAMES = {key: row['name'] for key, row in PROVIDERS.items()}
IMPORTABLE_PROVIDERS = frozenset(key for key, row in PROVIDERS.items() if row.get('default_platform'))
SUPPORTED_DRAFTS = frozenset(row['id'] for row in PLATFORMS if row['draft'])
LOGIN_URLS = {row['id']: PROVIDERS[row['provider']]['login_url'] for row in PLATFORMS if PROVIDERS[row['provider']].get('login_url')}
