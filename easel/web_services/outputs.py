"""Native Easel handlers, shared by the original app and optional hosts.

The implementation lives here once. Host-specific persistence and roots are
injected into an isolated namespace; default web routes retain their behavior.
"""
from __future__ import annotations
import asyncio,json,os,shutil,subprocess,sys,threading,time,uuid,zipfile
from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

TEXT_EXTS = {'.txt', '.md', '.json', '.csv', '.log', '.py', '.js', '.ts', '.html', '.htm', '.css', '.xml', '.yaml', '.yml', '.srt', '.vtt'}
IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.svg'}
VIDEO_EXTS = {'.mp4', '.mov', '.webm', '.m4v'}
AUDIO_EXTS = {'.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac'}
SYSTEM_TOPLEVEL_DIRS = {'analytics'}
PROTECTED_OUTPUTS = {'_login', '_analytics', '_schedule.json', '_ideas.json', '_publish', '_publish.log', '_sessions', '_profile_build', '_debug', '_inbox'}
EXPORTS = ('_file_kind', '_file_meta', '_build_output_node', '_read_project_meta',
           'get_output_tree', '_safe_output_path', 'api_outputs',
           'api_artifact_archive', 'api_output', 'api_media',
           '_safe_output_target', '_is_protected', 'api_output_delete')


def bind(context=None, *, into=None):
    from .binding import bind_functions
    return bind_functions(sys.modules[__name__], EXPORTS, context, into=into)


def create_outputs_context(root, *, outputs=None):
    """Bind native output rendering to an explicit host output directory."""
    from .binding import bind_functions
    root = Path(root).resolve()
    return bind_functions(sys.modules[__name__], EXPORTS,
                          {'PROJECT_ROOT': root, 'OUTPUTS_DIR': Path(outputs or root / 'outputs').resolve()})


