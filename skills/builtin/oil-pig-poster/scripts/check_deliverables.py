"""Read-only byte/identity/locked-text checks before independent review."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath


def check(root, manifest, *, work_id=None, version=None):
    root = Path(root).resolve(strict=True)
    if not isinstance(manifest, dict) or manifest.get('schema_version') != 1:
        raise ValueError('Expected a versioned artifact manifest')
    if work_id is not None and manifest.get('work_id') != work_id:
        raise ValueError('Artifact work identity mismatch')
    if version is not None and manifest.get('version') != version:
        raise ValueError('Artifact version mismatch')
    rows = manifest.get('artifacts')
    if not isinstance(rows, list) or not rows:
        raise ValueError('Actual deliverables are required')
    checked, seen = [], set()
    for row in rows:
        relative = row.get('path') if isinstance(row, dict) else None
        if not isinstance(relative, str) or not relative or '\\' in relative:
            raise ValueError('Deliverable paths must be explicit project-relative paths')
        parsed = PurePosixPath(relative)
        if parsed.is_absolute() or '..' in parsed.parts or ':' in relative:
            raise ValueError('Deliverable path escapes the selected output root')
        path = (root / relative).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file() or path in seen:
            raise ValueError('Deliverable is outside the output root or duplicated')
        seen.add(path)
        raw = path.read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        if not raw or actual != row.get('sha256'):
            raise ValueError('Deliverable bytes do not match the frozen manifest')
        locked = row.get('locked_text', [])
        if not isinstance(locked, list) or any(not isinstance(text, str) or not text for text in locked):
            raise ValueError('Locked text must be explicit nonempty strings')
        if locked:
            text = raw.decode('utf-8-sig')
            if any(value not in text for value in locked):
                raise ValueError('Locked original text is missing')
        checked.append({'path': relative, 'sha256': actual, 'size': len(raw)})
    return {'status': 'passed', 'checks': ['work_identity', 'version_identity', 'actual_file_bytes', 'locked_text'],
            'artifacts': checked, 'visual_or_semantic_review': 'not_performed',
            'acceptance_or_publication': 'not_authorized'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--work-id', required=True)
    parser.add_argument('--version', required=True)
    options = parser.parse_args()
    result = check(options.root, json.loads(options.manifest.read_text(encoding='utf-8-sig')),
                   work_id=options.work_id, version=options.version)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
