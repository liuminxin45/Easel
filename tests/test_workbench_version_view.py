"""Exact-version read projections preserve authority without replaying work."""
import importlib.util
import json
from pathlib import Path

import pytest

_fixture_spec=importlib.util.spec_from_file_location('version_view_fixtures',Path(__file__).with_name('test_workbench_skill_commands.py'))
_fixture=importlib.util.module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(_fixture)
runtime=_fixture.runtime
commands=_fixture.commands


def seed(box):
    root=box.root/'data/artifacts';root.mkdir(parents=True,exist_ok=True)
    with box.store.connect() as c:
        c.execute('INSERT INTO toolbox_works VALUES(?,?,?,?,?,?)',('work','', 'original','SOURCE-LARGE-'*10000,'2026-11-01','2026-11-03'))
        for i in range(1,4):
            jid='version-'+str(i)
            c.execute("INSERT INTO toolbox_jobs(id,work_id,kind,text,signature,status,created_at,finished_at,reply) VALUES(?,?,?,?,?,?,?,?,?)",(jid,'work','create' if i==1 else 'change','INPUT-'+str(i)+'-'*30000,jid,'completed','2026-11-0'+str(i),'2026-11-0'+str(i),'REPLY-'+str(i)))
            path=root/(jid+'.txt');path.write_text('Title '+str(i)+'\nBody '+str(i),encoding='utf-8')
            c.execute('INSERT INTO artifacts VALUES(?,?,?,?,?)',('artifact-'+str(i),jid,'标题与配文.txt',str(path),'text/plain'))
            doc={'work_id':'work','creation_options':{'creator':{'profile_id':'oil-pig','profile_revision':1,'skills':[{'id':'content-production','version':1,'sha256':'immutable-hash'}]},'recipe':{'prompt_text':'FROZEN-LARGE-'+str(i)+'-'*100000}}}
            c.execute('INSERT INTO toolbox_review_inputs VALUES(?,?,?)',(jid,'review-'+str(i),json.dumps(doc)))
        c.execute("INSERT INTO toolbox_jobs(id,work_id,kind,text,candidate_id,scope,signature,status,created_at,finished_at) VALUES(?,?,?,?,?,?,?,?,?,?)",('decision','work','reject','original user decision','version-1','["copy"]','decision','completed','2026-11-02','2026-11-02'))
    return 'work'


def test_exact_view_keeps_global_authority_and_exact_body(commands,monkeypatch):
    box=commands;wid=seed(box)
    full=box.work(wid)
    from easel_workbench.runtime import task_runtime
    monkeypatch.setattr(task_runtime,'projection',lambda *a,**k:pytest.fail('view must not assemble full execution snapshots'))
    view=box.version_view(wid,'version-1')
    for key in ('id','title','state','latest_version','latest_version_label','decision','review_needed','creator','pending','production_issue','recovery'):
        assert view[key]==full[key],key
    assert view['latest_version']=='version-3'
    assert [v['id'] for v in view['versions']]==['version-1']
    assert view['versions'][0]['copy']==full['versions'][0]['copy']
    assert view['versions'][0]['editable_text']==full['versions'][0]['editable_text']
    assert view['versions'][0]['creative']['creator']==full['versions'][0]['creative']['creator']
    assert [v['label'] for v in view['version_summaries']]==['v01','v02','v03']
    assert view['history']==[] and view['input_history']==[]
    encoded=json.dumps(view)
    assert 'SOURCE-LARGE' not in encoded and 'FROZEN-LARGE' not in encoded
    assert 'REPLY-2' not in encoded and 'execution' not in view['versions'][0]
    assert len(encoded)<20000
    with pytest.raises(ValueError,match='准确版本不存在'):box.version_view(wid,'foreign-version')


def test_records_are_selected_only_and_draft_does_not_materialize_versions(commands,monkeypatch):
    box=commands;wid=seed(box)
    from easel_workbench.runtime import task_runtime,publish_content
    monkeypatch.setattr(task_runtime,'projection',lambda *a,**k:pytest.fail('even records use explicit lazy execution API'))
    original=publish_content.from_artifacts
    seen=[]
    def read(rows,root):
        rows=list(rows);seen.extend(r['task_id'] for r in rows)
        return original(rows,root)
    monkeypatch.setattr(publish_content,'from_artifacts',read)
    view=box.version_view(wid,'version-1',include_history=True)
    assert {r['id'] for r in view['history']}=={'version-1','decision'}
    assert 'FROZEN-LARGE-1' in json.dumps(view['versions'][0]['creative'])
    assert 'version-2' not in seen
    draft=box.version_view(wid)
    assert draft['versions']==[] and draft['latest_version']=='version-3'
    assert 'material' not in draft


