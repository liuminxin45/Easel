"""Codex 0.160 JSON-RPC transport. No shell, public listener, or store writes."""
import json
import os
import pathlib
import queue
import shutil
import subprocess
import threading
import time

_desktop=pathlib.Path.home()/'AppData/Local/Programs/OpenAI/Codex/bin/codex.exe'
CODEX = pathlib.Path(os.environ.get('AI_DESK_CODEX') or (str(_desktop) if _desktop.is_file() else shutil.which('codex.exe') or shutil.which('codex') or str(_desktop)))


class RPCError(RuntimeError):
    def __init__(self, error):
        self.error = error
        super().__init__(str(error.get('message', 'Codex request failed')))

    @property
    def code(self):
        value = self.error.get('code')
        return value if type(value) is int else None

    @property
    def safe_code(self):
        """Fixed diagnostics only; native messages may contain private input."""
        message = str(self.error.get('message', '')).lower()
        if self.code == -32600 and message.startswith('no rollout found for thread id '):
            return 'thread_rollout_missing'
        if self.code == -32600 and message.startswith('thread not loaded:'):
            return 'thread_not_loaded'
        if any(word in message for word in ('writer', 'owned', 'already running', 'another process')):
            return 'thread_owned_elsewhere'
        return 'native_request_rejected'


class RPCNotSentError(ConnectionError):
    """Positive evidence that this call never entered stdin.write.

    This describes one transport call, not an entire job's history. A caller
    must never use it to erase an earlier dispatch/queue/turn boundary.
    """
    not_sent = True
    stage = 'before_write'

    def __init__(self, code='connection_unavailable'):
        allowed = {'connection_unavailable', 'connection_closed', 'process_exited', 'serialization_failed'}
        self.code = code if isinstance(code, str) and code in allowed else 'connection_unavailable'
        super().__init__('本次请求尚未写入本地 Codex 连接')


class RPC:
    def __init__(self, on_event=None, executable=None):
        self.on_event = on_event or (lambda event: None)
        self.pending = {}
        self.lock = threading.RLock()
        self.sequence = 0
        self.closed = False
        self.events = queue.Queue()
        self.process = subprocess.Popen(
            [str(executable or CODEX), 'app-server', '--stdio'], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, encoding='utf-8',
            text=True, bufsize=1, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        threading.Thread(target=self._events, daemon=True).start()
        threading.Thread(target=self._read, daemon=True).start()
        try:
            self.call('initialize', {'clientInfo': {'name': 'poster-toolbox',
                      'title': '贴图制作', 'version': '1.0'},
                      'capabilities': {'experimentalApi': True}}, timeout=30)
            self.write({'method': 'initialized'})
        except BaseException:
            self.close()
            raise

    def write(self, message):
        with self.lock:
            if self.closed:
                raise RPCNotSentError('connection_closed')
            if self.process.poll() is not None:
                raise RPCNotSentError('process_exited')
            try:
                serialized = json.dumps(message, ensure_ascii=False) + '\n'
            except Exception:
                # No raw message, params, serialization diagnostic or payload
                # is retained by this safe transport classification.
                raise RPCNotSentError('serialization_failed') from None
            # The side-effect boundary begins at this method invocation. A
            # partial write, encoding error or flush failure remains unknown.
            self.process.stdin.write(serialized)
            self.process.stdin.flush()

    def call(self, method, params=None, timeout=30):
        response = queue.Queue(1)
        with self.lock:
            self.sequence += 1
            key = self.sequence
            self.pending[key] = response
        try:
            self.write({'id': key, 'method': method, 'params': params or {}})
            try:
                result = response.get(timeout=timeout)
            except queue.Empty:
                raise TimeoutError('本地 Codex 响应超时；正在核对发送状态') from None
            if isinstance(result, BaseException):
                raise result
            if 'error' in result:
                raise RPCError(result['error'])
            return result.get('result', {})
        finally:
            with self.lock:
                self.pending.pop(key, None)

    def _read(self):
        try:
            for line in self.process.stdout:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if 'id' in event and ('result' in event or 'error' in event):
                    with self.lock:
                        target = self.pending.get(event['id'])
                    if target:
                        try: target.put_nowait(event)
                        except queue.Full: pass  # A duplicate response must not stall the reader.
                else:
                    # Host callbacks can wait for files, SQLite or another RPC.
                    # Preserve their order without blocking transport responses.
                    self.events.put(event)
        finally:
            self.events.put(None)
            with self.lock:
                for target in self.pending.values():
                    try:
                        target.put_nowait(ConnectionError('本地 Codex 连接已断开'))
                    except queue.Full:
                        pass

    def _events(self):
        while True:
            event = self.events.get()
            if event is None: return
            # Server requests still require explicit Host action; never approve here.
            try: self.on_event(event)
            except Exception: pass

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            try:
                self.process.stdin.close()
            except OSError:
                pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=5)
