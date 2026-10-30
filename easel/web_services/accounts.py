"""Native Easel implementation shared by default and hosted applications.

Moved from web/app.py; do not generate a private copy of these functions.
Host-specific roots, persistence and configuration are supplied by bind().
"""
from __future__ import annotations
import asyncio, ipaddress, json, os, re, shutil, socket, subprocess, sys, threading, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path
from fastapi import HTTPException
from pydantic import BaseModel, Field, StrictBool
from easel.direct_api import DirectAPIError, api_config, read_settings
from easel.gateway_endpoint import chat_completions_url, port_source
from easel import harnesses
from easel.harnesses import store as harness_store
from easel.harnesses.base import HarnessError
from easel.openclaw_workspace import config_path as _oc_config_path
from .binding import bind_functions


LOGIN_TIMEOUT = 240


LOGIN_PROCESSES: dict[str, subprocess.Popen] = {}


WHOAMI_TTL = 600  # 秒


_WHOAMI_CACHE: dict[str, tuple[float, dict]] = {}


_WHOAMI_LOCK = threading.Lock()


_WHOAMI_TASKS: dict[str, asyncio.Task] = {}


_LOGIN_START_LOCKS: dict[str, asyncio.Lock] = {}


LOGIN_RUNNERS: dict[str, dict] = {
    "xiaohongshu": {"name": "小红书", "backend": "xhs", "profile": "XiaohongshuProfile"},
    "kuaishou": {"name": "快手", "backend": "web", "wp": "kuaishou", "profile": "KuaishouProfile"},
    "weixin-channels": {"name": "微信视频号", "backend": "web", "wp": "weixin-channels", "profile": "ChannelsProfile"},
    "zhihu": {"name": "知乎", "backend": "web", "wp": "zhihu", "profile": "ZhihuProfile"},
    "bilibili": {"name": "B站", "backend": "biliup"},
    "douyin": {"name": "抖音", "backend": "douyin", "profile": "DouyinProfile"},
    # 微信公众号：扫码登录后台会话（发布+数据都走它），backend=='wechat-oa' 在各处单独分支处理。
    "wechat-oa": {"name": "微信公众号", "backend": "wechat-oa"},
}


WECHAT_WEB_ACCOUNT = "web"   # web 端配置写入/读取的账号 key


