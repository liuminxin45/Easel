"""Server-owned creative inputs. Saving never schedules AI; production freezes a revision."""
import json
from easel_workbench.runtime.desk import stamp
from easel_workbench.runtime.toolbox_store import ident, text, pack, ACTIVE


class DraftConflict(ValueError):
    pass


def initialize(connection):
    connection.executescript('''
CREATE TABLE IF NOT EXISTS toolbox_article_drafts(work_id TEXT PRIMARY KEY,revision INTEGER NOT NULL,document TEXT NOT NULL,submitted_revision INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS toolbox_article_draft_ops(id TEXT PRIMARY KEY,work_id TEXT NOT NULL,signature TEXT NOT NULL,result TEXT NOT NULL,document TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS toolbox_article_inputs(job_id TEXT PRIMARY KEY,revision INTEGER NOT NULL,document TEXT NOT NULL);
''')


def read(box, wid, connection):
    row = connection.execute('SELECT * FROM toolbox_article_drafts WHERE work_id=?', (wid,)).fetchone()
    if row:
        return {**json.loads(row['document']), 'revision': row['revision'], 'submitted_revision': row['submitted_revision']}
    work = connection.execute('SELECT * FROM toolbox_works WHERE id=?', (wid,)).fetchone()
    if not work:
        raise ValueError('作品不存在')
    original = connection.execute("SELECT text,files FROM toolbox_jobs WHERE work_id=? AND kind='create' ORDER BY rowid LIMIT 1", (wid,)).fetchone()
    return {'title': work['title'], 'material': work['material'], 'guidance': original['text'] if original else '',
            'files': json.loads(original['files']) if original else [], 'article_mode': box.options(wid, connection)['article_mode'],
            'revision': 0, 'submitted_revision': 0}


def save(box, value, wid=None):
    operation = ident(value.get('id')); wid = ident(wid or operation)
    revision = value.get('revision')
    if type(revision) is not int or revision < 0:
        raise ValueError('草稿版本无效')
    document = {name: text(value.get(name, ''), limit) for name, limit in [('title', 500), ('material', 100000), ('guidance', 10000)]}
    mode = value.get('article_mode', 'auto')
    if mode not in ('auto', 'product'):
        raise ValueError('文章类型无效')
    document['article_mode'] = mode
    format = value.get('format', 'article')
    if format not in ('article', 'poster'):
        raise ValueError('制作类型无效')
    signature = pack({'work_id': wid, 'request': value}); now = stamp()
    with box.store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        old = c.execute('SELECT * FROM toolbox_article_draft_ops WHERE id=?', (operation,)).fetchone()
        if old:
            if old['signature'] != signature:
                raise ValueError('同一操作 ID 不能用于不同内容')
            return json.loads(old['result'])
        if c.execute('SELECT 1 FROM toolbox_jobs WHERE id=?', (operation,)).fetchone():
            raise ValueError('操作 ID 已用于制作任务')
        document['files'] = json.loads(box._files(c, value.get('files', [])))
        if not any(document[name].strip() for name in ('title', 'material', 'guidance')) and not document['files']:
            raise ValueError('请先添加灵感、口述稿、链接或附件')
        work = c.execute('SELECT * FROM toolbox_works WHERE id=?', (wid,)).fetchone()
        if work:
            if 'format' in value and box.options(wid, c)['format'] != format:
                raise ValueError('草稿类型与作品不符')
            current = read(box, wid, c)
        else:
            if revision != 0:
                raise DraftConflict('草稿版本已变化，请重新打开；本机输入仍保留')
            current = {'revision': 0, 'submitted_revision': 0}
            aid = value.get('article_id') or None
            if aid:
                source=c.execute('SELECT * FROM articles WHERE id=?',(ident(aid),)).fetchone()
                if not source:raise ValueError('资讯不存在')
                document['title']=document['title'] or source['title']
                if not document['material'].strip():
                    document['material']=source['body']+'\n\n来源：'+source['url']
            c.execute('INSERT INTO toolbox_works VALUES(?,?,?,?,?,?)', (wid, aid, '未命名作品', '', now, now))
            c.execute('INSERT INTO toolbox_work_options VALUES(?,?,?)', (wid, format, mode))
            from easel_workbench.runtime.local_operations import reserve_work
            reserve_work(c,wid,document['title'] or next((line.strip()[:120] for line in document['material'].splitlines() if line.strip()),'未命名作品'))
        if revision != current['revision']:
            raise DraftConflict('其他页面已更新草稿，请重新打开后合并；本机输入仍保留')
        if 'creative' in value or 'creative' in current:
            from easel_workbench.runtime.content_studio import options
            document['creative']=options(value.get('creative',current.get('creative')))
        from easel_workbench.runtime.creator_runtime import service as creator_service,read_owner,CreatorConflict
        selection=document.get('creative',{}).get('creator')
        owner=read_owner(c,wid)
        # Saving binds the selected identity, without resolving generation
        # skills or creating a model task. Existing legacy drafts stay legacy.
        if selection is not None or owner or not work and getattr(box,'creator',None):
            try:creator_service(box,c).bind_work(c,wid,selection,allow_historical=bool(work))
            except CreatorConflict as exc:raise DraftConflict(str(exc)) from exc
        title = document['title'].strip() or next((line.strip()[:120] for line in (document['material'] or document['guidance']).splitlines() if line.strip()), '素材文章')
        result = {'work_id': wid, 'revision': revision + 1, 'status': 'draft'}
        c.execute('INSERT OR REPLACE INTO toolbox_article_drafts VALUES(?,?,?,?)', (wid, revision + 1, pack(document), current['submitted_revision']))
        # Work material remains the original input. Every dispatched job has its own snapshot.
        c.execute('UPDATE toolbox_works SET title=?,updated_at=? WHERE id=?', (title, now, wid))
        c.execute('INSERT INTO toolbox_article_draft_ops VALUES(?,?,?,?,?,?)', (operation, wid, signature, pack(result), pack(document), now))
    return result


