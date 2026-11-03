"""Composition root for the private workflow application.

The upstream Easel web profile remains available independently. This profile
keeps the established owner authentication and write/receipt contracts.
"""
from pathlib import Path
import os
import re
import secrets


def create_app(*, root=None, **services):
    from easel_workbench.runtime.toolbox_server import create_app as workflows
    root = Path(root or os.environ.get('AI_DESK_PROJECT_ROOT') or Path(__file__).resolve().parents[2])
    app = workflows(root=root, **services)
    app.state.easel_workbench_root = root
    if os.environ.get('EASEL_WORKBENCH_ADMISSION') == '1':
        from fastapi.responses import JSONResponse
        import json
        @app.middleware('http')
        async def admission(request,call_next):
            if request.method not in ('GET','HEAD','OPTIONS') and request.url.path not in ('/login','/logout','/logout-all'):
                state=root/'.local/workbench-deployment'
                try:ready=json.loads((state/'admission.json').read_text(encoding='utf-8')).get('workers') is True
                except (OSError,ValueError):ready=False
                if not ready or (state/'paused').exists():
                    from easel_workbench.runtime import server_logging as journal
                    operation=request.headers.get('x-operation-id','')
                    trace=getattr(request.state,'workbench_trace',None) or secrets.token_hex(8)
                    headers={'Cache-Control':'no-store','Retry-After':'5','X-Desk-Trace':trace}
                    body={'error':'服务正在切换，此操作尚未受理，请稍后重试。','code':'admission_paused','trace_id':trace}
                    if request.headers.get('x-workbench-operation-protocol')=='2' and len(request.headers.getlist('x-operation-id'))==1 and re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',operation):
                        body.update(protocol_version=2,operation_id=operation,operation_state='not_accepted');headers['X-Workbench-Operation-Protocol']='2'
                    journal.emit('admission_rejected',trace_id=trace,route=request.url.path,method=request.method,status=503,phase='not_accepted',operation_ref=journal.reference(operation))
                    return JSONResponse(body,status_code=503,headers=headers)
            return await call_next(request)
    @app.middleware('http')
    async def request_identity(request,call_next):
        # The outer middleware and business route share one server-issued trace.
        request.state.workbench_trace=secrets.token_hex(8)
        response=await call_next(request)
        response.headers['X-Desk-Trace']=request.state.workbench_trace
        return response
    from easel_workbench.health_endpoint import install_health
    install_health(app, root)
    return app
