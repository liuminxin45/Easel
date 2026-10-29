"""One HTML source for double-click preview and the authenticated online app."""
import base64, hashlib, pathlib, re


def render(web):
    web = pathlib.Path(web)
    source = (web / 'index.html').read_text(encoding='utf-8-sig')
    source = source.replace('https://unpkg.com/react@18/umd/react.production.min.js', '/vendor/react.production.min.js')
    source = source.replace('https://unpkg.com/react-dom@18/umd/react-dom.production.min.js', '/vendor/react-dom.production.min.js')
    source = source.replace('<script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>', '')
    source = re.sub(r'<script type="text/babel"[^>]*>[\s\S]*?</script>', '<script src="/app.js" defer></script>', source)
    source = source.replace('</head>', '<link rel="manifest" href="/manifest.webmanifest"><link rel="icon" href="/icons/app.svg"><link rel="apple-touch-icon" href="/icons/apple-touch-icon.png"></head>')
    style = re.search(r'<style>([\s\S]*?)</style>', source).group(1)
    digest = base64.b64encode(hashlib.sha256(style.encode()).digest()).decode()
    csp = ("default-src 'self'; script-src 'self'; worker-src 'self'; manifest-src 'self'; "
           f"style-src 'self' 'sha256-{digest}' 'nonce-__DESK_STYLE_NONCE__'; "
           "font-src 'self' https://fonts.gstatic.com; img-src 'self' blob:; connect-src 'self'; "
           "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
    if 'content="ant"' in source or 'content="desktop-kit"' in source:
        source=re.sub(r'<style>[\s\S]*?</style>','<link rel="stylesheet" href="/style.css">',source,count=1)
    return source, csp
