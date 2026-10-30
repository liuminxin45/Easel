"""A terminal AI turn is not a delivered candidate. Never dispatch from here."""
import json
import pathlib
import re

from easel_workbench.runtime.desk import stamp

TERMINAL_ISSUES = {'blocked', 'error'}


def initialize(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS toolbox_production_outcomes(
        job_id TEXT PRIMARY KEY, document TEXT NOT NULL, checked_at TEXT NOT NULL)''')


def declared(reply):
    """Only consume the bounded receipt schema, never instructions/paths in it."""
    from .delivery_receipts import structured_receipts
    for value in structured_receipts(reply):
        result = value.get('production_result') if isinstance(value, dict) else None
        if not isinstance(result, dict) or result.get('schema_version') != 1:
            continue
        if result.get('status') not in ('completed', 'blocked', 'failed'):
            continue
        return {key: str(result.get(key) or '')[:limit] for key, limit in
                [('status', 20), ('stage', 80), ('code', 80), ('message', 1000), ('next_action', 500)]}
    return None


def _file(row, root):
    try:
        path = pathlib.Path(row['path']).resolve()
        return path if path.is_relative_to(pathlib.Path(root).resolve()) and path.is_file() and path.stat().st_size else None
    except (OSError, ValueError):
        return None


def image_available(row, root):
    path = _file(row, root)
    if not path or row['mime'] not in ('image/png', 'image/jpeg', 'image/webp', 'image/gif', 'image/bmp', 'image/avif'):
        return False
    try:
        with path.open('rb') as file:
            header = file.read(32)
        return bool((row['mime'] == 'image/png' and header.startswith(b'\x89PNG\r\n\x1a\n') and len(header) >= 24 and int.from_bytes(header[16:20], 'big') and int.from_bytes(header[20:24], 'big'))
                    or (row['mime'] == 'image/jpeg' and header.startswith(b'\xff\xd8\xff'))
                    or (row['mime'] == 'image/webp' and header.startswith(b'RIFF') and header[8:12] == b'WEBP')
                    or (row['mime'] == 'image/gif' and header[:6] in (b'GIF87a', b'GIF89a'))
                    or (row['mime'] == 'image/bmp' and header.startswith(b'BM'))
                    or (row['mime'] == 'image/avif' and header[4:8] == b'ftyp' and b'avif' in header))
    except OSError:
        return False


def delivery(box, connection, job, article=None, summary=False):
    rows = [dict(row) for row in connection.execute('SELECT * FROM artifacts WHERE task_id=?', (job['id'],))]
    root = box.root / 'data/artifacts'
    scopes = ['images'] if any(image_available(row, root) for row in rows) else []
    authored = connection.execute('SELECT document FROM toolbox_text_versions WHERE job_id=?', (job['id'],)).fetchone()
    human = json.loads(authored['document']).get('text', {}) if authored else {}
    if box.options(job['work_id'], connection)['format'] == 'article':
        if article is None:
            from easel_workbench.runtime.article_delivery import from_artifacts
            from easel_workbench.runtime.article_drafts import job_work
            article = from_artifacts(rows, root, job_work(box.options(job['work_id'], connection), job['id'], connection)['article_mode'])
        if article.get('body') or human.get('title') and human.get('body'):
            scopes.append('article')
        return bool('article' in scopes), scopes
    # Process notes, sources, prompts, manifests and prose replies are not copy.
    if summary and scopes:
        return True, scopes
    from easel_workbench.runtime.publish_content import from_artifacts
    if from_artifacts(rows, root) or human.get('title') and human.get('body'):
        scopes.append('copy')
    return bool(scopes), scopes


def assess(box, connection, job, reply=None, article=None, summary=False):
    receipt = declared(reply if reply is not None else job.get('reply') or '')
    ready, scopes = delivery(box, connection, job, article, summary)
    if receipt and receipt['status'] in ('blocked', 'failed'):
        return {'status': 'blocked' if receipt['status'] == 'blocked' else 'error',
                'stage': receipt['stage'], 'code': receipt['code'] or 'production_incomplete',
                'message': receipt['message'] or '本次制作未完成',
                'next_action': receipt['next_action'] or '补充素材或调整要求后，再提交制作。',
                'available_scopes': scopes}
    if not ready:
        return {'status': 'error', 'stage': 'delivery', 'code': 'missing_deliverables',
                'message': '本次制作已结束，但没有收到可评审的成品。',
                'next_action': '查看制作说明，补充素材或调整要求后再制作。', 'available_scopes': scopes}
    return {'status': 'completed', 'available_scopes': scopes}


def record(connection, jid, outcome):
    connection.execute('INSERT OR REPLACE INTO toolbox_production_outcomes VALUES(?,?,?)',
                       (jid, json.dumps(outcome, ensure_ascii=False), stamp()))


def read(connection, jid):
    row = connection.execute('SELECT document FROM toolbox_production_outcomes WHERE job_id=?', (jid,)).fetchone()
    return json.loads(row['document']) if row else None


def issue(job, outcome=None, recovery=None):
    if recovery is None:
        from easel_workbench.runtime.production_retry import recovery as retry_recovery
        recovery=retry_recovery(job,None,outcome=outcome)
    if recovery and recovery['failure_kind']=='dispatch' and recovery['phase'] in ('failed','exhausted','retry_wait'):
        return {'job_id':job['id'],'status':'error','stage':'dispatch','code':recovery['error_code'],
                'message':recovery['message'],'next_action':'后台将按计划重试，也可立即重新发送原任务。' if recovery['phase']=='retry_wait' else '检查 Codex 连接后，重新发送原任务。',
                'recovery':recovery}
    if outcome and outcome['status'] in TERMINAL_ISSUES:
        from easel_workbench.runtime.revision_scope import is_scope_conflict
        extra={'category':'settings_conflict','title':'修改范围待确认','action':'adjust_settings'} if is_scope_conflict(outcome) else {}
        return {'job_id': job['id'], **outcome,'recovery':recovery,**extra}
    if job['status'] in TERMINAL_ISSUES:
        return {'job_id': job['id'], 'status': job['status'], 'code': 'production_incomplete',
                'message': job.get('error') or '本次制作未完成',
                'next_action': '查看制作说明，补充素材或调整要求后再制作。','recovery':recovery}
    return None
