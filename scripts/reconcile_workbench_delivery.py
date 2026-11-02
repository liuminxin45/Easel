"""Preview a precise original file receipt; application is deployment-fenced."""
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from easel_workbench.application.delivery_reconciliation import preview,apply

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--turn',required=True);parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--expected');args=parser.parse_args()
    if args.expected:
        plan=json.loads(args.plan.read_bytes())
        if plan['turn_id']!=args.turn:raise ValueError('原回合身份不同')
        result=apply(ROOT,plan,args.expected)
        print(json.dumps({'status':result['status'],'model_replayed':False,'id':result['id']}))
    else:
        plan=preview(ROOT,args.turn)
        if args.plan.exists():raise ValueError('预览路径已存在，不能覆盖原始证据')
        args.plan.parent.mkdir(parents=True,exist_ok=True);args.plan.write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'turn_id':args.turn,'files':len(plan['files']),'plan_sha256':plan['plan_sha256']}))
