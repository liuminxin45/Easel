import copy
import json
from pathlib import Path
import tempfile
import unittest

from easel_health_control.monitor import Monitor
from easel_health_control.state import StateStore


class MonitorFaultTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.app = self.root / 'application'
        self.app.mkdir()
        self.store = StateStore(self.root / 'independent-runtime')
        self.clock = [1000.0]
        self.calls = []
        self.config = {'app_root': str(self.app), 'threshold': 1, 'cooldown': 120,
                       'max_restarts': 2, 'startup_grace': 90}
        self.inspection = {'schema': 1, 'app_present': True, 'ownership_verified': True, 'controls_valid': True,
            'busy': False, 'unknown_receipts': False, 'retained_audited_unknown_count': 3,
            'binding': {'release': 'workbench-test', 'manifest_sha256': 'a'*64,
                        'native_release': 'native-test', 'native_manifest_sha256': 'b'*64},
            'server': {'pid': 11, 'creation_ticks': '100', 'alive': True, 'age_seconds': 500},
            'manager': {'pid': 21, 'creation_ticks': '200', 'alive': True, 'age_seconds': 500, 'heartbeat_age_seconds': 3},
            'server_member_pids': [11, 12], 'business': {'status': 'healthy', 'ok': True},
            'health_token': 'c'*64, 'ingress_origin': 'https://fixture.ts.net:8443'}
        self.local = {'ok': False, 'recoverable': True, 'reason': 'connection_or_timeout', 'seconds': 3}
        self.ingress = {'ok': False, 'recoverable': True, 'reason': 'connection_or_timeout', 'seconds': 5}

    def probe(self, url, *_):
        return copy.deepcopy(self.local if url.startswith('http://127.0.0.1') else self.ingress)

    def recover(self, request):
        # The budget and attempted receipt must already be durable when the
        # only allowed effect is handed off to the bridge.
        self.assertEqual(self.store.policy()['pending_operation'], request['operation_id'])
        self.assertEqual(self.store.read('repair-'+request['operation_id']+'.json')['phase'], 'attempted')
        self.calls.append(request)
        return {**request, 'outcome': 'server_restart_requested' if request['action'] == 'recover_server' else 'manager_restart_requested'}

    def monitor(self, **ports):
        return Monitor(self.config, self.store, inspect_target=ports.get('inspect_target', lambda: copy.deepcopy(self.inspection)),
            http_probe=self.probe, recovery_bridge=ports.get('recovery_bridge', self.recover), clock=lambda: self.clock[0])

    def healthy(self):
        self.local = {'ok': True, 'pid': 12, 'seconds': .02, 'status': 200}
        self.ingress = {'ok': True, 'pid': 12, 'seconds': .04, 'status': 200}

    def test_application_missing_still_has_independent_status(self):
        self.app.rmdir()
        result = self.monitor().tick(allow_repair=True)
        self.assertEqual(result['decision'], 'app_missing')
        self.assertEqual(self.store.read('status.json')['observation']['status'], 'app_missing')
        self.assertEqual(self.calls, [])

    def test_app_down_requests_only_fenced_server_recovery(self):
        result = self.monitor().tick(allow_repair=True)
        self.assertEqual(result['decision'], 'repair_acknowledged')
        self.assertEqual(self.calls[0]['action'], 'recover_server')
        self.assertEqual(self.calls[0]['expected_identity'], {'pid': 11, 'creation_ticks': '100'})
        self.assertEqual(self.store.policy()['attempts'], [1000.0])
        self.assertEqual(self.inspection['retained_audited_unknown_count'], 3)

    def test_monitor_defaults_to_no_actual_repair(self):
        result = self.monitor().tick()
        self.assertEqual(result['decision'], 'recovery_candidate')
        self.assertEqual(self.calls, [])
        self.assertEqual(self.store.policy()['attempts'], [])

    def test_endpoint_slow_and_tailnet_failure_never_restart_local(self):
        self.healthy()
        self.local['seconds'] = 2.5
        self.assertEqual(self.monitor().tick(allow_repair=True)['decision'], 'endpoint_slow')
        self.local['seconds'] = .02
        self.ingress = {'ok': False, 'recoverable': True, 'reason': 'connection_or_timeout', 'seconds': 5}
        self.assertEqual(self.monitor().tick(allow_repair=True)['decision'], 'network_degraded')
        self.assertEqual(self.calls, [])

    def test_stale_sources_and_upstream_500_are_business_provider_degradation(self):
        self.healthy()
        self.inspection['business'] = {'status': 'degraded', 'ok': False}
        self.assertEqual(self.monitor().tick(allow_repair=True)['decision'], 'business_degraded')
        self.inspection['business']['external_provider'] = True
        self.assertEqual(self.monitor().tick(allow_repair=True)['decision'], 'provider_degraded')
        self.inspection['business'] = {'status': 'healthy', 'ok': True}
        self.assertEqual(self.monitor().tick(allow_repair=True)['decision'], 'healthy')
        self.assertEqual(self.calls, [])

    def test_unverified_http_500_does_not_authorize_restart(self):
        self.local = {'ok': False, 'status': 500, 'recoverable': False, 'reason': 'unverified_http'}
        self.assertEqual(self.monitor().tick(allow_repair=True)['decision'], 'deferred')
        self.assertEqual(self.calls, [])

    def test_http_hung_but_busy_or_unknown_receipt_is_never_restarted(self):
        for field in ('busy', 'unknown_receipts'):
            with self.subTest(field=field):
                self.inspection[field] = True
                self.assertEqual(self.monitor().tick(allow_repair=True)['decision'], 'deferred')
                self.inspection[field] = False
        self.assertEqual(self.calls, [])

    def test_pid_reuse_between_observation_and_fence_defers_without_budget(self):
        rows = [copy.deepcopy(self.inspection), copy.deepcopy(self.inspection)]
        rows[1]['server']['creation_ticks'] = '101'
        result = self.monitor(inspect_target=lambda: rows.pop(0)).tick(allow_repair=True)
        self.assertEqual(result['decision'], 'repair_deferred')
        self.assertEqual(self.calls, [])
        self.assertEqual(self.store.policy()['attempts'], [])

    def test_release_change_during_fence_defers(self):
        rows = [copy.deepcopy(self.inspection), copy.deepcopy(self.inspection)]
        rows[1]['binding']['manifest_sha256'] = 'd'*64
        self.assertEqual(self.monitor(inspect_target=lambda: rows.pop(0)).tick(allow_repair=True)['decision'], 'repair_deferred')
        self.assertEqual(self.calls, [])

    def test_cooldown_and_restart_budget_survive_controller_restart_and_health(self):
        self.monitor().tick(allow_repair=True)
        self.clock[0] += 10
        self.assertEqual(self.monitor().tick(allow_repair=True)['decision'], 'cooling_down')
        self.clock[0] += 120
        self.monitor().tick(allow_repair=True)
        self.healthy()
        self.assertEqual(self.monitor().tick(allow_repair=True)['decision'], 'healthy')
        self.local = {'ok': False, 'recoverable': True, 'reason': 'connection_or_timeout'}
        self.clock[0] += 120
        self.assertEqual(self.monitor().tick(allow_repair=True)['decision'], 'circuit_open')
        self.assertEqual(len(self.calls), 2)

    def test_consecutive_failure_threshold_resets_after_a_good_probe(self):
        self.config['threshold'] = 3
        monitor = self.monitor()
        self.assertEqual(monitor.tick(allow_repair=True)['decision'], 'waiting')
        self.healthy()
        self.assertEqual(monitor.tick(allow_repair=True)['decision'], 'healthy')
        self.local = {'ok': False, 'recoverable': True}
        self.assertEqual(monitor.tick(allow_repair=True)['decision'], 'waiting')
        self.assertEqual(monitor.tick(allow_repair=True)['decision'], 'waiting')
        self.assertEqual(monitor.tick(allow_repair=True)['decision'], 'repair_acknowledged')
        self.assertEqual(len(self.calls), 1)

    def test_unknown_repair_receipt_is_not_replayed_after_controller_restart(self):
        def lost(request):
            self.calls.append(request)
            raise TimeoutError('never persist this raw credential URL')
        self.assertEqual(self.monitor(recovery_bridge=lost).tick(allow_repair=True)['decision'], 'repair_receipt_unknown')
        self.clock[0] += 5000
        self.assertEqual(self.monitor().tick(allow_repair=True)['decision'], 'receipt_unknown')
        self.assertEqual(len(self.calls), 1)

    def test_corrupt_deleted_or_truncated_policy_never_gets_a_new_budget(self):
        self.monitor().tick(allow_repair=True)
        self.store.path('policy.json').write_text('{broken', encoding='utf-8')
        self.assertEqual(self.monitor().tick(allow_repair=True)['decision'], 'invalid_state')
        self.assertEqual(self.monitor().tick(allow_repair=True)['decision'], 'invalid_state')
        self.store.path('policy.json').unlink()
        self.assertEqual(self.monitor().tick(allow_repair=True)['decision'], 'invalid_state')
        self.assertEqual(len(self.calls), 1)

    def test_clock_rollback_never_authorizes_a_repair(self):
        self.monitor().tick()
        self.clock[0] -= 20
        self.assertEqual(self.monitor().tick(allow_repair=True)['decision'], 'clock_rollback')
        self.assertEqual(self.calls, [])

    def test_missing_manager_can_only_request_verified_os_task_start(self):
        self.inspection['manager'] = {'alive': False}
        self.inspection['manager_task_verified'] = True
        result = self.monitor().tick(allow_repair=True)
        self.assertEqual(result['decision'], 'repair_acknowledged')
        self.assertEqual(self.calls[0]['action'], 'restart_manager')
        self.assertEqual(self.calls[0]['expected_identity'], {'pid': None, 'creation_ticks': None})

    def test_missing_server_waits_for_live_manager_without_null_identity_kill(self):
        self.inspection['server'] = {'alive': False, 'pid': None, 'creation_ticks': None}
        result = self.monitor().tick(allow_repair=True)
        self.assertEqual(result['decision'], 'server_missing')
        self.assertEqual(result['observation']['blocked_reason'], 'waiting_for_manager')
        self.assertEqual(self.calls, [])

    def test_performance_degradation_is_visible_but_never_restarts_a_server(self):
        self.healthy()
        self.inspection['performance'] = {'status': 'degraded', 'slow_count': 4, 'db_copy_bytes': 512000,
            'db_busy_count': 2, 'max_write_tx_ms': 1500.1, 'raw_query': 'private', 'bad': float('nan')}
        result = self.monitor().tick(allow_repair=True)
        self.assertEqual(result['decision'], 'performance_degraded')
        self.assertEqual(result['observation']['performance']['db_busy_count'], 2)
        self.assertNotIn('private', json.dumps(result))
        self.assertEqual(self.calls, [])

    def test_foreign_health_pid_and_unowned_process_never_restart(self):
        self.healthy()
        self.local['pid'] = 999
        self.assertEqual(self.monitor().tick(allow_repair=True)['decision'], 'deferred')
        self.inspection['ownership_verified'] = False
        self.local = {'ok': False, 'recoverable': True}
        self.assertEqual(self.monitor().tick(allow_repair=True)['decision'], 'ownership_unverified')
        self.assertEqual(self.calls, [])

    def test_no_application_data_or_health_token_is_persisted(self):
        self.monitor().tick(allow_repair=True)
        raw = '\n'.join(path.read_text(encoding='utf-8') for path in self.store.root.glob('*.json*'))
        self.assertNotIn('c'*64, raw)
        self.assertEqual(list(self.app.iterdir()), [])

    def test_state_cannot_live_under_the_application(self):
        with self.assertRaisesRegex(ValueError, 'outside_application'):
            Monitor(self.config, StateStore(self.app/'state'), inspect_target=lambda: self.inspection)


if __name__ == '__main__': unittest.main()
