"""Public ingress observation uses public routing and never restarts healthy local work."""
import copy
import json
from pathlib import Path
import socket
import ssl
import tempfile
import unittest
from unittest import mock
import urllib.parse
import urllib.request

from easel_health_control import public_ingress
from easel_health_control.monitor import HEALTH_PATH, Monitor
from easel_health_control.state import StateStore


HOST = 'fixture.ts.net'
URL = 'https://' + HOST + ':8443' + HEALTH_PATH
TOKEN = 'c' * 64
RELEASE = 'workbench-test'


class Response:
    def __init__(self, value, *, status=200, headers=None):
        self.body = json.dumps(value).encode()
        self.status = status
        self.headers = headers or {}
        self.closed = False

    def read(self, size):
        return self.body[:size]

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True


class HealthOpener:
    """Echo only the request nonce, as the actual health endpoint must do."""
    def __init__(self, *, change=None, error=None):
        self.change, self.error = change, error
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        if self.error:
            raise self.error
        headers = {key.lower(): value for key, value in request.header_items()}
        value = {'ok': True, 'nonce': headers['x-workbench-health-nonce'],
                 'release': RELEASE, 'pid': 12}
        if self.change:
            value.update(self.change)
        return Response(value, headers={'X-Workbench-Health': '1'})


