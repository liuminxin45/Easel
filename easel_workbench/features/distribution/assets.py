"""Read back exact approved asset bytes before the durable send boundary."""
import hashlib,pathlib
from .service import digest

def preflight_assets(box, revision):
    manifest = revision.get('asset_manifest')
    if not isinstance(manifest, list) or len(manifest) > 12:
        raise ValueError('asset_manifest_invalid')
    if digest({key: value for key, value in revision.items() if key not in ('id', 'created_at', 'hash')}) != revision.get('hash'):
        raise ValueError('revision_hash_mismatch')
    result = []
    root = (pathlib.Path(box.root) / 'data/toolbox/files').resolve()
    for expected in manifest:
        if not isinstance(expected, dict) or expected.get('mime') not in ('image/png', 'image/jpeg', 'image/webp', 'image/gif','video/mp4','video/webm','audio/mpeg','audio/wav','audio/x-wav','audio/mp4','audio/ogg'):
            raise ValueError('asset_kind_unsupported')
        metadata, path = box.file(expected.get('id'))
        path = path.resolve()
        if not path.is_relative_to(root) or path.is_symlink() or not path.is_file():
            raise ValueError('asset_path_invalid')
        size = path.stat().st_size
        limit=(32 if expected['mime'].startswith('image/') else 512)*1024*1024
        if type(expected.get('size')) is not int or size != expected['size'] or not 0 < size <= limit:
            raise ValueError('asset_size_mismatch')
        checksum = hashlib.sha256()
        with path.open('rb') as stream:
            while chunk := stream.read(1024 * 1024):
                checksum.update(chunk)
        if checksum.hexdigest() != expected.get('sha256') or metadata.get('sha256') != expected['sha256']:
            raise ValueError('asset_hash_mismatch')
        result.append({key: expected[key] for key in ('id', 'name', 'mime', 'sha256', 'size')} | {'path': str(path)})
    return result
