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

SCHEDULE_STATUSES = {'idea', 'draft', 'scheduled', 'published'}
SCHEDULE_KINDS = {'content', 'event'}
IDEA_STATUSES = {'pending', 'doing', 'done'}
EXPORTS = ('_schedule_lock', '_read_schedule', '_write_schedule', 'ScheduleItem',
           'api_schedule_list', 'api_schedule_create', 'api_schedule_update',
           'api_schedule_delete', 'api_schedule_context', '_read_ideas',
           '_write_ideas', 'IdeaItem', 'api_ideas_list', 'api_ideas_create',
           'api_ideas_update', 'api_ideas_delete')


def bind(context=None, *, into=None):
    from .binding import bind_functions
    return bind_functions(sys.modules[__name__], EXPORTS, context, into=into)


def create_planning_context(root, *, outputs=None, scripts=None, environment=None,
                            python=None, read_schedule=None, write_schedule=None,
                            read_ideas=None, write_ideas=None, lock=None):
    """Use the original handlers with either native files or a host repository."""
    from .binding import bind_functions
    root = Path(root).resolve()
    output = Path(outputs or root / 'outputs').resolve()
    context = {'PROJECT_ROOT': root, 'OUTPUTS_DIR': output,
               'SHARED_SCRIPTS': Path(scripts or root / 'skills/shared/scripts'),
               'SCHEDULE_FILE': output / '_schedule.json',
               'IDEAS_FILE': output / '_ideas.json',
               '_SCHEDULE_LOCK': lock or threading.RLock(),
               '_proxy_env': environment if callable(environment) else lambda: dict(environment or os.environ)}
    result = bind_functions(sys.modules[__name__], EXPORTS, context)
    for key, callback in (('_read_schedule', read_schedule), ('_write_schedule', write_schedule),
                          ('_read_ideas', read_ideas), ('_write_ideas', write_ideas)):
        if callback is not None:
            result.namespace[key] = callback
            setattr(result, key, callback)
    # Only context summary starts a subprocess; use the host's isolated runtime.
    if python:
        from types import SimpleNamespace
        result.namespace['sys'] = SimpleNamespace(executable=str(python))
    return result


def _schedule_lock() -> threading.Lock:
    return _SCHEDULE_LOCK

def _read_schedule() -> list[dict]:
    if not SCHEDULE_FILE.is_file():
        return []
    try:
        d = json.loads(SCHEDULE_FILE.read_text(encoding='utf-8'))
        return d if isinstance(d, list) else []
    except Exception:
        return []

def _write_schedule(items: list[dict]) -> None:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SCHEDULE_FILE.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(SCHEDULE_FILE)

class ScheduleItem(BaseModel):
    title: str
    date: str
    platform: str = ''
    time: str = ''
    status: str = 'idea'
    note: str = ''
    kind: str = 'content'
    url: str = ''
    source: str = 'manual'
    event_type: str = ''
    end_date: str = ''

async def api_schedule_list():
    return _read_schedule()

async def api_schedule_create(req: ScheduleItem):
    with _schedule_lock():
        items = _read_schedule()
        kind = req.kind if req.kind in SCHEDULE_KINDS else 'content'
        st = req.status if req.status in SCHEDULE_STATUSES else 'idea'
        item = {'id': uuid.uuid4().hex[:12], 'title': req.title.strip() or ('未命名活动' if kind == 'event' else '未命名'), 'date': req.date, 'platform': req.platform, 'time': req.time, 'status': st, 'note': req.note, 'kind': kind, 'url': req.url, 'source': req.source if req.source in {'manual', 'publish-page', 'chat', 'scheduler'} else 'manual', 'event_type': req.event_type, 'end_date': req.end_date}
        items.append(item)
        _write_schedule(items)
    return item

async def api_schedule_update(sid: str, req: ScheduleItem):
    with _schedule_lock():
        items = _read_schedule()
        for it in items:
            if it.get('id') == sid:
                kind = req.kind if req.kind in SCHEDULE_KINDS else it.get('kind', 'content')
                it.update({'title': req.title.strip() or it.get('title', '未命名'), 'date': req.date, 'platform': req.platform, 'time': req.time, 'status': req.status if req.status in SCHEDULE_STATUSES else it.get('status', 'idea'), 'note': req.note, 'kind': kind, 'url': req.url, 'event_type': req.event_type, 'end_date': req.end_date})
                _write_schedule(items)
                return it
    raise HTTPException(404, '排期不存在')

async def api_schedule_delete(sid: str):
    with _schedule_lock():
        items = _read_schedule()
        new = [it for it in items if it.get('id') != sid]
        if len(new) == len(items):
            raise HTTPException(404, '排期不存在')
        _write_schedule(new)
    return {'ok': True, 'deleted': sid}

async def api_schedule_context(days: int=14):
    """规划摘要（发布节奏/断更缺口 + 待发排期 + 临近节点 + 建议）——薄封装 calendar_ops，
    前端页头「近期节点/建议」与 Agent 读回共用同一逻辑。失败返回空摘要不抛错。"""
    cmd = [sys.executable, str(SHARED_SCRIPTS / 'calendar_ops.py'), '--data', str(SCHEDULE_FILE), 'context', '--days', str(max(1, min(days, 90)))]
    try:
        proc = await asyncio.to_thread(subprocess.run, cmd, cwd=str(PROJECT_ROOT), env=_proxy_env(), capture_output=True, text=True, timeout=20)
        return json.loads(proc.stdout) if proc.returncode == 0 and proc.stdout.strip() else {}
    except Exception:
        return {}

def _read_ideas() -> list[dict]:
    if not IDEAS_FILE.is_file():
        return []
    try:
        d = json.loads(IDEAS_FILE.read_text(encoding='utf-8'))
        return d if isinstance(d, list) else []
    except Exception:
        return []

def _write_ideas(items: list[dict]) -> None:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = IDEAS_FILE.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(IDEAS_FILE)

class IdeaItem(BaseModel):
    title: str
    note: str = ''
    source: str = ''
    status: str = 'pending'
    source_id: str | None = None

async def api_ideas_list():
    return _read_ideas()

async def api_ideas_create(req: IdeaItem):
    items = _read_ideas()
    st = req.status if req.status in IDEA_STATUSES else 'pending'
    item = {'id': uuid.uuid4().hex[:12], 'title': req.title.strip() or '未命名选题', 'note': req.note, 'source': req.source, 'status': st, 'created': int(time.time())}
    if req.source_id is not None:
        item['source_id'] = req.source_id
    items.insert(0, item)
    _write_ideas(items)
    return item

async def api_ideas_update(iid: str, req: IdeaItem):
    items = _read_ideas()
    for it in items:
        if it.get('id') == iid:
            it.update({'title': req.title.strip() or it.get('title', '未命名选题'), 'note': req.note, 'source': req.source, 'status': req.status if req.status in IDEA_STATUSES else it.get('status', 'pending')})
            # Older clients omit this optional binding when editing an idea.
            if req.source_id is not None:
                it['source_id'] = req.source_id
            _write_ideas(items)
            return it
    raise HTTPException(404, '选题不存在')

async def api_ideas_delete(iid: str):
    items = _read_ideas()
    new = [it for it in items if it.get('id') != iid]
    if len(new) == len(items):
        raise HTTPException(404, '选题不存在')
    _write_ideas(new)
    return {'ok': True, 'deleted': iid}
