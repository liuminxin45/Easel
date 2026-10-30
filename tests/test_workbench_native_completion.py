"""Native Easel files must retain the existing review and adoption gate."""
import asyncio
import base64
import importlib.util
import json
import hashlib
from pathlib import Path

import pytest

_spec=importlib.util.spec_from_file_location('native_business_fixture',Path(__file__).with_name('test_workbench_chat_business.py'))
_fixture=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_fixture)
business=_fixture.business
PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAEUlEQVR4nGM4XDHxPwgzwBgAYwQLLfOeIwgAAAAASUVORK5CYII=')


def test_native_files_enter_exact_review_queue_and_existing_adoption_gate(business,monkeypatch):
    from easel import harnesses
    from easel_workbench.application import create_app
    from easel_workbench.runtime import learning_execution
    from easel_workbench.runtime.learning_service import POLICY_PATH
    class Auth:
        data={'origin':'https://temp.local','host':'temp.local','secret':'A'*32}
        def session(self,token):return {'csrf':'fixture','until':9999999999} if token=='fixture' else None
    app=create_app(store=business.store,box=business.box,root=business.root,auth=Auth())
    b=app.state.chat_business;project=app.state.studio.project
    assert project.resolve().is_relative_to(business.root.resolve())
    policy=project/POLICY_PATH;policy.parent.mkdir(parents=True,exist_ok=True)
    policy.write_text(json.dumps({'schema_version':2,'revision':1,'methods':[],'profiles':[]}),encoding='utf-8')
    class Producer:
        async def run(self,r,emit,ask,bind):
            bind('native-downstream');r.on_native_turn('native-downstream','native-downstream-turn')
            payload=json.JSONDecoder().raw_decode(r.prompt.split('## 本轮冻结输入\n')[-1])[0]
            folder=Path(payload['output_directory']);folder.mkdir(parents=True,exist_ok=True)
            image=folder/'成品.png';image.write_bytes(PNG)
            copy=folder/'标题与配文.txt';copy.write_text('具体变化\n\n说明来源与边界。',encoding='utf-8')
            emit('token',json.dumps({'deliverables':[str(image),str(copy)]},ensure_ascii=False))
    monkeypatch.setattr(harnesses,'adapter',lambda runtime:Producer())
    async def scenario():
        value,plan=_fixture.confirmed(b)
        result=await b.chat.submit(value,**b.prepare(value));await b.chat._tasks[result['id']]
        turn=b.chat.get_turn(result['id'],private=True);wid=turn['work']['work_id'];jid=turn['id']
        assert b.box.work(wid)['versions'][0]['status']=='completed'
        with b.store.connect() as c:
            doc=json.loads(c.execute('SELECT document FROM toolbox_review_inputs WHERE job_id=?',(jid,)).fetchone()[0])
            assert doc.get('learning_snapshot'), 'Native files bypassed the frozen learning/review input'
            assert app.state.learning.read_run(c,jid), 'Native output has no exact learning run'
            queued=c.execute('SELECT kind,payload FROM learning_analysis_queue WHERE id=?',('review-'+jid,)).fetchone()
            assert queued and queued['kind']=='production_review' and json.loads(queued['payload'])['job_id']==jid
            quality=learning_execution.public_learning(b.box,c,jid)
            assert quality and quality['quality']['status']!='ready'
            with pytest.raises(ValueError):learning_execution.require_adoption(b.box,c,jid)
        options=app.state.completion.options(wid,jid)
        assert options['whole_ready'] and options['required_scopes']==['images','copy']
        preview=app.state.completion.preview(wid,jid,{'scope':['images','copy'],'completion':{'mode':'archive','targets':[],'manual_publications':[]}})
        assert preview['whole_work'] and preview['plan_hash']
        # Merely finding real files never silently marks independent review ready.
        with pytest.raises(ValueError):b.box.action(wid,{'id':'native-unreviewed-adoption','kind':'accept','candidate_id':jid,'scope':['images','copy'],'text':'','files':[],'completion':{'mode':'archive','targets':[],'manual_publications':[],'plan_hash':preview['plan_hash']}})
        with b.store.connect() as c:assert c.execute("SELECT count(*) FROM toolbox_jobs WHERE kind='accept'").fetchone()[0]==0
        inspector_calls=[]
        def synthetic_inspector(service,request):
            inspector_calls.append(request)
            files={file['artifact_name']:file for file in request['artifacts']};findings=[]
            for basis in request['required_evidence']:
                name='成品.png' if basis.get('dimension') in ('image','style','main_style') else '标题与配文.txt'
                actual=files[name]
                anchor={'type':'region','x':0,'y':0,'width':1,'height':1} if name.endswith('.png') else {'type':'text','start':0,'end':4,'quote':'具体变化'}
                findings.append({'basis_id':basis['id'],'status':'pass','message':'TEMP fake inspector; validates plumbing only.',
                    'artifact_name':name,'sha256':actual['sha256'],'location':'TEMP actual bytes','anchor':anchor})
            return {'checker':'synthetic','summary':'TEMP fake review, no actual model or visual judgment.','findings':findings}
        before={file['id']:hashlib.sha256(path.read_bytes()).hexdigest() for file,path in [b.box.file(a['id']) for a in b.box.work(wid)['versions'][0]['artifacts']]}
        from easel_workbench.runtime import production_style
        validation_errors=[];original_validate=production_style.validate_v2
        def capture_validate(report):
            try:return original_validate(report)
            except ValueError as error:validation_errors.append({'error':str(error),'report':report});raise
        monkeypatch.setattr(production_style,'validate_v2',capture_validate)
        quality=learning_execution.run_review(app.state.learning,{'payload':{'job_id':jid}},runner=synthetic_inspector)
        assert quality['status']=='ready' and not quality['objective_missing'],{'quality':quality,'validation_errors':validation_errors}
        assert len(inspector_calls)==1
        for fid,digest in before.items():assert hashlib.sha256(b.box.file(fid)[1].read_bytes()).hexdigest()==digest
        # The fresh completion preview binds any supplemented review metadata.
        completion={'mode':'archive','targets':[],'manual_publications':[]}
        preview=app.state.completion.preview(wid,jid,{'scope':['images','copy'],'completion':completion})
        result=b.box.action(wid,{'id':'native-reviewed-adoption','kind':'accept','candidate_id':jid,'scope':['images','copy'],'text':'TEMP明确采纳本版','files':[],'completion':{**completion,'plan_hash':preview['plan_hash']}})
        with b.store.connect() as c:
            decision=c.execute('SELECT candidate_id,status FROM toolbox_jobs WHERE id=?',('native-reviewed-adoption',)).fetchone()
            assert decision['candidate_id']==jid and decision['status']=='completed'
            assert c.execute('SELECT count(*) FROM creator_model_calls').fetchone()[0]==1, 'adoption must not create a model call'
        saved=app.state.completion.process('native-reviewed-adoption')
        assert saved['version_id']==jid and saved['archive']['status']=='verified'
        archive=Path(saved['archive']['path']);assert archive.is_relative_to(b.root/'data/completions')
        manifest=json.loads((archive/'完成清单.json').read_text(encoding='utf-8'))
        assert manifest['work_id']==wid and manifest['version_id']==jid
        assert all(hashlib.sha256((archive/file['path']).read_bytes()).hexdigest()==file['sha256'] for file in manifest['files'])
        await app.state.chat.close()
    asyncio.run(scenario())