def _file_kind(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext in IMAGE_EXTS:
        return 'image'
    if ext in VIDEO_EXTS:
        return 'video'
    if ext in AUDIO_EXTS:
        return 'audio'
    if ext in TEXT_EXTS:
        return 'text'
    return 'binary'

def _file_meta(f: Path, rel: str) -> dict:
    try:
        st = f.stat()
        mtime, size = (int(st.st_mtime), st.st_size)
    except OSError:
        mtime, size = (0, 0)
    return {'name': f.name, 'path': rel, 'kind': _file_kind(f.name), 'mtime': mtime, 'size': size}

def _build_output_node(path: Path, rel: str) -> dict:
    """递归构建产物树节点：文件→file 节点；目录→dir 节点带 children + 递归 fileCount。"""
    if path.is_dir():
        children = []
        for c in sorted(path.iterdir()):
            if c.is_symlink() or getattr(c, 'is_junction', lambda: False)():
                continue
            if c.name.startswith('.'):
                continue
            children.append(_build_output_node(c, f'{rel}/{c.name}'))
        mtime = max((x['mtime'] for x in children), default=int(path.stat().st_mtime))
        file_count = sum((x.get('fileCount', 1) if x['type'] == 'dir' else 1 for x in children))
        return {'name': path.name, 'type': 'dir', 'path': rel, 'mtime': mtime, 'children': children, 'fileCount': file_count}
    m = _file_meta(path, rel)
    m['type'] = 'file'
    return m

def _read_project_meta(proj: Path) -> dict:
    """读项目目录的 .easel.json 展示头，附封面/成品的解析路径供前端富展示。

    只取展示相关字段（不含编排 steps）。cover 解析优先级：
    展示头声明的 cover → 首个成品媒体 → 目录内首张图/视频（兜底）。
    """
    mf = proj / '.easel.json'
    if not mf.is_file():
        return {}
    try:
        data = json.loads(mf.read_text(encoding='utf-8'))
    except Exception:
        return {}
    meta = {k: data.get(k) for k in ('title', 'summary', 'platform', 'kind', 'status', 'tags', 'deliverables') if data.get(k) not in (None, '', [])}
    if not meta:
        return {}

    def _rel_if_exists(name: str) -> str:
        return f'{proj.name}/{name}' if name and (proj / name).is_file() else ''
    cover_rel = ''
    declared = data.get('cover')
    if declared and (proj / declared).is_file():
        cover_rel = f'{proj.name}/{declared}'
    if not cover_rel:
        for d in data.get('deliverables') or []:
            if _file_kind(d) in ('image', 'video') and (proj / d).is_file():
                cover_rel = f'{proj.name}/{d}'
                break
    if cover_rel:
        meta['cover'] = cover_rel
    meta['deliverablePaths'] = [f'{proj.name}/{d}' for d in data.get('deliverables') or [] if (proj / d).is_file()]
    return meta

def get_output_tree() -> list[dict]:
    if not OUTPUTS_DIR.is_dir():
        return []
    items = []
    for e in sorted(OUTPUTS_DIR.iterdir()):
        if e.name.startswith('.') or e.name.startswith('_'):
            continue
        if not e.is_dir() or e.is_symlink() or getattr(e, 'is_junction', lambda: False)() or e.name in SYSTEM_TOPLEVEL_DIRS:
            continue
        node = _build_output_node(e, e.name)
        meta = _read_project_meta(e)
        if meta:
            node['meta'] = meta
        items.append(node)
    return sorted(items, key=lambda x: x.get('mtime', 0), reverse=True)

def _safe_output_path(rel: str) -> Path:
    """把相对路径解析到 outputs/ 内，防路径穿越。"""
    full = (OUTPUTS_DIR / rel).resolve()
    root = OUTPUTS_DIR.resolve()
    if root != full and root not in full.parents:
        raise HTTPException(403, '非法路径')
    if not full.is_file():
        raise HTTPException(404, '文件不存在')
    return full

def api_outputs():
    return get_output_tree()

def api_artifact_archive(path: str):
    full = _safe_output_path(path)
    if full.suffix.lower() != '.zip':
        raise HTTPException(400, '仅支持 ZIP 产物索引')
    artifacts = []
    seen = set()
    extensions = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.avif', '.bmp', '.ico', '.html', '.htm', '.mp4', '.webm', '.mov', '.m4v', '.mp3', '.wav', '.ogg', '.m4a', '.flac', '.pdf'}
    try:
        with zipfile.ZipFile(full) as archive:
            entries = archive.infolist()
            if len(entries) > 1000:
                raise HTTPException(400, '压缩包文件过多，暂不自动预览')
            for entry in entries:
                name = entry.filename
                parts = name.split('/')
                if entry.is_dir() or name.startswith('/') or '\\' in name or any((not part or part.startswith(('.', '_')) for part in parts)) or any((ord(character) < 32 for character in name)) or (Path(name).suffix.lower() not in extensions):
                    continue
                relative = (full.parent / name).relative_to(OUTPUTS_DIR.resolve()).as_posix()
                try:
                    original = _safe_output_path(relative)
                except HTTPException:
                    continue
                if original.stat().st_size != entry.file_size or relative in seen:
                    continue
                seen.add(relative)
                artifacts.append(relative)
                if len(artifacts) >= 100:
                    break
    except (OSError, zipfile.BadZipFile):
        raise HTTPException(400, '无法读取压缩包索引')
    return {'paths': artifacts}

async def api_output(path: str):
    """文本产物内容。二进制/媒体返回 isBinary=true，前端改用 /api/media。"""
    full = _safe_output_path(path)
    kind = _file_kind(full.name)
    if kind not in ('text',):
        return {'path': path, 'content': '', 'kind': kind, 'isBinary': True}
    try:
        return {'path': path, 'content': full.read_text(encoding='utf-8'), 'kind': 'text', 'isBinary': False}
    except UnicodeDecodeError:
        return {'path': path, 'content': '', 'kind': 'binary', 'isBinary': True}

async def api_media(path: str):
    """原样输出媒体文件（图片/视频/音频/HTML/PDF），供 <img>/<video>/iframe/下载。"""
    full = _safe_output_path(path)
    headers = {'Cache-Control': 'no-cache, no-store, must-revalidate', 'Pragma': 'no-cache'} if full.suffix.lower() in {'.html', '.htm'} else {}
    return FileResponse(full, headers=headers)

def _safe_output_target(rel: str, *, must_exist: bool=True) -> Path:
    """解析到 outputs/ 内的文件或目录（防穿越）。与 _safe_output_path 不同：允许目录、
    可要求不必已存在（上传新文件时）。永远拒绝 outputs/ 根本身。"""
    full = (OUTPUTS_DIR / rel).resolve()
    root = OUTPUTS_DIR.resolve()
    if full == root or root not in full.parents:
        raise HTTPException(403, '非法路径')
    if must_exist and (not full.exists()):
        raise HTTPException(404, '不存在')
    return full

def _is_protected(full: Path) -> bool:
    """路径的顶层段是否属于受保护的系统项。"""
    try:
        rel = full.relative_to(OUTPUTS_DIR.resolve())
    except ValueError:
        return True
    if not rel.parts:
        return True
    first = rel.parts[0]
    return first.startswith('_') or first.startswith('.') or first in PROTECTED_OUTPUTS or (first.lower() in {'analytics', 'wechat'})

async def api_output_delete(path: str):
    """删除内容库里的单个文件或整个项目目录。系统数据（_login/_analytics/日历/发布记录）受保护。"""
    full = _safe_output_target(path)
    if _is_protected(full):
        raise HTTPException(403, '系统数据受保护，不可从内容库删除')
    is_dir = full.is_dir()
    try:
        if is_dir:
            shutil.rmtree(full)
        else:
            full.unlink()
    except OSError as e:
        raise HTTPException(500, f'删除失败：{e}')
    return {'ok': True, 'deleted': path, 'kind': 'dir' if is_dir else 'file'}
