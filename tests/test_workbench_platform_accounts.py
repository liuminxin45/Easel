"""TEMP-only native account migration, identity and delivery boundary regressions."""
import asyncio
import importlib.util
import json
import io
from pathlib import Path
from types import SimpleNamespace

import pytest

spec=importlib.util.spec_from_file_location('platform_account_fixtures',Path(__file__).with_name('test_workbench_skill_commands.py'))
fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
runtime,commands=fixtures.runtime,fixtures.commands
from easel_workbench.runtime.easel_accounts import EaselAccounts
from easel_workbench.runtime.easel_distribution import EaselDistributionRuntime
from easel_workbench.runtime.distribution_service import DistributionService,digest


class Vault:
    def put(self,sid,value):self.value=value;return 'vault-private-ref'
    def get(self,ref,sid):return self.value


@pytest.fixture
def accounts(commands):
    distribution=DistributionService(commands)
    account=EaselAccounts(commands,distribution,autostart=False,vault=Vault(),runner=lambda payload:{'loggedIn':True,'provider_user_id':'gh_exact','name':'准确账号'})
    commands.easel_accounts=account
    return account


def create(account,platform='wechat-oa',**fields):
    return account.command({'id':'create-'+platform,'action':'create','platform':platform,**fields})['result']['session']


def login(account,session):
    value=account.command({'id':'login-'+session['id'],'action':'login','session_id':session['id'],'base_revision':session['revision']})['result']['session']
    account.run(value['id'],value['revision'],'login')
    return account.bootstrap()['sessions'][0]


@pytest.mark.parametrize('platform',['wechat-oa','weixin-channels','xiaohongshu','douyin','kuaishou','zhihu','bilibili'])
def test_platform_can_connect_directly_without_extension_or_required_custom_name(accounts,platform):
    session=login(accounts,create(accounts,platform))
    assert session['state']=='connected' and session['identity_status']=='resolved'
    assert session['label'] and session['connection_id']
    assert not any(key.startswith('_') for key in session)
    connection=accounts.distribution.connection_internal(session['connection_id'])
    capability=accounts.capability(connection,'draft' if platform=='wechat-oa' else 'publish')
    assert capability['status']==('unsupported' if platform=='bilibili' else 'trial') and capability['account_verified'] and not capability['verified']


def test_reconnect_keeps_legacy_connection_identity_and_original_history(accounts):
    old={'id':'old-account','platform':'wechat_article','account':'gh_exact','label':'原账号','revision':7,'enabled':True,'created_at':'original','secret_ref':'keep-original-encrypted-ref'}
    with accounts.store.connect() as c:accounts.distribution._put(c,'connections',old)
    result=login(accounts,create(accounts,connection_id=old['id']))
    current=accounts.distribution.connection_internal(old['id'])
    assert result['connection_id']==old['id'] and current['account']==old['account']
    assert current['created_at']=='original' and current['revision']==8
    assert current['secret_ref']==old['secret_ref'] and current['connector']=='easel'


def test_wrong_scan_never_replaces_a_historical_account(accounts):
    old={'id':'old-account','platform':'wechat_article','account':'gh_other','label':'原账号','revision':7,'enabled':True}
    with accounts.store.connect() as c:accounts.distribution._put(c,'connections',old)
    session=login(accounts,create(accounts,connection_id=old['id']))
    assert session['state']=='account_mismatch'
    assert accounts.distribution.connection_internal(old['id'])==old


def test_credentials_are_not_a_browser_login_and_do_not_rebind_scan_identity(accounts):
    session=login(accounts,create(accounts))
    accounts.runner=lambda payload:{'loggedIn':True,'provider_user_id':'wx_api_appid','name':'接口凭据'}
    result=accounts.command({'id':'save-api-credential','action':'credentials','session_id':session['id'],'base_revision':session['revision'],'app_id':'wx_api_appid','app_secret':'private-never-return'})['result']['session']
    accounts.run(result['id'],result['revision'],'probe')
    current=accounts.bootstrap()['sessions'][0]
    assert current['state']=='connected' and current['account']=='gh_exact' and current['credentials_verified']
    assert 'private-never-return' not in json.dumps(current) and 'wx_api_appid' not in json.dumps(current)


