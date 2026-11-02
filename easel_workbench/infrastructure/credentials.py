"""Original Windows DPAPI vault format and ACLs, independent of publisher drivers."""
import copy,ctypes,json,os,pathlib,re,threading,uuid
from ctypes import wintypes
ENTROPY = b'ai-news-desk/distribution-secrets/v1'


_HANDLE = re.compile(r'vault:([a-f0-9]{32})\Z')


class VaultError(RuntimeError):
    """A deliberately non-diagnostic message: never include plaintext/blob data."""


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value):
        raise ValueError('连接标识无效')
    return value


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
