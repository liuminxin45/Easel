"""Easel Web — FastAPI 后端（含 SSE 流式输出）."""
from __future__ import annotations

import asyncio
import base64
import mimetypes
import os
if os.name == "nt":
    import msvcrt
else:
    import fcntl
import hashlib
import ipaddress
import json
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from contextlib import asynccontextmanager
import ipaddress
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, StrictBool
from sse_starlette.sse import EventSourceResponse

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from easel.gateway_endpoint import chat_completions_url, healthz_url, port_source
from easel.openclaw_cmd import openclaw_base_cmd
from easel.persona import (load_profile_text, persona_prefix, chat_turn_message,
                           profile_exists, valid_persona_name, _FILE_ORDER)
from easel.timeouts import TIMEOUT_CHAT, TIMEOUT_DIRECT, TIMEOUT_PRODUCE
from easel.manual_publish import build_package, publishing_mode
from easel.direct_api import (DirectAPIError, SYSTEM_PROMPT, api_config, api_mode,
                              history_path, read_settings, stream_chat)
from easel import harnesses
from easel.harnesses import store as harness_store
from easel.harnesses.base import HarnessError, RunRequest
try:
    from easel.gateway_questions import (
        GatewayClient, GatewayQuestionError, GatewayQuestionClosedError, GatewayUnsupportedError,
        question_bridge_supported)
except Exception:  # 兼容缺失依赖：问答题桥接降级为关闭
    GatewayClient = None  # type: ignore
    GatewayQuestionError = None  # type: ignore
    GatewayQuestionClosedError = None  # type: ignore
    GatewayUnsupportedError = None  # type: ignore
    question_bridge_supported = None  # type: ignore

# 问答题桥接的一次性诊断标记：连接失败/旧版本无 question RPC 的告警每进程只打一次，
# 避免每开一个新会话就在后端刷一行同样的错（用户反馈的噪音）。
_QBRIDGE_WARNED: set[str] = set()
# 进程级熔断：一旦确认桥接不可用（旧版本无 question RPC、或 connect 持续失败如
# NOT_PAIRED/scope-upgrade），就彻底停掉桥接，后续每轮直接跳过——不再连接，也就不再
# 每轮在网关上触发新的配对/权限申请。恢复需重启 easel web。
_QBRIDGE_DISABLED = False


def _qbridge_warn_once(key: str, message: str) -> None:
    if key in _QBRIDGE_WARNED:
        return
    _QBRIDGE_WARNED.add(key)
    print(message, file=sys.stderr, flush=True)


def _gateway_question_timing(question: dict) -> dict:
    return {key: value for key in ("createdAtMs", "expiresAtMs")
            if isinstance(value := question.get(key), (int, float))
            and not isinstance(value, bool) and 0 <= value <= 9_007_199_254_740_991}


def _gateway_question_state(question: dict | None) -> dict:
    if question is None:
        return {"status": "not_found"}
    status = question.get("status")
    if status not in {"pending", "answered", "resolved", "cancelled", "expired", "closed"}:
        status = "unknown"
    return {"status": status, **_gateway_question_timing(question)}


def _poll_gateway_questions(sk: str, proc, emit, stop: threading.Event) -> None:
    global _QBRIDGE_DISABLED
    if _QBRIDGE_DISABLED or GatewayClient is None:
        return
    if question_bridge_supported is not None and not question_bridge_supported():
        _QBRIDGE_DISABLED = True
        _qbridge_warn_once(
            "unsupported", "[question-bridge] 当前 OpenClaw 版本无 question RPC（需 2026.9.x+），"
            "已跳过 ask_user 选项卡片桥接，改用文字问答。")
        return
    client = None
    pushed: set[str] = set()
    pending: set[str] = set()
    final_check = False
    try:
        try:
            client = GatewayClient()
            client.connect()
        except Exception:
            _QBRIDGE_DISABLED = True
            _qbridge_warn_once(
                "connect", "[question-bridge] connect gateway failed，已停用桥接（本进程），"
                "ask_user 改用文字问答。")
            return
        while True:
            try:
                items = client.list_questions(session_key=f"agent:main:{sk}", status="pending")
            except GatewayUnsupportedError:
                _QBRIDGE_DISABLED = True
                _qbridge_warn_once(
                    "unsupported", "[question-bridge] 当前 OpenClaw 版本无 question RPC，"
                    "已停用 ask_user 选项卡片桥接（需 2026.9.x+）。")
                return
            except Exception:
                if proc.poll() is not None or stop.wait(2):
                    return
                continue
            current = {item["id"] for item in items if item.get("id")}
            for identifier in sorted(pending - current):
                try:
                    status = _gateway_question_state(client.get_question(identifier))["status"]
                except GatewayQuestionClosedError as error:
                    status = error.status
                except GatewayUnsupportedError:
                    status = "closed"
                except Exception:
                    current.add(identifier)
                    continue
                if status in ("pending", "unknown"):
                    current.add(identifier)
                    continue
                emit("question_closed", json.dumps({"id": identifier, "status": status}))
            for item in items:
                identifier = item.get("id")
                if identifier and identifier not in pushed:
                    pushed.add(identifier)
                    emit("question", json.dumps({
                        "id": identifier, "questions": item.get("questions", []),
                        "expiresAtMs": None, **_gateway_question_timing(item),
                    }, ensure_ascii=False))
            pending = current
            if proc.poll() is not None or stop.is_set():
                if pending and not final_check:
                    final_check = True
                    continue
                return
            stop.wait(2)
    finally:
        if client is not None:
            client.close()

PROFILES_DIR = PROJECT_ROOT / "profiles"
SKILLS_DIR = PROJECT_ROOT / "skills"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"

STATIC_DIR = Path(__file__).resolve().parent / "static"
REACT_DIR = Path(__file__).resolve().parent / "frontend" / "dist"
OPENCLAW_PROFILE = "easel"
# 对话传输层：http＝直连常驻 gateway 的 OpenAI 兼容端点，agent 在 gateway 进程里直接跑，
# 省掉每轮 spawn `openclaw agent` 瘦客户端的冷启动（本机实测同一句话：CLI 7.1-7.6s/轮，
# HTTP 4.1-4.5s/轮，差值就是客户端冷启动）；cli＝每轮 spawn 的老路径。
#
# 默认 http，但**只对新会话生效**：见 _resolve_transport。同一会话绝不中途换边——两条路径
# 写的是不同的 transcript，换边等于静默清空整段对话记忆（实测拿 CLI 去续一个 HTTP 起的会话，
# agent 直接答"无历史"）。设 EASEL_CHAT_TRANSPORT=cli 可整机回到老路径。
CHAT_TRANSPORT = os.environ.get("EASEL_CHAT_TRANSPORT", "http").strip().lower()
# 这里曾有个 OPENCLAW_WORKSPACE 常量，写死的是 2026.6.x 布局（~/.openclaw/workspace-<profile>）。
# 全仓无人引用，但留着迟早会被新代码拿去用，而 OpenClaw 的布局 2026.9.x 起已经变成
# <state 目录>/workspace（issue #19）。要用 workspace 路径请走 easel.openclaw_workspace.workspace_dir()，
# 它直接问 openclaw 要运行时真值，不猜版本。
# OpenClaw 会话历史（transcript）目录：<profile 配置目录>/agents/main/sessions/<session-id>.jsonl
# 配置/状态目录统一走 easel.openclaw_workspace：支持 EASEL_OPENCLAW_STATE_DIR 覆盖（#62）。
from easel.openclaw_workspace import config_path as _oc_config_path, state_dir as _oc_state_dir
OPENCLAW_SESSIONS_DIR = _oc_state_dir() / "agents" / "main" / "sessions"

# 思考档位（每轮 --thinking）。前后端已完整支持展示思考：后端把 thinking_delta 转成 SSE
# `thinking` 事件，前端 MessageBubble 渲染「💭 思考过程」并在流式结束后持久保留。面板里有没有
# 内容取决于网关——支持 extended-thinking 的网关会按档位回传思考流；不支持的（如内网 codewiz，
# 实测 transcript 里 assistant 只有 text 块、thinking 恒为 0）面板留空，调高档位也不会有内容。
# 默认 medium：让支持思考的部署直接显示较完整思考；EASEL_THINKING_LEVEL 可覆盖（low 提速 / high 更详尽）。
THINKING_LEVEL = (os.environ.get("EASEL_THINKING_LEVEL", "").strip() or "medium")

# gateway 进程把原始事件流（token/thinking/收尾）写到的**单个共享文件**。
# 关键：`openclaw agent` 只是瘦客户端，没有 --raw-stream 标志——只有常驻 gateway 按它自己
# 的 OPENCLAW_RAW_STREAM/OPENCLAW_RAW_STREAM_PATH 写这个文件（见 scripts/gateway.sh）。
# web 侧 tail 它做流式；默认值必须与 gateway.sh 里 EASEL_RAW_STREAM_PATH 的默认一致。
SHARED_RAW_STREAM = Path(os.environ.get("EASEL_RAW_STREAM_PATH", "/tmp/easel-raw-stream.jsonl"))


class _GatewayHttpProc:
    """HTTP 直连模式下的「伪进程」：给主循环 / 停止逻辑提供 poll/wait/kill 兼容面。"""

    def __init__(self) -> None:
        self._done = False
        self._task = None

    def finish(self) -> None:
        self._done = True

    def poll(self):
        return 0 if self._done else None

    def terminate(self) -> None:
        self._done = True
        if self._task is not None:
            try:
                self._task.cancel()
            except Exception:  # noqa: BLE001
                pass

    def kill(self) -> None:
        self.terminate()

    def wait(self, timeout=None):  # 兼容 await asyncio.to_thread(proc.wait, ...)
        # 必须真的等：主循环拿它来决定「能不能放掉会话双锁」。提前返回会让下一轮在
        # 上一轮可能还在写同一份 transcript 时就启动 —— 正是双锁要防的并发写。
        deadline = None if timeout is None else time.monotonic() + timeout
        while not self._done:
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired("gateway-http-turn", timeout)
            time.sleep(0.05)
        return 0


_HTTP_READY_CACHE: dict = {"at": -1e9, "ok": False}
_HTTP_READY_TTL = 60.0          # 探针要打一次真端点，别每轮都付这个 RTT


def _gateway_http_ready(force: bool = False) -> bool:
    """探测 gateway 的 /v1/chat/completions 到底挂没挂上。

    **不能探 /v1/models**：那个路径会被 gateway 控制台 SPA 的 catch-all 接走，端点没开也照样
    返回 200（body 是 OpenClaw Control 的 HTML 首页）—— 探了等于没探，只要网关活着就恒为 True。
    这里直接打真端点：openclaw 要求 gateway.http.endpoints.chatCompletions.enabled === true
    才挂这条路由（默认 false），没开就是 404；开了则因为 body 缺 messages 返回 400。用 400 当
    "端点在"的证据，既走完整条路由又不消耗一次模型调用。
    """
    now = time.monotonic()
    if not force and now - _HTTP_READY_CACHE["at"] < _HTTP_READY_TTL:
        return bool(_HTTP_READY_CACHE["ok"])
    ok = False
    try:
        import httpx  # noqa: F401  HTTP 路径全靠它做 SSE；没装就当端点不可用，回退 CLI
        rq = urllib.request.Request(
            chat_completions_url(), data=b"{}",
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(rq, timeout=3):
                ok = False       # 空 body 还给 200 说明这不是我们要的端点，不敢用
        except urllib.error.HTTPError as e:
            ok = e.code == 400   # 400 Missing user message ⇒ 端点在；404 ⇒ 没开
    except Exception:  # noqa: BLE001
        ok = False
    _HTTP_READY_CACHE.update(at=now, ok=ok)
    return ok


def _heal_openclaw_session(sk: str) -> None:
    """每轮 spawn openclaw 前，清洗该会话历史里的无签名 thinking 块 + 空消息（自愈防回放失效）。

    best-effort：任何异常都不阻断对话（清洗失败大不了退回原样，仍可 /new）。
    """
    try:
        import session_heal  # scripts/session_heal.py（已加入 sys.path）
        p = OPENCLAW_SESSIONS_DIR / f"{_openclaw_session_id(sk)}.jsonl"
        if p.is_file():
            st = session_heal.sanitize_history_file(p)
            if st.get("changed"):
                print(f"[session-heal] {p.name}: -{st['thinking_removed']} thinking / "
                      f"-{st['msgs_dropped']} empty", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"[session-heal] 跳过（{e}）", file=sys.stderr, flush=True)


# 制作层/直接执行层/chat 超时统一走 easel/timeouts.py（CLI/Web/skill 三入口单一真相源）

SHARED_SCRIPTS = PROJECT_ROOT / "skills" / "shared" / "scripts"
if str(SHARED_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SHARED_SCRIPTS))

from model_registry import model_group

BROWSER_PROFILES = Path.home() / ".easel-browser-profiles"
LOGIN_DIR = OUTPUTS_DIR / "_login"
PUBLISH_DIR = OUTPUTS_DIR / "_publish"   # 异步发布的状态/验证码文件（抖音发布可能触发短信墙）
PROFILE_BUILD_DIR = OUTPUTS_DIR / "_profile_build"   # 异步画像构建的状态文件（避免长请求被代理超时）
DEBUG_DIR = OUTPUTS_DIR / "_debug"   # 诊断日志（对话流收尾情况等），_ 前缀不进内容库
SESSIONS_DIR = OUTPUTS_DIR / "_sessions"   # 每会话最近一轮的完整结果，供 SSE 连接中断后前端取回
from easel.web_services.accounts import bind as _bind_shared_accounts
_bind_shared_accounts(into=globals())

# whoami 真校验（起 headless 浏览器，数秒）的进程内缓存：避免账号页 + 工作台重复起浏览器。


# ---- 微信公众号（wechat-oa）凭证式接入 ----
# 复用 skill-wechat-publisher 的发布引擎与配置：凭证存在其 wechat-publisher.yaml，
# 发布/取数脚本都从这里读账号。web 侧统一用账号 key "web"。
WECHAT_SKILL_DIR = PROJECT_ROOT / "skills" / "builtin" / "skill-wechat-publisher"
WECHAT_SKILL_SCRIPTS = WECHAT_SKILL_DIR / "scripts"
WECHAT_PUBLISH_SCRIPT = WECHAT_SKILL_SCRIPTS / "publish.py"
WECHAT_CONFIG_YAML = WECHAT_SKILL_DIR / "wechat-publisher.yaml"


from easel.web_services.settings import bind as _bind_shared_settings
_bind_shared_settings(into=globals())


def _model_spec(group: str, label: str | None = None) -> dict:
    spec = model_group(group)
    return {
        "label": label or spec["label"],
        "settings": spec.get("settings", []),
        "providers": spec["providers"],
    }


def _short_drama_spec() -> dict:
    """Image is required; video and cloud voice settings remain optional enhancements."""
    image = model_group("image")
    optional = []
    for group_name in ("video", "voice"):
        group = model_group(group_name)
        optional.extend({**key, "required": False} for key in group.get("settings", []))
        for provider in group["providers"]:
            optional.extend({**key, "required": False} for key in provider["keys"])
    seen = set()
    optional = [key for key in optional if not (key["env"] in seen or seen.add(key["env"]))]
    return {
        "label": "AI 短剧（生图必需 + 生视频/云配音可选）",
        "settings": [],
        "providers": [{
            "id": "drama",
            "name": "关键帧生图（必需）+ 视频生成与闭源配音（可选）",
            "keys": [*image["providers"][0]["keys"], *optional],
        }],
    }

SKILL_API_REQUIREMENTS: dict[str, dict] = {
    "ai-image-gen": _model_spec("image"),
    "ecom-details-image": _model_spec("image", "电商配图（AI 生图）"),
    "ai-video-gen": _model_spec("video"),
    "ai-music": _model_spec("music"),
    "voice-clone": _model_spec("voice", "声音克隆 / 云端 TTS"),
    # AI 短剧：编排 ai-image-gen(关键帧,必需) + ai-video-gen(生视频,可选,缺则退化图片短剧)。
    # 以生图为「已配置」基线（缺生图无法出关键帧）；生视频 key 同框可选填，也可在 ai-video-gen 卡片配。
    "short-drama": _short_drama_spec(),
    # 论文解读：MinerU 与生图均为可选（缺 MinerU 用 pdfplumber 兜底、缺生图用信息图/图表）。
    # 全 key 可选 → 不误报感叹号；但仍进注册表以便就地填 MINERU_API_TOKEN（无其它叶子 skill 承载它）。
    "paper-explainer": {
        "label": "论文解读（MinerU / 生图 均可选）",
        "providers": [
            {
                "id": "paper",
                "name": "MinerU 解析(可选, 缺则 pdfplumber) + 封面/概念生图(可选)",
                "keys": [
                    _k("MINERU_API_TOKEN", "MinerU API Token（可选，缺则用 pdfplumber 兜底）",
                       required=False),
                    _k("IMG_API_KEY", "生图 API Key（可选，用于封面/概念图）", required=False,
                       aliases=["OPENAI_API_KEY", "API_KEY"]),
                    _k("IMG_BASE_URL", "生图 API 根地址（可选）", required=False, secret=False,
                       aliases=["OPENAI_BASE_URL", "OPENAI_API_BASE", "BASE_URL"]),
                ],
            },
        ],
    },
}

_ENV_ALLOWLIST: set[str] = {
    "EASEL_DIRECT_API_BASE_URL", "EASEL_DIRECT_API_KEY", "EASEL_DIRECT_API_MODEL",
}
for _spec in SKILL_API_REQUIREMENTS.values():
    for _key in _spec.get("settings", []):
        _ENV_ALLOWLIST.add(_key["env"])
        _ENV_ALLOWLIST.update(_key.get("aliases", []))
    for _prov in _spec["providers"]:
        for _key in _prov["keys"]:
            _ENV_ALLOWLIST.add(_key["env"])
            _ENV_ALLOWLIST.update(_key.get("aliases", []))

ENV_FILE = PROJECT_ROOT / ".env"
_HARNESS_LOOP = None

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """应用生命周期：关机时回收公众号扫码进程（替代已弃用的 on_event）。"""
    global _HARNESS_LOOP
    _HARNESS_LOOP = asyncio.get_running_loop()
    yield
    tasks = list(_HARNESS_TASKS)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    from easel.harnesses.rpc import close_sessions
    await close_sessions()
    _HARNESS_LOOP = None
    _stop_analytics_on_shutdown()
    _stop_login_processes_on_shutdown()


app = FastAPI(title="Easel", docs_url=None, redoc_url=None, lifespan=_lifespan)

def _local_ports(env_port: str) -> set[str]:
    """本机写守卫放行的端口集合：固定的 7860/7870/5173，加上 `--port`/EASEL_PORT
    实际配置的端口——否则自定义端口跑 Easel 时，前端自己发的写请求（包括发消息
    的 /api/chat/stream）会被 local_write_guard 当跨站请求 403 掉。"""
    return {'7860', '7870', '5173', (env_port or '').strip() or '7860'}


