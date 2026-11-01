"""Download HTTP adapters over the host's existing authorized file reader.

The host retains authentication, admission and the actual file handlers. These
adapters only parse requests, delegate a read/probe, and set download headers.
"""
import json
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import quote, unquote, urlsplit

from starlette.requests import Request
from starlette.responses import FileResponse, Response

from easel_workbench.runtime import download_delivery
from easel_workbench.runtime.artifact_delivery import disposition
from easel_workbench.runtime.auth_totp import equal
from .response_lifecycle import close_read_response

ReadTarget = Callable[[Request, dict], Awaitable[Response]]


def download_request(request, target, *, head=False):
    """Delegate only a prevalidated local read to the existing file handler."""
    wanted = urlsplit(target)
    path = unquote(wanted.path)
    scope = {**request.scope, 'path': path, 'raw_path': quote(path, safe='/').encode('ascii'),
             'query_string': wanted.query.encode('ascii')}
    if head:
        scope['method'] = 'HEAD'
        scope['headers'] = [(key, value) for key, value in scope['headers']
                            if key.lower() not in (b'content-length', b'transfer-encoding')]
    return Request(scope)


async def serve_download(request, *, auth, read_target: ReadTarget, error):
    if request.method not in ('GET', 'HEAD'):
        return error(405, 'method rejected')
    granted = download_delivery.authorize(auth, request.query_params)
    if not granted:
        return error(403, '下载链接无效或已过期，请重新点击下载')
    delegated = download_request(request, request.query_params['target'])
    result = await read_target(delegated, granted)
    if result.status_code >= 400:
        return result
    if isinstance(result, FileResponse) and result.stat_result is None:
        result.stat_result = result.path.stat() if hasattr(result.path, 'stat') else Path(result.path).stat()
        result.set_stat_headers(result.stat_result)
    result.headers['Content-Disposition'] = disposition(request.query_params['name'], 'attachment')
    result.headers['Cache-Control'] = 'no-store'
    result.headers['Content-Security-Policy'] = "default-src 'none'; sandbox allow-downloads"
    return result


async def issue_download(request, raw, *, session, token, same_origin, csrf,
                         read_target: ReadTarget, error, reply):
    if request.method != 'POST':
        return error(405, 'method rejected')
    headers = request.headers
    if not same_origin or len(headers.getlist('x-csrf-token')) != 1 or not equal(headers.get('x-csrf-token', ''), csrf):
        return error(403, 'csrf_rejected')
    try:
        fields = json.loads(raw)
        if not isinstance(fields, dict):
            raise ValueError('下载请求需要 JSON 对象')
        wanted = download_delivery.target(fields.get('target', ''))
        checked = await read_target(download_request(request, wanted, head=True), session)
        if checked.status_code not in (200, 206):
            return checked
        await close_read_response(checked)
        link = download_delivery.issue(session, token, wanted, fields.get('name', ''))
        return reply({'url': link})
    except ValueError as exc:
        return error(400, str(exc))
