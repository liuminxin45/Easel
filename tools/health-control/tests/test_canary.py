import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pytest
from PIL import Image,ImageDraw
from PIL.PngImagePlugin import PngInfo

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from easel_health_control import canary,canary_worker
from easel_health_control.state import StateStore


def config(tmp_path):
    return {'application_root':str(tmp_path/'app'),'python_executable':sys.executable}


def test_daily_intent_precedes_child_and_same_day_never_sends_twice(tmp_path):
    cfg=config(tmp_path);root=tmp_path/'controller';calls=[]
    def runner(command,**kwargs):
        calls.append(command)
        if '--inspect' in command:return SimpleNamespace(stdout=json.dumps({'operation_id':operation['operation_id'],'status':'completed'}))
        intent=StateStore(root/'canary').read('operation.json')
        assert intent['worker_launch_attempted'] and not intent['dispatch_started'] and intent['status']=='launching'
        request=json.loads(Path(command[-1]).read_text(encoding='utf-8'))
        StateStore(request['workspace']).write('receipt.json',{'operation_id':request['operation_id'],'status':'completed'})
        return SimpleNamespace(returncode=0,stdout='')
    first=canary.run_daily(cfg,root,execute=True,clock=lambda:1793670000,runner=runner)
    operation=first
    second=canary.run_daily(cfg,root,execute=True,clock=lambda:1793670001,runner=runner)
    assert first['operation_id']==second['operation_id']
    assert len([x for x in calls if '--inspect' not in x])==1


def test_unknown_launch_is_only_inspected_even_next_day(tmp_path):
    cfg=config(tmp_path);root=tmp_path/'controller';calls=[]
    def runner(command,**kwargs):
        calls.append(command)
        if '--inspect' in command:return SimpleNamespace(stdout=json.dumps({'operation_id':op['operation_id'],'status':'unknown'}))
        raise OSError('process receipt lost')
    first=canary.run_daily(cfg,root,execute=True,clock=lambda:1793670000,runner=runner);op=first
    assert first['status']=='unknown'
    same=canary.run_daily(cfg,root,execute=True,clock=lambda:1793670001,runner=runner)
    later=canary.run_daily(cfg,root,execute=True,clock=lambda:1793756401,runner=runner)
    assert same['status']=='unknown' and later['reason']=='previous_native_receipt_unresolved'
    assert len([x for x in calls if '--inspect' not in x])==1


def test_workspace_cannot_be_inside_production(tmp_path):
    with pytest.raises(ValueError,match='external'):
        canary.run_daily({'application_root':str(tmp_path)},tmp_path/'state',execute=True)


def image_database(tmp_path):
    root=tmp_path/'project';(root/'data').mkdir(parents=True);tid='op-poster'
    image=root/'data/image.png';im=Image.new('RGB',(640,640),'white');draw=ImageDraw.Draw(im)
    for n in range(0,640,10):draw.line((0,n,640,640-n),fill=(n%255,60,130),width=2)
    draw.text((30,30),'real tool canary op',fill='black');info=PngInfo();info.add_text('easel_canary_operation','op');im.save(image,pnginfo=info)
    db=root/'data/desk.sqlite'
    with sqlite3.connect(db) as c:
        c.executescript('CREATE TABLE easel_chat_turns(id TEXT PRIMARY KEY,document TEXT);CREATE TABLE artifacts(id TEXT,task_id TEXT,path TEXT,mime TEXT);CREATE TABLE toolbox_jobs(id TEXT,kind TEXT);')
        c.execute('INSERT INTO easel_chat_turns VALUES(?,?)',(tid,json.dumps({'status':'completed','hook_status':'completed','runtime':'codex','native_id':'native-new','native_turn_id':'native-turn','message':'canary op','runner':'easel.harnesses.codex.CodexAdapter','work':{'version_id':tid}})))
        c.execute('INSERT INTO artifacts VALUES(?,?,?,?)',('image',tid,str(image),'image/png'))
    folder=root/'outputs/_sessions/jobs';folder.mkdir(parents=True)
    (folder/(tid+'.jsonl')).write_text(json.dumps({'event':'activity','data':'工具：commandExecution'})+'\n',encoding='utf-8')
    return root,tid,image


def test_image_receipt_requires_decodable_file_exact_turn_and_real_tool(tmp_path):
    root,tid,image=image_database(tmp_path)
    result=canary_worker.verify_image_receipt(root,tid,'op')
    assert result['status']=='completed' and result['images'][0]['width']==640
    assert result['dedicated_ai_image_generation_verified'] is False
    image.write_bytes(b'not a PNG')
    with pytest.raises(ValueError):canary_worker.verify_image_receipt(root,tid,'op')


def test_blank_png_is_not_a_success(tmp_path):
    root,tid,image=image_database(tmp_path)
    Image.new('RGB',(640,640),'white').save(image)
    with pytest.raises(ValueError,match='blank'):canary_worker.verify_image_receipt(root,tid,'op')