_LOCAL_PORTS = _local_ports(os.environ.get('EASEL_PORT', ''))
_LOCAL_ORIGINS = [f'http://{host}:{port}'
                  for host in ('127.0.0.1', 'localhost') for port in _LOCAL_PORTS]
_LOCAL_ORIGINS += [o.strip() for o in os.environ.get('EASEL_EXTRA_ORIGINS', '').split(',') if o.strip()]
_EXTRA_HOSTS = [h.strip() for h in os.environ.get('EASEL_EXTRA_HOSTS', '').split(',') if h.strip()]

# VSCode/code-server 等远程开发环境常通过 VSCODE_PROXY_URI 这个反代域名访问 Easel
# （真实连接仍是本机回环，代理在同一台机器上转发）；不识别这个域名会让通过代理
# 打开的页面从第一个请求起就被下面的 TrustedHostMiddleware/CORS 拒绝——收紧前
# allow_origins=["*"] 时这条路是通的，别让这次收紧顺带堵死它。
def _proxy_uri_origin(uri: str) -> tuple[str, str] | None:
    """从 VSCODE_PROXY_URI 里取反代域名，返回 (host, origin)；解析不出 host 则 None。"""
    if not uri:
        return None
    parsed = urllib.parse.urlparse(uri)
    if not parsed.hostname:
        return None
    return parsed.hostname, f'{parsed.scheme}://{parsed.hostname}'


_proxy_origin = _proxy_uri_origin(os.environ.get('VSCODE_PROXY_URI', ''))
if _proxy_origin:
    _EXTRA_HOSTS.append(_proxy_origin[0])
    _LOCAL_ORIGINS.append(_proxy_origin[1])


def _loopback_peer(request: Request) -> bool:
    """对端是否来自回环地址。只有「没有 Origin 可判」时才用作判据。"""
    client = request.client
    if client is None:
        return False
    host = client.host or ''
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


app.add_middleware(CORSMiddleware, allow_origins=_LOCAL_ORIGINS, allow_methods=["*"], allow_headers=["*"])
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=3)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['localhost', '127.0.0.1'] + _EXTRA_HOSTS)


@app.middleware('http')
async def local_write_guard(request: Request, call_next):
    """拦住「别的网站让浏览器替我改本机状态」的写请求，同时不误伤本机调用。

    两条判据，按请求实际形态二选一：
    ① 带 Origin（浏览器跨站发起）：Origin 必须在 _LOCAL_ORIGINS 里，否则 403。
    ② 不带 Origin（curl / 本机脚本 / 测试客户端）：要求对端来自回环地址。

    局限（重要）：这套防护假定 Origin/Host 头不可伪造——对浏览器成立，对裸
    HTTP 客户端不成立。本进程仍监听 0.0.0.0（见文件底部 uvicorn.run，未随
    此中间件收紧，兼容 Docker/远程容器端口转发场景），因此局域网内能直连到
    这个端口的攻击者，只要手写 curl 一起伪造 `Origin`/`Host` 头就能绕过本
    中间件与下面的 TrustedHostMiddleware。这里防的是「浏览器打开恶意网页」
    这一类跨站攻击，不是「网络可达即视为可信」的边界——不要把本服务暴露在
    不受信任的网络（公共 WiFi、无防火墙的公网主机）上。
    """
    origin = request.headers.get('origin')
    if request.url.path == '/api/clipper' and origin and re.fullmatch(r'chrome-extension://[a-p]{32}', origin):
        headers = {
            'Access-Control-Allow-Origin': origin,
            'Access-Control-Allow-Methods': 'POST',
            'Access-Control-Allow-Headers': 'Authorization, Content-Type',
            'Vary': 'Origin',
        }
        if request.method == 'OPTIONS':
            return JSONResponse({}, headers=headers)
        response = await call_next(request)
        response.headers.update(headers)
        return response
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        allowed = origin in _LOCAL_ORIGINS if origin else _loopback_peer(request)
        if not allowed:
            return JSONResponse({'detail': '仅允许从本机工作台操作。'}, status_code=403)
    return await call_next(request)


def list_personas() -> list[dict]:
    if not PROFILES_DIR.is_dir():
        return []
    result = []
    for d in sorted(PROFILES_DIR.iterdir()):
        if not d.is_dir() or not valid_persona_name(d.name):
            continue
        desc = ''
        identity = d / 'identity.md'
        if identity.is_file():
            for line in identity.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith('#') and not line.startswith('<!--'):
                    desc = line[:80]
                    break
        result.append({'name': d.name, 'description': desc})
    return result


def find_skill(name: str) -> str | None:
    """查找 SKILL，返回完整名或 None。与 CLI skill.py 一致。"""
    cands = [name, f'skill-{name}'] if not name.startswith('skill-') else [name]
    for cand in cands:
        if (SKILLS_DIR / 'builtin' / cand / 'SKILL.md').is_file():
            return cand
    return None


def _parse_skill_md(path: Path) -> tuple[str, str, str]:
    """解析 SKILL.md → (description, layer, body)。body 为去掉 frontmatter 的正文。
    正确处理 YAML 块标量 description（`>-` / `>` / `|` 后跟缩进多行）。"""
    text = path.read_text(encoding='utf-8')
    desc, layer, body = '', '', text
    lines = text.splitlines()
    if not (lines and lines[0].strip() == '---'):
        return desc, layer, body
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == '---':
            end = i
            break
    if end is None:
        return desc, layer, body
    body = '\n'.join(lines[end + 1:]).strip()
    fm = lines[1:end]
    i = 0
    while i < len(fm):
        st = fm[i].strip()
        if st.startswith('layer:'):
            layer = st.split(':', 1)[1].strip().strip('"').strip("'")
            i += 1
        elif st.startswith('description:'):
            val = st.split(':', 1)[1].strip()
            if val and val[0] in '|>':
                block = []
                j = i + 1
                while j < len(fm):
                    if fm[j].strip() == '':
                        block.append('')
                        j += 1
                        continue
                    indent = len(fm[j]) - len(fm[j].lstrip())
                    if indent == 0:
                        break
                    block.append(fm[j].strip())
                    j += 1
                desc = ' '.join(x for x in block if x).strip()
                i = j
            else:
                desc = val.strip('"').strip("'")
                i += 1
        else:
            i += 1
    return desc, layer, body


def get_skills() -> list[dict]:
    env = _read_env()
    result = []
    sd = SKILLS_DIR / 'builtin'
    if sd.is_dir():
        for d in sorted(sd.iterdir()):
            if d.is_dir() and (d / 'SKILL.md').is_file():
                desc, layer, _ = _parse_skill_md(d / 'SKILL.md')
                needs_api = d.name in SKILL_API_REQUIREMENTS
                result.append({
                    'name': d.name,
                    'description': desc,
                    'layer': layer,
                    'needsApi': needs_api,
                    'apiConfigured': _skill_api_configured(d.name, env) if needs_api else True,
                })
    return result


def clean_agent_output(raw: str) -> str:
    lines = []
    for line in raw.splitlines():
        c = re.sub(r'\x1b\[[0-9;]*m', '', line)
        if c.startswith('[') and any(t in c[:40] for t in ('[provider-', '[agents/', '[agent/', '[plugins]', '[tools]', '[diagnostic]', '[fetch-', '[heartbeat]', '[health-', '[gateway]')):
            continue
        if c.strip():
            lines.append(c)
    return '\n'.join(lines).strip()


def _proxy_env() -> dict[str, str]:
    """返回带外网代理的环境变量（保护内网直连）。"""
    from easel.runtime_env import proxy_environment

    env = proxy_environment(dict(os.environ),
                            'localhost,127.0.0.1,10.*,*.xiaohongshu.com,*.devops.xiaohongshu.com,*.douyin.com,*.kuaishou.com,*.zhihu.com,*.bilibili.com,*.weixin.qq.com,*.qq.com')
    env.setdefault('EASEL_ROOT', str(PROJECT_ROOT))
    return env


def _publish_env() -> dict[str, str]:
    """发布子进程 env：在 _proxy_env 基础上禁用脚本侧日历自动记录——
    发布页由 web 自己回流 _schedule.json，脚本再记一次会重复。对话页 Agent 直跑
    脚本时不经过这里，flag 未设 → 脚本自动记录（见 calendar_ops.record_publish）。"""
    env = _proxy_env()
    env['EASEL_CALENDAR_AUTORECORD'] = '0'
    return env


def _wechat_env() -> dict[str, str]:
    """公众号 API 子进程 env，决定微信 API 从哪个 IP 出网（公众号白名单要求固定出口 IP）。

    两种模式：
    - 设了 WECHAT_EGRESS_PROXY（如反向隧道到你本机/固定 IP 中转）→ 让微信 API **走这个代理**出网，
      微信看到的是该代理的公网 IP，白名单加它即可。其它外网仍走公司代理。
    - 未设 → 微信 API 走**直连**（api.weixin.qq.com 进 no_proxy）。注意本机直连出口也是共享 NAT
      轮询池（见 WECHAT_OA_INTEGRATION.md §4），直连仅在出口 IP 恰好固定的机器上可靠。"""
    env = _publish_env()
    wx_hosts = ("api.weixin.qq.com", "mp.weixin.qq.com")
    egress = os.environ.get("WECHAT_EGRESS_PROXY", "").strip()
    if egress:
        # 微信 API 走指定固定出口代理；从 no_proxy 里去掉微信域名，确保不被旁路成直连。
        env["http_proxy"] = env["https_proxy"] = egress
        env["HTTP_PROXY"] = env["HTTPS_PROXY"] = egress
        kept = [h for h in env.get("no_proxy", "").split(",") if h and not any(w in h for w in wx_hosts)]
        env["no_proxy"] = ",".join(kept)
        env["NO_PROXY"] = env["no_proxy"]
    else:
        existing = env.get("no_proxy", "")
        env["no_proxy"] = (existing + "," + ",".join(wx_hosts)) if existing else ",".join(wx_hosts)
        env["NO_PROXY"] = env["no_proxy"]
    return env


def _persona_prefix(persona: str | None) -> str:
    """把画像作为消息前缀内联（复用 easel.persona，与 CLI/skill 同源）。"""
    return persona_prefix(persona)


def _read_env() -> dict[str, str]:
    """宽松解析项目根 .env → {KEY: value}。跳过注释与非 KEY=value 行（容忍多行值残行）。"""
    result = {}
    if not ENV_FILE.is_file():
        return result
    for line in ENV_FILE.read_text(encoding='utf-8').splitlines():
        s = line.strip()
        if not s or s.startswith('#') or '=' not in s:
            continue
        key, val = s.split('=', 1)
        key = key.strip()
        if key.isidentifier() or key.replace('-', '_').isidentifier():
            result[key] = val.strip()
    return result


def _mask(val: str) -> str:
    """脱敏：只留尾 4 位（短值全遮）。"""
    v = val.strip()
    if len(v) <= 4:
        return '••••'
    return '••••' + v[-4:]


# 要从回显文本里抹掉的 .env 键：命中这些词的一律当机密处理
_SECRETISH_RE = re.compile(r'KEY|TOKEN|SECRET|PASSWORD|COOKIE', re.I)


def _scrub_secrets(text: str) -> str:
    """把 .env 里的机密值从要回显给前端的文本里抹掉。

    子进程 stderr 会被原样带到浏览器，而 openclaw 的报错可能回显配置值；
    按「已知机密的字面量」替换最稳妥，不依赖猜正则能否匹配各家 key 的格式。
    """
    out = text
    for key, val in _read_env().items():
        v = val.strip().strip('"').strip("'")
        # 太短的值（占位符、枚举值如 none/http）替换会误伤正常文本
        if len(v) >= 8 and _SECRETISH_RE.search(key):
            out = out.replace(v, _mask(v))
    return out


def _key_configured(key: dict, env: dict[str, str]) -> bool:
    '某个 key（含别名）是否已配置。'
    if _is_set(env.get(key['env'])):
        return True
    return any(_is_set(env.get(a)) for a in key.get('aliases', []))


def _skill_api_configured(skill: str, env: dict[str, str] | None = None) -> bool:
    'SKILL 是否已具备可用配置：任一 provider 的全部 required key 齐全。'
    spec = SKILL_API_REQUIREMENTS.get(skill)
    if not spec:
        return True
    env = _read_env() if env is None else env
    for prov in spec['providers']:
        if all(_key_configured(k, env) for k in prov['keys'] if k['required']):
            return True
    return False


# .env 的值是裸写 `KEY=value` 的，而 setup.sh:310/450 会 `source .env`。bash 在赋值右侧
# 不做分词和通配，但**照做**命令替换，且元字符会截断赋值另起一条命令 —— 所以 `$(…)`、反引号、
# `;`/`&`/`|`/`(`/`)`/`<`/`>`/空白 都等于任意命令执行。加引号写入不行：scripts/gateway.sh:63
# 用 `sed -n 's/^KEY=//p'` 裸取值，引号会跟着漏进端口号。只能在入口把值的字符集收死。
# 这里能写的全是 API Key / Base URL / 模型 id / 端口，没有一个需要空格或上面那些字符。


def _guard_env_values(updates: dict[str, str]) -> None:
    """集中拦截 .env 值注入：值里带换行能往 .env 追加任意行，带 `$(…)` 能直接执行命令
    —— 两者都等于任何能调到写 .env 接口的人都能拿到命令执行。键名同理。两个写入口都必须先过这道。"""
    for k, v in updates.items():
        if any(c in (k or '') for c in '\r\n=') or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', k or ''):
            raise HTTPException(400, f'非法的配置键名：{(k or "")[:40]!r}')
        v = v or ''
        if any(c in v for c in '\r\n\x00'):
            raise HTTPException(400, f'配置值不能包含换行符：{k}')
        if not _ENV_VALUE_OK.fullmatch(v):
            bad = ''.join(sorted({c for c in v if not _ENV_VALUE_OK.fullmatch(c)}))
            raise HTTPException(400, f'配置值含不允许的字符（{bad!r}）：{k}')


# 设置面板里「改了 Base URL 就必须重填 Key」要比对的 .env 键位（槽位 → (base 键, key 键)）。


def _harness_settings() -> dict:
    try:
        return harness_store.settings(OUTPUTS_DIR, read_settings(ENV_FILE))
    except HarnessError as error:
        raise HTTPException(409, str(error)) from error


def _chat_backend(session_id: str | None) -> str:
    selected = "api" if _direct_api_enabled() else _harness_settings()["runtime"]
    if not session_id:
        return selected
    try:
        record = harness_store.binding(SESSIONS_DIR, session_id)
    except HarnessError as error:
        raise HTTPException(409, str(error)) from error
    owner = record.get("runtime")
    if not owner:
        if history_path(SESSIONS_DIR, session_id).is_file():
            owner = "api"
        elif ((OPENCLAW_SESSIONS_DIR / f"{_openclaw_session_id(session_id)}.jsonl").is_file()
              or (OPENCLAW_SESSIONS_DIR / f"{_openclaw_session_id(f'web:{session_id}')}.jsonl").is_file()
              or _transport_pin_file(session_id).is_file()
              or (selected != "api" and _turn_file(f"web:{session_id}").is_file())):
            owner = "openclaw"
    if selected == "api" and owner == "openclaw":
        return selected
    if owner and owner != selected:
        raise HTTPException(409, f"此会话属于 {owner}，当前选择 {selected}；请新建会话，原历史不变")
    return selected


def _write_env(updates: dict[str, str]) -> None:
    '就地更新命中的 KEY、其余行原样保留，未命中的追加末尾；空串则删除该行。原子写。'
    updates = {k: v for k, v in updates.items() if k in _ENV_ALLOWLIST}
    _guard_env_values(updates)
    if not updates:
        return
    lines = ENV_FILE.read_text(encoding='utf-8').splitlines() if ENV_FILE.is_file() else []
    seen = set()
    out = []
    for line in lines:
        s = line.strip()
        matched = None
        if s and not s.startswith('#') and '=' in s:
            k = s.split('=', 1)[0].strip()
            if k in updates:
                matched = k
        if matched is not None:
            seen.add(matched)
            val = updates[matched]
            if val.strip() == '':
                continue
            out.append(f'{matched}={val}')
            continue
        out.append(line)
    appended = [f'{k}={v}' for k, v in updates.items() if k not in seen and v.strip() != '']
    if appended:
        if out and out[-1].strip() != '':
            out.append('')
        out.append('# ---- Easel API keys (added via Web) ----')
        out.extend(appended)
    tmp = ENV_FILE.with_suffix('.env.tmp')
    tmp.write_text('\n'.join(out) + '\n', encoding='utf-8')
    tmp.replace(ENV_FILE)


def _api_spec_status(skill: str, env: dict[str, str]) -> dict:
    '返回注册表项 + 每个 key 当前配置状态与脱敏值（不回传明文）。'
    spec = SKILL_API_REQUIREMENTS[skill]

    def key_status(k: dict) -> dict:
        raw = env.get(k['env'], '')
        return {
            'env': k['env'],
            'label': k['label'],
            'required': k['required'],
            'secret': k['secret'],
            'choices': list(k.get('choices', [])),
            'configured': _key_configured(k, env),
            'masked': _mask(raw) if k['secret'] and _is_set(raw) else (raw if not k['secret'] else ''),
        }

    providers = []
    for prov in spec['providers']:
        keys = [key_status(k) for k in prov['keys']]
        providers.append({'id': prov['id'], 'name': prov['name'], 'keys': keys})
    return {
        'label': spec['label'],
        'settings': [key_status(k) for k in spec.get('settings', [])],
        'providers': providers,
    }


def _agent_thinking_level() -> str:
    try:
        data = json.loads(_oc_config_path().read_text(encoding="utf-8-sig"))
        agents = data.get("agents", {})
        reference = agents.get("defaults", {}).get("model", {})
        for agent in agents.get("list", []):
            if isinstance(agent, dict) and agent.get("id") == "main" and agent.get("model"):
                reference = agent["model"]
                break
        primary = reference.get("primary", "") if isinstance(reference, dict) else reference
        if not isinstance(primary, str) or "/" not in primary:
            return THINKING_LEVEL
        provider, model_id = primary.split("/", 1)
        models = data.get("models", {}).get("providers", {}).get(provider, {}).get("models", [])
        for model in models:
            if isinstance(model, dict) and model.get("id") == model_id:
                return "off" if model.get("reasoning") is False else THINKING_LEVEL
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    return THINKING_LEVEL


def _publishing_message(message: str) -> str:
    if publishing_mode(read_settings(ENV_FILE)) == "manual":
        return ("【当前 Web 发布方式：人工提交】AI 只负责创作、排版、素材和审核建议。"
                "不要调用发布脚本、发布接口、浏览器代填或代点发布。"
                "引导用户在发布中心审核、复制或导出，再在官方页面亲自提交。"
                "导出、复制、打开网页和排期均不代表已发布。\n\n" + message)
    return message


