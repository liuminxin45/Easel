"""Creator identities and explicit, immutable capability releases.

This module performs local transactions only. A skill is a versioned instruction
and resource package; it is not a claim that a model or a publisher has run.
"""
from __future__ import annotations

import copy
import difflib
import hashlib
import io
import json
import mimetypes
import os
import pathlib
import re
import uuid
import warnings
import zipfile

from easel_workbench.runtime.desk import PROJECT, stamp
from easel_workbench.skills import (
    RETIRED_EASEL_SKILLS, RETIRED_TASKS, TASK_DEFAULTS, launch_metadata,
    require_selection, require_task, task_policy,
)

DEFAULT_PROFILE = 'oil-pig'

MANIFEST = '.agents/skills/capabilities.json'

MAX_PROMPT = 160000

MAX_RESOURCE = 40 * 1024 * 1024

class CreatorConflict(ValueError):
    """Concurrent edits or an operation identity with different content."""

def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode('utf-8')).hexdigest()

def key(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value):
        raise ValueError('记录标识无效')
    return value

def text(value, limit=MAX_PROMPT, required=False):
    if not isinstance(value, str) or len(value) > limit or '\x00' in value or required and not value.strip():
        raise ValueError('文字为空或超过长度限制')
    return value

def validate_package(release):
    """Deterministic publish gate; these checks do not judge content quality."""
    import yaml
    match = re.match(r'\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)', release.get('prompt', ''), re.S)
    if not match:
        raise ValueError('技能缺少完整的 YAML 名称与用途头部，请先保存为可调用技能格式')
    try:
        metadata = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        raise ValueError('技能头部格式无效，尚未发布') from None
    if not isinstance(metadata, dict) or set(metadata) - {'name', 'description', 'license', 'allowed-tools', 'metadata','layer'}:
        raise ValueError('技能头部只能包含支持的能力元信息')
    if 'layer' in metadata and metadata['layer'] not in ('discover','plan','produce','publish','attribute','general'):
        raise ValueError('项目技能分层无效')
    if release.get('entry','').startswith('skills/builtin/') and 'layer' not in metadata:
        raise ValueError('Easel 项目内置技能须保留分层元信息')
    name = metadata.get('name')
    description = metadata.get('description')
    if not isinstance(name, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name) or len(name) > 64:
        raise ValueError('技能名称需要64字以内的小写英文标识')
    if name != pathlib.PurePosixPath(release['entry']).parent.name:
        raise ValueError('修订须保留此技能的稳定名称；新能力不能覆盖另一个技能身份')
    if not isinstance(description, str) or not description.strip() or len(description) > 1024 or '<' in description or '>' in description:
        raise ValueError('技能需要明确、完整的用途说明')
    if not release['prompt'][match.end():].strip() or re.search(r'^\s*\[TODO:[^\n]*\]\s*$', release['prompt'][match.end():], re.M):
        raise ValueError('技能正文为空或仍有待填写占位')
    for field in ('input_contract', 'output_contract'):
        contract = release.get(field)
        if not isinstance(contract, dict) or not isinstance(contract.get('required'), list) or not contract['required'] or any(not isinstance(item, str) or not item for item in contract['required']):
            raise ValueError('技能缺少明确的输入输出合同')
    return {'status': 'passed', 'checks': ['skill_metadata', 'nonempty_instructions', 'input_contract', 'output_contract'],
            'semantic_cases': 'not_run', 'notice': '程序格式检查不代表审美、事实或效果验收。'}
