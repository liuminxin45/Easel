"""Authenticated artifact byte ranges; files never leave their captured root."""
import hashlib
import re
import pathlib
import urllib.parse


def disposition(name, mode):
    """ASCII fallback for native savers, alongside the original UTF-8 name."""
    name = pathlib.PureWindowsPath(name).name
    suffix = pathlib.PureWindowsPath(name).suffix
    suffix = suffix if re.fullmatch(r'\.[A-Za-z0-9]{1,16}', suffix) else ''
    stem = name[:-len(suffix)] if suffix else name
    stem = re.sub(r'[^A-Za-z0-9._-]+', '_', stem).strip('._-') or 'download'
    return mode + '; filename="' + stem + suffix + '"; filename*=UTF-8\'\'' + urllib.parse.quote(name, safe='')


def descriptor(path, identity, range_header=None, if_range=None):
    stat = path.stat(); total = stat.st_size
    etag = '"' + hashlib.sha256(f'{identity}:{total}:{stat.st_mtime_ns}'.encode()).hexdigest() + '"'
    headers = {'Accept-Ranges': 'bytes', 'ETag': etag}
    start, end, code = 0, total - 1, 200
    if range_header and (not if_range or if_range == etag):
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', range_header) if len(range_header) <= 100 else None
        if not match or not any(match.groups()) or not total:
            return 416, 0, 0, headers | {'Content-Range': f'bytes */{total}'}
        first, last = match.groups()
        if first:
            start = int(first); end = min(int(last), end) if last else end
        else:
            count = int(last); start = max(0, total - count)
            if not count: start = total
        if start >= total or end < start:
            return 416, 0, 0, headers | {'Content-Range': f'bytes */{total}'}
        code = 206
        headers['Content-Range'] = f'bytes {start}-{end}/{total}'
    return code,start,max(0,end-start+1),headers


def response(path, identity, range_header=None, if_range=None):
    code,start,length,headers=descriptor(path,identity,range_header,if_range)
    with path.open('rb') as f:
        f.seek(start); body = f.read(length)
    if len(body) != length:
        raise OSError('captured artifact changed while reading')
    return code, body, headers
