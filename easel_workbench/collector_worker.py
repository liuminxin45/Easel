"""Trusted server-installed Python collector. stdout is one protocol document."""
import argparse
import json
import os
from pathlib import Path
import sys

# A direct script starts with its package directory on sys.path. The private
# HTTP adapter is named ``http`` too, and must never shadow Python's stdlib.
_package = Path(__file__).resolve().parent
sys.path[:] = [entry for entry in sys.path if Path(entry or os.getcwd()).resolve() != _package]
sys.path.insert(0,str(_package.parent))
from easel_workbench.collectors import produce,source_preview


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--request',type=Path)
    group.add_argument('--source')
    parser.add_argument('--root',type=Path)
    args=parser.parse_args()
    if args.request:
        request=json.loads(args.request.read_text(encoding='utf-8'))
        result=produce(request)
    else:
        import os
        root=args.root or Path(os.environ.get('AI_DESK_PROJECT_ROOT') or Path(__file__).resolve().parents[1])
        result=source_preview(args.source,root)
    print(json.dumps(result,ensure_ascii=False))
