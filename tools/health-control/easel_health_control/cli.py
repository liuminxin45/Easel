"""OS-scheduled monitor and durable, read-only local reports."""
from pathlib import Path
import argparse
import datetime as dt
import html
import json
import os
import tempfile
import time

from .adapter import ApplicationAdapter
from .monitor import Monitor
from .state import StateStore


def reconcile_pending(adapter, store):
    policy = store.policy()
    pending = policy.get('pending_operation') if isinstance(policy, dict) else None
    if not pending: return
    original = store.read('repair-'+pending+'.json', {})
    request = original.get('request', {})
    answer = adapter.reconcile(request)
    if (answer.get('status') != 'receipt_confirmed'
            or any(answer.get(key) != request.get(key) for key in ('operation_id', 'action', 'binding'))
            or answer.get('outcome') not in ('server_restart_requested', 'manager_restart_requested', 'already_healthy', 'deferred')):
        return
    with store.lock():
        fresh = store.policy()
        if not isinstance(fresh, dict) or fresh.get('pending_operation') != pending: return
        # Read the original completed receipt; never issue another recovery.
        store.write('repair-'+pending+'.json', {**original, 'phase': 'acknowledged', 'outcome': answer['outcome']})
        fresh.update(pending_operation=None, decision='repair_receipt_reconciled')
        store.save_policy(fresh)
        store.event('repair_receipt_reconciled', at=time.time(), operation_id=pending, outcome=answer['outcome'])


def report(store):
    status = store.read('status.json', {})
    daily = store.read('daily-status.json', {})
    value = {'monitor': status, 'daily': daily,
        'observed_age_seconds': max(0, time.time()-status.get('at', 0)) if status else None}
    body = '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
    body += '<title>Easel 健康报告</title><style>body{font:16px/1.6 system-ui;max-width:960px;margin:32px auto;padding:0 20px;color:#18212b}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6f8;padding:20px;border-radius:10px}a{color:#135e98}</style>'
    body += '<h1>Easel 独立健康报告</h1><p>本报告只在检测完成后更新。入口连通、业务完成、性能与每日真实制作分别记录。</p>'
    body += '<p>生成时间：' + html.escape(dt.datetime.now().astimezone().isoformat(timespec='seconds')) + '</p>'
    body += '<pre>' + html.escape(json.dumps(value, ensure_ascii=False, indent=2)) + '</pre>'
    # No script, credentials, business payload or external asset dependencies.
    target = store.root/'report.html'
    fd, temporary = tempfile.mkstemp(prefix='report-', suffix='.tmp', dir=store.root)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            output.write(body)
        for attempt in range(6):
            try:
                os.replace(temporary, target)
                break
            except PermissionError:
                if attempt == 5: raise
                time.sleep(min(.02 * 2**attempt, .25))
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('action', choices=('tick', 'run', 'report', 'daily'))
    parser.add_argument('--duration', type=float, default=48)
    options = parser.parse_args(argv)
    config = json.loads(options.config.read_text(encoding='utf-8-sig'))
    store = StateStore(config['state_root'])
    if options.action == 'report':
        value = report(store)
    elif options.action == 'daily':
        from .canary import scheduled_run
        value = scheduled_run(config, store)
        report(store)
    else:
        adapter = ApplicationAdapter(config)
        monitor = Monitor(config, store, inspect_target=adapter.inspect, recovery_bridge=adapter.recover)
        deadline = time.monotonic() + max(0, min(options.duration, 50))
        while True:
            if config.get('auto_repair') is True:
                try:
                    reconcile_pending(adapter, store)
                except Exception:
                    # A missing/dead application cannot stop the independent
                    # monitor. Keep the original unknown budget/receipt intact.
                    pass
            value = monitor.tick(allow_repair=config.get('auto_repair') is True)
            report(store)
            remaining = deadline-time.monotonic()
            if options.action == 'tick' or remaining <= 0:
                break
            time.sleep(min(15, remaining))
    print(json.dumps(value, ensure_ascii=True, separators=(',', ':')))
    return value


if __name__ == '__main__':
    main()
