import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

from easel_health_control.cli import reconcile_pending
from easel_health_control.policy import initial
from easel_health_control.state import StateStore


class ReceiptTests(unittest.TestCase):
    def test_matching_persisted_original_completion_resolves_lost_ack_without_replay(self):
        with tempfile.TemporaryDirectory() as temporary:
            store=StateStore(temporary);operation='a'*32
            request={'operation_id':operation,'action':'recover_server','binding':{'release':'workbench-test'}}
            store.write('repair-'+operation+'.json',{'request':request,'phase':'unknown'})
            state=initial(1800);state.update(pending_operation=operation,attempts=[100],last_attempt=100,observed_at=101)
            store.save_policy(state)
            calls=[]
            def original(value):
                calls.append(value);return {**value,'status':'receipt_confirmed','outcome':'server_restart_requested'}
            adapter=SimpleNamespace(reconcile=original)
            reconcile_pending(adapter,store)
            self.assertIsNone(store.policy()['pending_operation'])
            self.assertEqual(store.policy()['attempts'],[100])
            self.assertEqual(len(calls),1)
            self.assertEqual(store.read('repair-'+operation+'.json')['phase'],'acknowledged')

    def test_unconfirmed_original_does_not_clear_pending_or_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            store=StateStore(temporary);operation='a'*32
            store.write('repair-'+operation+'.json',{'request':{'operation_id':operation},'phase':'unknown'})
            state=initial(1800);state['pending_operation']=operation;store.save_policy(state)
            reconcile_pending(SimpleNamespace(reconcile=lambda _: {'status':'fence_absent'}),store)
            self.assertEqual(store.policy()['pending_operation'],operation)
