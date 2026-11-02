from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from easel_health_control.monitor import probe_http
from easel_health_control.state import StateError, StateStore


class HttpAndStateTests(unittest.TestCase):
    def setUp(self):
        owner = self
        self.mode, self.requests = 'valid', []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                owner.requests.append(self.path)
                if owner.mode == 'slow': time.sleep(.08)
                if owner.mode == 'redirect':
                    self.send_response(302)
                    self.send_header('Location', '/must-not-follow')
                    self.end_headers()
                    return
                data = {'ok': True, 'pid': 42, 'release': 'workbench-test',
                        'nonce': self.headers.get('X-Workbench-Health-Nonce'), 'private_body': 'never-return-this'}
                if owner.mode == 'bad_nonce': data['nonce'] = 'untrusted'
                raw = json.dumps(data).encode()
                self.send_response(200)
                self.send_header('X-Workbench-Health', '1')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                try: self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError): pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.url = 'http://127.0.0.1:' + str(self.server.server_port) + '/_workbench/health'

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def test_real_nonce_http_probe_discards_raw_body(self):
        result = probe_http(self.url, 'c'*64, 'workbench-test', 1)
        self.assertTrue(result['ok'])
        self.assertEqual(result['pid'], 42)
        self.assertNotIn('private_body', result)
        self.assertNotIn('never-return-this', json.dumps(result))

    def test_bad_nonce_does_not_authorize_a_repair(self):
        self.mode = 'bad_nonce'
        result = probe_http(self.url, 'c'*64, 'workbench-test', 1)
        self.assertFalse(result['ok'])
        self.assertFalse(result['recoverable'])

    def test_slow_endpoint_has_a_real_bounded_timeout(self):
        self.mode = 'slow'
        start = time.monotonic()
        result = probe_http(self.url, 'c'*64, 'workbench-test', .015)
        self.assertFalse(result['ok'])
        self.assertTrue(result['recoverable'])
        self.assertLess(time.monotonic()-start, .5)

    def test_redirect_is_not_followed(self):
        self.mode = 'redirect'
        result = probe_http(self.url, 'c'*64, 'workbench-test', 1)
        self.assertEqual(result['status'], 302)
        self.assertFalse(result['recoverable'])
        self.assertEqual(self.requests, ['/_workbench/health'])

    def test_state_path_escape_and_overlapping_controller_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = StateStore(temporary)
            with self.assertRaises(StateError): store.write('../application.json', {})
            with store.lock():
                with self.assertRaises(OSError):
                    with StateStore(temporary).lock(): self.fail('second controller entered')

    def test_core_imports_without_application_or_nonstdlib_dependencies(self):
        source = Path(__file__).resolve().parents[1]
        code = 'import sys;sys.path.insert(0,' + repr(str(source)) + ');from easel_health_control import monitor,policy,state;assert not any(n=="easel" or n.startswith("easel_workbench") for n in sys.modules)'
        result = subprocess.run([sys.executable, '-I', '-c', code], cwd=tempfile.gettempdir(),
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__': unittest.main()
