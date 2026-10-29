"""Public account observations are hints, never server-side authorization."""
from __future__ import annotations
import hashlib,json
from easel_workbench.runtime.desk import stamp
from easel_workbench.runtime.toolbox_store import ident,pack,text
from easel_workbench.runtime.distribution_service import DistributionConflict
from easel_workbench.runtime.distribution_catalog import PROVIDER_NAMES as PLATFORMS, PLATFORM_IDS as IMPORT_PLATFORMS, IMPORTABLE_PROVIDERS, identity_metadata, plain_text
from easel_workbench.runtime.feedback_ledger import locked


def accounts(value):
    if not isinstance(value,list) or len(value)>100:raise ValueError('账号列表格式无效')
    result=[];seen=set()
    for row in value:
        if not isinstance(row,dict):continue
        platform=row.get('type') or row.get('platform')
        if not isinstance(platform,str) or platform not in PLATFORMS:continue
        account=row.get('uid',row.get('account',''))
        if plain_text(account) is None:continue
        key=(platform,account)
        if key in seen:continue
        seen.add(key)
        result.append({'platform':platform,'account':account,'name':PLATFORMS[platform],
            'reported_authenticated':True,'verified':False,'can_import':platform in IMPORTABLE_PROVIDERS and bool(account.strip()), **identity_metadata(row)})
    return result

def observe(service,value):
    key=ident(value.get('operation_id') or value.get('id'))
    safe=accounts(value.get('accounts'))
    signature=hashlib.sha256(pack(safe).encode()).hexdigest()
    with locked(service.root/'data/distribution-observations.lock'),service.store.connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS distribution_observations(id TEXT PRIMARY KEY,signature TEXT NOT NULL,document TEXT NOT NULL,created_at TEXT NOT NULL)')
        old=c.execute('SELECT * FROM distribution_observations WHERE id=?',(key,)).fetchone()
        if old:
            if old['signature']!=signature:raise DistributionConflict('同一检查操作的账号结果发生变化')
            return json.loads(old['document'])
        document={'status':'observed','source':'browser_extension','accounts':safe,'checked_at':stamp(),
                  'verified':False,'message':'浏览器扩展报告的当前登录账号；后台执行仍需准确账号核验。'}
        c.execute('INSERT INTO distribution_observations VALUES(?,?,?,?)',(key,signature,pack(document),document['checked_at']))
    return document

def latest(service):
    with service.store.connect() as c:
        exists=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='distribution_observations'").fetchone()
        row=c.execute('SELECT document FROM distribution_observations ORDER BY created_at DESC,rowid DESC LIMIT 1').fetchone() if exists else None
    return json.loads(row['document']) if row else {'status':'not_observed','accounts':[],'source':'browser_extension','verified':False,'checked_at':None}

def import_account(service,value):
    key=ident(value.get('operation_id') or value.get('id'));platform=value.get('platform')
    if platform not in IMPORT_PLATFORMS:raise ValueError('此平台尚未接入工作台')
    account=text(value.get('account',''),200,True)
    if not account.strip() or plain_text(account) is None:raise ValueError('未取得可接入的账号名称')
    label=text(value.get('label') or account,200,True)
    signature=hashlib.sha256(pack({'platform':platform,'account':account,'label':label}).encode()).hexdigest()
    with locked(service.root/'data/distribution-import.lock'):
        with service.store.connect() as c:
            c.execute('CREATE TABLE IF NOT EXISTS distribution_import_operations(id TEXT PRIMARY KEY,signature TEXT NOT NULL,command TEXT,result TEXT)')
            old=c.execute('SELECT * FROM distribution_import_operations WHERE id=?',(key,)).fetchone()
            if old:
                if old['signature']!=signature:raise DistributionConflict('同一接入操作不能更换账号')
                if old['result']:return json.loads(old['result'])
                fields=json.loads(old['command'])
            else:
                if c.execute('SELECT 1 FROM distribution_operations WHERE operation_id=?',(key,)).fetchone():
                    raise DistributionConflict('接入操作标识已被使用')
                connections=service._records(c,'connections')
        if not old:
            existing=next((item for item in connections if item['platform']==platform and item['account']==account),None)
            if existing:
                from easel_workbench.runtime.distribution_service import _public
                result={'status':'completed','operation_id':key,'result':{'connection':_public(existing),'already_exists':True}}
                with service.store.connect() as c:c.execute('INSERT INTO distribution_import_operations VALUES(?,?,NULL,?)',(key,signature,pack(result)))
                return result
            connection_id='account-'+hashlib.sha256(pack([platform,account]).encode()).hexdigest()[:40]
            fields={'action':'connection-save','operation_id':key,'connection_id':connection_id,'platform':platform,'account':account,'label':label,'enabled':True,'expected_revision':0}
            if callable(getattr(service.runtime,'bridge_status',None)) and service.runtime.bridge_status().get('configured'):
                fields['secret_ref']=service.runtime.credentials_for_connection(connection_id)
            with service.store.connect() as c:c.execute('INSERT INTO distribution_import_operations VALUES(?,?,?,NULL)',(key,signature,pack(fields)))
        result=service.command(fields,actor='owner')
        with service.store.connect() as c:c.execute('UPDATE distribution_import_operations SET result=? WHERE id=?',(pack(result),key))
        return result
