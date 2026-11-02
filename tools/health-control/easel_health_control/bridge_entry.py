"""Application-side subprocess bootstrap. Controller itself never imports Easel."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import sys


def load(root):
    root = Path(root).resolve()
    selected = json.loads((root/'data/active-workbench.json').read_text(encoding='utf-8-sig'))
    release = selected.get('release', '')
    if not re.fullmatch(r'workbench-[A-Za-z0-9_-]+', release):
        raise ValueError('invalid_release')
    directory = root/'workbench-releases'/release
    manifest_path = directory/'workbench-release.json'
    raw = manifest_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != selected.get('manifest_sha256'):
        raise ValueError('manifest_changed')
    manifest = json.loads(raw)
    # The bridge loads code, not skill assets. Verify all executable Python
    # members; the daily canary additionally verifies required skill resources.
    for name, digest in manifest['files'].items():
        if not name.endswith('.py'):
            continue
        path = (directory/name).resolve()
        if not path.is_relative_to(directory) or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('runtime_code_changed')
    if not (directory/'easel_workbench/diagnostics/health_bridge.py').is_file():
        raise ValueError('runtime_missing_health_bridge')
    sys.path.insert(0, str(directory))
    return root


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--app-root', required=True)
    parser.add_argument('action', choices=('inspect', 'recover', 'reconcile'))
    args = parser.parse_args()
    root = load(args.app_root)
    from easel_workbench.diagnostics.health_bridge import main as bridge
    bridge(root, args.action)


if __name__ == '__main__':
    main()