def finalize(box, wid, value):
    wid = ident(wid); jid = ident(value.get('id')); revision = value.get('revision')
    if type(revision) is not int or revision < 1:
        raise ValueError('请先保存草稿再成稿')
    signature = pack({'article_draft': wid, 'request': value}); now = stamp()
    with box.store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        old = c.execute('SELECT * FROM toolbox_jobs WHERE id=?', (jid,)).fetchone()
        if old:
            if old['signature'] != signature or old['work_id'] != wid:
                raise ValueError('同一操作 ID 不能用于不同内容')
            return {'id': jid, 'work_id': wid, 'status': old['status']}
        if c.execute('SELECT 1 FROM toolbox_article_draft_ops WHERE id=?', (jid,)).fetchone():
            raise ValueError('操作 ID 已用于保存草稿')
        draft = read(box, wid, c)
        if revision != draft['revision']:
            raise DraftConflict('草稿已变化，请重新读取并确认本次成稿内容')
        pending = c.execute('SELECT status FROM toolbox_jobs WHERE work_id=?', (wid,)).fetchall()
        if any(row['status'] in ACTIVE for row in pending):
            raise DraftConflict('已有任务处理中或回执待核对，请先查看制作进度')
        document = {key: draft[key] for key in ('title', 'material', 'guidance', 'files', 'article_mode')}
        box._files(c, document['files'])
        from easel_workbench.runtime.production_outcome import assess
        candidate = next((row for row in c.execute("SELECT * FROM toolbox_jobs WHERE work_id=? AND kind IN ('create','change') AND status='completed' ORDER BY rowid DESC", (wid,))
                          if assess(box,c,dict(row))['status']=='completed'), None)
        from easel_workbench.runtime.work_discussions import freeze,production_token
        document.update(freeze(c,wid,candidate['id'] if candidate else None))
        if value.get('discussion_token',document['discussion_token'])!=document['discussion_token']:
            raise DraftConflict('讨论已有更新，请重新读取后再制作')
        if draft['submitted_revision'] == revision and production_token(c,wid)==document['discussion_token']:
            raise DraftConflict('这份草稿与讨论已提交制作；请查看原任务，补充或修改后再制作')
        c.execute('INSERT INTO toolbox_jobs(id,work_id,kind,text,candidate_id,files,signature,status,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
                  (jid, wid, 'change' if candidate else 'create', document['guidance'], candidate['id'] if candidate else None, pack(document['files']), signature, 'queued', now))
        c.execute('INSERT INTO toolbox_article_inputs VALUES(?,?,?)', (jid, revision, pack(document)))
        c.execute('UPDATE toolbox_article_drafts SET submitted_revision=? WHERE work_id=?', (revision, wid))
        c.execute('UPDATE toolbox_works SET updated_at=? WHERE id=?', (now, wid))
        work=c.execute('SELECT article_id FROM toolbox_works WHERE id=?',(wid,)).fetchone()
        if work['article_id'] and box.options(wid,c)['format']=='poster' and c.execute("SELECT count(*) FROM toolbox_jobs WHERE work_id=? AND kind='create'",(wid,)).fetchone()[0]==1 and not candidate:
            c.execute('UPDATE articles SET selected=1 WHERE id=?',(work['article_id'],))
            from easel_workbench.runtime import news_feedback as news_feedback
            news_feedback.enqueue(c,work['article_id'],document['guidance'],task_id=jid,created_at=now)
        from easel_workbench.runtime.work_review import freeze as freeze_review
        parent=c.execute("SELECT id FROM toolbox_jobs WHERE work_id=? AND id!=? AND kind IN ('create','change') AND status='completed' ORDER BY julianday(created_at) DESC,rowid DESC LIMIT 1",(wid,jid)).fetchone()
        freeze_review(box,c,wid,jid,parent['id'] if parent else None,creation=value.get('creative',draft.get('creative')))
    return {'id': jid, 'work_id': wid, 'status': 'queued'}


def job_work(work, jid, connection):
    seen = set()
    while jid and jid not in seen:
        seen.add(jid)
        snapshot = connection.execute('SELECT revision,document FROM toolbox_article_inputs WHERE job_id=?', (jid,)).fetchone()
        if snapshot:
            return {**work, **json.loads(snapshot['document']), 'draft_revision': snapshot['revision']}
        job = connection.execute('SELECT candidate_id FROM toolbox_jobs WHERE id=?', (jid,)).fetchone()
        jid = job['candidate_id'] if job else None
    return work