def test_login_uses_revision_bound_refreshing_qr_and_does_not_leak_paths(accounts):
    session=create(accounts);value=accounts.command({'id':'login','action':'login','session_id':session['id'],'base_revision':1})['result']['session']
    directory=accounts.root/'data/easel-accounts'/session['id'];directory.mkdir(parents=True)
    (directory/'login.json').write_text(json.dumps({'state':'qr_ready','qr':'private-cookie-path','message':'private-cookie-value'}),encoding='utf-8')
    image=directory/'qr.png';image.write_bytes(b'qr-one')
    first=accounts.bootstrap()['sessions'][0]
    image.write_bytes(b'qr-two-new-bytes');second=accounts.bootstrap()['sessions'][0]
    assert first['qr_url']!=second['qr_url'] and 'revision=2' in first['qr_url']
    assert 'private-cookie' not in json.dumps(first)


def test_sms_code_has_one_persistent_receipt_without_entering_public_records(accounts):
    session=create(accounts,'douyin');value=accounts.command({'id':'login','action':'login','session_id':session['id'],'base_revision':1})['result']['session']
    directory=accounts.root/'data/easel-accounts'/session['id'];directory.mkdir(parents=True)
    (directory/'login.json').write_text('{"state":"sms_required"}',encoding='utf-8')
    command={'id':'sms-once','action':'sms','session_id':session['id'],'base_revision':value['revision'],'code':'983124'}
    first=accounts.command(command);assert accounts.command(command)==first
    assert (directory/'douyin.code').read_text()=='983124'
    with accounts.store.connect() as c:
        assert '983124' not in c.execute('SELECT result FROM media_operations WHERE id=?',('sms-once',)).fetchone()[0]
    assert '983124' not in json.dumps(accounts.bootstrap())


def test_disconnect_during_login_prevents_a_late_success_from_reconnecting(accounts):
    session=create(accounts)
    def late(payload):
        accounts.command({'id':'disconnect','action':'logout','session_id':session['id'],'base_revision':2})
        return {'loggedIn':True,'provider_user_id':'gh_exact','name':'late'}
    accounts.runner=late
    result=login(accounts,session)
    assert result['state']=='not_connected' and not result.get('connection_id')


def test_dead_login_owner_becomes_unknown_without_replaying(accounts,monkeypatch):
    session=create(accounts);accounts.command({'id':'login','action':'login','session_id':session['id'],'base_revision':1})
    accounts.autostart=True
    monkeypatch.setattr('easel_workbench.runtime.distribution_runtime.process_identity',lambda pid:None)
    assert accounts.bootstrap()['sessions'][0]['state']=='unknown'


def test_native_runtime_never_falls_back_to_the_browser_extension(accounts):
    class Forbidden:
        def __getattr__(self,name):pytest.fail('Extension fallback was accessed: '+name)
    runtime=EaselDistributionRuntime(accounts.box,Forbidden())
    connection={'id':'old','platform':'wechat_article','account':'original','enabled':True}
    assert runtime.capability(connection,'draft')['status']=='unsupported'
    assert not runtime.probe(connection)['logged_in']
    assert runtime.verify({}, {}, connection,{})['remote_state']=='unknown'
    assert runtime.summary()['connector']=='easel' and not runtime.summary()['extension_required']


def test_native_sender_rejects_missing_boundary_tampering_and_requires_explicit_trial(accounts):
    session=login(accounts,create(accounts,'weixin-channels'));connection=accounts.distribution.connection_internal(session['connection_id'])
    revision={'id':'exact-revision','connection_id':connection['id'],'platform':connection['platform'],'account':connection['account'],'asset_manifest':[],'title':'准确标题','body':'原字正文'}
    revision['hash']=digest({k:v for k,v in revision.items() if k not in ('id','created_at','hash')})
    delivery={'id':'delivery','connection_id':connection['id'],'platform':connection['platform'],'account':connection['account'],'action':'publish','pilot':True}
    claim={'delivery':delivery,'revision':revision,'connection':connection,'attempt':{'id':'attempt'},'lease_token':'lease'}
    calls=[];runtime=EaselDistributionRuntime(accounts.box,runner=lambda payload:calls.append(payload) or {'verified':False,'remote_id':'ack-only'})
    with pytest.raises(ValueError,match='发送边界'):runtime.send(claim,[])
    with accounts.store.connect() as c:accounts.distribution._put(c,'attempts',{'id':'attempt','delivery_id':'delivery','status':'leased','lease_token':'lease','dispatched_at':'actual'})
    assert runtime.send(claim,[])['remote_state']=='unknown' and len(calls)==1
    revision['body']='tampered'
    with pytest.raises(ValueError):runtime.send(claim,[])
    assert len(calls)==1
    delivery['pilot']=False
    with pytest.raises(ValueError,match='试运行'):runtime.send(claim,[])


