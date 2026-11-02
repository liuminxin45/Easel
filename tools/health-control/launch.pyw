"""Stable independent task entry; verifies its selected controller release."""
from pathlib import Path
import hashlib
import json
import os
import sys
import time

root = Path(__file__).resolve().parent
try:
    selected = json.loads((root/'active.json').read_text(encoding='utf-8-sig'))
    release = selected['release']
    if not isinstance(release, str) or len(release) != 16 or any(c not in '0123456789abcdef' for c in release):
        raise ValueError('invalid_controller_release')
    directory = root/'releases'/release
    raw = (directory/'controller-release.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != selected['manifest_sha256']:
        raise ValueError('controller_manifest_changed')
    manifest = json.loads(raw)
    for name, digest in manifest['files'].items():
        member = (directory/name).resolve()
        if not member.is_relative_to(directory) or hashlib.sha256(member.read_bytes()).hexdigest() != digest:
            raise ValueError('controller_source_changed')
    sys.path.insert(0, str(directory))
    from easel_health_control.cli import main
    main(['--config', str(root/'config.json'), *(sys.argv[1:] or ['run'])])
except BaseException as error:
    # Keep this last-resort record independent even if application/CLI is broken.
    with (root/'launcher-errors.jsonl').open('a', encoding='utf-8') as output:
        output.write(json.dumps({'at': time.time(), 'pid': os.getpid(), 'error_type': type(error).__name__})+'\n')
    raise
