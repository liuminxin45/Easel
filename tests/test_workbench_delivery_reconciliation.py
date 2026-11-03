"""Historical failed-delivery reads and SHA-bound fencing; no live private plan."""
import hashlib
import importlib.util
import json
from pathlib import Path
import pytest
from easel_workbench.application.delivery_reconciliation import preview,apply

spec=importlib.util.spec_from_file_location('historical_delivery_fixture',Path(__file__).with_name('test_workbench_chat_business.py'))
fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
business=fixtures.business


def failed_delivery(b):
    folder=b.root/'outputs/test-chat/historical-turn/products';folder.mkdir(parents=True)
    image=folder/'image.png';image.write_bytes(b'\x89PNG\r\n\x1a\n'+b'HISTORICAL_IMAGE_BYTES')
    text=folder/'title.txt';text.write_text('Original historical body',encoding='utf-8')
    prompt='EXACT HISTORICAL FROZEN REQUEST'
    turn={'id':'historical-turn','session_id':'test-chat','status':'completed','hook_status':'completed',
        'native_id':'original-native','native_turn_id':'original-turn','work':{'work_id':'historical-work','version_id':'historical-turn'},
        'actual_prompt':prompt,'actual_prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'snapshot':{'task':'poster'}}
    reply='\n'.join('[delivered](/'+p.as_posix()+')' for p in [image,text])
    with b.store.connect() as c:
        c.execute('INSERT INTO toolbox_works VALUES(?,?,?,?,?,?)',('historical-work','','Historical title','Original material','2026-10-30','2026-10-30'))
        c.execute('INSERT INTO toolbox_jobs(id,work_id,kind,text,signature,status,created_at,started_at,finished_at,reply,turn_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            ('historical-turn','historical-work','create','Original input','historical-signature','error','2026-10-30','2026-10-30','2026-10-30',reply,'original-turn'))
        c.execute('INSERT INTO easel_chat_turns VALUES(?,?,?,?,?)',('historical-turn','test-chat','historical-operation','historical-signature',json.dumps(turn)))
        c.execute('CREATE TABLE IF NOT EXISTS toolbox_production_outcomes(job_id TEXT PRIMARY KEY,document TEXT NOT NULL,checked_at TEXT NOT NULL)')
        c.execute('INSERT INTO toolbox_production_outcomes VALUES(?,?,?)',('historical-turn',json.dumps({'code':'missing_deliverables','status':'error'}),'2026-10-30'))
    return turn,[image,text]


def saved(b):
    with b.store.connect() as c:
        return {name:[tuple(r) for r in c.execute('SELECT * FROM '+name+' ORDER BY rowid')] for name in ('easel_chat_turns','toolbox_jobs','toolbox_production_outcomes','artifacts')}


def test_historical_failed_delivery_preview_is_read_only_and_binds_original_bytes(business):
    turn,files=failed_delivery(business);before=saved(business)
    plan=preview(business.root,turn['id'])
    assert saved(business)==before
    assert plan['turn_id']==turn['id'] and plan['native_turn_id']=='original-turn'
    assert {item['sha256'] for item in plan['files']}=={hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    with pytest.raises(ValueError,match='停写'):apply(business.root,plan,plan['plan_sha256'])
    assert saved(business)==before


def test_changed_original_file_cannot_use_an_old_historical_preview(business):
    turn,files=failed_delivery(business);plan=preview(business.root,turn['id']);before=saved(business)
    state=business.root/'.local/workbench-deployment';state.mkdir(parents=True)
    (state/'admission.json').write_text('{"workers":false}');(state/'cutover.json').write_text('{"phase":"fenced"}')
    files[0].write_bytes(b'changed')
    with pytest.raises(ValueError,match='变化'):apply(business.root,plan,plan['plan_sha256'])
    assert saved(business)==before


def test_unknown_historical_turn_is_not_a_replayable_delivery(business):
    turn,_=failed_delivery(business)
    with business.store.connect() as c:
        turn['status']='unknown';c.execute('UPDATE easel_chat_turns SET document=? WHERE id=?',(json.dumps(turn),turn['id']))
    before=saved(business)
    with pytest.raises(ValueError,match='重放'):preview(business.root,turn['id'])
    assert saved(business)==before


def test_deployment_correction_requires_exact_acceptance_bound_historical_preview(business,monkeypatch):
    turn,_=failed_delivery(business);plan=preview(business.root,turn['id'])
    directory=business.root/'.local/validation';directory.mkdir(parents=True)
    path=directory/'plan.json';path.write_text(json.dumps(plan),encoding='utf-8')
    acceptance=directory/'acceptance.json';acceptance.write_text(json.dumps({'evidence':{path.relative_to(business.root).as_posix():hashlib.sha256(path.read_bytes()).hexdigest()}}))
    scripts=Path(__file__).resolve().parents[1]/'scripts';monkeypatch.syspath_prepend(str(scripts))
    source=importlib.util.spec_from_file_location('historical_reconciliation_upgrade',scripts/'upgrade_workbench_runtime.py')
    upgrade=importlib.util.module_from_spec(source);source.loader.exec_module(upgrade)
    assert upgrade.reviewed_delivery_plan(business.root,acceptance,path,plan['plan_sha256'])['plan_sha256']==plan['plan_sha256']
    with pytest.raises(ValueError):upgrade.reviewed_delivery_plan(business.root,acceptance,path,'0'*64)
    acceptance.write_text('{"evidence":{}}')
    with pytest.raises(ValueError):upgrade.reviewed_delivery_plan(business.root,acceptance,path,plan['plan_sha256'])
