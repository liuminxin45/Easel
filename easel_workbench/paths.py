"""Resolve migrated, owned files without rewriting historical evidence."""
from pathlib import Path
import os

PREVIOUS_ROOT=Path('D:/Projects/ai-news-desk').resolve()
OWNED=('data/artifacts','data/toolbox/files','data/workbench')


def owned_output_path(root,relative):
    """A program-owned output path must stay in this project without links."""
    root=Path(root).resolve();name=Path(relative)
    reserved={'CON','PRN','AUX','NUL',*[f'{prefix}{n}' for prefix in ('COM','LPT') for n in range(1,10)]}
    if name.is_absolute() or not name.parts or name.parts[0]!='outputs' or any(part in ('.','..') or part.rstrip(' .')!=part or part.split('.')[0].upper() in reserved or ':' in part or '\\' in part or getattr(os.path,'isreserved',lambda _:False)(part) for part in name.parts):
        raise ValueError('项目输出路径无效')
    current=root
    for part in name.parts:
        current=current/part
        if current.is_symlink() or getattr(current,'is_junction',lambda:False)():raise ValueError('项目输出目录不能经链接跳转')
    path=current.resolve()
    if not path.is_relative_to(root/'outputs'):raise ValueError('项目输出路径离开当前项目')
    return path


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
