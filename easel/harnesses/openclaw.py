"""OpenClaw's native local CLI with an explicit caller-owned state directory.

No gateway is started or retargeted. The native CLI owns model/tool execution;
the caller owns session binding and treats interrupted CLI calls as unknown.
"""
from __future__ import annotations
import asyncio
import json
import hashlib
import os
import uuid
from .base import Descriptor, HarnessError
from .workspace import harness_instructions
from easel.openclaw_cmd import openclaw_base_cmd


class OpenClawAdapter:
    descriptor = Descriptor('openclaw', 'OpenClaw', 'native CLI', '安装并配置 OpenClaw CLI')

    async def run(self, request, emit, ask, bind):
        session = request.native_id or str(uuid.uuid4())
        command = openclaw_base_cmd() + ['agent', '--local', '--agent', 'main', '--session-id', session,
                                         '--json', '--timeout', str(request.timeout),
                                         '--message', harness_instructions(request) + '\n\n' + request.prompt]
        process = await asyncio.create_subprocess_exec(*command, cwd=str(request.cwd), env=request.env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            **({'creationflags': 0x08000000} if os.name == 'nt' else {'start_new_session': True}))
        bind(session)
        emit('activity', 'OpenClaw 原生本地执行；中断后须核对原回执。')
        try:
            stdout, _ = await process.communicate()
        except asyncio.CancelledError:
            if process.returncode is None:
                process.terminate()
            await process.communicate()
            # Process exit is not a native stop acknowledgement.
            raise
        if process.returncode or len(stdout) > 16 * 1024 * 1024:
            raise HarnessError('OpenClaw 未返回明确完成回执，请核对原生会话')
        try:
            outer = json.loads(stdout)
            result = outer.get('result', outer)
            actual = result.get('meta', {}).get('agentMeta', {}).get('sessionId')
            if actual != session:
                raise ValueError('session mismatch')
            run_id = outer.get('runId') or result.get('runId') or result.get('meta', {}).get('runId')
            messages = [row['text'] for row in result.get('payloads', []) if isinstance(row.get('text'), str)]
            meta=result.get('meta', {})
            if not messages or result.get('error') or meta.get('error') or meta.get('aborted') or meta.get('stopReason') in ('error','aborted','length') or any(row.get('isError') for row in result.get('payloads', [])):
                raise ValueError('no completed text')
            if run_id and request.on_native_turn:
                request.on_native_turn(session, str(run_id))
            elif request.on_execution_receipt:
                request.on_execution_receipt({'kind':'openclaw_cli_result','native_session_id':session,
                                              'sha256':hashlib.sha256(stdout).hexdigest()})
        except (ValueError, TypeError, KeyError, AttributeError):
            raise HarnessError('OpenClaw 原生结果缺少会话、回合或完成证据；原回合等待核对') from None
        for message in messages:
            emit('token', message)
