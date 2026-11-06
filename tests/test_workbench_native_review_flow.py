import asyncio,base64,importlib.util,json
from pathlib import Path
import pytest
spec=importlib.util.spec_from_file_location('review_business_fixture',Path(__file__).with_name('test_workbench_chat_business.py'))
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
business=fixture.business
from easel import harnesses
from easel.harnesses.codex import CodexAdapter
from easel_workbench.application.chat_admission import ChatAdmission
from easel_workbench.features.works.native_review import MARKER
PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAEUlEQVR4nGM4XDHxPwgzwBgAYwQLLfOeIwgAAAAASUVORK5CYII=')

@pytest.mark.parametrize('format',['poster','article'])
def test_native_production_decision_and_modification_are_version_bound(business,monkeypatch,format):
    calls=[]
    class Adapter:
        descriptor=CodexAdapter.descriptor
        async def run(self,request,emit,ask,bind):
            calls.append(request);bind('test-native');request.on_native_turn('test-native','test-native-'+str(len(calls)))
            frame=json.JSONDecoder().raw_decode(request.prompt.rsplit(MARKER,1)[1])[0]
            folder=Path(frame['product_directory']);folder.mkdir(parents=True,exist_ok=True)
            paths=[]
            if format=='poster':
                image=folder/'成品.png';image.write_bytes(PNG);paths.append(image)
                copy=folder/'标题与配文.txt';copy.write_text('测试标题\n测试正文',encoding='utf8');paths.append(copy)
            else:
                body=folder/'文章正文.md';body.write_text('# 测试标题\n\n测试正文',encoding='utf8');paths.append(body)
                html=folder/'文章.html';html.write_text('<h1>测试标题</h1><p>测试正文</p>',encoding='utf8');paths.append(html)
                manifest=folder/'文章交付.json';manifest.write_text(json.dumps({'schema_version':1,'article_type':'general','title':'测试标题','body_file':body.name,'sources':[]}),encoding='utf8');paths.append(manifest)
            emit('token','\n'.join('[成品]('+p.as_posix()+')' for p in paths))
    monkeypatch.setattr(harnesses,'adapter',lambda runtime:Adapter())
    admissions=ChatAdmission(chat=business.chat,business=business)
    async def send(tid,message,skill=None):
        value={'sessionId':'test-chat','turnId':tid,'message':message,'attachments':[],'context':{'profile_id':'oil-pig',**({'skill_id':skill} if skill else {})}}
        await admissions.receive(value)
        while tid in admissions.tasks:await asyncio.sleep(.01)
        if tid in business.chat._tasks:await business.chat._tasks[tid]
        return business.chat.get_turn(tid,private=True),value
    async def run():
        try:
            turn,_=await send('review-produce','制作内容','oil-pig-'+format)
            assert turn['status']=='completed' and turn['hook_status']=='completed',turn
            candidate=turn['business_receipt']['review_candidate'];assert candidate['status']=='completed',candidate
            uncertain,_=await send('review-ambiguous','不错')
            assert uncertain['business_receipt']['review_decision'] is None and len(calls)==1
            changed,_=await send('review-change','修改这版，标题更具体')
            newer=changed['business_receipt']['review_candidate']
            assert newer['work_id']==candidate['work_id'] and newer['parent_version_id']==candidate['version_id']
            rejected,reject_value=await send('review-reject','不采纳这版，保留原件')
            assert rejected['business_receipt']['review_decision']['kind']=='reject',rejected
            from easel_workbench.features.works.native_review import binding
            next_frame=binding(business,{'sessionId':'test-chat','turnId':'feedback-check','message':'修改这版，标题更具体','context':{}})
            assert next_frame['parent_feedback'][-1]['text']=='不采纳这版，保留原件'
            await admissions.receive(reject_value)
            assert len(calls)==2
            assert '采纳' in business.history('test-chat')['session']['messages'][-1]['content']
            accepted,_=await send('review-accept','采纳这版')
            assert accepted['business_receipt']['review_decision']['kind']=='accept',accepted
            assert len(calls)==2
            with business.store.connect() as c:
                assert c.execute("SELECT count(*) FROM toolbox_jobs WHERE kind IN ('accept','reject')").fetchone()[0]==2
                assert c.execute("SELECT count(*) FROM toolbox_local_tasks WHERE kind='cleanup'").fetchone()[0]==0
            from easel_workbench.features.works.native_review import decision
            interrupted={'sessionId':'test-chat','turnId':'review-local-restart','message':'不采纳这版','context':{},'attachments':[]}
            row=admissions._receive(interrupted)
            command=decision(business,interrupted)
            business.chat._admit(interrupted,snapshot=None,actual_prompt=interrupted['message'],frozen_instructions='local',admission_id=interrupted['turnId'],local_review=command)
            business.chat._release_owned(interrupted['turnId'])
            await admissions._process(interrupted['turnId'])
            assert business.chat.get_turn(interrupted['turnId'])['status']=='completed'
            assert len(calls)==2
            from easel_workbench.features.works.native_review import latest
            with business.store.connect() as c:
                failed={'id':'later-failed','session_id':'test-chat','status':'failed','hook_status':'completed','context':{'skill_id':'oil-pig-'+format}}
                c.execute('INSERT INTO easel_chat_turns VALUES(?,?,?,?,?)',('later-failed','test-chat','later-failed','failed',json.dumps(failed)))
            assert latest(business,'test-chat') is None
        finally:await admissions.close();await business.chat.close()
    asyncio.run(run())
