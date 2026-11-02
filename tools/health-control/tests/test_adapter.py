import json
from pathlib import Path
import tempfile
import time
import unittest

from easel_health_control.adapter import journal_performance, performance


class PerformanceReaderTests(unittest.TestCase):
    def test_finished_old_slow_request_does_not_remain_a_current_alarm(self):
        result = performance({'recent': [{'at': time.time()-601, 'duration_ms': 99000, 'db_copy_bytes': 400000000}]})
        self.assertEqual(result['status'], 'healthy')
        self.assertEqual(result['db_copy_bytes'], 0)

    def test_current_real_copy_and_write_lock_are_visible_without_payload(self):
        result = performance({'recent': [{'at': time.time(), 'db_copy_bytes': 400000000,
            'sql': 'secret sql', 'body': 'private prompt'}], 'writers': [{'write_tx_ms': 3000}]})
        self.assertEqual(result['status'], 'degraded')
        self.assertEqual(result['max_write_tx_ms'], 3000)
        self.assertNotIn('secret', json.dumps(result))

    def test_worker_journal_pairs_writes_and_rejects_foreign_pid_and_release(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs = root/'data/logs/toolbox'
            logs.mkdir(parents=True)
            def event(at, kind, ref='a', **extra):
                return {'at': at, 'event': kind, 'pid': 9, 'release': 'workbench-test', 'resource_ref': ref, **extra}
            rows = [event(90, 'database_write_started'), event(91, 'database_write_finished', write_tx_ms=1000),
                event(92, 'database_write_started', 'b'), event(93, 'database_write_started', 'c', pid=8),
                event(94, 'database_write_started', 'd', release='workbench-old')]
            (logs/'worker-2026110303-test-1.jsonl').write_text('\n'.join(map(json.dumps, rows)), encoding='utf-8')
            result = journal_performance(root, {'binding': {'release': 'workbench-test'}, 'role_member_pids': [9]}, now=100)
            self.assertEqual(result['max_write_tx_ms'], 8000)
            self.assertEqual(result['status'], 'degraded')


if __name__ == '__main__': unittest.main()