class PublicRouteTests(unittest.TestCase):
    def test_doh_filters_magicdns_private_loopback_and_duplicates_without_proxy(self):
        response = Response({'Status': 0, 'Answer': [
            {'type': 1, 'data': '100.108.176.39'},
            {'type': 1, 'data': '127.0.0.1'},
            {'type': 1, 'data': '10.2.3.4'},
            {'type': 1, 'data': '192.168.1.2'},
            {'type': 1, 'data': '169.254.1.2'},
            {'type': 28, 'data': '2606:4700:4700::1111'},
            {'type': 5, 'data': 'different.example'},
            {'type': 1, 'data': '1.1.1.1'},
            {'type': 1, 'data': '1.1.1.1'},
            {'type': 1, 'data': '8.8.8.8'},
            {'type': 1, 'data': '9.9.9.9'},
        ]})
        opener = mock.Mock()
        opener.open.return_value = response
        with mock.patch.object(public_ingress.urllib.request, 'build_opener', return_value=opener) as build:
            self.assertEqual(public_ingress.public_addresses(HOST), ['1.1.1.1', '8.8.8.8'])
        handlers = build.call_args.args
        self.assertEqual(len(handlers), 1)
        self.assertIsInstance(handlers[0], urllib.request.ProxyHandler)
        self.assertEqual(handlers[0].proxies, {})
        request = opener.open.call_args.args[0]
        parsed = urllib.parse.urlsplit(request.full_url)
        self.assertEqual(urllib.parse.parse_qs(parsed.query), {'name': [HOST], 'type': ['A']})
        self.assertNotIn(TOKEN, request.full_url)
        self.assertNotIn('x-workbench-health-token', dict(request.header_items()))
        self.assertTrue(response.closed)

    def test_doh_uses_second_resolver_after_network_failure(self):
        opener = mock.Mock()
        opener.open.side_effect = [OSError('private transport detail'),
            Response({'Status': 0, 'Answer': [{'type': 1, 'data': '8.8.8.8'}]})]
        with mock.patch.object(public_ingress.urllib.request, 'build_opener', return_value=opener):
            self.assertEqual(public_ingress.public_addresses(HOST), ['8.8.8.8'])
        destinations = [urllib.parse.urlsplit(call.args[0].full_url).netloc
                        for call in opener.open.call_args_list]
        self.assertEqual(destinations, ['dns.alidns.com', 'cloudflare-dns.com'])

    def test_all_doh_failures_return_only_a_fixed_failure_reason(self):
        opener = mock.Mock()
        opener.open.side_effect = OSError('secret-detail-' + TOKEN)
        with mock.patch.object(public_ingress.urllib.request, 'build_opener', return_value=opener):
            with self.assertRaisesRegex(OSError, '^public_dns_unavailable$'):
                public_ingress.public_addresses(HOST)

    def test_public_tls_connects_selected_ip_but_authenticates_original_host(self):
        connection = public_ingress.PublicHTTPSConnection(HOST + ':8443', address='1.1.1.1', timeout=1.25)
        context = mock.Mock(spec=ssl.SSLContext)
        connection._context = context
        raw = mock.Mock(spec=socket.socket)
        with mock.patch.object(public_ingress.socket, 'create_connection', return_value=raw) as connect:
            connection.connect()
        connect.assert_called_once_with(('1.1.1.1', 8443), 1.25, None)
        context.wrap_socket.assert_called_once_with(raw, server_hostname=HOST)
        self.assertIs(connection.sock, context.wrap_socket.return_value)

    def test_public_tls_closes_the_raw_socket_if_authentication_fails(self):
        connection = public_ingress.PublicHTTPSConnection(HOST, address='1.1.1.1', port=8443)
        connection._context = mock.Mock(spec=ssl.SSLContext)
        connection._context.wrap_socket.side_effect = ssl.SSLError('certificate mismatch')
        raw = mock.Mock(spec=socket.socket)
        with mock.patch.object(public_ingress.socket, 'create_connection', return_value=raw):
            with self.assertRaises(ssl.SSLError):
                connection.connect()
        raw.close.assert_called_once()

    def test_private_addresses_are_rejected_before_opening_any_socket(self):
        for address in ['100.108.176.39', '127.0.0.1', '10.0.0.1']:
            with self.subTest(address=address):
                connection = public_ingress.PublicHTTPSConnection(HOST, address=address, port=8443)
                with mock.patch.object(public_ingress.socket, 'create_connection') as connect:
                    with self.assertRaisesRegex(OSError, '^public_route_required$'):
                        connection.connect()
                connect.assert_not_called()

    def test_public_opener_has_no_proxy_and_does_not_follow_redirects(self):
        with mock.patch.object(urllib.request, 'getproxies') as getproxies:
            opener = public_ingress.public_opener('1.1.1.1')
        getproxies.assert_not_called()
        redirects = [handler for handler in opener.handlers
                     if isinstance(handler, urllib.request.HTTPRedirectHandler)]
        self.assertEqual(len(redirects), 1)
        self.assertIsNone(redirects[0].redirect_request(None, None, 302, '', {}, 'https://other.example/'))
        self.assertFalse(any(isinstance(handler, urllib.request.ProxyHandler) and handler.proxies
                             for handler in opener.handlers))

    def test_public_probe_uses_the_real_health_validator_on_the_routed_connection(self):
        opener = HealthOpener()
        with mock.patch.object(public_ingress, 'public_opener', return_value=opener) as route:
            result = public_ingress.probe_public_http(URL, TOKEN, RELEASE, resolve=lambda _: ['1.1.1.1'])
        route.assert_called_once_with('1.1.1.1')
        self.assertTrue(result['ok'])
        self.assertEqual(result['pid'], 12)
        self.assertEqual(opener.requests[0][0].full_url, URL)
        self.assertNotIn(TOKEN, json.dumps(result))
        self.assertNotIn('nonce', result)

    def test_bad_nonce_release_or_pid_never_passes_or_retries_as_a_network_failure(self):
        for change in [{'nonce': 'wrong'}, {'release': 'workbench-other'},
                       {'pid': 0}, {'pid': True}, {'pid': '12'}, {'ok': False}]:
            with self.subTest(change=change):
                opener = HealthOpener(change=change)
                with mock.patch.object(public_ingress, 'public_opener', return_value=opener) as route:
                    result = public_ingress.probe_public_http(URL, TOKEN, RELEASE,
                                                             resolve=lambda _: ['1.1.1.1', '8.8.8.8'])
                self.assertFalse(result['ok'])
                self.assertFalse(result['recoverable'])
                self.assertEqual(result['reason'], 'unverified_identity')
                self.assertEqual(route.call_count, 1)
                self.assertNotIn(TOKEN, json.dumps(result))

    def test_network_failure_can_try_second_public_ip_without_replaying_business(self):
        first, second = HealthOpener(error=OSError('private route detail')), HealthOpener()
        with mock.patch.object(public_ingress, 'public_opener', side_effect=[first, second]) as route:
            result = public_ingress.probe_public_http(URL, TOKEN, RELEASE,
                                                     resolve=lambda _: ['1.1.1.1', '8.8.8.8'])
        self.assertTrue(result['ok'])
        self.assertEqual([call.args[0] for call in route.call_args_list], ['1.1.1.1', '8.8.8.8'])
        self.assertEqual(len(first.requests), 1)
        self.assertEqual(len(second.requests), 1)

    def test_dns_failure_does_not_expose_exception_credentials_or_open_health_socket(self):
        def fail(_):
            raise OSError('https://private.example/?token=' + TOKEN)
        with mock.patch.object(public_ingress, 'public_opener') as route:
            result = public_ingress.probe_public_http(URL, TOKEN, RELEASE, resolve=fail)
        self.assertEqual(result['reason'], 'public_dns_unavailable')
        self.assertFalse(result['ok'])
        self.assertFalse(result['recoverable'])
        route.assert_not_called()
        self.assertNotIn(TOKEN, json.dumps(result))
        self.assertNotIn('private.example', json.dumps(result))

    def test_non_ingress_or_redirect_like_health_urls_are_rejected_before_dns(self):
        for url in ['https://other.example:8443' + HEALTH_PATH,
                    URL + '?token=private', URL + '#fragment',
                    'https://user:password@' + HOST + ':8443' + HEALTH_PATH,
                    'https://' + HOST + ':8443/native/']:
            with self.subTest(url=url), mock.patch.object(public_ingress, 'public_opener') as route:
                resolver = mock.Mock(return_value=['1.1.1.1'])
                with self.assertRaises(ValueError):
                    public_ingress.probe_public_http(url, TOKEN, RELEASE, resolve=resolver)
                resolver.assert_not_called()
                route.assert_not_called()


class PublicIngressMonitorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name).resolve()
        app = root / 'application'
        app.mkdir()
        self.store = StateStore(root / 'independent-controller')
        self.now = 1000.0
        self.config = {'app_root': str(app), 'threshold': 1, 'cooldown': 120,
                       'max_restarts': 2, 'startup_grace': 90, 'public_ingress_enabled': True}
        self.inspection = {'schema': 1, 'ownership_verified': True, 'controls_valid': True,
            'busy': False, 'unknown_receipts': False,
            'binding': {'release': RELEASE, 'manifest_sha256': 'a'*64,
                        'native_release': 'native-test', 'native_manifest_sha256': 'b'*64},
            'server': {'pid': 11, 'creation_ticks': '100', 'alive': True, 'age_seconds': 500},
            'manager': {'pid': 21, 'creation_ticks': '200', 'alive': True, 'age_seconds': 500, 'heartbeat_age_seconds': 3},
            'server_member_pids': [11, 12], 'business': {'status': 'healthy', 'ok': True},
            'health_token': TOKEN, 'ingress_origin': 'https://' + HOST + ':8443'}
        self.public = {'ok': True, 'pid': 12, 'seconds': .04, 'status': 200}
        self.public_calls = []
        self.repairs = []

    def transport(self, *_):
        return {'ok': True, 'pid': self.inspection['server_member_pids'][-1], 'seconds': .02, 'status': 200}

    def public_probe(self, *args):
        self.public_calls.append(args)
        return copy.deepcopy(self.public)

    def recover(self, request):
        self.repairs.append(request)
        raise AssertionError('healthy local applications must not be restarted for public routing failures')

    def monitor(self):
        return Monitor(self.config, self.store, inspect_target=lambda: copy.deepcopy(self.inspection),
                       http_probe=self.transport, public_probe=self.public_probe,
                       recovery_bridge=self.recover, clock=lambda: self.now)

    def test_public_failure_is_network_degraded_and_does_not_consume_restart_budget(self):
        self.public = {'ok': False, 'reason': 'connection_or_timeout', 'recoverable': True, 'seconds': 5}
        result = self.monitor().tick(allow_repair=True)
        self.assertEqual(result['decision'], 'network_degraded')
        self.assertFalse(result['observation']['needs_repair'])
        self.assertEqual(self.repairs, [])
        self.assertEqual(self.store.policy()['attempts'], [])

    def test_public_health_from_a_foreign_process_is_rejected_without_restart(self):
        self.public['pid'] = 999
        result = self.monitor().tick(allow_repair=True)
        self.assertEqual(result['decision'], 'network_degraded')
        self.assertFalse(result['observation']['public_ingress']['ok'])
        self.assertEqual(result['observation']['public_ingress']['reason'], 'foreign_public_ingress_pid')
        self.assertEqual(self.repairs, [])

    def test_public_result_is_cached_for_sixty_seconds_and_recovers_after_refresh(self):
        monitor = self.monitor()
        self.assertEqual(monitor.tick(allow_repair=True)['decision'], 'healthy')
        self.public = {'ok': False, 'reason': 'connection_or_timeout', 'recoverable': True, 'seconds': 5}
        self.now += 59
        self.assertEqual(monitor.tick(allow_repair=True)['decision'], 'healthy')
        self.assertEqual(len(self.public_calls), 1)
        self.now += 1
        self.assertEqual(monitor.tick(allow_repair=True)['decision'], 'network_degraded')
        self.public = {'ok': True, 'pid': 12, 'seconds': .03, 'status': 200}
        self.now += 60
        self.assertEqual(monitor.tick(allow_repair=True)['decision'], 'healthy')
        self.assertEqual(len(self.public_calls), 3)
        self.assertEqual(self.repairs, [])

    def test_release_change_invalidates_public_result_before_the_cache_expires(self):
        monitor = self.monitor()
        monitor.tick()
        self.inspection['binding']['release'] = 'workbench-new-release'
        self.now += 1
        monitor.tick()
        self.assertEqual(len(self.public_calls), 2)
        self.assertEqual(self.public_calls[-1][2], 'workbench-new-release')

    def test_new_server_pid_invalidates_a_cached_success(self):
        monitor = self.monitor()
        monitor.tick()
        self.inspection['server_member_pids'] = [31, 32]
        self.inspection['server'].update(pid=31, creation_ticks='300')
        self.public['pid'] = 32
        self.now += 1
        result = monitor.tick()
        self.assertEqual(len(self.public_calls), 2)
        self.assertEqual(result['observation']['public_ingress']['pid'], 32)

    def test_changed_manifest_invalidates_the_cached_result_for_the_same_release_name(self):
        monitor = self.monitor()
        monitor.tick()
        self.inspection['binding']['manifest_sha256'] = 'd' * 64
        self.now += 1
        monitor.tick()
        self.assertEqual(len(self.public_calls), 2)

    def test_new_server_pid_also_invalidates_a_cached_failure(self):
        self.public = {'ok': False, 'reason': 'connection_or_timeout', 'recoverable': True, 'seconds': 5}
        monitor = self.monitor()
        self.assertEqual(monitor.tick()['decision'], 'network_degraded')
        self.inspection['server_member_pids'] = [31, 32]
        self.inspection['server'].update(pid=31, creation_ticks='300')
        self.public = {'ok': True, 'pid': 32, 'seconds': .02, 'status': 200}
        self.now += 1
        result = monitor.tick()
        self.assertEqual(len(self.public_calls), 2)
        self.assertEqual(result['decision'], 'healthy')

    def test_public_probe_is_not_run_when_not_explicitly_enabled(self):
        self.config['public_ingress_enabled'] = False
        result = self.monitor().tick()
        self.assertEqual(result['decision'], 'healthy')
        self.assertNotIn('public_ingress', result['observation'])
        self.assertEqual(self.public_calls, [])


if __name__ == '__main__':
    unittest.main()
