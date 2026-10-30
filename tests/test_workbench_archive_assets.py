"""TEMP-only archived static lookup: no old UI entry or fallback guessing."""
import hashlib
import json
from pathlib import Path

import pytest

from easel_workbench.runtime import archive_assets


def sha(body):
    return hashlib.sha256(body).hexdigest()


@pytest.fixture
def stored(tmp_path):
    base = tmp_path / '.local/workbench-archives'
    registry = {'schema': 1, 'entries': {}, 'static_aliases': {}}
    for kind, release, manifest_name in [('releases', 'toolbox-old', 'release.json'),
                                         ('native-releases', 'native-old', 'native-manifest.json')]:
        relative = 'reviewed/retired/project/' + kind + '/' + release
        directory = base / relative; directory.mkdir(parents=True)
        files = {'app.js': b'original static script', 'style.css': b'body{}',
                 'auth-app.js': b'auth compatibility', 'icons/app.svg': b'<svg/>',
                 'index.html': b'OLD UI MUST NEVER START', 'sw.js': b'OLD WORKER',
                 'manifest.webmanifest': b'{"start_url":"/old"}'}
        for name, body in files.items():
            path = directory / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(body)
        manifest = json.dumps({'files': {name: sha(body) for name, body in files.items()}}).encode()
        (directory / manifest_name).write_bytes(manifest)
        registry['entries'][kind + '/' + release] = {'path': relative, 'manifest': manifest_name,
                                                    'manifest_sha256': sha(manifest)}
    registry['static_aliases']['/auth-app.js'] = 'releases/toolbox-old/auth-app.js'
    registry['static_aliases']['/icons/app.svg'] = 'releases/toolbox-old/icons/app.svg'
    path = base / 'registry.json'; path.write_text(json.dumps(registry), encoding='utf-8')
    return tmp_path, registry, path


def test_exact_native_and_web_static_work_with_live_directories_absent(stored):
    root, registry, _ = stored
    assert archive_assets.archived_asset(root, 'native-releases', 'native-old', 'app.js')[0] == b'original static script'
    assert archive_assets.archived_asset(root, 'releases', 'toolbox-old', 'style.css')[1].startswith('text/css')
    assert archive_assets.archived_alias(root, '/auth-app.js')[0] == b'auth compatibility'
    assert archive_assets.archived_alias(root, '/icons/app.svg')[0] == b'<svg/>'
    assert not (root / 'releases').exists() and not (root / 'native-releases').exists()


@pytest.mark.parametrize('name', ['index.html', 'sw.js', 'manifest.webmanifest', 'toolbox-boot.js',
                                  '../app.js', '/app.js', 'C:/app.js', 'a\\app.js', 'CON.js'])
def test_archived_entry_points_and_escaping_names_are_rejected(stored, name):
    root, _, _ = stored
    with pytest.raises(FileNotFoundError):
        archive_assets.archived_asset(root, 'native-releases', 'native-old', name)


def test_unknown_versions_or_missing_registry_never_choose_latest(stored, tmp_path):
    root, _, _ = stored
    assert archive_assets.archived_asset(root, 'native-releases', 'native-newer', 'app.js') is None
    assert archive_assets.archived_asset(tmp_path / 'unregistered', 'releases', 'toolbox-old', 'app.js') is None
    for path in ('/', '/index.html', '/sw.js', '/offline.html', '/manifest.webmanifest', '/toolbox-boot.js'):
        assert archive_assets.archived_alias(root, path) is None


def test_manifest_and_file_integrity_are_both_mandatory(stored):
    root, registry, _ = stored
    entry = registry['entries']['releases/toolbox-old']; directory = root / '.local/workbench-archives' / entry['path']
    (directory / 'app.js').write_bytes(b'tampered')
    with pytest.raises(RuntimeError, match='member integrity'):
        archive_assets.archived_asset(root, 'releases', 'toolbox-old', 'app.js')
    (directory / 'release.json').write_bytes(b'{"files":{}}')
    with pytest.raises(RuntimeError, match='manifest integrity'):
        archive_assets.archived_asset(root, 'releases', 'toolbox-old', 'app.js')


@pytest.mark.parametrize('path', ['../../outside', '/absolute/path', 'reviewed/retired/project/releases/other'])
def test_registry_cannot_select_another_version_or_leave_archive(stored, path):
    root, registry, registry_path = stored
    registry['entries']['releases/toolbox-old']['path'] = path
    registry_path.write_text(json.dumps(registry), encoding='utf-8')
    with pytest.raises((FileNotFoundError, RuntimeError)):
        archive_assets.archived_asset(root, 'releases', 'toolbox-old', 'app.js')


def test_unlisted_member_and_alias_mismatch_are_not_served(stored):
    root, registry, registry_path = stored
    with pytest.raises(FileNotFoundError):
        archive_assets.archived_asset(root, 'releases', 'toolbox-old', 'private.js')
    registry['static_aliases']['/auth-app.js'] = 'releases/toolbox-old/app.js'
    registry_path.write_text(json.dumps(registry), encoding='utf-8')
    with pytest.raises(RuntimeError, match='exact static file'):
        archive_assets.archived_alias(root, '/auth-app.js')


def test_archive_ancestor_junction_is_rejected_before_read(stored, monkeypatch):
    root, _, _ = stored
    original = archive_assets._link
    monkeypatch.setattr(archive_assets, '_link', lambda path: path.name == 'retired' or original(path))
    with pytest.raises(RuntimeError, match='link'):
        archive_assets.archived_asset(root, 'releases', 'toolbox-old', 'app.js')


def test_release_asset_fallback_does_not_hide_corrupt_live_directory(stored):
    from easel_workbench.runtime import web_assets
    root, _, _ = stored
    assert web_assets.release_asset(root, 'toolbox-old', 'app.js')[0] == b'original static script'
    live = root / 'releases/toolbox-old'; live.mkdir(parents=True)
    (live / 'release.json').write_text(json.dumps({'files': {'app.js': '0' * 64}}), encoding='utf-8')
    (live / 'app.js').write_bytes(b'live tampering')
    with pytest.raises(RuntimeError, match='integrity'):
        web_assets.release_asset(root, 'toolbox-old', 'app.js')


def test_native_member_archive_css_and_original_missing_member_boundary(stored):
    from easel_workbench.runtime import native_preview
    root, _, _ = stored
    assert native_preview.member(root, 'native-old', 'style.css') == b'body{}'
    for name in ('index.html', 'sw.js', 'manifest.webmanifest'):
        with pytest.raises(FileNotFoundError):
            native_preview.member(root, 'native-old', name)
    live = root / 'native-releases/native-old'; live.mkdir(parents=True)
    (live / 'native-manifest.json').write_text(json.dumps({'files': {'style.css': sha(b'body{}')}}), encoding='utf-8')
    # Archive contains this exact CSS; a partial original still fails closed.
    with pytest.raises(FileNotFoundError):
        native_preview.member(root, 'native-old', 'style.css')
