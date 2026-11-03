"""TEMP SQL summaries keep authoritative bodies/actions behind explicit reads."""
import importlib.util
import json
from pathlib import Path

import pytest

spec=importlib.util.spec_from_file_location('private_view_fixtures',Path(__file__).with_name('test_workbench_skill_commands.py'))
fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
runtime,commands=fixtures.runtime,fixtures.commands

from easel_workbench.runtime.easel_frontend import EaselFrontend
from easel_workbench.features.distribution.service import DistributionService


def forbidden(*args,**kwargs):raise AssertionError('summary loaded an unselected heavyweight source')


def publication(box,key='pub-one',work='work-one'):
    with box.store.connect() as c:
        return box.studio._put(c,'publications',{'id':key,'work_id':work,'version_id':'version-one',
            'title':'Title','account':'Account','channel_id':'wechat','status':'published','url':'https://example.test/p',
            'published_at':None,'body':'PRIVATE_BODY'*100000,'source_snapshot':{'original':'PRIVATE_SOURCE'},
            'history':[{'body':'PRIVATE_HISTORY'}]},True)


def test_publication_summary_never_constructs_works_foundation_or_original_records(commands,monkeypatch):
    original=publication(commands)
    for name in ('foundation','capabilities','_records'):monkeypatch.setattr(commands.studio,name,forbidden)
    monkeypatch.setattr(commands,'works',forbidden)
    result=commands.studio.bootstrap(view='publications')
    assert result['total']==1
    item=result['publications'][0]
    for key in ('id','title','account','url','status','published_at','work_id','version_id'):
        assert item[key]==original[key]
    assert item['metadata_pending'] is True and item['missing_metadata']==['published_at']
    assert len(json.dumps(result))<2000 and 'PRIVATE' not in json.dumps(result)
    detail=commands.studio.publication_detail(original['id'])['publication']
    assert detail['body']==original['body'] and detail['history']==original['history']


def distribution(box):
    service=DistributionService(box)
    publication(box)
    with box.store.connect() as c:
        service._put(c,'connections',{'id':'connection-one','platform':'wechat','account':'Account','enabled':True,'revision':3,'secret_ref':'opaque-vault-reference'})
        for suffix,work in (('one','work-one'),('two','work-two')):
            service._put(c,'revisions',{'id':'revision-'+suffix,'work_id':work,'version_id':'version-'+suffix,
                'connection_id':'connection-one','connection_revision':3,'platform':'wechat','account':'Account','hash':'hash-'+suffix,
                'publication_id':'pub-one','title':'Title '+suffix,'body':'PRIVATE_BODY'*50000,'source_snapshot':{'body':'PRIVATE_SOURCE'}})
            service._put(c,'approvals',{'id':'approval-'+suffix,'revision_id':'revision-'+suffix,'revision_hash':'hash-'+suffix,'batch_id':'batch-'+suffix,'platform':'wechat','account':'Account','action':'draft','pilot':False,'schedule_at':None})
            service._put(c,'deliveries',{'id':'delivery-'+suffix,'work_id':work,'revision_id':'revision-'+suffix,'approval_id':'approval-'+suffix,'batch_id':'batch-'+suffix,'status':'unknown','account':'Account','platform':'wechat','result':{'body':'PRIVATE_RESULT'},'error':None})
            service._put(c,'attempts',{'id':'attempt-'+suffix,'delivery_id':'delivery-'+suffix,'status':'unknown','trace':'PRIVATE_TRACE'*50000})
            service._put(c,'batches',{'id':'batch-'+suffix,'approval_ids':['approval-'+suffix]})
    return service


