"""Deterministic delivery receipt shared by native Easel and legacy tasks.

No model, native connection or retry is started here. The caller supplies the
actual final response and native turn; files are received under explicit roots.
"""
from .desk import stamp
from . import server_logging as journal


def record_delivery(box, jid, reply, native_turn_id, product_roots=None, receiver=None, execution_identity=None):
    from .bridge import capture_artifacts
    from .task_runtime import production_finish, step
    with box.store.connect() as c:
        row = c.execute('SELECT * FROM toolbox_jobs WHERE id=?', (jid,)).fetchone()
        if not row:
            raise ValueError('找不到准确的作品任务')
        job = dict(row)
    if not isinstance(reply, str) or not reply.strip():
        with box.store.connect() as c:
            c.execute("UPDATE toolbox_jobs SET status='uncertain',error=? WHERE id=?",
                      ('完成通知缺少有效回执，继续核对原任务；不会自动重复制作', jid))
        return {'job_id': jid, 'status': 'uncertain'}
    if not native_turn_id and isinstance(execution_identity,dict) and execution_identity.get('kind') in ('jsonrpc_request','cli_result_sha256'):
        native_turn_id=execution_identity.get('id')
    if not isinstance(native_turn_id, str) or not native_turn_id:
        raise ValueError('交付必须绑定准确的原生回合或协议完成回执')
    if job.get('turn_id') and job['turn_id'] != native_turn_id:
        raise ValueError('交付回合与已记录的任务身份不一致')
    if job['status'] == 'completed':
        if job.get('reply') != reply:
            raise ValueError('已完成的原生回执不能被另一份内容覆盖')
        return {'job_id': jid, 'status': 'completed', 'reused_receipt': True}
    receiver = receiver or capture_artifacts
    status, outcome = 'completed', None
    try:
        if job['kind'] != 'discuss':
            if product_roots is None:
                receiver(box.store, jid, reply)
            else:
                receiver(box.store, jid, reply, product_roots=product_roots, root=box.root)
        if job['kind'] in ('create', 'change'):
            from .production_outcome import assess, record
            with box.store.connect() as c:
                outcome = assess(box, c, job, reply)
                record(c, jid, outcome)
            status = outcome['status']
    except Exception as error:
        journal.exception('production_delivery_failed', error, operation_ref=journal.reference(jid))
        from .production_outcome import record
        outcome = {'status': 'error', 'stage': 'delivery', 'code': 'delivery_capture_failed',
                   'message': '成品接收失败，原制作答复已保留。', 'next_action': '查看制作说明与原任务，补齐交付文件后继续。'}
        with box.store.connect() as c:
            record(c, jid, outcome)
        status = 'error'
    from .browser_cleanup import record as record_browser_cleanup
    warning = record_browser_cleanup(box.store, jid, reply) if job['kind'] in ('accept', 'reject') else None
    with box.store.connect() as c:
        c.execute('UPDATE toolbox_jobs SET status=?,turn_id=?,reply=?,finished_at=?,error=? WHERE id=?',
                  (status, native_turn_id, reply, stamp(), outcome['message'] if outcome and status != 'completed' else warning, jid))
    journal.emit('production_state', operation_ref=journal.reference(jid), phase=status)
    production_finish(box, jid, 'completed', {'turn_id': native_turn_id, 'reply': reply})
    with box.store.connect() as c:
        step(c, jid, 'capture', 'completed' if status == 'completed' else 'failed', delivery_status=status,
             artifacts=[dict(row) for row in c.execute('SELECT id,name,mime FROM artifacts WHERE task_id=?', (jid,))])
    if job['kind'] in ('accept', 'archive'):
        from .completion_service import service as completion_service
        service = completion_service(box)
        service.verify_project_archive(service.archive_decision_id(job), reply)
    with box.store.connect() as c:
        c.execute('UPDATE toolbox_works SET updated_at=? WHERE id=?', (stamp(), job['work_id']))
        if status == 'completed':
            from .local_operations import enqueue_delivery
            enqueue_delivery(c, job)
        learning = getattr(box, 'learning', None)
        if learning and job['kind'] in ('create', 'change') and status == 'completed':
            learning.enqueue_review(c, jid)
        if learning and job['kind'] in ('feedback', 'accept', 'reject'):
            learning.index_database(c)
        # Retired notification storage keeps its historical compatibility view.
        c.execute("INSERT OR IGNORE INTO notification_events(event_key,kind,status,article_id,task_id) VALUES(?,?,?,?,?)",
                  ('toolbox:' + jid, 'toolbox_discuss' if job['kind'] == 'discuss' else 'toolbox', status, None, jid))
    return {'job_id': jid, 'status': status}
