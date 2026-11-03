"""Persisted correction safety; new productions use ordinary native skill flows.

The original plan-driven RPC/automatic-correction suite is archived verbatim.
These tests exercise retained historical guards without creating a private plan.
"""
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
import pytest
from easel_workbench.native_corrections import NativeCorrections,initialize,_parent,_verify

spec=importlib.util.spec_from_file_location('historical_correction_fixture',Path(__file__).with_name('test_workbench_chat_business.py'))
fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
business=fixtures.business


def seed(b,status='queued'):
    with b.store.connect() as c:
        initialize(c)
        c.execute('INSERT INTO toolbox_works VALUES(?,?,?,?,?,?)',('old-work','','Old work','Old material','2026-10-30','2026-10-30'))
        for jid,kind,state in [('old-parent','create','completed'),('old-child','change','queued' if status=='queued' else 'uncertain')]:
            c.execute('INSERT INTO toolbox_jobs(id,work_id,kind,text,signature,status,created_at,candidate_id) VALUES(?,?,?,?,?,?,?,?)',
                (jid,'old-work',kind,'EXACT OLD INPUT',jid,state,'2026-10-30',None if jid=='old-parent' else 'old-parent'))
        turn={'id':'old-parent','session_id':'test-chat','status':'completed','runner':'easel.harnesses.codex.CodexAdapter',
            'native_id':'old-thread','native_turn_id':'old-turn','actual_prompt':'EXACT OLD PROMPT','frozen_instructions':'EXACT OLD RULES',
            'actual_prompt_sha256':hashlib.sha256(b'EXACT OLD PROMPT').hexdigest(),'instructions_sha256':hashlib.sha256(b'EXACT OLD RULES').hexdigest(),
            'snapshot':{'task':'poster'},'work':{'work_id':'old-work','version_id':'old-parent'}}
        c.execute('INSERT INTO easel_chat_turns VALUES(?,?,?,?,?)',('old-parent','test-chat','old-operation','old-signature',json.dumps(turn)))
        rid=c.execute('SELECT rowid FROM easel_chat_turns WHERE id=?',('old-parent',)).fetchone()[0]
        document={'job_id':'old-child','session_id':'test-chat','parent_job_id':'old-parent','parent_turn_rowid':rid,
            'parent_created_at':'2026-10-30','work':{'work_id':'old-work','version_id':'old-child'},
            'user_input_fence':{'review_seq':0,'draft_rowid':0},'actual_prompt':'EXACT OLD CORRECTION','snapshot':{'task':'change'}}
        c.execute('INSERT INTO easel_native_corrections VALUES(?,?,?,?)',('old-child','test-chat',status,json.dumps(document)))
    state=b.root/'.local/workbench-deployment';state.mkdir(parents=True,exist_ok=True)
    (state/'admission.json').write_text('{"workers":true}')
    return document,turn


def saved(b):
    with b.store.connect() as c:
        return {name:[tuple(r) for r in c.execute('SELECT * FROM '+name+' ORDER BY rowid')] for name in ('easel_chat_turns','easel_native_corrections','toolbox_jobs')}


@pytest.mark.parametrize('status',['accepted','running','unknown','uncertain'])
def test_existing_nonqueued_correction_is_never_replayed_after_restart(business,monkeypatch,status):
    seed(business,status);before=saved(business)
    async def forbidden(*a,**k):pytest.fail('historical nonqueued correction cannot create another native turn')
    monkeypatch.setattr(business.chat,'submit',forbidden)
    async def scenario():
        for _ in range(3):
            consumer=NativeCorrections(business.chat,business)
            assert (await consumer.tick())['status']=='idle'
            await consumer.close()
    asyncio.run(scenario());assert saved(business)==before


def test_later_native_user_input_supersedes_only_unsent_historical_correction(business,monkeypatch):
    doc,parent=seed(business)
    with business.store.connect() as c:
        later={'id':'later-user','session_id':'test-chat','status':'completed','snapshot':None,'work':None,'message':'Later original user input'}
        c.execute('INSERT INTO easel_chat_turns VALUES(?,?,?,?,?)',('later-user','test-chat','later-operation','later-signature',json.dumps(later)))
    async def forbidden(*a,**k):pytest.fail('superseded correction must not submit')
    monkeypatch.setattr(business.chat,'submit',forbidden)
    async def scenario():
        consumer=NativeCorrections(business.chat,business)
        assert (await consumer.tick())['status']=='superseded_by_user'
        await consumer.close()
    asyncio.run(scenario())
    with business.store.connect() as c:
        assert c.execute('SELECT status FROM easel_native_corrections WHERE job_id=?',('old-child',)).fetchone()[0]=='superseded_by_user'
        assert c.execute('SELECT status FROM toolbox_jobs WHERE id=?',('old-child',)).fetchone()[0]=='cancelled'
        assert json.loads(c.execute('SELECT document FROM easel_chat_turns WHERE id=?',('old-parent',)).fetchone()[0])==parent
        assert not c.execute('SELECT 1 FROM easel_chat_turns WHERE id=?',('old-child',)).fetchone()


def test_paused_writer_cannot_dispatch_a_historical_queued_correction(business,monkeypatch):
    seed(business);before=saved(business)
    (business.root/'.local/workbench-deployment/admission.json').write_text('{"workers":false}')
    async def forbidden(*a,**k):pytest.fail('paused correction cannot submit')
    monkeypatch.setattr(business.chat,'submit',forbidden)
    async def scenario():
        consumer=NativeCorrections(business.chat,business)
        assert (await consumer.tick())['status']=='paused';await consumer.close()
    asyncio.run(scenario());assert saved(business)==before


@pytest.mark.parametrize('field',['actual_prompt','frozen_instructions'])
def test_historical_parent_corruption_fails_before_any_dispatch_or_record_write(business,field):
    doc,parent=seed(business);parent[field]+='changed'
    with business.store.connect() as c:c.execute('UPDATE easel_chat_turns SET document=? WHERE id=?',(json.dumps(parent),'old-parent'))
    before=saved(business)
    with business.store.connect() as c:
        with pytest.raises(ValueError,match='冻结字节'):_parent(c,'old-parent')
        with pytest.raises(ValueError,match='指纹'):_verify(business.box,c,{**doc,'sha256':'invalid'})
    assert saved(business)==before


def test_an_accepted_child_cannot_be_cancelled_or_requeued_by_late_metadata_failure(business):
    doc,_=seed(business)
    with business.store.connect() as c:
        child={'id':'old-child','status':'unknown','session_id':'test-chat','actual_prompt':'EXACT ACCEPTED CHILD'}
        c.execute('INSERT INTO easel_chat_turns VALUES(?,?,?,?,?)',('old-child','test-chat','child-operation','child-signature',json.dumps(child)))
    before=saved(business)
    consumer=NativeCorrections(business.chat,business)
    with business.store.connect() as c:consumer._cancel_unsent(c,doc,'blocked')
    assert saved(business)==before
