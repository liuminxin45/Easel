"""Private composition: no second model transport or publishing workflow."""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
from easel_workbench.runtime import server_logging as journal


class Insights:
    def __init__(self,box):
        from .reviews import service as reviews
        from .templates import Service as Templates
        from .metrics import Service as Metrics
        self.box=box;self.root=Path(box.root);self.loop=None;self.analytics=None
        self.reviews=reviews(box);self.reviews.allowed=self.allowed;self.templates=Templates(box)
        self.metrics=Metrics(box,fetch=self.fetch)

    async def start(self):
        self.loop=asyncio.get_running_loop()

    def fetch(self):
        async def read():
            if self.analytics is None:raise ValueError('公众号统计端口尚未接入')
            return await self.analytics()
        if self.loop is None or not self.loop.is_running():
            raise ValueError('公众号统计服务尚未就绪')
        return asyncio.run_coroutine_threadsafe(read(),self.loop).result(timeout=210)

    def allowed(self):
        if os.environ.get('EASEL_WORKBENCH_ADMISSION')=='1':
            try:
                state=self.root/'.local/workbench-deployment'
                if (state/'paused').exists() or json.loads((state/'admission.json').read_text(encoding='utf-8')).get('workers') is not True:return False
            except (ValueError,OSError):return False
        try:
            if json.loads((self.root/'data/automation-enabled.json').read_text(encoding='utf-8')).get('cutover_paused'):return False
        except FileNotFoundError:pass
        except (ValueError,OSError):return False
        return True

    def background(self,stop):
        while not stop.is_set():
            if self.allowed():
                for name,run in [('review',self.reviews.run_pending_once),('feedback',self.reviews.refresh_feedback),('metrics',self.metrics.run_due_once)]:
                    if stop.is_set() or not self.allowed():break
                    try:run()
                    except Exception as exc:journal.emit('production_insights_failed',phase=name,error_type=type(exc).__name__)
            stop.wait(20)

    def view(self,wid,vid):
        return {'review':self.reviews.view(wid,vid),'publication':self.metrics.view(wid,vid)}


def service(box):
    if not getattr(box,'_production_insights',None):box._production_insights=Insights(box)
    return box._production_insights