def test_distribution_summary_projects_metadata_and_scope_before_body_hydration(commands,monkeypatch):
    service=distribution(commands)
    monkeypatch.setattr(service,'_records',forbidden);monkeypatch.setattr(service,'_validate_revision',forbidden)
    monkeypatch.setattr(service.studio,'_records',forbidden)
    result=service.bootstrap('work-one',view='summary')
    assert {row['id'] for row in result['revisions']}=={'revision-one'}
    for key in ('approvals','deliveries','attempts','batches','publications'):
        assert len(result[key])==1 and result['counts'][key]==1
    assert result['connections'][0]['secret_configured'] is True
    assert result['connections'][0]['enabled'] is True and result['approvals'][0]['pilot'] is False
    assert result['revisions'][0]['hash']=='hash-one'
    assert result['batches'][0]['status']=='needs_attention' and result['batches'][0]['approval_count']==1
    assert 'valid' not in result['revisions'][0] # no implied live source validation
    assert 'PRIVATE' not in json.dumps(result) and 'opaque-vault-reference' not in json.dumps(result)
    assert len(json.dumps(result))<10000


def test_distribution_exact_detail_validates_only_selected_revision_and_preserves_unknown_receipt(commands,monkeypatch):
    service=distribution(commands);checked=[]
    monkeypatch.setattr(service,'_validate_revision',lambda c,value:checked.append(value['id']))
    before=service._get
    revision=service.detail('revisions','revision-two')['revision']
    assert checked==['revision-two'] and revision['valid'] is True
    assert revision['body'].startswith('PRIVATE_BODY')
    detail=service.detail('deliveries','delivery-one')
    assert detail['delivery']['status']=='unknown' and detail['delivery']['result']['body']=='PRIVATE_RESULT'
    assert [row['id'] for row in detail['attempts']]==['attempt-one']
    with service.store.connect() as c:
        assert before(c,'deliveries','delivery-one')['status']=='unknown'
        assert 'valid' not in before(c,'revisions','revision-two')
    with pytest.raises(ValueError):service.detail('connections','connection-one')
    with pytest.raises(ValueError):service.detail('revisions','missing')


def add_work(box,key,*,revision=1,submitted=0,jobs=()):
    with box.store.connect() as c:
        c.execute('INSERT INTO toolbox_works VALUES(?,?,?,?,?,?)',(key,None,'Title '+key,'','2026-11-03','2026-11-03'))
        c.execute('INSERT INTO toolbox_article_drafts VALUES(?,?,?,?)',(key,revision,json.dumps({'title':'Title '+key,'material':'','guidance':'','files':[]}),submitted))
        for jid,kind,status in jobs:
            c.execute('INSERT INTO toolbox_jobs(id,work_id,kind,text,files,signature,status,created_at,scope) VALUES(?,?,?,?,?,?,?,?,?)',(jid,key,kind,'question','[]',jid,status,'2026-11-03','[]'))


def test_topics_sql_projection_matches_legacy_drafts_discussions_decisions_and_tombstones(commands,monkeypatch):
    add_work(commands,'draft')
    add_work(commands,'submitted',revision=1,submitted=1)
    add_work(commands,'discussing',revision=0,jobs=[('talk','discuss','queued')])
    add_work(commands,'working',jobs=[('produce','create','queued')])
    add_work(commands,'decided',jobs=[('accept','accept','completed')])
    add_work(commands,'changed-discussion',revision=1,submitted=1,jobs=[('completed-talk','discuss','completed')])
    frontend=EaselFrontend(commands)
    with commands.store.connect() as c:
        c.execute('INSERT INTO easel_topics VALUES(?,?)',('tombstone',json.dumps({'id':'tombstone','work_id':'draft','deleted':True})))
        c.execute('INSERT INTO easel_topics VALUES(?,?)',('manual',json.dumps({'id':'manual','title':'Manual','status':'pending'})))
    legacy=[row for row in commands.works()['items'] if row['state'] in ('draft','discussing')]
    monkeypatch.setattr(commands,'works',forbidden);monkeypatch.setattr(commands,'work',forbidden)
    from easel_workbench.runtime import content_studio
    monkeypatch.setattr(content_studio,'frozen_options',forbidden)
    result=frontend.topics()['items']
    assert [row['work_id'] for row in result if row.get('work_id')]==[row['id'] for row in legacy if row['id']!='draft']
    assert {row.get('work_id') for row in result}=={None,'discussing','changed-discussion'}
    assert next(row for row in result if row['id']=='manual')['title']=='Manual'


@pytest.mark.parametrize('view',['bad','summary'])
def test_studio_rejects_unknown_views(commands,view):
    with pytest.raises(ValueError):commands.studio.bootstrap(view=view)


