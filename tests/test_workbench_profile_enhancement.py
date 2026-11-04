"""Shared enhancement lifecycle and private revision CAS with fake execution only."""
import importlib.util
import json
from pathlib import Path
import pytest
from easel.web_services.profiles import start_profile_enhancement, baseline_profile_files
from easel_workbench.runtime.native_api import NativeApi
spec=importlib.util.spec_from_file_location('profile_fixtures',Path(__file__).with_name('test_workbench_native_api.py'))
f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
runtime,commands=f.runtime,f.commands

def test_shared_lifecycle_background_failure_keeps_baseline():
    states=[];jobs=[]
    def failed(*_):raise RuntimeError('fake unavailable')
    start_profile_enhancement('测试',{},execute=failed,write_status=lambda *value:states.append(value),background=jobs.append)
    assert states[0][1]=='running' and len(jobs)==1
    jobs.pop()()
    assert states[-1][1]=='failed' and '基线画像已可用' in states[-1][2]

@pytest.mark.parametrize('manual',[False,True])
def test_native_enhancement_applies_only_initial_revision(commands,monkeypatch,manual):
    import easel.web_services.profiles as profiles
    jobs=[]
    original=profiles.start_profile_enhancement
    def controlled(*args,**kwargs):
        kwargs['background']=jobs.append
        kwargs['execute']=lambda message,timeout:json.dumps({'files':{name:'增强正文' for name in baseline_profile_files('测试',{})}},ensure_ascii=False)
        return original(*args,**kwargs)
    monkeypatch.setattr(profiles,'start_profile_enhancement',controlled)
    api=NativeApi(commands);api._operation='profile-baseline'
    created=api._build_profile({'name':'测试','form':{}})
    pid=created['name'];before=commands.creator.detail('profile',pid)
    assert created['async'] and api._profile_build_status(pid)['state']=='running'
    if manual:
        commands.creator.command({'id':'manual-save','action':'profile-save','profile_id':pid,'base_revision':before['revision'],'document':{'identity':'手工修改'}})
    jobs.pop()()
    after=commands.creator.detail('profile',pid)
    assert after['identity']==('手工修改' if manual else '增强正文')
    assert api._profile_build_status(pid)['state']==('failed' if manual else 'done')
    assert any(item['revision']==before['revision'] and item['identity']==before['identity'] for item in after['history'])
    restarted=NativeApi(commands)
    assert restarted._profile_build_status(pid)['state']==('failed' if manual else 'done')

def test_restart_running_is_unknown_and_does_not_schedule_replay(commands,monkeypatch):
    import easel.web_services.profiles as profiles
    jobs=[];original=profiles.start_profile_enhancement
    monkeypatch.setattr(profiles,'start_profile_enhancement',lambda *a,**kw:original(*a,**kw,background=jobs.append))
    api=NativeApi(commands);api._operation='baseline-no-replay'
    pid=api._build_profile({'name':'待增强','form':{}})['name']
    assert len(jobs)==1
    assert NativeApi(commands)._profile_build_status(pid)['state']=='unknown'
    assert len(jobs)==1


def test_api_runtime_keeps_baseline_and_dispatches_no_native_skill(commands,monkeypatch):
    import asyncio
    from types import SimpleNamespace
    import easel.web_services.profiles as profiles
    jobs=[];original=profiles.start_profile_enhancement
    monkeypatch.setattr(profiles,'start_profile_enhancement',lambda *a,**kw:original(*a,**kw,background=jobs.append))
    called=[]
    def forbidden(*a,**kw):
        called.append(True)
        raise AssertionError('API runtime cannot dispatch local profile skills')
    fake=SimpleNamespace(settings=SimpleNamespace(current=lambda:{'runtime':'api'}),create_internal_session=forbidden,submit=forbidden)
    async def scenario():
        api=NativeApi(commands);api._operation='api-baseline'
        result=api._build_profile({'name':'API baseline','form':{}},chat=fake,loop=asyncio.get_running_loop())
        await asyncio.to_thread(jobs.pop())
        assert api._profile_build_status(result['name'])['state']=='failed'
        assert commands.creator.detail('profile',result['name'])['identity']
        assert called==[]
    asyncio.run(scenario())
