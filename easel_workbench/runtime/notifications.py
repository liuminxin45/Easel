"""Durable message inbox and best-effort WebToApp polling (stdlib only)."""
import re
import sqlite3
import urllib.parse

KINDS = {'select': '制作草稿', 'followup': '追问', 'change': '修改', 'accept': '采纳反馈', 'reject': '拒绝反馈', 'creative_feedback': '追加制作反馈'}
STATES = {'queued': '排队中', 'running': '制作中', 'completed': '已完成', 'error': '执行出错'}


def migrate(c):
    c.executescript('''
CREATE TABLE IF NOT EXISTS notification_events(
 id INTEGER PRIMARY KEY AUTOINCREMENT, event_key TEXT NOT NULL UNIQUE,
 kind TEXT NOT NULL, status TEXT, article_id TEXT, task_id TEXT, source_job TEXT,
 item_count INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), read_at TEXT);
CREATE INDEX IF NOT EXISTS notification_events_time ON notification_events(created_at);
CREATE TABLE IF NOT EXISTS notification_devices(id TEXT PRIMARY KEY,cursor INTEGER NOT NULL,last_poll TEXT);
CREATE TRIGGER IF NOT EXISTS notification_task_insert AFTER INSERT ON tasks
WHEN NEW.status IN ('queued','running','completed','error') BEGIN
 INSERT OR IGNORE INTO notification_events(event_key,kind,status,article_id,task_id)
 VALUES('task:'||NEW.id||':'||NEW.status,NEW.kind,NEW.status,NEW.article_id,NEW.id);
END;
CREATE TRIGGER IF NOT EXISTS notification_task_update AFTER UPDATE OF status ON tasks
WHEN OLD.status IS NOT NEW.status AND NEW.status IN ('queued','running','completed','error') BEGIN
 INSERT OR IGNORE INTO notification_events(event_key,kind,status,article_id,task_id)
 VALUES('task:'||NEW.id||':'||NEW.status,NEW.kind,NEW.status,NEW.article_id,NEW.id);
END;
CREATE TRIGGER IF NOT EXISTS notification_retention AFTER INSERT ON notification_events BEGIN
 DELETE FROM notification_events WHERE created_at < strftime('%Y-%m-%dT%H:%M:%fZ','now','-30 days');
END;
''')
    columns = {r[1] for r in c.execute('PRAGMA table_info(notification_events)')}
    for name in ('thread_id', 'turn_id', 'request_id', 'host_id', 'host_name', 'provider_id'):
        if name not in columns:
            c.execute('ALTER TABLE notification_events ADD COLUMN ' + name + ' TEXT')
    trigger=c.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='notification_workbench_read_insert'").fetchone()
    if trigger and 'provider_id' not in trigger[0]:c.execute('DROP TRIGGER notification_workbench_read_insert')
    c.executescript('''
CREATE TABLE IF NOT EXISTS notification_workbench_reads(
 host_id TEXT NOT NULL,thread_id TEXT NOT NULL,turn_id TEXT NOT NULL,status TEXT NOT NULL,
 read_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 PRIMARY KEY(host_id,thread_id,turn_id,status));
CREATE TRIGGER IF NOT EXISTS notification_workbench_read_insert AFTER INSERT ON notification_events
WHEN NEW.kind='workbench' AND NEW.read_at IS NULL AND coalesce(NEW.provider_id,'codex')='codex' BEGIN
 UPDATE notification_events SET read_at=(
  SELECT read_at FROM notification_workbench_reads
  WHERE host_id=coalesce(nullif(NEW.host_id,''),'local')
   AND thread_id=NEW.thread_id AND turn_id=NEW.turn_id AND status=NEW.status)
 WHERE id=NEW.id;
END;
CREATE TABLE IF NOT EXISTS notification_provider_reads(
 host_id TEXT NOT NULL,provider_id TEXT NOT NULL,thread_id TEXT NOT NULL,turn_id TEXT NOT NULL,status TEXT NOT NULL,
 read_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 PRIMARY KEY(host_id,provider_id,thread_id,turn_id,status));
CREATE TRIGGER IF NOT EXISTS notification_provider_read_insert AFTER INSERT ON notification_events
WHEN NEW.kind='workbench' AND NEW.read_at IS NULL AND coalesce(NEW.provider_id,'codex')<>'codex' BEGIN
 UPDATE notification_events SET read_at=(SELECT read_at FROM notification_provider_reads
 WHERE host_id=coalesce(nullif(NEW.host_id,''),'local') AND provider_id=NEW.provider_id
 AND thread_id=NEW.thread_id AND turn_id=NEW.turn_id AND status=NEW.status) WHERE id=NEW.id;
END;
''')

    retire(c)


def retire(c):
    # Preserve historical rows. Older idle workers may still issue notification
    # INSERTs, so the DB fence also covers their already-loaded code.
    for name in ('notification_task_insert','notification_task_update','notification_retention','notification_workbench_read_insert','notification_provider_read_insert'):
        c.execute('DROP TRIGGER IF EXISTS '+name)
    c.execute('CREATE TRIGGER IF NOT EXISTS notification_retired_insert BEFORE INSERT ON notification_events BEGIN SELECT RAISE(IGNORE); END')


def prune(c):
    return None


def news(c, run, source, count):
    return None


