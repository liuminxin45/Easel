"""Codex native app-server adapter; credentials remain in Codex."""
from __future__ import annotations

import asyncio
from pathlib import Path

from easel import __version__

from .base import Descriptor, HarnessError, RunRequest
from .commands import base_command
from .permissions import can_auto_approve
from .rpc import connection
from .workspace import harness_instructions


class CodexAdapter:
    descriptor = Descriptor("codex", "Codex", "app-server", "npm install -g @openai/codex；codex login")

    async def run(self, request: RunRequest, emit, ask, bind):
        if request.sandbox not in ("read-only", "workspace-write"):
            raise HarnessError("Codex 只允许只读或工作区写入权限")
        if request.reasoning_effort is not None and (not isinstance(request.reasoning_effort,str) or not request.reasoning_effort.strip()):
            raise HarnessError('推理强度必须为明确的原生字符串')
        if request.output_schema is not None and not isinstance(request.output_schema,dict):
            raise HarnessError('结构化输出合同必须为对象')
        if request.input_images is not None and (not isinstance(request.input_images,tuple) or any(not isinstance(path,str) or not Path(path).is_absolute() or not Path(path).is_file() for path in request.input_images)):
            raise HarnessError('图片输入必须为已取得的绝对文件路径')
        if request.ephemeral is not None and (type(request.ephemeral) is not bool or request.native_id):
            raise HarnessError('临时会话选项仅适用于新建原生会话')
        completion = asyncio.get_running_loop().create_future()
        thread_id = request.native_id
        turn_id = ""
        streamed: set[str] = set()

        def notify(method, params):
            def _thread_scoped() -> bool:
                # 无 threadId/turnId 的是全局事件（连接级/认证失败常在 turn/start 前发出）；
                # 带 id 的必须匹配本会话。放行判定独立于 turn_id 是否已闩锁。
                if params.get("threadId") is None and params.get("turnId") is None:
                    return True
                return bool(turn_id) and params.get("threadId") == thread_id \
                    and params.get("turnId", turn_id) == turn_id

            # 致命 error 事件常不带 thread 上下文（如 turn/start 前的认证失败）；
            # 放在 id 过滤之前处理，否则只能等外层 wait_for 超时（30min+）才报错。
            if method == "error":
                if params.get("willRetry", False) or not _thread_scoped():
                    return
                if not completion.done():
                    completion.set_exception(HarnessError("Codex 执行失败，请检查原生登录与模型配置"))
                return

            if not turn_id or params.get("threadId") != thread_id or params.get("turnId", turn_id) != turn_id:
                return
            if method == "item/agentMessage/delta":
                streamed.add(params.get("itemId", ""))
                emit("token", params.get("delta", ""))
            elif method in ("item/reasoning/summaryTextDelta", "item/reasoning/textDelta"):
                emit("thinking", params.get("delta", ""))
            elif method == "item/started":
                item = params.get("item") or {}
                if item.get("type") not in ("agentMessage", "reasoning", "userMessage"):
                    emit("activity", f"工具：{item.get('type', 'tool')}")
            elif method == "item/completed":
                item = params.get("item") or {}
                if item.get("type") == "agentMessage":
                    if request.on_agent_message is not None:
                        request.on_agent_message(thread_id, turn_id, dict(item))
                    if item.get("id") not in streamed:
                        emit("token", item.get("text", ""))
            elif method == "turn/completed":
                turn = params.get("turn") or {}
                if turn.get("id") != turn_id or completion.done():
                    return
                if request.on_agent_message is not None:
                    for item in turn.get("items") or []:
                        if item.get("type") == "agentMessage":
                            request.on_agent_message(thread_id, turn_id, dict(item))
                if turn.get("status") == "completed":
                    completion.set_result(None)
                else:
                    error = turn.get("error") or {}
                    completion.set_exception(HarnessError(
                        str(error.get("message") or f"Codex 本轮未完成：{turn.get('status')}")))

        async def respond(method, params):
            if params.get("threadId") != thread_id or (
                    turn_id and params.get("turnId", turn_id) != turn_id):
                raise HarnessError("不属于当前会话的请求")
            if method in ("item/commandExecution/requestApproval", "item/fileChange/requestApproval"):
                if can_auto_approve(method, params, request):
                    emit("activity", "Codex：已自动通过普通操作授权")
                    return {"decision": "accept"}
                detail = params.get("command") or params.get("reason") or params.get("itemId", "")
                answers = await ask([{
                    "questionId": "permission", "header": "执行授权",
                    "question": f"Codex 请求额外权限（仅本次）：{str(detail)[:3000]}" + (
                        "\n此操作不属于可自动批准的普通操作，请确认风险。" if request.codex_auto_approve else ""),
                    "options": [{"label": "允许本次"}, {"label": "拒绝"}],
                }])
                return {"decision": "accept" if answers.get("permission") == ["允许本次"] else "decline"}
            if method == "item/tool/requestUserInput":
                questions = params.get("questions") or []
                if any(question.get("isSecret") for question in questions):
                    raise HarnessError("请在终端完成敏感凭证输入")
                normalized = [{**question, "questionId": question["id"]} for question in questions]
                answers = await ask(normalized)
                return {"answers": {key: {"answers": value} for key, value in answers.items()}}
            raise HarnessError("不支持的 Codex 客户端请求")

        command = list(request.command) if request.command else base_command("codex") + ["app-server"]
        async with connection(request, command, notify, respond) as rpc:
            if rpc.initialized is None:
                rpc.initialized = await rpc.call("initialize", {
                    "clientInfo": {"name": "easel", "version": __version__},
                    "capabilities": {"experimentalApi": True}})
                await rpc.send({"method": "initialized"})
            options = {"cwd": str(request.cwd), "approvalPolicy": "on-request",
                       "sandbox": request.sandbox,
                       "developerInstructions": harness_instructions(request)}
            if request.model:
                options["model"] = request.model
            if request.ephemeral is not None:
                options['ephemeral']=request.ephemeral
            if thread_id and rpc.native_id == thread_id:
                result = {"thread": {"id": thread_id}}
            elif thread_id:
                result = await rpc.call("thread/resume", {**options, "threadId": thread_id})
            else:
                result = await rpc.call("thread/start", options)
            resumed_id = (result.get("thread") or {}).get("id", "")
            if request.native_id and resumed_id != request.native_id:
                raise HarnessError("Codex 返回了不同的原生会话 ID，不会替换已有历史")
            thread_id = resumed_id
            if not thread_id:
                raise HarnessError("Codex 未返回原生会话 ID")
            bind(thread_id)
            rpc.native_id = thread_id
            policy = {"type": "readOnly"} if request.sandbox == "read-only" else {
                "type": "workspaceWrite", "writableRoots": [str(request.cwd)],
                "networkAccess": False}
            params = {"threadId": thread_id, "input": [{"type": "text", "text": request.prompt}],
                      "approvalPolicy": "on-request", "sandboxPolicy": policy}
            if request.model:
                params["model"] = request.model
            if request.input_images is not None:
                params['input'].extend({'type':'localImage','path':path} for path in request.input_images)
            if request.reasoning_effort is not None:
                params['effort']=request.reasoning_effort
            if request.output_schema is not None:
                params['outputSchema']=request.output_schema
            early: list[tuple[str, dict]] = []
            original_notify = rpc.notify
            rpc.notify = lambda method, data: early.append((method, data))
            result = await rpc.call("turn/start", params)
            turn_id = (result.get("turn") or {}).get("id", "")
            if not turn_id:
                raise HarnessError("Codex 未返回本轮 ID")
            if request.on_native_turn is not None:
                request.on_native_turn(thread_id, turn_id)
            rpc.notify = original_notify
            for method, data in early:
                notify(method, data)
            try:
                await rpc.wait_notification(completion)
            except asyncio.CancelledError:
                try:
                    await rpc.call("turn/interrupt", {"threadId": thread_id, "turnId": turn_id}, timeout=2)
                except HarnessError:
                    pass
                else:
                    if request.on_native_interrupt is not None:
                        request.on_native_interrupt(thread_id, turn_id)
                raise
            finally:
                if completion.done() and not completion.cancelled():
                    completion.exception()
