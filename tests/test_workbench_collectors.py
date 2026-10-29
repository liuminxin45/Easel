"""Private raw acquisition preserves bodies and leaves AI/persistence upstream."""
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
import pytest
import os

from easel_workbench import collectors


@pytest.fixture(autouse=True)
def restore_worker_process_environment():
    names=('AI_DESK_PROJECT_ROOT','EASEL_WORKBENCH_COLLECTOR_CHILD')
    before={name:os.environ.get(name) for name in names}
    yield
    for name,value in before.items():
        if value is None:os.environ.pop(name,None)
        else:os.environ[name]=value


def test_raw_receipt_preserves_original_candidate_and_coverage(tmp_path, monkeypatch):
    monkeypatch.setenv('AI_DESK_PROJECT_ROOT',str(tmp_path))
    value=[[{'event_id':'old-stable-id','title':'原题','description':'完整正文\n不可截断'}],{'coverage':'partial','errors':[{'source':'x'}]}]
    observed=[]
    def protocol(source, environment):
        observed.append((source,environment))
        request=json.loads(Path(source.options['args'][1]).read_text(encoding='utf-8'))
        raw=json.dumps(value,ensure_ascii=False).encode()
        Path(request['receipt']).write_bytes(raw)
        return {'version':1,'items':[{'id':hashlib.sha256(raw).hexdigest()}]}
    with patch('easel.trends.runner.collect',protocol):
        result=collectors.acquire('aihot',{'folder':str(tmp_path)})
    assert result==value
    assert observed[0][0].type=='python'
    assert not any('KEY' in k or 'TOKEN' in k for k in observed[0][1])


def test_changed_receipt_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv('AI_DESK_PROJECT_ROOT',str(tmp_path))
    def protocol(source,environment):
        request=json.loads(Path(source.options['args'][1]).read_text(encoding='utf-8'))
        Path(request['receipt']).write_text('[]')
        return {'items':[{'id':'0'*64}]}
    import pytest
    with patch('easel.trends.runner.collect',protocol),pytest.raises(ValueError,match='receipt'):
        collectors.acquire('aihot',{})


def test_producer_only_calls_raw_reader_and_binds_receipt(tmp_path, monkeypatch):
    from easel_workbench.runtime import collection_sources
    monkeypatch.setattr(collection_sources,'collect_aihot',lambda folder,**kwargs:([{'event_id':'exact','description':'完整原文'}],{'coverage':'ok'}))
    receipt=tmp_path/'raw.json'
    result=collectors.produce({'mode':'aihot','source':'60028244fb76','root':str(tmp_path),
        'parameters':{'folder':str(tmp_path)},'receipt':str(receipt)})
    assert result['version']==1
    assert result['items'][0]['id']==hashlib.sha256(receipt.read_bytes()).hexdigest()
    assert json.loads(receipt.read_text(encoding='utf-8'))[0][0]['event_id']=='exact'


def test_binary_and_original_timestamps_roundtrip():
    import datetime as dt
    value={'original':b'\x00\xff','date':dt.datetime(2026,10,30,tzinfo=dt.timezone.utc),'source_ids':{'a','b'}}
    result=collectors.decode(collectors.encode(value))
    assert result['original']==value['original'] and result['date']==value['date']
    assert result['source_ids']==['a','b']


def test_registry_contains_exactly_nine_original_python_source_ids():
    sources=collectors.registered_sources()
    assert {s.id for s in sources}==set(collectors.SOURCES.values())|collectors.DISCOVERY
    assert all(s.type=='python' and Path(s.options['script']).name=='collector_worker.py' for s in sources)
    assert all(s.options['args']==['--source',s.id] for s in sources)


