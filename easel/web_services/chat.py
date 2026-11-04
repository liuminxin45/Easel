"""One source for Easel native turn supervision and process controls.

Extracted from web.app without importing the application or private workbench.
The standalone app binds its existing namespace; alternate hosts supply ports.
"""
from __future__ import annotations
import asyncio
import os
import re
import subprocess
import time
import uuid
from pathlib import Path
if os.name == 'nt':
    import msvcrt
else:
    import fcntl
from easel import harnesses
from easel.harnesses import store as harness_store
from easel.harnesses.base import RunRequest, HarnessError
from easel.direct_api import read_settings
from easel.timeouts import TIMEOUT_CHAT
from fastapi import HTTPException
from .binding import bind_functions

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


class SessionFileLock:
    """跨进程会话锁（fcntl.flock）：同一会话同一时刻只允许一个 openclaw 进程在跑。

    现有 _session_lock（asyncio）只在单个 web 进程内串行；挡不住两个浏览器标签/常驻 gateway/
    cron 并发碰同一会话 → openclaw 抛 EmbeddedAttemptSessionTakeoverError（rc=1，答一半就停）。
    flock 在持有进程退出时自动释放，无 stale 死锁。返回 True=拿到锁，False=超时未拿到。
    """

    def __init__(self, root, sk: str):
        self._root = Path(root)
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", sk)[:120]
        self._path = self._root / f"{safe}.lock"
        self._fh = None
        self.acquired = False

    def acquire(self, timeout: float = 300.0, poll: float = 0.5) -> bool:
        try:
            self._root.mkdir(parents=True, exist_ok=True)
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


async def _run_harness_chat(req: ChatRequest, sk: str, message: str, runtime: str,
                            config: dict, emit, timeout: int = TIMEOUT_CHAT, *, interactive=True,
                            run_request=None, bind_native=None, propagate_errors=False,
                            stop_requested=None, on_dispatch=None) -> str:
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
        request = run_request or RunRequest(message, PROJECT_ROOT, env, native_id,
                             config["models"].get(runtime, ""), config["sandbox"], timeout,
                             session_key=sk, codex_auto_approve=config.get("codex_auto_approve", False))
        if stop_requested and stop_requested():raise asyncio.CancelledError()
        if on_dispatch is not None:on_dispatch()
        await asyncio.wait_for(harnesses.adapter(runtime).run(
            request, receive, ask,
            bind_native or (lambda identifier: harness_store.bind(SESSIONS_DIR, sk, runtime, identifier))), timeout)
        clean_end = True
        reason = "completed"
    except asyncio.CancelledError:
        reason = "stopped" if sk in _STOPPED_CHAT or stop_requested and stop_requested() else "shutdown"
        emit("activity", "已停止" if reason == "stopped" else "服务关闭，本轮已取消")
        if propagate_errors:raise
    except asyncio.TimeoutError:
        reason = "timeout"
        error_message = "Agent 执行超时，已终止本轮进程"
        emit("error", error_message)
        if propagate_errors:raise
    except (HarnessError, HTTPException) as error:
        error_message = _scrub_secrets(str(error.detail if isinstance(error, HTTPException) else error))
        emit("error", error_message)
        if propagate_errors:raise
    except Exception:
        error_message = "Agent 执行失败，请检查本机 CLI、登录和模型配置"
        emit("error", error_message)
        if propagate_errors:raise
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



def bind(*, into):
    return bind_functions(__import__(__name__, fromlist=['']), ('_run_harness_chat',), into=into)


def create_chat_context(root, *, backend, environment, snapshot, ask, scrub, running=None):
    root = Path(root).resolve()
    sessions = root / 'outputs/_sessions'
    locks = {}
    def session_lock(key):
        return locks.setdefault(key, asyncio.Lock())
    ports = {'PROJECT_ROOT': root, 'SESSIONS_DIR': sessions, 'ENV_FILE': root / '.env',
             '_session_lock': session_lock, '_CrossProcLock': lambda key: SessionFileLock(sessions, key),
             '_chat_backend': backend, '_save_turn': snapshot, '_harness_ask': ask,
             '_scrub_secrets': scrub, 'read_settings': lambda path: environment,
             '_proxy_env': lambda: {}, '_STOPPED_CHAT': set(),
             '_RUNNING_CHAT': running if running is not None else {}, '_HARNESS_TASKS': set()}
    return bind_functions(__import__(__name__, fromlist=['']), ('_run_harness_chat',), ports)
