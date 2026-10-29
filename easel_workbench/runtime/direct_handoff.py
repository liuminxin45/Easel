"""Local-only explicit work binding for desktop conversation turns."""

if __name__ == "__main__" and not __package__:
    import sys as _bootstrap_sys
    from pathlib import Path as _BootstrapPath
    _bootstrap_sys.path.insert(0,str(_BootstrapPath(__file__).resolve().parents[2]))

import argparse,json,uuid
from easel_workbench.runtime.desk import Store,THREAD
from easel_workbench.runtime.toolbox_store import Toolbox
from easel_workbench.runtime.direct_turns import DirectTurns,current_turn
from easel_workbench.runtime.bridge import target

def record_current(box,value,path,turn=None):
    """Persist an explicit decision/feedback from this already running turn."""
    turn=turn or current_turn(path)
    if '[AI_NEWS_DESK_REQUEST:' in turn['request']:raise ValueError('工作台请求由原操作接收，不重复记录')
    kind=value.get('kind')
    if kind not in ('feedback','accept','reject'):raise ValueError('只记录明确反馈或决定')
    from easel_workbench.runtime.toolbox_store import ident
    wid=ident(value.get('work_id'));candidate=ident(value.get('candidate_id'))
    thread=value.get('thread') or THREAD
    operation=value.get('id') or str(uuid.uuid5(uuid.NAMESPACE_URL,'toolbox-local-direct:'+thread+':'+turn['turn_id']+':'+wid+':'+candidate+':'+kind))
    payload={'id':operation,'kind':kind,'candidate_id':candidate,'text':turn['request'],'scope':value.get('scope',[])}
    return box.action(wid,payload,origin='direct_turn')

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    b=sub.add_parser('bind');b.add_argument('--work-id',required=True);b.add_argument('--kind',required=True,choices=['create','change','discuss','feedback']);b.add_argument('--candidate-id');b.add_argument('--title',default='');b.add_argument('--material',default='');b.add_argument('--format',choices=['poster','article'],default='poster');b.add_argument('--article-mode',default='auto')
    s=sub.add_parser('status');s.add_argument('--id',required=True)
    r=sub.add_parser('retry');r.add_argument('--id',required=True)
    local=sub.add_parser('record');local.add_argument('--work-id',required=True);local.add_argument('--candidate-id',required=True);local.add_argument('--kind',required=True,choices=['feedback','accept','reject']);local.add_argument('--scope',action='append',choices=['images','copy','article'],default=[]);local.add_argument('--id')
    b.add_argument('--thread-id',default=THREAD);b.add_argument('--creator-id');b.add_argument('--creative-json')
    local.add_argument('--thread-id',default=THREAD)
    sub.add_parser('poll')
    a=p.parse_args();service=DirectTurns(Toolbox(Store()))
    if a.command in ('record','bind'):
        from easel_workbench.runtime.task_runtime import target_for_thread
        source=target() if a.thread_id==THREAD else target_for_thread(a.thread_id)
    if a.command=='record':result=record_current(service.box,{'id':a.id,'work_id':a.work_id,'candidate_id':a.candidate_id,'kind':a.kind,'scope':a.scope,'thread':a.thread_id},source)
    elif a.command=='bind':
        creative=json.loads(a.creative_json) if a.creative_json else {}
        if not isinstance(creative,dict):raise ValueError('本轮创作要求必须是对象')
        if a.creator_id:creative['creator']={**creative.get('creator',{}),'profile_id':a.creator_id}
        result=service.bind({'thread':a.thread_id,'work_id':a.work_id,'kind':a.kind,'candidate_id':a.candidate_id,'title':a.title,'material':a.material,'format':a.format,'article_mode':a.article_mode,**({'creative':creative} if creative else {})},source)
    elif a.command=='status':result=service.status(a.id)
    elif a.command=='retry':
        with service.store.connect() as c:
            c.execute("UPDATE toolbox_direct_turns SET state='watching',error=NULL WHERE id=? AND state='blocked'",(a.id,))
        service.poll();result=service.status(a.id)
    else:result=service.poll()
    print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
