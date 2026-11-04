"""Route frozen configurations to original Easel engines, with no model client."""
from __future__ import annotations
import base64
from pathlib import Path
from types import SimpleNamespace
from easel.direct_api import stream_chat
from easel.harnesses.base import HarnessError


async def run(service, turn, request, emit, ask, bind, *, on_dispatch=None, stop_requested=None):
    """Adapt private attachment IDs and receipts to the common API supervisor."""
    from easel.web_services.chat import create_chat_context
    content = [{'type': 'text', 'text': turn['actual_prompt']}]
    for file in turn.get('attachments', []):
        descriptor, path = service.box.file(file['id'])
        if descriptor['mime'].startswith('image/'):
            content.append({'type':'image_url','image_url':{'url':'data:'+descriptor['mime']+';base64,'+base64.b64encode(Path(path).read_bytes()).decode('ascii')}})
        elif descriptor['mime'].startswith('text/'):
            content.append({'type':'text','text':Path(path).read_text(encoding='utf-8')})
        else:
            raise HarnessError('API 仅聊天只支持文本和模型支持的图片附件')
    async def questions(_session, items, _emit):return await ask(items)
    context=create_chat_context(service.root,backend=lambda sid:'api',environment=request.env,
        snapshot=lambda *args:None,ask=questions,scrub=str,running=service._native_controls,
        api_stream=stream_chat)
    # Closing an HTTP stream is not a provider-side stop acknowledgement.
    def completed():turn['completion_evidence']='api_finish_stop'
    await context._run_direct_chat(SimpleNamespace(turnId=turn['id']),turn['session_id'],
        content,request.frozen_instructions or '',emit,timeout=request.timeout,run_request=request,
        on_dispatch=on_dispatch,stop_requested=stop_requested,on_complete=completed,bind_native=bind,
        propagate_errors=True)
