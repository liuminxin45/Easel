"""Reconcile one proven native interruption without rerunning a model or delivery.

The native read and original row hashes are reviewed before applying. Original
documents remain in an append-only reconciliation journal. No file is imported,
no completed result is manufactured, and no dispatch/retry boundary is cleared.
"""
from __future__ import annotations
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def packed(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def sha(value):return hashlib.sha256(value.encode('utf-8')).hexdigest()


def affected(connection,turn_id):
    turn=connection.execute('SELECT document FROM easel_chat_turns WHERE id=?',(turn_id,)).fetchone()
    if not turn:raise ValueError('Exact original turn is missing')
    document=json.loads(turn['document']);session_id=document['session_id']
    result={'turn':dict(turn),'session':dict(connection.execute('SELECT * FROM easel_chat_sessions WHERE id=?',(session_id,)).fetchone()),
            'job':dict(connection.execute('SELECT * FROM toolbox_jobs WHERE id=?',(turn_id,)).fetchone()),
            'calls':[dict(row) for row in connection.execute('SELECT * FROM creator_model_calls WHERE task_id=?',(turn_id,))],
            'run':dict(connection.execute('SELECT * FROM creator_task_runs WHERE id=?',(turn_id,)).fetchone())}
    return result


def apply(connection,turn_id,proof,expected_hash):
    connection.execute('BEGIN IMMEDIATE')
    connection.execute('CREATE TABLE IF NOT EXISTS easel_native_receipt_reconciliations(turn_id TEXT PRIMARY KEY,document TEXT NOT NULL)')
    old=connection.execute('SELECT document FROM easel_native_receipt_reconciliations WHERE turn_id=?',(turn_id,)).fetchone()
    if old:return json.loads(old[0])
    original=affected(connection,turn_id)
    if sha(packed(original))!=expected_hash:raise ValueError('Original receipt changed; inspect again')
    turn=json.loads(original['turn']['document']);session=json.loads(original['session']['document'])
    native=proof.get('thread',{});receipt=proof.get('turn',{})
    if proof.get('method')!='thread/read' or proof.get('read_only') is not True or proof.get('new_model_turns')!=0:
        raise ValueError('Evidence is not a native read-only receipt')
    if native.get('id')!=turn['native_id'] or receipt.get('id')!=turn['native_turn_id'] or receipt.get('status')!='interrupted':
        raise ValueError('Native thread/turn interruption does not match the frozen task')
    if native.get('status',{}).get('type') not in ('notLoaded','idle') or Path(native.get('cwd','')).resolve()!=ROOT.resolve():
        raise ValueError('Native owner/project is not idle and verified')
    if turn['status']!='unknown' or turn.get('hook_status')!='completed' or original['job']['status']!='uncertain':
        raise ValueError('Only the exact finalized unknown receipt may be reconciled')
    if session.get('pendingTurnId')!=turn_id:raise ValueError('Session ownership changed')
    at=datetime.datetime.now(datetime.timezone.utc).isoformat()
    reference={'kind':'native_thread_read','native_status':'interrupted','sha256':sha(packed(proof)),'observed_at':at}
    message='原生接口已核对本回合中断；未重新发送，原文件保留，制作与交付未完成。'
    turn.update(status='stopped',delivery_state='interrupted',interrupt_confirmed=True,interrupt_confirmed_at=at,
                previous_error=turn.get('error'),error=message,native_receipt_reconciliation=reference,updated_at=at)
    session.update(pendingTurnId=None,revision=session['revision']+1,updated=at)
    connection.execute('UPDATE easel_chat_turns SET document=? WHERE id=?',(packed(turn),turn_id))
    connection.execute('UPDATE easel_chat_sessions SET document=? WHERE id=?',(packed(session),session['id']))
    connection.execute("UPDATE toolbox_jobs SET status='error',finished_at=?,error=? WHERE id=?",(at,message,turn_id))
    for row in original['calls']:
        call=json.loads(row['document'])
        if call['status']!='unknown' or call.get('native_turn_id')!=turn['native_turn_id']:raise ValueError('Model call identity changed')
        call.update(status='failed',delivery_state='interrupted',finished_at=at,native_receipt_reconciliation=reference)
        connection.execute('UPDATE creator_model_calls SET document=?,updated_at=? WHERE id=?',(packed(call),at,row['id']))
    run=json.loads(original['run']['document']);run.update(status='failed',finished_at=at,error=message,native_receipt_reconciliation=reference)
    for step in run.get('steps',[]):
        if step['id']=='production':step.update(status='failed',error=message)
    connection.execute('UPDATE creator_task_runs SET document=?,updated_at=? WHERE id=?',(packed(run),at,turn_id))
    outcome={'status':'error','stage':'production','code':'native_interrupted','message':message,'next_action':'查看原任务和保留的文件，后续制作需另行明确操作。','native_receipt_reconciliation':reference}
    connection.execute('INSERT OR REPLACE INTO toolbox_production_outcomes VALUES(?,?,?)',(turn_id,packed(outcome),at))
    report={'turn_id':turn_id,'status':'native_interruption_reconciled','original_sha256':expected_hash,
            'native_proof':proof,'before':original,'replayed':False,'completed':False,'delivered':False,'observed_at':at}
    connection.execute('INSERT INTO easel_native_receipt_reconciliations VALUES(?,?)',(turn_id,packed(report)))
    return report


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--turn',required=True);parser.add_argument('--evidence',type=Path,required=True);parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    state=ROOT/'.local/workbench-deployment'
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    owner=read(ROOT/'data/migration-owner.json');active=read(ROOT/'data/active-workbench.json')
    if owner['target_root']!=str(ROOT) or any(owner[key]!=active[key] for key in ('release','manifest_sha256')):raise ValueError('Active business owner does not match')
    if read(state/'cutover.json').get('phase')!='live' or read(state/'admission.json').get('workers') is not True:raise ValueError('Another cutover is active')
    from workbench_release import verify
    verify(ROOT/'workbench-releases'/active['release'],active['manifest_sha256'])
    from easel_workbench.runtime.poster_rpc import RPC
    database=(ROOT/'data/desk.sqlite').resolve()
    with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as source:
        source.row_factory=sqlite3.Row;original=affected(source,args.turn)
        original_turn=json.loads(original['turn']['document']);rpc=RPC()
        try:native=rpc.call('thread/read',{'threadId':original_turn['native_id'],'includeTurns':True},timeout=25)['thread']
        finally:rpc.close()
        found=next(turn for turn in native['turns'] if turn['id']==original_turn['native_turn_id'])
        proof={'method':'thread/read','thread':{key:native.get(key) for key in ('id','cwd','status')},'turn':{key:found.get(key) for key in ('id','status','error','startedAt','completedAt')},'read_only':True,'new_model_turns':0}
        expected=sha(packed(original))
        with tempfile.TemporaryDirectory(prefix='easel-native-receipt-rehearsal-') as directory:
            rehearsal=sqlite3.connect(Path(directory)/'rehearsal.sqlite');rehearsal.row_factory=sqlite3.Row;source.backup(rehearsal)
            try:
                with rehearsal:report=apply(rehearsal,args.turn,proof,expected)
                assert not report['replayed'] and not report['completed']
                job=dict(rehearsal.execute('SELECT * FROM toolbox_jobs WHERE id=?',(args.turn,)).fetchone())
                from easel_workbench.runtime.production_retry import recovery
                recovered=recovery(job,rehearsal,outcome={'status':'error','code':'native_interrupted','message':'native interrupted'})
                assert recovered['can_retry'] is False and recovered['failure_kind']=='production'
            finally:rehearsal.close()
    report['rehearsal_passed']=True;report['applied']=False
    if args.apply:
        with sqlite3.connect(database,timeout=30) as connection:
            connection.row_factory=sqlite3.Row
            with connection:report=apply(connection,args.turn,proof,expected)
        report.update(rehearsal_passed=True,applied=True)
    args.evidence.parent.mkdir(parents=True,exist_ok=True);args.evidence.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({key:report[key] for key in ('turn_id','status','replayed','completed','rehearsal_passed','applied')}))


if __name__=='__main__':main()
