"""Pin production HTML/assets to a reviewed snapshot instead of a live editor tree."""
import json
import pathlib
import re
import secrets
import hashlib

from easel_workbench.runtime.project_paths import ROOT
DEFAULT_CSP = "default-src 'self'; script-src 'self'; worker-src 'self'; manifest-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"


def release_directory(project, name):
    base=(pathlib.Path(project)/'releases').resolve()
    if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,100}',name):raise FileNotFoundError()
    directory=(base/name).resolve()
    if not directory.is_relative_to(base) or not directory.is_dir():raise FileNotFoundError()
    return directory


def script_or_style(name):
    return isinstance(name,str) and bool(re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\.(?:js|css)',name)) and all(part not in ('.','..') for part in name.split('/'))


def release_asset(project, release, name):
    """Only immutable manifest members, with matching bytes, are executable assets."""
    if not script_or_style(name):raise FileNotFoundError()
    try:
        directory=release_directory(project,release)
    except FileNotFoundError:
        # A broken/replaced live package is an integrity error, not retirement.
        original=pathlib.Path(project)/'releases'/release
        if original.exists() or original.is_symlink():raise
        from easel_workbench.runtime.archive_assets import archived_asset
        archived=archived_asset(project,'releases',release,name)
        if archived is None:raise
        return archived
    manifest=json.loads((directory/'release.json').read_text(encoding='utf-8'))
    checksum=manifest.get('files',{}).get(name)
    if not isinstance(checksum,str) or not re.fullmatch(r'[a-f0-9]{64}',checksum):raise FileNotFoundError()
    target=(directory/name).resolve()
    if not target.is_relative_to(directory) or not target.is_file():raise FileNotFoundError()
    body=target.read_bytes()
    if hashlib.sha256(body).hexdigest()!=checksum:raise RuntimeError('Release asset integrity mismatch')
    return body,'text/javascript; charset=utf-8' if name.endswith('.js') else 'text/css; charset=utf-8'


def root(project=ROOT):
    project = pathlib.Path(project).resolve()
    selector = project / 'data' / 'active-web.json'
    if not selector.exists():
        return project / 'web'
    try:
        name = json.loads(selector.read_text(encoding='utf-8'))['release']
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,100}', name):
            raise ValueError()
        release = (project / 'releases' / name).resolve()
        if not release.is_relative_to((project / 'releases').resolve()) or not (release / 'index.html').is_file():
            raise ValueError()
        return release
    except (OSError, ValueError, KeyError, TypeError) as e:
        # A broken pin must never fall back to the unfinished live web directory.
        raise RuntimeError('Active web release unavailable') from e


def page(project=ROOT):
    project = pathlib.Path(project).resolve()
    web = root(project)
    html = (web / 'index.html').read_text(encoding='utf-8-sig')
    if (project / 'data' / 'active-web.json').exists():
        metadata = web / 'release.json'
        csp = json.loads(metadata.read_text(encoding='utf-8')).get('csp', DEFAULT_CSP) if metadata.exists() else DEFAULT_CSP
        if not isinstance(csp, str) or '\r' in csp or '\n' in csp:
            raise RuntimeError('Invalid release policy')
        return bind_nonce(html, csp)
    if 'content="ant"' in html or 'content="desktop-kit"' in html or 'type="text/babel"' in html or "type='text/babel'" in html:
        from easel_workbench.runtime import ui_document as ui_document
        return bind_nonce(*ui_document.render(web))
    return html, DEFAULT_CSP


def bind_nonce(html,csp):
    if '__DESK_STYLE_NONCE__' not in html:return html,csp
    nonce=secrets.token_urlsafe(24)
    return html.replace('__DESK_STYLE_NONCE__',nonce),csp.replace('__DESK_STYLE_NONCE__',nonce)


