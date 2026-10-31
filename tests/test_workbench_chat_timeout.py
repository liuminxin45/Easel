"""TEMP timeout receipts using the actual chat service and a fake native adapter."""
import asyncio
import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location('chat_timeout_support', Path(__file__).with_name('test_workbench_chat.py'))
_support = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_support)
runtime, commands, service = _support.runtime, _support.commands, _support.service
snapshot, value, completed = _support.snapshot, _support.value, _support.completed

from easel import harnesses
from easel.harnesses.base import HarnessError


@pytest.mark.parametrize('confirmed', [True, False])
def test_timeout_uses_only_confirmed_native_interruption_and_preserves_original(service, confirmed):
    async def scenario():
        chat, adapter = service
        adapter.hold = asyncio.Event()
        adapter.interrupt_ack = confirmed
        chat.timeout = .04
        finished = []
        chat.on_finish = lambda record: finished.append(record) or {'completed': False}
        retained = chat.root / 'outputs' / 'already-saved.png'
        retained.write_bytes(b'original incomplete artifact')
        original = value('timeout-original')
        turn = await chat.submit(original, snapshot=snapshot(chat), actual_prompt='Exact frozen timeout input')
        await completed(chat, turn['id'])
        receipt = chat.get_turn(turn['id'], private=True)
        assert receipt['status'] == ('stopped' if confirmed else 'unknown')
        assert receipt['delivery_state'] == ('interrupted' if confirmed else 'unknown')
        assert receipt['output'] == '真实 '
        assert receipt['message'] == original['message']
        assert receipt['actual_prompt'] == 'Exact frozen timeout input'
        assert receipt['native_id'] == 'actual-native-session'
        assert receipt['native_turn_id'] == 'actual-native-turn-1'
        assert retained.read_bytes() == b'original incomplete artifact'
        assert finished[0]['status'] == receipt['status']
        assert not chat.last('workbench-session')['clean_end']
        pending = chat.history('workbench-session')['session']['pendingTurnId']
        assert pending == (None if confirmed else turn['id'])
        assert [event['event'] for event in chat.read_events(turn['id'])][-2:] == ['error', 'done']
        # Reading and submitting the same identity only return the original
        # receipt. Neither a timeout nor later UI recovery starts another turn.
        again = await chat.submit(original, snapshot=None, actual_prompt='Must not replace original')
        assert again['id'] == turn['id'] and len(adapter.requests) == 1
        assert chat.get_turn(turn['id'], private=True)['actual_prompt'] == 'Exact frozen timeout input'
        await chat.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('mismatch', ['thread', 'turn'])
def test_timeout_rejects_an_interruption_for_a_different_native_identity(service, monkeypatch, mismatch):
    class WrongIdentityAdapter:
        calls = 0
        rejected = False

        async def run(self, request, emit, ask, bind):
            self.calls += 1
            bind('native-original-thread')
            request.on_native_turn('native-original-thread', 'native-original-turn')
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                try:
                    request.on_native_interrupt('other-thread' if mismatch == 'thread' else 'native-original-thread',
                                                'other-turn' if mismatch == 'turn' else 'native-original-turn')
                except HarnessError:
                    self.rejected = True
                raise

    adapter = WrongIdentityAdapter()
    monkeypatch.setattr(harnesses, 'adapter', lambda runtime: adapter)

    async def scenario():
        chat, _ = service
        chat.timeout = .04
        turn = await chat.submit(value('wrong-native-identity'), snapshot=snapshot(chat), actual_prompt='Frozen original')
        await completed(chat, turn['id'])
        receipt = chat.get_turn(turn['id'])
        assert adapter.rejected and adapter.calls == 1
        assert receipt['status'] == 'unknown' and receipt['delivery_state'] == 'unknown'
        assert not receipt.get('interrupt_confirmed')
        assert chat.history('workbench-session')['session']['pendingTurnId'] == turn['id']
        await chat.close()
    asyncio.run(scenario())


def test_service_shutdown_keeps_existing_non_user_cancellation_semantics(service):
    async def scenario():
        chat, adapter = service
        adapter.hold = asyncio.Event()
        turn = await chat.submit(value('shutdown-original'), snapshot=snapshot(chat), actual_prompt='Frozen shutdown input')
        while not adapter.requests:
            await asyncio.sleep(0)
        await chat.close()
        receipt = chat.get_turn(turn['id'])
        assert receipt.get('interrupt_confirmed') is True
        assert receipt['status'] == 'unknown' and receipt['delivery_state'] == 'unknown'
        assert len(adapter.requests) == 1
    asyncio.run(scenario())
