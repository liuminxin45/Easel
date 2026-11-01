"""Run blocking service work without blocking its caller's event loop."""
import asyncio
import inspect


async def run_sync(function, *args, **kwargs):
    """Cancellation waits for the thread before releasing caller-owned locks.

    Cancelling an HTTP coroutine cannot stop SQLite or filesystem work already
    running in a thread. Drain that work, consume its exception, then preserve
    cancellation; never let a second operation overlap the first accidentally.
    """
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except BaseException:
                break
        if task.done() and not task.cancelled():
            if task.exception() is None:
                result = task.result()
                if inspect.iscoroutine(result):
                    result.close()
        raise
