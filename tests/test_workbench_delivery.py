"""Native products enter existing versions through a deterministic receiver."""
import base64
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

_spec=importlib.util.spec_from_file_location('delivery_fixtures',Path(__file__).with_name('test_workbench_skill_commands.py'))
_fixtures=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_fixtures)
runtime,commands=_fixtures.runtime,_fixtures.commands

from easel_workbench.runtime import bridge
from easel_workbench.runtime.production_delivery import record_delivery

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAEUlEQVR4nGM4XDHxPwgzwBgAYwQLLfOeIwgAAAAASUVORK5CYII=')


@pytest.fixture
def products(commands):
    commands.create({'id':'delivery','title':'合成内容','material':'明确原始材料','format':'poster','files':[]})
    root=commands.root/'outputs/session/turn/products';root.mkdir(parents=True)
    (root/'成品.png').write_bytes(PNG)
    (root/'标题与配文.txt').write_text('准确标题\n完整配文。',encoding='utf-8')
    return commands,root


def links(*paths):return '\n'.join('[成品]('+path.as_posix()+')' for path in paths)


def test_native_delivery_uses_only_exact_turn_products_without_executor(products,monkeypatch):
    box,root=products
    other=box.root/'outputs/session/another/products';other.mkdir(parents=True)
    (other/'别人的.png').write_bytes(PNG)
    (root/'source-reference.txt').write_text('原件不得当成成品',encoding='utf-8')
    (root/'检查报告.txt').write_text('过程检查不冒充成品',encoding='utf-8')
    (root/'未列出的正文.txt').write_text('不能枚举整个文件夹',encoding='utf-8')
    from easel_workbench.runtime import poster_executor
    monkeypatch.setattr(poster_executor.Executor,'__init__',lambda *args,**kwargs:pytest.fail('Receiver cannot create an executor'))
    reply=links(root/'成品.png',root/'标题与配文.txt',other/'别人的.png',root/'source-reference.txt',root/'检查报告.txt',root)
    result=record_delivery(box,'delivery',reply,'native-turn',product_roots=[root])
    assert result['status']=='completed'
    with box.store.connect() as c:
        rows=c.execute("SELECT name,path FROM artifacts WHERE task_id='delivery'").fetchall()
        assert {r['name'] for r in rows}=={'成品.png','标题与配文.txt'}
        assert c.execute('SELECT count(*) FROM creator_model_calls').fetchone()[0]==0
        assert c.execute("SELECT turn_id FROM toolbox_jobs WHERE id='delivery'").fetchone()[0]=='native-turn'
    assert (root/'成品.png').read_bytes()==PNG
    assert all(Path(r['path']).is_relative_to(box.root/'data/artifacts') for r in rows)


@pytest.mark.parametrize('relative',['outputs','outputs/session','outputs/session/turn','data/artifacts','outputs/other/products'])
def test_receiver_rejects_unbounded_or_non_turn_product_roots(products,relative):
    box,root=products
    with pytest.raises(ValueError):
        bridge.capture_artifacts(box.store,'delivery',links(root/'成品.png'),product_roots=[box.root/relative],root=box.root)
    with box.store.connect() as c:assert c.execute('SELECT count(*) FROM artifacts').fetchone()[0]==0


def test_completed_native_receipt_is_idempotent_and_cannot_be_replaced(products):
    box,root=products;reply=links(root/'成品.png',root/'标题与配文.txt')
    record_delivery(box,'delivery',reply,'native-turn',product_roots=[root])
    result=record_delivery(box,'delivery',reply,'native-turn',product_roots=[root],receiver=lambda *args,**kwargs:pytest.fail('Already received'))
    assert result['reused_receipt']
    with pytest.raises(ValueError):record_delivery(box,'delivery','Different reply','native-turn',product_roots=[root])
    with pytest.raises(ValueError):record_delivery(box,'delivery',reply,'other-turn',product_roots=[root])


def test_receiver_preserves_modified_original_and_default_legacy_scope(products,monkeypatch):
    box,root=products
    monkeypatch.setattr(bridge,'ROOT',box.root);monkeypatch.setattr(bridge,'PRODUCT_ROOTS',[root])
    reply=links(root/'成品.png',root/'标题与配文.txt')
    bridge.capture_artifacts(box.store,'delivery',reply)
    with box.store.connect() as c:
        row=c.execute("SELECT path FROM artifacts WHERE task_id='delivery' AND name='成品.png'").fetchone()
    captured=Path(row[0]);captured.write_bytes(b'Preserve separately modified historical bytes')
    with pytest.raises(ValueError,match='未覆盖'):bridge.capture_artifacts(box.store,'delivery',reply)
    assert captured.read_bytes()==b'Preserve separately modified historical bytes'
    assert (root/'成品.png').read_bytes()==PNG


