"""Route frozen configurations to original Easel engines, with no model client."""
from __future__ import annotations
import base64
import json
from pathlib import Path
import uuid
from easel.direct_api import stream_chat, history_path, DirectAPIError
from easel.harnesses.base import HarnessError


async def run(service, turn, request, emit, ask, bind):
    if turn['runtime'] == 'openclaw':
        from easel.harnesses.openclaw import OpenClawAdapter
        from dataclasses import replace
        environment = dict(request.env)
        environment.update(service.settings.openclaw_environment(turn['execution_settings']))
        await OpenClawAdapter().run(replace(request, env=environment), emit, ask, bind)
        return
    native = request.native_id or str(uuid.uuid4())
    bind(native)
    content = [{'type': 'text', 'text': turn['actual_prompt']}]
    for file in turn.get('attachments', []):
        descriptor, path = service.box.file(file['id'])
        if descriptor['mime'].startswith('image/'):
            content.append({'type':'image_url','image_url':{'url':'data:'+descriptor['mime']+';base64,'+base64.b64encode(Path(path).read_bytes()).decode('ascii')}})
        elif descriptor['mime'].startswith('text/'):
            content.append({'type':'text','text':Path(path).read_text(encoding='utf-8')})
        else:
            raise HarnessError('API 仅聊天只支持文本和模型支持的图片附件')
    completed = False
    try:
        async for kind, text in stream_chat(request.env, content, system=request.frozen_instructions or '',
                history_file=history_path(service.sessions_dir, native), timeout=request.timeout):
            if kind == 'finish':
                completed = True
            else:
                emit(kind, text)
    except DirectAPIError as error:
        raise HarnessError(str(error)) from None
    if not completed:
        raise HarnessError('API 未返回明确完成回执')
    # API chat has no server thread/turn ID. Keep that distinction in receipts.
    turn['completion_evidence'] = 'api_finish_stop'
