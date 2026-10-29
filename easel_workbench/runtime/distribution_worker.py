"""An explicit-delivery worker; never retries a dispatched intent automatically."""
from __future__ import annotations

if __name__ == "__main__" and not __package__:
    import sys as _bootstrap_sys
    from pathlib import Path as _BootstrapPath
    _bootstrap_sys.path.insert(0,str(_BootstrapPath(__file__).resolve().parents[2]))


import datetime as dt
import hashlib
import os
import pathlib
import threading

from easel_workbench.runtime.desk import ROOT, Store, stamp
from easel_workbench.runtime.distribution_runtime import DistributionRuntime, process_identity
from easel_workbench.runtime.distribution_service import DistributionService, digest
from easel_workbench.runtime.toolbox_store import Toolbox


def preflight_assets(box, revision):
    manifest = revision.get('asset_manifest')
    if not isinstance(manifest, list) or len(manifest) > 12:
        raise ValueError('asset_manifest_invalid')
    if digest({key: value for key, value in revision.items() if key not in ('id', 'created_at', 'hash')}) != revision.get('hash'):
        raise ValueError('revision_hash_mismatch')
    result = []
    root = (pathlib.Path(box.root) / 'data/toolbox/files').resolve()
    for expected in manifest:
        if not isinstance(expected, dict) or expected.get('mime') not in ('image/png', 'image/jpeg', 'image/webp', 'image/gif','video/mp4','video/webm','audio/mpeg','audio/wav','audio/x-wav','audio/mp4','audio/ogg'):
            raise ValueError('asset_kind_unsupported')
        metadata, path = box.file(expected.get('id'))
        path = path.resolve()
        if not path.is_relative_to(root) or path.is_symlink() or not path.is_file():
            raise ValueError('asset_path_invalid')
        size = path.stat().st_size
        limit=(32 if expected['mime'].startswith('image/') else 512)*1024*1024
        if type(expected.get('size')) is not int or size != expected['size'] or not 0 < size <= limit:
            raise ValueError('asset_size_mismatch')
        checksum = hashlib.sha256()
        with path.open('rb') as stream:
            while chunk := stream.read(1024 * 1024):
                checksum.update(chunk)
        if checksum.hexdigest() != expected.get('sha256') or metadata.get('sha256') != expected['sha256']:
            raise ValueError('asset_hash_mismatch')
        result.append({key: expected[key] for key in ('id', 'name', 'mime', 'sha256', 'size')} | {'path': str(path)})
    return result


class DistributionWorker:
    def __init__(self, service, runtime=None, *, runner_id='distribution-local', lease_seconds=180, probe_before_claim=True):
        self.service = service
        self.runtime = runtime or service.runtime or DistributionRuntime(service.box)
        self.runner_id = runner_id
        self.lease_seconds = lease_seconds
        self.probe_before_claim = probe_before_claim
        self._state = 'idle'
        self._state_lock = threading.Lock()
        self._process_identity = process_identity(os.getpid())

    def _heartbeat(self, state=None):
        if state is not None:
            with self._state_lock:
                self._state = state
        with self._state_lock:
            current = self._state
        with self.service.store.connect() as connection:
            previous = self.service._get(connection, 'runners', self.runner_id, False) or {'id': self.runner_id}
            previous.update(last_seen_at=stamp(), state=current, process_id=os.getpid(), process_identity=self._process_identity)
            self.service._put(connection, 'runners', previous)

    def _probe_due_connections(self):
        if not self.probe_before_claim or not callable(getattr(self.runtime, 'probe', None)):
            return
        with self.service.store.connect() as connection:
            due = set()
            for delivery in self.service._records(connection, 'deliveries'):
                if delivery['status'] != 'queued':
                    continue
                scheduled = delivery.get('schedule_at')
                if scheduled and dt.datetime.fromisoformat(scheduled.replace('Z', '+00:00')) > dt.datetime.now(dt.timezone.utc):
                    continue
                due.add(delivery['connection_id'])
            accounts = [item for item in self.service._records(connection, 'connections') if item['id'] in due and item['enabled']]
        for account in accounts:
            self.runtime.probe(account)

    def run_once(self):
        self._heartbeat('polling')
        self._probe_due_connections()
        claim = self.service.claim_next(self.runner_id, lease_seconds=self.lease_seconds)
        if claim is None:
            self._heartbeat('idle')
            return None
        delivery, revision, connection = claim['delivery'], claim['revision'], claim['connection']
        self._heartbeat('preflight')
        dispatched = False
        try:
            if (revision.get('id') != delivery.get('revision_id') or revision.get('connection_id') != connection.get('id')
                    or revision.get('account') != connection.get('account') or revision.get('account') != delivery.get('account')
                    or revision.get('platform') != connection.get('platform') or revision.get('platform') != delivery.get('platform')):
                raise ValueError('delivery_identity_mismatch')
            assets = preflight_assets(self.service.box, revision)
            self.service.mark_dispatched(delivery['id'], claim['attempt']['id'], claim['lease_token'], runner_id=self.runner_id)
            dispatched = True
            self._heartbeat('dispatched')
            result = self.runtime.send(claim, assets)
        except Exception:
            result = {'remote_state': 'unknown' if dispatched else 'failed', 'verified': False,
                      'error': '发送边界已记录，回执不明；不会自动重发，请实际核验' if dispatched else '发送前核对失败；未调用平台，请检查账号、批准版本和图片原件'}
        # The service independently inspects the committed marker. Even if an
        # exception hid mark_dispatched's acknowledgement, it stays unknown.
        finished = self.service.finish_attempt(delivery['id'], claim['attempt']['id'], claim['lease_token'], result, runner_id=self.runner_id)
        self._heartbeat('idle')
        public = finished['delivery']
        return {'delivery_id': public['id'], 'attempt_id': claim['attempt']['id'], 'status': public['status'],
                'remote_state': public.get('remote_state'), 'verified': public.get('verified', False)}

    def run(self, *, stop_event=None, once=False, poll_seconds=5):
        stop_event = stop_event or threading.Event()
        heartbeat_stop = threading.Event()
        def heartbeat():
            while not heartbeat_stop.wait(5):
                try:
                    self._heartbeat()
                except Exception:
                    pass
        thread = threading.Thread(target=heartbeat, name='distribution-heartbeat', daemon=True)
        thread.start()
        try:
            while not stop_event.is_set():
                try:
                    self.run_once()
                except Exception:
                    # Never print an exception, a bridge response, credentials,
                    # input documents, or a leased claim into process logs.
                    print('distribution_worker: cycle_unavailable', flush=True)
                if once:
                    break
                stop_event.wait(max(1, float(poll_seconds)))
        finally:
            heartbeat_stop.set()
            thread.join(timeout=6)
            try:
                self._heartbeat('stopped')
            except Exception:
                pass


def run(root=None, *, stop_event=None, once=False, poll_seconds=5, runtime=None):
    root = pathlib.Path(root or ROOT).resolve()
    box = Toolbox(Store(root / 'data/desk.sqlite'), root)
    if runtime is None:
        from easel_workbench.runtime.easel_distribution import EaselDistributionRuntime
        runtime = EaselDistributionRuntime(box,DistributionRuntime(box))
    service = DistributionService(box, runtime)
    return DistributionWorker(service, runtime).run(stop_event=stop_event, once=once, poll_seconds=poll_seconds)


if __name__ == '__main__':
    run()
