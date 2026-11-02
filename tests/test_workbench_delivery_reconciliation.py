"""TEMP-only correction of a real failed receipt; never rerun the fake model."""
import asyncio
import importlib.util
import json
from pathlib import Path

import pytest
from easel import harnesses
from easel.harnesses.codex import CodexAdapter
from easel_workbench.runtime import bridge
from easel_workbench.application.delivery_reconciliation import preview,apply

spec=importlib.util.spec_from_file_location('reconciliation_fixture',Path(__file__).with_name('test_workbench_chat_business.py'))
fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
business=fixtures.business
PNG=b'\x89PNG\r\n\x1a\n'+b'\x00\x00\x00\rIHDR'+(1).to_bytes(4,'big')*2+b'\x08\x02\x00\x00\x00'


def failed_delivery(business,monkeypatch):
    calls=[]
    class Adapter:
        descriptor=CodexAdapter.descriptor
        async def run(self,request,emit,ask,bind):
            calls.append(request);bind('native-case');request.on_native_turn('native-case','native-case-turn')
            payload=json.JSONDecoder().raw_decode(request.prompt.split('## 本轮冻结输入\n')[-1])[0]
            folder=Path(payload['output_directory']);folder.mkdir(parents=True,exist_ok=True)
            image=folder/'成品.png';image.write_bytes(PNG)
            copy=folder/'标题与配文.txt';copy.write_text('原始标题\n原始配文。',encoding='utf-8')
            (folder/'未交付.txt').write_text('不能自动接收',encoding='utf-8')
            emit('token','\n'.join('[交付](/'+path.as_posix()+')' for path in (image,copy)))
    async def scenario():
        value,_=fixtures.confirmed(business)
        with monkeypatch.context() as held:
            held.setattr(harnesses,'adapter',lambda runtime:Adapter());held.setattr(bridge,'delivery_paths',lambda reply:[])
            turn=await business.chat.submit(value,**business.prepare(value))
            if task:=business.chat._tasks.get(turn['id']):await task
        await business.chat.close()
    asyncio.run(scenario())
    return calls


def fence(root):
    state=root/'.local/workbench-deployment';state.mkdir(parents=True)
    (state/'admission.json').write_text('{"workers":false}',encoding='utf-8')
    (state/'cutover.json').write_text('{"phase":"fenced"}',encoding='utf-8')


def test_exact_failed_receipt_is_corrected_once_with_original_evidence(business,monkeypatch):
    calls=failed_delivery(business,monkeypatch);plan=preview(business.root,'turn-one')
    with business.store.connect() as c:
        original_calls=[tuple(row) for row in c.execute('SELECT * FROM creator_model_calls ORDER BY id')]
    assert len(plan['files'])==2 and plan['outcome']['code']=='missing_deliverables'
    with pytest.raises(ValueError):apply(business.root,plan,plan['plan_sha256'])
    fence(business.root)
    result=apply(business.root,plan,plan['plan_sha256']);assert result['status']=='completed' and not result['model_replayed']
    assert apply(business.root,plan,plan['plan_sha256'])==result and len(calls)==1
    with business.store.connect() as c:
        assert [tuple(row) for row in c.execute('SELECT * FROM creator_model_calls ORDER BY id')]==original_calls
        assert c.execute("SELECT status FROM toolbox_jobs WHERE id='turn-one'").fetchone()[0]=='completed'
        assert tuple(c.execute("SELECT started_at,finished_at FROM toolbox_jobs WHERE id='turn-one'").fetchone())==(plan['job']['started_at'],plan['job']['finished_at'])
        assert {r[0] for r in c.execute("SELECT name FROM artifacts WHERE task_id='turn-one'")}=={'成品.png','标题与配文.txt'}
        audit=json.loads(c.execute('SELECT document FROM toolbox_delivery_reconciliations').fetchone()[0])
        assert audit['original']['job']['status']=='error' and audit['original']['outcome']==plan['outcome']
    from easel_workbench.features.works.products import ChatProducts
    product=ChatProducts(business).describe('turn-one')
    assert not product['incomplete'] and product['can_adopt'] and len(product['files'])==2


def test_changed_original_file_rejects_correction_before_receipt_write(business,monkeypatch):
    calls=failed_delivery(business,monkeypatch);plan=preview(business.root,'turn-one');fence(business.root)
    Path(plan['files'][0]['path']).write_bytes(b'changed')
    with pytest.raises(ValueError,match='变化'):apply(business.root,plan,plan['plan_sha256'])
    with business.store.connect() as c:
        assert c.execute('SELECT count(*) FROM artifacts').fetchone()[0]==0
        assert c.execute('SELECT count(*) FROM toolbox_delivery_reconciliations').fetchone()[0]==0
    assert len(calls)==1


def test_deployment_correction_requires_exact_acceptance_bound_preview(business,monkeypatch):
    import hashlib
    failed_delivery(business,monkeypatch);plan=preview(business.root,'turn-one')
    directory=business.root/'.local/validation';directory.mkdir(parents=True)
    path=directory/'plan.json';path.write_text(json.dumps(plan),encoding='utf-8')
    acceptance=directory/'acceptance.json'
    evidence={path.relative_to(business.root).as_posix():hashlib.sha256(path.read_bytes()).hexdigest()}
    acceptance.write_text(json.dumps({'evidence':evidence}),encoding='utf-8')
    scripts=Path(__file__).resolve().parents[1]/'scripts';monkeypatch.syspath_prepend(str(scripts))
    spec=importlib.util.spec_from_file_location('reconciliation_upgrade',scripts/'upgrade_workbench_runtime.py')
    upgrade=importlib.util.module_from_spec(spec);spec.loader.exec_module(upgrade)
    assert upgrade.reviewed_delivery_plan(business.root,acceptance,path,plan['plan_sha256'])['plan_sha256']==plan['plan_sha256']
    with pytest.raises(ValueError):upgrade.reviewed_delivery_plan(business.root,acceptance,path,'0'*64)
    acceptance.write_text('{"evidence":{}}',encoding='utf-8')
    with pytest.raises(ValueError):upgrade.reviewed_delivery_plan(business.root,acceptance,path,plan['plan_sha256'])