def _wechat_load_yaml() -> dict:
    """读 wechat-publisher.yaml（不存在或损坏则返回空 dict）。"""
    if not WECHAT_CONFIG_YAML.is_file():
        return {}
    try:
        import yaml
        data = yaml.safe_load(WECHAT_CONFIG_YAML.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _wechat_web_account() -> dict:
    """返回 web 端配置的公众号账号（accounts.web），无则空 dict。"""
    cfg = _wechat_load_yaml()
    accts = cfg.get("accounts") if isinstance(cfg.get("accounts"), dict) else {}
    acc = accts.get(WECHAT_WEB_ACCOUNT)
    return acc if isinstance(acc, dict) else {}


def _wechat_has_credentials() -> bool:
    acc = _wechat_web_account()
    return bool(acc.get("app_id") and acc.get("app_secret"))


def _wechat_save_credentials(app_id: str, app_secret: str, name: str = "", author: str = "") -> None:
    """把 AppID/AppSecret 写入 wechat-publisher.yaml 的 accounts.web（原子写，保留其它账号）。"""
    import yaml
    cfg = _wechat_load_yaml()
    if not isinstance(cfg.get("accounts"), dict):
        cfg["accounts"] = {}
    acc = cfg["accounts"].get(WECHAT_WEB_ACCOUNT)
    if not isinstance(acc, dict):
        acc = {}
    acc["name"] = name or acc.get("name") or "微信公众号"
    acc["app_id"] = app_id
    acc["app_secret"] = app_secret
    if author:
        acc["author"] = author
    acc.setdefault("author", "")
    cfg["accounts"][WECHAT_WEB_ACCOUNT] = acc
    # web 账号存在即设为默认，方便 CLI 直接用
    cfg.setdefault("default", WECHAT_WEB_ACCOUNT)
    WECHAT_CONFIG_YAML.parent.mkdir(parents=True, exist_ok=True)
    tmp = WECHAT_CONFIG_YAML.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    os.replace(tmp, WECHAT_CONFIG_YAML)


def _wechat_clear_credentials() -> None:
    """删除 accounts.web 及其 token 缓存。"""
    import yaml
    cfg = _wechat_load_yaml()
    accts = cfg.get("accounts")
    if isinstance(accts, dict) and WECHAT_WEB_ACCOUNT in accts:
        accts.pop(WECHAT_WEB_ACCOUNT, None)
        if cfg.get("default") == WECHAT_WEB_ACCOUNT:
            cfg["default"] = next(iter(accts), "") if accts else ""
        try:
            tmp = WECHAT_CONFIG_YAML.with_suffix(".yaml.tmp")
            tmp.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
            os.replace(tmp, WECHAT_CONFIG_YAML)
        except Exception:
            pass
    for cache in (WECHAT_SKILL_SCRIPTS / f".token_cache_{WECHAT_WEB_ACCOUNT}.json",
                  WECHAT_SKILL_SCRIPTS / ".token_cache.json"):
        try:
            cache.unlink()
        except OSError:
            pass


def _wechat_verify_token() -> tuple[bool, str]:
    """用当前 accounts.web 凭证调官方 token 接口验证。返回 (ok, message)。
    在子进程里跑，避免把 skill 的 import 副作用带进 web 进程。"""
    code = (
        "import sys; sys.path.insert(0, %r)\n"
        "from config import set_account\n"
        "from wechat_token import get_access_token\n"
        "set_account(%r)\n"
        "try:\n"
        "    t = get_access_token(force_refresh=True)\n"
        "    print('OK' if t else 'EMPTY')\n"
        "except Exception as e:\n"
        "    print('ERR:' + str(e))\n"
    ) % (str(WECHAT_SKILL_SCRIPTS), WECHAT_WEB_ACCOUNT)
    try:
        proc = subprocess.run([(PYTHON_EXECUTABLE or sys.executable), "-c", code], cwd=str(WECHAT_SKILL_SCRIPTS),
                              env=_wechat_env(), capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return False, "验证超时（网络或 IP 白名单问题）"
    out = (proc.stdout or "").strip().splitlines()
    last = out[-1] if out else ""
    if last == "OK":
        return True, ""
    if last.startswith("ERR:"):
        return False, last[4:].strip()[:200]
    err = (proc.stderr or "").strip().splitlines()[-1:] or ["验证失败"]
    return False, err[0][:200]


def _write_login_marker(platform: str, state: str, message: str = '') -> None:
    """回写登录标记 outputs/_login/<平台>.json（与 login_state.write_status 同格式，原子写）。
    whoami 真校验确认已登录后调用 → _account_logged_in 的快速路径此后自愈并持久。"""
    LOGIN_DIR.mkdir(parents=True, exist_ok=True)
    data = {"state": state, "message": message, "qr": "", "ts": int(time.time())}
    st = LOGIN_DIR / f'{platform}.json'
    tmp = st.with_suffix('.json.tmp')
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        os.replace(tmp, st)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass


def _account_logged_in(platform: str, cfg: dict) -> bool:
    """尽力判断某平台是否已登录。
    浏览器平台的登录态只有启动浏览器才真能知道（profile 里总有 Cookies 文件，存在≠已登录，
    会误报），故这里只信「本流程最近一次登录成功」——即 status.json == success。
    biliup 的 cookies.json 只有登录成功才生成，可直接判。"""
    backend = cfg['backend']
    if backend == 'unsupported':
        return False
    if backend == 'biliup':
        return ((COOKIE_PATH or (PROJECT_ROOT / 'cookies.json'))).is_file()
    if backend == 'wechat-oa':
        # 发布+数据都走「后台会话」→ 以 mp 后台登录成功为准；AppID 凭证作为兜底（旧配置）
        try:
            if _mp_login_status().get('state') == 'success':
                return True
        except Exception:
            pass
        return CREDENTIALS_AS_BROWSER_LOGIN and _wechat_has_credentials()
    st = LOGIN_DIR / f'{platform}.json'
    if st.is_file():
        try:
            return json.loads(st.read_text(encoding="utf-8")).get('state') == 'success'
        except Exception:
            return False
    return False


def _login_status(platform: str) -> dict:
    """读登录状态文件 + 二维码是否就绪。"""
    st = LOGIN_DIR / f'{platform}.json'
    data = {'state': 'unknown', 'message': ''}
    if st.is_file():
        try:
            d = json.loads(st.read_text(encoding="utf-8"))
            data = {'state': d.get('state', 'unknown'), 'message': d.get('message', '')}
        except Exception:
            pass
    # A runner that exits before writing its status must become an actionable error,
    # never the ambiguous ``unknown`` state shown as an endless spinner in the UI.
    proc = LOGIN_PROCESSES.get(platform)
    if data['state'] not in ('success', 'expired', 'error') and proc is not None:
        code = proc.poll()
        if code is not None:
            data = {'state': 'error', 'message': f'登录程序异常退出（退出码 {code}），请查看 outputs/_login/{platform}.log'}
    qr = LOGIN_DIR / f'{platform}.png'
    if data['state'] in ('qr_ready', 'window_login') and qr.is_file():
        data['qr'] = f'_login/{platform}.png'
        try:
            data['qrTs'] = qr.stat().st_mtime_ns // 1_000_000
        except OSError:
            data['qrTs'] = 0
    else:
        data['qr'] = ''
        data['qrTs'] = 0
    return data


async def api_accounts():
    return [
        {'platform': pf, 'name': cfg['name'], 'backend': cfg['backend'],
         'supported': cfg['backend'] != 'unsupported',
         'loggedIn': _account_logged_in(pf, cfg),
         'note': cfg.get('note', '')}
        for pf, cfg in LOGIN_RUNNERS.items()
    ]


async def api_login_start(platform: str, restart: bool = False):
    if platform not in LOGIN_RUNNERS:
        raise HTTPException(404, '未知平台')
    lock = _LOGIN_START_LOCKS.setdefault(platform, asyncio.Lock())
    async with lock:
        return await _start_login(platform, restart)


async def _start_login(platform: str, restart: bool = False):
    """启动后台登录并立即返回，二维码由前端状态轮询获取。"""
    cfg = LOGIN_RUNNERS.get(platform)
    if not cfg:
        raise HTTPException(404, '未知平台')
    backend = cfg['backend']
    if backend == 'unsupported':
        raise HTTPException(400, f"{cfg['name']} 暂不可用：{cfg.get('note', '')}")
    if backend == 'wechat-oa':
        # 公众号不走扫码：前端应改用凭证表单提交到 /api/accounts/{platform}/credentials。
        return {'mode': 'credentials', 'configured': _wechat_has_credentials(),
                'message': '微信公众号请填写 AppID / AppSecret'}
    existing = LOGIN_PROCESSES.get(platform)
    if existing is not None and existing.poll() is None:
        if not restart:
            return {'mode': 'qr', **_login_status(platform)}
        try:
            existing.terminate()
            await asyncio.to_thread(existing.wait, timeout=8)
        except subprocess.TimeoutExpired:
            raise HTTPException(409, '上一次登录仍在退出，请稍后重试') from None
        LOGIN_PROCESSES.pop(platform, None)
    LOGIN_DIR.mkdir(parents=True, exist_ok=True)
    qr = LOGIN_DIR / f'{platform}.png'
    status = LOGIN_DIR / f'{platform}.json'
    for f in (qr, status):
        try:
            f.unlink()
        except OSError:
            pass
    if backend == 'xhs':
        cmd = [(PYTHON_EXECUTABLE or sys.executable), str(SHARED_SCRIPTS / 'xhs_publish.py'), 'login', '--no-proxy',
               '--qr-out', str(qr), '--status-file', str(status), '--timeout', str(LOGIN_TIMEOUT)]
    elif backend == 'biliup':
        # B站：TV 端扫码登录 API 生成二维码 + 写 biliup cookie（biliup login 需真终端，前端用不了）
        cmd = [(PYTHON_EXECUTABLE or sys.executable), str(SHARED_SCRIPTS / 'bili_login.py'), 'login',
               '--qr-out', str(qr), '--status-file', str(status),
               '--cookie', str((COOKIE_PATH or (PROJECT_ROOT / 'cookies.json'))), '--timeout', str(LOGIN_TIMEOUT)]
    elif backend == 'douyin':
        code_file = LOGIN_DIR / f'{platform}.code'
        try:
            code_file.unlink()
        except OSError:
            pass
        cmd = [(PYTHON_EXECUTABLE or sys.executable), str(SHARED_SCRIPTS / 'douyin_publish.py'), 'login',
               '--no-proxy',
               '--qr-out', str(qr), '--status-file', str(status),
               '--sms-code-file', str(code_file), '--timeout', str(LOGIN_TIMEOUT)]
    else:
        cmd = [(PYTHON_EXECUTABLE or sys.executable), str(SHARED_SCRIPTS / 'web_publisher.py'), 'login-qr',
               '--platform', cfg['wp'], '--qr-out', str(qr), '--status-file', str(status),
               '--timeout', str(LOGIN_TIMEOUT)]
    # 新登录开始 → 清掉旧的 whoami 缓存（登录前可能缓存了「未登录」），避免登录成功后仍读到旧结果
    with _WHOAMI_LOCK:
        _WHOAMI_CACHE.pop(platform, None)
    log_path = LOGIN_DIR / f'{platform}.log'
    log_file = log_path.open('a', encoding='utf-8')
    login_env = _proxy_env()
    login_env['PYTHONIOENCODING'] = 'utf-8'
    login_env['PYTHONUTF8'] = '1'
    try:
        proc = subprocess.Popen(_account_command(platform, cmd), cwd=str(PROJECT_ROOT), env=login_env,
                                stdout=log_file, stderr=subprocess.STDOUT)
    finally:
        log_file.close()
    LOGIN_PROCESSES[platform] = proc
    s = _login_status(platform)
    if s['state'] == 'unknown':
        s.update(state='starting', message='正在启动浏览器并准备二维码…')
    return {'mode': 'qr', **s}


async def api_login_status(platform: str):
    if platform not in LOGIN_RUNNERS:
        raise HTTPException(404, '未知平台')
    s = _login_status(platform)
    if s.get('state') == 'success':
        # 登录刚成功 → 清掉登录前缓存的「未登录」whoami 结果，令下次 whoami 重新真校验；
        # 否则卡片会因 WHOAMI_TTL(600s) 内的旧 false 持续显示「未登录」（本次视频号问题的根因）。
        # 只清缓存、不改任何登录/检测逻辑。
        with _WHOAMI_LOCK:
            _WHOAMI_CACHE.pop(platform, None)
    return {'mode': 'qr', **s}


class SmsCodeRequest(BaseModel):
    code: str


async def api_login_sms(platform: str, req: SmsCodeRequest):
    """回填短信验证码：写入 runner 轮询的一次性验证码文件（见 login_state.read_sms_code）。

    登录 runner 检测到风控短信墙时把状态置 sms_required，前端弹输入框，用户把手机
    收到的验证码提交到这里，runner 读走后填码提交，继续完成登录。
    """
    if platform not in LOGIN_RUNNERS:
        raise HTTPException(404, '未知平台')
    code = ''.join(ch for ch in (req.code or '') if ch.isdigit())
    if not (4 <= len(code) <= 8):
        raise HTTPException(400, '验证码应为 4-8 位数字')
    LOGIN_DIR.mkdir(parents=True, exist_ok=True)
    (LOGIN_DIR / f'{platform}.code').write_text(code, encoding='utf-8')
    return {'ok': True}


class WechatCredentials(BaseModel):
    appId: str = ''
    appSecret: str = ''
    name: str = ''
    author: str = ''


async def api_get_credentials(platform: str):
    """读取凭证式平台（目前仅公众号）的已配置状态（AppID 脱敏，AppSecret 不回传）。"""
    cfg = LOGIN_RUNNERS.get(platform)
    if not cfg or cfg.get('backend') != 'wechat-oa':
        raise HTTPException(404, '该平台不使用凭证登录')
    acc = _wechat_web_account()
    app_id = acc.get('app_id', '') or ''
    return {
        'configured': bool(app_id and acc.get('app_secret')),
        'appIdMasked': (app_id[:6] + '***' + app_id[-4:]) if len(app_id) > 10 else ('***' if app_id else ''),
        'name': acc.get('name', '') or '',
        'author': acc.get('author', '') or '',
    }


async def api_save_credentials(platform: str, req: WechatCredentials):
    """保存凭证式平台（公众号）的 AppID/AppSecret，写入 skill 配置并调官方接口验证。"""
    cfg = LOGIN_RUNNERS.get(platform)
    if not cfg or cfg.get('backend') != 'wechat-oa':
        raise HTTPException(404, '该平台不使用凭证登录')
    app_id = (req.appId or '').strip()
    app_secret = (req.appSecret or '').strip()
    if not app_id or not app_secret:
        raise HTTPException(400, 'AppID 和 AppSecret 都不能为空')
    _wechat_save_credentials(app_id, app_secret, name=req.name.strip(), author=req.author.strip())
    # 验证要真连微信接口（最长 30s）：丢线程池，避免卡住整个事件循环
    ok, msg = await asyncio.to_thread(_wechat_verify_token)
    with _WHOAMI_LOCK:
        _WHOAMI_CACHE.pop(platform, None)
    if ok:
        _write_login_marker(platform, 'success', req.name.strip() or '微信公众号')
        return {'ok': True, 'message': '公众号凭证已保存并验证通过'}
    # 校验失败：凭证已存（下次改正后可直接重试），但明确告知失败原因（常见 40164 IP 白名单 / 40125 密钥错误）
    return {'ok': False, 'message': f'凭证已保存但验证未通过：{msg}。若是 40164 请把服务器出口 IP 加入公众号 IP 白名单。'}


def _mp_login_status() -> dict:
    """读公众号后台(mp)登录状态 + 二维码（文件由 weixin_mp_stats.py login 写）。"""
    st = LOGIN_DIR / "wechat-oa-mp.json"
    data = {"state": "unknown", "message": ""}
    if st.is_file():
        try:
            d = json.loads(st.read_text(encoding="utf-8"))
            data = {"state": d.get("state", "unknown"), "message": d.get("message", "")}
        except Exception:
            pass
    proc = LOGIN_PROCESSES.get("wechat-oa-mp")
    if data["state"] not in ("success", "expired", "error") and proc is not None and proc.poll() is not None:
        data = {"state": "error", "message": f"登录程序退出（码 {proc.poll()}），见 outputs/_login/wechat-oa-mp.log"}
    qr = LOGIN_DIR / "wechat-oa-mp.png"
    if data["state"] in ("qr_ready", "window_login") and qr.is_file():
        data["qr"] = "_login/wechat-oa-mp.png"
        try:
            data["qrTs"] = qr.stat().st_mtime_ns // 1_000_000
        except OSError:
            data["qrTs"] = 0
    else:
        data["qr"] = ""
        data["qrTs"] = 0
    return data


def _stop_mp_login_on_shutdown() -> None:
    """正常重启 Web 时回收扫码进程，避免它继续写入下一次登录的状态。"""
    proc = LOGIN_PROCESSES.pop("wechat-oa-mp", None)
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        _write_login_marker("wechat-oa-mp", "expired", "服务已重启，请重新扫码登录")


def _stop_login_processes_on_shutdown() -> None:
    """Release only the exact Popen handles owned by this native context."""
    _stop_mp_login_on_shutdown()
    for platform, process in list(LOGIN_PROCESSES.items()):
        LOGIN_PROCESSES.pop(platform, None)
        if process.poll() is not None:
            continue
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        _write_login_marker(platform, 'expired', '服务已重启，请重新扫码登录')


async def api_mp_login_start(platform: str):
    """启动「公众号后台」扫码登录（数据中心取数用，管理员级会话，独立于 AppID 凭证）。
    默认直连起 Playwright 出二维码；受限网络可设 EASEL_PROXY / https_proxy 走正向代理。"""
    cfg = LOGIN_RUNNERS.get(platform)
    if not cfg or cfg.get("backend") != "wechat-oa":
        raise HTTPException(404, "该平台不使用公众号后台登录")
    # 重复点击复用正在进行的登录，不能删除其二维码或启动第二个 Chromium。
    proc = LOGIN_PROCESSES.get("wechat-oa-mp")
    if proc is not None and proc.poll() is None:
        return {"mode": "qr", **_mp_login_status()}
    LOGIN_DIR.mkdir(parents=True, exist_ok=True)
    for f in (LOGIN_DIR / "wechat-oa-mp.png", LOGIN_DIR / "wechat-oa-mp.json"):
        try:
            f.unlink()
        except OSError:
            pass
    proxy_environment = _proxy_env()
    wx_proxy = proxy_environment.get("EASEL_PROXY") or proxy_environment.get("https_proxy") or ""
    cmd = [(PYTHON_EXECUTABLE or sys.executable), str(SHARED_SCRIPTS / "weixin_mp_stats.py"), "login",
           "--proxy", wx_proxy, "--qr-out", str(LOGIN_DIR / "wechat-oa-mp.png"),
           "--status-file", str(LOGIN_DIR / "wechat-oa-mp.json"), "--timeout", "240"]
    log_file = (LOGIN_DIR / "wechat-oa-mp.log").open("a", encoding="utf-8")
    env = _proxy_env()
    env.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    proc = subprocess.Popen(_account_command(platform, cmd), cwd=str(PROJECT_ROOT), env=env,
                            stdout=log_file, stderr=subprocess.STDOUT)
    log_file.close()
    LOGIN_PROCESSES["wechat-oa-mp"] = proc
    status = _mp_login_status()
    if status["state"] == "unknown":
        status.update(state="starting", message="正在启动浏览器并准备二维码…")
    return {"mode": "qr", **status}


async def api_mp_login_status(platform: str):
    cfg = LOGIN_RUNNERS.get(platform)
    if not cfg or cfg.get("backend") != "wechat-oa":
        raise HTTPException(404, "该平台不使用公众号后台登录")
    return {"mode": "qr", **_mp_login_status()}


async def api_account_whoami(platform: str, force: bool = False):
    if platform not in LOGIN_RUNNERS:
        raise HTTPException(404, '未知平台')
    task = _WHOAMI_TASKS.get(platform)
    if task is None or task.done():
        task = asyncio.create_task(_check_account_whoami(platform, force))
        _WHOAMI_TASKS[platform] = task
        def finish(completed):
            if _WHOAMI_TASKS.get(platform) is completed:
                _WHOAMI_TASKS.pop(platform, None)

        task.add_done_callback(finish)
    return await asyncio.shield(task)


async def _check_account_whoami(platform: str, force: bool = False):
    """真校验登录态 + 读昵称/头像（起 headless 浏览器，数秒）。前端开页后台调用以自愈假阳性。
    带 TTL 进程内缓存（避免账号页+工作台重复起浏览器）；确认已登录则回写标记，令快速路径自愈。"""
    cfg = LOGIN_RUNNERS.get(platform)
    if not cfg:
        raise HTTPException(404, '未知平台')
    backend = cfg['backend']
    if backend == 'unsupported':
        return {'loggedIn': False, 'name': '', 'avatar': ''}
    if backend == 'wechat-oa':
        if _mp_login_status()['state'] != 'success':
            acc = _wechat_web_account()
            return {'loggedIn': _account_logged_in(platform, cfg),
                    'name': acc.get('name', '') or '微信公众号', 'avatar': ''}
    process_key = 'wechat-oa-mp' if backend == 'wechat-oa' else platform
    login_process = LOGIN_PROCESSES.get(process_key)
    if login_process is not None and login_process.poll() is None:
        if (_mp_login_status() if backend == 'wechat-oa' else _login_status(platform))['state'] == 'success':
            try:
                await asyncio.to_thread(login_process.wait, timeout=8)
                if login_process.poll() is None:
                    raise HTTPException(409, '登录已确认，浏览器仍在保存账号，请稍后重试校验')
            except subprocess.TimeoutExpired:
                raise HTTPException(409, '登录已确认，浏览器仍在保存账号，请稍后重试校验')
        else:
            with _WHOAMI_LOCK:
                previous = _WHOAMI_CACHE.get(platform)
            return previous[1] if previous else {
                'loggedIn': _account_logged_in(platform, cfg), 'name': '', 'avatar': '',
            }
    marker_path = LOGIN_DIR / f'{process_key}.json'
    def marker_version():
        try:
            return marker_path.read_bytes()
        except OSError:
            return None

    initial_marker = marker_version()
    with _WHOAMI_LOCK:
        hit = _WHOAMI_CACHE.get(platform)
    cache_ttl = (min(WHOAMI_TTL, 60) if hit and hit[1].get('loggedIn')
                 and (not hit[1].get('name') or not hit[1].get('avatar')) else WHOAMI_TTL)
    if (not force and hit and (time.time() - hit[0]) < cache_ttl
            and hit[1]['loggedIn'] == _account_logged_in(platform, cfg)):
        return hit[1]
    if backend == 'biliup':
        cmd = [(PYTHON_EXECUTABLE or sys.executable), str(SHARED_SCRIPTS / 'bili_login.py'), 'whoami',
               '--cookie', str((COOKIE_PATH or (PROJECT_ROOT / 'cookies.json')))]
    elif backend == 'xhs':
        cmd = [(PYTHON_EXECUTABLE or sys.executable), str(SHARED_SCRIPTS / 'xhs_publish.py'), 'whoami', '--no-proxy']
    elif backend == 'wechat-oa':
        cmd = [(PYTHON_EXECUTABLE or sys.executable), str(SHARED_SCRIPTS / 'weixin_mp_stats.py'), 'whoami', '--no-proxy']
    elif backend == 'douyin':
        cmd = [(PYTHON_EXECUTABLE or sys.executable), str(SHARED_SCRIPTS / 'douyin_publish.py'), 'whoami', '--no-proxy']
    else:
        cmd = [(PYTHON_EXECUTABLE or sys.executable), str(SHARED_SCRIPTS / 'web_publisher.py'), 'whoami',
               '--platform', cfg['wp']]
    try:
        proc = await asyncio.to_thread(subprocess.run, _account_command(platform, cmd), cwd=str(PROJECT_ROOT), env=_proxy_env(),
                                       capture_output=True, text=True, encoding='utf-8',
                                       timeout=35 if backend == 'xhs' else 40 if backend in ('douyin', 'wechat-oa') else 60)
    except subprocess.TimeoutExpired:
        raise HTTPException(504, '校验超时（浏览器起不来或网络慢）')
    data = {'loggedIn': False, 'name': '', 'avatar': ''}
    confident = False
    for line in reversed((proc.stdout or '').strip().splitlines()):
        line = line.strip()
        if line.startswith('{'):
            try:
                d = json.loads(line)
                data = {'loggedIn': bool(d.get('loggedIn')), 'name': d.get('name') or '', 'avatar': d.get('avatar') or ''}
                stable_id = d.get('provider_user_id')
                if isinstance(stable_id, str) and re.fullmatch(r'[A-Za-z0-9_.:@-]{1,200}', stable_id):
                    data['provider_user_id'] = stable_id
                # 有 error 字段 = 校验本身失败（浏览器起不来/网络抖动/崩溃），不是可信的「未登录」结论
                confident = proc.returncode == 0 and isinstance(d.get('loggedIn'), bool) and not d.get('error')
                break
            except Exception:
                continue
    current_process = LOGIN_PROCESSES.get(process_key)
    if (marker_version() != initial_marker
            or (current_process is not None and current_process.poll() is None)):
        return {'loggedIn': _account_logged_in(platform, cfg), 'name': '', 'avatar': ''}
    if not confident:
        raise HTTPException(502, '未能确认当前账号身份，请稍后重试校验；原登录状态和账号资料保持不变')
    verified_logged_in = data['loggedIn']
    if backend == 'wechat-oa' and not verified_logged_in and CREDENTIALS_AS_BROWSER_LOGIN and _wechat_has_credentials():
        account = _wechat_web_account()
        data = {'loggedIn': True, 'name': account.get('name', '') or '微信公众号', 'avatar': ''}
    with _WHOAMI_LOCK:
        _WHOAMI_CACHE[platform] = (time.time(), data)
    # 回写标记：确认已登录 → 快速路径（/api/accounts、/api/analytics/platforms）此后也正确；
    # biliup 走 cookies.json 判定，不用标记文件。
    if backend != 'biliup':
        if verified_logged_in:
            _write_login_marker(process_key, 'success', data.get('name') or '')
        else:
            try:
                marker_path.unlink()
            except OSError:
                pass
    return data


async def api_logout(platform: str):
    """退出登录：删持久化浏览器 profile + 登录状态/二维码/头像文件（biliup 删 cookies.json）。"""
    cfg = LOGIN_RUNNERS.get(platform)
    if not cfg:
        raise HTTPException(404, '未知平台')
    deleted = []
    if cfg['backend'] == 'wechat-oa':
        # 1) 清 AppID 凭证（旧配置兜底）
        _wechat_clear_credentials()
        deleted.append('wechat-publisher.yaml:accounts.web')
        # 2) 停掉可能仍在跑的后台登录进程（避免它又写回 success 标记）
        proc = LOGIN_PROCESSES.pop('wechat-oa-mp', None)
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        # 3) 删 AppID 标记 + mp 后台会话标记/二维码/日志（登录态判定看的就是 wechat-oa-mp.json）
        for name in (f'{platform}.json', f'{platform}.png',
                     'wechat-oa-mp.json', 'wechat-oa-mp.png', 'wechat-oa-mp.log'):
            f = LOGIN_DIR / name
            try:
                if f.is_file():
                    f.unlink()
                    deleted.append(f.name)
            except OSError:
                pass
        # 4) 删 mp 后台浏览器持久化会话（真正退出登录）
        mpdir = (_account_profile_root(platform) / 'WeixinMpProfile').resolve()
        if _account_profile_root(platform).resolve() in mpdir.parents and mpdir.is_dir():
            shutil.rmtree(mpdir, ignore_errors=True)
            deleted.append('WeixinMpProfile')
        with _WHOAMI_LOCK:
            _WHOAMI_CACHE.pop(platform, None)
        return {'ok': True, 'deleted': deleted}
    proc = LOGIN_PROCESSES.pop(platform, None)
    if proc is not None and proc.poll() is None:
        # 与上面公众号分支同理：停掉仍在跑的登录进程，否则它会把 success 标记
        # 又写回 {platform}.json，账号在退出后“复活”成已登录。
        try:
            proc.terminate()
            await asyncio.to_thread(proc.wait, timeout=5)
        except Exception:
            pass
    prof_name = cfg.get('profile')
    if prof_name:
        pdir = (_account_profile_root(platform) / prof_name).resolve()
        if _account_profile_root(platform).resolve() in pdir.parents and pdir.is_dir():
            shutil.rmtree(pdir, ignore_errors=True)
            deleted.append(prof_name)
    if cfg['backend'] == 'biliup':
        ck = (COOKIE_PATH or (PROJECT_ROOT / 'cookies.json'))
        if ck.is_file():
            ck.unlink()
            deleted.append('cookies.json')
    for suffix in ('.json', '.png', '-me.png', '.code'):
        f = LOGIN_DIR / f'{platform}{suffix}'
        try:
            if f.is_file():
                f.unlink()
                deleted.append(f.name)
        except OSError:
            pass
    with _WHOAMI_LOCK:
        _WHOAMI_CACHE.pop(platform, None)
    return {'ok': True, 'deleted': deleted}


PYTHON_EXECUTABLE = None
PROFILE_BASE = None
COOKIE_PATH = None
CREDENTIALS_AS_BROWSER_LOGIN = True


def _account_profile_root(platform):
    return Path(PROFILE_BASE(platform)) if PROFILE_BASE else BROWSER_PROFILES


def _account_command(platform, command):
    command = list(command)
    if PROFILE_BASE and LOGIN_RUNNERS[platform]['backend'] != 'biliup':
        command += ['--profile-base', str(_account_profile_root(platform))]
    return command


EXPORTS = ('LOGIN_TIMEOUT', 'LOGIN_PROCESSES', 'WHOAMI_TTL', '_WHOAMI_CACHE', '_WHOAMI_LOCK', '_WHOAMI_TASKS', '_LOGIN_START_LOCKS', 'LOGIN_RUNNERS', 'WECHAT_WEB_ACCOUNT', '_wechat_load_yaml', '_wechat_web_account', '_wechat_has_credentials', '_wechat_save_credentials', '_wechat_clear_credentials', '_wechat_verify_token', '_write_login_marker', '_account_logged_in', '_login_status', 'api_accounts', 'api_login_start', '_start_login', 'api_login_status', 'SmsCodeRequest', 'api_login_sms', 'WechatCredentials', 'api_get_credentials', 'api_save_credentials', '_mp_login_status', '_stop_mp_login_on_shutdown', '_stop_login_processes_on_shutdown', 'api_mp_login_start', 'api_mp_login_status', 'api_account_whoami', '_check_account_whoami', 'api_logout', 'PYTHON_EXECUTABLE', 'PROFILE_BASE', 'COOKIE_PATH', 'CREDENTIALS_AS_BROWSER_LOGIN', '_account_profile_root', '_account_command')

def bind(context=None, *, into=None):
    return bind_functions(sys.modules[__name__], EXPORTS, context, into=into)


def create_accounts_context(root, *, outputs=None, scripts=None, profiles=None,
                            environment=None, python=None, profile_base=None,
                            cookie_path=None, credential_store=None,
                            process_factory=None, process_run=None,
                            credentials_as_browser_login=False):
    """Bind the native lifecycle to explicit roots and host-owned secrets.

    No credentials or process environment are installed globally. Each context
    owns its process registry, locks, TTL cache and native request functions.
    """
    from types import SimpleNamespace
    root = Path(root).resolve()
    scripts = Path(scripts or root / 'skills/shared/scripts').resolve()
    def child_environment():
        values = environment() if callable(environment) else environment
        values = dict(os.environ if values is None else values)
        values.setdefault('EASEL_ROOT', str(root))
        values.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
        return values
    dependencies = {
        'PROJECT_ROOT': root, 'OUTPUTS_DIR': Path(outputs or root / 'outputs').resolve(),
        'SHARED_SCRIPTS': scripts, 'BROWSER_PROFILES': Path(profiles or root / '.runtime/browser-profiles').resolve(),
        'LOGIN_DIR': Path(outputs or root / 'outputs').resolve() / '_login',
        'WECHAT_SKILL_DIR': root / 'skills/builtin/skill-wechat-publisher',
        'WECHAT_SKILL_SCRIPTS': root / 'skills/builtin/skill-wechat-publisher/scripts',
        'WECHAT_CONFIG_YAML': root / 'skills/builtin/skill-wechat-publisher/wechat-publisher.yaml',
        'PYTHON_EXECUTABLE': str(python) if python else None,
        'PROFILE_BASE': profile_base, 'COOKIE_PATH': Path(cookie_path) if cookie_path else None,
        'CREDENTIALS_AS_BROWSER_LOGIN': credentials_as_browser_login,
        'LOGIN_RUNNERS': {key: dict(value) for key, value in LOGIN_RUNNERS.items()},
        'LOGIN_PROCESSES': {}, '_WHOAMI_CACHE': {}, '_WHOAMI_TASKS': {},
        '_WHOAMI_LOCK': threading.Lock(), '_LOGIN_START_LOCKS': {},
        '_proxy_env': child_environment, '_wechat_env': child_environment,
    }
    if process_factory is not None or process_run is not None:
        dependencies['subprocess'] = SimpleNamespace(
            **{key: getattr(subprocess, key) for key in dir(subprocess) if not key.startswith('__')})
        if process_factory is not None:
            dependencies['subprocess'].Popen = process_factory
        if process_run is not None:
            dependencies['subprocess'].run = process_run
    if credential_store is not None:
        for name in ('_wechat_web_account', '_wechat_save_credentials',
                     '_wechat_clear_credentials', '_wechat_verify_token'):
            callback = (credential_store.get(name) if isinstance(credential_store, dict)
                        else getattr(credential_store, name, None))
            if callback is not None:
                dependencies[name] = callback
    return bind(dependencies)
