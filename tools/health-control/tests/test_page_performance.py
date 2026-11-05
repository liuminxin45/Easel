import json
import time
from easel_health_control.page_performance import summarize,sample_memory
from easel_health_control.state import StateStore


def test_summary_combines_only_recent_bounded_metadata(tmp_path):
    now=time.time();p=tmp_path/'performance-2026110501-0.jsonl'
    event={'kind':'summary','metric':'boot','screen':'home','platform':'android','buckets':[0,1,0,0,0,0,0,0,0]}
    slow={'kind':'slow','metric':'boot','screen':'home','platform':'android','duration_ms':4500,'phases_ms':{'document':500},'outcome':'ready','hidden':False,'release':'native-test'}
    p.write_text(json.dumps({'at':now,'events':[event,slow],'dropped':2})+'\n',encoding='utf8')
    result=summarize(tmp_path,now=now)
    assert result['status']=='available' and result['histograms'][0]['buckets'][1]==1
    assert result['slow'][0]['duration_ms']==4500 and result['dropped_reported']==2
    assert summarize(tmp_path,now=now,max_read=10)['status']=='partial'


def test_memory_sample_is_rate_limited_and_independent_of_app(tmp_path):
    store=StateStore(tmp_path);calls=[]
    read=lambda: calls.append(True) or {'status':'normal','available_bytes':123}
    assert sample_memory(store,clock=lambda:100,reader=read)['available_bytes']==123
    sample_memory(store,clock=lambda:130,reader=read)
    assert len(calls)==1
    sample_memory(store,clock=lambda:161,reader=read)
    assert len(calls)==2


def test_broken_optional_performance_cache_does_not_break_health_report(tmp_path):
    from easel_health_control.cli import report
    store=StateStore(tmp_path);(tmp_path/'page-memory.json').write_text('{broken',encoding='utf8')
    (tmp_path/'page-performance-report.json').write_text('{broken',encoding='utf8')
    value=report(store)
    assert value['memory']['status']=='unavailable'
    assert value['page_performance']['status']=='unavailable'
    assert (tmp_path/'report.html').is_file()