def test_delivery_failure_keeps_actual_reply_and_does_not_restart_model(products):
    box,root=products;reply=links(root/'成品.png')
    result=record_delivery(box,'delivery',reply,'native-turn',product_roots=[root],
                           receiver=lambda *args,**kwargs:(_ for _ in ()).throw(OSError('Synthetic file failure')))
    assert result['status']=='error'
    with box.store.connect() as c:
        row=c.execute("SELECT reply,turn_id,error FROM toolbox_jobs WHERE id='delivery'").fetchone()
        assert row['reply']==reply and row['turn_id']=='native-turn'
        assert '成品接收失败' in row['error']
        assert c.execute('SELECT count(*) FROM creator_model_calls').fetchone()[0]==0


def test_streamed_progress_then_structured_json_receives_real_products(products,monkeypatch):
    from easel import harnesses
    from easel_workbench.chat import ChatService
    from easel_workbench.chat_business import ChatBusiness
    box,root=products
    other=box.root/'outputs/session/foreign/products';other.mkdir(parents=True)
    (other/'其他回合.png').write_bytes(PNG)
    (root/'source-reference.png').write_bytes(PNG)
    (root/'未声明.png').write_bytes(PNG)
    receipt={'deliverables':[{'path':str(root/'成品.png')},{'path':str(root/'标题与配文.txt')},
                             {'path':str(other/'其他回合.png')},{'path':str(root/'source-reference.png')}],
             'production_result':{'schema_version':1,'status':'completed'}}
    calls=[]
    class NativeAdapter:
        async def run(self,request,emit,ask,bind):
            calls.append(request);bind('native-thread');request.on_native_turn('native-thread','native-turn')
            emit('token','正在制作…\n')
            await asyncio.sleep(0)
            emit('token',json.dumps(receipt,ensure_ascii=False,indent=2))
    monkeypatch.setattr(harnesses,'adapter',lambda runtime:NativeAdapter())
    async def scenario():
        business=ChatBusiness(box)
        service=ChatService(box,on_finish=business.finished);business.chat=service
        service.create_session({'id':'session-create','session_id':'session','profile_id':'oil-pig'})
        result=await service.submit({'id':'turn','sessionId':'session','message':'实际合成交付测试'},
            snapshot=box.creator.resolve(task='poster'),actual_prompt='Frozen methods and exact output path',
            frozen_instructions='Synthetic only; no native model',work={'work_id':'delivery','version_id':'delivery'})
        task=service._tasks.get(result['id'])
        if task:await task
        assert service.get_turn('turn')['status']=='completed'
        assert service.get_turn('turn')['hook_status']=='completed'
        assert service.get_turn('turn')['output'].startswith('正在制作…\n{')
        with box.store.connect() as c:
            assert c.execute("SELECT status FROM toolbox_jobs WHERE id='delivery'").fetchone()[0]=='completed'
            rows=c.execute("SELECT name,path FROM artifacts WHERE task_id='delivery'").fetchall()
            assert {r['name'] for r in rows}=={'成品.png','标题与配文.txt'}
            assert all(Path(r['path']).read_bytes()==(root/r['name']).read_bytes() for r in rows)
            assert c.execute('SELECT count(*) FROM creator_model_calls').fetchone()[0]==0
        assert len(calls)==1
        await service.close()
    asyncio.run(scenario())


def test_prefixed_json_requires_explicit_receipt_and_preserves_blocked_status(products):
    from easel_workbench.runtime.production_outcome import declared
    box,root=products
    bridge.capture_artifacts(box.store,'delivery','说明\n'+json.dumps({'path':str(root/'成品.png')}),product_roots=[root],root=box.root)
    bridge.capture_artifacts(box.store,'delivery','说明\n'+json.dumps({'files':[str(root/'成品.png')],
        'production_result':{'schema_version':1,'status':'completed'}}),product_roots=[root],root=box.root)
    with box.store.connect() as c:assert c.execute('SELECT count(*) FROM artifacts').fetchone()[0]==0
    reply='正在处理\n'+json.dumps({'production_result':{'schema_version':1,'status':'blocked','code':'source_unavailable','message':'素材暂不可用'}})
    assert declared(reply)['status']=='blocked' and declared(reply)['code']=='source_unavailable'
    assert declared('说明 '+json.dumps({'production_result':{'schema_version':1,'status':'blocked'}})) is None
