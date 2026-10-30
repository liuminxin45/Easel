"""Shared native environment endpoints with optional host installation ports.

The default app uses the original installer. An isolated host supplies checks,
recipe identity and its durable project-local queue without a second endpoint
implementation or changing the fixed application Python/Node runtimes.
"""
from __future__ import annotations
import asyncio,json,subprocess,sys,threading,time,uuid
from pathlib import Path
from fastapi import HTTPException
from pydantic import BaseModel
SHARED_SCRIPTS = Path(__file__).resolve().parents[2] / 'skills/shared/scripts'
PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ENVIRONMENT_PORTS = {}

INSTALL_TOOL = SHARED_SCRIPTS / 'install_tool.py'

_ENV_TOOLS_CACHE: dict = {'ts': 0.0, 'data': None}

_ENV_JOBS: dict[str, dict] = {}

async def api_env_tools(refresh: bool=False):
    """环境体检：引擎 check --json（15 秒缓存；refresh=1 强制重测）。"""
    if not refresh and _ENV_TOOLS_CACHE['data'] and (time.time() - _ENV_TOOLS_CACHE['ts'] < 15):
        return _ENV_TOOLS_CACHE['data']
    if _ENVIRONMENT_PORTS.get('check'):
        data = await asyncio.to_thread(_ENVIRONMENT_PORTS['check'], refresh)
        data['cachedAt'] = int(time.time())
        _ENV_TOOLS_CACHE.update({'ts': time.time(), 'data': data})
        return data
    try:
        proc = await asyncio.to_thread(lambda: subprocess.run([sys.executable, str(INSTALL_TOOL), '--json', 'check'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=240, cwd=str(PROJECT_ROOT)))
    except subprocess.TimeoutExpired:
        raise HTTPException(504, '环境体检超时，请稍后再试')
    if proc.returncode != 0 or not (proc.stdout or '').strip():
        raise HTTPException(500, f"环境体检失败：{(proc.stderr or '').strip()[-300:] or '无输出'}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise HTTPException(500, f'体检输出解析失败：{e}')
    data['cachedAt'] = int(time.time())
    _ENV_TOOLS_CACHE.update({'ts': time.time(), 'data': data})
    return data

class EnvInstallRequest(BaseModel):
    id: str

_INSTALL_IDS_CACHE: dict = {'ts': 0.0, 'ids': frozenset()}

def _install_tool_ids() -> frozenset[str]:
    """引擎里真实存在的配方 id（缓存 5 分钟）。安装接口只认这张表里的 id——
    只按正则放行的话，`--help` 这类带横线的串会被 argparse 当选项吃掉。"""
    if _ENVIRONMENT_PORTS.get('ids'):
        return frozenset(_ENVIRONMENT_PORTS['ids']())
    if _INSTALL_IDS_CACHE['ids'] and time.time() - _INSTALL_IDS_CACHE['ts'] < 300:
        return _INSTALL_IDS_CACHE['ids']
    try:
        p = subprocess.run([sys.executable, str(INSTALL_TOOL), '--json', 'list'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30, cwd=str(PROJECT_ROOT))
        ids = frozenset((t['id'] for t in json.loads(p.stdout).get('tools') or [] if t.get('id')))
    except Exception:
        return _INSTALL_IDS_CACHE['ids']
    if ids:
        _INSTALL_IDS_CACHE.update({'ts': time.time(), 'ids': ids})
    return ids

async def api_env_install(req: EnvInstallRequest):
    """后台安装（引擎 install）：立即返回 jobId，前端轮询进度。"""
    tid = (req.id or '').strip()
    known = await asyncio.to_thread(_install_tool_ids)
    if tid not in known:
        raise HTTPException(400, f'无效的工具 id：{tid[:40]!r}')
    if _ENVIRONMENT_PORTS.get('install'):
        return await asyncio.to_thread(_ENVIRONMENT_PORTS['install'], tid)
    job_id = uuid.uuid4().hex[:16]
    if len(_ENV_JOBS) >= 200:
        for k, _ in sorted((kv for kv in _ENV_JOBS.items() if kv[1].get('ended')), key=lambda kv: kv[1]['ended'])[:100]:
            _ENV_JOBS.pop(k, None)
    job = {'jobId': job_id, 'id': tid, 'state': 'running', 'lines': [], 'result': None, 'started': int(time.time()), 'ended': None}
    _ENV_JOBS[job_id] = job

    def _run() -> None:
        proc = None
        try:
            proc = subprocess.Popen([sys.executable, str(INSTALL_TOOL), '--json', 'install', tid], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', cwd=str(PROJECT_ROOT))
            _out: list[str] = []
            t_out = threading.Thread(target=lambda: _out.append(proc.stdout.read() or ''), daemon=True)
            t_out.start()
            for line in proc.stderr:
                line = line.rstrip()
                if line:
                    job['lines'] = (job['lines'] + [line])[-40:]
            try:
                proc.wait(timeout=3600)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=30)
                raise
            t_out.join(timeout=30)
            out = ''.join(_out).strip()
            if out:
                job['result'] = (json.loads(out).get('results') or [None])[0]
            job['state'] = 'ok' if (job['result'] or {}).get('state') == 'ok' else 'fail'
        except Exception as e:
            job['state'] = 'fail'
            job['result'] = {'id': tid, 'state': 'fail', 'detail': f'{type(e).__name__}: {e}'}
        finally:
            job['ended'] = int(time.time())
            _ENV_TOOLS_CACHE['ts'] = 0.0
    threading.Thread(target=_run, daemon=True).start()
    return {'jobId': job_id, 'id': tid, 'state': 'running'}

async def api_env_job(job_id: str):
    """查安装进度：running / ok / fail + 最近日志行 + 最终结果。"""
    if _ENVIRONMENT_PORTS.get('job'):
        return await asyncio.to_thread(_ENVIRONMENT_PORTS['job'], job_id)
    job = _ENV_JOBS.get(job_id)
    if not job:
        raise HTTPException(404, '任务不存在（服务可能重启过）')
    return job

EXPORTS = ('EnvInstallRequest', 'INSTALL_TOOL', '_ENV_JOBS', '_ENV_TOOLS_CACHE', '_INSTALL_IDS_CACHE', '_install_tool_ids', 'api_env_install', 'api_env_job', 'api_env_tools')

def bind(context=None, *, into=None):
    from .binding import bind_functions
    return bind_functions(sys.modules[__name__], EXPORTS, context, into=into)

def create_environment_context(root, *, scripts=None, ports=None):
    root = Path(root).resolve()
    scripts = Path(scripts or root / 'skills/shared/scripts').resolve()
    return bind({'PROJECT_ROOT': root, 'SHARED_SCRIPTS': scripts,
                 'INSTALL_TOOL': scripts / 'install_tool.py',
                 '_ENV_TOOLS_CACHE': {'ts': 0.0, 'data': None}, '_ENV_JOBS': {},
                 '_INSTALL_IDS_CACHE': {'ts': 0.0, 'ids': frozenset()},
                 '_ENVIRONMENT_PORTS': dict(ports or {})})
