"""Trusted server-installed Python collector. stdout is one protocol document."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
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
