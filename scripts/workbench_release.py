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


def validate_published_skills(root, *, source_root=None):
    """Read-only admission check against the actual published DB releases.

    A self-consistent source fingerprint alone does not prove that the running
    skill can pass ChatBusiness's source check. Use that same check against both
    the checkout and the frozen candidate, without seeding or rewriting the DB.
    Initial/legacy installations still use the explicit builtin migration gate.
    """
    import contextlib
    import sqlite3
    from types import SimpleNamespace
    from easel_workbench.project_skill_sync import managed,matches_source
    root=Path(root).resolve();source=Path(source_root or root).resolve()
    database=root/'data/desk.sqlite'
    result={'checked':0,'source_root':str(source),'skills':[]}
    if not database.is_file():return result
    with contextlib.closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as c:
        tables={row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'creator_skill_pointers' not in tables:return result
        rows=c.execute('SELECT p.skill_id,p.version,v.document FROM creator_skill_pointers p '
                       'LEFT JOIN creator_skill_versions v ON v.skill_id=p.skill_id AND v.version=p.version').fetchall()
        unavailable=[]
        for sid,version,raw in rows:
            if version==0:continue  # unpublished candidates are not callable
            if raw is None:raise ValueError('Published skill release missing: '+sid)
            release=json.loads(raw)
            if release.get('id')!=sid or release.get('version')!=version:
                raise ValueError('Published skill identity changed: '+sid)
            if not managed(release):continue
            available=matches_source(SimpleNamespace(project=source),release,c)
            result['skills'].append({'id':sid,'version':version,'available':available})
            result['checked']+=1
            if not available:unavailable.append(sid+'@'+str(version))
        if unavailable:
            raise ValueError('Published project skills are not callable; exact source bytes or publication receipt differ: '+', '.join(unavailable))
    return result


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


def committed_source(root=None):
    """A release must identify committed source, never another chat's edits."""
    root=Path(root or ROOT)
    status=subprocess.check_output(['git','status','--porcelain','--untracked-files=normal'],cwd=root,text=True)
    if status.strip():
        raise ValueError('Commit or isolate pending work before freezing a runtime; working tree is not clean')
    return subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()


def freeze(native, *, candidate_path=None):
    revision=committed_source()
    validate_published_skills(ROOT)
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
    validate_published_skills(ROOT,source_root=target)
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
    value={'schema':1,'release':name,'architecture':'easel-workbench-extension','session_creation_protocol':2,
        'easel_base':'0f43dc98277eac85fb48952878acad349731d3fc','files':files,
        'native':{'release':n['release'],'manifest_sha256':sha(native/'native-manifest.json')},
        'python':sys.version,'python_executable':sys.executable,'installed_dependencies':dependencies,
        'capabilities_type':'easel_project_builtin','capabilities_sha256':capabilities,
        'workspace_sha256':workspace,
        'upstream_commit':'0f43dc98277eac85fb48952878acad349731d3fc',
        'source_commit':revision,
        'created_at':dt.datetime.now(dt.timezone.utc).isoformat()}
    if committed_source()!=revision:
        raise ValueError('Source commit changed while freezing; candidate was not selected')
    atomic(target/'workbench-release.json',value)
    selection={'release':name,'manifest_sha256':sha(target/'workbench-release.json'),'native':value['native']}
    candidate=Path(candidate_path) if candidate_path is not None else Path('.local/workbench-deployment/candidate.json')
    atomic(ROOT/candidate,selection)
    print(json.dumps(selection));return selection


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--native',required=True)
    p.add_argument('--candidate',type=Path,help='Write the frozen candidate to this path; default keeps the shared deployment candidate')
    a=p.parse_args();freeze(a.native,candidate_path=a.candidate)
