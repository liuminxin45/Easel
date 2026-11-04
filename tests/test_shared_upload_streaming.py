"""Bounded original upload core, no network or models."""
import asyncio
import io
import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile
from starlette.requests import Request
from easel.web_services.uploads import stream_upload, parse_upload_form, DEFAULT_MAX_BYTES, upload_limits

def run(coro): return asyncio.run(coro)

def test_stream_cap_cleanup_and_existing_target_preserved(tmp_path):
    target=tmp_path/'file'
    with pytest.raises(HTTPException) as exc:
        run(stream_upload(UploadFile(io.BytesIO(b'abcdef'),filename='x.txt'),target,max_bytes=5))
    assert exc.value.status_code==413 and not target.exists()
    target.write_bytes(b'owned')
    with pytest.raises(FileExistsError):
        run(stream_upload(UploadFile(io.BytesIO(b'new'),filename='x.txt'),target))
    assert target.read_bytes()==b'owned'

def test_original_empty_and_private_nonempty_contract(tmp_path):
    assert run(stream_upload(UploadFile(io.BytesIO(b'')),tmp_path/'empty'))['size']==0
    with pytest.raises(HTTPException):
        run(stream_upload(UploadFile(io.BytesIO(b'')),tmp_path/'private',allow_empty=False))
    assert not (tmp_path/'private').exists()

def multipart_request(size, chunk=8192):
    header=b'--test\r\nContent-Disposition: form-data; name="sessionId"\r\n\r\nsession\r\n--test\r\nContent-Disposition: form-data; name="files"; filename="file.txt"\r\n\r\n'
    raw=header+b'x'*size+b'\r\n--test--\r\n'
    position=0
    async def receive():
        nonlocal position
        part=raw[position:position+chunk];position+=len(part)
        return {'type':'http.request','body':part,'more_body':position<len(raw)}
    req=Request({'type':'http','method':'POST','path':'/','headers':[(b'content-type',b'multipart/form-data; boundary=test')]},receive)
    async def no_body(): raise AssertionError('whole-body buffering forbidden')
    req.body=no_body
    return req

def test_multipart_allowance_does_not_reject_exact_file_cap():
    async def scenario():
        form=await parse_upload_form(multipart_request(5000),max_bytes=5000)
        try: assert form['files'].size==5000
        finally: await form.close()
    run(scenario())
    assert upload_limits()['max_mb']==50 and DEFAULT_MAX_BYTES==50*1024**2

def test_oversized_chunked_request_closes_parser_spools(monkeypatch):
    import easel.web_services.uploads as uploads
    spools=[]
    original=uploads.MultiPartParser
    class Recording(original):
        def on_headers_finished(self):
            super().on_headers_finished()
            if self._current_part.file: spools.append(self._current_part.file.file)
    monkeypatch.setattr(uploads,'MultiPartParser',Recording)
    with pytest.raises(HTTPException) as exc: run(parse_upload_form(multipart_request(2*1024**2),max_bytes=1))
    assert exc.value.status_code==413 and spools and all(f.closed for f in spools)

def test_cancelled_read_removes_partial(tmp_path):
    class Interrupted:
        filename='x.txt'
        count=0
        async def read(self, size):
            assert size==1024**2
            self.count+=1
            if self.count==1:return b'prefix'
            raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):run(stream_upload(Interrupted(),tmp_path/'partial'))
    assert not (tmp_path/'partial').exists()


def test_real_fifty_mb_file_plus_multipart_headers_is_accepted(tmp_path):
    async def scenario():
        header=b'--test\r\nContent-Disposition: form-data; name="sessionId"\r\n\r\nsession\r\n--test\r\nContent-Disposition: form-data; name="files"; filename="limit.txt"\r\n\r\n'
        async def chunks():
            yield header
            for _ in range(50): yield b'x'*1024**2
            yield b'\r\n--test--\r\n'
        iterator=chunks().__aiter__()
        async def receive():
            try:return {'type':'http.request','body':await anext(iterator),'more_body':True}
            except StopAsyncIteration:return {'type':'http.request','body':b'','more_body':False}
        request=Request({'type':'http','method':'POST','path':'/','headers':[(b'content-type',b'multipart/form-data; boundary=test')]},receive)
        form=await parse_upload_form(request)
        try:
            assert form['files'].size==DEFAULT_MAX_BYTES
            result=await stream_upload(form['files'],tmp_path/'limit')
            assert result['size']==DEFAULT_MAX_BYTES
        finally:await form.close()
    run(scenario())


def test_raw_request_uses_same_writer_and_rejects_length_before_read(tmp_path):
    from easel.web_services.uploads import stream_request_upload
    async def scenario():
        reads=[]
        async def receive():
            reads.append(True)
            return {'type':'http.request','body':b'abcdef','more_body':False}
        scope={'type':'http','method':'POST','path':'/','headers':[]}
        request=Request(scope,receive)
        result=await stream_request_upload(request,tmp_path/'raw','x.txt',max_bytes=6)
        assert result['size']==6 and (tmp_path/'raw').read_bytes()==b'abcdef'
        for headers in ([(b'content-length',b'7')],[(b'content-length',b'-1')],[(b'content-length',b'1'),(b'content-length',b'1')]):
            before=len(reads)
            with pytest.raises(HTTPException):await stream_request_upload(Request({**scope,'headers':headers},receive),tmp_path/'reject','x.txt',max_bytes=6)
            assert len(reads)==before and not (tmp_path/'reject').exists()
        with pytest.raises(HTTPException):await stream_request_upload(Request(scope,receive),tmp_path/'too-big','x.txt',max_bytes=5)
        assert not (tmp_path/'too-big').exists()
    run(scenario())
