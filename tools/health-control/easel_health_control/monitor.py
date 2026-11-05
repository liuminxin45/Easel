"""Independent stdlib-only observation and narrowly fenced recovery requests.

The inspector and recovery bridge are injected ports, not application imports.
The bridge must repeat all ownership/idle gates under its own process locks.
"""
import copy
import json
import os
from pathlib import Path
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .policy import assess, consume, number
from .usage import project as usage_projection
from .content_library import project as library_projection

HEALTH_PATH = '/_workbench/health'


def binding(value):
    if not isinstance(value, dict): raise ValueError('invalid_binding')
    result = {}
    for key, prefix in (('release', 'workbench'), ('native_release', 'native')):
        if not re.fullmatch(prefix + r'-[A-Za-z0-9_-]+', str(value.get(key, ''))):
            raise ValueError('invalid_binding')
        result[key] = value[key]
    for key in ('manifest_sha256', 'native_manifest_sha256'):
        if not re.fullmatch(r'[a-f0-9]{64}', str(value.get(key, ''))): raise ValueError('invalid_binding')
        result[key] = value[key]
    return result


def identity(row):
    if (not isinstance(row, dict) or type(row.get('pid')) is not int or row['pid'] <= 0
            or not isinstance(row.get('creation_ticks'), str)
            or not re.fullmatch(r'[0-9]{1,24}', row['creation_ticks'])):
        raise ValueError('unverified_process_identity')
    return {'pid': row['pid'], 'creation_ticks': row['creation_ticks']}


def ingress_origin(value):
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or not parsed.hostname.endswith('.ts.net')
            or parsed.port != 8443 or parsed.path not in ('', '/') or parsed.query or parsed.fragment
            or parsed.username is not None or parsed.password is not None): raise ValueError('invalid_ingress')
    return value.rstrip('/')


def probe_http(url, token, release, timeout=3, *, opener=None):
    """Verify nonce/release/PID, reject redirects/proxies and never retain body."""
    start = time.monotonic()
    nonce = secrets.token_hex(16)
    if not isinstance(token, str) or not re.fullmatch(r'[a-f0-9]{64}', token):
        return {'ok': False, 'reason': 'health_credential_unavailable', 'recoverable': False, 'seconds': 0}
    request = urllib.request.Request(url, headers={'X-Workbench-Health-Token': token,
        'X-Workbench-Health-Nonce': nonce, 'Cache-Control': 'no-cache'})
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs): return None
    try:
        opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(4097)
            value = json.loads(raw) if len(raw) <= 4096 else None
            if (not isinstance(value, dict) or response.status != 200 or response.headers.get('X-Workbench-Health') != '1'
                    or value.get('ok') is not True or value.get('nonce') != nonce or value.get('release') != release
                    or type(value.get('pid')) is not int or value['pid'] <= 0): raise ValueError('unverified_health')
            return {'ok': True, 'pid': value['pid'], 'seconds': round(time.monotonic()-start, 4), 'status': 200}
    except urllib.error.HTTPError as error:
        status = error.code
        error.close()
        return {'ok': False, 'reason': 'unverified_http', 'status': status, 'recoverable': False,
                'seconds': round(time.monotonic()-start, 4)}
    except (ValueError, TypeError):
        return {'ok': False, 'reason': 'unverified_identity', 'recoverable': False, 'seconds': round(time.monotonic()-start, 4)}
    except (OSError, TimeoutError):
        return {'ok': False, 'reason': 'connection_or_timeout', 'recoverable': True, 'seconds': round(time.monotonic()-start, 4)}