@pytest.mark.parametrize('mode,source',[(m,s) for m,s in collectors.SOURCES.items()]+[('discovery',s) for s in sorted(collectors.DISCOVERY)])
def test_every_source_dispatches_unchanged_raw_payload_via_fork_registry(tmp_path,monkeypatch,mode,source):
    monkeypatch.setenv('AI_DESK_PROJECT_ROOT',str(tmp_path))
    monkeypatch.setenv('https_proxy','http://127.0.0.1:7890')
    monkeypatch.setenv('SSL_CERT_FILE','C:/safe/ca.pem')
    monkeypatch.setenv('USERPROFILE','C:/Users/owner')
    monkeypatch.setenv('APPDATA','C:/Users/owner/AppData/Roaming')
    monkeypatch.setenv('GH_TOKEN','never-forward')
    monkeypatch.setenv('MODEL_API_KEY','never-forward')
    original={'body':'完整原文\n'+('甲'*3000),'candidate_id':'existing-id','ack':False,'coverage':{'errors':['kept']}}
    def protocol(definition,environment):
        assert definition.id==source and definition.type=='python'
        assert {k.lower():v for k,v in environment.items()}['https_proxy']=='http://127.0.0.1:7890'
        assert environment['SSL_CERT_FILE']=='C:/safe/ca.pem'
        assert 'GH_TOKEN' not in environment and 'MODEL_API_KEY' not in environment
        explicit=definition.options['env']
        assert ('USERPROFILE' in explicit)==(mode=='weekly')
        assert 'GH_TOKEN' not in explicit
        request=json.loads(Path(definition.options['args'][1]).read_text(encoding='utf-8'))
        assert request['source']==source and request['mode']==mode
        raw=json.dumps(original,ensure_ascii=False).encode()
        collectors.write_receipt(request['receipt'],raw)
        return {'version':1,'items':[{'id':hashlib.sha256(raw).hexdigest()}]}
    with patch('easel.trends.runner.collect',protocol):
        assert collectors.acquire(mode,{},source=source)==original


def test_chunked_large_original_roundtrips_without_breaching_individual_file_limit(tmp_path):
    raw=json.dumps({'original':'内容'*1500000},ensure_ascii=False).encode()
    path=tmp_path/'payload.json'
    collectors.write_receipt(path,raw)
    assert collectors.read_receipt(path)==raw
    assert all(p.stat().st_size<=512*1024 for p in tmp_path.glob('payload.json.*'))
    path.with_name(path.name+'.0001').write_bytes(b'')
    with pytest.raises(ValueError,match='Incomplete'):
        collectors.read_receipt(path)


def test_source_reserved_marker_fields_stay_source_data():
    raw={'__workbench_bytes__':'not-base64','__workbench_date__':'not-date',
         '__workbench_mapping__':['source data'],'__workbench_chunks__':17}
    assert collectors.decode(collectors.encode(raw))==raw


def test_unknown_or_mismatched_source_is_rejected_before_dispatch(tmp_path,monkeypatch):
    monkeypatch.setenv('AI_DESK_PROJECT_ROOT',str(tmp_path))
    with pytest.raises(ValueError,match='identity'):
        collectors.acquire('discovery',{},source='other-source')
    with pytest.raises(ValueError,match='identity'):
        collectors.acquire('aibot',{},source='github-trending')


def test_standard_source_preview_contains_real_titles_not_receipt_placeholders(tmp_path,monkeypatch):
    from easel_workbench.runtime.collection_adapters import aibot_daily_news
    monkeypatch.setattr(aibot_daily_news,'collect',lambda page,day:[('真实候选标题','完整正文','https://example.com/news')])
    def produce(request):
        collectors.write_receipt(request['receipt'],json.dumps('source HTML').encode())
    monkeypatch.setattr(collectors,'produce',produce)
    payload=collectors.source_preview('cc09dbccc795',tmp_path)
    assert payload['items'][0]['title']=='真实候选标题'
    assert payload['items'][0]['url']=='https://example.com/news'
    assert '原始采集回执' not in payload['items'][0]['title']


def test_explicit_per_source_interpreter_is_preserved(tmp_path,monkeypatch):
    from dataclasses import replace
    monkeypatch.setenv('AI_DESK_PROJECT_ROOT',str(tmp_path))
    source=next(s for s in collectors.registered_sources() if s.id=='cc09dbccc795')
    configured=replace(source,options={**source.options,'python':'C:/source-env/python.exe'})
    monkeypatch.setattr(collectors,'registered_sources',lambda:[configured])
    def protocol(definition,environment):
        assert definition.options['python']=='C:/source-env/python.exe'
        request=json.loads(Path(definition.options['args'][1]).read_text(encoding='utf-8'))
        raw=json.dumps('original full HTML').encode()
        collectors.write_receipt(request['receipt'],raw)
        return {'items':[{'id':hashlib.sha256(raw).hexdigest()}]}
    with patch('easel.trends.runner.collect',protocol):
        assert collectors.acquire('aibot',{})=='original full HTML'


def test_explicit_missing_registry_does_not_enable_default_sources(tmp_path,monkeypatch):
    monkeypatch.setenv('EASEL_WORKBENCH_TREND_CONFIG',str(tmp_path/'missing.json'))
    with pytest.raises(ValueError):collectors.registered_sources()
