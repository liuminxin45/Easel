"""Server-held completion form defaults; saving never grants delivery authority."""
from __future__ import annotations
import copy, hashlib, json
from easel_workbench.runtime.desk import stamp
from easel_workbench.runtime.toolbox_store import ident, pack, text


class PreferencesConflict(ValueError):
    pass


def initialize(c):
    c.execute('CREATE TABLE IF NOT EXISTS completion_preferences (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, document TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS completion_preference_operations (id TEXT PRIMARY KEY, signature TEXT NOT NULL, result TEXT NOT NULL)')


def _read(c):
    row=c.execute("SELECT revision,document FROM completion_preferences WHERE id='default'").fetchone()
    return {'revision':row['revision'],'completion':json.loads(row['document'])} if row else {'revision':0,'completion':{'mode':'archive','targets':[],'manual_publications':[]}}


def get(store):
    with store.connect() as c:
        initialize(c)
        return _read(c)


def normalize(value):
    if not isinstance(value,dict) or set(value)-{'mode','targets','manual_publications'}:
        raise ValueError('默认交付方式包含无关字段')
    if value.get('mode') not in ('archive','distribute'):
        raise ValueError('默认方式只能是仅归档或按所选渠道交付；已手动发布须逐篇确认')
    targets=value.get('targets',[]);manual=value.get('manual_publications',[])
    if not isinstance(targets,list) or not isinstance(manual,list) or len(targets)+len(manual)>20:
        raise ValueError('默认渠道列表无效')
    result={'mode':value['mode'],'targets':[],'manual_publications':[]};seen=set()
    for row in targets:
        if not isinstance(row,dict) or set(row)-{'connection_id','action'}:raise ValueError('默认账号字段无效')
        connection=ident(row.get('connection_id'));action=row.get('action')
        if action not in ('draft','publish'):raise ValueError('默认交付动作无效')
        if connection in seen:raise ValueError('同一账号不能重复配置')
        seen.add(connection);result['targets'].append({'connection_id':connection,'action':action})
    manual_seen=set()
    for row in manual:
        if not isinstance(row,dict) or set(row)-{'channel_id','account','status','url','published_at'}:raise ValueError('默认手动渠道字段无效')
        if row.get('status','draft')!='draft' or row.get('url') or row.get('published_at'):
            raise ValueError('默认方式不能预先声明作品已发布')
        channel=ident(row.get('channel_id'));account=text(row.get('account',''),200,True)
        identity=(channel,account)
        if identity in manual_seen:raise ValueError('手动渠道不能重复配置')
        manual_seen.add(identity);result['manual_publications'].append({'channel_id':channel,'account':account,'status':'draft'})
    if result['mode']=='archive' and (targets or manual):raise ValueError('仅归档不包含发布渠道')
    if result['mode']=='distribute' and not (targets or manual):raise ValueError('请选择交付渠道')
    return result


def save(store,value):
    if not isinstance(value,dict) or set(value)-{'id','operation_id','expected_revision','completion'}:raise ValueError('保存默认方式包含无关字段')
    oid=ident(value.get('operation_id') or value.get('id'))
    if value.get('id') and value['id']!=oid:raise ValueError('操作标识不一致')
    expected=value.get('expected_revision')
    if type(expected) is not int or expected<0:raise ValueError('请先读取当前默认方式')
    completion=normalize(value.get('completion'));signature=hashlib.sha256(pack({'completion':completion,'expected_revision':expected}).encode()).hexdigest()
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE');initialize(c)
        old=c.execute('SELECT signature,result FROM completion_preference_operations WHERE id=?',(oid,)).fetchone()
        if old:
            if old['signature']!=signature:raise PreferencesConflict('同一操作不能保存不同默认方式')
            return json.loads(old['result'])
        before=_read(c)
        if before['revision']!=expected:raise PreferencesConflict('默认方式已在其他设备更新，请重新核对')
        result={'revision':expected+1,'completion':copy.deepcopy(completion),'updated_at':stamp(),'authorizes_delivery':False}
        c.execute("INSERT INTO completion_preferences VALUES('default',?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,document=excluded.document",(result['revision'],pack(completion)))
        c.execute('INSERT INTO completion_preference_operations VALUES(?,?,?)',(oid,signature,pack(result)))
        return result
