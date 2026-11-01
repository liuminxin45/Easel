import asyncio
import inspect
import threading

import pytest

from easel.web_services.concurrency import run_sync
from easel.web_services.planning import create_planning_context


def test_cancel_waits_for_real_thread_and_closes_unconsumed_coroutine():
    async def scenario():
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        async def result():
            return 1
        coroutine = result()
        def operation():
            started.set()
            release.wait(3)
            finished.set()
            return coroutine
        task = asyncio.create_task(run_sync(operation))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and not finished.is_set()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()
        assert inspect.getcoroutinestate(coroutine) == inspect.CORO_CLOSED
    asyncio.run(scenario())


@pytest.mark.parametrize('kind', ['ideas', 'schedule'])
def test_planning_slow_storage_does_not_block_event_loop(tmp_path, kind):
    async def scenario():
        started, release = threading.Event(), threading.Event()
        def slow_read():
            started.set()
            assert release.wait(3)
            return []
        planning = create_planning_context(tmp_path, **{'read_' + kind: slow_read})
        task = asyncio.create_task(getattr(planning, 'api_' + kind + '_list')())
        try:
            assert await asyncio.to_thread(started.wait, 2)
            assert not task.done(), 'Storage blocked the event loop until the operation finished'
            # A separate request/heartbeat can run while this read is pending.
            assert await asyncio.wait_for(asyncio.sleep(0, result='responsive'), 1) == 'responsive'
        finally:
            release.set()
        assert await task == []
    asyncio.run(scenario())


def test_concurrent_official_idea_writes_keep_every_record(tmp_path):
    async def scenario():
        planning = create_planning_context(tmp_path)
        created = await asyncio.gather(*(planning.api_ideas_create(planning.IdeaItem(title=str(i))) for i in range(16)))
        stored = await planning.api_ideas_list()
        assert {x['id'] for x in stored} == {x['id'] for x in created}
        assert len(stored) == 16
    asyncio.run(scenario())
