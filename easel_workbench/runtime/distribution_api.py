"""Authenticated distribution routes. Credentials never enter draft persistence."""
from __future__ import annotations
import asyncio, hashlib, hmac, html, json, re, secrets, urllib.parse
from fastapi.responses import JSONResponse, Response
from easel_workbench.runtime.auth_totp import equal
from easel_workbench.runtime.toolbox_store import ident

def mount_service(box):
    from easel_workbench.runtime.distribution_service import DistributionService
    from easel_workbench.runtime.easel_distribution import EaselDistributionRuntime
    return DistributionService(box, EaselDistributionRuntime(box))

def bridge_status(service):
    method=getattr(service.runtime,'bridge_status',None)
    return method() if callable(method) else {'status':'not_configured','configured':False}

def bridge_page(service,session):
    esc=html.escape;nonce=secrets.token_urlsafe(24)
    content=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>连接同步桥接</title><style nonce="{nonce}">body{{font:16px/1.6 system-ui,sans-serif;background:#f5f7f8;color:#182527;margin:0;padding:24px}}main{{max-width:540px;margin:auto}}h1{{font-size:24px}}label,input,button{{display:block;box-sizing:border-box;width:100%}}input,button{{font:inherit;padding:14px;border:1px solid #a5b5b8;border-radius:10px;margin:8px 0 20px}}button{{background:#087f78;color:white;border:0}}a{{color:#087f78}}</style><main><a href="/native/?path=%2Ftoolbox%3Fsection%3Ddistribution%26pane%3Dconnections">返回账号连接</a><h1>连接同步桥接</h1><p>平台账号可从当前浏览器扩展自动发现。后台执行需单独连接本机桥接。</p><p>在文章同步助手的“同步桥接 / MCP 连接”中启用桥接，将密钥保存到这里。本机端口为 9527。</p><form method="post" action="/api/distribution/bridge/configure" autocomplete="off"><input type="hidden" name="csrf" value="{esc(session['csrf'],quote=True)}"><input type="hidden" name="operation_id" value="{secrets.token_hex(16)}"><label for="token">同步桥接密钥</label><input id="token" name="bridge_token" type="password" autocomplete="new-password" maxlength="4096" required><button type="submit">加密保存</button></form><p>密钥由运行工作台的电脑加密保管，不会发布内容。</p></main></html>'''
    return Response(content,media_type='text/html',headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Content-Security-Policy':f"default-src 'none'; style-src 'nonce-{nonce}'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"})

def credentials_page(service, session, connection_id, message=''):
    connection = service.connection_internal(ident(connection_id))
    esc = html.escape
    nonce = secrets.token_urlsafe(24)
    content = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>连接凭据</title><style nonce="{nonce}">body{{font:16px/1.6 system-ui,sans-serif;background:#f5f7f8;color:#182527;margin:0;padding:24px}}main{{max-width:540px;margin:auto}}h1{{font-size:24px}}label,input,button{{display:block;box-sizing:border-box;width:100%}}input,button{{font:inherit;padding:14px;border:1px solid #a5b5b8;border-radius:10px;margin:8px 0 20px}}button{{background:#087f78;color:white;border:0}}a{{color:#087f78}}.muted{{color:#53666a}}</style><main><a href="/native/?path=%2Ftoolbox%3Fsection%3Ddistribution%26pane%3Dconnections">返回账号连接</a><h1>连接凭据</h1><p>{esc(connection['label'] or connection['account'])}</p><p class="muted">专用浏览器中启用同步桥接，将连接密钥填在这里。凭据由此电脑加密保管。</p><p role="status">{esc(message)}</p><form method="post" action="/api/distribution/credentials" autocomplete="off"><input type="hidden" name="csrf" value="{esc(session['csrf'],quote=True)}"><input type="hidden" name="connection_id" value="{esc(connection['id'],quote=True)}"><input type="hidden" name="expected_revision" value="{connection['revision']}"><input type="hidden" name="operation_id" value="{secrets.token_hex(16)}"><label for="token">同步桥接密钥</label><input id="token" name="bridge_token" type="password" autocomplete="new-password" maxlength="4096" required><button type="submit">加密保存</button></form><p class="muted">安装扩展与登录平台分别检查；保存密钥不会发布内容。</p></main></html>'''
    return Response(content, media_type='text/html', headers={
        'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY',
        'Content-Security-Policy':f"default-src 'none'; style-src 'nonce-{nonce}'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"})

def configure_credentials(service, fields, credential_key):
    from easel_workbench.runtime.feedback_ledger import locked
    with locked(service.root/'data/distribution-credentials.lock'):
        return _configure_credentials(service,fields,credential_key)

def _configure_credentials(service, fields, credential_key):
    connection=service.connection_internal(ident(fields.get('connection_id')))
    operation_id=ident(fields.get('operation_id'))
    token=fields.get('bridge_token','')
    if not 16<=len(token)<=4096 or any(ord(c)<32 or c.isspace() for c in token):
        raise ValueError('连接密钥格式无效')
    fingerprint=hmac.new(credential_key,json.dumps({k:fields.get(k) for k in ('connection_id','expected_revision','bridge_token')},sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest()
    with service.store.connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS distribution_credential_operations(id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,command TEXT NOT NULL)')
        old=c.execute('SELECT * FROM distribution_credential_operations WHERE id=?',(operation_id,)).fetchone()
        occupied=c.execute('SELECT 1 FROM distribution_operations WHERE operation_id=?',(operation_id,)).fetchone()
    if occupied and not old:
        from easel_workbench.runtime.distribution_service import DistributionConflict
        raise DistributionConflict('保存操作标识已被使用，请返回重新配置')
    if old:
        if not hmac.compare_digest(old['fingerprint'],fingerprint):
            from easel_workbench.runtime.distribution_service import DistributionConflict
            raise DistributionConflict('同一保存操作的内容发生变化，请返回重新配置')
        command=json.loads(old['command'])
    else:
        if int(fields.get('expected_revision','0')) != connection['revision']:
            from easel_workbench.runtime.distribution_service import DistributionConflict
            raise DistributionConflict('连接已变化，请返回重新配置')
        ref=service.runtime.configure_secret(connection['id'],{'WECHATSYNC_TOKEN':token,'bridge_url':'ws://127.0.0.1:9527'})
        command={'action':'connection-save','operation_id':operation_id,'connection_id':connection['id'],'platform':connection['platform'],'account':connection['account'],'label':connection['label'],'enabled':connection['enabled'],'secret_ref':ref,'expected_revision':connection['revision']}
        # Persist the exact secret handle before command execution; an interrupted
        # form resumes the original command rather than minting another identity.
        with service.store.connect() as c:
            c.execute('INSERT OR IGNORE INTO distribution_credential_operations VALUES(?,?,?)',(operation_id,fingerprint,json.dumps(command)))
            original=c.execute('SELECT * FROM distribution_credential_operations WHERE id=?',(operation_id,)).fetchone()
        if not hmac.compare_digest(original['fingerprint'],fingerprint):
            from easel_workbench.runtime.distribution_service import DistributionConflict
            raise DistributionConflict('同一保存操作的内容发生变化')
        command=json.loads(original['command'])
    return service.command(command,actor='owner')

async def handle(service, path, request, session, same, raw, api_csrf, credential_key):
    if not path.startswith('/api/distribution/'):
        return None
    def reply(value, status=200):
        return JSONResponse(value,status_code=status,headers={'Cache-Control':'no-store'})
    method = request.method
    if getattr(service.runtime,'extension_retired',False):
        retired=path in ('/api/distribution/bridge/form','/api/distribution/bridge/configure','/api/distribution/credentials/form','/api/distribution/credentials','/api/distribution/discover','/api/distribution/observations','/api/distribution/import-account','/api/distribution/browser','/api/distribution/discovery') or path.startswith('/api/distribution/checks/')
        if retired:return reply({'error':'feature_retired','feature':'browser_extension_connection','retired':True,'message':'浏览器扩展连接已退役，请在账号页直接扫码连接。'},410)
    if path == '/api/distribution/auto-check' and method in ('GET','HEAD'):
        from easel_workbench.runtime import distribution_auto_api as distribution_auto_api
        return await distribution_auto_api.handle(service,path,request)
    if path == '/api/distribution/bridge/form' and method in ('GET','HEAD'):
        return bridge_page(service,session)
    if path == '/api/distribution/credentials/form' and method in ('GET','HEAD'):
        return credentials_page(service,session,request.query_params.get('connection_id',''))
    if path == '/api/distribution/bootstrap' and method in ('GET','HEAD'):
        data=await asyncio.to_thread(service.bootstrap,request.query_params.get('work_id') or None)
        from easel_workbench.runtime import distribution_discovery as distribution_discovery
        if not getattr(service.runtime,'extension_retired',False):data['discovery']={'bridge':bridge_status(service),'observation':await asyncio.to_thread(distribution_discovery.latest,service)}
        return reply(data)
    if path == '/api/distribution/discovery' and method in ('GET','HEAD'):
        from easel_workbench.runtime import distribution_discovery as distribution_discovery
        return reply({'bridge':bridge_status(service),'observation':await asyncio.to_thread(distribution_discovery.latest,service)})
    match=re.fullmatch(r'/api/distribution/checks/([A-Za-z0-9_-]{1,160})',path)
    if match and method in ('GET','HEAD'):
        from easel_workbench.runtime import distribution_check_api as distribution_check_api
        return reply(await asyncio.to_thread(distribution_check_api.service(service).status,match[1]))
    if method != 'POST':
        return reply({'error':'method rejected'},405)
    if not same:
        return reply({'error':'origin_rejected'},403)
    if path in ('/api/distribution/credentials','/api/distribution/bridge/configure'):
        if request.headers.get('content-type','').split(';')[0] != 'application/x-www-form-urlencoded' or len(raw)>16384:
            return reply({'error':'表单格式无效'},415)
        pairs=urllib.parse.parse_qs(raw.decode('utf-8'),keep_blank_values=True,max_num_fields=6,errors='strict')
        if any(len(v)!=1 for v in pairs.values()):
            return reply({'error':'重复表单字段'},400)
        fields={k:v[0] for k,v in pairs.items()}
        if not equal(fields.get('csrf',''),session['csrf']):
            return reply({'error':'csrf_rejected'},403)
        if path == '/api/distribution/bridge/configure':
            await asyncio.to_thread(service.runtime.configure_bridge,{'WECHATSYNC_TOKEN':fields.get('bridge_token','')},operation_id=ident(fields.get('operation_id')))
        else:await asyncio.to_thread(configure_credentials,service,fields,credential_key)
        return Response(status_code=303,headers={'Location':'/native/?'+urllib.parse.urlencode({'path':'/toolbox?section=distribution&pane=connections'}),'Cache-Control':'no-store'})
    if len(request.headers.getlist('x-csrf-token')) != 1 or not equal(request.headers.get('x-csrf-token',''),api_csrf):
        return reply({'error':'csrf_rejected'},403)
    if request.headers.get('content-type','').split(';')[0]!='application/json':
        return reply({'error':'请求类型无效'},415)
    value=json.loads(raw)
    if not isinstance(value,dict):
        raise ValueError('请求需要 JSON 对象')
    if path == '/api/distribution/auto-check':
        from easel_workbench.runtime import distribution_auto_api as distribution_auto_api
        return await distribution_auto_api.handle(service,path,request,value)
    if path == '/api/distribution/commands':
        value.setdefault('operation_id',value.get('id'))
        return reply(await asyncio.to_thread(service.command,value,actor='owner'))
    if path == '/api/distribution/observations':
        from easel_workbench.runtime import distribution_discovery as distribution_discovery
        return reply(await asyncio.to_thread(distribution_discovery.observe,service,value))
    if path == '/api/distribution/import-account':
        from easel_workbench.runtime import distribution_discovery as distribution_discovery
        return reply(await asyncio.to_thread(distribution_discovery.import_account,service,value))
    if path == '/api/distribution/discover':
        return reply(await asyncio.to_thread(service.runtime.discover_accounts))
    if path == '/api/distribution/probe':
        connection=service.connection_internal(ident(value.get('connection_id')))
        return reply(await asyncio.to_thread(service.runtime.probe,connection))
    if path == '/api/distribution/browser':
        from easel_workbench.runtime import distribution_install as distribution_install
        if value.get('purpose')=='discover':
            from easel_workbench.runtime import distribution_check_api as distribution_check_api
            return reply(await distribution_check_api.launch(service,value,request.headers['origin']))
        connection=service.connection_internal(ident(value.get('connection_id')))
        return reply(await asyncio.to_thread(distribution_install.open_browser,service.root,connection))
    return reply({'error':'资源不存在'},404)