def test_creator_bootstrap_uses_projected_descriptors_preserves_status_and_full_profile_compatibility(runtime,monkeypatch):
    from easel_workbench.features.skills.bootstrap_reads import SKILL_FIELDS,PROFILE_FIELDS
    from easel_workbench.skills import launch_metadata,task_policy
    with runtime.store.connect() as c:
        original=runtime._skill(c,'content-writing',1,False)
        newer={key:value for key,value in original.items() if key not in ('history','published_version','is_current')}
        newer.update(version=2,status='candidate',prompt='PRIVATE_LARGE_PROMPT'*10000,resources=[{'content':'PRIVATE_RESOURCE'*10000}],base_version=1)
        c.execute('INSERT INTO creator_skill_versions VALUES(?,?,?)',('content-writing',2,json.dumps(newer)))
        # An old release remains published when a later pointer moves. An event
        # may mark a release published even if its stored import status differs.
        c.execute("UPDATE creator_skill_pointers SET version=2 WHERE skill_id='content-writing'")
        c.execute('INSERT INTO creator_skill_events VALUES(?,?,?,?,?,?)',('publish-two','content-writing',2,'publish','{}','2026-11-03'))
        expected=[]
        for row in c.execute('SELECT id FROM creator_skills ORDER BY rowid'):
            item=runtime._skill(c,row['id'],with_content=False)
            expected.append({**{key:item.get(key) for key in SKILL_FIELDS},'published_version':item['published_version'],
                'is_current':item['is_current'],'status':item['status'],**launch_metadata(item)})
        profile=runtime._profile(c,'oil-pig')
        before=[row[0] for row in c.execute('SELECT document FROM creator_skill_versions ORDER BY skill_id,version')]
    monkeypatch.setattr(runtime,'_skill',forbidden);monkeypatch.setattr(runtime.releases,'_skill',forbidden)
    summary=runtime.bootstrap(summary=True);full=runtime.bootstrap()
    actual=[{key:value for key,value in item.items() if key!='versions'} for item in summary['skills']]
    assert actual==expected and summary['task_policy']==task_policy(expected)
    writing=next(row for row in summary['skills'] if row['id']=='content-writing')
    assert [(row['version'],row['status']) for row in writing['versions']]==[(2,'published'),(1,'published')]
    assert set(summary['profiles'][0])==set(PROFILE_FIELDS)
    assert isinstance(summary['profiles'][0]['active'],bool)
    assert summary['profiles'][0]=={key:profile.get(key) for key in PROFILE_FIELDS}
    assert full['profiles'][0]==profile and 'voice' in full['profiles'][0]
    assert 'PRIVATE' not in json.dumps(summary) and len(json.dumps(summary))<20000
    with runtime.store.connect() as c:
        assert [row[0] for row in c.execute('SELECT document FROM creator_skill_versions ORDER BY skill_id,version')]==before


def test_native_profile_reads_do_not_load_skill_bootstrap(commands,monkeypatch):
    from easel_workbench.runtime.native_api import NativeApi
    api=NativeApi(commands)
    monkeypatch.setattr(commands.creator,'bootstrap',forbidden)
    assert api._profiles()[0]['id']=='oil-pig'
    assert len(api._profile_files('oil-pig')['files'])==6


def test_legacy_distribution_full_read_keeps_bodies_and_selected_summary_matches_scalars(commands,monkeypatch):
    service=distribution(commands)
    monkeypatch.setattr(service,'_validate_revision',lambda *args:None)
    full=service.bootstrap();summary=service.bootstrap(view='summary')
    for kind in ('revisions','approvals','deliveries','attempts','batches','publications'):
        assert [row['id'] for row in summary[kind]]==[row['id'] for row in full[kind]]
        for item,legacy in zip(summary[kind],full[kind]):
            for field,value in item.items():
                if field in legacy:assert value==legacy[field]
    assert 'PRIVATE_BODY' in full['revisions'][0]['body']
    assert full['deliveries'][0]['result']['body']=='PRIVATE_RESULT'
    assert 'body' not in summary['revisions'][0] and 'result' not in summary['deliveries'][0]
