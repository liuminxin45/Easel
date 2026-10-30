"""Authenticated candidate UI. No business state or AI execution is implemented here."""
import hashlib,json,mimetypes,pathlib,re,secrets
from fastapi.responses import Response

def selected(root):
    root=pathlib.Path(root);pointer=root/'data/active-native.json'
    if not pointer.is_file():return None
    value=json.loads(pointer.read_text(encoding='utf-8'));name=value.get('release','')
    if not re.fullmatch(r'native-[A-Za-z0-9_-]{1,80}',name):raise RuntimeError('Invalid native selector')
    directory=(root/'native-releases'/name).resolve()
    if not directory.is_relative_to((root/'native-releases').resolve()):raise RuntimeError('Invalid native path')
    manifest=directory/'native-manifest.json'
    if value.get('manifest_sha256') and hashlib.sha256(manifest.read_bytes()).hexdigest()!=value['manifest_sha256']:raise RuntimeError('Native manifest changed')
    return directory,json.loads(manifest.read_text(encoding='utf-8'))

def member(root,release,name):
    if not re.fullmatch(r'native-[A-Za-z0-9_-]{1,80}',release) or not name or '\\' in name:raise FileNotFoundError()
    directory=(pathlib.Path(root)/'native-releases'/release).resolve();path=(directory/name).resolve()
    if not directory.exists():
        from easel_workbench.runtime.archive_assets import archived_asset
        archived=archived_asset(root,'native-releases',release,name)
        if archived is None:raise FileNotFoundError()
        return archived[0]
    if not path.is_relative_to(directory) or not path.is_file():raise FileNotFoundError()
    manifest=json.loads((directory/'native-manifest.json').read_text(encoding='utf-8'));expected=manifest['files'].get(name)
    if not expected:raise FileNotFoundError()
    body=path.read_bytes()
    if hashlib.sha256(body).hexdigest()!=expected:raise RuntimeError('Native asset changed')
    return body

def response(body,status=200,content_type='text/html; charset=utf-8',**extra):
    return Response(body,status_code=status,headers={'Content-Type':content_type,'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'same-origin','X-Frame-Options':'DENY',**extra})

def page(root,directory,manifest,auth=False,template=None):
    selected_template=template or ('auth.html' if auth else 'index.html')
    if selected_template not in ('auth.html','index.html','check.html'):raise ValueError('Invalid native template')
    nonce=secrets.token_urlsafe(24);source=member(root,manifest['release'],selected_template).decode('utf-8')
    # The critical entry stylesheet is present even if a second CSS request fails.
    def inline(match):
        href=match.group(1);prefix='/native-assets/'+manifest['release']+'/'
        if not href.startswith(prefix):return match.group(0)
        css=member(root,manifest['release'],href[len(prefix):]).decode('utf-8')
        return '<style nonce="'+nonce+'">'+css+'</style>'
    source=re.sub(r'<link\b[^>]*rel="stylesheet"[^>]*href="([^"]+)"[^>]*>',inline,source)
    source=source.replace('__DESK_STYLE_NONCE__',nonce)
    csp="default-src 'self'; script-src 'self'; style-src 'self' 'nonce-"+nonce+"'; img-src 'self' blob: data:; font-src 'self'; connect-src 'self'; worker-src 'self'; manifest-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    return response(source,**{'Content-Security-Policy':csp})

async def _handle_native(request,root,authenticated):
    path=request.url.path
    if not (path in ('/native','/native/') or path.startswith(('/native/','/native-assets/'))):return None
    if request.method not in ('GET','HEAD'):return response('method rejected',405,'text/plain')
    picked=selected(root)
    if picked is None:return response('原生界面候选尚未准备完成',503,'text/plain; charset=utf-8')
    directory,manifest=picked
    if path.startswith('/native-assets/'):
        match=re.fullmatch(r'/native-assets/(native-[A-Za-z0-9_-]{1,80})/(.+)',path)
        if not match:return response('not found',404,'text/plain')
        name=match[2]
        # Login's scripts/styles are public code only, never API responses or originals.
        if not re.search(r'\.(?:js|css|svg|png|webp|woff2?)$',name):return response('not found',404,'text/plain')
        try:body=member(root,match[1],name)
        except FileNotFoundError:return response('not found',404,'text/plain')
        mime='text/javascript' if name.endswith('.js') else 'text/css' if name.endswith('.css') else mimetypes.guess_type(name)[0] or 'application/octet-stream'
        return response(body,content_type=mime,**{'Cache-Control':'private, max-age=31536000, immutable','Cross-Origin-Resource-Policy':'same-origin'})
    if path=='/native/login':return page(root,directory,manifest,auth=True)
    if not authenticated:
        next_path=path+('?' + request.url.query if request.url.query else '')
        import urllib.parse
        return response('',303,Location='/native/login?'+urllib.parse.urlencode({'next':next_path}))
    if path=='/native':return response('',303,Location='/native/'+('?' + request.url.query if request.url.query else ''))
    if path=='/native/licenses':
        names=('licenses/Easel-NOTICE.txt','licenses/Easel-LICENSE.txt')
        return response(b'\n\n'.join(member(root,manifest['release'],name) for name in names),content_type='text/plain; charset=utf-8')
    if path=='/native/version':return response(json.dumps({'release':manifest['release']}),content_type='application/json')
    if path=='/native/sw.js':return response(member(root,manifest['release'],'sw.js'),content_type='text/javascript',**{'Service-Worker-Allowed':'/native/'})
    if path=='/native/manifest.webmanifest':return response(member(root,manifest['release'],'manifest.webmanifest'),content_type='application/manifest+json')
    if re.fullmatch(r'/native/chat(?:/[A-Za-z0-9_.-]{1,128})?',path):
        import urllib.parse
        target=path.removeprefix('/native')+('?' + request.url.query if request.url.query else '')
        return response('',303,Location='/native/?'+urllib.parse.urlencode({'path':target}))
    if path=='/native/':return page(root,directory,manifest)
    return response('not found',404,'text/plain')

async def handle_native(request,root,authenticated):
    result=await _handle_native(request,root,authenticated)
    if result is None:return None
    from easel_workbench.runtime.http_content import encode
    mime=result.headers.get('Content-Type','application/octet-stream')
    body,encoding=encode(result.body,request.headers,mime,public=request.url.path.startswith('/native-assets/'))
    headers={key:value for key,value in result.headers.items() if key.lower()!='content-length'}
    headers.update(encoding);headers['content-length']=str(len(body))
    return Response(b'' if request.method=='HEAD' else body,status_code=result.status_code,headers=headers)
