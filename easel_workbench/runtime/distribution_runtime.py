"""Host-only, DPAPI-backed access to the constrained WechatSync bridge.

Credentials travel solely in an encrypted local vault and a child stdin pipe.
Probe/receipt documents contain public account identifiers, never credentials.
Official 1.1.0 has no remote content readback: draft writes remain unknown.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import subprocess
import threading
import uuid

from easel_workbench.runtime.desk import stamp
from easel_workbench.runtime.distribution_catalog import SUPPORTED_DRAFTS, identity_metadata

BRIDGE_URL = 'ws://127.0.0.1:9527'
CLI_VERSION = '1.1.0'
CLI_SHA = 'b792a30402f070b536c3dcc3090ff7ab483d4e77357ce893e564939224c7008b'
EXTENSION_ARCHIVE_SHA = 'dfb191decd63a45063c4f6d8f7687745e5ecebe34363792dd6781b657d69fd29'
EXTENSION_MANIFEST_SHA = '4dbf8ac30804b8c192af895fa2069a629de0505954d010f7b080279d01bcb40e'
EXTENSION_BACKGROUND_SHA = '1c45a07a8323cdc2a92c38349381e1d24d560b19c0b59a2567479ab6661de4b8'
ENTROPY = b'ai-news-desk/distribution-secrets/v1'
_HANDLE = re.compile(r'vault:([a-f0-9]{32})\Z')
BRIDGE_ID = 'bridge-discovery'


class VaultError(RuntimeError):
    """A deliberately non-diagnostic message: never include plaintext/blob data."""


class BridgeError(RuntimeError):
    pass


class BridgeTimeout(BridgeError):
    pass


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value):
        raise ValueError('连接标识无效')
    return value


def process_identity(pid):
    """PID plus creation identity; reused/dead PIDs never prove a live worker."""
    if type(pid) is not int or pid <= 0:
        return None
    if os.name == 'nt':
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        try:
            code = wintypes.DWORD()
            kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:
                return None
            times = [wintypes.FILETIME() for _ in range(4)]
            kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
            if not kernel.GetProcessTimes(handle, *(ctypes.byref(item) for item in times)):
                return None
            return str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return pathlib.Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except (OSError, IndexError):
        return None


@contextmanager
def _bridge_mutex(root):
    """Cross-process/cross-session protection for credential pointer receipts."""
    if os.name != 'nt':
        raise VaultError('桥接配置需要此Windows主机的凭据保护')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    key = hashlib.sha256(str(pathlib.Path(root).resolve()).casefold().encode()).hexdigest()
    handle = kernel.CreateMutexW(None, False, 'Global\\AiDeskDistributionBridge-' + key)
    if not handle:
        raise VaultError('桥接配置锁暂不可用，请稍后用原操作重试')
    owned = False
    try:
        waited = kernel.WaitForSingleObject(handle, 30000)
        if waited not in (0, 0x80):
            raise VaultError('桥接正在配置，请稍后用原操作重试')
        owned = True
        yield
    finally:
        if owned:
            kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)


class _Blob(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]


def _blob(raw):
    buffer = ctypes.create_string_buffer(raw, max(1, len(raw)))
    return _Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer


def _dpapi(raw, decrypt=False):
    if os.name != 'nt':
        raise VaultError('此凭据库仅在当前Windows用户下可用')
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    incoming, incoming_buffer = _blob(raw)
    entropy, entropy_buffer = _blob(ENTROPY)
    outgoing = _Blob()
    if decrypt:
        function = crypt.CryptUnprotectData
        function.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
        args = (ctypes.byref(incoming), None, ctypes.byref(entropy), None, None, 1, ctypes.byref(outgoing))
    else:
        function = crypt.CryptProtectData
        function.argtypes = [ctypes.POINTER(_Blob), wintypes.LPCWSTR, ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
        args = (ctypes.byref(incoming), 'AI Desk distribution', ctypes.byref(entropy), None, None, 1, ctypes.byref(outgoing))
    function.restype = wintypes.BOOL
    try:
        if not function(*args):
            raise VaultError('凭据保护失败，请在原Windows账号下重新配置')
        return ctypes.string_at(outgoing.pbData, outgoing.cbData)
    finally:
        ctypes.memset(incoming_buffer, 0, len(incoming_buffer))
        ctypes.memset(entropy_buffer, 0, len(entropy_buffer))
        if outgoing.pbData:
            ctypes.memset(outgoing.pbData, 0, outgoing.cbData)
            kernel.LocalFree(ctypes.cast(outgoing.pbData, ctypes.c_void_p))


def _private_acl(path, directory=False):
    if os.name != 'nt':
        raise VaultError('Windows凭据目录不可用')
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    token = wintypes.HANDLE()
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.OpenProcessToken.restype = wintypes.BOOL
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
        raise VaultError('无法保护Windows凭据权限')
    sid_string = wintypes.LPWSTR()
    descriptor = ctypes.c_void_p()
    try:
        length = wintypes.DWORD()
        advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(length))
        buffer = ctypes.create_string_buffer(length.value)
        if not advapi.GetTokenInformation(token, 1, buffer, length, ctypes.byref(length)):
            raise VaultError('无法保护Windows凭据权限')
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p)).contents.value
        advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
        if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(sid_string)):
            raise VaultError('无法保护Windows凭据权限')
        flags = 'OICI' if directory else ''
        sddl = f'D:P(A;{flags};FA;;;SY)(A;{flags};FA;;;{sid_string.value})'
        advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
        if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
            raise VaultError('无法保护Windows凭据权限')
        advapi.SetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
        if not advapi.SetFileSecurityW(str(path), 4 | 0x80000000, descriptor):
            raise VaultError('无法保护Windows凭据权限')
    finally:
        if descriptor:
            kernel.LocalFree(descriptor)
        if sid_string:
            kernel.LocalFree(ctypes.cast(sid_string, ctypes.c_void_p))
        kernel.CloseHandle(token)


class DPAPIVault:
    def __init__(self, root):
        self.root = pathlib.Path(root).resolve()
        self.directory = self.root / 'data/distribution-secrets'
        self._lock = threading.RLock()

    def _ensure(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        resolved = self.directory.resolve()
        if not resolved.is_relative_to(self.root) or self.directory.is_symlink():
            raise VaultError('凭据目录不安全')
        _private_acl(self.directory, True)

    def _path(self, name):
        if not re.fullmatch(r'[a-z0-9-]{1,100}', name):
            raise VaultError('凭据引用无效')
        path = self.directory / (name + '.dpapi')
        if not path.resolve().is_relative_to(self.directory.resolve()) or path.is_symlink():
            raise VaultError('凭据引用无效')
        return path

    def _write(self, name, value):
        raw = _json(value)
        if len(raw) > 64 * 1024:
            raise VaultError('凭据或主机核验记录过大')
        with self._lock:
            self._ensure()
            target = self._path(name)
            encrypted = b'NDV1' + _dpapi(raw)
            temporary = self.directory / (uuid.uuid4().hex + '.tmp')
            try:
                with temporary.open('xb') as stream:
                    stream.write(encrypted)
                    stream.flush()
                    os.fsync(stream.fileno())
                _private_acl(temporary)
                os.replace(temporary, target)
                _private_acl(target)
            finally:
                if temporary.exists():
                    temporary.unlink()

    def _read(self, name):
        try:
            path = self._path(name)
            if not path.is_file() or path.stat().st_size > 128 * 1024:
                raise VaultError('凭据引用不可用')
            encrypted = path.read_bytes()
            if not encrypted.startswith(b'NDV1'):
                raise VaultError('凭据保护格式无效')
            document = json.loads(_dpapi(encrypted[4:], True))
            if not isinstance(document, dict):
                raise VaultError('凭据保护格式无效')
            return document
        except (OSError, ValueError, UnicodeError):
            raise VaultError('凭据无法读取，请在原Windows账号下重新配置') from None

    def put(self, connection_id, secret):
        _identifier(connection_id)
        if not isinstance(secret, dict):
            raise ValueError('凭据需要对象')
        handle = uuid.uuid4().hex
        return self.put_reserved(connection_id, secret, 'vault:' + handle)

    def put_reserved(self, connection_id, secret, reference):
        """Server-only recovery of a previously DPAPI-reserved opaque handle."""
        _identifier(connection_id)
        match = _HANDLE.fullmatch(reference) if isinstance(reference, str) else None
        if not match or not isinstance(secret, dict):
            raise VaultError('凭据保留标识无效')
        if self._path(match.group(1)).exists():
            if self.get(reference, connection_id) != secret:
                raise VaultError('已签发凭据不可改作其他内容')
            return reference
        self._write(match.group(1), {'schema_version': 1, 'connection_id': connection_id, 'secret': copy.deepcopy(secret)})
        return reference

    def get(self, reference, connection_id=None):
        match = _HANDLE.fullmatch(reference) if isinstance(reference, str) else None
        if not match:
            raise VaultError('凭据引用无效')
        document = self._read(match.group(1))
        if document.get('schema_version') != 1 or not isinstance(document.get('secret'), dict) or connection_id is not None and document.get('connection_id') != connection_id:
            raise VaultError('凭据不属于此连接')
        return copy.deepcopy(document['secret'])

    def validate(self, reference):
        try:
            self.get(reference)
            return True
        except (VaultError, ValueError, TypeError):
            return False

    def read_proof(self, key):
        try:
            return self._read('proof-' + key)
        except VaultError:
            return None

    def write_proof(self, key, value):
        self._write('proof-' + key, value)


class DistributionRuntime:
    def __init__(self, box, *, vault=None, bridge=None, node_path=None, bridge_path=None, tool_root=None, timeout=45, cache_seconds=120):
        self.box = box
        self.root = pathlib.Path(box.root).resolve()
        self.vault = vault or DPAPIVault(self.root)
        self._bridge = bridge
        receipt = self._receipt()
        local = pathlib.Path(os.environ.get('LOCALAPPDATA', str(pathlib.Path.home() / 'AppData/Local')))
        self.node_path = pathlib.Path(node_path or receipt.get('node_path') or local / 'nvm/v24.19.0/node.exe').resolve()
        self.bridge_path = pathlib.Path(bridge_path or pathlib.Path(__file__).resolve().parent / 'scripts/distribution_bridge.mjs').resolve()
        self.tool_root = pathlib.Path(tool_root or receipt.get('tool_root') or pathlib.Path.home() / '.codex/tools/wechatsync').resolve()
        self.timeout = max(2, min(float(timeout), 360))
        self.cache_seconds = max(1, min(int(cache_seconds), 300))
        self._discovery = None

    def _receipt(self):
        path = self.root / 'data/distribution-install.json'
        try:
            if not path.is_file() or path.stat().st_size > 32768:
                return {}
            value = json.loads(path.read_text(encoding='utf-8'))
            return value if isinstance(value, dict) and value.get('schema_version') == 1 else {}
        except (OSError, ValueError):
            return {}

    def configure_secret(self, connection_id, value):
        _identifier(connection_id)
        if not isinstance(value, dict) or set(value) - {'WECHATSYNC_TOKEN', 'bridge_url', 'extension_id'}:
            raise ValueError('此连接仅接收本机草稿桥接配置')
        token = value.get('WECHATSYNC_TOKEN')
        if not isinstance(token, str) or not 16 <= len(token) <= 4096 or re.search(r'[\x00-\x20\x7f]', token):
            raise ValueError('本机桥接令牌格式无效')
        if value.get('bridge_url', BRIDGE_URL) != BRIDGE_URL:
            raise ValueError('桥接仅允许本机固定地址')
        extension_id = value.get('extension_id') or self._receipt().get('extension_id')
        if not isinstance(extension_id, str) or not re.fullmatch(r'[a-p]{32}', extension_id):
            raise ValueError('尚无此电脑实际核验的扩展身份，请先完成安装')
        return self.vault.put(connection_id, {'WECHATSYNC_TOKEN': token, 'bridge_url': BRIDGE_URL, 'extension_id': extension_id})

    def validate_secret_ref(self, reference):
        return self.vault.validate(reference)

    def _bridge_pointer(self):
        path = self.root / 'data/distribution-bridge.json'
        try:
            if not path.is_file() or path.stat().st_size > 8192:
                return None
            value = json.loads(path.read_text(encoding='utf-8'))
            if (not isinstance(value, dict) or value.get('schema_version') != 1
                    or not _HANDLE.fullmatch(value.get('secret_ref', ''))):
                return None
            return {key: value.get(key) for key in ('schema_version', 'secret_ref', 'configured_at', 'operation_id')}
        except (OSError, ValueError, TypeError):
            return None

    def _write_bridge_pointer(self, value):
        directory = self.root / 'data'
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / 'distribution-bridge.json'
        if not target.resolve().is_relative_to(self.root) or target.is_symlink():
            raise VaultError('桥接配置路径不安全')
        temporary = directory / ('.distribution-bridge-' + uuid.uuid4().hex + '.tmp')
        try:
            with temporary.open('xb') as stream:
                stream.write(_json(value));stream.flush();os.fsync(stream.fileno())
            _private_acl(temporary)
            os.replace(temporary, target)
            _private_acl(target)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _global_settings(self):
        pointer = self._bridge_pointer()
        if not pointer:
            raise VaultError('尚未配置此电脑的同步桥接')
        settings = self.vault.get(pointer['secret_ref'], BRIDGE_ID)
        self._validate_settings(settings)
        if settings['extension_id'] != self._receipt().get('extension_id'):
            settings.clear()
            raise VaultError('实际扩展身份已变化，请重新配对此电脑')
        return settings

    def bridge_status(self):
        installation = self._installation_evidence()
        pointer = self._bridge_pointer()
        pointer_exists = (self.root / 'data/distribution-bridge.json').is_file()
        configured = False
        paired = False
        try:
            if pointer:
                settings = self.vault.get(pointer['secret_ref'], BRIDGE_ID)
                self._validate_settings(settings)
                configured = True
                paired = settings['extension_id'] == self._receipt().get('extension_id')
                settings.clear()
        except Exception:
            pass
        if configured and not paired or pointer and not configured or pointer_exists and pointer is None:
            status, message = 'needs_pairing', '此电脑的桥接身份需要重新配对；不会读取其他浏览器的凭据。'
        elif not installation['installed'] or not installation['node_available'] or not self.bridge_path.is_file():
            status, message = 'not_installed', '本机同步工具或安装证据尚未就绪。'
        elif not configured:
            status, message = 'not_configured', '在此电脑配置一次同步桥接，即可只读发现账号。'
        else:
            status, message = 'ready', '本机桥接已配置；账号发现与执行核验分别进行。'
        token = os.environ.get('WECHATSYNC_TOKEN', '')
        available = (not configured and isinstance(token, str) and 16 <= len(token) <= 4096
                     and not re.search(r'[\x00-\x20\x7f]', token))
        return {'status': status, 'configured': configured, 'installed': installation['installed'],
                'checked_at': self._discovery.get('checked_at') if self._discovery else None,
                'configured_at': pointer.get('configured_at') if pointer else None,
                'bootstrap_available': bool(available), 'message': message}

    def configure_bridge(self, value, operation_id=None):
        """Idempotent private bootstrap, including crash-before-pointer recovery."""
        if value is None:
            value = {}
        if not isinstance(value, dict) or set(value) - {'WECHATSYNC_TOKEN'}:
            raise ValueError('全局桥接仅接收一次本机同步令牌')
        if 'WECHATSYNC_TOKEN' in value and (not isinstance(value['WECHATSYNC_TOKEN'], str)
                or not 16 <= len(value['WECHATSYNC_TOKEN']) <= 4096 or re.search(r'[\x00-\x20\x7f]', value['WECHATSYNC_TOKEN'])):
            raise ValueError('本机同步令牌格式无效')
        operation_id = _identifier(operation_id or 'bridge-' + uuid.uuid4().hex)
        with _bridge_mutex(self.root):
            pointer = self._bridge_pointer()
            key = hashlib.sha256(('bridge-configure\0' + operation_id).encode()).hexdigest()
            input_fingerprint = hashlib.sha256(_json(value)).hexdigest()
            record = self.vault.read_proof(key)
            if record:
                if record.get('kind') != 'bridge-configure' or record.get('input_fingerprint') != input_fingerprint:
                    raise ValueError('同一配置操作不能用于不同令牌或扩展身份')
                if record.get('phase') == 'committed':
                    return copy.deepcopy(record['result'])
                settings = copy.deepcopy(record.get('configuration_snapshot'))
                if not isinstance(settings, dict):
                    raise VaultError('桥接配置恢复记录不完整')
                self._validate_settings(settings)
                if settings['extension_id'] != self._receipt().get('extension_id'):
                    raise VaultError('实际扩展身份已变化，请重新配对而非继续旧配置')
                current = pointer.get('secret_ref') if pointer else None
                if current not in (record.get('previous_ref'), record.get('secret_ref')):
                    raise ValueError('桥接已被后续操作更新，请先核对当前配置')
            else:
                token = value.get('WECHATSYNC_TOKEN')
                if token is None:
                    if pointer:
                        raise ValueError('已有桥接配置；如需更换，请明确输入新令牌')
                    token = os.environ.get('WECHATSYNC_TOKEN')
                settings = {'WECHATSYNC_TOKEN': token, 'bridge_url': BRIDGE_URL, 'extension_id': self._receipt().get('extension_id')}
                self._validate_settings(settings)
                record = {'kind': 'bridge-configure', 'operation_id': operation_id, 'input_fingerprint': input_fingerprint,
                          'configuration_snapshot': copy.deepcopy(settings),
                          'secret_ref': 'vault:' + uuid.uuid4().hex, 'previous_ref': pointer.get('secret_ref') if pointer else None,
                          'configured_at': stamp(), 'phase': 'reserved'}
                self.vault.write_proof(key, record)
            self.vault.put_reserved(BRIDGE_ID, settings, record['secret_ref'])
            self._write_bridge_pointer({'schema_version': 1, 'secret_ref': record['secret_ref'],
                                        'configured_at': record['configured_at'], 'operation_id': operation_id})
            self._discovery = None
            record.update(phase='committed', result=self.bridge_status())
            record.pop('configuration_snapshot', None)
            self.vault.write_proof(key, record)
            settings.clear()
            return copy.deepcopy(record['result'])

    def credentials_for_connection(self, connection_id):
        """Clone internally; a global owner handle can never become an account handle."""
        _identifier(connection_id)
        if connection_id == BRIDGE_ID:
            raise ValueError('账号连接需要独立身份')
        with _bridge_mutex(self.root):
            settings = self._global_settings()
            pointer = self._bridge_pointer()
            key = hashlib.sha256(('bridge-clone\0' + connection_id + '\0' + pointer['secret_ref']).encode()).hexdigest()
            record = self.vault.read_proof(key)
            if record is None:
                record = {'kind': 'bridge-clone', 'connection_id': connection_id, 'source_ref': pointer['secret_ref'],
                          'secret_ref': 'vault:' + uuid.uuid4().hex, 'phase': 'reserved'}
                self.vault.write_proof(key, record)
            if record.get('kind') != 'bridge-clone' or record.get('connection_id') != connection_id or record.get('source_ref') != pointer['secret_ref']:
                raise VaultError('账号凭据继承记录不一致')
            reference = self.vault.put_reserved(connection_id, settings, record['secret_ref'])
            record['phase'] = 'committed';self.vault.write_proof(key, record);settings.clear()
            return reference

    def discover_accounts(self):
        """Official read-only listPlatforms, never creates or upgrades a connection."""
        checked = stamp()
        status = self.bridge_status()
        if not status['configured'] or status['status'] == 'needs_pairing':
            return {'status': 'needs_pairing', 'accounts': [], 'checked_at': checked,
                    'message': '请先配对此电脑的同步桥接；浏览器观察不能代替服务器核验。'}
        try:
            reply = self._invoke('getPlatforms', None)
            if reply.get('ok') is not True or reply.get('code_verified') is not True or not isinstance(reply.get('accounts'), list):
                raise BridgeError('账号发现暂不可核对')
            accounts = []
            for row in reply['accounts'][:80]:
                if not isinstance(row, dict):
                    continue
                def public_string(key, limit):
                    raw = row.get(key, '')
                    return re.sub(r'[\x00-\x1f\x7f]', '', raw)[:limit] if isinstance(raw, str) else ''
                platform, name, account = public_string('platform', 80), public_string('name', 200), public_string('account', 200)
                if not platform or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', platform):
                    continue
                accounts.append({'platform': platform, 'name': name, 'account': account,
                                 'authenticated': row.get('authenticated') is True and bool(account.strip()), **identity_metadata(row)})
            result = {'status': 'discovered', 'accounts': accounts, 'checked_at': stamp(),
                      'message': '已只读列出本机扩展账号；选择账号后仍需逐项核验分发能力。'}
        except Exception:
            result = {'status': 'needs_pairing', 'accounts': [], 'checked_at': stamp(),
                      'message': '未能核对当前桥接或扩展身份，请在此电脑完成配对后重查。'}
        self._discovery = copy.deepcopy(result)
        return result

    def _installation_evidence(self):
        receipt = self._receipt()
        result = {'cli_source_verified': False, 'extension_archive_verified': False,
                  'extension_code_verified': False, 'node_available': False, 'installed': False}
        if not receipt:
            return result
        try:
            tool = pathlib.Path(receipt['tool_root']).resolve()
            extension = pathlib.Path(receipt['extension_path']).resolve()
            package = json.loads((tool / 'node_modules/@wechatsync/cli/package.json').read_text(encoding='utf-8'))
            if tool != self.tool_root or not extension.is_relative_to(tool) or not re.fullmatch(r'[a-p]{32}', receipt.get('extension_id', '')):
                return result
            result['node_available'] = (pathlib.Path(receipt['node_path']).resolve() == self.node_path
                                        and self.node_path.name.lower() == 'node.exe' and self.node_path.is_file())
            result['cli_source_verified'] = (package.get('name') == '@wechatsync/cli' and package.get('version') == CLI_VERSION
                and receipt.get('cli_version') == CLI_VERSION and receipt.get('cli_sha256') == CLI_SHA
                and hashlib.sha256((tool / 'node_modules/@wechatsync/cli/dist/index.js').read_bytes()).hexdigest() == CLI_SHA)
            result['extension_archive_verified'] = (receipt.get('extension_sha256') == EXTENSION_ARCHIVE_SHA
                and hashlib.sha256((tool / 'extension-2.0.9.zip').read_bytes()).hexdigest() == EXTENSION_ARCHIVE_SHA)
            result['extension_code_verified'] = (hashlib.sha256((extension / 'manifest.json').read_bytes()).hexdigest() == EXTENSION_MANIFEST_SHA
                and hashlib.sha256((extension / 'assets/index.ts-Bw-475TG.js').read_bytes()).hexdigest() == EXTENSION_BACKGROUND_SHA)
            result['installed'] = all(result[key] for key in ('cli_source_verified', 'extension_archive_verified', 'extension_code_verified'))
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return result

    def summary(self):
        receipt = self._receipt()
        installation = self._installation_evidence()
        installed = installation['installed']
        runners = []
        try:
            with self.box.store.connect() as connection:
                rows = connection.execute('SELECT document FROM distribution_runners').fetchall()
            now = dt.datetime.now(dt.timezone.utc)
            for row in rows:
                item = json.loads(row['document'])
                observed = dt.datetime.fromisoformat(item['last_seen_at'])
                if observed.tzinfo is None:
                    continue
                age = (now - observed.astimezone(dt.timezone.utc)).total_seconds()
                alive = bool(item.get('process_identity') and process_identity(item.get('process_id')) == item['process_identity'])
                runners.append({'id': item['id'], 'last_seen_at': item['last_seen_at'], 'at': observed,
                                'process_alive': alive, 'heartbeat_fresh': 0 <= age <= 15,
                                'running': alive and 0 <= age <= 15 and item.get('state') != 'stopped'})
        except Exception:
            runners = []
        latest = max(runners, key=lambda item: item['at']) if runners else None
        return {'status': 'ready_for_account_probe' if installed and installation['node_available'] and self.bridge_path.is_file() else 'not_configured',
                'connector': 'wechatsync', 'cli_version': CLI_VERSION if installed else None,
                **installation, 'bridge_available': self.bridge_path.is_file(),
                'extension_installed': installation['extension_code_verified'],
                'installed_at': receipt.get('installed_at') if isinstance(receipt.get('installed_at'), str) and re.fullmatch(r'[0-9TZ:+. -]{10,40}', receipt['installed_at']) else None,
                'cli_sha256': receipt.get('cli_sha256') if isinstance(receipt.get('cli_sha256'), str) and re.fullmatch(r'[a-f0-9]{64}', receipt['cli_sha256']) else None,
                'remote_readback': 'not_supported', 'automatic_publish': False,
                'running': any(item['running'] for item in runners),
                'heartbeat': {key: latest[key] for key in ('id', 'last_seen_at', 'process_alive', 'heartbeat_fresh', 'running')} if latest else None,
                'note': '安装、账号只读核验、草稿试运行分别记录；正式发布不受支持。'}

    def _binding(self, connection):
        value = {key: connection.get(key) for key in ('id', 'platform', 'account', 'revision', 'secret_ref')}
        try:
            value['bridge_sha256'] = hashlib.sha256(self.bridge_path.read_bytes()).hexdigest()
        except OSError:
            value['bridge_sha256'] = None
        return hashlib.sha256(_json(value)).hexdigest()

    def _validate_settings(self, settings):
        if (not isinstance(settings, dict) or settings.get('bridge_url') != BRIDGE_URL
                or not isinstance(settings.get('extension_id'), str) or not re.fullmatch(r'[a-p]{32}', settings['extension_id'])):
            raise VaultError('本机桥接配置无效')
        token = settings.get('WECHATSYNC_TOKEN')
        if not isinstance(token, str) or not 16 <= len(token) <= 4096 or re.search(r'[\x00-\x20\x7f]', token):
            raise VaultError('本机桥接配置无效')
        return settings

    def _settings(self, connection):
        settings = self.vault.get(connection.get('secret_ref'), connection.get('id'))
        self._validate_settings(settings)
        return settings

    def _invoke(self, op, connection, **fields):
        settings = self._settings(connection) if connection is not None else self._global_settings()
        payload = {'protocol_version': 1, 'op': op, 'tool_root': str(self.tool_root),
                   'settings': settings, **fields}
        if connection is not None:
            payload['connection'] = {key: connection.get(key) for key in ('id', 'platform', 'account')}
        try:
            if self._bridge is not None:
                reply = self._bridge(copy.deepcopy(payload))
            else:
                receipt = self._receipt()
                installation = self._installation_evidence()
                if (not installation['installed'] or not installation['node_available'] or receipt.get('cli_version') != CLI_VERSION
                        or pathlib.Path(receipt.get('node_path', '')).resolve() != self.node_path
                        or pathlib.Path(receipt.get('tool_root', '')).resolve() != self.tool_root
                        or receipt.get('extension_id') != settings['extension_id']):
                    raise BridgeError('本机安装证据尚未核对')
                try:
                    cli_source = self.tool_root / 'node_modules/@wechatsync/cli/dist/index.js'
                    if hashlib.sha256(cli_source.read_bytes()).hexdigest() != receipt.get('cli_sha256'):
                        raise BridgeError('本机工具字节与安装记录不一致')
                except OSError:
                    raise BridgeError('本机草稿桥接尚未安装') from None
                if self.node_path.name.lower() != 'node.exe' or not self.node_path.is_file() or not self.bridge_path.is_file():
                    raise BridgeError('本机草稿桥接尚未安装')
                environment = {key: value for key, value in os.environ.items() if key.upper() in {'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'USERPROFILE', 'LOCALAPPDATA', 'APPDATA', 'PATH'}}
                try:
                    process = subprocess.run([str(self.node_path), str(self.bridge_path)], input=_json(payload) + b'\n',
                                             capture_output=True, timeout=self.timeout, env=environment, shell=False,
                                             creationflags=0x08000000 if os.name == 'nt' else 0)
                except subprocess.TimeoutExpired:
                    raise BridgeTimeout('本机桥接等待超时；发送后的结果须人工核验') from None
                except OSError:
                    raise BridgeError('本机桥接无法启动') from None
                if process.returncode != 0 or len(process.stdout) > 512 * 1024:
                    raise BridgeError('本机桥接返回无效结果')
                try:
                    reply = json.loads(process.stdout)
                except (ValueError, UnicodeError):
                    raise BridgeError('本机桥接返回无效结果') from None
            if not isinstance(reply, dict) or reply.get('protocol_version') != 1 or len(_json(reply)) > 512 * 1024:
                raise BridgeError('本机桥接协议不匹配')
            # No raw child stdout/stderr/error is ever surfaced. Reject even a
            # faulty adapter's credential echo before interpreting its fields.
            if settings['WECHATSYNC_TOKEN'] in _json(reply).decode('utf-8'):
                raise BridgeError('本机桥接结果未通过隐私检查')
            return reply
        except (VaultError, BridgeError):
            raise
        except Exception:
            raise BridgeError('本机草稿桥接暂不可核对') from None
        finally:
            settings.clear()
            payload.clear()

    def probe(self, connection):
        account = connection.get('account', '')
        base = {'status': 'unknown', 'account': account, 'code_verified': False, 'account_verified': False,
                'capabilities': {'draft': False, 'publish': False, 'verify': False}, 'checked_at': stamp(),
                'reason': '本机桥接或账号尚未完成实际核验', 'evidence': []}
        try:
            reply = self._invoke('probe', connection)
            exact = reply.get('ok') is True and reply.get('account_verified') is True and reply.get('account') == account
            base.update(code_verified=reply.get('code_verified') is True, account_verified=exact)
            draft = bool(exact and base['code_verified'] and connection.get('platform') in SUPPORTED_DRAFTS and isinstance(reply.get('capabilities'), dict) and reply['capabilities'].get('draft') is True)
            base['capabilities']['draft'] = draft
            base['status'] = 'trial' if draft else 'unsupported' if connection.get('platform') not in SUPPORTED_DRAFTS else 'unknown'
            base['reason'] = '账号已精确核对；仅支持明确批准的草稿试运行，远端内容核验未接入' if draft else '该内容类型不受官方草稿连接器支持' if base['status'] == 'unsupported' else '未读回与此连接完全一致的已登录账号'
            base['evidence'] = [{'kind': 'official_bridge_account_probe', 'connector': 'wechatsync', 'version': CLI_VERSION,
                                 'account': account, 'matched': exact, 'code_verified': base['code_verified'], 'at': base['checked_at']}]
        except Exception:
            pass
        try:
            self.vault.write_proof(self._binding(connection), base)
        except Exception:
            base.update(status='unknown', code_verified=False, account_verified=False,
                        capabilities={'draft': False, 'publish': False, 'verify': False}, evidence=[],
                        reason='本机核验结果无法安全保存，请检查此Windows账号的凭据库')
        return copy.deepcopy(base)

    def capability(self, connection, action):
        result = {'status': 'unknown', 'verified': False, 'code_verified': False, 'account_verified': False,
                  'account': connection.get('account', ''), 'reason': '请先只读核对本机连接与当前账号'}
        if not connection.get('enabled', True) or action not in ('draft', 'publish', 'verify'):
            return {**result, 'status': 'unsupported', 'reason': '连接或动作不可用'}
        if action == 'publish':
            return {**result, 'status': 'unsupported', 'reason': '官方草稿桥接未提供正式发布能力'}
        if action == 'verify':
            return {**result, 'status': 'unsupported', 'reason': '官方连接器没有独立远端内容读回接口'}
        if connection.get('platform') not in SUPPORTED_DRAFTS:
            return {**result, 'status': 'unsupported', 'reason': '该内容类型不受官方草稿连接器支持'}
        proof = self.vault.read_proof(self._binding(connection))
        if not proof:
            return result
        try:
            checked = dt.datetime.fromisoformat(proof['checked_at'])
            age = (dt.datetime.now(dt.timezone.utc) - checked.astimezone(dt.timezone.utc)).total_seconds()
            if not 0 <= age <= self.cache_seconds or proof.get('account') != connection.get('account'):
                return result
        except (KeyError, ValueError, TypeError):
            return result
        if proof.get('code_verified') is True and proof.get('account_verified') is True and proof.get('capabilities', {}).get('draft') is True:
            result.update(status='trial', code_verified=True, account_verified=True, reason=proof['reason'], evidence=proof.get('evidence', []))
        return result

    def _remote(self, reply, revision, connection):
        from easel_workbench.runtime.distribution_service import safe_url
        result = {'remote_state': 'unknown', 'verified': False, 'account': connection['account'],
                  'error': '官方连接器尚无独立内容读回；写入响应不等于已核验草稿或已发布',
                  'evidence': [{'kind': 'unverified_connector_receipt', 'connector': 'wechatsync', 'readback': False}]}
        remote_id = reply.get('remote_id')
        if isinstance(remote_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,256}', remote_id):
            result['remote_id'] = remote_id
        if safe_url(reply.get('safe_url')):
            result['safe_url'] = reply['safe_url']
        # Current official wrapper intentionally never supplies this. If an
        # independently implemented readback is later added, exact content and
        # asset hashes must be present; echoed revision_hash alone is ignored.
        readback = reply.get('readback')
        expected_assets = [item['sha256'] for item in revision.get('asset_manifest', [])]
        if not isinstance(readback, dict) or reply.get('verified') is not True:
            return result
        matched = (readback.get('account') == revision['account'] == connection['account']
                   and readback.get('title') == revision['title'] and readback.get('body') == revision['body']
                   and readback.get('asset_sha256s') == expected_assets and readback.get('remote_id') == result.get('remote_id')
                   and readback.get('remote_state') in ('draft', 'pending_review', 'published') and safe_url(result.get('safe_url')))
        if not matched:
            return result
        try:
            observed = dt.datetime.fromisoformat(readback['observed_at'].replace('Z', '+00:00'))
            if observed.tzinfo is None or not -5 <= (dt.datetime.now(dt.timezone.utc)-observed.astimezone(dt.timezone.utc)).total_seconds() <= 120:
                return result
        except (KeyError, ValueError, TypeError, AttributeError):
            return result
        result.update(remote_state=readback['remote_state'], verified=True, revision_hash=revision['hash'],
                      evidence=[{'kind': 'remote_content_readback', 'account_confirmed': True, 'content_confirmed': True,
                                 'asset_count': len(expected_assets), 'observed_at': readback['observed_at']}])
        result.pop('error', None)
        if result['remote_state'] == 'published':
            published = readback.get('published_at')
            try:
                parsed = dt.datetime.fromisoformat(published.replace('Z', '+00:00'))
                if parsed.tzinfo is None:
                    return {**result, 'verified': False, 'remote_state': 'unknown', 'error': '远端发布时间未核实'}
            except (ValueError, TypeError, AttributeError):
                return {**result, 'verified': False, 'remote_state': 'unknown', 'error': '远端发布时间未核实'}
            result['published_at'] = published
        return result

    def verify(self, delivery, revision, connection, hints):
        from easel_workbench.runtime.distribution_service import safe_url
        if (not isinstance(hints, dict) or set(hints)-{'remote_id', 'safe_url'}
                or 'safe_url' in hints and not safe_url(hints['safe_url'])
                or 'remote_id' in hints and (not isinstance(hints['remote_id'], str) or not 1 <= len(hints['remote_id']) <= 1000 or any(ord(char)<32 for char in hints['remote_id']))):
            return {'remote_state': 'unknown', 'verified': False, 'error': '远端核验线索无效或含不安全链接'}
        if any((delivery.get(key) != revision.get(key)) for key in ('account', 'platform', 'connection_id')) or connection.get('id') != revision.get('connection_id') or connection.get('account') != revision.get('account'):
            return {'remote_state': 'unknown', 'verified': False, 'error': '账号或稿件身份不一致，未执行远端核验'}
        try:
            reply = self._invoke('reconcile', connection, delivery=delivery, revision=revision, hints=hints)
            return self._remote(reply, revision, connection)
        except Exception:
            return {'remote_state': 'unknown', 'verified': False, 'error': '本机远端核验不可用，保留原任务与未知结果'}

    def send(self, claim, assets):
        delivery, revision, connection = claim['delivery'], claim['revision'], claim['connection']
        if delivery.get('action') != 'draft' or delivery.get('pilot') is not True or connection.get('platform') not in SUPPORTED_DRAFTS:
            raise BridgeError('此连接只支持明确批准的草稿试运行')
        if (delivery.get('connection_id') != connection.get('id') or revision.get('connection_id') != connection.get('id')
                or delivery.get('account') != connection.get('account') or revision.get('account') != connection.get('account')
                or delivery.get('platform') != connection.get('platform') or revision.get('platform') != connection.get('platform')):
            raise BridgeError('发送账号与已批准稿件不一致')
        try:
            with self.box.store.connect() as sql:
                row = sql.execute('SELECT document FROM distribution_attempts WHERE id=?', (claim['attempt']['id'],)).fetchone()
                attempt = json.loads(row['document']) if row else {}
            if (attempt.get('delivery_id') != delivery.get('id') or not attempt.get('dispatched_at')
                    or attempt.get('status') != 'leased' or attempt.get('lease_token') != claim.get('lease_token')):
                raise BridgeError('未找到此任务持久化的发送边界，未调用平台')
        except BridgeError:
            raise
        except Exception:
            raise BridgeError('发送边界暂不可核对，未调用平台') from None
        manifest = revision.get('asset_manifest', [])
        if not isinstance(assets, list) or len(assets) != len(manifest):
            raise BridgeError('发送图片与批准快照不一致')
        for actual, expected in zip(assets, manifest):
            if any(actual.get(key) != expected.get(key) for key in ('id', 'name', 'mime', 'sha256', 'size')):
                raise BridgeError('发送图片与批准快照不一致')
            _, frozen = self.box.file(expected['id'])
            if pathlib.Path(actual.get('path', '')).resolve() != frozen.resolve() or not frozen.resolve().is_relative_to(self.root / 'data/toolbox/files'):
                raise BridgeError('发送图片路径不属于批准快照')
        reply = self._invoke('sync', connection, delivery=delivery, revision=revision, assets=assets)
        return self._remote(reply, revision, connection)
