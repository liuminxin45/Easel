"""Authenticated display descriptors and disposable image derivatives.

Callers authenticate before using resolve/read_thumbnail. Originals and the
existing signed native-downloader links are never changed by this module.
"""
from __future__ import annotations

from collections import OrderedDict
import hashlib
import heapq
import io
import math
import os
import pathlib
import re
import threading
import urllib.parse
import uuid
import warnings

from PIL import Image, ImageOps, __version__ as PILLOW_VERSION

from easel_workbench.runtime.image_delivery import IMAGE_TYPES

MAX_CACHE_BYTES = 256 * 1024 * 1024
MAX_THUMB_SOURCE_BYTES = 64 * 1024 * 1024
MAX_THUMB_PIXELS = 40_000_000
MAX_DERIVATIVE_BYTES = 1024 * 1024
MAX_DERIVATIVE_ENTRIES = 8192
THUMB_SIZE = 256
ENCODER_VERSION = 'thumb-256-webp-q80-v1-pillow-' + PILLOW_VERSION
VARIANTS = frozenset(('original', 'thumb-256'))
_SHA = re.compile(r'[a-f0-9]{64}')
_ID = re.compile(r'[A-Za-z0-9_-]{1,128}')
_DERIVATIVE = re.compile(r'[a-f0-9]{64}\.webp')
_SERVICE_LOCK = threading.RLock()


class MediaChanged(ValueError):
    """A requested content version is no longer the current source bytes."""


class MediaUnavailable(ValueError):
    """The requested image cannot safely produce a display derivative."""


def _stamp(path):
    value = path.stat()
    return (value.st_size, value.st_mtime_ns, value.st_ctime_ns, value.st_ino)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _thumbnail_dimensions(width, height):
    """Match Pillow's aspect-preserving rounding without allocating pixels."""
    if width <= THUMB_SIZE and height <= THUMB_SIZE:
        return width, height
    aspect = width / height
    if width > height:
        exact = THUMB_SIZE / aspect
        candidate = min(math.floor(exact), math.ceil(exact), key=lambda value: float('inf') if not value else abs(aspect - THUMB_SIZE / value))
        return THUMB_SIZE, max(1, candidate)
    exact = THUMB_SIZE * aspect
    candidate = min(math.floor(exact), math.ceil(exact), key=lambda value: abs(aspect - value / THUMB_SIZE))
    return max(1, candidate), THUMB_SIZE


def _png_exif(path):
    """Read optional eXIf chunks even after IDAT, without inflating pixels."""
    with path.open('rb') as source:
        if source.read(8) != b'\x89PNG\r\n\x1a\n':
            return None
        size = path.stat().st_size
        for _ in range(4096):
            header = source.read(8)
            if len(header) != 8:
                return None
            length = int.from_bytes(header[:4], 'big'); kind = header[4:]
            if source.tell() + length + 4 > size:
                raise ValueError('incomplete image metadata')
            if kind == b'eXIf':
                if length > 1024 * 1024:
                    raise ValueError('oversized image metadata')
                return source.read(length)
            if kind == b'IEND':
                return None
            source.seek(length + 4, 1)
    raise ValueError('too many image metadata chunks')