def test_formal_adoption_is_rejected(tmp_path):
    root,tid,image=image_database(tmp_path)
    with sqlite3.connect(root/'data/desk.sqlite') as c:c.execute("INSERT INTO toolbox_jobs VALUES('bad','accept')")
    with pytest.raises(ValueError,match='forbidden_adoption'):canary_worker.verify_image_receipt(root,tid,'op')


def test_outside_image_cannot_become_a_canary_artifact(tmp_path):
    root,tid,image=image_database(tmp_path);outside=tmp_path/'outside.png';outside.write_bytes(image.read_bytes())
    with sqlite3.connect(root/'data/desk.sqlite') as c:c.execute('UPDATE artifacts SET path=?',(str(outside),))
    with pytest.raises(ValueError,match='outside'):canary_worker.verify_image_receipt(root,tid,'op')


def test_missing_native_turn_is_unknown_and_does_not_start_adapter(tmp_path):
    root,tid,image=image_database(tmp_path)
    assert canary_worker.verify_image_receipt(root,'missing','op')['status']=='unknown'


def test_native_skill_canary_verifies_actual_owned_png_without_private_version_or_artifact_row(tmp_path):
    root,tid,image=image_database(tmp_path)
    folder=root/'outputs/op'/tid/'products';folder.mkdir(parents=True)
    target=folder/'actual.png';target.write_bytes(image.read_bytes())
    with sqlite3.connect(root/'data/desk.sqlite') as c:
        turn=json.loads(c.execute('SELECT document FROM easel_chat_turns WHERE id=?',(tid,)).fetchone()[0])
        turn.update(session_id='op',snapshot=None,work=None,context={'skill_id':'content-production','action_id':'native'})
        c.execute('UPDATE easel_chat_turns SET document=?',(json.dumps(turn),));c.execute('DELETE FROM artifacts')
    value=canary_worker.verify_image_receipt(root,tid,'op')
    assert value['status']=='completed' and value['turn_id']==tid
    assert 'version_id' not in value and value['images'][0]['artifact_id'] is None
    assert value['images'][0]['path']==str(target)
    (folder/'duplicate.png').write_bytes(target.read_bytes())
    with pytest.raises(ValueError,match='exactly_one'):canary_worker.verify_image_receipt(root,tid,'op')


def test_daily_cli_uses_explicit_authority_and_writes_summary(tmp_path,monkeypatch):
    observed=[]
    monkeypatch.setattr(canary,'run_daily',lambda config,root,**kwargs:observed.append(kwargs['execute']) or {'status':'prepared'})
    store=StateStore(tmp_path/'controller')
    canary.scheduled_run({'app_root':str(tmp_path/'app'),'daily_real_agent_authorized':False},store)
    assert observed==[False] and store.read('daily-status.json')['status']=='prepared'


def test_real_hn_reader_preserves_publication_time_and_fetch_time(monkeypatch):
    # Network transport is a fixture here; scheduled runtime uses the real fetcher.
    sys.path.insert(0,str(next(p for p in [Path(__file__).resolve().parents[3],Path(__file__).resolve().parents[2]/'Easel'] if (p/'easel_workbench').is_dir())))
    from easel_workbench.runtime import discovery_feeds
    calls=[]
    def fetch(url):
        calls.append(url)
        return (json.dumps([123]) if 'topstories' in url else json.dumps({'id':123,'title':'Concrete source event','type':'story','time':1700000000,'url':'https://example.org/source'})),{}
    monkeypatch.setattr(discovery_feeds,'fetch',fetch)
    story=canary_worker.collect_current()
    assert len(calls)==2 and story['source_event_id']=='hn:123'
    assert story['published_at'].startswith('2023-')
    assert story['collected_at']!=story['published_at']
    assert story['origin']=='live_builtin_hn_reader'


def test_collection_http_failure_is_not_a_fresh_success(monkeypatch):
    sys.path.insert(0,str(next(p for p in [Path(__file__).resolve().parents[3],Path(__file__).resolve().parents[2]/'Easel'] if (p/'easel_workbench').is_dir())))
    from easel_workbench.runtime import discovery_feeds
    monkeypatch.setattr(discovery_feeds,'fetch',lambda url:(_ for _ in ()).throw(OSError('network unavailable')))
    with pytest.raises(OSError):canary_worker.collect_current()


def test_png_nonce_must_match_actual_operation(tmp_path):
    root,tid,image=image_database(tmp_path)
    with Image.open(image) as original:
        original.load();original.save(image)
    with pytest.raises(ValueError,match='operation_metadata'):canary_worker.verify_image_receipt(root,tid,'op')


def test_terminal_native_without_image_is_failed_acceptance_not_unknown_execution(tmp_path):
    root,tid,image=image_database(tmp_path)
    with sqlite3.connect(root/'data/desk.sqlite') as c:c.execute('DELETE FROM artifacts')
    result=canary_worker.checked_image_receipt(root,tid,'op')
    assert result=={'status':'failed','reason':'artifact_validation_failed','validation_code':'canary_requires_exactly_one_png'}


