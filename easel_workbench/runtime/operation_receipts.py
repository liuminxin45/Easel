"""Read existing command receipts without submitting or replaying a command.

This is a projection of the business ledgers, not another operation journal.
An absent receipt says nothing about whether an in-flight request will commit.
"""
from __future__ import annotations

import json
import re
import hashlib

from easel_workbench.runtime.toolbox_store import ident


LEDGERS = {
    '/api/platform-accounts': ('media_operations', 'id'),
    '/api/media/accounts': ('media_operations', 'id'),
    '/api/creator/commands': ('creator_operations', 'id'),
    '/api/easel/commands': ('easel_ui_operations', 'id'),
    '/api/chat/sessions': ('easel_chat_operations', 'id'),
    '/api/studio/commands': ('studio_operations', 'operation_id'),
    '/api/creative/commands': ('creative_receipts', 'operation_id'),
    '/api/learning/commands': ('learning_operations', 'operation_id'),
    '/api/distribution/commands': ('distribution_operations', 'operation_id'),
    '/api/completion/defaults': ('completion_preference_operations', 'id'),
    '/api/style-presets': ('toolbox_style_preset_ops', 'id'),
    '/api/drafts': ('toolbox_article_draft_ops', 'id'),
    '/api/article-drafts': ('toolbox_article_draft_ops', 'id'),
    '/api/collection/sources': ('collection_source_operations', 'operation_id'),
}


def read(store, operation_id, path, *, collection=None):
    operation_id = ident(operation_id)
    ledger = LEDGERS.get(path)
    if re.fullmatch(r'/api/works/[A-Za-z0-9_-]+/draft', path):
        ledger = ('toolbox_article_draft_ops', 'id')
    elif re.fullmatch(r'/api/works/[A-Za-z0-9_-]+/versions/[A-Za-z0-9_-]+/review', path):
        ledger = ('toolbox_review_ops', 'id')
    elif re.fullmatch(r'/api/tasks/[A-Za-z0-9_-]+/retry', path):
        ledger = ('toolbox_dispatch_retry_operations', 'operation_id')
    elif re.fullmatch(r'/api/works/[A-Za-z0-9_-]+/completion/[A-Za-z0-9_-]+/retry-archive', path):
        ledger = ('toolbox_completion_ops', 'id')
    elif re.fullmatch(r'/api/works/[A-Za-z0-9_-]+/(project-binding|local-operations/retry)', path):
        ledger = ('toolbox_local_ops', 'operation_id')
    job_path=re.fullmatch(r'/api/works/([A-Za-z0-9_-]+)/(actions|discussions|text|finalize)',path)
    if path in ('/api/works','/api/text-works','/api/topic-research') or job_path:
        job_id='topic-'+hashlib.sha256(operation_id.encode()).hexdigest() if path=='/api/topic-research' else operation_id
        with store.connect() as c:
            row=c.execute('SELECT id,work_id,kind,status FROM toolbox_jobs WHERE id=?',(job_id,)).fetchone()
        if row and (not job_path or row['work_id']==job_path[1]):
            allowed={'actions':{'accept','reject','feedback','change'},'discussions':{'discuss'},'text':{'create','change'},'finalize':{'create'}}
            if not job_path or row['kind'] in allowed[job_path[2]]:
                result={key:row[key] for key in ('id','work_id','status')}
                if path=='/api/topic-research':result['research']=True
                return {'id':operation_id,'state':'received','result':result}
        return {'id':operation_id,'state':'waiting'}
    manual=re.fullmatch(r'/api/works/([A-Za-z0-9_-]+)/versions/([A-Za-z0-9_-]+)/manual-review',path)
    if manual:
        with store.connect() as c:
            if not c.execute("SELECT 1 FROM sqlite_master WHERE name='learning_manual_reviews'").fetchone():return {'id':operation_id,'state':'waiting'}
            original=c.execute('SELECT job_id FROM learning_manual_reviews WHERE operation_id=?',(operation_id,)).fetchone()
            task_id='manual-review-'+hashlib.sha256(operation_id.encode()).hexdigest()[:40]
            row=c.execute('SELECT * FROM learning_analysis_queue WHERE id=?',(task_id,)).fetchone() if original and original['job_id']==manual[2] else None
        if row:
            result=dict(row);result['payload']=json.loads(result['payload'])
            return {'id':operation_id,'state':'received','result':result}
        return {'id':operation_id,'state':'waiting'}
    if path=='/api/collection/runs' or re.fullmatch(r'/api/collection/runs/[A-Za-z0-9_-]+/retry',path):
        with store.connect() as c:
            if not c.execute("SELECT 1 FROM sqlite_master WHERE name='collection_operations'").fetchone():return {'id':operation_id,'state':'waiting'}
            row=c.execute('SELECT run_id FROM collection_operations WHERE id=?',(operation_id,)).fetchone()
        if row and collection is not None:
            return {'id':operation_id,'state':'received','result':{**collection.get(row['run_id']),'reused':True}}
        return {'id':operation_id,'state':'waiting'}
    if path == '/api/platform-accounts/environment/install':
        from easel_workbench.runtime.easel_connection_support import digest
        with store.connect() as c:
            if not c.execute("SELECT 1 FROM sqlite_master WHERE name='media_install_jobs'").fetchone():
                return {'id': operation_id, 'state': 'waiting'}
            row = c.execute('SELECT document FROM media_install_jobs WHERE id=?', ('install-' + digest(operation_id)[:24],)).fetchone()
        return {'id': operation_id, 'state': 'received', 'result': json.loads(row['document'])} if row else {'id': operation_id, 'state': 'waiting'}
    if ledger is None:
        return {'id': operation_id, 'state': 'unavailable'}
    table, key = ledger
    with store.connect() as c:
        if not c.execute('SELECT 1 FROM sqlite_master WHERE type=\'table\' AND name=?', (table,)).fetchone():
            return {'id': operation_id, 'state': 'waiting'}
        # Identifiers come exclusively from the fixed allowlist above.
        row = c.execute(f'SELECT result FROM {table} WHERE {key}=?', (operation_id,)).fetchone()
    if row is None or row['result'] is None:
        return {'id': operation_id, 'state': 'waiting'}
    return {'id': operation_id, 'state': 'received', 'result': json.loads(row['result'])}
