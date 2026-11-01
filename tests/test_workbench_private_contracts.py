"""Stable validation/serialization and protocol boundaries after P1 extraction."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from easel_workbench.contracts import legacy_jobs, media_paths, values


def test_historical_exports_are_the_same_objects():
    from easel_workbench.runtime import native_api, toolbox_store
    for name in ('ident', 'text', 'pack'):
        assert getattr(toolbox_store, name) is getattr(values, name)
    for name in ('ACTIVE', 'KINDS'):
        assert getattr(toolbox_store, name) is getattr(legacy_jobs, name)
    for name in ('HOST_DISPLAY_IMAGE', 'HOST_MEDIA_JOB', 'HOST_ACCOUNT_QR', 'is_host_media_protocol'):
        assert getattr(native_api, name) is getattr(media_paths, name)


@pytest.mark.parametrize('bad', [None, True, 1, b'id', '', 'a' * 129, 'a/b', 'id\n', '中文'])
def test_record_identity_rejects_the_same_invalid_inputs(bad):
    with pytest.raises(ValueError, match='^记录标识无效$'):
        values.ident(bad)


def test_values_keep_exact_unicode_and_canonical_json_bytes():
    identifier = 'A_z-9' + 'a' * 123
    assert len(identifier) == 128 and values.ident(identifier) is identifier
    original = '  原字\r\n '
    assert values.text(original, len(original), required=True) is original
    assert values.text('   ', 3) == '   '
    with pytest.raises(ValueError, match='^内容为空或超过长度限制$'):
        values.text('   ', 3, required=True)
    with pytest.raises(ValueError, match='^内容为空或超过长度限制$'):
        values.text(original, len(original) - 1)
    assert values.pack({'z': ['原字', True, None], 'a': 1}).encode() == '{"a":1,"z":["原字",true,null]}'.encode()


@pytest.mark.parametrize(('path', 'host'), [
    ('/api/media/accounts', True), ('/api/media/accounts/id/qr', True),
    ('/api/platform-accounts/id/qr', True), ('/api/media/jobs/id/transcript', True),
    ('/api/media/jobs/id', True), ('/api/media/images/id/' + 'a' * 64 + '/original', True),
    ('/api/media/accounts/original.png', False), ('/api/media/jobs/notes.html', False),
    ('/api/media/images/notes.html', False), ('/api/media/images/id/' + 'a' * 64 + '/other', False),
    ('/api/media/jobs/id/extra', False),
])
def test_reserved_protocols_do_not_consume_ordinary_output_directories(path, host):
    assert media_paths.is_host_media_protocol(path) is host


def test_leaf_contract_import_does_not_load_storage_web_or_execution():
    root = Path(__file__).resolve().parents[1]
    program = '''
import json, sys
from easel_workbench.contracts import values, media_paths, legacy_jobs
print(json.dumps([name for name in sys.modules if name.startswith((
    'easel_workbench.runtime', 'easel_workbench.http', 'easel.harnesses', 'fastapi', 'sqlite3'))]))
'''
    result = subprocess.run([sys.executable, '-c', program], cwd=root, env={**os.environ, 'PYTHONPATH': str(root)},
                            capture_output=True, text=True, check=True, timeout=15)
    assert json.loads(result.stdout) == []
