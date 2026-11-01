"""Real TEMP receipts: confirmed stops may settle; unknowns need native proof."""
import importlib.util
import json
from pathlib import Path
import sqlite3

import pytest

spec=importlib.util.spec_from_file_location('native_receipt_reconcile',Path(__file__).parents[1]/'scripts/reconcile_workbench_native_receipt.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def fixture(tmp_path,status='stopped',pending=None):
    c=sqlite3.connect(tmp_path/'receipts.sqlite');c.row_factory=sqlite3.Row
    for table in ['easel_chat_turns','easel_chat_sessions','toolbox_jobs','creator_task_runs']:
        if table=='toolbox_jobs':c.execute('CREATE TABLE toolbox_jobs(id TEXT PRIMARY KEY,status TEXT,finished_at TEXT,error TEXT)')
        elif table=='creator_task_runs':c.execute('CREATE TABLE creator_task_runs(id TEXT PRIMARY KEY,document TEXT,updated_at TEXT)')
        else:c.execute('CREATE TABLE '+table+'(id TEXT PRIMARY KEY,document TEXT)')
    c.execute('CREATE TABLE creator_model_calls(id TEXT PRIMARY KEY,task_id TEXT,document TEXT,updated_at TEXT)')
    c.execute('CREATE TABLE toolbox_production_outcomes(id TEXT PRIMARY KEY,document TEXT,updated_at TEXT)')
    turn={'id':'turn','session_id':'session','native_id':'thread','native_turn_id':'native-turn','status':status,'hook_status':'completed',
          'interrupt_confirmed':True,'delivery_state':'interrupted','message':'original input','output':'partial original','attachments':['original.png']}
    c.execute('INSERT INTO easel_chat_turns VALUES(?,?)',('turn',module.packed(turn)))
    c.execute('INSERT INTO easel_chat_sessions VALUES(?,?)',('session',module.packed({'id':'session','pendingTurnId':pending,'revision':2})))
    c.execute('INSERT INTO toolbox_jobs VALUES(?,?,?,?)',('turn','uncertain',None,None))
    c.execute('INSERT INTO creator_model_calls VALUES(?,?,?,?)',('call','turn',module.packed({'status':'unknown','native_turn_id':'native-turn'}),None))
    c.execute('INSERT INTO creator_task_runs VALUES(?,?,?)',('turn',module.packed({'steps':[{'id':'production','status':'running'}]}),None));c.commit()
    proof={'method':'thread/read','thread':{'id':'thread','cwd':str(module.ROOT),'status':{'type':'idle'}},'turn':{'id':'native-turn','status':'interrupted'},'read_only':True,'new_model_turns':0}
    return c,proof,turn


@pytest.mark.parametrize('status,pending',[('stopped',None),('unknown','turn')])
def test_actual_interruption_settles_job_without_replay_and_preserves_original(tmp_path,status,pending):
    c,proof,turn=fixture(tmp_path,status,pending)
    with c:report=module.apply(c,'turn',proof,module.sha(module.packed(module.affected(c,'turn'))))
    assert not report['replayed'] and not report['completed'] and not report['delivered']
    actual=json.loads(c.execute('SELECT document FROM easel_chat_turns').fetchone()[0])
    for key in ['message','output','attachments','native_id','native_turn_id']:assert actual[key]==turn[key]
    assert c.execute('SELECT status FROM toolbox_jobs').fetchone()[0]=='error'
    assert json.loads(c.execute('SELECT document FROM creator_model_calls').fetchone()[0])['status']=='failed'
    with c:assert module.apply(c,'turn',proof,'unused-idempotent-hash')==report
    c.close()


@pytest.mark.parametrize('bad',['native-status','native-id','owner','unconfirmed','new-pending'])
def test_unproven_or_changed_receipt_cannot_be_settled(tmp_path,bad):
    c,proof,turn=fixture(tmp_path)
    if bad=='native-status':proof['turn']['status']='inProgress'
    if bad=='native-id':proof['turn']['id']='different'
    if bad=='owner':proof['thread']['cwd']=str(tmp_path)
    if bad=='unconfirmed':
        turn['interrupt_confirmed']=False;c.execute('UPDATE easel_chat_turns SET document=?',(module.packed(turn),));c.commit()
    if bad=='new-pending':
        c.execute('UPDATE easel_chat_sessions SET document=?',(module.packed({'id':'session','pendingTurnId':'new-turn','revision':3}),));c.commit()
    digest=module.sha(module.packed(module.affected(c,'turn')))
    with pytest.raises(ValueError),c:module.apply(c,'turn',proof,digest)
    assert c.execute('SELECT status FROM toolbox_jobs').fetchone()[0]=='uncertain'
    assert json.loads(c.execute('SELECT document FROM creator_model_calls').fetchone()[0])['status']=='unknown'
    c.close()
