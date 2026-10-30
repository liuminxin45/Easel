"""Public, content-free PWA assets. Application data stays behind authentication."""
import pathlib,hashlib
from easel_workbench.runtime.http_content import encode

from easel_workbench.runtime.project_paths import ROOT
WEB = ROOT / 'web'
MIGRATION_ROOT = pathlib.Path(__file__).resolve().parents[1] / 'assets'
MIGRATION = {
    '/toolbox-boot.js': ('legacy-handoff-boot.js', 'text/javascript; charset=utf-8'),
    '/manifest.webmanifest': ('legacy-handoff.webmanifest', 'application/manifest+json'),
    '/sw.js': ('legacy-handoff-sw.js', 'text/javascript; charset=utf-8'),
    '/offline.html': ('legacy-handoff.html', 'text/html; charset=utf-8'),
}
PUBLIC = {
    '/ui-vendor.js': ('ui-vendor.js', 'text/javascript; charset=utf-8'),
    '/auth-app.js': ('auth-app.js', 'text/javascript; charset=utf-8'),
    '/auth-ui.js': ('auth-ui.js', 'text/javascript; charset=utf-8'),
    '/icons/app.svg': ('icons/app.svg', 'image/svg+xml'),
    '/icons/icon-192.png': ('icons/icon-192.png', 'image/png'),
    '/icons/icon-512.png': ('icons/icon-512.png', 'image/png'),
    '/icons/maskable-512.png': ('icons/maskable-512.png', 'image/png'),
    '/icons/apple-touch-icon.png': ('icons/apple-touch-icon.png', 'image/png'),
}


def asset(path,web=None,*,project=None):
    # The retired root entry must not depend on the old active-web selector.
    # Its new worker never deletes caches or navigates an already open editor.
    migration = MIGRATION.get(path)
    if migration:
        name, mime = migration
        return (MIGRATION_ROOT / name).read_bytes(), mime
    entry = PUBLIC.get(path)
    if not entry:
        return None
    name, mime = entry
    from easel_workbench.runtime import web_assets as web_assets
    project = pathlib.Path(project or WEB.parent)
    def archived():
        from easel_workbench.runtime.archive_assets import archived_alias
        result = archived_alias(project,path)
        if result is None:
            raise FileNotFoundError('Retired static alias is unavailable')
        return result
    try:
        web = pathlib.Path(web) if web is not None else web_assets.root(project)
    except RuntimeError:
        # A retired/missing old selector is not a new UI dependency. The only
        # fallback is an explicitly pinned public auth/icon alias, never HTML.
        return archived()
    if not web.is_dir():
        return archived()
    try:
        return (web / name).read_bytes(), mime
    except FileNotFoundError:
        if not web.is_dir():return archived()
        raise


def serve(handler, path,web=None,*,project=None):
    result = asset(path,web,project=project)
    if result is None:
        return False
    body, mime = result
    body,encoding=encode(body,handler.headers,mime,public=True)
    etag='"'+hashlib.sha256(body).hexdigest()+'"'
    cached=any(tag.strip().removeprefix('W/') in (etag,'*') for tag in handler.headers.get('If-None-Match','').split(','))
    handler.send_response(304 if cached else 200)
    headers = {
        'Content-Type': mime, 'Content-Length': str(len(body)),
        'Cache-Control': 'no-store, no-cache, must-revalidate' if path in MIGRATION else 'no-cache', 'X-Content-Type-Options': 'nosniff',
        'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY',
        'Content-Security-Policy': "default-src 'none'; script-src 'self'; connect-src 'self'; style-src 'unsafe-inline'; img-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
        'ETag':etag,**encoding,
    }
    if path == '/sw.js':
        headers['Service-Worker-Allowed'] = '/'
    for key, value in headers.items():
        handler.send_header(key, value)
    handler.end_headers()
    if handler.command != 'HEAD' and not cached:
        handler.wfile.write(body)
    return True