class Monitor:
    def __init__(self, config, store, *, inspect_target, http_probe=probe_http, recovery_bridge=None, clock=time.time, public_probe=None):
        self.config, self.store = dict(config), store
        self.inspect_target, self.http_probe, self.recovery_bridge, self.clock = inspect_target, http_probe, recovery_bridge, clock
        self.public_probe = public_probe
        self._public_result = None
        self._public_key = None
        self.app_root = Path(config['app_root']).resolve()
        if store.root == self.app_root or store.root.is_relative_to(self.app_root):
            raise ValueError('controller_state_must_be_outside_application')
        self.local_url = config.get('local_url', 'http://127.0.0.1:9123' + HEALTH_PATH)
        parsed = urllib.parse.urlsplit(self.local_url)
        if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.path != HEALTH_PATH or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
            raise ValueError('invalid_loopback_health_url')

    def _observe(self):
        if not self.app_root.is_dir():
            return {'status': 'app_missing', 'target': 'app_missing', 'needs_repair': False}, None
        try:
            inspected = self.inspect_target()
            if not isinstance(inspected, dict) or inspected.get('schema') != 1:
                raise ValueError('invalid_inspection')
            bound = binding(inspected.get('binding'))
            owner = inspected.get('ownership_verified') is True
            controls = inspected.get('controls_valid') is True
            business = inspected.get('business', {})
            if not isinstance(business, dict): business = {}
            safe_business = {'status': business.get('status') if business.get('status') in (
                'healthy', 'degraded', 'unknown', 'paused', 'unavailable') else 'unknown',
                'ok': business.get('ok') if type(business.get('ok')) is bool else None,
                'external_provider': business.get('external_provider') is True}
            known_roles = {'collector', 'worker', 'feedback', 'learning', 'local', 'publisher', 'overviews'}
            for field in ('degraded_roles', 'unknown_roles'):
                safe_business[field] = [role for role in business.get(field, []) if role in known_roles] if isinstance(business.get(field), list) else []
            safe_business['roles'] = {}
            numeric_fields = {'age_seconds', 'enabled_source_count', 'latest_failed_source_count',
                'latest_partial_source_count', 'latest_completed_source_count', 'latest_active_source_count',
                'unobserved_source_count', 'late_source_count', 'max_late_seconds', 'max_success_age_seconds',
                'schedule_unobserved_source_count', 'external_provider_source_count', 'execution_grace_seconds', 'latest_empty_source_count'}
            for role, signal in business.get('roles', {}).items() if isinstance(business.get('roles'), dict) else []:
                if role not in known_roles or not isinstance(signal, dict): continue
                safe = {key: signal[key] for key in numeric_fields if key in signal and number(signal[key])}
                if signal.get('status') in ('healthy', 'degraded', 'unknown', 'paused', 'unavailable', 'stale', 'not_configured'):
                    safe['status'] = signal['status']
                safe['ok'] = signal.get('ok') if type(signal.get('ok')) is bool else None
                if isinstance(signal.get('reason'), str) and re.fullmatch('[a-z_]{1,64}', signal['reason']):
                    safe['reason'] = signal['reason']
                if signal.get('coverage_status') in ('observed','partial','failed'):
                    safe['coverage_status']=signal['coverage_status']
                if signal.get('schedule_evidence') in ('slot_receipt','terminal_outcome'):
                    safe['schedule_evidence']=signal['schedule_evidence']
                safe_business['roles'][role] = safe
            safe_business['degraded_roles'] = [role for role in business.get('degraded_roles', [])
                if isinstance(role, str) and re.fullmatch(r'[a-z_]{1,32}', role)] if isinstance(business.get('degraded_roles', []), list) else []
            # Do not persist untrusted inspector payloads, exception messages,
            # raw status bodies, health credentials or business documents.
            result = {'status': 'unavailable', 'binding': bound, 'business': safe_business,
                      'ownership_verified': owner, 'controls_valid': controls, 'needs_repair': False}
            performance = inspected.get('performance')
            result['usage'] = usage_projection(inspected.get('usage'))
            result['content_library'] = library_projection(inspected.get('content_library'))
            if isinstance(performance, dict):
                result['performance'] = {'status': performance.get('status') if performance.get('status') in (
                    'healthy', 'degraded', 'unavailable') else 'unavailable', **{
                    key: performance[key] for key in ('slow_count', 'db_copy_bytes', 'db_busy_count', 'max_write_tx_ms')
                    if key in performance and number(performance[key])}}
            retained = inspected.get('retained_audited_unknown_count')
            if type(retained) is int and retained >= 0:
                result['retained_audited_unknown_count'] = retained
            local = self.http_probe(self.local_url, inspected.get('health_token'), bound['release'], self.config.get('local_timeout', 3))
            allowed_pids = inspected.get('server_member_pids', [])
            if local.get('ok') and (type(allowed_pids) is not list or local.get('pid') not in allowed_pids):
                local = {'ok': False, 'reason': 'foreign_health_pid', 'recoverable': False, 'seconds': local.get('seconds', 0)}
            result['local'] = local
            origin = ingress_origin(self.config.get('ingress_origin') or inspected.get('ingress_origin', ''))
            ingress = self.http_probe(origin + HEALTH_PATH, inspected.get('health_token'), bound['release'], self.config.get('ingress_timeout', 5))
            if ingress.get('ok') and ingress.get('pid') not in allowed_pids:
                ingress = {'ok': False, 'reason': 'foreign_ingress_pid', 'recoverable': False, 'seconds': ingress.get('seconds', 0)}
            result['ingress'] = ingress
            if self.config.get('public_ingress_enabled') is True:
                now = self.clock()
                public_key = (bound['release'], bound['manifest_sha256'], tuple(allowed_pids))
                if (self._public_result is None or now - self._public_result['observed_at'] >= 60
                        or now < self._public_result['observed_at'] or self._public_key != public_key):
                    from .public_ingress import probe_public_http
                    public = (self.public_probe or probe_public_http)(origin + HEALTH_PATH,
                        inspected.get('health_token'), bound['release'], self.config.get('ingress_timeout', 5))
                    if public.get('ok') and public.get('pid') not in allowed_pids:
                        public = {'ok': False, 'reason': 'foreign_public_ingress_pid', 'recoverable': False, 'seconds': public.get('seconds', 0)}
                    self._public_result = {**public, 'observed_at': now, 'release': bound['release']}
                    self._public_key = public_key
                    self.store.event('public_ingress_probe', at=now, source='public_ingress',
                        outcome='healthy' if public.get('ok') else 'failed',
                        reason=public.get('reason', 'verified'), seconds=public.get('seconds', 0))
                result['public_ingress'] = self._public_result
            manager = inspected.get('manager', {})
            server = inspected.get('server', {})
            stale_manager = manager.get('alive') is not True or not number(manager.get('heartbeat_age_seconds')) or manager['heartbeat_age_seconds'] > 90
            if not stale_manager and server.get('alive') is False:
                result.update(status='server_missing', blocked_reason='waiting_for_manager',
                    target=bound['release'] + ':' + bound['manifest_sha256'] + ':server_missing', eligible=False)
                return result, inspected
            action = 'restart_manager' if stale_manager else 'recover_server'
            selected = manager if stale_manager else server
            missing_manager = stale_manager and manager.get('alive') is False and inspected.get('manager_task_verified') is True
            selected_identity = {'pid': None, 'creation_ticks': None} if missing_manager else identity(selected)
            age = 10**9 if missing_manager else selected.get('age_seconds', 0)
            if not number(age): raise ValueError('invalid_process_age')
            result.update(identity=selected_identity, action=action,
                target=':'.join([bound['release'], bound['manifest_sha256'], action,
                                 str(selected_identity['pid']), str(selected_identity['creation_ticks'])]),
                age_seconds=age)
            healthy_local = local.get('ok') is True
            if healthy_local and not stale_manager:
                if (not ingress.get('ok') or ingress.get('seconds', 0) > self.config.get('slow_seconds', 2)
                        or result.get('public_ingress', {}).get('ok') is False
                        or result.get('public_ingress', {}).get('seconds', 0) > self.config.get('public_slow_seconds', 8)): result['status'] = 'network_degraded'
                elif local.get('seconds', 0) > self.config.get('slow_seconds', 2): result['status'] = 'endpoint_slow'
                elif business.get('external_provider') is True: result['status'] = 'provider_degraded'
                elif business.get('ok') is False: result['status'] = 'business_degraded'
                elif result['content_library']['status'] in ('stale','error') or result['content_library']['performance_degraded']: result['status'] = 'content_library_degraded'
                elif result['content_library']['status']=='building': result['status'] = 'content_library_building'
                elif 'content_library' in inspected and result['content_library']['status']=='unavailable': result['status'] = 'content_library_unknown'
                elif result.get('performance', {}).get('status') == 'degraded': result['status'] = 'performance_degraded'
                elif business.get('ok') is None: result['status'] = 'business_unknown'
                else: result['status'] = 'healthy'
            else:
                result.update(status='manager_stale' if stale_manager else 'app_unresponsive', needs_repair=True)
            result['eligible'] = (owner and controls and inspected.get('busy') is False
                and inspected.get('unknown_receipts') is False
                and (stale_manager or local.get('recoverable') is True))
            if not owner: result['blocked_reason'] = 'ownership_unverified'
            elif not controls: result['blocked_reason'] = 'controls_unverified'
            elif inspected.get('busy') is not False: result['blocked_reason'] = 'business_busy_or_unverified'
            elif inspected.get('unknown_receipts') is not False: result['blocked_reason'] = 'business_receipt_unknown'
            if not owner or not controls:
                result.update(status='ownership_unverified' if not owner else 'controls_unverified', needs_repair=False)
            return result, inspected
        except Exception as error:
            return {'status': 'inspection_unavailable', 'target': 'unverified', 'needs_repair': False,
                    'error_type': type(error).__name__}, None

    def tick(self, *, allow_repair=False):
        with self.store.lock():
            started = self.clock()
            observation, _ = self._observe()
            now = self.clock()
            options = {key: self.config[key] for key in ('threshold', 'startup_grace', 'cooldown', 'window', 'max_restarts') if key in self.config}
            policy = assess(self.store.policy(), observation, now, **options)
            self.store.save_policy(policy)
            report = {'schema': 1, 'at': now, 'started_at': started, 'inspection_seconds': max(0, now-started),
                      'controller_pid': os.getpid(), 'observation': observation, 'policy': policy,
                      'decision': policy['decision'], 'repair_enabled': allow_repair is True}
            if policy['action'] and allow_repair is True and self.recovery_bridge is not None:
                fresh, _ = self._observe()
                if (fresh.get('binding') != observation.get('binding') or fresh.get('identity') != observation.get('identity')
                        or fresh.get('target') != observation.get('target') or not fresh.get('eligible') or not fresh.get('needs_repair')):
                    report.update(decision='repair_deferred', reason='fresh_ownership_or_idle_gate_changed')
                else:
                    request = {'schema': 1, 'operation_id': uuid.uuid4().hex, 'action': policy['action'],
                        'binding': copy.deepcopy(observation['binding']), 'expected_identity': copy.deepcopy(observation['identity']), 'observed_at': self.clock()}
                    policy = consume(policy, request['observed_at'], request['operation_id'])
                    self.store.save_policy(policy)
                    receipt = {'schema': 1, 'request': request, 'phase': 'attempted'}
                    name = 'repair-' + request['operation_id'] + '.json'
                    self.store.write(name, receipt)
                    self.store.event('repair_attempted', at=self.clock(), operation_id=request['operation_id'], action=request['action'])
                    try:
                        answer = self.recovery_bridge(copy.deepcopy(request))
                        if (not isinstance(answer, dict) or any(answer.get(key) != request[key] for key in ('operation_id', 'action', 'binding'))
                                or answer.get('outcome') not in ('server_restart_requested', 'manager_restart_requested', 'already_healthy', 'deferred')):
                            raise ValueError('unverified_repair_receipt')
                        receipt.update(phase='acknowledged', outcome=answer['outcome'])
                        self.store.write(name, receipt)
                        policy.update(pending_operation=None, decision='repair_acknowledged')
                        self.store.save_policy(policy)
                        report.update(decision='repair_acknowledged', repair={'operation_id': request['operation_id'], 'outcome': answer['outcome']})
                    except Exception as error:
                        receipt.update(phase='unknown', error_type=type(error).__name__)
                        self.store.write(name, receipt)
                        report.update(decision='repair_receipt_unknown', repair={'operation_id': request['operation_id'], 'error_type': type(error).__name__})
                    report['policy'] = policy
            self.store.write('status.json', report)
            self.store.event('observation', at=now, decision=report['decision'],
                             error_type=observation.get('error_type'), seconds=report['inspection_seconds'])
            return report
