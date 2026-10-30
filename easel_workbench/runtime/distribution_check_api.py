"""A phone-authorized, one-attempt account observation, never a login session."""
from __future__ import annotations
import asyncio,json,re,urllib.parse
from fastapi.responses import JSONResponse,Response
from easel_workbench.runtime import server_logging as journal

def service(distribution):
    from easel_workbench.runtime.distribution_checks import CheckService
    if not getattr(distribution,'account_checks',None):distribution.account_checks=CheckService(distribution.box)
    return distribution.account_checks

def reply(value,code=200):
    return JSONResponse(value,status_code=code,headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})

async def public(distribution,path,request,same,raw):
    if getattr(distribution.runtime,'extension_retired',False):
        if path=='/distribution/check':
            from easel_workbench.runtime.distribution_auto_api import ACCOUNTS_URL
            return Response(status_code=303,headers={'Location':ACCOUNTS_URL+'#','Cache-Control':'no-store','Referrer-Policy':'no-referrer'})
        if path=='/api/distribution/check-report':return reply({'error':'feature_retired','feature':'browser_extension_connection','retired':True},410)
    if path=='/distribution/check':
        if request.method not in ('GET','HEAD'):return reply({'error':'method rejected'},405)
        if request.url.query:return reply({'error':'检测页面不接受查询凭证'},400)
        from easel_workbench.runtime import native_preview as native_preview
        picked=native_preview.selected(distribution.root)
        if not picked:return reply({'error':'检测页面暂不可用'},503)
        directory,manifest=picked
        result=native_preview.page(distribution.root,directory,manifest,template='check.html')
        return result
    if path!='/api/distribution/check-report':return None
    if request.method!='POST':return reply({'error':'method rejected'},405)
    if not same:return reply({'error':'origin_rejected'},403)
    authorization=request.headers.get('authorization','')
    if not re.fullmatch(r'Bearer [A-Za-z0-9_-]{43}',authorization):return reply({'error':'检测凭证无效或已过期'},403)
    if request.url.query or request.headers.get('content-type','').split(';')[0]!='application/json':return reply({'error':'请求类型无效'},415)
    value=json.loads(raw)
    if not isinstance(value,dict) or set(value)-{'check_id','event','accounts','code'}:return reply({'error':'检测报告格式无效'},400)
    try:
        result=await asyncio.to_thread(service(distribution).accept,value.get('check_id'),authorization[7:],value.get('event'),accounts=value.get('accounts'),code=value.get('code'))
    except PermissionError:return reply({'error':'检测凭证无效或已过期'},403)
    journal.emit('account_check',operation_ref=journal.reference(value.get('check_id')),phase=result.get('phase'),count=len(value.get('accounts') or []) if value.get('event')=='result' else 0)
    return reply(result)

async def launch(distribution,value,origin):
    from easel_workbench.runtime.toolbox_store import ident
    from easel_workbench.runtime.distribution_install import open_browser
    checks=service(distribution)
    attempt=await asyncio.to_thread(checks.begin,ident(value.get('operation_id') or value.get('id')),actor='owner')
    check_id=attempt['check_id']
    if attempt.get('fresh'):
        target=origin+'/distribution/check#'+urllib.parse.urlencode({'check':check_id,'ticket':attempt['readonly_ticket']})
        try:await asyncio.to_thread(open_browser,distribution.root,None,target)
        except Exception:await asyncio.to_thread(checks.fail_launch,check_id)
    state=await asyncio.to_thread(checks.status,check_id)
    journal.emit('account_check',operation_ref=journal.reference(check_id),phase=state.get('phase'))
    return {'status':'launch_requested','check':state,'message':'已请求电脑执行本次只读检测。'}