def latest(c):
    # AUTOINCREMENT high-water mark survives retention deleting the whole inbox.
    row = c.execute("SELECT seq FROM sqlite_sequence WHERE name='notification_events'").fetchone()
    return row[0] if row else 0


def register(store, device_id):
    raise ValueError('通知设备功能已退役')

def _production_context(connection, task_id):
    if connection is None or not task_id:
        return None
    try:
        row = connection.execute('''SELECT j.id,j.work_id,j.kind,j.status,j.dispatch_started,j.queue_id,
j.turn_id,j.error,j.created_at,j.started_at,j.finished_at,j.rollout_offset,
w.title AS work_title,coalesce(o.format,'poster') AS work_format
FROM toolbox_jobs j JOIN toolbox_works w ON w.id=j.work_id
LEFT JOIN toolbox_work_options o ON o.work_id=w.id WHERE j.id=?''', (task_id,)).fetchone()
    except sqlite3.OperationalError as error:
        # A legacy news-only Store can contain historical notification rows
        # before Toolbox has been initialized; do not create tables on reads.
        if 'no such table' in str(error):
            return None
        raise
    if row is None:
        return None
    value = dict(row)
    from easel_workbench.runtime.production_retry import recovery
    value['recovery'] = recovery(value, connection)
    return value


def message(row, sources, connection=None):
    item = dict(row)
    title = ' '.join((item.get('article_title') or ('作品任务' if item['kind']=='toolbox' else '新闻任务')).split())[:100]
    if item['kind'] in ('toolbox','toolbox_discuss'):
        context = _production_context(connection, item.get('task_id'))
        recovery = context.get('recovery') if context else None
        if context:
            title = ' '.join(context['work_title'].split())[:100] or '作品任务'
        label={'completed':'作品已就绪','blocked':'待补素材','error':'制作未完成'}.get(item['status'],'任务状态更新')
        if recovery:
            label = {'dispatch': '发送未成功', 'production': '制作未完成', 'uncertain': '结果待核对'}.get(recovery.get('failure_kind'), label)
            if recovery.get('failure_kind') == 'dispatch' and recovery.get('retry_exhausted'):
                label = '发送未成功，自动重试已用完'
            elif recovery.get('failure_kind') == 'dispatch' and recovery.get('automatic_enabled') and recovery.get('next_retry_at'):
                label = '发送未成功，等待自动重试'
        article = context and context['work_format'] == 'article'
        item.update(title=('文章制作' if article else '贴图制作')+' · '+label, body=title, url='/articles' if article else '/posters')
        if item['kind']=='toolbox_discuss':
            discussion_label = '答复已就绪' if item['status']=='completed' else '讨论未完成' if item['status']=='error' else label
            item['title']='作品讨论 · '+discussion_label
        if context:
            item['url'] += '/' + urllib.parse.quote(context['work_id'], safe='')
        if item.get('task_id'):
            item['url'] += '?' + urllib.parse.urlencode({'task':item['task_id']})
        if recovery:
            item['recovery'] = recovery
            explanation = recovery.get('message')
            if isinstance(explanation, str) and explanation.strip():
                item['body'] = title + '\n' + explanation
    elif item['kind'] == 'workbench':
        item.update(title='历史通知',body='原工作台通知已保留',url='/posters')
    elif item['kind'] == 'news':
        source = sources.get(item['source_job'], {}).get('name', '资讯来源')
        item.update(title=source + ' · 新资讯', body=f"新增 {item['item_count']} 条资讯", url='/news?' + urllib.parse.urlencode({'source': item['source_job']}))
    else:
        label = KINDS.get(item['kind'], '任务') + ' · ' + STATES.get(item['status'], '状态更新')
        item.update(title=label, body=title, url='/posters/legacy-' + str(item['article_id']))
    item.pop('article_title', None)
    item.pop('event_key', None)
    return item


ROWS = '''SELECT e.*,a.title AS article_title FROM notification_events e
LEFT JOIN articles a ON a.id=e.article_id'''


def inbox(store, sources, page=1, module=''):
    page = max(1, min(100000, int(page)))
    if module not in ('','all','workbench','news'):raise ValueError('invalid message module')
    where=" WHERE e.kind='workbench'" if module=='workbench' else " WHERE e.kind<>'workbench'" if module=='news' else ''
    with store.connect() as c:
        prune(c)
        total, unread = c.execute('SELECT count(*),coalesce(sum(read_at IS NULL),0) FROM notification_events').fetchone()
        if where:total=c.execute('SELECT count(*) FROM notification_events e'+where).fetchone()[0]
        rows = c.execute(ROWS + where + ' ORDER BY e.id DESC LIMIT 20 OFFSET ?', ((page-1)*20,)).fetchall()
        return {'items': [message(r, sources, c) for r in rows], 'total': total, 'unread': unread,
                'latest': latest(c), 'page': page, 'has_more': page*20 < total}


def mark_read(store, event_id):
    if event_id != 'all' and (type(event_id) is not int or event_id <= 0):
        raise ValueError('invalid message id')
    with store.connect() as c:
        if event_id == 'all':
            c.execute("UPDATE notification_events SET read_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE read_at IS NULL")
        else:
            c.execute("UPDATE notification_events SET read_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=? AND read_at IS NULL", (event_id,))
    return {'ok': True}


def poll(store, device_id, sources, origin):
    raise ValueError('通知设备功能已退役')
