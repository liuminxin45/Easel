"""Public, content-free PWA assets. Application data stays behind authentication."""
import pathlib,hashlib
from easel_workbench.runtime.http_content import encode

from easel_workbench.runtime.project_paths import ROOT
WEB = ROOT / 'web'
PUBLIC = {
    '/toolbox-boot.js': ('toolbox-boot.js', 'text/javascript; charset=utf-8'),
    '/ui-vendor.js': ('ui-vendor.js', 'text/javascript; charset=utf-8'),
    '/auth-app.js': ('auth-app.js', 'text/javascript; charset=utf-8'),
    '/auth-ui.js': ('auth-ui.js', 'text/javascript; charset=utf-8'),
    '/manifest.webmanifest': ('manifest.webmanifest', 'application/manifest+json'),
    '/sw.js': ('sw.js', 'text/javascript; charset=utf-8'),
    '/offline.html': ('offline.html', 'text/html; charset=utf-8'),
    '/icons/app.svg': ('icons/app.svg', 'image/svg+xml'),
    '/icons/icon-192.png': ('icons/icon-192.png', 'image/png'),
    '/icons/icon-512.png': ('icons/icon-512.png', 'image/png'),
    '/icons/maskable-512.png': ('icons/maskable-512.png', 'image/png'),
    '/icons/apple-touch-icon.png': ('icons/apple-touch-icon.png', 'image/png'),
}


def asset(path,web=None):
    entry = PUBLIC.get(path)
    if not entry:
        return None
    name, mime = entry
    from easel_workbench.runtime import web_assets as web_assets
    web = pathlib.Path(web) if web is not None else web_assets.root(WEB.parent)
    return (web / name).read_bytes(), mime


def serve(handler, path,web=None):
    result = asset(path,web)
    if result is None:
        return False
    body, mime = result
    body,encoding=encode(body,handler.headers,mime,public=True)
    etag='"'+hashlib.sha256(body).hexdigest()+'"'
    cached=any(tag.strip().removeprefix('W/') in (etag,'*') for tag in handler.headers.get('If-None-Match','').split(','))
    handler.send_response(304 if cached else 200)
    headers = {
        'Content-Type': mime, 'Content-Length': str(len(body)),
        'Cache-Control': 'no-cache', 'X-Content-Type-Options': 'nosniff',
        'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY',
        'Content-Security-Policy': "default-src 'none'; script-src 'self'; connect-src 'self'; style-src 'unsafe-inline'; img-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
        'ETag':etag,**encoding,
    }
    for key, value in headers.items():
        handler.send_header(key, value)
    handler.end_headers()
    if handler.command != 'HEAD' and not cached:
        handler.wfile.write(body)
    return True