def run_agent_sync(msg: str, timeout: int = TIMEOUT_DIRECT, session_id: str | None = None) -> str:
    if _direct_api_enabled():
        raise HTTPException(409, "API 直连模式支持聊天；此操作需要具备文件和技能执行工具的 Agent 运行时")
    msg = _publishing_message(msg)
    sk = session_id or f'web-{int(time.time() * 1000)}'
    runtime = _chat_backend(session_id)
    if runtime not in ("api", "openclaw"):
        async def execute():
            request = ChatRequest(message=msg, sessionId=sk)
            errors = []
            def emit(kind, text):
                if kind == "error":
                    errors.append(text)
            result = await _run_harness_chat(request, sk, msg, runtime, _harness_settings(), emit,
                                             timeout, interactive=False)
            if errors:
                raise HTTPException(502, errors[0])
            return result
        if _HARNESS_LOOP is not None and _HARNESS_LOOP.is_running():
            return asyncio.run_coroutine_threadsafe(execute(), _HARNESS_LOOP).result(timeout + 15)
        return asyncio.run(execute())
    # 钉死 --session-id 让 OpenClaw 每轮续同一 transcript（防跨天空闲后新起空会话丢历史，见 _openclaw_session_id）
    cmd = openclaw_base_cmd() + ['--profile', OPENCLAW_PROFILE, 'agent', '--agent', 'main',
           '--session-key', f'agent:main:{sk}', '--session-id', _openclaw_session_id(sk),
           '--thinking', _agent_thinking_level(),
           '--timeout', str(timeout), '--message', msg]
    # 跨进程锁：同一会话同时刻只跑一个 openclaw，防并发 takeover 崩溃（rc=1）
    xlock = _CrossProcLock(sk)
    if not xlock.acquire(timeout=min(timeout, 300)):
        return '⏳ 这个会话正在另一个窗口运行，请稍候再试'
    # 同 supervisor：先拿到锁再 heal，避免与正在追加 transcript 的进程并发重写丢行
    _heal_openclaw_session(sk)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=timeout + 30, env=_proxy_env())
        out = clean_agent_output(r.stdout or '')
        if out:
            return out
        # 以前这里直接 `or '（无输出）'`：returncode 与 stderr 全部丢弃，于是子进程的
        # 任何失败（参数不被当前 OpenClaw 版本支持、配置校验不过、provider 报错）都长
        # 成同一句「（无输出）」，排查只能靠手动把整条命令行复现一遍。
        # 实测 `--session-key` 在老版 OpenClaw 上不存在，就是被这里藏掉一整轮的。
        err = clean_agent_output(r.stderr or '')
        if r.returncode != 0:
            detail = _scrub_secrets(err)[-400:].strip() or f'退出码 {r.returncode}'
            return f'❌ agent 执行失败（rc={r.returncode}）：{detail}'
        # rc=0 但没有任何产出：stderr 里通常有线索（如模型拒答、工具被拦）
        if err:
            return f'（无输出）\n\n{_scrub_secrets(err)[-400:].strip()}'
        return '（无输出）'
    except subprocess.TimeoutExpired:
        return '⏱️ 请求超时'
    except Exception as e:
        return f'❌ {e}'
    finally:
        xlock.release()


def check_gateway() -> bool:
    try:
        # 端口不能写死：Easel 用 --profile easel，OpenClaw 对非默认 profile 会走
        # 20000 + fnv1a32(profile) % 40000（easel → 37289），见 easel/gateway_endpoint.py。
        # 回环 healthz 探针不能继承 http_proxy；否则设置页会把健康的本机 gateway 误报离线。
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(healthz_url(), timeout=3) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


from easel.web_services.outputs import bind as _bind_shared_outputs
_bind_shared_outputs(into=globals())


@app.get("/")
async def index():
    no_cache = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}
    react_index = REACT_DIR / "index.html"
    if react_index.is_file():
        return FileResponse(react_index, media_type="text/html", headers=no_cache)
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html", headers=no_cache)


@app.get("/onepage")
async def onepage():
    return FileResponse(STATIC_DIR / "onepage.html", media_type="text/html")


@app.get("/assets/{path:path}")
async def react_assets(path: str):
    base = (REACT_DIR / "assets").resolve()
    fp = (REACT_DIR / "assets" / path).resolve()
    if base != fp and base not in fp.parents:
        raise HTTPException(403, "非法路径")
    if not fp.is_file():
        raise HTTPException(404)
    return FileResponse(fp, headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/static/{path:path}")
async def static_file(path: str):
    base = STATIC_DIR.resolve()
    fp = (STATIC_DIR / path).resolve()
    if base != fp and base not in fp.parents:
        raise HTTPException(403, "非法路径")
    if not fp.is_file():
        raise HTTPException(404)
    # HTML entrypoints must not be cached: the intro page is edited in-place during local development.
    headers = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"} if fp.suffix.lower() in {".html", ".htm"} else {}
    return FileResponse(fp, headers=headers)


@app.get("/api/status")
async def api_status():
    direct = _direct_api_enabled()
    runtime = _harness_settings()["runtime"]
    ready = False
    if direct:
        try:
            api_config(read_settings(ENV_FILE))
            ready = True
        except DirectAPIError:
            pass
    elif runtime == "openclaw":
        ready = await asyncio.to_thread(check_gateway)
    else:
        ready = harnesses.describe(runtime)["installed"]
    return {"gateway": ready, "transport": "api" if direct else (
                CHAT_TRANSPORT if runtime == "openclaw" else runtime), "runtime": runtime,
            "skills": get_skills(), "personas": list_personas()}


@app.get("/api/settings/bootstrap")
async def api_settings_bootstrap():
    """首次打开时的自检：模型配好了吗、网关活着吗、上次安装留了什么没做完。

    安装脚本不再在终端问 API Key（改为引导到这里配），所以前端需要一个可靠的
    「还缺什么」判据。modelConfigured 必须同时满足两件事，这正是 doctor 里那条
    「全绿却对话报错」防线：
      - .env 里有可用的认证（_env_key_valid，带占位符识别）；
      - primary 指向的 provider 在 openclaw.json 里真的配了认证
        （_primary_model_routable）—— 只查 .env 查不出 provider 一个字没写的情况。
    """
    direct = _direct_api_enabled()
    runtime = _harness_settings()["runtime"]
    if runtime not in ("api", "openclaw"):
        installed = harnesses.describe(runtime)["installed"]
        return {"modelConfigured": installed, "envKeyOk": installed, "routeOk": installed,
                "routeDetail": "CLI 已安装；请在终端完成原生登录，并发送消息验证模型可用性",
                "gatewayUp": installed, "openclawConfigExists": False, "installWarnings": [],
                "runtime": runtime, "authVerified": False}
    env_ok = False
    route_ok = False
    route_detail = ''
    try:
        if direct:
            api_config(read_settings(ENV_FILE))
            env_ok = route_ok = True
        else:
            from easel.commands.doctor import _env_key_valid, _primary_model_routable
            env_ok = bool(_env_key_valid())
            route_ok, route_detail = _primary_model_routable()
    except DirectAPIError as error:
        route_detail = str(error)
    except Exception as e:  # noqa: BLE001
        route_detail = f'自检失败：{e}'

    warnings: list[dict] = []
    try:
        rep = PROJECT_ROOT / 'outputs' / '_install' / 'last-install.json'
        if rep.is_file():
            warnings = json.loads(rep.read_text(encoding='utf-8')).get('warnings') or []
    except Exception:  # noqa: BLE001
        warnings = []

    return {
        'modelConfigured': bool(env_ok and route_ok),
        'envKeyOk': env_ok,
        'routeOk': bool(route_ok),
        'routeDetail': route_detail,
        'gatewayUp': bool(route_ok) if direct else bool(await asyncio.to_thread(check_gateway)),
        'openclawConfigExists': _oc_config_path().is_file(),
        'installWarnings': warnings,
    }


@app.post("/api/gateway/restart")
async def api_gateway_restart():
    """重启本机 gateway，让刚保存的模型配置立刻生效。

    为什么需要：默认传输层是 http（见 CHAT_TRANSPORT），对话走的是一个常驻 gateway，
    由 setup.sh 启动一次。配置改了之后它是否重新读 openclaw.json 取决于 OpenClaw 版本，
    不是一条该押在安装流程上的假设。

    安全性：web/app.py 绑 0.0.0.0 且无鉴权，所以这个端点刻意做成**无参数**，argv
    完全固定（复用 easel.commands.gateway 的同一条分发），不接受任何外部输入拼进命令。
    """
    if _direct_api_enabled():
        return {'ok': True, 'note': 'API 直连配置下一轮生效，无需重启 OpenClaw'}
    if _harness_settings()["runtime"] != "openclaw":
        raise HTTPException(409, "当前 Agent 使用独立按轮启动的进程，不需要重启 OpenClaw 网关")
    script = PROJECT_ROOT / 'scripts' / ('gateway.ps1' if os.name == 'nt' else 'gateway.sh')
    if not script.is_file():
        raise HTTPException(500, '找不到 gateway 启动脚本')
    cmd = (['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script), 'restart']
           if os.name == 'nt' else ['bash', str(script), 'restart'])
    try:
        r = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True,
                                   text=True, timeout=120, env=_proxy_env()),
        )
    except subprocess.TimeoutExpired:
        # 超时返回提示而不是 500：网关可能只是起得慢，用户刷新一下就好。
        return {'ok': False, 'note': '重启超时；可稍后刷新，或手动运行 bash scripts/gateway.sh restart'}
    except Exception as e:  # noqa: BLE001
        return {'ok': False, 'note': f'重启失败：{e}'}
    # check_gateway 里有阻塞的 urllib 探针（最多 3s）：丢线程，别卡事件循环
    up = await asyncio.to_thread(check_gateway)
    tail = clean_agent_output(r.stdout or '')[-200:]
    return {'ok': bool(up), 'gatewayUp': bool(up),
            'note': tail or ('网关已重启' if up else '网关未就绪，请查看 /tmp/easel-gateway.log')}


@app.get("/api/personas")
async def api_personas():
    return list_personas()


@app.get("/api/persona/{name}")
async def api_persona(name: str):
    text = load_profile_text(name)
    if not text:
        raise HTTPException(404, "画像不存在")
    return {"name": name, "content": text}


def _valid_persona_name(name: str) -> bool:
    return valid_persona_name(name)


def _persona_file_path(name: str, filename: str) -> Path:
    """校验画像名/文件名，返回 profiles/<name>/<filename> 的安全路径。"""
    if not _valid_persona_name(name):
        raise HTTPException(400, "画像名非法")
    if not filename.endswith(".md") or "/" in filename or "\\" in filename or filename.startswith("."):
        raise HTTPException(400, "文件名非法")
    pd = (PROFILES_DIR / name).resolve()
    fp = (pd / filename).resolve()
    if pd != fp.parent or PROFILES_DIR.resolve() not in pd.parents:
        raise HTTPException(403, "非法路径")
    return fp


@app.get("/api/persona/{name}/files")
async def api_persona_files(name: str):
    """返回画像六维文件原文（按固定顺序 + 其余 .md），供在线编辑。"""
    if not profile_exists(name):
        raise HTTPException(404, "画像不存在")
    pd = PROFILES_DIR / name
    ordered = list(_FILE_ORDER) + sorted(f.name for f in pd.glob("*.md") if f.name not in _FILE_ORDER)
    files = []
    for fn in ordered:
        fp = pd / fn
        files.append({"filename": fn, "content": fp.read_text(encoding="utf-8") if fp.is_file() else ""})
    return {"name": name, "files": files}


class PersonaFileRequest(BaseModel):
    filename: str
    content: str


@app.put("/api/persona/{name}/file")
async def api_persona_file_save(name: str, req: PersonaFileRequest):
    """保存画像单个维度文件（原子写）。"""
    if not profile_exists(name):
        raise HTTPException(404, "画像不存在")
    fp = _persona_file_path(name, req.filename)
    tmp = fp.with_suffix(".md.tmp")
    tmp.write_text(req.content, encoding="utf-8")
    tmp.replace(fp)
    return {"ok": True, "filename": req.filename}


@app.delete("/api/persona/{name}")
async def api_persona_delete(name: str):
    """删除整个画像目录。"""
    if not _valid_persona_name(name):
        raise HTTPException(400, "画像名非法")
    pd = (PROFILES_DIR / name).resolve()
    if PROFILES_DIR.resolve() not in pd.parents or not pd.is_dir():
        raise HTTPException(404, "画像不存在")
    import shutil
    shutil.rmtree(pd)
    return {"ok": True, "deleted": name}


@app.get("/api/skills")
async def api_skills():
    return get_skills()


@app.get("/api/skill/{name}")
async def api_skill_detail(name: str):
    """单个 SKILL 详情：描述 + 正文 + API 需求与当前配置状态（脱敏）。"""
    full = find_skill(name)
    if full is None:
        raise HTTPException(404, f"SKILL '{name}' 不存在")
    desc, layer, body = _parse_skill_md(SKILLS_DIR / "builtin" / full / "SKILL.md")
    needs_api = full in SKILL_API_REQUIREMENTS
    env = _read_env()
    return {
        "name": full,
        "layer": layer,
        "description": desc,
        "body": body,
        "needsApi": needs_api,
        "apiConfigured": _skill_api_configured(full, env) if needs_api else True,
        "apiSpec": _api_spec_status(full, env) if needs_api else None,
    }


class EnvUpdateRequest(BaseModel):
    updates: dict[str, str]


@app.post("/api/env")
async def api_env_save(req: EnvUpdateRequest):
    """写 API key 到项目根 .env（仅允许注册表内 env 名）。返回更新后各 skill 的配置状态。"""
    bad = [k for k in (req.updates or {}) if k not in _ENV_ALLOWLIST]
    if bad:
        raise HTTPException(400, f"不允许写入的变量：{', '.join(bad)}")
    _write_env(req.updates or {})
    env = _read_env()
    return {
        "ok": True,
        "skills": {s: _skill_api_configured(s, env) for s in SKILL_API_REQUIREMENTS},
    }


# ═══════════════════════════════════════════════════════════════════════
# 设置面板 · 环境安装（skills/shared/scripts/install_tool.py 引擎桥）

from easel.web_services.environment import bind as _bind_environment
_bind_environment(into=globals())
app.get('/api/env/tools')(api_env_tools)
app.post('/api/env/install')(api_env_install)
app.get('/api/env/job/{job_id}')(api_env_job)
# 体检走引擎 check --json；安装后台跑、前端轮询 /api/env/job/{id}。
# ═══════════════════════════════════════════════════════════════════════















# ═══════════════════════════════════════════════════════════════════════
# 设置面板 · 模型配置（v1：按真实 .env / openclaw.json 只读展示 + 真自测）
# ═══════════════════════════════════════════════════════════════════════


class ChatTransportRequest(BaseModel):
    transport: str


class HarnessSettingsRequest(BaseModel):
    runtime: str
    model: str = Field(default="", max_length=240)
    sandbox: str = "workspace-write"
    codex_auto_approve: StrictBool | None = None


@app.get("/api/settings/harness")
async def api_harness_settings():
    config = _harness_settings()
    agents = await asyncio.to_thread(lambda: [harnesses.describe(runtime) for runtime in harness_store.IDS])
    return {**config, "agents": agents,
            "locked": "EASEL_AGENT_RUNTIME" in read_settings(ENV_FILE)}


@app.post("/api/settings/harness")
async def api_harness_settings_save(req: HarnessSettingsRequest):
    if req.runtime not in harness_store.IDS:
        raise HTTPException(400, "未知 Agent 底座")
    if req.sandbox not in ("read-only", "workspace-write"):
        raise HTTPException(400, "请选择只读或工作区写入权限")
    if any(ord(character) < 32 for character in req.model):
        raise HTTPException(400, "模型名称不能包含控制字符")
    if "EASEL_AGENT_RUNTIME" in read_settings(ENV_FILE):
        raise HTTPException(409, "启动环境固定了底座，请修改 EASEL_AGENT_RUNTIME 后重启")
    if _RUNNING_CHAT or _BG_TASKS or _DIRECT_CHAT_TASKS or _HARNESS_TASKS:
        raise HTTPException(409, "请等待当前任务完成或停止后切换底座")
    if req.runtime not in ("api", "openclaw") and not harnesses.describe(req.runtime)["installed"]:
        raise HTTPException(409, "请先在终端安装并配置对应 Agent CLI，再切换")
    config = _harness_settings()
    if req.runtime == "openclaw" and api_mode(read_settings(ENV_FILE)):
        if "EASEL_CHAT_TRANSPORT" in os.environ:
            raise HTTPException(409, "运行环境已固定仅聊天模式，请修改 EASEL_CHAT_TRANSPORT 后重启")
        _write_env_direct({"EASEL_CHAT_TRANSPORT": "http"})
    config["runtime"] = req.runtime
    config["sandbox"] = req.sandbox
    if req.runtime == "codex" and req.codex_auto_approve is not None:
        config["codex_auto_approve"] = req.codex_auto_approve
    config["models"] = {**config["models"], req.runtime: req.model.strip()}
    harness_store.write_json(OUTPUTS_DIR / "_harness" / "config.json", config)
    from easel.harnesses.rpc import close_sessions
    await close_sessions()
    return await api_harness_settings()


@app.post("/api/settings/chat/transport")
async def api_chat_transport_save(req: ChatTransportRequest):
    if req.transport not in ("api", "openclaw"):
        raise HTTPException(400, "请选择 api 或 openclaw")
    if "EASEL_AGENT_RUNTIME" in read_settings(ENV_FILE):
        raise HTTPException(409, "启动环境固定了执行引擎，请修改 EASEL_AGENT_RUNTIME 后重启")
    if "EASEL_CHAT_TRANSPORT" in os.environ:
        raise HTTPException(409, "运行环境已指定 EASEL_CHAT_TRANSPORT，请修改启动环境后重启")
    if _RUNNING_CHAT or _BG_TASKS or _DIRECT_CHAT_TASKS or _HARNESS_TASKS:
        raise HTTPException(409, "请等待当前对话完成或停止后切换模式")
    config = _harness_settings()
    _write_env_direct({"EASEL_CHAT_TRANSPORT": "api" if req.transport == "api" else "http"})
    config["runtime"] = "api" if req.transport == "api" else "openclaw"
    harness_store.write_json(OUTPUTS_DIR / "_harness" / "config.json", config)
    from easel.harnesses.rpc import close_sessions
    await close_sessions()
    return _model_channels()


@app.get("/api/settings/models")
async def api_settings_models(runtime: str | None = None):
    """模型通道：chat / transcribe（含可编辑的原值；key 只回脱敏）。"""
    if runtime is not None and runtime not in ("api", "openclaw"):
        raise HTTPException(400, "仅聊天和 OpenClaw 才有 API 供应商配置")
    if runtime is None:
        return await asyncio.to_thread(_model_channels)
    return await asyncio.to_thread(_model_channels, runtime)


