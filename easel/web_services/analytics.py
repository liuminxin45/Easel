"""The original Easel analytics handlers, shared with optional hosts.

Only roots, process environment and existing account status are host ports.
Metric extraction, growth snapshots and validation remain in native scripts.
"""
from __future__ import annotations
import asyncio,json,os,signal,subprocess,sys,threading
from pathlib import Path
from fastapi import HTTPException
PYTHON_EXECUTABLE = None
PROFILE_BASE = None
COOKIE_PATH = None
_ANALYTICS_GUARD = None
_ANALYTICS_PROCESSES = {}
_ANALYTICS_PROCESS_LOCK = threading.RLock()
_ANALYTICS_CLOSED = False
_ANALYTICS_CLOSE_GUARD = False

ANALYTICS_PLATFORMS = {'xiaohongshu', 'douyin', 'kuaishou', 'zhihu', 'weixin-channels', 'bilibili', 'wechat-oa'}
_analytics_inflight: dict[str, asyncio.Task] = {}

def _run_analytics_command(cmd: list[str], env: dict[str, str], timeout: int):
    with _ANALYTICS_PROCESS_LOCK:
        if _ANALYTICS_CLOSED:
            raise HTTPException(503, '统计读取正在停止')
        process = subprocess.Popen(cmd, cwd=str(PROJECT_ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', start_new_session=os.name != 'nt')
        _ANALYTICS_PROCESSES[id(process)] = process
    try:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
            return subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            if os.name == 'nt':
                try:
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.kill()
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.stdout.close()
                process.stderr.close()
                process.wait(timeout=5)
            raise
    finally:
        with _ANALYTICS_PROCESS_LOCK:
            _ANALYTICS_PROCESSES.pop(id(process), None)

async def api_analytics_platforms():
    """列出支持抓数据的平台 + 各自登录态（前端据此渲染平台选择器）。"""
    return [{'platform': pf, 'name': LOGIN_RUNNERS.get(pf, {}).get('name', pf), 'loggedIn': _account_logged_in(pf, LOGIN_RUNNERS.get(pf, {}))} for pf in LOGIN_RUNNERS if pf in ANALYTICS_PLATFORMS]

async def api_analytics(platform: str):
    """抓取某平台已登录账号的创作数据，同平台并发刷新共享一次有时限的任务。"""
    if platform not in ANALYTICS_PLATFORMS:
        raise HTTPException(404, '该平台暂不支持数据抓取')
    task = _analytics_inflight.get(platform)
    if task is None or task.done():
        task = asyncio.create_task(_fetch_analytics(platform))
        _analytics_inflight[platform] = task
        task.add_done_callback(lambda finished: _finish_analytics(platform, finished))
    return await asyncio.shield(task)

def _finish_analytics(platform: str, task: asyncio.Task) -> None:
    if _analytics_inflight.get(platform) is task:
        _analytics_inflight.pop(platform, None)
    if not task.cancelled():
        task.exception()

async def _fetch_analytics(platform: str):
    if platform == 'bilibili':
        cmd = [PYTHON_EXECUTABLE or sys.executable, str(SHARED_SCRIPTS / 'bili_login.py'), 'stats', '--cookie', str(COOKIE_PATH or PROJECT_ROOT / 'cookies.json')]
    elif platform == 'wechat-oa':
        proxy_values = _proxy_env()
        wx_proxy = proxy_values.get('EASEL_PROXY') or proxy_values.get('https_proxy') or proxy_values.get('HTTPS_PROXY') or ''
        cmd = [PYTHON_EXECUTABLE or sys.executable, str(SHARED_SCRIPTS / 'weixin_mp_stats.py'), 'stats', '--proxy', wx_proxy, '--count', '20']
    else:
        cmd = [PYTHON_EXECUTABLE or sys.executable, str(SHARED_SCRIPTS / 'account_stats.py'), 'fetch', '--platform', platform]
    if _ANALYTICS_GUARD:
        _ANALYTICS_GUARD(platform)
    profile = Path(PROFILE_BASE(platform)) if PROFILE_BASE and platform != 'bilibili' else None
    if profile is not None:
        cmd += ['--profile-base', str(profile)]
    ana_env = _proxy_env()
    ana_env.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    if profile is not None:
        ana_env['EASEL_ANALYTICS_DIR'] = str(profile / '_analytics')
    try:
        proc = await asyncio.to_thread(_run_analytics_command, cmd, ana_env, 180 if platform == 'wechat-oa' else 90)
    except subprocess.TimeoutExpired:
        raise HTTPException(504, '抓取超时，已停止浏览器；请检查网络，关闭正在进行的登录或校验后重试')
    for line in reversed((proc.stdout or '').strip().splitlines()):
        line = line.strip()
        if line.startswith('{'):
            try:
                result = json.loads(line)
            except Exception:
                continue
            if not isinstance(result, dict):
                continue
            if proc.returncode or result.get('error'):
                raise HTTPException(502, str(result.get('error') or '平台数据抓取失败')[:240])
            if result.get('loggedIn') is True and all((result.get(key) is None for key in ('followers', 'likes', 'following', 'posts'))) and (not result.get('metrics')) and (not result.get('notes')):
                raise HTTPException(502, '账号已登录，但平台未返回可用数据；请检查网络或平台维护状态后重试')
            return result
    detail = (proc.stderr or '').strip().splitlines()[-1:] or ['未取到数据']
    raise HTTPException(502, f'未取到数据（可能未登录或平台改版）：{detail[0][:120]}')


def _stop_analytics_on_shutdown():
    global _ANALYTICS_CLOSED
    with _ANALYTICS_PROCESS_LOCK:
        if _ANALYTICS_CLOSE_GUARD:
            _ANALYTICS_CLOSED = True
        processes = list(_ANALYTICS_PROCESSES.values())
    for task in list(_analytics_inflight.values()):
        if not task.done():
            task.get_loop().call_soon_threadsafe(task.cancel)
    for process in processes:
        if process.poll() is not None:
            continue
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

EXPORTS = ('ANALYTICS_PLATFORMS', 'COOKIE_PATH', 'PROFILE_BASE', 'PYTHON_EXECUTABLE', '_analytics_inflight', '_fetch_analytics', '_finish_analytics', '_run_analytics_command', '_stop_analytics_on_shutdown', 'api_analytics', 'api_analytics_platforms')

def bind(context=None, *, into=None):
    from .binding import bind_functions
    return bind_functions(sys.modules[__name__], EXPORTS, context, into=into)

def create_analytics_context(root, accounts, *, scripts=None, environment=None,
                             python=None, guard=None, process_factory=None):
    from types import SimpleNamespace
    root = Path(root).resolve()
    context = {'PROJECT_ROOT': root, 'SHARED_SCRIPTS': Path(scripts or root / 'skills/shared/scripts').resolve(),
               'LOGIN_RUNNERS': accounts.LOGIN_RUNNERS,
               '_account_logged_in': accounts._account_logged_in,
               '_proxy_env': environment if callable(environment) else lambda: dict(environment or os.environ),
               'PYTHON_EXECUTABLE': str(python) if python else None,
               'PROFILE_BASE': accounts.PROFILE_BASE, 'COOKIE_PATH': accounts.COOKIE_PATH,
               '_analytics_inflight': {}, '_ANALYTICS_PROCESSES': {},
               '_ANALYTICS_PROCESS_LOCK': threading.RLock(), '_ANALYTICS_CLOSED': False,
               '_ANALYTICS_CLOSE_GUARD': True, '_ANALYTICS_GUARD': guard}
    if process_factory:
        child_process = SimpleNamespace(**{key: getattr(subprocess, key) for key in dir(subprocess) if not key.startswith('__')})
        child_process.Popen = process_factory
        context['subprocess'] = child_process
    return bind(context)
