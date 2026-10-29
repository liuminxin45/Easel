"""Ente Auth code-only forms. Secrets are never rendered or logged."""
import html, re, secrets, threading, time, urllib.parse, pathlib
from http.cookies import SimpleCookie, CookieError
from easel_workbench.runtime.auth_totp import SESSION_AGE, equal
SESSION='__Host-desk_session'
PREFLIGHT='__Host-desk_login'

def safe_next(value):
    decoded=urllib.parse.unquote(value)
    if not value.startswith('/') or decoded.startswith('//') or any(c in decoded for c in '\\#\r\n\x00') or any(ord(c)<32 for c in decoded):return '/'
    if urllib.parse.urlsplit(value).netloc or urllib.parse.urlsplit(value).scheme:return '/'
    if decoded.split('?')[0] in ('/login','/logout','/logout-all'):return '/'
    return value

def cookie(name,token,age):
    return f'{name}={token}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age={age}'

def cookies(headers):
    try:
        result=SimpleCookie();result.load(headers.get('Cookie',''));return {k:v.value for k,v in result.items()}
    except CookieError:return {}

class Forms:
    def __init__(self,state):
        self.state=state;self.preflight={};self.lock=threading.RLock();self.web_root=getattr(state,'web_root',None)
    def session(self,h):return self.state.session(cookies(h.headers).get(SESSION))
    def send(self,h,status,body='',location=None,set_cookie=None):
        from easel_workbench.runtime.http_content import encode
        payload,encoding=encode(body.encode('utf-8'),h.headers,'text/html');h.send_response(status)
        headers={'Content-Type':'text/html; charset=utf-8','Content-Length':str(len(payload)),'Cache-Control':'no-store','Referrer-Policy':'same-origin','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Strict-Transport-Security':'max-age=31536000','Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline' https://fonts.googleapis.com; script-src 'self'; connect-src 'self'; img-src 'self'; manifest-src 'self'; font-src https://fonts.gstatic.com; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"}
        nonce=re.search(r'<meta name="style-nonce" content="([A-Za-z0-9_-]+)">',body)
        headers.update(encoding)
        if nonce:headers['Content-Security-Policy']=headers['Content-Security-Policy'].replace("style-src 'unsafe-inline' https://fonts.googleapis.com","style-src 'self' 'nonce-"+nonce.group(1)+"'")
        for k,v in headers.items():h.send_header(k,v)
        if location:h.send_header('Location',location)
        if set_cookie:h.send_header('Set-Cookie',set_cookie)
        if getattr(h,'auth_id',None):h.send_header('X-Desk-Auth-Request',h.auth_id)
        h.send_header('Connection','close');h.end_headers();h.close_connection=True
        if h.command!='HEAD':h.wfile.write(payload)
    def layout(self,title,content):
        from easel_workbench.runtime import web_assets as web_assets
        css=((pathlib.Path(self.web_root) if self.web_root else web_assets.root())/'style.css').read_text(encoding='utf-8')
        nonce=secrets.token_urlsafe(24)
        content=content.replace('<h1>工具箱</h1>','<h1>登录</h1>')
        return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#f7f9fa"><meta name="style-nonce" content="{nonce}"><meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-title" content="工具箱"><link rel="manifest" href="/manifest.webmanifest"><link rel="icon" href="/icons/app.svg"><link rel="apple-touch-icon" href="/icons/apple-touch-icon.png"><title>{title} · 工具箱</title><script src="/toolbox-boot.js" defer></script><script src="/ui-vendor.js" defer></script><script src="/auth-app.js" defer></script><script src="/auth-ui.js" defer></script><style nonce="{nonce}">{css}</style></head><body><div id="auth-root" data-page="{title}"><main class="auth-page"><section class="auth-card">{content}</section></main></div></body></html>'''

    def page(self,csrf,next_path='/',error=''):
        esc=html.escape
        return self.layout('登录',f'''<h1>工具箱</h1><p role="alert" class="error">{esc(error)}</p><form method="post" action="/login"><input type="hidden" name="csrf" value="{esc(csrf)}"><input type="hidden" name="next" value="{esc(next_path,quote=True)}"><label for="code">Ente Auth 验证码</label><input id="code" name="code" type="text" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{{6}}" minlength="6" maxlength="6" placeholder="000000" required autofocus><button type="submit">登录</button></form>''')
    def account_page(self,session):
        csrf=html.escape(session['csrf'])
        return self.layout('账号',f'''<h1>账号</h1><p>Ente Auth · 登录有效期 30 天</p><p><a href="/settings?panel=devices">通知设备</a></p><p><a href="/">返回工具箱</a></p><form method="post" action="/logout"><input type="hidden" name="csrf" value="{csrf}"><button>退出当前设备</button></form><form method="post" action="/logout-all"><input type="hidden" name="csrf" value="{csrf}"><button>退出全部设备</button></form>''')
    def login(self,h,fields=None):
        with self.lock:
            now=time.monotonic();self.preflight={k:v for k,v in self.preflight.items() if v>now}
            if fields is None:
                token=secrets.token_urlsafe(32)
                if len(self.preflight)>=256:self.preflight.pop(next(iter(self.preflight)))
                self.preflight[token]=now+600
                query=urllib.parse.parse_qs(urllib.parse.urlsplit(h.path).query)
                self.send(h,200,self.page(token,safe_next(query.get('next',['/'])[0])),set_cookie=cookie(PREFLIGHT,token,600));return
            token=cookies(h.headers).get(PREFLIGHT,'')
            if not token or token not in self.preflight or not equal(fields.get('csrf',''),token):
                reason='login_cookie_missing' if not token else 'login_challenge_expired' if token not in self.preflight else 'login_challenge_mismatch'
                getattr(h,'auth_event',lambda *a:None)(reason,403)
                if len(self.preflight)>=256:self.preflight.pop(next(iter(self.preflight)))
                replacement=secrets.token_urlsafe(32);self.preflight[replacement]=now+600
                self.send(h,403,self.page(replacement,safe_next(fields.get('next','/')),error='登录校验已过期，请再次点击登录；若仍失败，请允许 App 保存本站 Cookie。'),set_cookie=cookie(PREFLIGHT,replacement,600));return
            status,session=self.state.login(fields.get('code',''))
            if status!=303:
                getattr(h,'auth_event',lambda *a:None)('login_rate_limited' if status==429 else 'login_code_rejected',status)
                error='尝试过多，请 5 分钟后重试。' if status==429 else '验证码不正确、已使用或已过期，请使用下一组验证码。'
                self.send(h,status,self.page(token,safe_next(fields.get('next','/')),error));return
            self.preflight.pop(token,None)
            getattr(h,'auth_event',lambda *a:None)('login_success',303)
            self.send(h,303,location=safe_next(fields.get('next','/')),set_cookie=cookie(SESSION,session,SESSION_AGE))
