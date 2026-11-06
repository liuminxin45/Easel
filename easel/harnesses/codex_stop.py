"""Cooperative cancellation on the existing native channel, never a replay."""
from __future__ import annotations

import asyncio

from .base import HarnessError

STOP_GRACE_SECONDS = 15


async def prepare(awaitable, stop_event):
    """Only preparation is cancellable without a native execution identity."""
    if stop_event is None:
        return await awaitable
    task = asyncio.ensure_future(awaitable)
    stop = asyncio.create_task(stop_event.wait())
    try:
        await asyncio.wait((task, stop), return_when=asyncio.FIRST_COMPLETED)
        if stop_event.is_set():
            raise asyncio.CancelledError
        return await task
    finally:
        stop.cancel()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, stop, return_exceptions=True)


async def dispatch(awaitable, stop_event):
    """Keep a possibly sent start alive for its ID, but never wait forever."""
    if stop_event is None:
        return await awaitable
    task=asyncio.ensure_future(awaitable)
    stop=asyncio.create_task(stop_event.wait())
    try:
        await asyncio.wait((task,stop),return_when=asyncio.FIRST_COMPLETED)
        if task.done():return await task
        try:return await asyncio.wait_for(asyncio.shield(task),STOP_GRACE_SECONDS)
        except asyncio.TimeoutError:
            raise HarnessError('停止时未取得原生启动回执；关闭本地连接，保留未知结果') from None
    finally:
        for pending in (task,stop):
            if not pending.done():pending.cancel()
        await asyncio.gather(task,stop,return_exceptions=True)


async def finish(rpc, completion, request, thread_id, turn_id, notify):
    """A terminal notification outranks an interrupt ACK or its failure."""
    waiter = asyncio.create_task(rpc.wait_notification(completion))
    stop = asyncio.create_task(request.stop_event.wait()) if request.stop_event else None
    interrupt = None
    try:
        try:
            if stop is None:
                try:
                    return await asyncio.shield(waiter)
                except asyncio.CancelledError:
                    # Callers without cooperative stop retain the original API.
                    try:
                        await rpc.call("turn/interrupt", {"threadId": thread_id, "turnId": turn_id}, timeout=2)
                    except HarnessError:
                        pass
                    else:
                        if request.on_native_interrupt:
                            request.on_native_interrupt(thread_id, turn_id)
                    raise
            await asyncio.wait((waiter, stop), return_when=asyncio.FIRST_COMPLETED)
            if waiter.done():
                return await waiter
        except asyncio.CancelledError:
            # Shutdown/timeout still uses the same exact-turn stop protocol.
            if stop is None:
                raise
        interrupt = asyncio.create_task(rpc.call(
            "turn/interrupt", {"threadId": thread_id, "turnId": turn_id},
            timeout=STOP_GRACE_SECONDS))
        done, _ = await asyncio.wait((waiter,), timeout=STOP_GRACE_SECONDS)
        if not done:
            # A missed notification may still have an authoritative native turn.
            try:
                result = await rpc.call("thread/read", {"threadId": thread_id, "includeTurns": True}, timeout=3)
                for turn in (result.get("thread") or {}).get("turns") or []:
                    if turn.get("id") == turn_id and turn.get("status") in ("completed", "interrupted", "failed"):
                        notify("turn/completed", {"threadId": thread_id, "turn": turn})
            except HarnessError:
                pass
        if completion.done():
            return completion.result()
        if interrupt.done() and not interrupt.cancelled():
            error = interrupt.exception()
            if error and request.on_execution_receipt:
                request.on_execution_receipt({"kind": "codex_stop_error", "thread_id": thread_id,
                                              "turn_id": turn_id, "error": str(error)[:1000]})
        # connection() retires the owned transport on this exception. Its exit
        # receipt is separate from the still unknown native outcome.
        raise HarnessError("停止等待已结束，正在关闭本地执行连接；原生结果待核对")
    finally:
        for task in (stop, interrupt, waiter):
            if task and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in (stop, interrupt, waiter) if task), return_exceptions=True)
