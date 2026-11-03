"""Only the private source-to-conversation association; no chat execution."""
import json
from .receipts import ChatConflict,identity,now

def initialize(c):
    c.execute('CREATE TABLE IF NOT EXISTS native_news_conversations(article_id TEXT NOT NULL,profile_id TEXT NOT NULL,session_id TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(article_id,profile_id))')

def current(c,article_id,profile_id):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='native_news_conversations'").fetchone():return None
    row=c.execute('SELECT s.document FROM native_news_conversations n JOIN easel_chat_sessions s ON s.id=n.session_id WHERE n.article_id=? AND n.profile_id=?',(identity(article_id),identity(profile_id))).fetchone()
    return json.loads(row[0]) if row else None

def creation(c,value):
    aid=value.get('news_article_id')
    if aid is None:return None,None
    aid=identity(aid);pid=identity(value.get('profile_id') or 'oil-pig')
    if not c.execute('SELECT 1 FROM articles WHERE id=?',(aid,)).fetchone():raise ValueError('新闻材料不存在')
    if not c.execute('SELECT 1 FROM creator_profiles WHERE id=?',(pid,)).fetchone():raise ValueError('画像不存在')
    fresh=value.get('news_new_session',False)
    if type(fresh) is not bool:raise ValueError('重新开始标识无效')
    session=current(c,aid,pid)
    if session and (session.get('archived') or session.get('deleted_at')):
        if not fresh:raise ChatConflict('关联对话已归档或删除，请明确重新开始')
        session=None
    elif session and fresh:raise ChatConflict('已有可用讨论会话，请先查看，不能重复创建')
    return aid,session

def bind(c,article_id,session):
    if article_id:c.execute('INSERT INTO native_news_conversations VALUES(?,?,?,?) ON CONFLICT(article_id,profile_id) DO UPDATE SET session_id=excluded.session_id,updated_at=excluded.updated_at',(article_id,session['profile_id'],session['id'],now()))

def summary(session):
    if not session:return None
    return {key:session.get(key) for key in ('id','profile_id','title','runtime','archived','deleted_at','pendingTurnId','pendingSubmissionId','source_article_id')}
