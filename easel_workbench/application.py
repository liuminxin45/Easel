"""Composition root for the private workflow application.

The upstream Easel web profile remains available independently. This profile
keeps the established owner authentication and write/receipt contracts.
"""
from pathlib import Path
import os


def create_app(*, root=None, **services):
    from .runtime.toolbox_server import create_app as workflows
    root = Path(root or os.environ.get('AI_DESK_PROJECT_ROOT') or Path(__file__).resolve().parents[1])
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
                    return JSONResponse({'error':'正在完成服务切换，输入草稿已保留，请稍后使用原操作重试。'},status_code=503,headers={'Cache-Control':'no-store','Retry-After':'5'})
            return await call_next(request)
    return app
