"""Private, nonce-bound liveness; it grants no business or session authority."""
from pathlib import Path
import os
import re
import secrets

HEALTH_PATH = '/_workbench/health'


def health_token(root, *, create=False):
    path = Path(root) / '.local/workbench-deployment/health-token'
    if not create and not path.exists():
        raise FileNotFoundError(path)
    from .runtime.feedback_ledger import locked
    with locked(path.with_name('health-token.lock'), timeout=5):
        return _read_or_create_token(path, create)


def _read_or_create_token(path, create):
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor, 'w', encoding='ascii') as stream:
                stream.write(secrets.token_hex(32));stream.flush();os.fsync(stream.fileno())
    value = path.read_text(encoding='ascii').strip()
    if not re.fullmatch('[a-f0-9]{64}', value):
        raise ValueError('Invalid private health token')
    return value


def install_health(app, root):
    from fastapi.responses import JSONResponse
    token = health_token(root, create=True)

    @app.middleware('http')
    async def health(request, call_next):
        if request.url.path != HEALTH_PATH:
            return await call_next(request)
        nonce = request.headers.get('x-workbench-health-nonce', '')
        supplied = request.headers.get('x-workbench-health-token', '')
        valid = (request.method == 'GET'
                 and len(request.headers.getlist('x-workbench-health-token')) == 1
                 and len(request.headers.getlist('x-workbench-health-nonce')) == 1
                 and re.fullmatch('[a-f0-9]{64}', supplied)
                 and secrets.compare_digest(supplied, token)
                 and re.fullmatch('[a-f0-9]{32}', nonce))
        if not valid:
            return JSONResponse({'error': 'not_found'}, status_code=404,
                                headers={'Cache-Control': 'no-store'})
        return JSONResponse({'ok': True, 'nonce': nonce, 'pid': os.getpid(),
                             'release': os.environ.get('AI_DESK_RELEASE', 'development')},
                            headers={'Cache-Control': 'no-store', 'X-Workbench-Health': '1'})
