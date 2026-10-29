"""Resolve migrated, owned files without rewriting historical evidence."""
from pathlib import Path

PREVIOUS_ROOT=Path('D:/Projects/ai-news-desk').resolve()
OWNED=('data/artifacts','data/toolbox/files','data/workbench')


def artifact_path(value, root):
    path=Path(value).resolve();root=Path(root).resolve()
    for relative in OWNED:
        before=(PREVIOUS_ROOT/relative).resolve()
        if path.is_relative_to(before):
            return root/relative/path.relative_to(before)
    return path


def discovery_evidence(value,root):
    path=Path(value).resolve();root=Path(root).resolve()
    previous=(PREVIOUS_ROOT/'evidence/discovery').resolve()
    if path.is_relative_to(previous):return (root/'evidence/discovery'/path.relative_to(previous)).resolve()
    return path
