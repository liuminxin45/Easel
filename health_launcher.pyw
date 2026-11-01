"""OS-owned bounded health job, loaded from the selected immutable backend."""
from pathlib import Path
import json
import os
import sys
import traceback


def launch(root):
    sys.path.insert(0, str(root / 'scripts'))
    from workbench_release import verify
    selection = json.loads((root / 'data/active-workbench.json').read_text(encoding='utf-8'))
    name = selection['release']
    import re
    if not re.fullmatch(r'workbench-[A-Za-z0-9_-]+', name):
        raise ValueError('Invalid health runtime selection')
    release = root / 'workbench-releases' / name
    package = verify(release, selection['manifest_sha256'])
    if package.get('release') != name:
        raise ValueError('Health runtime binding changed')
    sys.path.insert(0, str(release))
    os.environ['AI_DESK_PROJECT_ROOT'] = str(root)
    from easel_workbench.health_watchdog import run
    run(root)


if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    try:
        launch(root)
    except Exception:
        directory = root / '.local/workbench-deployment';directory.mkdir(parents=True, exist_ok=True)
        # Exception type/trace location only: never persist HTTP token or body.
        with (directory / 'health-launcher.log').open('a', encoding='utf-8') as stream:
            traceback.print_exc(file=stream)
        raise