def test_media_view_uses_selected_payload_and_current_global_identity(commands):
    from easel_workbench.runtime.easel_integration import EaselIntegration
    box=commands
    box.easel=EaselIntegration(box,autostart=False)
    with box.store.connect() as c:
        c.execute('INSERT INTO toolbox_works VALUES(?,?,?,?,?,?)',('media-work','','Media','SOURCE-LARGE'*10000,'2026-11-01','2026-11-03'))
        for i in range(1,4):
            job={'id':'media-'+str(i),'work_id':'media-work','title':'Title '+str(i),'prompt':'Direction '+str(i),'format':'image','stage':'image','status':'completed','created_at':'2026-11-0'+str(i),'parent_version_id':None if i==1 else 'media-'+str(i-1),'artifacts':[],
                 'creator':{'profile':{'id':'oil-pig','name':'Oil Pig','revision':1},'prompt_text':'FROZEN-MEDIA-'+str(i)+'-'*100000},'config':{'frozen':'CONFIG-'+str(i)+'-'*100000},'options':{'input':'OPTIONS-'+str(i)+'-'*10000}}
            box.easel._put_job(c,job)
    full=box.work('media-work')
    view=box.version_view('media-work','media-1')
    for key in ('id','title','state','latest_version','latest_version_label','decision','review_needed','creator','pending','production_issue','recovery','related_work_id'):
        assert view[key]==full[key],key
    assert [v['id'] for v in view['versions']]==['media-1']
    assert view['versions'][0]['parent_version_id'] is None
    assert view['versions'][0]['prompt']==full['versions'][0]['prompt']
    assert [v['label'] for v in view['version_summaries']]==['v01','v02','v03']
    assert 'FROZEN-MEDIA' not in json.dumps(view) and 'CONFIG-' not in json.dumps(view)
    assert len(json.dumps(view))<10000
    records=box.version_view('media-work','media-2',include_history=True)
    assert records['versions'][0]['parent_version_id']=='media-1'
    assert 'FROZEN-MEDIA-2' in json.dumps(records)
    assert 'FROZEN-MEDIA-1' not in json.dumps(records)


def test_work_summary_selector_keyset_filter_and_owner_precedence(commands,monkeypatch):
    box=commands
    with box.store.connect() as c:
        for wid in ('a','b','c','d','e'):
            c.execute('INSERT INTO toolbox_works VALUES(?,?,?,?,?,?)',(wid,'','Title '+wid,'HEAVY MATERIAL'*10000,'2026-11-01','2026-11-03'))
        c.execute('INSERT INTO toolbox_work_options VALUES(?,?,?)',('e','article','auto'))
        owner={'profile':{'name':'Explicit owner'},'profile_id':'explicit','profile_revision':4}
        for wid in ('b','c'):
            c.execute('INSERT INTO creator_work_owners VALUES(?,?,?,?,?)',(wid,'explicit',4,json.dumps(owner),'2026-11-01'))
        for rid,name,revision in [('old','Old task',2),('new','Latest task',7)]:
            doc={'snapshot':{'profile':{'id':'task-owner','name':name,'revision':revision},'prompt_text':'HEAVY SNAPSHOT'*10000}}
            c.execute('INSERT INTO creator_task_runs VALUES(?,?,?,?)',(rid,'c',json.dumps(doc),'2026-11-03'))
    monkeypatch.setattr(box,'work',lambda *a,**k:pytest.fail('selector cannot project work'))
    monkeypatch.setattr(box,'works',lambda *a,**k:pytest.fail('selector cannot enumerate full work'))
    first=box.work_summaries(limit=2)
    assert first['total']==5 and [w['id'] for w in first['items']]==['e','d']
    second=box.work_summaries(limit=2,cursor=first['next_cursor'])
    third=box.work_summaries(limit=2,cursor=second['next_cursor'])
    assert [w['id'] for w in second['items']]==['c','b']
    assert [w['id'] for w in third['items']]==['a'] and third['next_cursor'] is None
    assert second['items'][0]['creator']=={'id':'task-owner','name':'Latest task','revision':7}
    assert second['items'][1]['creator']=={'id':'explicit','name':'Explicit owner','revision':4}
    assert third['items'][0]['creator']=={'id':'oil-pig','name':'油猪大侠','revision':None}
    assert len(json.dumps(first))<2000
    filtered=box.work_summaries(profile_id='task-owner')
    assert filtered['total']==1 and filtered['items'][0]['id']=='c'
    assert box.work_summaries(format='article')['items'][0]['id']=='e'
    assert box.work_summaries(profile_id='explicit',format='article')['total']==0
    with pytest.raises(ValueError,match='分页标识'):box.work_summaries(cursor=first['next_cursor'],profile_id='explicit')
    for bad in ('not-json','x'*3000):
        with pytest.raises(ValueError,match='分页标识'):box.work_summaries(cursor=bad)
    with pytest.raises(ValueError):box.work_summaries(limit=0)


def test_scoped_unknown_version_keeps_original_recovery_and_never_replays(commands):
    box=commands;wid=seed(box)
    with box.store.connect() as c:
        c.execute("INSERT INTO toolbox_jobs(id,work_id,kind,text,candidate_id,signature,status,created_at,dispatch_started,turn_id) VALUES(?,?,?,?,?,?,?,?,?,?)",('unknown','work','change','original frozen request','version-3','unknown-signature','uncertain','2026-11-04',1,'original-native-turn'))
        before=[tuple(r) for r in c.execute('SELECT * FROM toolbox_jobs ORDER BY rowid')]
    full=box.work(wid);view=box.version_view(wid,'unknown')
    assert view['latest_version']==full['latest_version']=='version-3'
    assert view['decision']==full['decision']
    assert view['state']==full['state'] and view['review_needed']==full['review_needed']
    assert view['versions'][0]['status']=='uncertain'
    recovery=view['versions'][0]['recovery']
    assert recovery['send_state']=='unknown' and recovery['action']=='reconcile'
    assert not recovery['can_retry']
    assert view['recovery']['job_id']=='unknown' and view['pending'][0]['id']=='unknown'
    with box.store.connect() as c:
        assert [tuple(r) for r in c.execute('SELECT * FROM toolbox_jobs ORDER BY rowid')]==before
