"""One authenticated FastAPI app, direct data reads and durable tool actions."""

if __name__ == "__main__" and not __package__:
    import sys as _bootstrap_sys
    from pathlib import Path as _BootstrapPath
    _bootstrap_sys.path.insert(0,str(_BootstrapPath(__file__).resolve().parents[2]))

import asyncio,contextlib,email.message,hashlib,json,mimetypes,pathlib,re,secrets,time,urllib.parse
from contextlib import asynccontextmanager
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse,Response,StreamingResponse
from easel_workbench.runtime.auth_forms import Forms,SESSION,cookies,cookie
from easel_workbench.runtime.auth_totp import AuthState,CONFIG,equal
from easel_workbench.runtime.http_context import Context
from easel_workbench.runtime.toolbox_store import Toolbox,ident,text,pack
from easel_workbench.runtime.desk import ROOT,Store,SOURCES,THREAD,stamp
from easel_workbench.runtime.api_security import csrf_token
from easel_workbench.runtime import server_logging as journal
from easel_workbench.runtime import image_delivery as image_delivery
from easel_workbench.runtime import distribution_entry as distribution_entry

TOOLS=[{'id': 'workbench', 'name': '工作台', 'path': '/toolbox', 'description': '采集、选题、日历与发布数据。'}, {'id': 'chat', 'name': '对话', 'path': '/chat', 'description': '在 Easel 会话中调用项目技能。'}, {'id': 'skills', 'name': '技能库', 'path': '/toolbox?section=skills', 'description': '创作方法、版本与整理经验。'}, {'id': 'content', 'name': '内容库', 'path': '/works', 'description': '作品、素材和版本反馈。'}, {'id': 'accounts', 'name': '账号', 'path': '/toolbox?section=distribution&pane=connections', 'description': '平台连接与能力证据。'}, {'id': 'profiles', 'name': '画像', 'path': '/toolbox?section=profiles', 'description': '身份、读者、表达与默认技能。'}]
def create_app(store=None,auth=None,box=None,root=ROOT,wiki=None,studio=None,distribution=None):
    root=pathlib.Path(root);store=store or Store();auth=auth or AuthState(CONFIG);box=box or Toolbox(store,root)
    forms=Forms(auth,inert=True);csrf=csrf_token(store);origin=auth.data['origin'];host=auth.data['host']
    def error(code,message):return JSONResponse({'error':message},status_code=code,headers={'Cache-Control':'no-store'})
    def reply(data,code=200):return JSONResponse(data,status_code=code,headers={'Cache-Control':'no-store'})
    app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
    from easel_workbench.runtime.news_overviews import Overviews
    overviews=Overviews(store,root);app.state.overviews=overviews
    from easel_workbench.runtime.weekly_periodical import Periodical
    periodical=Periodical(store,root);app.state.periodical=periodical
    app.state.box=box;app.state.auth=auth
    from easel_workbench.settings import service as settings_service,handle as settings_api
    settings=settings_service(box);app.state.settings=settings
    from easel_workbench.runtime.collection_service import CollectionService
    collection=CollectionService(store,root);app.state.collection=collection
    from easel_workbench.runtime.studio_service import StudioService,StudioConflict as WorkspaceConflict,StudioUnavailable as WorkspaceUnavailable
    studio=studio or StudioService(box,root=root)
    box.studio=studio;app.state.studio=studio
    from easel_workbench.runtime.learning_execution import attach as attach_learning
    from easel_workbench.runtime.learning_service import LearningConflict
    learning=attach_learning(box,studio);app.state.learning=learning
    from easel_workbench.runtime.creator_runtime import CreatorRuntime,CreatorConflict
    creator=CreatorRuntime(box,project=studio.project);box.creator=creator;app.state.creator=creator
    from easel_workbench.chat import ChatService
    from easel_workbench.chat_business import ChatBusiness
    from easel_workbench.chat_api import handle as chat_api
    chat_business=ChatBusiness(box,root=root)
    chat=ChatService(box,root=root,on_started=chat_business.started,on_finish=chat_business.finished,on_accept=chat_business.accept)
    chat_business.chat=chat;app.state.chat=chat;app.state.chat_business=chat_business
    from easel_workbench.native_corrections import NativeCorrections
    corrections=NativeCorrections(chat,chat_business);app.state.native_corrections=corrections
    app.add_event_handler('startup',corrections.start)
    app.add_event_handler('shutdown',corrections.close)
    app.add_event_handler('shutdown',chat.close)
    from easel_workbench.runtime import distribution_api as distribution_api
    distribution=distribution or distribution_api.mount_service(box)
    app.state.distribution=distribution
    from easel_workbench.runtime.easel_frontend import service as frontend_service,FrontendConflict
    frontend=frontend_service(box)
    from easel_workbench.runtime.easel_connection_support import ConnectionConflict as IntegrationConflict
    from easel_workbench.runtime.easel_accounts import service as easel_account_service
    accounts=easel_account_service(box,distribution);app.state.easel_accounts=accounts
    app.add_event_handler('shutdown',accounts.close_native)
    from easel_workbench.runtime.completion_service import CompletionService,CompletionConflict
    from easel_workbench.runtime.completion_preferences import PreferencesConflict
    completion=CompletionService(box,distribution=distribution,studio=studio)
    box.completion=completion;app.state.completion=completion
    from easel_workbench.runtime.usage_service import SafeUsageService,UsageError
    usage=SafeUsageService(store,root);app.state.usage=usage
    from easel_workbench.runtime import distribution_auto_api as distribution_auto_api
    app.state.account_auto_check_retirement=distribution_auto_api.mount(distribution,origin)
    from easel_workbench.runtime import read_cache as read_cache; from easel_workbench.runtime import media_cache as media_cache
    media=media_cache.service(box);app.state.media=media
    views=read_cache.ViewCache(store,root,studio.project);app.state.view_cache=views
    def decorate_images(value,session,token,file_context=False):
        if isinstance(value,list):return [decorate_images(row,session,token,file_context) for row in value]
        if not isinstance(value,dict):return value
        result={key:decorate_images(row,session,token,key in ('artifacts','files','images','thumbnail')) for key,row in value.items()}
        if (result.get('mime') in image_delivery.IMAGE_TYPES or file_context and not result.get('mime')) and isinstance(result.get('id'),str) and isinstance(result.get('name'),str):
            try:result={**result,**media.describe(result)}
            except (ValueError,OSError):pass
            url=image_delivery.image_url(result,session,token)
            if url:result['image_url']=url
        return result
    async def body(request,limit):
        if len(request.headers.getlist('content-length'))>1:raise ValueError('重复请求长度')
        if int(request.headers.get('content-length','0'))>limit:raise ValueError('请求内容过大')
        size=0;parts=[]
        async with asyncio.timeout(25):
            async for part in request.stream():
                size+=len(part)
                if size>limit:raise ValueError('请求内容过大')
                parts.append(part)
        return b''.join(parts)
    def as_form(headers,raw):
        if headers.get('content-type','').split(';')[0]!='application/x-www-form-urlencoded' or not 0<len(raw)<=16384:raise ValueError('表单格式无效')
        rows=urllib.parse.parse_qs(raw.decode('utf-8'),keep_blank_values=True,max_num_fields=10,errors='strict')
        if any(len(value)!=1 for value in rows.values()):raise ValueError('重复表单字段')
        return {key:value[0] for key,value in rows.items()}
    def file_response(value,path,headers,download=False,etag_override=None,cache_control='no-store'):
        from easel_workbench.runtime.artifact_delivery import descriptor,disposition
        range_header=headers.get('range');if_range=headers.get('if-range')
        if etag_override:
            if if_range and if_range!=etag_override:range_header=None
            if_range=None
        code,start,length,extra=descriptor(path,value['id'],range_header,if_range)
        if etag_override:extra['ETag']=etag_override
        def chunks():
            with path.open('rb') as stream:
                stream.seek(start);left=length
                while left:
                    part=stream.read(min(65536,left))
                    if not part:raise OSError('附件发生变化')
                    left-=len(part);yield part
        mode='inline' if value['mime'].startswith(('image/','video/','audio/')) and not download else 'attachment'
        sandbox="default-src 'none'; sandbox"+(' allow-downloads' if value['mime'] in image_delivery.IMAGE_TYPES else '')
        return StreamingResponse(chunks(),status_code=code,media_type=value['mime'],headers={'Content-Length':str(length),'Cache-Control':cache_control,'X-Content-Type-Options':'nosniff','Content-Security-Policy':sandbox,'Content-Disposition':disposition(value['name'],mode),**({'Vary':'Accept-Encoding, Cookie'} if etag_override else {}),**extra})
    async def dispatch(path,request,trace,bypass_read_cache=False):
        path='/'+path;method=request.method;headers=request.headers
        target=path+('?' + request.url.query if request.url.query else '')
        if len(headers.getlist('host'))!=1 or headers.get('host')!=host:return error(403,'Host rejected')
        if headers.get('sec-fetch-site')=='cross-site':return error(403,'cross-site rejected')
        from easel_workbench.runtime import native_api
        if method not in ('GET','HEAD','POST') and not (method in ('PUT','PATCH','DELETE') and native_api.supports(path,method)):return error(405,'method rejected')
        if target.startswith('//') or '\\' in target or '#' in target or headers.get('upgrade') or len(headers.getlist('authorization'))>1:return error(400,'请求格式无效')
        if method in ('GET','HEAD') and (headers.get('transfer-encoding') or int(headers.get('content-length','0'))):return error(400,'GET 不接受请求内容')
        raw=await body(request,20*1024*1024 if path in ('/api/uploads','/api/upload') else 5*1024*1024 if re.fullmatch(r'/api/media/uploads/[A-Za-z0-9_-]+/chunks/\d+',path) else 512000) if method in ('POST','PUT','PATCH','DELETE') else b''
        request._body=raw
        pairs=[(key.decode('latin1'),value.decode('latin1')) for key,value in headers.raw];ctx=Context(method,target,pairs,raw)
        ctx.auth_id=trace
        ctx.auth_event=lambda reason,status:journal.emit('authentication',trace_id=ctx.auth_id,route=path,status=status,phase=reason)
        same=len(headers.getlist('origin'))==1 and headers.get('origin')==origin and headers.get('sec-fetch-site') in (None,'same-origin')
        from easel_workbench.runtime import pwa_assets as pwa_assets; from easel_workbench.runtime import web_assets as web_assets
        from easel_workbench.runtime import distribution_check_api as distribution_check_api
        check_response=await distribution_check_api.public(distribution,path,request,same,raw)
        if check_response is not None:return check_response
        auto_response=await distribution_auto_api.public(distribution,path,request,same,raw)
        if auto_response is not None:return auto_response
        if method in ('GET','HEAD') and path=='/distribution-entry.js':return distribution_entry.script_response(method)
        if path.startswith('/api/workbench/') or path.startswith('/api/v2/') or path in ('/api/cache-session','/api/offline-manifest','/api/action'):
            return error(410,'旧工作台与同步接口已停用，请重新打开工具箱；草稿会保留')
        if path=='/api/mobile/poll':return error(410,'通知设备与通知推送已退役')
        if method in ('GET','HEAD') and pwa_assets.asset(path,project=root) is not None:
            pwa_assets.serve(ctx,path,project=root);return ctx.response()
        if path=='/login':
            # Native auth still reads the original inert CSRF challenge via
            # fetch; only opening the old document moves to the native UI.
            if method in ('GET','HEAD') and (headers.get('sec-fetch-mode')=='navigate' or 'text/html' in headers.get('accept','')):
                return Response(status_code=303,headers={'Location':'/native/login'+('?' + request.url.query if request.url.query else ''),'Cache-Control':'no-store'})
            if method=='POST' and not same:return error(403,'origin_rejected')
            await asyncio.to_thread(forms.login,ctx,as_form(headers,raw) if method=='POST' else None);return ctx.response()
        match=re.fullmatch(r'/media/images/([A-Za-z0-9_-]{1,128})/([^/]+)',path)
        if path.startswith('/media/images/'):
            if method not in ('GET','HEAD'):return error(405,'method rejected')
            if not match or not image_delivery.read_session(auth,request.query_params):return error(403,'图片链接无效或已过期，请刷新作品页面')
            try:value,file=await asyncio.to_thread(box.file,match[1])
            except ValueError:return error(403,'图片链接无效或已过期，请刷新作品页面')
            if match[2]!=value['name'] or not image_delivery.authorize(value,auth,request.query_params):return error(403,'图片链接无效或已过期，请刷新作品页面')
            return file_response(value,file,headers,request.query_params.get('download')=='1')
        session=await asyncio.to_thread(forms.session,ctx)
        if path in ('/native','/native/') or path.startswith(('/native/','/native-assets/')):
            from easel_workbench.runtime import native_preview as native_preview
            native_response=await native_preview.handle_native(request,root,bool(session))
            if native_response is not None:return native_response
        if not session:
            if method in ('GET','HEAD') and (path in ('/','/toolbox','/chat','/news','/posters','/posters/new','/articles','/articles/new','/works','/works/new','/settings','/messages','/account','/account/password','/workbench','/apps','/wiki') or path.startswith(('/chat/','/articles/','/posters/','/works/','/news/a/','/news/production/','/workbench/','/wiki/'))):
                native_target='/native/?'+urllib.parse.urlencode({'path':target})
                forms.send(ctx,303,location='/native/login?next='+urllib.parse.quote(native_target,safe=''));return ctx.response()
            return error(401,'authentication_required')
        if native_api.supports(path,method):
            native_value=None
            if method in ('POST','PUT','PATCH','DELETE'):
                if not same:return error(403,'origin_rejected')
                if len(headers.getlist('x-csrf-token'))!=1 or not equal(headers.get('x-csrf-token',''),csrf):return error(403,'csrf_rejected')
                if len(headers.getlist('x-operation-id'))!=1:return error(400,'原生操作缺少唯一身份')
                content_type=headers.get('content-type','').split(';')[0]
                if path=='/api/upload' and content_type=='multipart/form-data':pass
                elif content_type=='application/json':
                    native_value=json.loads(raw)
                    if not isinstance(native_value,dict):return error(400,'请求需要 JSON 对象')
                else:return error(415,'请求类型无效')
            native_response=await native_api.handle(box,path,request,native_value)
            if native_response is not None:return native_response
        if path=='/api/wiki' or path.startswith('/api/wiki/'):
            return error(410,'资料库已移除，笔记原件保留')
        if path=='/wiki' or path.startswith('/wiki/'):
            return Response(status_code=303,headers={'Location':'/toolbox','Cache-Control':'no-store'})
        # Owner authentication above remains mandatory for retired routes too.
        # Original image display is a pre-existing workbench feature.
        legacy_account = path == '/api/media/accounts' or path.startswith('/api/media/accounts/')
        history_read = method in ('GET','HEAD') and bool(re.fullmatch(r'/api/media/jobs/[A-Za-z0-9_-]+(?:/transcript)?',path))
        if path.startswith('/api/media/') and not (legacy_account or path.startswith('/api/media/images/') or history_read):
            return error(410,'Easel 仅保留平台连接；媒体制作、配置与迁入入口已撤下，历史数据保留')
        media_match=re.fullmatch(r'/api/media/images/([A-Za-z0-9_-]{1,128})/([a-f0-9]{64})/(original|thumb-256)',path)
        if path.startswith('/api/media/images/'):
            if method not in ('GET','HEAD'):return error(405,'method rejected')
            if not media_match or request.url.query:return error(400,'图片展示地址无效')
            fid,content_sha256,variant=media_match.groups()
            try:
                if variant=='thumb-256':value,content,etag=await asyncio.to_thread(media.read_thumbnail,fid,content_sha256)
                else:value,file,etag=await asyncio.to_thread(media.resolve,fid,content_sha256,variant)
            except media_cache.MediaChanged:return error(410,'图片版本已变化，请刷新作品')
            except (media_cache.MediaUnavailable,ValueError,FileNotFoundError):return error(404,'图片暂不可用，请查看原件或刷新作品')
            media_headers={'Cache-Control':'private, no-cache, must-revalidate','Vary':'Accept-Encoding, Cookie','ETag':etag,'Cross-Origin-Resource-Policy':'same-origin'}
            if read_cache.matches(headers.get('if-none-match'),etag):return Response(status_code=304,headers=media_headers)
            if variant=='thumb-256':return Response(content,media_type=value['mime'],headers=media_headers)
            return file_response(value,file,headers,etag_override=etag,cache_control=media_headers['Cache-Control'])
        cache_policy=read_cache.policy(path) if method in ('GET','HEAD') and not bypass_read_cache else None
        if cache_policy:
            async def load_read_view():
                response=await dispatch(path.removeprefix('/'),request,trace,True)
                if response.status_code==200 and response.headers.get('content-type','').startswith('application/json'):
                    data=await asyncio.to_thread(decorate_images,json.loads(response.body),session,cookies(ctx.headers).get(SESSION))
                    return JSONResponse(data,headers={'Cache-Control':'no-store'})
                return response
            scope=hashlib.sha256(session['csrf'].encode()).hexdigest()
            return await views.respond(request,scope,load_read_view,cache_policy)
        distribution_response=await distribution_api.handle(distribution,path,request,session,same,raw,csrf,auth.data['secret'].encode())
        if distribution_response is not None:return distribution_response
        if method in ('GET','HEAD') and path=='/toolbox':
            if request.query_params.get('section')=='learning':
                return Response(status_code=303,headers={'Location':'/native/?'+urllib.parse.urlencode({'path':target}),'Cache-Control':'no-store'})
            entry_location=distribution_entry.native_target(request.query_params)
            if entry_location:return Response(status_code=303,headers={'Location':entry_location,'Cache-Control':'no-store'})
        if method in ('GET','HEAD') and path=='/toolbox' and request.query_params.get('panel')=='experience':
            q=request.query_params;screen=q.get('screen','home');pane=q.get('section','overview')
            location=('/toolbox?'+urllib.parse.urlencode({'section':'foundation' if screen in ('foundation','rules','context') else 'insights','pane':pane})) if screen in ('foundation','rules','context','insights') else '/news' if screen.startswith('news') else '/toolbox' if screen in ('wiki','note','library') else '/settings' if screen=='settings' else '/toolbox' if screen=='notifications' else ('/articles' if q.get('format')=='article' else '/posters')+('/new' if screen=='create' else '') if screen in ('work','works','create') else '/toolbox'
            if screen in ('work','context') and re.fullmatch(r'[A-Za-z0-9_-]{1,160}',q.get('work','')):
                try:
                    work=await asyncio.to_thread(box.work,q['work']);location=('/articles/' if work['format']=='article' else '/posters/')+work['id']
                    if any(v['id']==q.get('version') for v in work['versions']):location+='?'+urllib.parse.urlencode({'version':q['version']})
                except ValueError:pass
            return Response(status_code=303,headers={'Location':location,'Cache-Control':'no-store'})
        if path in ('/logout','/logout-all'):
            if method!='POST':return error(405,'method rejected')
            if not same:return error(403,'origin_rejected')
            fields=as_form(headers,raw)
            if not auth.logout(cookies(ctx.headers).get(SESSION),fields.get('csrf',''),all_sessions=path=='/logout-all'):return error(403,'csrf_rejected')
            forms.send(ctx,303,location='/login',set_cookie=cookie(SESSION,'',0));return ctx.response()
        if path in ('/account','/account/password'):
            if method=='POST':return error(405,'method rejected')
            return Response(status_code=303,headers={'Location':'/native/?path=%2Fsettings','Cache-Control':'no-store'})
        if path in ('/api/mobile/devices','/api/notifications','/api/notifications/read'):
            if method not in ('GET','HEAD') and (not same or len(headers.getlist('x-csrf-token'))!=1 or not equal(headers.get('x-csrf-token',''),csrf)):return error(403,'csrf_rejected')
            return error(410,'通知页与通知设备已退役，任务进度请在工作台或作品中查看')
        if method in ('GET','HEAD'):
            settings_response=await settings_api(settings,path,request)
            if settings_response is not None:return settings_response
            chat_response=await chat_api(chat,chat_business,path,request,authenticated=lambda:auth.session(cookies(ctx.headers).get(SESSION)),serve_file=file_response)
            if chat_response is not None:
                if hasattr(chat_response,'body') and chat_response.status_code==200:
                    return reply(decorate_images(json.loads(chat_response.body),session,cookies(ctx.headers).get(SESSION)))
                return chat_response
        if method=='POST':
            if not same:return error(403,'origin_rejected')
            if len(headers.getlist('x-csrf-token'))!=1 or not equal(headers.get('x-csrf-token',''),csrf):return error(403,'csrf_rejected')
            if path=='/api/uploads':
                if headers.get('content-type','').split(';')[0]!='application/octet-stream':return error(415,'请求类型无效')
                return reply(await asyncio.to_thread(box.upload,ident(headers.get('x-operation-id')),urllib.parse.unquote(headers.get('x-file-name',''),errors='strict'),raw))
            if headers.get('content-type','').split(';')[0]!='application/json':return error(415,'请求类型无效')
            value=json.loads(raw)
            if not isinstance(value,dict):raise ValueError('请求需要 JSON 对象')
            if path=='/api/collection/sources':
                return reply(await asyncio.to_thread(collection.registry.update,value))
            settings_response=await settings_api(settings,path,request,value)
            if settings_response is not None:return settings_response
            chat_response=await chat_api(chat,chat_business,path,request,value,authenticated=lambda:auth.session(cookies(ctx.headers).get(SESSION)),serve_file=file_response)
            if chat_response is not None:return chat_response
            if path=='/api/creative/preview':
                from easel_workbench.runtime.creative_recipes import service as recipes
                try:return reply(await asyncio.to_thread(recipes(box).preview,value))
                except ValueError as exc:return error(409,str(exc))
            if path=='/api/creative/commands':
                from easel_workbench.runtime.creative_recipes import service as recipes
                try:return reply(await asyncio.to_thread(recipes(box).command,value))
                except ValueError as exc:return error(409,str(exc))
            if path=='/api/creator/commands':
                try:return reply(await asyncio.to_thread(creator.command,value))
                except CreatorConflict as exc:return error(409,str(exc))
                except ValueError as exc:return error(400,str(exc))
            if path=='/api/platform-accounts/environment/install':
                from easel_workbench.runtime.connection_environment import service as environment_service
                try:return reply(await asyncio.to_thread(environment_service(box).install,value))
                except IntegrationConflict as exc:return error(409,str(exc))
                except ValueError as exc:return error(400,str(exc))
            if path in ('/api/platform-accounts','/api/media/accounts'):return error(410,'账号操作已迁入 Easel 原生登录接口；历史记录与回执保留')
            if path=='/api/easel/commands':
                try:return reply(await asyncio.to_thread(frontend.command,value))
                except FrontendConflict as exc:return error(409,str(exc))
                except ValueError as exc:return error(400,str(exc))
            if path in ('/api/usage/events','/api/usage/settings','/api/usage/clear'):
                if len(raw)>16384:return error(413,'统计批次不能超过16KB')
                handler={'/api/usage/events':usage.ingest,'/api/usage/settings':usage.settings,'/api/usage/clear':usage.clear}[path]
                try:return reply(await asyncio.to_thread(handler,session['csrf'],value))
                except UsageError as exc:return error(getattr(exc,'status',400),str(exc))
            completion_preview=re.fullmatch(r'/api/works/([A-Za-z0-9_-]+)/versions/([A-Za-z0-9_-]+)/completion-preview',path)
            if path=='/api/learning/commands':
                if value.get('action') in ('analyze-evidence','analysis-start','proposal-create','proposal-preview','proposal-confirm','proposal-revert'):
                    return error(410,'旧学习写入入口已退役。请在采集与研究拆解参考，或在技能库整理经验、确认技能版本。')
                try:return reply(await asyncio.to_thread(learning.command,value))
                except LearningConflict as exc:return error(409,str(exc))
                except ValueError as exc:return error(400,str(exc))
            if completion_preview:
                try:return reply(await asyncio.to_thread(completion.preview,*completion_preview.groups(),value))
                except CompletionConflict as exc:return error(409,str(exc))
            local_command=re.fullmatch(r'/api/works/([A-Za-z0-9_-]+)/(project-binding|local-operations/retry)',path)
            manual_review=re.fullmatch(r'/api/works/([A-Za-z0-9_-]+)/versions/([A-Za-z0-9_-]+)/manual-review',path)
            if local_command or manual_review:
                if not value.get('id'):value['id']=value.get('operation_id')
                ident(value.get('id'))
                if manual_review:
                    from easel_workbench.runtime.learning_execution import enqueue_manual_review
                    return reply(await asyncio.to_thread(enqueue_manual_review,box,*manual_review.groups(),value['id']))
                from easel_workbench.runtime import local_operations as local_operations
                try:
                    service=local_operations.service(box)
                    handler=service.bind if local_command[2]=='project-binding' else service.retry
                    return reply(await asyncio.to_thread(handler,{**value,'operation_id':value['id'],'work_id':local_command[1]}))
                except local_operations.LocalConflict as exc:return error(409,str(exc))
            if (path in ('/api/studio/commands','/api/completion/defaults') or re.fullmatch(r'/api/tasks/[A-Za-z0-9_-]+/retry',path) or re.fullmatch(r'/api/works/[A-Za-z0-9_-]+/completion/[A-Za-z0-9_-]+/retry-archive',path)) and not value.get('id'):value['id']=value.get('operation_id')
            ident(value.get('id'))
            if path=='/api/completion/defaults':
                from easel_workbench.runtime import completion_preferences as completion_preferences
                try:return reply(await asyncio.to_thread(completion_preferences.save,store,value))
                except PreferencesConflict as exc:return error(409,str(exc))
            completion_retry=re.fullmatch(r'/api/works/([A-Za-z0-9_-]+)/completion/([A-Za-z0-9_-]+)/retry-archive',path)
            if completion_retry:
                try:return reply(await asyncio.to_thread(completion.retry_archive,*completion_retry.groups(),value))
                except CompletionConflict as exc:return error(409,str(exc))
            if path=='/api/studio/context':
                try:return reply(await asyncio.to_thread(studio.context,value.get('work_id') or None,value.get('creative'),candidate_id=value.get('candidate_id') or None,request_text=value.get('request_text')))
                except WorkspaceConflict as exc:return error(409,str(exc))
            if path=='/api/studio/commands':
                action=value.get('action')
                if action in ('foundation-preview','foundation-confirm','foundation-revert','config-preview','config-confirm','config-revert'):
                    return error(410,'旧基座编辑入口已退役。请在创作画像维护身份与读者，在技能库确认提示词和资源版本。')
                if action=='proposal-create' and value.get('scope','work')!='work':
                    return error(410,'长期改进请整理为技能候选，并明确发布版本和适用范围。')
                if action in ('proposal-confirm','proposal-revert'):
                    with store.connect() as connection:
                        proposal=studio._get(connection,'proposals',value.get('proposal_id'))
                    if proposal.get('scope')!='work':return error(410,'旧长期提案保留供核对，请转入技能库修改可读提示词和资源。')
                try:return reply(await asyncio.to_thread(studio.command,value))
                except WorkspaceConflict as exc:return error(409,str(exc))
            if path=='/api/topic-research':
                from easel_workbench.runtime.studio_research import collect
                from easel_workbench.runtime.article_drafts import DraftConflict
                try:return reply(await asyncio.to_thread(collect,box,value))
                except DraftConflict as exc:return error(409,str(exc))
            if path=='/api/works':return reply(await asyncio.to_thread(box.create,value))
            from easel_workbench.runtime.article_drafts import save as save_article_draft,finalize as finalize_article,DraftConflict
            try:
                if path in ('/api/article-drafts','/api/drafts'):return reply(await asyncio.to_thread(save_article_draft,box,value))
                discussion_match=re.fullmatch(r'/api/works/([A-Za-z0-9_-]+)/discussions',path)
                if discussion_match:
                    from easel_workbench.runtime.work_discussions import enqueue as discuss_work
                    return reply(await asyncio.to_thread(discuss_work,box,discussion_match[1],value))
                draft_match=re.fullmatch(r'/api/works/([A-Za-z0-9_-]+)/(draft|finalize)',path)
                if draft_match:
                    return reply(await asyncio.to_thread(save_article_draft,box,value,draft_match[1]) if draft_match[2]=='draft' else await asyncio.to_thread(finalize_article,box,draft_match[1],value))
            except DraftConflict as exc:return error(409,str(exc))
            match=re.fullmatch(r'/api/tasks/([A-Za-z0-9_-]+)/retry',path)
            if match:
                if set(value)-{'id','operation_id','expected_retry_revision'}:raise ValueError('重试请求包含无关字段')
                return reply(await asyncio.to_thread(box.retry,match[1],operation_id=value.get('operation_id'),expected_retry_revision=value.get('expected_retry_revision')))
            match=re.fullmatch(r'/api/works/([A-Za-z0-9_-]+)/actions',path)
            if path=='/api/style-presets':
                return error(410,'风格参数预设已退役，请在技能库修改可读提示词并保存候选版本。')
            if path=='/api/text-works':
                from easel_workbench.runtime.content_studio import save_text,StudioConflict
                try:return reply(await asyncio.to_thread(save_text,box,value.get('id'),value,new=True))
                except StudioConflict as exc:return error(409,str(exc))
            text_match=re.fullmatch(r'/api/works/([A-Za-z0-9_-]+)/text',path)
            if text_match:
                from easel_workbench.runtime.content_studio import save_text,StudioConflict
                try:return reply(await asyncio.to_thread(save_text,box,text_match[1],value))
                except StudioConflict as exc:return error(409,str(exc))
            if match:
                from easel_workbench.runtime.work_review import ReviewConflict
                try:return reply(await asyncio.to_thread(box.action,match[1],value))
                except (ReviewConflict,CompletionConflict) as exc:return error(409,str(exc))
            match=re.fullmatch(r'/api/works/([A-Za-z0-9_-]+)/versions/([A-Za-z0-9_-]+)/review',path)
            if match:
                from easel_workbench.runtime.work_review import mutate,ReviewConflict
                try:return reply(await asyncio.to_thread(mutate,box,*match.groups(),value))
                except ReviewConflict as exc:return error(409,str(exc))
            if path=='/api/news/read':
                with store.connect() as c:changed=c.execute('UPDATE articles SET unread=0 WHERE id=? AND unread<>0',(ident(value.get('article_id')),)).rowcount>0
                return reply({'ok':True,'changed':changed})
            if path=='/api/news/feedback':
                from easel_workbench.runtime import news_feedback as news_feedback
                with store.connect() as c:fid=news_feedback.enqueue(c,ident(value.get('article_id')),text(value.get('text',''),10000,True),request_id=value['id'])
                with store.connect() as c:recorded=c.execute('SELECT status FROM news_feedback WHERE id=?',(fid,)).fetchone()
                return reply({'id':fid,'status':recorded['status'] if recorded else 'pending','execution_mode':'local','message':'系统已记录'})
            if path=='/api/news/feedback/retry':
                from easel_workbench.runtime import news_feedback as news_feedback
                with store.connect() as c:
                    c.execute('BEGIN IMMEDIATE')
                    outcome=news_feedback.retry(c,ident(value.get('feedback_id')))
                return reply({'ok':True,**outcome})
            if path=='/api/collection/runs':
                return reply(await asyncio.to_thread(collection.enqueue,value),202)
            collection_retry=re.fullmatch(r'/api/collection/runs/([A-Za-z0-9_-]{1,128})/retry',path)
            if collection_retry:
                return reply(await asyncio.to_thread(collection.retry,collection_retry.group(1),value),202)
            return error(404,'工具操作不存在')
        q=request.query_params
        source_receipt=re.fullmatch(r'/api/operations/([A-Za-z0-9_-]{1,128})',path)
        if source_receipt and q.get('path')=='/api/collection/sources':
            return reply(await asyncio.to_thread(collection.registry.receipt,source_receipt.group(1)))
        operation_receipt=re.fullmatch(r'/api/operations/([A-Za-z0-9_-]{1,160})',path)
        if operation_receipt:
            from easel_workbench.runtime.operation_receipts import read as read_operation_receipt
            return reply(await asyncio.to_thread(read_operation_receipt,store,operation_receipt[1],q.get('path',''),collection=collection))
        if path=='/api/creator/bootstrap':return reply(await asyncio.to_thread(creator.bootstrap))
        profile_proposal=re.fullmatch(r'/api/creator/profile-proposals/([A-Za-z0-9_-]+)',path)
        if profile_proposal:
            from easel_workbench.runtime.profile_learning import get as profile_proposal_get
            with store.connect() as connection:return reply(profile_proposal_get(connection,profile_proposal[1]))
        if path=='/api/easel/plans':return reply(await asyncio.to_thread(frontend.plans))
        if path=='/api/easel/topics':return reply(await asyncio.to_thread(frontend.topics))
        if path in ('/api/platform-accounts','/api/media/accounts'):return reply(await asyncio.to_thread(accounts.bootstrap))
        account_qr=re.fullmatch(r'/api/(?:platform-accounts|media/accounts)/([A-Za-z0-9_-]+)/qr',path)
        if account_qr:
            with store.connect() as connection:account=accounts._get(connection,account_qr[1])
            image=pathlib.Path(root)/'data/easel-accounts'/account['id']/'qr.png'
            if account.get('state')!='login' or request.query_params.get('revision')!=str(account['revision']) or not image.is_file():return error(404,'暂无待扫描二维码')
            return Response(await asyncio.to_thread(image.read_bytes),media_type='image/png',headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
        if path=='/api/platform-accounts/environment':
            from easel_workbench.runtime.connection_environment import service as environment_service
            return reply(await asyncio.to_thread(environment_service(box).check))
        media_job=re.fullmatch(r'/api/media/jobs/([A-Za-z0-9_-]+)(/transcript)?',path)
        if media_job:
            from easel_workbench.runtime.easel_integration import service as history_service
            history=history_service(box)
            try:return reply(await asyncio.to_thread(history.transcript if media_job[2] else history.job,media_job[1]))
            except ValueError as exc:return error(404,str(exc))
        creator_experience=re.fullmatch(r'/api/creator/experience/([A-Za-z0-9_-]{1,128})',path)
        if creator_experience:
            from easel_workbench.runtime.task_runtime import experience_detail
            def experience_read():
                with store.connect() as connection:return experience_detail(connection,creator_experience[1])
            try:return reply(await asyncio.to_thread(experience_read))
            except ValueError as exc:return error(404,str(exc))
        creator_resource=re.fullmatch(r'/api/creator/skills/([A-Za-z0-9_-]{1,128})/(export|resources/(?:(\d+)/)?(\d+))',path)
        if creator_resource:
            sid,action,release_version,index=creator_resource.groups()
            try:
                requested_version=release_version or q.get('version')
                version=int(requested_version) if requested_version else None
                if action=='export':
                    raw=await asyncio.to_thread(creator.export,sid,version)
                    return Response(raw,media_type='application/zip',headers={'Cache-Control':'no-store','Content-Disposition':'attachment; filename="'+sid+'.zip"','X-Content-Type-Options':'nosniff'})
                item=await asyncio.to_thread(creator.resource,sid,version,int(index))
                mime=mimetypes.guess_type(item['name'])[0] or 'application/octet-stream'
                inline=mime in ('image/png','image/jpeg','image/gif','image/webp','image/avif','text/plain','text/markdown','application/json')
                if mime.startswith('text/') and inline:mime='text/plain; charset=utf-8'
                if read_cache.matches(headers.get('if-none-match'),'"'+item['sha256']+'"'):
                    return Response(status_code=304,headers={'Cache-Control':'private, no-cache, must-revalidate','Vary':'Cookie','ETag':'"'+item['sha256']+'"'})
                return Response(item['bytes'],media_type=mime,headers={'Cache-Control':'private, no-cache, must-revalidate','Vary':'Cookie','ETag':'"'+item['sha256']+'"','Content-Disposition':'inline' if inline else 'attachment','X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'none'; sandbox"})
            except CreatorConflict as exc:return error(409,str(exc))
            except ValueError as exc:return error(404,str(exc))
        profile_asset=re.fullmatch(r'/api/creator/profiles/([A-Za-z0-9_-]{1,128})/assets/(\d+)/(\d+)',path)
        if profile_asset:
            try:
                item=await asyncio.to_thread(creator.profile_resource,profile_asset[1],int(profile_asset[2]),int(profile_asset[3]))
                etag='"'+item['sha256']+'"'
                private={'Cache-Control':'private, no-cache, must-revalidate','Vary':'Cookie','ETag':etag,'X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'none'; sandbox"}
                if read_cache.matches(headers.get('if-none-match'),etag):return Response(status_code=304,headers=private)
                return Response(item['bytes'],media_type=item['mime'],headers=private)
            except CreatorConflict as exc:return error(409,str(exc))
            except ValueError as exc:return error(404,str(exc))
        creator_detail=re.fullmatch(r'/api/creator/(profiles|skills|runs)/([A-Za-z0-9_-]{1,128})',path)
        if creator_detail:
            kind,key=creator_detail.groups()
            try:return reply(await asyncio.to_thread(creator.detail,kind,key,version=q.get('version')))
            except CreatorConflict as exc:return error(409,str(exc))
            except ValueError as exc:return error(404,str(exc))
        local_read=re.fullmatch(r'/api/works/([A-Za-z0-9_-]+)/local-operations',path)
        if local_read:
            from easel_workbench.runtime import local_operations as local_operations
            return reply(await asyncio.to_thread(local_operations.service(box).read,local_read[1]))
        completion_options=re.fullmatch(r'/api/works/([A-Za-z0-9_-]+)/versions/([A-Za-z0-9_-]+)/completion-options',path)
        if completion_options:
            from easel_workbench.runtime import completion_preferences as completion_preferences
            options=await asyncio.to_thread(completion.options,*completion_options.groups())
            options['defaults']=await asyncio.to_thread(completion_preferences.get,store)
            return reply(options)
        completion_work=re.fullmatch(r'/api/works/([A-Za-z0-9_-]+)/completion',path)
        if completion_work:return reply(await asyncio.to_thread(completion.get,completion_work.group(1)))
        if path=='/api/collection/status':return reply(await asyncio.to_thread(collection.status))
        if path=='/api/collection/sources':
            result=await asyncio.to_thread(collection.registry.public)
            definitions=await asyncio.to_thread(collection.definitions)
            result['sources']=[{**row,'enabled':definitions.get(row['id'],{}).get('enabled',False)} for row in result['sources']]
            return reply(result)
        collection_run=re.fullmatch(r'/api/collection/runs/([A-Za-z0-9_-]{1,128})',path)
        if collection_run:return reply(await asyncio.to_thread(collection.get,collection_run.group(1)))
        if path=='/api/creative/bootstrap':
            from easel_workbench.runtime.creative_recipes import service as recipes
            return reply(await asyncio.to_thread(recipes(box).bootstrap))
        if path=='/api/creative/effects':
            from easel_workbench.runtime.creative_recipes import service as recipes
            return reply(await asyncio.to_thread(recipes(box).effects,q.get('pack_id')))
        if path=='/api/creative/image-plans':
            from easel_workbench.runtime.creative_recipes import service as recipes
            return reply(await asyncio.to_thread(recipes(box).plans,ident(q.get('work_id'))))
        recipe_file=re.fullmatch(r'/api/creative/(assets|export|prompts)/([A-Za-z0-9_-]+)(?:/(\d+))?',path)
        if recipe_file:
            from easel_workbench.runtime.creative_recipes import service as recipes
            kind,key,index=recipe_file.groups();catalog=recipes(box)
            try:
                if kind=='prompts':return reply(await asyncio.to_thread(catalog.prompt_record,key))
                if kind=='assets':
                    data,mime=await asyncio.to_thread(catalog.asset,key,int(index or 0),q.get('variant')=='thumb')
                    asset_headers={'Cache-Control':'private, no-cache, must-revalidate','Vary':'Cookie','X-Content-Type-Options':'nosniff','ETag':'"'+hashlib.sha256(data).hexdigest()+'"'}
                    if read_cache.matches(headers.get('if-none-match'),asset_headers['ETag']):return Response(status_code=304,headers=asset_headers)
                    return Response(data,media_type=mime,headers=asset_headers)
                data=await asyncio.to_thread(catalog.export,key)
                return Response(data,media_type='application/zip',headers={'Cache-Control':'no-store','Content-Disposition':'attachment; filename="creative-recipe.zip"'})
            except (ValueError,OSError) as exc:return error(404,str(exc))
        if path=='/api/learning/bootstrap':return reply(await asyncio.to_thread(learning.bootstrap))
        if path=='/api/learning/evidence':
            try:return reply(await asyncio.to_thread(learning.list_evidence,q.get('query',''),q.get('kind',''),int(q.get('page','1'))))
            except ValueError as exc:return error(400,str(exc))
        learning_original=re.fullmatch(r'/api/learning/evidence/([A-Za-z0-9_-]+)/original',path)
        if learning_original:
            try:
                item=await asyncio.to_thread(learning.original_file,learning_original.group(1));raw=await asyncio.to_thread(item['path'].read_bytes)
                if hashlib.sha256(raw).hexdigest()!=item['sha256']:return error(409,'原件在读取时已变化，请更新索引再核对')
                return Response(raw,media_type=item['mime'],headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Content-Disposition':('inline' if item['mime'].startswith('image/') else 'attachment')+"; filename*=UTF-8''"+urllib.parse.quote(item['name'])})
            except (ValueError,FileNotFoundError):return error(404,'原件不可用或已变化')
        learning_detail=re.fullmatch(r'/api/learning/(evidence|method|profile|issue|proposal|run|cycle|batch)/([A-Za-z0-9_-]+)',path)
        if learning_detail:
            try:return reply(await asyncio.to_thread(learning.detail,*learning_detail.groups()))
            except ValueError as exc:return error(404,str(exc))
        if path=='/api/studio/bootstrap':return reply(await asyncio.to_thread(studio.bootstrap))
        if path=='/api/studio/foundation':return reply(await asyncio.to_thread(studio.foundation))
        if path=='/api/studio/context':return reply(await asyncio.to_thread(studio.context,q.get('work_id') or None,{'format':q.get('format','poster')},candidate_id=q.get('candidate_id') or None))
        def picture_links(value):
            url=image_delivery.image_url(value,session,cookies(ctx.headers).get(SESSION))
            return {**value,'image_url':url} if url else value
        if path=='/health':return reply({'ok':True,'architecture':'toolbox','thread':THREAD})
        if path=='/api/config':
            definitions=await asyncio.to_thread(collection.definitions)
            return reply({'csrf':csrf,'sources':{key:{k:row[k] for k in ('name','kind','feed','enabled','default','builtin') if k in row} for key,row in definitions.items()},'tools':TOOLS,'thread_link':'codex://threads/'+THREAD,'architecture':'toolbox','usage':await asyncio.to_thread(usage.config,session['csrf'])})
        if path=='/api/usage/summary':
            try:return reply(await asyncio.to_thread(usage.summary,session['csrf'],dict(q)))
            except UsageError as exc:return error(getattr(exc,'status',400),str(exc))
        if path=='/api/release':return reply({'release':web_assets.root(root).name,'architecture':'toolbox'})
        if path=='/api/news':
            registry=await asyncio.to_thread(store.sources,True)
            if registry.get(q.get('source'),{}).get('kind')=='periodical':
                result=await asyncio.to_thread(periodical.listing,q.get('issue',''),q.get('section',''),q.get('theme',''))
                production=await asyncio.to_thread(box.news_production,[row['id'] for row in result['items']])
                result['items']=[{**row,'poster':production.get(row['id'])} for row in result['items']]
                return reply(result)
            result=await asyncio.to_thread(store.article_day,q.get('q',''),q.get('source',''),'',q.get('day',''))
            production=await asyncio.to_thread(box.news_production,[row['id'] for row in result['items']])
            rows=await asyncio.to_thread(overviews.project,result['items'])
            result['items']=[{**{k:row[k] for k in ('id','title','original_title','overview','overview_status','overview_error','unread','selected')},**{k:row[k] for k in ('overview_source','overview_input_hash','source_job','run_at','source_order','hot','fetched_at') if k in row},'poster':production.get(row['id'])} for row in rows]
            return reply(result)
        if path.startswith('/api/periodicals/'):
            return reply(await asyncio.to_thread(periodical.original,ident(path.rsplit('/',1)[-1])))
        if path.startswith('/api/news/'):
            aid=ident(path.rsplit('/',1)[-1]);detail=await asyncio.to_thread(store.detail,aid)
            if not detail:return error(404,'资讯不存在')
            detail['poster']=(await asyncio.to_thread(box.news_production,[aid])).get(aid)
            return reply(detail)
        if path=='/api/style-presets':
            from easel_workbench.runtime.content_studio import catalog
            return reply(await asyncio.to_thread(catalog,box,q.get('format','poster')))
        if path=='/api/works':return reply(await asyncio.to_thread(box.works,q.get('format','')))
        review_match=re.fullmatch(r'/api/works/([A-Za-z0-9_-]+)/versions/([A-Za-z0-9_-]+)/review',path)
        if review_match:
            from easel_workbench.runtime.work_review import read as read_review
            return reply(await asyncio.to_thread(read_review,box,*review_match.groups()))
        if path=='/api/history':
            result=await asyncio.to_thread(box.archive,q.get('page','1'),q.get('kind',''))
            result['items']=[picture_links(value) for value in result['items']];return reply(result)
        match=re.fullmatch(r'/api/works/([A-Za-z0-9_-]+)/versions/([A-Za-z0-9_-]+)/download',path)
        if match:
            import tempfile,zipfile
            def archive():
                work=box.work(match[1]);version=next((v for v in work['versions'] if v['id']==match[2] and v['status']=='completed'),None)
                if version is None:raise ValueError('作品版本不存在')
                stream=tempfile.SpooledTemporaryFile(max_size=8*1024*1024)
                try:
                    images=[a for a in version['artifacts'] if a['mime'].startswith('image/')]
                    if not images:raise ValueError('此版本还没有图片文件')
                    with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_STORED) as bundle:
                        for n,item in enumerate(images,1):
                            _,file=box.file(item['id']);bundle.write(file,str(n).zfill(2)+'-'+file.name)
                    stream.seek(0);return stream
                except BaseException:stream.close();raise
            stream=await asyncio.to_thread(archive)
            def zip_chunks():
                try:
                    while part:=stream.read(65536):yield part
                finally:stream.close()
            return StreamingResponse(zip_chunks(),media_type='application/zip',headers={'Cache-Control':'no-store','Content-Disposition':'attachment; filename="poster-images.zip"'})
        if path.startswith('/api/works/'):
            result=await asyncio.to_thread(box.work,path.rsplit('/',1)[-1])
            with store.connect() as c:
                linked=c.execute("SELECT session_id,document FROM easel_chat_turns WHERE json_extract(document,'$.work.work_id')=? ORDER BY rowid DESC LIMIT 1",(result['id'],)).fetchone()
            if linked:result['native_chat']={'session_id':linked['session_id'],**json.loads(linked['document'])['work']}
            for version in result['versions']:version['artifacts']=[picture_links(value) for value in version['artifacts']]
            return reply(result)
        if path.startswith('/api/tasks/'):return reply(await asyncio.to_thread(box.job,path.rsplit('/',1)[-1]))
        if path.startswith('/api/files/') or path.startswith('/artifact/'):
            try:value,file=await asyncio.to_thread(box.file,path.rsplit('/',1)[-1])
            except ValueError as exc:return error(404,str(exc))
            return file_response(value,file,headers,q.get('download')=='1')
        if path.startswith(('/assets/','/toolbox-assets/')):
            parts=path.split('/',3)
            if len(parts)!=4:return error(404,'资源不存在')
            try:content,mime=web_assets.release_asset(root,parts[2],parts[3])
            except FileNotFoundError:return error(404,'资源不存在')
            return Response(content,media_type=mime,headers={'Cache-Control':'private, max-age=31536000, immutable'})
        if path in ('/app.js','/style.css','/workbench.js','/workbench.css') or re.fullmatch('/module-[A-Za-z0-9_.-]+\\.js',path):
            file=web_assets.root(root)/path[1:]
            if file.is_file():return Response(file.read_bytes(),media_type='text/css' if path.endswith('.css') else 'text/javascript',headers={'Cache-Control':'no-store'})
        if path.startswith('/workbench') or path=='/apps':return Response(status_code=303,headers={'Location':'/posters','Cache-Control':'no-store'})
        if path.startswith('/news/production/'):
            try:job=box.job(path.rsplit('/',1)[-1]);location='/posters/'+job['work_id']
            except ValueError:location='/posters'
            return Response(status_code=303,headers={'Location':location})
        if path=='/messages' and method in ('GET','HEAD'):return Response(status_code=303,headers={'Location':'/native/?path=%2Ftoolbox','Cache-Control':'no-store'})
        if path in ('/','/toolbox','/chat','/news','/posters','/posters/new','/articles','/articles/new','/works','/works/new','/settings','/messages') or re.fullmatch(r'/(?:chat|articles|posters|works|news/a)/[A-Za-z0-9_-]+',path):
            return Response(status_code=303,headers={'Location':'/native/?'+urllib.parse.urlencode({'path':target}),'Cache-Control':'no-store'})
        return error(404,'页面不存在')
    @app.api_route('/{path:path}',methods=['GET','HEAD','POST','PUT','PATCH','DELETE','OPTIONS'])
    async def route(path,request:Request):
        start=time.monotonic();trace=secrets.token_hex(8)
        try:result=await dispatch(path,request,trace)
        except WorkspaceConflict as exc:result=error(409,str(exc))
        except WorkspaceUnavailable as exc:result=error(503,str(exc))
        except FileNotFoundError as exc:result=error(404,str(exc))
        except (ValueError,TypeError,UnicodeError,KeyError) as exc:result=error(400,str(exc))
        except Exception as exc:
            journal.emit('request_error',trace_id=trace,route=request.url.path,error_type=type(exc).__name__);result=error(503,'服务器暂时不可用，请重试；未自动重复操作')
        if result.status_code==200 and hasattr(result,'body') and not result.headers.get('content-encoding'):
            from easel_workbench.runtime.http_content import encode
            payload,encoding=encode(result.body,request.headers,result.headers.get('content-type',''),public='immutable' in result.headers.get('cache-control',''))
            vary={item.strip() for item in result.headers.get('Vary','').split(',') if item.strip()}
            vary.update(item.strip() for item in encoding.get('Vary',encoding.get('vary','')).split(',') if item.strip())
            result.body=payload;result.headers.update(encoding);result.headers['Content-Length']=str(len(payload))
            if vary:result.headers['Vary']=', '.join(sorted(vary))
        result.headers.update({'X-Desk-Trace':trace,'X-Desk-Architecture':'toolbox','X-Desk-Workspace':'integrated-v1','Strict-Transport-Security':'max-age=31536000','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','X-Frame-Options':'DENY'})
        journal.emit('request_finished',trace_id=trace,route=request.url.path,method=request.method,status=result.status_code,duration_ms=round((time.monotonic()-start)*1000,3))
        if request.method=='HEAD':return Response(status_code=result.status_code,headers=dict(result.headers))
        return result
    return app
def main():
    import uvicorn
    journal.configure(ROOT/'data/logs/toolbox','server');journal.install_exception_hooks()
    import threading
    from easel_workbench.runtime.news_overviews import background
    app=create_app();stop=threading.Event()
    threading.Thread(target=background,args=(app.state.overviews,stop),name='news-chinese-overviews',daemon=True).start()
    try:uvicorn.run(app,host='127.0.0.1',port=9123,access_log=False,limit_concurrency=96,timeout_graceful_shutdown=8)
    finally:stop.set()
if __name__=='__main__':main()
