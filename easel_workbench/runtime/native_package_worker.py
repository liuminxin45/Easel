"""Run the original local handoff builder in project-isolated media Python.

Input comes only from the authenticated host's frozen operation, never a public
path parameter. This helper contacts no model and no social platform.
"""
from __future__ import annotations

if __name__ == '__main__' and not __package__:
    import sys as _bootstrap_sys
    from pathlib import Path as _BootstrapPath
    _bootstrap_sys.path.insert(0, str(_BootstrapPath(__file__).resolve().parents[2]))

import json
from pathlib import Path
import sys

from easel.manual_publish import build_package


def main():
    payload = json.load(sys.stdin)
    outputs = Path(payload['outputs']).resolve()
    package = build_package(outputs, payload['platform'], payload['title'],
                            payload['body'], payload.get('tags', ''),
                            payload.get('media', []), payload.get('reviewed'))
    relative = package.resolve().relative_to(outputs).as_posix()
    print(json.dumps({'path': relative}, ensure_ascii=False))


if __name__ == '__main__':
    main()
