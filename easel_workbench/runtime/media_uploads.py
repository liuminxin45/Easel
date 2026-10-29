"""Idempotent bounded chunks for large user media; no business response cache."""
import hashlib
import json
import mimetypes
import os
import pathlib
import uuid

from easel_workbench.runtime.toolbox_store import ident, pack

CHUNK = 5 * 1024 * 1024
LIMIT = 512 * 1024 * 1024


def initialize(c):
    c.executescript('CREATE TABLE IF NOT EXISTS media_uploads(id TEXT PRIMARY KEY,name TEXT NOT NULL,size INTEGER NOT NULL,count INTEGER NOT NULL);CREATE TABLE IF NOT EXISTS media_upload_chunks(upload_id TEXT NOT NULL,number INTEGER NOT NULL,sha256 TEXT NOT NULL,size INTEGER NOT NULL,PRIMARY KEY(upload_id,number));')


def chunk(box, uid, number, name, size, count, raw):
    ident(uid)
    if not isinstance(name, str) or not 1 <= len(name) <= 240 or pathlib.PureWindowsPath(name).name != name or name in ('.', '..') or ':' in name or any(ord(c) < 32 for c in name):
        raise ValueError('媒体文件名无效')
    if type(size) is not int or not 0 < size <= LIMIT or type(count) is not int or count != (size + CHUNK - 1) // CHUNK or type(number) is not int or not 0 <= number < count:
        raise ValueError('媒体分段信息无效')
    expected = min(CHUNK, size - number * CHUNK)
    if len(raw) != expected:
        raise ValueError('媒体分段长度不符')
    sha = hashlib.sha256(raw).hexdigest()
    base = pathlib.Path(box.root).resolve()
    directory = base / 'data/media-uploads' / uid
    directory.mkdir(parents=True, exist_ok=True)
    if not directory.resolve().is_relative_to(base) or directory.is_symlink():
        raise ValueError('媒体上传目录无效')
    target = directory / str(number)
    with box.store.connect() as c:
        initialize(c)
        c.execute('BEGIN IMMEDIATE')
        old = c.execute('SELECT * FROM media_uploads WHERE id=?', (uid,)).fetchone()
        if old and (old['name'], old['size'], old['count']) != (name, size, count):
            raise ValueError('同一媒体上传不能更换文件')
        c.execute('INSERT OR IGNORE INTO media_uploads VALUES(?,?,?,?)', (uid, name, size, count))
        previous = c.execute('SELECT * FROM media_upload_chunks WHERE upload_id=? AND number=?', (uid, number)).fetchone()
        if previous and previous['sha256'] != sha:
            raise ValueError('同一媒体分段不能更换内容')
        if target.exists() and (target.is_symlink() or hashlib.sha256(target.read_bytes()).hexdigest() != sha):
            raise ValueError('媒体分段字节冲突')
        if not target.exists():
            temp = target.with_name(target.name + '.' + uuid.uuid4().hex + '.tmp')
            with temp.open('xb') as out:
                out.write(raw)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temp, target)
        c.execute('INSERT OR IGNORE INTO media_upload_chunks VALUES(?,?,?,?)', (uid, number, sha, len(raw)))
    return {'id': uid, 'number': number, 'sha256': sha, 'size': len(raw)}


def complete(box, value):
    uid = ident(value.get('upload_id'))
    with box.store.connect() as c:
        initialize(c)
        c.execute('BEGIN IMMEDIATE')
        old = c.execute('SELECT id,name,mime,size,sha256 FROM toolbox_files WHERE id=?', (uid,)).fetchone()
        if old:
            return dict(old)
        upload = c.execute('SELECT * FROM media_uploads WHERE id=?', (uid,)).fetchone()
        if not upload:
            raise ValueError('媒体上传不存在')
        chunks = list(c.execute('SELECT * FROM media_upload_chunks WHERE upload_id=? ORDER BY number', (uid,)))
        if len(chunks) != upload['count'] or sum(ch['size'] for ch in chunks) != upload['size']:
            raise ValueError('媒体分段尚未完整上传')
        directory = pathlib.Path(box.root) / 'data/toolbox/files' / uid
        directory.mkdir(parents=True, exist_ok=True)
        if not directory.resolve().is_relative_to(pathlib.Path(box.root).resolve()) or directory.is_symlink():
            raise ValueError('媒体存储目录无效')
        target = directory / upload['name']
        temporary = directory / (uuid.uuid4().hex + '.tmp')
        checksum = hashlib.sha256()
        try:
            with temporary.open('xb') as out:
                for chunk in chunks:
                    source = pathlib.Path(box.root) / 'data/media-uploads' / uid / str(chunk['number'])
                    raw = source.read_bytes()
                    if source.is_symlink() or hashlib.sha256(raw).hexdigest() != chunk['sha256']:
                        raise ValueError('媒体分段校验失败')
                    out.write(raw)
                    checksum.update(raw)
                out.flush()
                os.fsync(out.fileno())
            sha = checksum.hexdigest()
            if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != sha:
                raise ValueError('媒体原件冲突')
            if not target.exists():
                os.replace(temporary, target)
            mime = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
            c.execute('INSERT INTO toolbox_files VALUES(?,?,?,?,?,?)', (uid, upload['name'], str(target), mime, upload['size'], sha))
            return {'id': uid, 'name': upload['name'], 'mime': mime, 'size': upload['size'], 'sha256': sha}
        finally:
            temporary.unlink(missing_ok=True)
