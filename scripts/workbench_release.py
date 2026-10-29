"""Immutable, independently verifiable Easel workbench runtime snapshots."""
from pathlib import Path
import argparse
import datetime as dt
import hashlib
import json
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic(path,value):
    import os
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.new')
    with tmp.open('w',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2);stream.flush();os.fsync(stream.fileno())
    os.replace(tmp,path)


def verify(directory,expected=None):
    directory=Path(directory).resolve();manifest=directory/'workbench-release.json'
    if expected and sha(manifest)!=expected:raise ValueError('Release manifest changed')
    value=json.loads(manifest.read_text(encoding='utf-8'))
    for name,digest in value['files'].items():
        path=(directory/name).resolve()
        if not path.is_relative_to(directory) or not path.is_file() or sha(path)!=digest:
            raise ValueError('Release member changed: '+name)
    return value


def freeze(native):
    native=ROOT/'native-releases'/native
    n=json.loads((native/'native-manifest.json').read_text(encoding='utf-8'))
    for name,digest in n['files'].items():
        if sha(native/name)!=digest:raise ValueError('Frontend bytes changed')
    name='workbench-'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d-%H%M%S')
    target=ROOT/'workbench-releases'/name;target.mkdir(parents=True,exist_ok=False)
    for folder in ('easel_workbench','easel','config'):
        shutil.copytree(ROOT/folder,target/folder,ignore=shutil.ignore_patterns('__pycache__','*.pyc','trend-sources.json','workbench-trend-sources.json','trend-collectors'))
    (target/'launch.py').write_text('''from pathlib import Path
import os,sys,json,hashlib
root=Path(__file__).resolve().parent
m=json.loads((root/'workbench-release.json').read_text(encoding='utf-8'))
for name,expected in m['files'].items():
 p=(root/name).resolve()
 if not p.is_relative_to(root) or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:raise RuntimeError('Frozen runtime changed: '+name)
sys.path.insert(0,str(root))
os.environ['AI_DESK_RELEASE']=m['release']
from easel_workbench.entry import main
main()
''',encoding='utf-8')
    files={p.relative_to(target).as_posix():sha(p) for p in target.rglob('*') if p.is_file()}
    import importlib.metadata
    dependencies=sorted(d.metadata['Name']+'=='+d.version for d in importlib.metadata.distributions())
    value={'schema':1,'release':name,'architecture':'easel-workbench-extension',
        'easel_base':'514caf8089f89b4793063aeae867690cc69bf8b8','files':files,
        'native':{'release':n['release'],'manifest_sha256':sha(native/'native-manifest.json')},
        'python':sys.version,'python_executable':sys.executable,'installed_dependencies':dependencies,
        'capabilities_sha256':sha('D:/Projects/neo-content/.agents/skills/capabilities.json'),
        'created_at':dt.datetime.now(dt.timezone.utc).isoformat()}
    atomic(target/'workbench-release.json',value)
    selection={'release':name,'manifest_sha256':sha(target/'workbench-release.json'),'native':value['native']}
    atomic(ROOT/'.local/workbench-deployment/candidate.json',selection)
    print(json.dumps(selection));return selection


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--native',required=True);a=p.parse_args();freeze(a.native)
