"""Native delete actions on TEMP historical storage, with actual HTTP ports."""
import importlib.util
import json
from pathlib import Path
import pytest
from fastapi import HTTPException

spec=importlib.util.spec_from_file_location('deletion_fixtures',Path(__file__).with_name('test_workbench_native_api.py'))
fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
runtime,commands=fixtures.runtime,fixtures.commands
call=fixtures.call
from easel_workbench.runtime.native_api import NativeApi


def prepare(box):
    api=NativeApi(box);box._native_api=api;return api


@pytest.mark.parametrize('directory',[False,True])
def test_native_delete_removes_active_entry_retains_originals_and_is_idempotent(commands,directory):
    source=commands.root/'outputs/project/original.txt';source.parent.mkdir(parents=True);source.write_text('original bytes',encoding='utf-8')
    api=prepare(commands);api.library.rebuild()
    target='project' if directory else 'project/original.txt'
    response,result=call(commands,'/api/output/'+target,'DELETE',{},'exact-delete')
    assert response.status_code==200 and result=={'ok':True,'deleted':target,'kind':'dir' if directory else 'file'}
    assert source.read_text(encoding='utf-8')=='original bytes'
    assert any(node['path']=='project' for node in api.library.list()['items']) is not directory
    assert call(commands,'/api/output/'+target,'DELETE',{},'exact-delete')[1]==result
    assert call(commands,'/api/output/project/original.txt')[1]['content']=='original bytes'
    with pytest.raises(HTTPException):api.library.resolve(target)
    api.library.rebuild()
    assert any(node['path']=='project' for node in api.library.list()['items']) is not directory
    # A new file/version is visible; removal of an old directory cannot hide it.
    other=source.with_name('new.txt');other.write_text('new version',encoding='utf-8');api.library.rebuild()
    children=api.library.list(parent='project')['items']
    assert [node['path'] for node in children]==['project/new.txt']
    source.write_text('explicit replacement with new bytes',encoding='utf-8');api.library.rebuild()
    assert {node['name'] for node in api.library.list(parent='project')['items']}=={'original.txt','new.txt'}
    with commands.store.connect() as c:
        saved=json.loads(c.execute('SELECT document FROM native_library_deletions WHERE path=?',('project/original.txt',)).fetchone()[0])
    assert (commands.root/saved['archive']).read_text(encoding='utf-8')=='original bytes'


@pytest.mark.parametrize('status',['running','unknown','completed','stopped'])
def test_registered_native_products_require_settled_execution_and_keep_their_history(commands,status):
    original=commands.root/'data/artifacts/native-product.txt';original.parent.mkdir(parents=True,exist_ok=True);original.write_text('exact native result',encoding='utf-8')
    turn={'id':'native-turn','session_id':'native-session','message':'original instruction','status':status,'snapshot':{'task':'native'}}
    with commands.store.connect() as c:
        c.execute('CREATE TABLE easel_chat_turns(id TEXT PRIMARY KEY,session_id TEXT,document TEXT)')
        c.execute('INSERT INTO easel_chat_turns VALUES(?,?,?)',('native-turn','native-session',json.dumps(turn)))
        c.execute('INSERT INTO artifacts VALUES(?,?,?,?,?)',('native-file','native-turn',original.name,str(original),'text/plain'))
    api=prepare(commands);api.library.rebuild()
    path='__workbench__/native-file/native-product.txt'
    response,result=call(commands,'/api/output/'+path,'DELETE',{},'delete-native-result')
    assert response.status_code==(409 if status in ('running','unknown') else 200)
    assert original.read_text(encoding='utf-8')=='exact native result'
    with commands.store.connect() as c:
        assert json.loads(c.execute('SELECT document FROM easel_chat_turns').fetchone()[0])==turn
        assert c.execute('SELECT count(*) FROM artifacts').fetchone()[0]==1
    if response.status_code==200:
        with pytest.raises(HTTPException):api.library.resolve(path)
        assert call(commands,'/api/output/'+path)[1]['content']=='exact native result'
    else:assert api.library.resolve(path)['nodes'][-1]['path']==path


