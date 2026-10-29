"""Small, media-independent primitives for platform connections."""
import hashlib
import os

from easel_workbench.runtime.toolbox_store import pack


class ConnectionConflict(ValueError):
    pass


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else pack(value).encode()).hexdigest()


def safe_env(values, directory):
    allowed = {'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'LOCALAPPDATA', 'APPDATA',
               'PROGRAMFILES', 'PROGRAMFILES(X86)', 'SSL_CERT_FILE', 'SSL_CERT_DIR',
               'HTTPS_PROXY', 'HTTP_PROXY', 'NO_PROXY'}
    env = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    env.update({k: str(v) for k, v in values.items()})
    env.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8', EASEL_ROOT=str(directory),
               HOME=str(directory), USERPROFILE=str(directory), EASEL_CONFIG_DIR=str(directory))
    return env
