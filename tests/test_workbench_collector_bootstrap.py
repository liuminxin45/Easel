"""The real script bootstrap must not shadow stdlib with private HTTP routes."""
from pathlib import Path
import json,os,subprocess,sys

import pytest

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'easel_workbench/collector_worker.py'


@pytest.mark.parametrize('entry',['',str(SCRIPT.parent)])
def test_direct_collector_script_directory_cannot_shadow_stdlib_http(tmp_path,entry):
    environment={**os.environ,'AI_DESK_PROJECT_ROOT':str(tmp_path),'PYTHONDONTWRITEBYTECODE':'1'}
    environment.pop('AI_DESK_RELEASE',None)
    code='''import sys,runpy,json,pathlib
sys.path.insert(0,sys.argv[2])
runpy.run_path(sys.argv[1],run_name='trusted_collector_bootstrap_probe')
import urllib.request,http.client
assert not pathlib.Path(http.client.__file__).is_relative_to(pathlib.Path(sys.argv[1]).parent)
print(json.dumps({'stdlib_http':True,'collector_script_directory_removed':str(pathlib.Path(sys.argv[1]).parent) not in sys.path}))
'''
    result=subprocess.run([sys.executable,'-c',code,str(SCRIPT),entry],cwd=SCRIPT.parent,
                          env=environment,capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)=={'stdlib_http':True,'collector_script_directory_removed':True}


def test_direct_collector_retains_the_native_raw_protocol_cli(tmp_path):
    environment={**os.environ,'AI_DESK_PROJECT_ROOT':str(tmp_path),'PYTHONDONTWRITEBYTECODE':'1'}
    environment.pop('AI_DESK_RELEASE',None)
    result=subprocess.run([sys.executable,str(SCRIPT),'--help'],cwd=SCRIPT.parent,
                          env=environment,capture_output=True,text=True,timeout=15)
    assert result.returncode==0 and '--request' in result.stdout and '--source' in result.stdout
