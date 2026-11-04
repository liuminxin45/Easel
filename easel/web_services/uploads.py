"""Shared bounded attachment streaming for the original and authenticated hosts."""
from __future__ import annotations
import hashlib
from pathlib import Path
from fastapi import HTTPException
from starlette.formparsers import MultiPartParser, MultiPartException
from easel.web_services.outputs import IMAGE_EXTS, VIDEO_EXTS

MAX_UPLOAD_MB = 50
DEFAULT_MAX_BYTES = MAX_UPLOAD_MB * 1024 * 1024
CHUNK_BYTES = 1024 * 1024
UPLOAD_EXTS = IMAGE_EXTS | VIDEO_EXTS | {
    ".pdf", ".txt", ".md", ".markdown", ".csv", ".json", ".srt", ".vtt",
    ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".mp3", ".wav", ".m4a"}

def upload_limits():
    return {"ok": True, "max_mb": MAX_UPLOAD_MB}

async def stream_upload(upload, target, *, max_bytes=DEFAULT_MAX_BYTES, allow_empty=True):
    """Write bounded chunks; every exception, including cancellation, removes partial bytes."""
    target = Path(target)
    size = 0
    digest = hashlib.sha256()
    created = False
    try:
        with target.open('xb') as output:
            created = True
            while chunk := await upload.read(CHUNK_BYTES):
                size += len(chunk)
                if max_bytes is not None and size > max_bytes:
                    raise HTTPException(413, f'{upload.filename or "file"} 超过 {max_bytes // 1024**2}MB 上限')
                output.write(chunk)
                digest.update(chunk)
        if not size and not allow_empty:
            raise HTTPException(400, '文件不能为空')
        return {'size': size, 'sha256': digest.hexdigest()}
    except BaseException:
        if created: target.unlink(missing_ok=True)
        raise

async def parse_upload_form(request, *, max_files=16, max_bytes=DEFAULT_MAX_BYTES):
    """Limit incoming bytes before multipart spooling; never buffer the whole request."""
    content_type = request.headers.get('content-type', '')
    if not content_type.lower().startswith('multipart/form-data;') or any(c in content_type for c in '\r\n\x00'):
        raise HTTPException(415, '附件需要 multipart/form-data')
    # Multipart headers/field bytes do not consume the advertised file allowance.
    request_cap = max_bytes + 1024 * 1024
    length = request.headers.get('content-length')
    if length:
        try:
            if int(length) > request_cap: raise HTTPException(413, '附件请求超过允许大小')
        except ValueError: raise HTTPException(400, '附件请求长度无效') from None
    async def bounded():
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > request_cap: raise HTTPException(413, '附件请求超过允许大小')
            yield chunk
    parser = MultiPartParser(request.headers, bounded(), max_files=max_files, max_fields=1, max_part_size=4096)
    try:
        return await parser.parse()
    except BaseException as exc:
        for file in parser._files_to_close_on_error: file.close()
        if isinstance(exc, MultiPartException): raise HTTPException(400, str(exc)) from exc
        raise


async def stream_request_upload(request, target, filename, *, max_bytes=DEFAULT_MAX_BYTES, allow_empty=False):
    """Legacy opaque upload transport, using the same bounded writer as multipart."""
    import asyncio
    lengths = request.headers.getlist('content-length')
    if len(lengths) > 1: raise HTTPException(400, '重复请求长度')
    if lengths:
        try: size = int(lengths[0])
        except ValueError: raise HTTPException(400, '请求长度无效') from None
        if size < 0: raise HTTPException(400, '请求长度无效')
        if max_bytes is not None and size > max_bytes: raise HTTPException(413, '附件超过允许大小')
    class BodyReader:
        def __init__(self):
            self.filename = filename
            self.iterator = request.stream().__aiter__()
            self.pending = memoryview(b'')
            self.ended = False
        async def read(self, size):
            while not self.pending and not self.ended:
                try: self.pending = memoryview(await anext(self.iterator))
                except StopAsyncIteration: self.ended = True
            result = self.pending[:size].tobytes()
            self.pending = self.pending[size:]
            return result
    async with asyncio.timeout(25):
        return await stream_upload(BodyReader(), target, max_bytes=max_bytes, allow_empty=allow_empty)
