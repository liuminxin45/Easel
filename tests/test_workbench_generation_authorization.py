"""Private authorizations use native instructions; no paid tool is called."""
import asyncio
import copy
import importlib.util
from pathlib import Path

import pytest

from easel.harnesses.base import RunRequest
from easel.harnesses.workspace import harness_instructions
from easel_workbench.application.generation_policy import UPSTREAM_CHARGE_RULE, MARKER

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('generation_fixture',Path(__file__).with_name('test_workbench_chat_business.py'))
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
business=fixture.business


def shared_workspace(business):
    path=business.root/'agents/workspace/AGENTS.md'
    raw=(ROOT/'agents/workspace/AGENTS.md').read_bytes();path.write_bytes(raw)
    return path,raw


def test_original_easel_rule_remains_while_private_native_instructions_replace_it(business):
    path,raw=shared_workspace(business)
    original=harness_instructions(RunRequest('',business.root,{},sandbox='workspace-write'))
    assert UPSTREAM_CHARGE_RULE in original
    actual=business._workspace()
    assert UPSTREAM_CHARGE_RULE not in actual and MARKER in actual
    assert '不再因按量计费' in actual and '无法取得费用预估而二次询问' in actual
    assert '只讨论、先给方案、暂不生成或停止' in actual
    assert '不包含自动采纳、公开发布、修改账号、开通或购买新服务' in actual
    assert path.read_bytes()==raw
    assert harness_instructions(RunRequest('',business.root,{},sandbox='workspace-write'))==original


@pytest.mark.parametrize('message,context',[
    ('请制作微信公众号贴图。',{'skill_id':'oil-pig-poster'}),
    ('请重新生成配图和配文，包括标题和封面文字。',{}),
    ('请制作文章，按需配图。',{'skill_id':'oil-pig-article'}),
    ('先讨论怎么写，不要生成图片。',{}),
    ('只出两张图的方案，先不要制作。',{'skill_id':'oil-pig-poster'}),
])
def test_all_private_entries_freeze_the_same_policy_without_rewriting_user_intent(business,message,context):
    shared_workspace(business)
    value={'sessionId':'test-chat','turnId':'policy-turn','message':message,'context':context}
    before=copy.deepcopy(value);prepared=business.prepare(value)
    assert value==before and message in prepared['actual_prompt']
    assert UPSTREAM_CHARGE_RULE not in prepared['frozen_instructions']
    assert prepared['frozen_instructions'].count(MARKER)==1
    with business.store.connect() as c:
        assert c.execute('SELECT count(*) FROM easel_chat_turns').fetchone()[0]==0


def test_old_frozen_turn_and_same_operation_survive_new_policy_without_replay(business,monkeypatch):
    from easel import harnesses
    path,raw=shared_workspace(business);requests=[]
    class Fake:
        async def run(self,request,emit,ask,bind):
            requests.append(request);bind('TEMP-same-native-thread')
            request.on_native_turn('TEMP-same-native-thread','TEMP-native-'+str(len(requests)))
            emit('token','TEMP synthetic reply; no generation or platform calls')
    monkeypatch.setattr(harnesses,'adapter',lambda runtime:Fake())
    async def scenario():
        old={'sessionId':'test-chat','turnId':'old-turn','message':'先给方案','context':{}}
        original=harness_instructions(RunRequest('',business.root,{},sandbox='workspace-write'))
        try:
            turn=await business.chat.submit(old,snapshot=None,actual_prompt=old['message'],frozen_instructions=original)
            async for _ in business.chat.events(turn['id']):pass
            new={'sessionId':'test-chat','turnId':'new-turn','message':'请重新生成配图和配文。','context':{}}
            prepared=business.prepare(new);turn=await business.chat.submit(new,**prepared)
            async for _ in business.chat.events(turn['id']):pass
            assert len(requests)==2 and UPSTREAM_CHARGE_RULE in requests[0].frozen_instructions
            assert UPSTREAM_CHARGE_RULE not in requests[1].frozen_instructions and MARKER in requests[1].frozen_instructions
            assert requests[1].native_id=='TEMP-same-native-thread'
            assert business.prepare(old)['receipt']['id']=='old-turn'
            assert len(requests)==2
            with business.store.connect() as c:
                import json
                saved=json.loads(c.execute('SELECT document FROM easel_chat_turns WHERE id=?',('old-turn',)).fetchone()[0])
                assert saved['frozen_instructions']==original
        finally:await business.chat.close()
    asyncio.run(scenario());assert path.read_bytes()==raw


def test_active_private_production_references_do_not_reintroduce_cost_confirmation():
    paths=[ROOT/'skills/shared/workbench/production-contract.md',*(ROOT/'skills/builtin'/sid/'references/absorbed/shared/production-contract.md' for sid in ('oil-pig-poster','oil-pig-article'))]
    for path in paths:
        text=path.read_text(encoding='utf-8')
        assert '按量计费操作沿官方规则先确认' not in text
        assert '不因按量计费或缺少费用预估再次确认' in text
