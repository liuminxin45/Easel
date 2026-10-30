"""Immutable, independently verifiable Easel workbench runtime snapshots."""
from pathlib import Path
import argparse
import datetime as dt
import hashlib
import json
import shutil
import subprocess
import sys
import subprocess

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def capabilities_revision(root):
    from easel_workbench.skill_catalog import ProjectSkillCatalog
    catalog=ProjectSkillCatalog(root)
    if not catalog.available():raise ValueError('Project builtin capability catalog is missing')
    return catalog.revision()


def workspace_revision(root):
    root=Path(root).resolve();directory=root/'agents/workspace'
    if not (directory/'AGENTS.md').is_file():raise ValueError('Project workspace instructions are missing')
    paths=[*directory.glob('*.md')]
    if (root/'AGENTS.md').is_file():paths.append(root/'AGENTS.md')
    value={p.relative_to(root).as_posix():sha(p) for p in sorted(paths)}
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def validate_source_binding(package,root):
    if package.get('capabilities_type')!='easel_project_builtin':
        raise ValueError('New runtime candidates must use project builtin skills')
    if package.get('capabilities_sha256')!=capabilities_revision(root):
        raise ValueError('Skill source changed after candidate validation')
    if package.get('workspace_sha256')!=workspace_revision(root):
        raise ValueError('Workspace instructions changed after candidate validation')


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
    capabilities=capabilities_revision(ROOT);workspace=workspace_revision(ROOT)
    name='workbench-'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d-%H%M%S')
    target=ROOT/'workbench-releases'/name;target.mkdir(parents=True,exist_ok=False)
    for folder in ('easel_workbench','easel','config','skills'):
        shutil.copytree(ROOT/folder,target/folder,ignore=shutil.ignore_patterns('__pycache__','*.pyc','trend-sources.json','workbench-trend-sources.json','trend-collectors'))
    shutil.copytree(ROOT/'agents/workspace',target/'agents/workspace',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    if (ROOT/'AGENTS.md').is_file():shutil.copy2(ROOT/'AGENTS.md',target/'AGENTS.md')
    if capabilities_revision(target)!=capabilities or capabilities_revision(ROOT)!=capabilities:
        raise ValueError('Project skill source changed while freezing')
    if workspace_revision(target)!=workspace or workspace_revision(ROOT)!=workspace:
        raise ValueError('Project workspace changed while freezing')
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
        'easel_base':'5a597e5f3ef5b01098b53f36caf719dd9a32b7bf','files':files,
        'native':{'release':n['release'],'manifest_sha256':sha(native/'native-manifest.json')},
        'python':sys.version,'python_executable':sys.executable,'installed_dependencies':dependencies,
        'capabilities_type':'easel_project_builtin','capabilities_sha256':capabilities,
        'workspace_sha256':workspace,
        'upstream_commit':'5a597e5f3ef5b01098b53f36caf719dd9a32b7bf',
        'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'created_at':dt.datetime.now(dt.timezone.utc).isoformat()}
    atomic(target/'workbench-release.json',value)
    selection={'release':name,'manifest_sha256':sha(target/'workbench-release.json'),'native':value['native']}
    atomic(ROOT/'.local/workbench-deployment/candidate.json',selection)
    print(json.dumps(selection));return selection


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--native',required=True);a=p.parse_args();freeze(a.native)