@pytest.mark.parametrize('path',['_sessions/private.txt','../outside.txt','project/../other',''])
def test_delete_cannot_turn_unlisted_or_system_paths_into_writes(commands,path):
    api=prepare(commands);api.library.rebuild()
    response,_=call(commands,'/api/output/'+path,'DELETE',{},'unsafe-delete')
    assert response is None or response.status_code in (403,404)
    with commands.store.connect() as c:assert c.execute('SELECT count(*) FROM native_library_deletions').fetchone()[0]==0


def test_native_profile_delete_keeps_revisions_and_refs_and_rejects_stale_views(commands):
    profile=commands.creator.command({'id':'create-deletable','action':'profile-save','base_revision':0,
        'document':{'name':'可删除画像','identity':'historical identity'}})['result']['profile']
    pid,revision=profile['id'],profile['revision'];api=prepare(commands)
    stale,_=call(commands,'/api/persona/'+pid,'DELETE',{'expected_revision':revision-1},'stale-profile-delete')
    assert stale.status_code==409 and commands.creator.detail('profile',pid)['active']
    response,result=call(commands,'/api/persona/'+pid,'DELETE',{'expected_revision':revision},'profile-delete')
    assert response.status_code==200 and result=={'ok':True,'deleted':pid}
    historical=commands.creator.detail('profile',pid)
    assert historical['active'] is False and historical['identity']==profile['identity']
    assert historical['revision']==revision+1 and historical['history'][-1]['identity']==profile['identity']
    assert call(commands,'/api/persona/'+pid,'DELETE',{'expected_revision':revision},'profile-delete')[1]==result
    assert call(commands,'/api/persona/'+pid+'/files')[0].status_code==404
    assert pid not in {item['name'] for item in call(commands,'/api/personas')[1]}
    default=commands.creator.detail('profile','oil-pig')
    blocked,_=call(commands,'/api/persona/oil-pig','DELETE',{'expected_revision':default['revision']},'default-delete')
    assert blocked.status_code==403


def test_metadata_projection_failure_keeps_the_atomic_delete_receipt_and_hides_old_index(commands,monkeypatch):
    source=commands.root/'outputs/project/original.txt';source.parent.mkdir(parents=True);source.write_text('retained',encoding='utf-8')
    api=prepare(commands);api.library.rebuild()
    rebuild=api.library.rebuild
    def unavailable(**kwargs):raise OSError('TEMP projection unavailable after the committed deletion')
    monkeypatch.setattr(api.library,'rebuild',unavailable)
    response,result=call(commands,'/api/output/project','DELETE',{},'delete-projection-failure')
    assert response.status_code==200 and api.receipt('delete-projection-failure')['result']==result
    assert call(commands,'/api/output/project','DELETE',{},'delete-projection-failure')[1]==result
    page=call(commands,'/api/library/items',query='limit=50')[1]
    assert not any(item['path']=='project' for item in page['items'])
    response,_=call(commands,'/api/library/resolve',query='path=project')
    assert response.status_code==410
    assert source.read_text(encoding='utf-8')=='retained'
    monkeypatch.setattr(api.library,'rebuild',rebuild);api.library.rebuild()
    assert not any(item['path']=='project' for item in api.library.list()['items'])


def test_archive_failure_never_hides_the_original_or_claims_completion(commands,monkeypatch):
    import easel_workbench.features.works.library_deletion as deletion
    source=commands.root/'outputs/project/original.txt';source.parent.mkdir(parents=True);source.write_text('original',encoding='utf-8')
    api=prepare(commands);api.library.rebuild()
    def cannot_copy(*args,**kwargs):raise OSError('TEMP no disk space')
    monkeypatch.setattr(deletion.shutil,'copy2',cannot_copy)
    response,_=call(commands,'/api/output/project','DELETE',{},'archive-failed')
    assert response.status_code==500 and api.receipt('archive-failed')['state']!='completed'
    assert source.read_text(encoding='utf-8')=='original'
    assert api.library.resolve('project')['nodes'][-1]['path']=='project'
    with commands.store.connect() as c:assert c.execute('SELECT count(*) FROM native_library_deletions').fetchone()[0]==0