@app.post("/api/settings/harness/models/{runtime}")
async def api_harness_models(runtime: str):
    if runtime not in ("codex", "opencode"):
        raise HTTPException(400, "此底座不支持原生模型列表")
    from easel.harnesses.base import RunRequest
    from easel.harnesses.models import available_models
    request = RunRequest("", PROJECT_ROOT, {
        **_proxy_env(), "EASEL_ROOT": str(PROJECT_ROOT), "EASEL_AGENT_RUNTIME": runtime})
    try:
        models = await asyncio.wait_for(available_models(runtime, request), 25)
    except asyncio.TimeoutError as error:
        raise HTTPException(504, "原生模型列表读取超时，请稍后重试") from error
    except (HarnessError, OSError, UnicodeError) as error:
        raise HTTPException(409, "无法读取原生模型列表，请检查 CLI 安装与原生配置") from error
    return {"runtime": runtime, "models": models}


def _write_env_direct(updates: dict[str, str]) -> None:
    """后端受控键位专用：就地更新/追加 .env（不做 allowlist 过滤，仅服务端固定映射调用）。原子写。"""
    updates = {k: v for k, v in updates.items() if k and v.strip() != ''}
    if not updates:
        return
    _guard_env_values(updates)
    lines = ENV_FILE.read_text(encoding='utf-8').splitlines() if ENV_FILE.is_file() else []
    seen = set()
    out = []
    for line in lines:
        s = line.strip()
        matched = None
        if s and not s.startswith('#') and '=' in s:
            k = s.split('=', 1)[0].strip()
            if k in updates:
                matched = k
        if matched is not None:
            seen.add(matched)
            out.append(f'{matched}={updates[matched]}')
            continue
        out.append(line)
    appended = [f'{k}={v}' for k, v in updates.items() if k not in seen]
    if appended:
        if out and out[-1].strip() != '':
            out.append('')
        out.append('# ---- Easel 模型配置（Web 设置面板写入）----')
        out.extend(appended)
    tmp = ENV_FILE.with_suffix('.env.tmp')
    tmp.write_text('\n'.join(out) + '\n', encoding='utf-8')
    tmp.replace(ENV_FILE)


app.post('/api/settings/models/save')(api_settings_models_save)


app.get('/api/settings/local-agents')(api_local_agents)


app.post('/api/settings/local-agents/enable')(api_local_agent_enable)


# slot → (base 键, key 键)；与 _SLOT_ENV_KEYS 同源，外加自定义供应商。


app.post('/api/settings/models/available')(api_models_available)


app.post('/api/settings/models/selftest')(api_models_selftest)


class AttachmentRef(BaseModel):
    id: str
    name: str
    path: str


class ChatRequest(BaseModel):
    message: str
    persona: str | None = None
    sessionId: str | None = None
    turnId: str | None = None
    attachments: list[AttachmentRef] = Field(default_factory=list)


def _attachment_scope(session_id: str) -> str:
    """Map a browser session to a filesystem-safe, non-reversible inbox scope."""
    value = session_id.strip()
    if not value or len(value) > 256:
        raise HTTPException(400, "无效的会话标识")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def _attachment_id(scope: str, path: str) -> str:
    return hashlib.sha256(f"{scope}\0{path}".encode("utf-8")).hexdigest()[:24]


def _attachment_context(req: ChatRequest) -> str:
    """Validate attachment ownership and build an Agent-only attachment manifest."""
    if not req.attachments:
        return ""
    if not req.sessionId:
        raise HTTPException(400, "附件必须绑定到会话")

    scope = _attachment_scope(req.sessionId)
    rows: list[str] = []
    seen: set[str] = set()
    for attachment in req.attachments:
        rel = Path(attachment.path)
        if rel.is_absolute() or ".." in rel.parts or len(rel.parts) != 4:
            raise HTTPException(400, "附件路径无效")
        if rel.parts[0] != "_inbox" or rel.parts[1] != scope:
            raise HTTPException(403, "附件不属于当前会话")
        normalized = rel.as_posix()
        if attachment.id != _attachment_id(scope, normalized):
            raise HTTPException(403, "附件标识校验失败")
        full = _safe_output_target(normalized)
        if not full.is_file():
            raise HTTPException(404, f"附件不存在：{attachment.name}")
        if normalized in seen:
            continue
        seen.add(normalized)
        rows.append(f"- outputs/{normalized}")

    return (
        "〔系统附件清单，仅供本轮执行，不要向用户复述文件上传过程或内部路径〕\n"
        "只允许使用下列当前会话附件；禁止扫描、枚举或猜测 outputs/_inbox 中的其他文件：\n"
        + "\n".join(rows)
        + "\n需要纳入内容项目时，将清单内文件复制到 outputs/<项目>/assets/ 后再使用；"
          "保留 inbox 原件，确保重试仍可复现。"
    )


def _chat_message(req: ChatRequest) -> str:
    context = _attachment_context(req)
    message = req.message.strip()
    if context:
        message = f"{message}\n\n{context}" if message else context
    if not message:
        raise HTTPException(400, "消息不能为空")
    return _publishing_message(chat_turn_message(message, req.persona))


def _direct_chat_content(req: ChatRequest) -> tuple[str | list, str]:
    _attachment_context(req)  # Reuse ownership/path validation before reading any attachment.
    message = req.message.strip()
    if not message and not req.attachments:
        raise HTTPException(400, "消息不能为空")
    system = SYSTEM_PROMPT
    if req.persona:
        if not _valid_persona_name(req.persona) or not profile_exists(req.persona):
            raise HTTPException(400, "画像不存在或名称无效")
        system += "\n\n当前画像：\n" + load_profile_text(req.persona)
    content = [{"type": "text", "text": message or "请分析这些附件"}]
    for attachment in req.attachments:
        path = _safe_output_target(attachment.path)
        if path.suffix.lower() in TEXT_EXTS:
            if path.stat().st_size > 65536:
                raise HTTPException(413, "API 直连模式文本附件不能超过 64 KiB")
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeError:
                raise HTTPException(400, "文本附件需要 UTF-8 编码") from None
            content.append({"type": "text", "text": f"附件 {attachment.name}：\n{text}"})
        elif path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
            if path.stat().st_size > 4 * 1024 * 1024:
                raise HTTPException(413, "API 直连模式图片附件不能超过 4 MiB")
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            mime = mimetypes.guess_type(path.name)[0] or "image/png"
            content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}})
        else:
            raise HTTPException(400, "API 直连模式支持文本和图片附件；此附件需要文件处理工具")
    return (content if req.attachments else message), system


# 每个会话（session-key）一把锁：防止同一会话被两个并发的 openclaw agent 进程同时处理。
# 并发跑同一 session 文件会触发 openclaw 的 EmbeddedAttemptSessionTakeoverError（进程 rc=1、
# 表现为「答一半停在冒号」），以及会话串味（一个会话读到另一个的 session 文件内容）。
# 不同会话 key 不同锁 → 不同对话仍可并行；只序列化「同一会话」的重叠请求。
_session_locks: dict[str, asyncio.Lock] = {}


def _session_lock(sk: str) -> asyncio.Lock:
    lk = _session_locks.get(sk)
    if lk is None:
        lk = asyncio.Lock()
        _session_locks[sk] = lk
    return lk


# 会话续接：把 web 的 sessionId 确定性映射成一个稳定的 OpenClaw --session-id（transcript 文件名）。
# 背景（实测根因）：OpenClaw 靠 --session-key 解析 transcript，但空闲超过约 24h（threadBindings
# 默认 idleHours:24）后该绑定过期，下一条消息会新起一个空 transcript → 历史全丢（用户「关页两天
# 后再问就忘了」）。同一天内没事，隔天就断。解法：我们自己钉死 --session-id（对同一 web 会话恒定），
# 让 OpenClaw 每轮都续同一个 transcript 文件，绕开 key→绑定的过期/轮换逻辑。
_EASEL_SESSION_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # 固定命名空间（uuid5 确定性）


def _openclaw_session_id(sk: str) -> str:
    """web sessionId → 稳定的 OpenClaw session-id（transcript）。同 sk 永远同 id，无需落盘映射。"""
    return str(uuid.uuid5(_EASEL_SESSION_NS, sk))