def test_confirmed_exited_preflight_can_retry_same_operation_at_most_three_times(tmp_path):
    root=tmp_path/'controller';ids=[]
    def runner(command,**kwargs):
        request=json.loads(Path(command[-1]).read_text(encoding='utf-8'));ids.append(request['operation_id'])
        StateStore(request['workspace']).write('receipt.json',{'operation_id':request['operation_id'],'status':'blocked',
            'native_intent_saved':False,'preflight_confirmed_unsent':True})
        return SimpleNamespace(returncode=1,stdout='')
    cfg=config(tmp_path)
    for n in range(4):result=canary.run_daily(cfg,root,execute=True,clock=lambda:1793670000,runner=runner)
    assert len(ids)==3 and len(set(ids))==1
    assert result['reason']=='daily_preflight_attempt_limit' and not result['dispatch_started']


def test_confirmed_unsent_preparation_error_does_not_label_a_later_success_failed(tmp_path):
    root=tmp_path/'controller';calls=[]
    def runner(command,**kwargs):
        request=json.loads(Path(command[-1]).read_text(encoding='utf-8'));calls.append(request['operation_id'])
        value={'operation_id':request['operation_id'],'status':'completed'} if len(calls)>1 else {
            'operation_id':request['operation_id'],'status':'blocked','reason':'preflight_missing_registry','error_type':'FileNotFoundError',
            'native_intent_saved':False,'preflight_confirmed_unsent':True}
        StateStore(request['workspace']).write('receipt.json',value)
        return SimpleNamespace(returncode=0,stdout='')
    for n in range(2): result=canary.run_daily(config(tmp_path),root,execute=True,clock=lambda:1793670000,runner=runner)
    assert len(calls)==2 and len(set(calls))==1 and result['status']=='completed'
    assert 'reason' not in result and 'error_type' not in result


def test_worker_saved_native_intent_only_inspects_without_bootstrapping(tmp_path,monkeypatch,capsys):
    workspace=tmp_path/'run';workspace.mkdir();(workspace/'native-intent.json').write_text('{}')
    request=workspace/'request.json';request.write_text(json.dumps({'operation_id':'op','workspace':str(workspace),'execute':True}))
    monkeypatch.setattr(canary_worker,'prepare',lambda *args:pytest.fail('unknown operation bootstrapped again'))
    assert canary_worker.main([str(request)])==0
    assert json.loads(capsys.readouterr().out)['status']=='unknown'


def test_frozen_release_members_are_verified_before_bootstrap(tmp_path):
    import hashlib
    app=tmp_path/'app';source=app/'workbench-releases/workbench-fixture';source.mkdir(parents=True)
    member=source/'module.py';member.write_text('original')
    package={'files':{'module.py':hashlib.sha256(member.read_bytes()).hexdigest()}}
    manifest=source/'workbench-release.json';manifest.write_text(json.dumps(package))
    (app/'data').mkdir();(app/'data/active-workbench.json').write_text(json.dumps({'release':'workbench-fixture','manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest()}))
    assert canary_worker.selected_release(app)[0]==source
    member.write_text('changed')
    with pytest.raises(ValueError,match='release_member_changed'):canary_worker.selected_release(app)


@pytest.mark.parametrize('collection_status,expected',[('failed','failed'),('unknown','unknown'),('completed','completed')])
def test_missing_final_receipt_restores_original_collection_from_durable_intent(tmp_path,collection_status,expected):
    root,tid,image=image_database(tmp_path)
    collection={'status':collection_status,'source':'hacker-news','fetched_at':'2026-11-03T01:00:00+00:00','published_at':'2023-11-14T22:13:20+00:00'}
    StateStore(tmp_path).write('native-intent.json',{'operation_id':'op','session_id':'op','turn_id':tid,'collection':collection})
    assert not (tmp_path/'receipt.json').exists()
    result=canary_worker.inspect({'workspace':str(tmp_path),'operation_id':'op'})
    assert result['status']==expected
    assert result['collection']==collection and result['native_intent_saved'] is True
    assert result['images'][0]['width']==640


def test_completed_png_without_original_collection_cannot_be_total_completed(tmp_path):
    root,tid,image=image_database(tmp_path)
    StateStore(tmp_path).write('native-intent.json',{'operation_id':'op','session_id':'op','turn_id':tid})
    result=canary_worker.inspect({'workspace':str(tmp_path),'operation_id':'op'})
    assert result['status']=='unknown' and result['collection']['status']=='unknown'


def test_completed_png_cannot_borrow_another_operations_collection(tmp_path):
    root,tid,image=image_database(tmp_path)
    StateStore(tmp_path).write('native-intent.json',{'operation_id':'other','session_id':'other','turn_id':tid,'collection':{'status':'completed'}})
    assert canary_worker.inspect({'workspace':str(tmp_path),'operation_id':'op'})['status']=='unknown'