class MediaCache:
    def __init__(self, box, max_bytes=MAX_CACHE_BYTES):
        if type(max_bytes) is not int or max_bytes < 1:
            raise ValueError('图片缓存容量无效')
        self.box = box
        self.root = pathlib.Path(box.root).resolve()
        self.directory = self.root / '.runtime' / 'media-cache-v1'
        self.max_bytes = max_bytes
        self._hashes = OrderedDict()
        self._metadata = OrderedDict()
        self._disk_entries = OrderedDict()
        self._disk_bytes = 0
        self._disk_loaded = False
        self._lock = threading.RLock()
        self.metrics = {'hash_reads': 0, 'metadata_reads': 0, 'thumb_builds': 0, 'thumb_hits': 0, 'evictions': 0, 'index_scans': 0}

    def _directory(self):
        # Reject junctions/symlinks, including an ancestor redirected into
        # another directory that happens to be inside the project.
        if self.directory.resolve() != self.directory:
            raise MediaUnavailable('图片缓存目录位置异常，未读取或清理')
        self.directory.mkdir(parents=True, exist_ok=True)
        if self.directory.resolve() != self.directory:
            raise MediaUnavailable('图片缓存目录位置异常，未读取或清理')
        return self.directory

    def _safe_source(self, value, path):
        if not isinstance(value, dict) or not isinstance(value.get('id'), str) or not _ID.fullmatch(value['id']) or value.get('mime') not in IMAGE_TYPES:
            raise MediaUnavailable('本文件不是可显示的图片')
        path = pathlib.Path(path).resolve()
        roots = (self.root / 'data/artifacts', self.root / 'data/toolbox/files', self.root / 'data/workbench')
        if not any(path.is_relative_to(root.resolve()) for root in roots) or not path.is_file():
            raise MediaUnavailable('原图片已不可用')
        return path

    def _fingerprint(self, path):
        key = str(path)
        current = _stamp(path)
        previous = self._hashes.get(key)
        if previous and previous[0] == current:
            self._hashes.move_to_end(key)
            return previous[1], current[0]
        for _ in range(2):
            before = _stamp(path)
            digest = hashlib.sha256()
            with path.open('rb') as source:
                for block in iter(lambda: source.read(1024 * 1024), b''):
                    digest.update(block)
            after = _stamp(path)
            self.metrics['hash_reads'] += 1
            if before == after:
                result = digest.hexdigest()
                self._hashes[key] = (after, result)
                self._hashes.move_to_end(key)
                while len(self._hashes) > 2048:
                    self._hashes.popitem(last=False)
                return result, after[0]
        raise MediaChanged('图片正在变化，请重新读取作品')

    def _lookup(self, file_id):
        """Mirror the file API's roots/integrity without rehashing warm uploads.

        The signed original downloader deliberately keeps Toolbox.file's
        existing checks. Display requests use a bounded stat-keyed SHA memo:
        both the requested content ID and any stored upload SHA must match.
        """
        if not isinstance(file_id, str) or not _ID.fullmatch(file_id):
            raise MediaUnavailable('图片显示地址无效')
        with self.box.store.connect() as c:
            row = c.execute('SELECT * FROM toolbox_files WHERE id=?', (file_id,)).fetchone()
            if row is None:
                row = c.execute('SELECT * FROM artifacts WHERE id=?', (file_id,)).fetchone()
        if row is None:
            raise MediaUnavailable('原图片已不可用')
        value = dict(row)
        path = self._safe_source(value, value['path'])
        digest, size = self._fingerprint(path)
        if value.get('sha256') and value['sha256'] != digest:
            raise MediaChanged('原图片校验失败')
        return value, path, digest, size

    def _header_metadata(self, path, digest):
        previous = self._metadata.get(digest)
        if previous is not None:
            self._metadata.move_to_end(digest)
            return dict(previous)
        empty = {'width': None, 'height': None, 'thumbnail_width': None, 'thumbnail_height': None, 'animated': None}
        result = dict(empty)
        self.metrics['metadata_reads'] += 1
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(path) as image:
                    width, height = image.size
                    if image.format == 'PNG' and 'exif' not in image.info:
                        exif_data = _png_exif(path)
                        if exif_data is not None:
                            image.info['exif'] = exif_data
                    # PngImageFile.getexif() calls load() when EXIF is absent.
                    # The base method only parses header metadata already read.
                    orientation = Image.Image.getexif(image).get(274, 1)
                    if orientation in (5, 6, 7, 8):
                        width, height = height, width
                    animated = bool(getattr(image, 'is_animated', False))
                    tw, th = _thumbnail_dimensions(width, height)
                    result.update(width=width, height=height, thumbnail_width=tw, thumbnail_height=th, animated=animated)
        except Exception:
            # Invalid or unsupported metadata never fabricates dimensions and
            # never prevents the authenticated original-download fallback.
            result = empty
        current, _ = self._fingerprint(path)
        if current != digest:
            raise MediaChanged('图片已变化，请重新读取作品')
        self._metadata[digest] = dict(result)
        self._metadata.move_to_end(digest)
        while len(self._metadata) > 2048:
            self._metadata.popitem(last=False)
        return result

    def describe(self, value, path=None):
        """Add stable display URLs without generating thumbnails or a ticket."""
        with self._lock:
            if path is None:
                stored, path, digest, size = self._lookup(value['id'])
                value = {**stored, **value}
            else:
                path = self._safe_source(value, path)
                digest, size = self._fingerprint(path)
            if value.get('sha256') and value['sha256'] != digest:
                raise MediaChanged('原图片校验失败')
            url = '/api/media/images/' + urllib.parse.quote(value['id'], safe='') + '/' + digest
            # Only safe public descriptor fields are returned. Source paths,
            # session-derived links and decoder internals are never invented.
            public = {key: value[key] for key in ('id', 'name', 'mime', 'created_at', 'image_url') if key in value}
            return {**public, 'size': size, 'content_sha256': digest,
                    'display_url': url + '/original',
                    'thumbnail_url': url + '/thumb-256' if size <= MAX_THUMB_SOURCE_BYTES else None,
                    'thumbnail_version': ENCODER_VERSION, **self._header_metadata(path, digest)}

    def _owned_entries(self):
        for entry in self._directory().iterdir():
            if not _DERIVATIVE.fullmatch(entry.name) or entry.is_symlink() or entry.is_junction() or not entry.is_file():
                continue
            try:
                stat = entry.stat()
            except FileNotFoundError:
                continue
            yield entry, stat

    def _unlink_owned(self, name):
        if not _DERIVATIVE.fullmatch(name):
            return False
        path = self.directory / name
        if path.is_symlink() or path.is_junction():
            return False
        try:
            path.unlink()
            self.metrics['evictions'] += 1
        except FileNotFoundError:
            pass
        except (PermissionError, IsADirectoryError):
            return False
        previous = self._disk_entries.pop(name, None)
        if previous is not None:
            self._disk_bytes -= previous
        return True

    def _load_disk_index(self, protected=None):
        if self._disk_loaded:
            return
        # Recover the existing disposable directory once per server process.
        # nlargest bounds metadata memory even when upgrading an old directory
        # containing a very large number of tiny derivatives.
        total = 0
        count = 0
        protected_name = protected.name if protected is not None else None
        def candidates():
            nonlocal total, count
            for path, stat in self._owned_entries():
                total += stat.st_size; count += 1
                yield (path.name == protected_name, stat.st_mtime_ns, path.name, stat.st_size)
        kept = heapq.nlargest(MAX_DERIVATIVE_ENTRIES, candidates())
        names = {item[2] for item in kept}
        if count > MAX_DERIVATIVE_ENTRIES:
            # Only the first recovery scan may need this second bounded-memory
            # pass. Ordinary cache hits never enumerate the directory.
            for path, stat in self._owned_entries():
                if path.name not in names and self._unlink_owned(path.name):
                    total -= stat.st_size
        self._disk_entries = OrderedDict((name, size) for _, modified, name, size in sorted(kept, key=lambda item: (item[1], item[2])))
        self._disk_bytes = total
        self._disk_loaded = True
        self.metrics['index_scans'] += 1
        self._make_room(protected=protected_name)

    def _make_room(self, extra_bytes=0, extra_entries=0, protected=None):
        blocked = set()
        while self._disk_bytes + extra_bytes > self.max_bytes or len(self._disk_entries) + extra_entries > MAX_DERIVATIVE_ENTRIES:
            name = next((name for name in self._disk_entries if name != protected and name not in blocked), None)
            if name is None:
                return False
            if not self._unlink_owned(name):
                blocked.add(name)
        return True

    def _remember_disk(self, path, size):
        previous = self._disk_entries.pop(path.name, 0)
        self._disk_bytes += size - previous
        self._disk_entries[path.name] = size
        os.utime(path, None)

    def _encode(self, path, expected):
        if path.stat().st_size > MAX_THUMB_SOURCE_BYTES:
            raise MediaUnavailable('原图过大，请使用原图查看')
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(path) as image:
                    if image.width * image.height > MAX_THUMB_PIXELS:
                        raise MediaUnavailable('原图像素过大，请使用原图查看')
                    image.seek(0)  # GIF previews intentionally use the first frame.
                    frame = ImageOps.exif_transpose(image)
                    frame.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.Resampling.LANCZOS, reducing_gap=3.0)
                    frame = frame.convert('RGBA' if 'A' in frame.getbands() or 'transparency' in image.info else 'RGB')
                    output = io.BytesIO()
                    frame.save(output, format='WEBP', quality=80, method=4, exact=True)
                    body = output.getvalue()
            digest, _ = self._fingerprint(path)
            if digest != expected:
                raise MediaChanged('图片已变化，请重新读取作品')
            return body
        except (MediaChanged, MediaUnavailable):
            raise
        except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise MediaUnavailable('图片格式无法生成缩略图，请使用原图查看') from None

    def resolve(self, file_id, content_sha256, variant):
        """Return (safe response descriptor, captured path, strong quoted ETag)."""
        if not isinstance(file_id, str) or not _ID.fullmatch(file_id) or not isinstance(content_sha256, str) or not _SHA.fullmatch(content_sha256) or variant not in VARIANTS:
            raise MediaUnavailable('图片显示地址无效')
        with self._lock:
            value, path, actual, size = self._lookup(file_id)
            if actual != content_sha256:
                raise MediaChanged('图片版本已变化，请重新读取作品')
            if variant == 'original':
                return {key: value[key] for key in ('id', 'name', 'mime')}, path, '"' + actual + '"'
            key = _sha((actual + ':' + ENCODER_VERSION).encode())
            cache_path = self._directory() / (key + '.webp')
            if cache_path.is_symlink() or cache_path.resolve().parent != self.directory:
                raise MediaUnavailable('缩略图缓存位置异常')
            if cache_path.is_file():
                body = cache_path.read_bytes() if cache_path.stat().st_size <= min(self.max_bytes, MAX_DERIVATIVE_BYTES) else b''
                if len(body) < 12 or body[:4] != b'RIFF' or body[8:12] != b'WEBP':
                    if not self._unlink_owned(cache_path.name):
                        raise MediaUnavailable('缩略图缓存暂不可更新，请使用原图查看')
                    body = None
                else:
                    self.metrics['thumb_hits'] += 1
            else:
                body = None
            if body is None:
                body = self._encode(path, actual)
                if len(body) > self.max_bytes:
                    raise MediaUnavailable('图片缓存容量不足，请使用原图查看')
                self._load_disk_index()
                # A removed file can leave a stale metadata entry after an
                # external cache cleanup. Drop only that disposable entry.
                old_size = self._disk_entries.pop(cache_path.name, 0)
                self._disk_bytes -= old_size
                if not self._make_room(extra_bytes=len(body), extra_entries=1, protected=cache_path.name):
                    raise MediaUnavailable('图片缓存容量不足，请使用原图查看')
                temporary = cache_path.with_name(cache_path.name + '.' + uuid.uuid4().hex + '.tmp')
                try:
                    with temporary.open('xb') as stream:
                        stream.write(body); stream.flush(); os.fsync(stream.fileno())
                    os.replace(temporary, cache_path)
                finally:
                    temporary.unlink(missing_ok=True)
                self.metrics['thumb_builds'] += 1
            self._load_disk_index(protected=cache_path)
            self._remember_disk(cache_path, len(body))
            self._make_room(protected=cache_path.name)
            return {'id': value['id'], 'name': pathlib.Path(value['name']).stem + '-thumbnail.webp', 'mime': 'image/webp'}, cache_path, '"' + _sha(body) + '"'

    def read_thumbnail(self, file_id, content_sha256):
        """Read tiny derivatives while holding the eviction lock."""
        with self._lock:
            value, path, etag = self.resolve(file_id, content_sha256, 'thumb-256')
            return value, path.read_bytes(), etag


def service(box):
    with _SERVICE_LOCK:
        current = getattr(box, '_display_media_cache', None)
        if current is None:
            current = MediaCache(box)
            box._display_media_cache = current
        return current