def _session_flock_path(sk: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", sk)[:120]
    return SESSIONS_DIR / f"{safe}.lock"


def _transport_pin_file(sk: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", sk)[:120]
    return SESSIONS_DIR / f"{safe}.transport"


def _resolve_transport(sk: str) -> str:
    """决定这一轮走哪条传输层，并保证同一会话**永不中途换边**。

    换边的代价是静默丢光上下文，不是慢一点：CLI 路径用 `--session-id`（uuid5(sk)）把 transcript
    钉死，而 /v1/chat/completions **压根不读 x-openclaw-session-id** —— openclaw 2026.6.11 全量
    实测：该 header 只有 MCP 端点和对上游供应商的出站请求会用，OpenAI 兼容端点只认
    x-openclaw-session-key，transcript 文件名由网关自己挑。于是同一个 web 会话在两条路径下落在
    两份不同的 jsonl 上。实测拿 CLI 去续一个已有两轮 HTTP 历史的会话，agent 回答"无历史"。

    所以判定顺序（都不依赖内存态，web 重启后依然成立）：
      1) uuid5 那份 transcript 已落盘 → 这会话是 CLI 起的，继续 cli；
      2) 有 http 钉子文件 → 继续 http；
      3) 两者都没有 → 新会话，按总开关 + 真探针决定。
    """
    if (OPENCLAW_SESSIONS_DIR / f"{_openclaw_session_id(sk)}.jsonl").is_file():
        return "cli"
    try:
        if _transport_pin_file(sk).read_text(encoding="utf-8").strip() == "http":
            return "http"
    except OSError:
        pass
    # 3) 新会话：按总开关 + 真探针；探不通不报错，退回 CLI 但要吭一声
    if CHAT_TRANSPORT == "http" and _gateway_http_ready():
        return "http"
    if CHAT_TRANSPORT == "http":
        _warn_http_transport_unavailable()
    return "cli"


_HTTP_FALLBACK_WARNED = False


def _warn_http_transport_unavailable() -> None:
    """HTTP 直连不可用时只喊一次，并把**探的到底是哪个端点**写出来。

    以前这里是静默退回：端口写死探错地方，表现只是「每轮慢 3s」，没人会去查 —— 这次网关
    端口错配就是这么藏住的（面板离线 + 静默退 CLI）。
    """
    global _HTTP_FALLBACK_WARNED
    if _HTTP_FALLBACK_WARNED:
        return
    _HTTP_FALLBACK_WARNED = True
    print(f"[chat-transport] HTTP 直连探不通 {chat_completions_url()}（端口来自 {port_source()}），"
          f"已退回 CLI 传输（每轮多付一次客户端冷启动）。"
          f"查：{PROJECT_ROOT}/scripts/gateway.sh status", file=sys.stderr, flush=True)


def _pin_transport(sk: str, kind: str) -> None:
    """把会话钉在某条传输层上。只需钉 http —— cli 侧由 uuid5 transcript 文件自证。"""
    if kind != "http":
        return
    try:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        _transport_pin_file(sk).write_text("http", encoding="utf-8")
    except OSError:
        pass


class _CrossProcLock:
    """跨进程会话锁（fcntl.flock）：同一会话同一时刻只允许一个 openclaw 进程在跑。

    现有 _session_lock（asyncio）只在单个 web 进程内串行；挡不住两个浏览器标签/常驻 gateway/
    cron 并发碰同一会话 → openclaw 抛 EmbeddedAttemptSessionTakeoverError（rc=1，答一半就停）。
    flock 在持有进程退出时自动释放，无 stale 死锁。返回 True=拿到锁，False=超时未拿到。
    """

    def __init__(self, sk: str):
        self._path = _session_flock_path(sk)
        self._fh = None
        self.acquired = False

    def acquire(self, timeout: float = 300.0, poll: float = 0.5) -> bool:
        try:
            SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
            self._fh = open(self._path, "a+b")
            if os.name == "nt":
                self._fh.seek(0, os.SEEK_END)
                if self._fh.tell() == 0:
                    self._fh.write(b"0")
                    self._fh.flush()
        except OSError:
            return False  # 拿不到文件句柄就不强求（退化为仅 asyncio 锁）
        deadline = time.time() + timeout
        while True:
            try:
                if os.name == "nt":
                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.acquired = True
                return True
            except OSError:
                if time.time() >= deadline:
                    return False
                time.sleep(poll)

    def release(self) -> None:
        if self._fh is not None:
            try:
                if self.acquired:
                    if os.name == "nt":
                        self._fh.seek(0)
                        msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None
            self.acquired = False


def _turn_file(sk: str) -> Path:
    """每会话最近一轮结果的落盘路径（sk 做文件名安全化）。"""
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", sk)[:120]
    return SESSIONS_DIR / f"{safe}.json"


def _job_event_file(turn_id: str) -> Path:
    """Per-turn append-only event log used to resume SSE without restarting the agent."""
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", turn_id)[:160]
    return SESSIONS_DIR / "jobs" / f"{safe}.jsonl"


def _read_job_events(turn_id: str, after: int = 0) -> list[dict]:
    path = _job_event_file(turn_id)
    if not path.is_file():
        return []
    events = []
    try:
        # Read/decode each record separately: a concurrent append can end in
        # partial JSON or even half a UTF-8 character. Keep valid records and
        # retry the incomplete tail on the next read without changing the log.
        with path.open("rb") as stream:
            for line in stream:
                try:
                    event = json.loads(line)
                except (ValueError, UnicodeError):
                    continue
                if not isinstance(event, dict):
                    continue
                event_id = event.get("id")
                if (type(event_id) is not int or event_id <= 0
                        or not isinstance(event.get("event"), str)
                        or not event["event"]):
                    continue
                if event_id > after:
                    events.append(event)
    except OSError:
        return []
    return events


def _raw_event_for_run(line: str, expected_run_id: str | None) -> dict | None:
    """Parse one OpenClaw raw event and reject events from other runs.

    The gateway multiplexes every run into one shared raw-stream file, and its
    events carry `runId` (not `sessionId`). A turn latches onto its own runId —
    the first event seen after the turn starts — and must ignore any event with
    a different runId. `expected_run_id=None` means not-yet-latched → accept, so
    the caller can latch from `event['runId']`.
    """
    line = line.strip()
    if not line:
        return None
    try:
        event = json.loads(line)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(event, dict):
        return None
    if expected_run_id is not None:
        rid = event.get("runId")
        if rid is not None and rid != expected_run_id:
            return None
    return event


def _save_turn(sk: str, status: str, text: str, extra: dict | None = None) -> None:
    """持久化本轮结果（running/done），供 SSE 连接中断后前端用 /api/chat/last 取回。

    后端跑完整轮不依赖客户端连接——长任务时 webide 代理会掐断 SSE，但 openclaw 仍跑到底，
    结果写这里，前端断线后轮询即可拿到完整回答（否则"运行完也不说一声"）。
    """
    try:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        payload = {"status": status, "text": text, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        if extra:
            payload.update(extra)
        tmp = _turn_file(sk).with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, _turn_file(sk))
    except Exception:
        pass


# 后台 supervisor 任务集合：持有强引用防被 GC；每个对话流的 openclaw run 跑在这里，
# 与客户端 SSE 连接解耦（断线不杀 run）。
_BG_TASKS: set = set()
_DIRECT_CHAT_TASKS: set = set()

# 正在跑的对话 openclaw 进程（sk→proc），供用户**显式「停止」**终止；断线**不**经此路径（断线不杀）。
_RUNNING_CHAT: dict = {}
# 被用户显式停止的会话 key：supervisor 据此把本轮当作正常「已停止」收尾（不报「被中断」、释放会话锁）。
_STOPPED_CHAT: set = set()
_HARNESS_TASKS: set = set()
_HARNESS_QUESTIONS: dict = {}


class _HarnessProc(_GatewayHttpProc):
    def __init__(self) -> None:
        super().__init__()
        self._cancel_requested = False

    def terminate(self) -> None:
        if self._task is not None:
            task = self._task
            def cancel_once():
                if (not task.done() and not self._cancel_requested
                        and not getattr(task, "cancelling", lambda: 0)()):
                    self._cancel_requested = True
                    task.cancel()
            task.get_loop().call_soon_threadsafe(cancel_once)


async def _harness_ask(sk: str, questions: list[dict], emit) -> dict:
    identifier = "harness_" + uuid.uuid4().hex
    future = asyncio.get_running_loop().create_future()
    record = {"session": sk, "future": future, "status": "pending", "questions": questions}
    _HARNESS_QUESTIONS[identifier] = record
    try:
        emit("question", _scrub_secrets(json.dumps(
            {"id": identifier, "questions": questions}, ensure_ascii=False)))
        answers = await asyncio.wait_for(future, TIMEOUT_CHAT)
        record["status"] = "resolved"
        return answers
    finally:
        _HARNESS_QUESTIONS.pop(identifier, None)


async def _run_harness_chat(req: ChatRequest, sk: str, message: str, runtime: str,
                            config: dict, emit, timeout: int = TIMEOUT_CHAT, *, interactive=True) -> str:
    pk = f"web:{sk}"
    turn_id = req.turnId or uuid.uuid4().hex
    full_text: list[str] = []
    clean_end = False
    reason = "error"
    error_message = ""
    lock = _session_lock(sk)
    xlock = _CrossProcLock(sk)
    acquired = False
    claimed = False
    locked = False
    proc = _HarnessProc()
    task = asyncio.current_task()
    _HARNESS_TASKS.add(task)

    def receive(kind, text):
        safe = _scrub_secrets(text)
        if kind == "token":
            full_text.append(safe)
        emit(kind, safe)

    async def ask(questions):
        if not interactive:
            raise HarnessError("此操作需要权限确认，请在流式对话中执行并确认权限")
        return await _harness_ask(sk, questions, receive)

    try:
        if lock.locked():
            emit("activity", "这个会话上一条还在运行，等待完成…")
        await lock.acquire()
        locked = True
        deadline = time.monotonic() + min(timeout, 300)
        while not acquired and time.monotonic() < deadline:
            acquired = xlock.acquire(0)
            if not acquired:
                xlock.release()
                await asyncio.sleep(0.2)
        if not acquired:
            raise HarnessError("此会话正在另一个窗口运行，请稍后再试")
        if _chat_backend(sk) != runtime:
            raise HarnessError("底座已切换，请使用新对话重试")
        record = harness_store.binding(SESSIONS_DIR, sk)
        native_id = record.get("native_id", "")
        harness_store.bind(SESSIONS_DIR, sk, runtime, native_id)
        _STOPPED_CHAT.discard(sk)
        proc._task = task
        _RUNNING_CHAT[sk] = proc
        _save_turn(pk, "running", "", {"turn_id": turn_id, "runtime": runtime})
        claimed = True
        env = {**read_settings(ENV_FILE), **_proxy_env(), "EASEL_AGENT_RUNTIME": runtime,
               "EASEL_ROOT": str(PROJECT_ROOT)}
        request = RunRequest(message, PROJECT_ROOT, env, native_id,
                             config["models"].get(runtime, ""), config["sandbox"], timeout,
                             session_key=sk, codex_auto_approve=config.get("codex_auto_approve", False))
        await asyncio.wait_for(harnesses.adapter(runtime).run(
            request, receive, ask,
            lambda identifier: harness_store.bind(SESSIONS_DIR, sk, runtime, identifier)), timeout)
        clean_end = True
        reason = "completed"
    except asyncio.CancelledError:
        reason = "stopped" if sk in _STOPPED_CHAT else "shutdown"
        emit("activity", "已停止" if reason == "stopped" else "服务关闭，本轮已取消")
    except asyncio.TimeoutError:
        reason = "timeout"
        error_message = "Agent 执行超时，已终止本轮进程"
        emit("error", error_message)
    except (HarnessError, HTTPException) as error:
        error_message = _scrub_secrets(str(error.detail if isinstance(error, HTTPException) else error))
        emit("error", error_message)
    except Exception:
        error_message = "Agent 执行失败，请检查本机 CLI、登录和模型配置"
        emit("error", error_message)
    finally:
        if claimed:
            snapshot = "".join(full_text) + (f"\n\n❌ {error_message}" if error_message else "")
            _save_turn(pk, "done", snapshot, {
                "turn_id": turn_id, "runtime": runtime,
                "clean_end": clean_end, "stop_reason": reason})
        # 注意：claim 失败（锁被占/底座已切换）时刻意**不**落盘——保留上一轮的
        # 结果快照不被失败轮覆盖（见 test_failed_ownership_check_does_not_overwrite_
        # previous_result）；错误经 SSE 事件流（job log）回放可见。
        proc.finish()
        if _RUNNING_CHAT.get(sk) is proc:
            _RUNNING_CHAT.pop(sk, None)
        if claimed:
            _STOPPED_CHAT.discard(sk)
        xlock.release()
        if locked:
            lock.release()
        _HARNESS_TASKS.discard(task)
    return "".join(full_text)


async def _run_direct_chat(req: ChatRequest, sk: str, content, system: str, emit) -> str:
    """Run one API turn with the same stop/recovery/session locking as Gateway chat."""
    pk = f"web:{sk}"
    turn_id = req.turnId or uuid.uuid4().hex
    full_text = []
    clean_end = False
    reason = "error"
    error_message = ""
    lock = _session_lock(sk)
    xlock = _CrossProcLock(sk)
    proc = _GatewayHttpProc()
    acquired = False
    claimed = False
    locked = False
    settings = read_settings(ENV_FILE)
    task = asyncio.current_task()
    _DIRECT_CHAT_TASKS.add(task)
    if lock.locked():
        emit("activity", "⏳ 这个会话上一条还在跑，排队等它结束…")
    try:
        await lock.acquire()
        locked = True
        deadline = time.monotonic() + min(TIMEOUT_CHAT, 300)
        while True:
            acquired = xlock.acquire(0)
            if acquired:
                break
            xlock.release()
            if time.monotonic() >= deadline:
                break
            await asyncio.sleep(0.2)
        if not acquired:
            raise DirectAPIError("这个会话正在另一个窗口运行，请稍候再试")
        # Existing OpenClaw conversations have different histories. Require a new
        # session rather than silently discard their context when switching modes.
        if (_transport_pin_file(sk).is_file()
                or (OPENCLAW_SESSIONS_DIR / f"{_openclaw_session_id(sk)}.jsonl").is_file()
                or (OPENCLAW_SESSIONS_DIR / f"{_openclaw_session_id(pk)}.jsonl").is_file()):
            raise DirectAPIError("此会话属于 OpenClaw，请新建会话使用 API 直连")
        _save_turn(pk, "running", "", {"turn_id": turn_id})
        claimed = True
        proc._task = asyncio.current_task()
        _RUNNING_CHAT[sk] = proc
        emit("activity", "🧠 正在通过 API 思考…")

        async def consume():
            nonlocal clean_end, reason
            async for kind, text in stream_chat(
                    settings, content, system=system,
                    history_file=history_path(SESSIONS_DIR, sk), timeout=TIMEOUT_CHAT):
                if kind == "finish":
                    clean_end, reason = True, text
                else:
                    if kind == "token":
                        full_text.append(text)
                    emit(kind, text)

        await asyncio.wait_for(consume(), timeout=TIMEOUT_CHAT)
    except asyncio.CancelledError:
        reason = "user_stopped" if sk in _STOPPED_CHAT else "cancelled"
        if reason != "user_stopped":
            raise
    except (DirectAPIError, asyncio.TimeoutError) as error:
        error_message = str(error) or "API 请求超时"
        emit("error", error_message)
    except OSError:
        error_message = "会话历史保存失败，请检查项目 outputs 目录权限"
        emit("error", error_message)
    finally:
        proc.finish()
        snapshot = "".join(full_text) + (f"\n\n❌ {error_message}" if error_message else "")
        try:
            if claimed:
                _save_turn(pk, "done", snapshot, {
                    "turn_id": turn_id, "clean_end": clean_end, "stop_reason": reason,
                })
        finally:
            if _RUNNING_CHAT.get(sk) is proc:
                _RUNNING_CHAT.pop(sk, None)
            if claimed:
                _STOPPED_CHAT.discard(sk)
            xlock.release()
            if locked:
                lock.release()
            _DIRECT_CHAT_TASKS.discard(task)
    return "".join(full_text)


@app.get("/api/chat/last/{session_id}")
async def api_chat_last(session_id: str, turn_id: str | None = None):
    """取某会话最近一轮的完整结果（SSE 断线后前端据此取回，避免丢结果）。"""
    f = _turn_file(f"web:{session_id}")
    if not f.is_file():
        return {"status": "none", "text": ""}
    try:
        payload = json.loads(f.read_text(encoding="utf-8"))
        if turn_id and payload.get("turn_id") != turn_id:
            return {"status": "stale", "text": "", "turn_id": payload.get("turn_id")}
        return payload
    except Exception:
        return {"status": "none", "text": ""}


@app.get("/api/chat/jobs/{turn_id}/stream")
async def api_chat_job_stream(turn_id: str, after: int = 0):
    """Replay missed events, then tail this turn until its terminal event arrives."""
    # A stale browser-side pendingTurnId must fail promptly instead of receiving
    # heartbeats forever. The frontend can then recover from the final snapshot.
    if not _job_event_file(turn_id).is_file():
        raise HTTPException(404, "对话任务记录不存在或已失效")

    async def events():
        cursor = max(0, after)
        idle_since = time.monotonic()
        while True:
            batch = _read_job_events(turn_id, cursor)
            if batch:
                idle_since = time.monotonic()
                for event in batch:
                    cursor = int(event["id"])
                    raw = event.get("data")
                    # job 日志里 question 的 data 已是序列化 JSON 字符串（实时流
                    # forward() 对 question 原样透传），这里若再 json.dumps 会双层
                    # 转义 → 前端 JSON.parse 拿到字符串而非对象 → ask_user 选项
                    # 卡片渲染成空壳。其余事件存原文/dict，与实时流的 dumps 规则
                    # 一致。因此仅 question 按实时流规则原样透传。
                    if event["event"] in ("question", "question_closed") and isinstance(raw, str):
                        data_out = raw
                    else:
                        data_out = json.dumps(raw, ensure_ascii=False)
                    yield {
                        "id": str(cursor),
                        "event": event["event"],
                        "data": data_out,
                    }
                    if event["event"] in ("done", "error"):
                        return
            else:
                # Keep proxy connections active; reconnecting remains safe if it still drops.
                if time.monotonic() - idle_since >= 15:
                    yield {"event": "ping", "data": "{}"}
                    idle_since = time.monotonic()
                await asyncio.sleep(0.25)

    return EventSourceResponse(events(), headers={
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
        "Content-Encoding": "identity",
    })


@app.post("/api/chat/stream")
async def api_chat_stream(req: ChatRequest):
    """SSE 真流式对话。

    `openclaw agent` CLI 会把整段模型输出缓冲到结束才打印（stdout 无增量）。真正跑模型的是
    常驻 gateway，它按自己的 OPENCLAW_RAW_STREAM/OPENCLAW_RAW_STREAM_PATH 把「模型原始流」逐
    token 写到**单个共享 jsonl**（SHARED_RAW_STREAM，见 scripts/gateway.sh）。后端在本轮开始时
    记下该文件尾偏移、实时 tail 之后追加的行，用 runId 闩锁隔离本轮，把 assistant_text_stream 的
    token delta 转成 SSE `token`、thinking delta 转成 `thinking`。stdout 仅留作错误/兜底。
    """
    # 每轮末尾追加「先查技能库」提醒，抗长对话指令衰减（对用户不可见）
    runtime = _chat_backend(req.sessionId)
    config = _harness_settings()
    direct = runtime == "api"
    alternate = runtime not in ("api", "openclaw")
    if direct:
        content, system = _direct_chat_content(req)
        message = ""
    else:
        if req.sessionId and history_path(SESSIONS_DIR, req.sessionId).is_file():
            raise HTTPException(409, "此会话属于 API 直连，请新建会话使用 OpenClaw")
        message = _chat_message(req)

    # supervisor（跑 openclaw run）与 forward（转发 SSE 给浏览器）之间的事件通道。
    # 关键：run 跑在独立后台任务里，客户端断开只结束 forward，不取消 supervisor →
    # openclaw 照常跑到底、结果落盘，前端断线后 /api/chat/last 取回。
    loop = asyncio.get_event_loop()
    client_q: asyncio.Queue = asyncio.Queue()
    CLIENT_DONE = object()

    async def supervisor():
        sk = req.sessionId or f"web-{int(time.time() * 1000)}"
        pk = f"web:{sk}"                 # 落盘 key（与 /api/chat/last 一致）
        turn_id = req.turnId or uuid.uuid4().hex
        event_seq = 0
        full_text: list[str] = []        # 累积完整回答，供断线取回
        timed_out = False                # 只有真·超时才 terminate 进程；断线绝不杀

        event_path = _job_event_file(turn_id)
        try:
            event_path.parent.mkdir(parents=True, exist_ok=True)
            event_path.write_text("", encoding="utf-8")
        except OSError:
            pass

        def to_client(kind, text=None, **extra):
            nonlocal event_seq
            event_seq += 1
            data = ({"sessionKey": extra.get("sessionKey")} if kind == "done" else text)
            event = {"id": event_seq, "event": kind, "data": data}
            try:
                with event_path.open("a", encoding="utf-8") as ef:
                    ef.write(json.dumps(event, ensure_ascii=False) + "\n")
                    ef.flush()
            except OSError:
                pass
            client_q.put_nowait({"t": kind, "text": text, "id": event_seq, **extra})

        # 秒级反馈：发出即亮「已收到」，不等 agent 冷启动（首个 SSE 事件，随流回放必达）
        to_client("activity", "⏳ 已收到…" if direct else "⏳ 已收到，正在唤醒 agent…")

        if direct:
            try:
                await _run_direct_chat(
                    req.model_copy(update={"turnId": turn_id}), sk, content, system, to_client)
            finally:
                to_client("done", sessionKey=sk)
                client_q.put_nowait(CLIENT_DONE)
            return

        if alternate:
            try:
                await _run_harness_chat(req.model_copy(update={"turnId": turn_id}),
                                        sk, message, runtime, config, to_client)
            finally:
                to_client("done", sessionKey=sk)
                client_q.put_nowait(CLIENT_DONE)
            return

        async def _run_gateway_turn(hproc):
            """HTTP 直连常驻网关跑一轮（OpenAI 兼容端点 /v1/chat/completions，原生 SSE）。

            与 CLI 路径的差异：agent 在常驻 gateway 进程里直接跑，无每轮进程冷启动；
            正文 token 经 SSE 直接进 q（与 CLI 路径共享同一消费出口）；
            收尾由主循环统一负责（proc.poll() 兼容面）。
            """
            body = {
                "model": "openclaw/default",
                "stream": True,
                "messages": [{"role": "user", "content": message}],
            }
            # session-id 必须跟 CLI 路径钉死同一个（见 _openclaw_session_id）：只带 session-key
            # 的话网关会自己另起一个 transcript —— 跨天空闲后丢历史，且万一本轮回退 CLI，
            # 两条路径会写进不同的会话文件，对话历史直接劈叉。
            headers = {"x-openclaw-session-key": f"agent:main:{sk}",
                       "x-openclaw-session-id": _openclaw_session_id(sk)}
            tool_noted = False
            saw_done = False
            got_text = False
            try:
                import httpx as _httpx
                timeout = _httpx.Timeout(TIMEOUT_CHAT + 60, connect=10)
                async with _httpx.AsyncClient(timeout=timeout) as client:
                    async with client.stream(
                            "POST", chat_completions_url(),
                            json=body, headers=headers) as resp:
                        if resp.status_code != 200:
                            raw = (await resp.aread())[:200].decode("utf-8", "replace")
                            to_client("error", f"❌ 对话失败（HTTP {resp.status_code}）：{raw[:160]}")
                            return
                        async for line in resp.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            payload = line[5:].lstrip()   # SSE 允许 `data:{…}`（冒号后无空格）
                            if payload == "[DONE]":
                                saw_done = True
                                break
                            try:
                                d = json.loads(payload)
                            except ValueError:
                                continue
                            if isinstance(d.get("error"), dict):   # 200 里夹错误对象：不能当正常流吞掉
                                to_client("error", f"❌ 网关返回错误：{str(d['error'])[:160]}")
                                return
                            delta = (d.get("choices") or [{}])[0].get("delta") or {}
                            # 思考流的两个可能来源，先到先得（`sse_thinking` 闩锁，防两路都来时重复）：
                            # ① 这里的 reasoning 增量 —— openclaw 2026.6.11 的 chat/completions
                            #    实现里 reasoning/thinking 出现 0 次，**不会**给；留着是给别的网关/
                            #    以后的版本用。② 常驻 gateway 写的共享 raw 流（见下面 _tail），
                            #    它按自己的 env 写，跟这一轮是谁触发的无关，所以 HTTP 模式照样能读到。
                            rc = delta.get("reasoning_content") or delta.get("reasoning")
                            if rc:
                                run_info["sse_thinking"] = True
                                run_info["thinking_chars"] += len(rc)
                                q.put_nowait({"t": "thinking", "text": rc})
                            c = delta.get("content")
                            if c:
                                got_text = True
                                # Already on the event loop: enqueue directly.
                                # _emit schedules a callback which can run after
                                # this coroutine's completion sentinel.
                                q.put_nowait({"t": "token", "text": c})
                            if delta.get("tool_calls") and not tool_noted:
                                tool_noted = True
                                to_client("activity", "🔧 正在执行操作…")
                # 流正常结束却既没正文也没 [DONE]：多半是端点没真开或中途断了。
                # 不报错的话这一轮会静默落一条空回答，还会被 /api/chat/last 原样取回。
                if not got_text and not saw_done:
                    to_client("error", "❌ 网关流异常结束：没有收到任何内容（检查 "
                                       "gateway.http.endpoints.chatCompletions 是否开启，"
                                       "或设 EASEL_CHAT_TRANSPORT=cli 回退）")
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                to_client("error", f"❌ 网关连接失败：{str(e)[:140]}")
            finally:
                # 先把 SENTINEL 排进 q（FIFO 保证它排在本轮所有 token 之后），再标记完成：
                # 主循环读到它时，前面的 token 必然已全部消费过。
                q.put_nowait(SENTINEL)
                hproc.finish()

        cmd = openclaw_base_cmd() + [
            "--profile", OPENCLAW_PROFILE, "agent", "--agent", "main",
            "--session-key", f"agent:main:{sk}", "--session-id", _openclaw_session_id(sk),
            "--thinking", _agent_thinking_level(),
            "--timeout", str(TIMEOUT_CHAT), "--message", message,
        ]
        env = _proxy_env()
        # 注意：不要在客户端 env 上设 OPENCLAW_RAW_STREAM*——`agent` 客户端不写 raw 流，
        # 设了也没用；raw 流开关在 gateway 侧（scripts/gateway.sh）。
        # 告诉 skill：本部署的 ask_user 选项卡片是否可用。卡片依赖 gateway 的
        # question.* RPC（仅 2026.9.x 有），2026.6.11 上桥接不可用 → skill 改用
        # 「文字问答跨轮等待」拿短信验证码，而不是空等卡片超时。
        _cards_ok = question_bridge_supported is not None and question_bridge_supported()
        env["EASEL_ASKUSER_CARDS"] = "1" if _cards_ok else "0"

        # 会话级串行：同一会话若已有请求在跑，先提示排队，等它结束再开
        # （否则两个 openclaw 进程并发写同一 session 文件 → 崩溃 rc=1 / 会话串味）。
        # 双层锁：asyncio 锁管同 web 进程内并发；flock 跨进程锁管两个标签/gateway/cron 撞同一会话。
        lock = _session_lock(sk)
        xlock = _CrossProcLock(sk)
        if lock.locked():
            to_client("activity", "⏳ 这个会话上一条还在跑，排队等它结束再开始…")
        locked = claimed = started = False
        startup_reason = "spawn_failed"
        startup_error = None
        try:
            await lock.acquire()
            locked = True
            # Match direct-API locking: nonblocking attempts with cancellable
            # sleeps. An executor worker could acquire a lock after cancellation
            # and outlive its owner, leaving the session permanently locked.
            lock_deadline = time.monotonic() + min(TIMEOUT_CHAT, 300)
            while True:
                if xlock.acquire(0):
                    break
                xlock.release()
                if time.monotonic() >= lock_deadline:
                    startup_error = "这个会话正在另一个窗口运行，请稍候再试。"
                    return
                await asyncio.sleep(0.2)

            # Only the owner of both locks may replace the session snapshot.
            _save_turn(pk, "running", "", {"turn_id": turn_id})
            claimed = True

            # 拿到两层锁之后再清洗历史：sanitize 是读-改-写，若与上一轮仍往同一
            # transcript 追加的 openclaw 并发，会丢掉 heal 读到 replace 之间追加的行。
            _heal_openclaw_session(sk)       # 清洗历史里无签名 thinking 块，防回放失效

            # 原始事件流由常驻 gateway 写到共享文件（见 SHARED_RAW_STREAM / scripts/gateway.sh），
            # 不是 agent 客户端写的。本轮开始时记下文件当前尾偏移：只读此偏移之后追加的行，
            # 再用首个新事件的 runId 闩锁本轮，隔离其它并发会话的事件。
            try:
                raw_start_offset = SHARED_RAW_STREAM.stat().st_size
            except OSError:
                raw_start_offset = 0

            # Transport selection includes a blocking network probe; keep it
            # off the event loop. It cannot start an agent or acquire locks.
            is_http = (await asyncio.to_thread(_resolve_transport, sk)) == "http"
            if is_http:
                # HTTP 直连常驻网关：无进程冷启动（agent 在 gateway 进程里跑）
                proc = _GatewayHttpProc()
            else:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    cwd=str(PROJECT_ROOT), text=True, bufsize=1, env=env,
                )
            started = True
        except asyncio.CancelledError:
            startup_reason = "cancelled"
            raise
        except Exception:
            startup_error = "❌ 启动失败，请重试"
            return
        finally:
            if not started:
                # A queued/cancelled waiter never owns the previous snapshot.
                # Persist an owned failure before releasing either lock.
                if claimed:
                    _save_turn(pk, "done", startup_error or "", {
                        "turn_id": turn_id, "clean_end": False,
                        "stop_reason": startup_reason,
                    })
                xlock.release()
                if locked:
                    lock.release()
                if startup_error:
                    to_client("error", startup_error)
                to_client("done", sessionKey=sk)
                client_q.put_nowait(CLIENT_DONE)
        _RUNNING_CHAT[sk] = proc         # 注册运行中进程（HTTP 模式为伪进程），供 /api/chat/stop
        # 经 gateway 后客户端 stdout 没有 model-fetch 标记（那是独立跑 agent 才有），先立刻
        # 给一个「正在思考」活动指示，随后 token 从共享 raw stream 流进来接管显示。
        to_client("activity", "🧠 正在思考…")

        q = asyncio.Queue()
        SENTINEL = object()
        stdout_lines = []
        run_info: dict = {"stop_reason": None, "last_ev": None, "saw_message_end": False,
                          "run_id": None,
                          "fetch_count": 0, "token_chars": 0, "thinking_chars": 0,
                          "delegated": False, "ignored_foreign_events": 0}

        def _drain_stdout():
            try:
                for line in proc.stdout:
                    stdout_lines.append(line)
                    c = re.sub(r"\x1b\[[0-9;]*m", "", line)
                    if "model-fetch] start" in c:
                        run_info["fetch_count"] += 1
                        fc = run_info["fetch_count"]
                        _emit("activity", "🧠 正在思考…" if fc == 1 else f"🔧 调用工具后继续推理（第 {fc} 步）…")
                    elif "[agent]" in c and "delegat" in c.lower():
                        run_info["delegated"] = True
                        _emit("activity", "🛠️ 制作中…")
                    m = re.search(r"ended with stopReason=(\S+)", c)
                    if m:
                        run_info["stop_reason"] = m.group(1)
            except Exception:
                pass

        def _emit(kind: str, text: str):
            loop.call_soon_threadsafe(q.put_nowait, {"t": kind, "text": text})

        # 必须等 q / run_info / _emit 都就位后再起这一轮：_run_gateway_turn 闭包引用它们，
        # 早一步 create_task 就只能靠「中间没有 await」来侥幸，改一行同步代码就会崩。
        if is_http:
            proc._task = loop.create_task(_run_gateway_turn(proc))

        # ---- ask_user 问答题桥接：轮询 gateway 的 pending question，推给前端渲染 ----
        # 背景：OpenClaw 的 ask_user 注册到 gateway 进程内，Easel 前端不消费 question RPC → 选项不可见。
        # 这里在 agent 运行期间每 2s 轮询一次，把新出现的 pending question 以 SSE `question` 事件推送，
        # 前端渲染选项卡片；用户点击后经 /api/chat/question/answer 调 question.resolve 完成回答。
        question_stop = threading.Event()
        question_poll_fut = None
        question_events_open = True

        def emit_question(kind: str, payload: str):
            if question_events_open:
                _emit(kind, _scrub_secrets(payload))

        if GatewayClient is not None and not _QBRIDGE_DISABLED:
            question_poll_fut = loop.run_in_executor(
                None, _poll_gateway_questions, sk, proc, emit_question, question_stop)

        def _handle(line: str):
            o = _raw_event_for_run(line, run_info["run_id"])
            if o is None:
                # 属其它并发 run 的事件（或无法解析）：绝不混入本轮可见流/收尾诊断，仅计数。
                try:
                    parsed = json.loads(line)
                    rid = parsed.get("runId") if isinstance(parsed, dict) else None
                    if rid is not None and run_info["run_id"] is not None and rid != run_info["run_id"]:
                        run_info["ignored_foreign_events"] += 1
                except Exception:
                    pass
                return
            # 首个带 runId 的事件闩锁本轮 run（之后 _raw_event_for_run 只放行这个 run）。
            if run_info["run_id"] is None:
                rid = o.get("runId")
                if rid is None:
                    return          # 还没拿到 runId，等下一条带 runId 的事件再闩锁
                run_info["run_id"] = rid
            ev, et, delta = o.get("event"), o.get("evtType"), o.get("delta") or ""
            # 记录最后一个 raw 事件：正常收尾 last_ev == assistant_message_end；
            # 若停在 text_delta/thinking_delta 说明输出或思考流被中断、没正常收尾（本次排查关键信号）。
            if ev:
                run_info["last_ev"] = ev
            if ev == "assistant_message_end":
                run_info["saw_message_end"] = True
            if not delta:
                return
            if ev == "assistant_text_stream" and et == "text_delta":
                if is_http:
                    # HTTP 模式正文以 SSE 为准（那条才是本请求自己的响应流）。这里再发一遍
                    # 就是同一段内容进两次队列 —— 前端会看到每个字重复。
                    return
                run_info["token_chars"] += len(delta)
                run_info["text_tail"] = (run_info.get("text_tail", "") + delta)[-160:]
                _emit("token", delta)
                return
            if ev == "assistant_thinking_stream" and et == "thinking_delta":
                if run_info.get("sse_thinking"):
                    return      # SSE 已经在供思考流了，别叠第二份
                run_info["thinking_chars"] += len(delta)
                _emit("thinking", delta)
                return

        def _tail():
            try:
                f = None
                # gateway 刚起或本轮还没产生事件时文件可能暂不存在：轮询等它出现（进程先退出则收尾）。
                while f is None:
                    try:
                        f = open(SHARED_RAW_STREAM, "r", encoding="utf-8")
                    except OSError:
                        if proc.poll() is not None:
                            return
                        time.sleep(0.04)
                with f:
                    f.seek(raw_start_offset)   # 只读本轮开始后追加的行，跳过历史轮次
                    buf = ""
                    while True:
                        chunk = f.readline()
                        if chunk == "":
                            if proc.poll() is not None:
                                buf += f.read()
                                for ln in buf.split("\n"):
                                    _handle(ln)
                                break
                            time.sleep(0.04)
                            continue
                        buf += chunk
                        while "\n" in buf:
                            ln, buf = buf.split("\n", 1)
                            _handle(ln)
            except Exception:
                pass
            finally:
                # HTTP completion belongs to _run_gateway_turn. The optional
                # raw reader must not end that stream or overtake its tokens.
                if not is_http:
                    loop.call_soon_threadsafe(q.put_nowait, SENTINEL)

        stdout_fut = None
        if is_http:
            # 正文走 SSE，但思考流**不走**：openclaw 2026.6.11 的 chat/completions 实现里
            # reasoning/thinking 一次都没出现，不回传任何思考增量。思考只存在于常驻 gateway
            # 写的那份共享 raw 流里（它按 gateway 自己的 env 写，与谁触发无关）。所以这条路径
            # 照样 tail 它——_handle 里 text_delta 在 is_http 下直接丢弃，只取 thinking_delta，
            # 正文不会进两次。不 tail 的话「💭 思考过程」在 HTTP 模式下永远是空的。
            loop.run_in_executor(None, _tail)
        else:
            stdout_fut = loop.run_in_executor(None, _drain_stdout)
            loop.run_in_executor(None, _tail)

        deadline = time.monotonic() + TIMEOUT_CHAT + 30
        emitted = False
        # 两条路径都靠「队列里读到 SENTINEL」收尾。HTTP 模式若改用带外标志（一开始就置 True），
        # 最后一批还排在 q 里没被消费的 token 会随 poll() 转为已完成而被直接丢掉——答案尾巴被截。
        tail_finished = False
        try:
            while True:
                # A raw-stream reader failure must not be mistaken for model
                # completion. Keep the session lock until the process exits.
                if tail_finished and proc.poll() is not None:
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    to_client("error", "⏱️ 请求超时")
                    break
                try:
                    item = await asyncio.wait_for(q.get(), timeout=min(10, remaining))
                except asyncio.TimeoutError:
                    continue
                if item is SENTINEL:
                    tail_finished = True
                    if proc.poll() is not None:
                        break
                    continue
                if item["t"] == "token":
                    emitted = True
                    full_text.append(item["text"])
                    to_client("token", item["text"])
                elif item["t"] == "thinking":
                    to_client("thinking", item["text"])
                elif item["t"] == "activity":
                    to_client("activity", item["text"])
                elif item["t"] in ("question", "question_closed"):
                    to_client(item["t"], item["text"])
            question_stop.set()
            if question_poll_fut is not None:
                try:
                    await asyncio.wait_for(asyncio.shield(question_poll_fut), timeout=2)
                except Exception:
                    pass
            rc = proc.poll()
            # 等 stdout 读完（stopReason 行在进程收尾时才打印，避免 _tail 先发 SENTINEL 时漏读）
            if stdout_fut is not None:
                try:
                    await asyncio.wait_for(stdout_fut, timeout=2)
                except Exception:
                    pass
            sr = run_info.get("stop_reason")
            if not emitted:
                clean = clean_agent_output("".join(stdout_lines))
                if clean:
                    emitted = True
                    full_text.append(clean)
                    to_client("token", clean)
                elif rc not in (0, None):
                    err = clean_agent_output("".join(stdout_lines))[:200]
                    to_client("error", f"❌ 执行失败（退出码 {rc}）{' — ' + err if err else ''}")
            # 收尾检测：即使已吐了内容，只要不是「正常收尾」就显式告知——
            # 否则被截断（触顶）/被杀（负载）/流被中断，都会被当成「清晰地答完了」，
            # 用户看到的就是「答一半突然停、也不说做完」（本 bug 根因）。
            # 正常收尾的唯一标志：raw 流最后一个事件是 assistant_message_end。
            # 用户显式「停止」不是异常中断 → 不报「被中断」告警（前端已就地标注「已停止」）。
            if (emitted or run_info["thinking_chars"]) and sk not in _STOPPED_CHAT:
                note = None
                if sr and sr in ("max_tokens", "length", "model_length"):
                    note = (f"\n\n---\n⚠️ 上面这条**被截断**了（stopReason={sr}，单条回复触顶）。"
                            f"回我「继续」我接着写完，或让我把任务拆小一点。")
                elif rc not in (0, None):
                    note = (f"\n\n---\n⚠️ 生成**被中断**（退出码 {rc}，多半是超时或系统负载过高把进程杀了），"
                            f"不是正常收尾。可以让我重试。")
                elif sr == "tool_use":
                    note = ("\n\n---\n⚠️ 我刚做完这一步、**正要执行下一步操作时中断了**"
                            "（本轮以工具调用结尾却没能继续，前端把它当成答完了）。回我「继续」我接着做。")
                elif run_info.get("last_ev") not in (None, "assistant_message_end"):
                    note = ("\n\n---\n⚠️ 这条**可能没写完**——模型的输出/思考流被中断、没有正常收尾"
                            "（多为网络或模型代理把长回复的流掐断了）。回我「继续」，或重试。")
                elif run_info.get("text_tail", "").rstrip()[-1:] in ("：", ":"):
                    # 正常收尾但正文停在冒号 = 模型"我要做X："后没接着做（多为要接工具/下一步却断了）。
                    # 用户实测「所有莫名停止都停在冒号」——这一条兜住这个模式。
                    note = ("\n\n---\n⚠️ 我似乎停在了冒号处、没接着把后面的内容/操作做出来。"
                            "回我「继续」我补上。")
                if note:
                    full_text.append(note)
                    to_client("token", note)
        finally:
            # 只有真的在 HTTP 上跑出了内容，才把这个会话钉到 http 上。钉早了（比如选路时就钉）
            # 会把一个其实没跑成的会话锁死在 http，之后每轮都往一条不通的路上撞；而钉住之后
            # 就绝不能再换回 cli —— 网关那份 transcript 我们按名字找不回来，换边即丢历史。
            if is_http and emitted:
                _pin_transport(sk, "http")
            user_stopped = sk in _STOPPED_CHAT
            _STOPPED_CHAT.discard(sk)
            # Reaching finally while the child is alive means timeout, explicit
            # stop, cancellation, or an internal stream failure. Never release
            # the session locks while such a process can still write history.
            if proc.poll() is None:
                try:
                    proc.terminate()
                except OSError:
                    pass
                try:
                    await asyncio.to_thread(proc.wait, timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        proc.kill()
                        await asyncio.to_thread(proc.wait, timeout=2)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
            question_stop.set()
            question_events_open = False
            while not q.empty():
                queued = q.get_nowait()
                if queued is not SENTINEL and queued["t"] in ("question", "question_closed"):
                    to_client(queued["t"], queued["text"])
            # 诊断日志：每次对话流收尾都记一行，供事后定位「莫名停下」到底是哪种情况。
            try:
                DEBUG_DIR.mkdir(parents=True, exist_ok=True)
                tail = clean_agent_output("".join(stdout_lines))[-800:]
                with (DEBUG_DIR / "chat-stream.jsonl").open("a", encoding="utf-8") as lf:
                    lf.write(json.dumps({
                        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "session": sk,
                        "rc": proc.poll(),
                        "stop_reason": run_info["stop_reason"],
                        "last_ev": run_info["last_ev"],
                        "clean_end": run_info["last_ev"] == "assistant_message_end",
                        "saw_message_end": run_info["saw_message_end"],
                        "fetch_count": run_info["fetch_count"],
                        "token_chars": run_info["token_chars"],
                        "thinking_chars": run_info["thinking_chars"],
                        "delegated": run_info["delegated"],
                        "ignored_foreign_events": run_info["ignored_foreign_events"],
                        "text_tail": run_info.get("text_tail", ""),
                        "stdout_tail": tail,
                    }, ensure_ascii=False) + "\n")
            except Exception:
                pass
            # 落盘完整结果：后端跑完整轮不依赖客户端连接，断线后前端用 /api/chat/last 取回
            _save_turn(pk, "done", "".join(full_text), {
                "turn_id": turn_id,
                "clean_end": run_info.get("last_ev") == "assistant_message_end",
                "stop_reason": "user_stopped" if user_stopped else run_info.get("stop_reason"),
            })
            xlock.release()
            lock.release()
            _RUNNING_CHAT.pop(sk, None)
            to_client("done", sessionKey=sk)
            client_q.put_nowait(CLIENT_DONE)

    # 把 run 跑在独立后台任务里（持强引用防 GC）——客户端断开不取消它。
    task = asyncio.create_task(supervisor())
    _BG_TASKS.add(task)

    def _bg_done(t):
        _BG_TASKS.discard(t)
        if t.cancelled():
            client_q.put_nowait(CLIENT_DONE)
            return
        try:
            exc = t.exception()   # 取出异常避免「never retrieved」告警
        except Exception:
            exc = None
        if exc is not None:
            # supervisor 意外崩溃：解锁 forward，别让它空等
            try:
                client_q.put_nowait(CLIENT_DONE)
            except Exception:
                pass
    task.add_done_callback(_bg_done)

    async def forward():
        """纯转发：从 client_q 取事件 yield 给浏览器。

        客户端断开（关标签/代理掐断）只会结束本生成器，supervisor 任务不受影响，
        继续把 openclaw run 跑完并落盘 → 前端断线后 /api/chat/last 取回完整结果。
        """
        idle_since = time.monotonic()
        while True:
            try:
                item = await asyncio.wait_for(client_q.get(), timeout=10)
            except asyncio.TimeoutError:
                # 长时间无输出（等模型长回复 / 制作类长任务）→ 发心跳，让用户知道没卡死。
                # 用独立的 `heartbeat` 事件，不走 `activity`：否则会覆盖掉真实的
                # 「🧠 正在思考…/🛠️ 制作中…」状态与思考流（防呆消息把思考设计顶掉的根因）。
                # 发出后重置 idle_since → 心跳按 30s 一次的节奏，不再每 10s 重复刷屏。
                if time.monotonic() - idle_since >= 30:
                    idle_since = time.monotonic()
                    yield {"event": "heartbeat", "data": json.dumps(
                        "仍在处理中，未卡住…（复杂或制作类任务会花点时间）", ensure_ascii=False)}
                continue
            if item is CLIENT_DONE:
                break
            idle_since = time.monotonic()
            t = item["t"]
            if t == "token":
                yield {"id": str(item["id"]), "event": "token", "data": json.dumps(item["text"], ensure_ascii=False)}
            elif t == "thinking":
                yield {"id": str(item["id"]), "event": "thinking", "data": json.dumps(item["text"], ensure_ascii=False)}
            elif t == "activity":
                yield {"id": str(item["id"]), "event": "activity", "data": json.dumps(item["text"], ensure_ascii=False)}
            elif t in ("question", "question_closed"):
                yield {"id": str(item["id"]), "event": t, "data": item["text"]}
            elif t == "error":
                yield {"id": str(item["id"]), "event": "error", "data": json.dumps(item["text"], ensure_ascii=False)}
            elif t == "done":
                yield {"id": str(item["id"]), "event": "done", "data": json.dumps({"sessionKey": item.get("sessionKey")}, ensure_ascii=False)}

    return EventSourceResponse(forward(), headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Content-Encoding": "identity"})


class QuestionAnswerRequest(BaseModel):
    sessionId: str | None = None
    questionId: str
    answers: dict  # {questionId: [optionValues]}
    resolvedBy: str | None = None


@app.post("/api/chat/question/answer")
async def api_question_answer(req: QuestionAnswerRequest):
    """前端点击 ask_user 选项后调用：转发 gateway question.resolve，让等待的 agent 拿到答案。"""
    if req.questionId.startswith("harness_"):
        record = _HARNESS_QUESTIONS.get(req.questionId)
        if record is None:
            return {"ok": False, "expired": True, "status": "expired",
                    "error": "权限或问答请求已过期，请重试"}
        required = {question["questionId"] for question in record["questions"]}
        if set(req.answers or {}) != required:
            raise HTTPException(400, "回答与当前问题不匹配")
        if record["future"].done():
            return {"ok": False, "expired": True, "status": "resolved", "error": "请求已回答"}
        record["future"].set_result(req.answers)
        return {"ok": True}
    if _direct_api_enabled():
        raise HTTPException(409, "API 直连模式使用文字问答，请新建对话")
    if _harness_settings()["runtime"] != "openclaw":
        raise HTTPException(409, "此问题属于旧 OpenClaw 会话，请使用当前底座的新对话")
    if GatewayClient is None:
        return {"ok": False, "error": "gateway question bridge unavailable"}
    client = GatewayClient()
    try:
        client.connect()
        result = client.resolve(req.questionId, req.answers or {}, req.resolvedBy)
        return {"ok": True, "result": result}
    except GatewayQuestionClosedError as error:
        return {"ok": False, "expired": True, "status": "expired", "reason": error.reason,
                "error": "此问题已关闭或过期，答案未发送。请在输入框中继续对话。"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        client.close()


class QuestionStatusRequest(BaseModel):
    questionIds: list[str]


@app.post("/api/chat/question/status")
async def api_question_status(req: QuestionStatusRequest):
    """批量查 question 状态（重放旧事件时过滤已解决的题）。"""
    if req.questionIds and all(identifier.startswith("harness_") for identifier in req.questionIds):
        return {"ok": True, "questions": {
            identifier: {"status": _HARNESS_QUESTIONS.get(identifier, {}).get("status", "not_found")}
            for identifier in req.questionIds}}
    if _direct_api_enabled():
        return {"ok": True, "questions": {qid: {"status": "not_found"} for qid in req.questionIds}}
    if _harness_settings()["runtime"] != "openclaw":
        return {"ok": False, "questions": {}}
    if GatewayClient is None:
        return {"ok": False, "questions": {}}
    client = GatewayClient()
    try:
        client.connect()
        out = {}
        for qid in req.questionIds:
            try:
                q = client.get_question(qid)
                out[qid] = _gateway_question_state(q)
            except GatewayQuestionClosedError as error:
                out[qid] = {"status": error.status}
            except GatewayUnsupportedError:
                return {"ok": False, "error": "gateway question status unsupported", "questions": {}}
            except GatewayQuestionError:
                out[qid] = {"status": "unknown"}
            except Exception:
                out[qid] = {"status": "unknown"}   # 网络/连接异常：保持 unknown（前端保留显示，宁不缺题）
        return {"ok": True, "questions": out}
    except Exception as e:
        return {"ok": False, "error": str(e), "questions": {}}
    finally:
        client.close()


class StopRequest(BaseModel):
    sessionId: str | None = None


@app.post("/api/chat/stop")
async def api_chat_stop(req: StopRequest):
    """用户显式停止当前会话正在跑的对话 agent：终止进程 → supervisor 收尾释放会话锁 →
    下一句立刻能发（不再卡「上一条还在跑」）。仅此显式入口会杀进程；客户端断线不经此路径。"""
    sk = (req.sessionId or "").strip()
    proc = _RUNNING_CHAT.get(sk) if sk else None
    if proc is not None and proc.poll() is None:
        _STOPPED_CHAT.add(sk)          # 标记为用户停止，供 supervisor 正常收尾（不报「被中断」）
        try:
            proc.terminate()
        except OSError:
            pass
        try:
            await asyncio.to_thread(proc.wait, timeout=3)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except OSError:
                pass
        # supervisor removes the running marker only after persisting the final
        # snapshot and releasing both session locks.
        deadline = time.monotonic() + 5
        while _RUNNING_CHAT.get(sk) is proc and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        return {"stopped": True}
    return {"stopped": False}          # 没有在跑（可能已结束）→ 前端照常清理即可


@app.post("/api/chat")
async def api_chat(req: ChatRequest):
    """非流式对话（备选）。"""
    runtime = _chat_backend(req.sessionId)
    if runtime not in ("api", "openclaw"):
        message = _chat_message(req)
        sk = req.sessionId or uuid.uuid4().hex
        errors = []
        def emit(kind, text):
            if kind == "error":
                errors.append(text)
        result = await _run_harness_chat(req, sk, message, runtime, _harness_settings(), emit,
                                         interactive=False)
        if errors:
            raise HTTPException(502, errors[0])
        return {"response": result, "sessionKey": sk}
    if runtime == "api":
        content, system = _direct_chat_content(req)
        errors = []
        def emit(kind, text):
            if kind == "error":
                errors.append(text)
        sk = req.sessionId or uuid.uuid4().hex
        result = await _run_direct_chat(req, sk, content, system, emit)
        if errors:
            raise HTTPException(502, errors[0])
        return {"response": result, "sessionKey": sk}
    if req.sessionId and history_path(SESSIONS_DIR, req.sessionId).is_file():
        raise HTTPException(409, "此会话属于 API 直连，请新建会话使用 OpenClaw")
    # 每轮末尾追加「先查技能库」提醒，抗长对话指令衰减（对用户不可见）
    message = _chat_message(req)
    loop = asyncio.get_event_loop()
    # chat 可能中途触发制作层长任务 → 用 TIMEOUT_CHAT，与流式 /api/chat/stream 一致（勿用 300s）
    result = await loop.run_in_executor(None, run_agent_sync, message, TIMEOUT_CHAT, req.sessionId)
    return {"response": result}


class SkillRequest(BaseModel):
    skill: str
    input: str
    persona: str | None = None


@app.post("/api/skill")
async def api_skill(req: SkillRequest):
    if _direct_api_enabled():
        raise HTTPException(409, "API 直连模式支持聊天；SKILL 执行需要具备本机工具的 Agent 运行时")
    skill_full = find_skill(req.skill)
    if skill_full is None:
        raise HTTPException(404, f"SKILL '{req.skill}' 不存在")
    message = f"{_persona_prefix(req.persona)}请执行 /{skill_full}，内容如下：\n\n{req.input}"
    # 统一给足超时：制作类 SKILL（生视频/多镜合成）可能跑很久，取安全上界
    timeout = TIMEOUT_PRODUCE
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, run_agent_sync, message, timeout)
    return {"response": result}


app.get('/api/outputs')(api_outputs)


app.get('/api/artifacts/archive')(api_artifact_archive)


app.get('/api/output/{path:path}')(api_output)


app.get('/api/media/{path:path}')(api_media)


UPLOAD_EXTS = IMAGE_EXTS | VIDEO_EXTS | {
    ".pdf", ".txt", ".md", ".markdown", ".csv", ".json", ".srt", ".vtt",
    ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".mp3", ".wav", ".m4a"}
MAX_UPLOAD_MB = 50


def _unique_upload_path(dest: Path, filename: str) -> Path:
    """同一上传批次内保留所有同名文件，不让后一个静默覆盖前一个。"""
    target = dest / filename
    if not target.exists():
        return target
    source = Path(filename)
    index = 2
    while True:
        target = dest / f"{source.stem} ({index}){source.suffix}"
        if not target.exists():
            return target
        index += 1


app.delete('/api/output/{path:path}')(api_output_delete)


@app.post("/api/upload")
async def api_upload(
    files: list[UploadFile] = File(...),
    sessionId: str = Form(...),
):
    """Store chat attachments in a session-scoped inbox and return opaque refs."""
    scope = _attachment_scope(sessionId)
    batch = time.strftime('%Y%m%d-') + uuid.uuid4().hex[:6]
    dest = OUTPUTS_DIR / "_inbox" / scope / batch
    dest.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in files:
        name = Path(f.filename or "file").name
        ext = Path(name).suffix.lower()
        if ext not in UPLOAD_EXTS:
            raise HTTPException(400, f'不支持的文件类型：{ext or name}')
        # 分块流式落盘 + 边写边限：与 /api/upload/local 同样模式，避免先整读进内存
        # （超限的多 GB 文件会把 web 进程撑爆）才报 413。
        cap = MAX_UPLOAD_MB * 1024 * 1024
        target = _unique_upload_path(dest, name)
        size = 0
        try:
            with open(target, 'wb') as out:
                while True:
                    chunk = await f.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > cap:
                        raise HTTPException(413, f'{name} 超过 {MAX_UPLOAD_MB}MB 上限')
                    out.write(chunk)
        except HTTPException:
            try:
                target.unlink()
            except OSError:
                pass
            raise
        rel = f"_inbox/{scope}/{batch}/{target.name}"
        saved.append({"id": _attachment_id(scope, rel), "name": target.name, "path": rel})
    if not saved:
        raise HTTPException(400, '没有文件')
    return {"ok": True, "files": saved}


@app.get("/api/upload/limits")
async def api_upload_limits():
    """当前上传上限（MB）——前端在文件超限时据此切换到本地复制通道。"""
    return {"ok": True, "max_mb": MAX_UPLOAD_MB}


@app.post("/api/upload/local")
async def api_upload_local(
    files: list[UploadFile] = File(...),
    sessionId: str = Form(...),
):
    """超过上传上限的文件复制通道：1MB 分块流式落盘（不整读进内存）、无大小上限；
    产出与 /api/upload 同构的附件引用（id/name/path），附件校验与清单链路零改动。"""
    scope = _attachment_scope(sessionId)
    batch = time.strftime('%Y%m%d-') + uuid.uuid4().hex[:6]
    dest = OUTPUTS_DIR / "_inbox" / scope / batch
    dest.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in files:
        name = Path(f.filename or "file").name
        ext = Path(name).suffix.lower()
        if ext not in UPLOAD_EXTS:
            raise HTTPException(400, f'不支持的文件类型：{ext or name}')
        target = _unique_upload_path(dest, name)
        with open(target, 'wb') as out:
            while True:
                chunk = await f.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        rel = f"_inbox/{scope}/{batch}/{target.name}"
        saved.append({"id": _attachment_id(scope, rel), "name": target.name, "path": rel})
    if not saved:
        raise HTTPException(400, '没有文件')
    return {"ok": True, "files": saved}


app.get('/api/accounts')(api_accounts)


app.post('/api/login/{platform}')(api_login_start)


app.get('/api/login/{platform}/status')(api_login_status)


app.post('/api/login/{platform}/sms')(api_login_sms)


app.get('/api/accounts/{platform}/credentials')(api_get_credentials)


app.post('/api/accounts/{platform}/credentials')(api_save_credentials)


app.post('/api/accounts/{platform}/mp-login')(api_mp_login_start)


app.get('/api/accounts/{platform}/mp-login/status')(api_mp_login_status)


app.get('/api/accounts/{platform}/whoami')(api_account_whoami)


app.post('/api/logout/{platform}')(api_logout)


# 归因层：可抓创作数据的平台（多数走 Playwright 登录态；bilibili 用 biliup cookies 不起浏览器、

from easel.web_services.analytics import bind as _bind_analytics
_bind_analytics(into=globals())
app.get('/api/analytics/platforms')(api_analytics_platforms)
app.get('/api/analytics/{platform}')(api_analytics)
# wechat-oa 走 mp 后台会话 Playwright 拦截数据 XHR）












MEDIA_REQUIRED = {"xiaohongshu", "douyin", "kuaishou", "weixin-channels", "bilibili"}
VIDEO_ONLY_PUBLISH = {"douyin", "weixin-channels", "bilibili"}   # 只能发视频的平台


class PublishRequest(BaseModel):
    title: str = ''
    body: str = ''
    media: list[str] = []
    tags: str = ''
    persona: str = ''


class ManualPublishRequest(BaseModel):
    title: str = Field(default='', max_length=1000)
    body: str = Field(default='', max_length=100000)
    tags: str = Field(default='', max_length=2000)
    media: list[str] = Field(default_factory=list, max_length=32)
    reviewed: StrictBool = False


@app.get("/api/publishing-policy")
def api_publishing_policy():
    mode = publishing_mode(read_settings(ENV_FILE))
    return {"mode": mode, "automaticSubmission": mode == "automated"}


def _require_automated_publishing() -> None:
    if publishing_mode(read_settings(ENV_FILE)) != "automated":
        raise HTTPException(403, '当前为人工发布模式，请审核后复制或导出，在平台官方发布页亲自提交')


@app.post("/api/manual-publish/{platform}/export")
def api_manual_publish_export(platform: str, req: ManualPublishRequest):
    """Build a local handoff package; never contact a platform or mark it published."""
    try:
        package = build_package(OUTPUTS_DIR, platform, req.title, req.body,
                                req.tags, req.media, req.reviewed)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    return {"path": package.relative_to(OUTPUTS_DIR.resolve()).as_posix(),
            "filename": package.name, "published": False}


def _write_publish_status(status_file: Path, state: str, message: str = '') -> None:
    """写异步发布状态（与 login_state 同格式），原子写。"""
    try:
        status_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = status_file.with_suffix('.tmp')
        tmp.write_text(json.dumps({'state': state, 'message': message, 'ts': int(time.time())},
                                  ensure_ascii=False), encoding='utf-8')
        os.replace(tmp, status_file)
    except Exception:
        pass


def _read_publish_status(platform: str) -> dict:
    st = PUBLISH_DIR / f'{platform}.json'
    if st.is_file():
        try:
            d = json.loads(st.read_text(encoding='utf-8'))
            return {'state': d.get('state', 'unknown'), 'message': d.get('message', '')}
        except Exception:
            pass
    return {'state': 'unknown', 'message': ''}


def _record_successful_publish(title: str, body: str, cfg: dict, profile: str = '',
                               tags: str = '', ptype: str = '') -> None:
    try:
        scripts_dir = str(SHARED_SCRIPTS)
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        import calendar_ops
        with _schedule_lock():
            calendar_ops.record_publish(cfg['name'], title, note=body[:200],
                                        tags=tags, ptype=ptype,
                                        source='publish-page', profile=profile,
                                        data_path=SCHEDULE_FILE, forward_log=True)
    except Exception:
        pass


def _run_publish_bg(platform: str, cmd: list, title: str, body: str, cfg: dict,
                    status_file: Path, code_file: Path, profile: str = '',
                    tags: str = '', ptype: str = '') -> None:
    """后台线程跑发布脚本（脚本自身把 starting/sms_required/verifying/success/error 写进 status_file）。
    结束后兜底补写终态 + 记 _publish.log + 成功则回流排期。"""
    ok = False
    out = err = ''
    try:
        proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=_publish_env(),
                              capture_output=True, text=True, timeout=900)
        ok = proc.returncode == 0
        out, err = proc.stdout or '', proc.stderr or ''
    except subprocess.TimeoutExpired:
        err = '发布超时（>900s）'
    except Exception as e:  # noqa: BLE001
        err = f'发布进程异常：{e}'
    try:
        with (OUTPUTS_DIR / '_publish.log').open('a', encoding='utf-8') as lf:
            lf.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} {platform}(async) ok={ok} =====\n")
            lf.write('CMD: ' + ' '.join(cmd) + '\nSTDOUT:\n' + out[-2000:] + '\nSTDERR:\n' + err[-2000:] + '\n')
    except Exception:
        pass
    # 脚本正常会写终态；异常/超时没写到时兜底补一个
    if _read_publish_status(platform)['state'] not in ('success', 'error'):
        _write_publish_status(status_file, 'success' if ok else 'error',
                              '发布成功' if ok else ('\n'.join((err or out).strip().splitlines()[-4:]) or '发布失败'))
    try:
        code_file.unlink()
    except OSError:
        pass
    if ok:
        _record_successful_publish(title, body, cfg, profile, tags, ptype)


def _start_async_publish(platform: str, cmd: list, title: str, body: str, cfg: dict,
                         status_file: Path, code_file: Path, profile: str = '',
                         tags: str = '', ptype: str = '') -> dict:
    """启动异步发布：清旧码/状态 → 起后台线程 → 立即返回。前端轮询 /api/publish/{p}/status，
    遇 sms_required 弹输入框、提交到 /api/publish/{p}/sms。"""
    try:
        code_file.unlink()
    except OSError:
        pass
    _write_publish_status(status_file, 'starting', '发布中…（若触发风控会要求短信验证）')
    threading.Thread(target=_run_publish_bg,
                     args=(platform, cmd, title, body, cfg, status_file, code_file, profile, tags, ptype),
                     daemon=True).start()
    # 关键：**不返回 ok:true**——这只是「已启动」的应答，真正结果要靠轮询 /status。
    # 若这里给 ok:true，旧前端会把它当「已发布」立刻显示成功（假成功 bug，真机踩过）。
    return {'async': True, 'pending': True, 'message': '发布已启动，请稍候…'}


@app.get("/api/publish/{platform}/status")
async def api_publish_status(platform: str):
    """轮询异步发布状态：starting/sms_required/verifying/success/error。"""
    if platform not in LOGIN_RUNNERS:
        raise HTTPException(404, '未知平台')
    return {'mode': 'publish', **_read_publish_status(platform)}


@app.post("/api/publish/{platform}/sms")
async def api_publish_sms(platform: str, req: SmsCodeRequest):
    """发布触发短信墙时回填验证码（写发布 runner 轮询的一次性验证码文件）。"""
    _require_automated_publishing()
    if platform not in LOGIN_RUNNERS:
        raise HTTPException(404, '未知平台')
    code = ''.join(ch for ch in (req.code or '') if ch.isdigit())
    if not (4 <= len(code) <= 8):
        raise HTTPException(400, '验证码应为 4-8 位数字')
    PUBLISH_DIR.mkdir(parents=True, exist_ok=True)
    (PUBLISH_DIR / f'{platform}.code').write_text(code, encoding='utf-8')
    return {'ok': True}


@app.post("/api/publish/{platform}")
async def api_publish(platform: str, req: PublishRequest):
    """一键发布：分发到对应 publisher 脚本真发（--exec）。二次确认在前端。"""
    _require_automated_publishing()
    cfg = LOGIN_RUNNERS.get(platform)
    if not cfg:
        raise HTTPException(404, '未知平台')
    backend = cfg['backend']
    if backend == 'unsupported':
        raise HTTPException(400, f"{cfg['name']} 暂不支持一键发布")
    profile = (req.persona or '').strip()
    if profile and (not valid_persona_name(profile) or not profile_exists(profile)):
        raise HTTPException(400, '选择的画像不存在或名称非法')
    if not req.title.strip() and not req.body.strip():
        raise HTTPException(400, '标题/正文不能为空')
    imgs, vids = [], []
    for rel in req.media or []:
        full = _safe_output_path(rel)
        ext = full.suffix.lower()
        if ext in VIDEO_EXTS:
            vids.append(str(full))
        elif ext in IMAGE_EXTS:
            imgs.append(str(full))
    if platform in MEDIA_REQUIRED and not imgs and not vids:
        raise HTTPException(400, f"{cfg['name']} 需附带图片或视频")
    if imgs and vids:
        raise HTTPException(400, '同一条内容不能同时发图片和视频，请二选一')
    if platform in VIDEO_ONLY_PUBLISH and not vids:
        raise HTTPException(400, f"{cfg['name']} 只能发视频，请附带一个视频文件")
    title = req.title.strip() or req.body.strip()[:20]
    tags = req.tags or ''
    publish_type = '视频' if vids else ('文章' if platform == 'wechat-oa' else '图文')
    py = sys.executable
    if platform == 'xiaohongshu':
        base = [py, str(SHARED_SCRIPTS / 'xhs_publish.py')]
        cmd = base + ['publish-video', '--no-proxy', '--video', vids[0]] if vids else base + ['publish', '--no-proxy', '--images', ','.join(imgs)]
        cmd += ['--title', title, '--content', req.body, '--tags', tags, '--exec']
    elif platform == 'bilibili':
        # B站投稿：直接调 biliup CLI（需 cookies.json，PATH 上有 biliup）。必须视频；
        # tid=36「知识」；B站投稿必须≥1 标签，无则兜底「日常」。
        bili_tag = tags.replace('#', '').replace('，', ',').strip().strip(',') or '日常'
        cmd = ['biliup', '-u', str(PROJECT_ROOT / 'cookies.json'), 'upload', vids[0],
               '--title', title[:80], '--tid', '36', '--copyright', '1', '--tag', bili_tag]
        if req.body.strip():
            cmd += ['--desc', req.body[:2000]]
    elif platform == 'douyin':
        base = [py, str(SHARED_SCRIPTS / 'douyin_publish.py')]
        cmd = base + ['publish-video', '--no-proxy', '--video', vids[0]] if vids else base + ['publish', '--no-proxy', '--images', ','.join(imgs)]
        cmd += ['--title', title, '--content', req.body, '--tags', tags, '--exec']
        # 抖音发布可能触发风控短信墙——异步跑 + 状态/验证码文件，前端轮询到 sms_required 时弹输入框
        PUBLISH_DIR.mkdir(parents=True, exist_ok=True)
        status_file = PUBLISH_DIR / 'douyin.json'
        code_file = PUBLISH_DIR / 'douyin.code'
        cmd += ['--status-file', str(status_file), '--sms-code-file', str(code_file)]
        return _start_async_publish(platform, cmd, title, req.body, cfg, status_file, code_file,
                                    profile, tags, publish_type)
    elif platform == 'wechat-oa':
        # 微信公众号：走「后台会话」发布（免 AppID/AppSecret、免 IP 白名单）。
        # 正文 MD → 公众号 HTML（skill 排版器）→ 会话建草稿（weixin_mp_stats.py publish，内嵌图传 mp CDN）。
        if _mp_login_status().get('state') != 'success':
            raise HTTPException(400, '公众号后台未登录：请先在账号页点「登录公众号后台」扫码')
        if not imgs:
            raise HTTPException(400, '公众号文章需要一张封面图，请附带至少一张图片')
        if vids:
            raise HTTPException(400, '公众号发图文文章，请附带封面/正文图片而非视频')
        cover = imgs[0]
        PUBLISH_DIR.mkdir(parents=True, exist_ok=True)
        stamp = uuid.uuid4().hex[:12]
        md_path = PUBLISH_DIR / f'wechat-oa-{stamp}.md'
        html_path = PUBLISH_DIR / f'wechat-oa-{stamp}.html'
        body_md = req.body or ''
        extra_imgs = imgs[1:]
        if extra_imgs:
            body_md += "\n\n" + "\n\n".join(f'![]({p})' for p in extra_imgs)
        md_path.write_text(f"# {title}\n\n{body_md}\n", encoding='utf-8')
        conv = await asyncio.to_thread(
            subprocess.run, [py, str(WECHAT_SKILL_SCRIPTS / 'html_converter.py'),
                             str(md_path), '-o', str(html_path)],
            cwd=str(PROJECT_ROOT), env=_proxy_env(),
            capture_output=True, text=True, timeout=60)
        if conv.returncode != 0 or not html_path.is_file():
            raise HTTPException(500, f"排版失败：{(conv.stderr or conv.stdout or '')[-200:]}")
        wx_proxy = os.environ.get('EASEL_PROXY') or os.environ.get('https_proxy') or ''
        cmd = [py, str(SHARED_SCRIPTS / 'weixin_mp_stats.py'), 'publish', '--proxy', wx_proxy,
               '--html', str(html_path), '--cover', cover, '--title', title,
               '--digest', (req.body or '').strip()[:100], '--author', '']
    else:
        cmd = [py, str(SHARED_SCRIPTS / 'web_publisher.py'), 'publish',
               '--platform', cfg['wp'], '--title', title, '--desc', req.body,
               '--tags', tags, '--exec']
        media = vids[0] if vids else (imgs[0] if imgs else None)
        if media:
            cmd += ['--media', media]
    # 公众号走后台会话（Playwright，脚本自带 --proxy，默认直连）；其余平台走 _publish_env
    pub_env = _proxy_env() if platform == 'wechat-oa' else _publish_env()
    try:
        proc = await asyncio.to_thread(subprocess.run, cmd, cwd=str(PROJECT_ROOT), env=pub_env,
                                       capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        raise HTTPException(504, '发布超时（媒体处理慢或流程卡住）')
    ok = proc.returncode == 0
    tail = (proc.stderr or proc.stdout or '').strip().splitlines()
    detail = '\n'.join(tail[-8:])
    try:
        with (OUTPUTS_DIR / '_publish.log').open('a', encoding='utf-8') as lf:
            lf.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} {platform} rc={proc.returncode} ok={ok} =====\n")
            lf.write('CMD: ' + ' '.join(cmd) + '\n')
            lf.write('STDOUT:\n' + (proc.stdout or '')[-2000:] + '\n')
            lf.write('STDERR:\n' + (proc.stderr or '')[-2000:] + '\n')
    except Exception:
        pass
    if ok:
        _record_successful_publish(title, req.body, cfg, profile, tags, publish_type)
    return {'ok': ok, 'message': '发布成功' if ok else '发布失败（见 detail）', 'detail': detail}


class ProfileBuildRequest(BaseModel):
    name: str
    form: dict


@app.post("/api/profile/build")
async def api_profile_build(req: ProfileBuildRequest):
    """首次引导：表单 → 写基线画像（确定性，秒可用）→ **后台**跑 agent 分析社媒链接增强。

    改异步：立即返回（基线已写、画像即可用），避免 agent 增强(~2min)阻塞请求被 code-server
    代理超时掐断（前端曾因此报 API 400）。前端轮询 /api/profile/build/status/{name} 看增强进度。
    """
    name = (req.name or '').strip()  # 自动去掉首尾空格
    if not name:
        raise HTTPException(400, '画像名不能为空（去掉首尾空格后为空，请输入有效名称）')
    if '/' in name or '\\' in name:
        raise HTTPException(400, '画像名不能包含 / 或 \\ 字符，请改掉后重试')
    if name.startswith(('.', '_')):
        raise HTTPException(400, '画像名不能以 . 或 _ 开头，请换个开头')
    pd = PROFILES_DIR / name
    if pd.exists():
        raise HTTPException(409, f'画像「{name}」已存在，请换一个名字')
    _write_baseline_profile(name, req.form or {})
    instruction = _form_to_instruction(name, req.form or {})
    msg = (f"请执行 /skill-profile-builder 完善已存在的画像「{name}」。用户已通过表单提供以下信息，我已按此写好 profiles/{name}"
           f"/ 的基线六维文件。请：①尽力抓取用户给的社媒链接分析已发内容/风格/受众（抓不到就降级，标注[待补充]，勿臆造）②据分析结果润色/补全各维度文件 ③给出一句话完成度摘要。表单信息如下：\n\n{instruction}")

    _write_profile_status(name, 'running', 'AI 正在分析并增强画像…')

    def _enhance() -> None:
        try:
            log = run_agent_sync(msg, TIMEOUT_PRODUCE)
            _write_profile_status(name, 'done', log)
        except Exception as e:  # noqa: BLE001
            _write_profile_status(name, 'failed', f'AI 增强失败（基线画像已可用）：{e}')

    threading.Thread(target=_enhance, daemon=True).start()
    # 基线已写、画像立即可用；增强在后台，前端轮询状态
    return {'created': pd.is_dir(), 'name': name, 'async': True, 'status': 'running'}


def _profile_status_file(name: str) -> Path:
    return PROFILE_BUILD_DIR / f'{name}.json'


def _write_profile_status(name: str, state: str, log: str = '') -> None:
    """原子写画像增强状态。"""
    try:
        PROFILE_BUILD_DIR.mkdir(parents=True, exist_ok=True)
        f = _profile_status_file(name)
        tmp = f.with_suffix('.tmp')
        tmp.write_text(json.dumps({'state': state, 'log': log, 'ts': int(time.time())},
                                  ensure_ascii=False), encoding='utf-8')
        os.replace(tmp, f)
    except Exception:
        pass


@app.get("/api/profile/build/status/{name}")
async def api_profile_build_status(name: str):
    """查画像增强进度：running / done / failed / unknown。"""
    f = _profile_status_file(name)
    if f.is_file():
        try:
            d = json.loads(f.read_text(encoding='utf-8'))
            return {'state': d.get('state', 'unknown'), 'log': d.get('log', '')}
        except Exception:
            pass
    return {'state': 'unknown', 'log': ''}


def _form_to_instruction(name: str, form: dict) -> str:
    def g(k: str, default: str = '（未填）') -> str:
        v = form.get(k)
        if isinstance(v, list):
            return '、'.join(str(x) for x in v) if v else default
        return str(v).strip() if v not in (None, '') else default
    links = form.get('links') or {}
    links_txt = '\n'.join(f'  - {p}: {u}' for p, u in links.items() if u) or '  （未提供）'
    return (f"画像名：{name}\n运营平台：{g('platforms')}\n起号状态：{g('accountStage')}"
            f"\n社媒主页链接：\n{links_txt}\n想做的方向：{g('direction')}"
            f"\n为什么做/我的优势：{g('reason')}\n运营目标：{g('goal')}"
            f"\n想产出的形式：{g('formats')}\n喜欢看的内容/对标账号：{g('likes')}"
            f"\n期望调性：{g('tone')}\n不做的内容/红线：{g('avoid')}\n")


def _write_baseline_profile(name: str, form: dict) -> None:
    """从表单确定性生成六维基线文件。链接派生字段标 [待 AI 分析]。"""
    pd = PROFILES_DIR / name
    pd.mkdir(parents=True, exist_ok=True)

    def g(k: str, default: str = '') -> str:
        v = form.get(k)
        if isinstance(v, list):
            return '、'.join(str(x) for x in v)
        return str(v).strip() if v not in (None, '') else default
    direction = g('direction') or '[待补充]'
    reason = g('reason') or '[待补充]'
    goal = g('goal')
    formats = g('formats')
    tone = g('tone') or '[待分析]'
    likes = g('likes')
    avoid = g('avoid')
    platforms = form.get('platforms') or []
    links = form.get('links') or {}
    (pd / 'identity.md').write_text(
        f"# 身份定位\n\n## 我是谁\n\n{direction}\n\n## 差异化\n\n{reason}\n\n## 内容方向\n\n{direction}"
        f"{'（形式：' + formats + '）' if formats else ''}\n"
        f"{'运营目标：' + goal if goal else ''}\n",
        encoding='utf-8')
    (pd / 'style.md').write_text(
        f"# 内容风格\n\n## 语气\n\n{tone}\n\n## 开头结构\n\n[待 AI 分析已发内容]\n\n## 视觉风格\n\n[待 AI 分析]\n\n## 内容节奏\n\n{formats or '[待补充]'}\n\n## 标志性元素\n\n[待 AI 分析]\n",
        encoding='utf-8')
    (pd / 'audience.md').write_text(
        '# 目标受众\n\n## 核心人群\n\n[待 AI 分析/待补充]\n\n## 兴趣标签\n\n[待补充]\n\n## 痛点\n\n[待补充]\n\n## 互动特征\n\n[待 AI 分析已发内容]\n',
        encoding='utf-8')
    plat_lines = []
    for p in platforms:
        url = links.get(p, '')
        plat_lines.append(f"## {p}\n\n主页：{url or '[待补充]'}\n粉丝量级 / 内容形式：[待补充]\n")
    (pd / 'platforms.md').write_text(
        '# 平台运营\n\n' + ('\n'.join(plat_lines) if plat_lines else '[待补充]\n'),
        encoding='utf-8')
    (pd / 'preferences.md').write_text(
        f"# 偏好与红线\n\n## 要做的\n\n{direction}\n\n## 不做的\n\n{avoid or '[待补充]'}\n\n## 合规底线\n\n{avoid or '[待补充]'}\n",
        encoding='utf-8')
    (pd / 'memory.md').write_text(
        f"# 经验沉淀\n\n## 内容洞察\n\n{'喜欢的内容/对标：' + likes if likes else '[待 AI 分析已收藏/点赞]'}\n\n## 踩过的坑\n\n[待积累]\n",
        encoding='utf-8')


@app.delete("/api/session/{session_key}")
async def api_delete_session(session_key: str):
    """删除 OpenClaw 本地的 session 记录。"""
    if session_key in _RUNNING_CHAT or _session_lock(session_key).locked():
        raise HTTPException(409, "请先停止当前对话再删除")
    record = harness_store.binding(SESSIONS_DIR, session_key)
    if record and record.get("runtime") != "openclaw":
        from easel.harnesses.rpc import close_sessions
        await close_sessions(session_key)
        harness_store.binding_path(SESSIONS_DIR, session_key).unlink(missing_ok=True)
        _turn_file(f"web:{session_key}").unlink(missing_ok=True)
        return {"deleted": True, "nativeHistoryDeleted": False}
    direct_history = history_path(SESSIONS_DIR, session_key)
    if direct_history.is_file():
        if session_key in _RUNNING_CHAT:
            raise HTTPException(409, "请先停止当前对话再删除")
        direct_history.unlink()
        _turn_file(f"web:{session_key}").unlink(missing_ok=True)
        return {"deleted": True}
    if _direct_api_enabled():
        return {"deleted": False, "reason": "session not found"}
    sessions_file = _oc_state_dir() / 'agents' / 'main' / 'sessions' / 'sessions.json'
    if not sessions_file.is_file():
        return {'deleted': False, 'reason': 'sessions file not found'}
    data = json.loads(sessions_file.read_text(encoding="utf-8"))
    full_key = f'agent:main:{session_key}' if not session_key.startswith('agent:') else session_key
    for key in (full_key, session_key):
        if key in data:
            del data[key]
            sessions_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return {'deleted': True}
    return {'deleted': False, 'reason': 'session not found'}


# Source commands/URLs are loaded exclusively from a trusted local configuration file.
# The browser only selects registered IDs; it cannot supply executable commands.
from easel.trends.service import TrendService, failure_group as trend_failure_group
from easel.trends.sources import ConfigError as TrendConfigError, load_sources as load_trend_sources
from easel.trends import management as trend_management
from easel.trends.protocol import CollectorError as TrendCollectorError, safe_json as trend_safe_json
from easel.trends.protocol import MAX_MANAGEMENT_BYTES

_TREND_SERVICE = TrendService()


def _trend_registry():
    warnings = []
    try:
        environment = read_settings(ENV_FILE)
        sources = load_trend_sources(PROJECT_ROOT, environment, warnings=warnings)
        return sources, environment, warnings
    except Exception:
        return [], {}, ["热点配置暂时无法读取，请检查本地配置；其他工作台功能不受影响。"]


@app.get("/api/trends/sources")
async def api_trend_sources():
    sources, _, warnings = _trend_registry()
    return {"version": 1, "sources": [source.public() for source in sources], "warnings": warnings}


def _trend_manager_guard(request: Request):
    # Check the real transport peer even when Origin/Host have been forged by a remote client.
    if not _loopback_peer(request) or (request.headers.get("origin") and request.headers["origin"] not in _LOCAL_ORIGINS):
        raise HTTPException(403, "数据源管理仅允许本机操作")


@app.get("/api/trends/manage")
async def api_trend_manage(request: Request):
    _trend_manager_guard(request)
    try:
        return await asyncio.to_thread(trend_management.describe, PROJECT_ROOT, read_settings(ENV_FILE))
    except Exception:
        raise HTTPException(409, "无法读取数据源管理配置，请修复本地配置文件后重试") from None


@app.post("/api/trends/manage")
async def api_trend_manage_write(request: Request):
    _trend_manager_guard(request)
    length = request.headers.get("content-length", "")
    if length and (not length.isascii() or not length.isdigit() or len(length) > 10):
        raise HTTPException(400, "无效的请求长度")
    if length.isdigit() and int(length) > MAX_MANAGEMENT_BYTES:
        raise HTTPException(413, "数据源操作最多 256 KiB")
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_MANAGEMENT_BYTES:
            raise HTTPException(413, "数据源操作最多 256 KiB")
        raw.extend(chunk)
    try:
        value = trend_safe_json(bytes(raw), MAX_MANAGEMENT_BYTES)
        if not isinstance(value, dict):
            raise TrendConfigError("数据源操作必须是对象")
        return await asyncio.to_thread(trend_management.update, PROJECT_ROOT, read_settings(ENV_FILE), value)
    except TrendConfigError as error:
        raise HTTPException(400, str(error)) from None
    except TrendCollectorError:
        raise HTTPException(400, "数据源操作不是有效 JSON 或字段过深") from None
    except Exception:
        raise HTTPException(409, "配置保存失败，原配置已保留，请检查文件权限或修复配置") from None


@app.get("/api/trends")
async def api_trends(platforms: str | None = None, limit: int = 12):
    if platforms is not None and len(platforms) > 8192:
        raise HTTPException(400, "数据源查询过长")
    sources, environment, warnings = _trend_registry()
    registry = {source.id: source for source in sources}
    selected = ([source.id for source in sources if source.default] if platforms is None else
                list(dict.fromkeys(p.strip() for p in platforms.split(",") if p.strip() in registry)))
    results = await asyncio.gather(*(
        asyncio.to_thread(_TREND_SERVICE.get, registry[identifier], environment, max(1, min(limit, 30)))
        for identifier in selected), return_exceptions=True)
    groups = [result if isinstance(result, dict) else trend_failure_group(registry[identifier])
              for identifier, result in zip(selected, results)]
    return {"version": 1, "trends": groups, "updated": int(time.time()), "warnings": warnings}


SCHEDULE_FILE = OUTPUTS_DIR / "_schedule.json"

# _schedule.json 读-改-写串行化：发布回流（后台线程 _run_publish_bg + 事件循环上的
# api_publish 成功路径）与增删改端点并发时，不加锁会互相覆盖丢记录。
_SCHEDULE_LOCK = threading.Lock()


from easel.web_services.planning import bind as _bind_shared_planning
_bind_shared_planning(into=globals())


app.get('/api/schedule')(api_schedule_list)


app.post('/api/schedule')(api_schedule_create)


app.put('/api/schedule/{sid}')(api_schedule_update)


app.delete('/api/schedule/{sid}')(api_schedule_delete)


app.get('/api/schedule/context')(api_schedule_context)


IDEAS_FILE = OUTPUTS_DIR / "_ideas.json"


app.get('/api/ideas')(api_ideas_list)


app.post('/api/ideas')(api_ideas_create)


app.put('/api/ideas/{iid}')(api_ideas_update)


app.delete('/api/ideas/{iid}')(api_ideas_delete)


if __name__ == "__main__":
    import uvicorn
    from easel.runtime_env import web_environment

    os.environ.update(web_environment(dict(os.environ)))
    openclaw_base_cmd.cache_clear()
    port = int(os.environ.get("EASEL_PORT", "7860"))
    proxy_url = os.environ.get("VSCODE_PROXY_URI", "").replace("{{port}}", str(port))
    print("\n  ✦ Easel Web")
    print(f"  http://localhost:{port}")
    if proxy_url:
        print(f"  {proxy_url}")
    print()
    # 监听 0.0.0.0（非仅回环）是为了兼容 Docker/远程容器端口转发访问 Easel 的场景；
    # local_write_guard/TrustedHostMiddleware 只挡浏览器发起的跨站请求，见其注释里的局限说明。
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