@pytest.mark.parametrize('path',['/api/distribution/bridge/form','/api/distribution/bridge/configure','/api/distribution/discover','/api/distribution/browser','/api/distribution/checks/original','/api/distribution/credentials/form'])
def test_old_extension_endpoints_are_retired_without_invoking_any_driver(path):
    from easel_workbench.runtime.distribution_api import handle
    from starlette.requests import Request
    service=SimpleNamespace(runtime=SimpleNamespace(extension_retired=True))
    request=Request({'type':'http','method':'GET','path':path,'headers':[]})
    response=asyncio.run(handle(service,path,request,{},True,b'','csrf',None))
    assert response.status_code==410 and json.loads(response.body)['retired']


def test_old_check_page_clears_ticket_fragment_and_reports_stop_polling():
    from easel_workbench.runtime.distribution_check_api import public
    service=SimpleNamespace(runtime=SimpleNamespace(extension_retired=True))
    page=asyncio.run(public(service,'/distribution/check',None,False,b''))
    assert page.status_code==303 and page.headers['location'].endswith('#')
    assert asyncio.run(public(service,'/api/distribution/check-report',None,False,b'')).status_code==410


def test_upstream_publisher_receives_exact_profile_and_ack_is_not_readback(tmp_path,monkeypatch,capsys):
    from easel_workbench.runtime import easel_publish_worker as worker
    import os,sys
    payload={'session':{'platform':'wechat-oa','state':'connected','account':'gh_exact'},'directory':str(tmp_path),'delivery_id':'exact-delivery','action':'draft','revision':{'title':'原字标题','body':'<script>plain text</script>','account':'gh_exact'},'assets':[{'mime':'image/png','path':'approved.png'}]}
    calls=[]
    monkeypatch.setattr(os,'environ',dict(os.environ));monkeypatch.setattr(sys,'argv',sys.argv[:])
    monkeypatch.chdir(Path.cwd());monkeypatch.setattr(worker,'safe_env',lambda values,directory:dict(os.environ))
    monkeypatch.setattr(worker.subprocess,'run',lambda *args,**kwargs:SimpleNamespace(stdout=json.dumps({'loggedIn':True,'provider_user_id':'gh_exact'})))
    module=SimpleNamespace(main=lambda:calls.append(sys.argv[:]) or print('{"success":true,"media_id":"remote-ack"}'))
    original=worker.importlib.import_module
    monkeypatch.setattr(worker.importlib,'import_module',lambda name:module if name=='weixin_mp_stats' else SimpleNamespace() if name=='platform_readback' else original(name))
    monkeypatch.setattr(sys,'stdin',io.StringIO(json.dumps(payload)))
    worker.main();result=json.loads(capsys.readouterr().out)
    assert result['media_id']=='remote-ack' and result['readback']['outcome']=='unverified'
    assert calls[0][calls[0].index('--profile-base')+1]==str(tmp_path/'profiles-0')
    assert '&lt;script&gt;' in (tmp_path/'draft-exact-delivery.html').read_text()


@pytest.mark.parametrize('change',['account','title','time','state','ack'])
def test_readback_needs_exact_identity_title_remote_id_and_time(accounts,change):
    runtime=EaselDistributionRuntime(accounts.box)
    revision={'title':'准确标题','hash':'frozen'};connection={'account':'uid','platform':'douyin_video'}
    result={'account':'uid','readback':{'outcome':'verified','matched':{'title':'准确标题','platform_content_id':'1234','status':'published','published_at_ms':1700000000000}}}
    if change=='account':result['account']='another'
    if change=='title':result['readback']['matched']['title']='another'
    if change=='time':result['readback']['matched'].pop('published_at_ms')
    if change=='state':result['readback']['matched']['status']='unknown'
    if change=='ack':result={'account':'uid','media_id':'ack','readback':{'outcome':'unverified'}}
    assert not runtime._remote(result,revision,connection)['verified']


def test_channels_upstream_timeout_recovery_cannot_press_publish_twice():
    from easel_workbench.runtime.easel_publish_worker import single_channel_submission,SubmissionAlreadyAttempted
    presses=[];keyboard=SimpleNamespace(press=lambda key:presses.append(key));page=SimpleNamespace(keyboard=keyboard)
    def upstream(page,context):
        for attempt in range(3):
            try:
                page.keyboard.press('Enter')
                raise TimeoutError('Acknowledgement unknown')
            except Exception:continue
    module=SimpleNamespace(_publish_weixin_channels=upstream);single_channel_submission(module)
    with pytest.raises(SubmissionAlreadyAttempted):module._publish_weixin_channels(page,{})
    assert presses==['Enter']
    keyboard.press('after-wrapper');assert presses==['Enter','after-wrapper']
