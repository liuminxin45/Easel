"""Private, nonce-bound liveness; it grants no business or session authority."""
from pathlib import Path
import os
import re
import secrets

HEALTH_PATH = '/_workbench/health'
DIAGNOSTIC_PATH = '/_workbench/diagnostics'


def health_token(root, *, create=False):
    path = Path(root) / '.local/workbench-deployment/health-token'
    if not create and not path.exists():
        raise FileNotFoundError(path)
    from .runtime.feedback_ledger import locked
    with locked(path.with_name('health-token.lock'), timeout=5):
        return _read_or_create_token(path, create)


def _read_or_create_token(path, create):
    if create:
        from .runtime.feedback_ledger import atomic_create
        if not path.exists():
            atomic_create(path, secrets.token_hex(32))
    value = path.read_text(encoding='ascii').strip()
    if not re.fullmatch('[a-f0-9]{64}', value):
        raise ValueError('Invalid private health token')
    return value


def install_health(app, root):
    from fastapi.responses import JSONResponse
    try:
        token = health_token(root, create=True)
    except (ValueError, OSError):
        # A broken monitoring credential must not prevent the workbench from
        # serving its existing authenticated business routes.
        token = None

    @app.middleware('http')
    async def health(request, call_next):
        if request.url.path not in (HEALTH_PATH, DIAGNOSTIC_PATH):
            return await call_next(request)
        nonce = request.headers.get('x-workbench-health-nonce', '')
        supplied = request.headers.get('x-workbench-health-token', '')
        valid = (token is not None and request.method == 'GET'
                 and len(request.headers.getlist('x-workbench-health-token')) == 1
                 and len(request.headers.getlist('x-workbench-health-nonce')) == 1
                 and re.fullmatch('[a-f0-9]{64}', supplied)
                 and secrets.compare_digest(supplied, token)
                 and re.fullmatch('[a-f0-9]{32}', nonce))
        if not valid:
            return JSONResponse({'error': 'not_found'}, status_code=404,
                                headers={'Cache-Control': 'no-store'})
        value = {'ok': True, 'nonce': nonce, 'pid': os.getpid(),
                 'release': os.environ.get('AI_DESK_RELEASE', 'development')}
        if request.url.path == DIAGNOSTIC_PATH:
            # Separate from bounded liveness: diagnostics never grants a session,
            # returns business content or blocks the event loop on SQLite.
            import asyncio
            from .business_health import snapshot as business_snapshot
            from .diagnostics.performance import snapshot as performance_snapshot
            try:
                value['business'] = await asyncio.wait_for(asyncio.to_thread(business_snapshot, root), timeout=2)
            except (OSError, ValueError, TimeoutError):
                value['business'] = {'status': 'unavailable', 'ok': None}
            value['performance'] = performance_snapshot()
        return JSONResponse(value,
                            headers={'Cache-Control': 'no-store', 'X-Workbench-Health': '1'})
