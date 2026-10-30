"""Verify and atomically activate static UI without stopping any runtime role.

The runtime manifest retains its original build-time native association. This
operation changes only active-native.json and its deployment evidence; it does
not change admission, runtime selection, business data or process ownership.
"""
from pathlib import Path
import argparse
import json
import re
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from workbench_release import sha,verify
from activate_workbench import authenticate,smoke
from easel_workbench.runtime.feedback_ledger import atomic,locked
from easel_workbench.processes import rows,argv,checked_identity


def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def contained(root,name,base=None):
    if not isinstance(name,str) or not name or '..' in Path(name).parts:raise ValueError('Invalid evidence or asset path')
    path=Path(name)
    if not path.is_absolute():path=(base or root)/path
    root=Path(root).resolve()
    for part in (path,*path.parents):
        if part==root:break
        if part.is_symlink() or getattr(part,'is_junction',lambda:False)():raise ValueError('Release paths cannot follow links')
    result=path.resolve()
    if not result.is_relative_to(root) or not result.is_file():raise ValueError('Evidence or asset is outside the project')
    return result


def binding(value,prefix):
    if not isinstance(value,dict) or not re.fullmatch(prefix+r'-[A-Za-z0-9_-]{1,80}',str(value.get('release',''))) or not re.fullmatch('[a-f0-9]{64}',str(value.get('manifest_sha256',''))):
        raise ValueError('Invalid immutable release binding')
    return {key:value[key] for key in ('release','manifest_sha256')}


def native_package(root,choice,source=False,source_root=None):
    choice=binding(choice,'native');directory=root/'native-releases'/choice['release']
    manifest=contained(root,str(directory/'native-manifest.json'))
    if sha(manifest)!=choice['manifest_sha256']:raise ValueError('Frontend manifest changed')
    document=read(manifest);files=document.get('files')
    if document.get('schema')!=1 or document.get('release')!=choice['release'] or document.get('architecture')!='easel-workbench-extension' or not isinstance(files,dict) or not files:
        raise ValueError('Unexpected frontend package')
    if not {'index.html','auth.html','sw.js','manifest.webmanifest','build-inputs.json'}.issubset(files):raise ValueError('Frontend shell is incomplete')
    for name,expected in files.items():
        if Path(name).is_absolute() or not re.fullmatch('[a-f0-9]{64}',str(expected)):raise ValueError('Invalid frontend member')
        path=contained(root,name,directory)
        if not path.is_relative_to(directory.resolve()) or sha(path)!=expected:raise ValueError('Frontend member changed: '+name)
    if source:
        origin=source_root or root
        inputs=read(directory/'build-inputs.json')
        if inputs.get('node')!='v24.19.0' or not isinstance(inputs.get('inputs'),dict) or not inputs['inputs']:raise ValueError('Frontend build inputs are missing')
        for name,expected in inputs['inputs'].items():
            if Path(name).is_absolute() or sha(contained(root,str(origin/name)))!=expected:raise ValueError('Frontend build source changed: '+name)
    return directory,document


def controls(root):
    data=root/'data';state=root/'.local/workbench-deployment'
    runtime=binding(read(data/'active-workbench.json'),'workbench');native=binding(read(data/'active-native.json'),'native')
    if (state/'paused').exists() or read(state/'admission.json').get('workers') is not True:raise ValueError('Runtime admission is not live')
    cutover=read(state/'cutover.json');owner=read(data/'migration-owner.json')
    if cutover.get('phase')!='live' or Path(cutover.get('target_root','')).resolve()!=root:raise ValueError('Runtime cutover is not live')
    if Path(owner.get('target_root','')).resolve()!=root or any(owner.get(k)!=runtime[k] for k in runtime):raise ValueError('Runtime data ownership changed')
    protected={name:sha(root/name) if (root/name).is_file() else None for name in
               ('data/active-workbench.json','data/active-web.json','data/migration-owner.json',
                '.local/workbench-deployment/admission.json','.local/workbench-deployment/cutover.json')}
    return {'runtime':runtime,'native':native,'protected':protected}


def process_snapshot(root,runtime):
    """PID and native creation time, never the changing heartbeat document."""
    pids=read(root/'.local/workbench-deployment/pids.json')
    if pids.get('release')!=runtime['release'] or pids.get('paused') is not False or 'server' not in pids.get('roles',{}):raise ValueError('Live role snapshot does not match the runtime')
    inventory=rows();result={'manager':None,'roles':{}}
    members={'manager':pids.get('manager'),**pids['roles']}
    for role,pid in members.items():
        row=inventory.get(pid)
        if type(pid) is not int or not row or row.get('name','').lower() not in ('python.exe','pythonw.exe'):raise ValueError('Runtime process is missing')
        args=argv(row.get('command') or '')
        if role=='manager':
            valid=len(args)==2 and Path(args[1]).resolve()==root/'launcher.pyw'
        else:
            valid=(len(args)==7 and Path(args[1]).resolve()==root/'workbench-releases'/runtime['release']/'launch.py'
                   and args[2]==role and args[3]=='--root' and Path(args[4]).resolve()==root and args[5:] == ['--port','9123'])
        if not valid:raise ValueError('Runtime process launch ownership changed')
        handle=checked_identity(row)
        try:
            if handle.exited():raise ValueError('Runtime process exited')
            identity={'pid':pid,'creation_ticks':handle.creation_ticks}
        finally:handle.close()
        if role=='manager':result['manager']=identity
        else:result['roles'][role]=identity
    return result


def report_binding(report):
    value=report.get('native')
    return binding({'release':value,'manifest_sha256':report.get('manifest_sha256')},'native') if isinstance(value,str) else binding(value,'native')


def evidence_members(root,report_path,report):
    for name,expected in report.get('evidence',{}).items():
        if not isinstance(expected,str):raise ValueError('Invalid report evidence digest')
        path=Path(name)
        if not path.is_absolute() and not (report_path.parent/path).is_file():path=root/path
        member=contained(root,str(path),report_path.parent)
        if sha(member)!=expected:raise ValueError('Report evidence changed')


def validate(root,acceptance_path,current):
    acceptance_path=contained(root,str(acceptance_path));acceptance=read(acceptance_path)
    if acceptance.get('schema_version')!=1 or acceptance.get('passed') is not True:raise ValueError('Passing frontend acceptance is required')
    backend=binding(acceptance.get('backend'),'workbench');previous=binding(acceptance.get('previous_native'),'native');native=binding(acceptance.get('native'),'native')
    if backend!=current['runtime'] or previous!=current['native'] or native==previous:raise ValueError('Acceptance does not match the live baseline')
    directory=root/'workbench-releases'/backend['release'];verify(directory,backend['manifest_sha256'])
    source_root=root
    if 'source_root' in acceptance:
        source=acceptance['source_root']
        if not isinstance(source,str) or Path(source).is_absolute() or '..' in Path(source).parts:raise ValueError('Invalid isolated source root')
        source_root=(root/source).resolve()
        if not source_root.is_relative_to(root/'.local/workbench-validation'):raise ValueError('Isolated source must be inside project validation evidence')
    native_package(root,previous);native_package(root,native,source=True,source_root=source_root)
    references=acceptance.get('evidence')
    if not isinstance(references,dict) or not {'browser','upgrade','frontend'}.issubset(references):raise ValueError('Browser, upgrade and frontend evidence are required')
    evidence={}
    for kind,reference in references.items():
        if not isinstance(reference,dict):raise ValueError('Invalid evidence reference')
        path=contained(root,reference.get('path'))
        if sha(path)!=reference.get('sha256'):raise ValueError('Acceptance evidence changed')
        report=read(path)
        if report.get('passed') is not True or report_binding(report)!=native or report.get('errors') or report.get('error'):raise ValueError('Evidence does not confirm this frontend')
        if 'checks' in report and (not isinstance(report['checks'],list) or not report['checks'] or any(not isinstance(check,dict) or check.get('passed') is not True for check in report['checks'])):raise ValueError('Evidence contains incomplete checks')
        if kind in ('browser','upgrade'):
            actual=report.get('backend') or {}
            if actual.get('manifest_sha256')!=backend['manifest_sha256'] or not (actual.get('directory') or actual.get('release')):raise ValueError('Browser evidence is not bound to the active backend')
            if actual.get('directory') and Path(actual['directory']).resolve()!=directory.resolve() or actual.get('release',backend['release'])!=backend['release']:raise ValueError('Browser evidence used another backend')
            if report.get('real_AI_calls')!=0 or report.get('real_platform_writes')!=0:raise ValueError('Frontend acceptance must use isolated inference')
            if kind=='upgrade' and binding(report.get('previous') or report.get('previous_native'),'native')!=previous:raise ValueError('Upgrade evidence used another previous frontend')
            if 'harness_sha256' in report:
                harness=root/'tests'/('workbench_native_browser.py' if kind=='browser' else 'workbench_native_upgrade.py')
                if sha(harness)!=report['harness_sha256']:raise ValueError('Validation harness changed after acceptance')
        if kind=='frontend':
            count=report.get('test_count',report.get('frontend_tests'))
            if type(count) is not int or count<1 or not isinstance(report.get('evidence'),dict) or not report['evidence']:raise ValueError('Frontend summary must bind its passing test transcript')
        evidence_members(root,path,report)
        evidence[kind]={'path':str(path.relative_to(root)),'sha256':sha(path)}
    return acceptance,native,{'path':str(acceptance_path.relative_to(root)),'sha256':sha(acceptance_path),'evidence':evidence}


def frontend_smoke(client,root,native):
    result=smoke(client,native);directory,manifest=native_package(root,native)
    page=client.get('/native/')
    if page.status_code!=200 or not re.search(r'<meta\b[^>]*name=[\"\']native-release[\"\'][^>]*content=[\"\']'+re.escape(native['release'])+r'[\"\']',page.text):raise ValueError('Selected frontend HTML is not live')
    prefix='/native-assets/'+native['release']+'/'
    assets=set(re.findall(r'(?:src|href)=[\"\']('+re.escape(prefix)+r'[^\"\']+)[\"\']',page.text))
    if not assets:raise ValueError('Selected frontend entry assets are missing')
    for url in sorted(assets):
        name=url.removeprefix(prefix);expected=manifest['files'].get(name);response=client.get(url)
        if not expected or response.status_code!=200 or __import__('hashlib').sha256(response.content).hexdigest()!=expected:raise ValueError('Served frontend asset changed')
    for url,name in (('/native/sw.js','sw.js'),('/native/manifest.webmanifest','manifest.webmanifest')):
        response=client.get(url)
        if response.status_code!=200 or __import__('hashlib').sha256(response.content).hexdigest()!=manifest['files'][name]:raise ValueError('Served frontend shell resource changed')
    return {**result,'entry_assets':len(assets),'shell_resources':2}


def execute(acceptance_path,*,apply=False,expected_native=None,root=ROOT):
    root=Path(root).resolve();state=root/'.local/workbench-deployment'
    with locked(state/'frontend-release.lock',timeout=30):
        before=controls(root);acceptance,native,proof=validate(root,acceptance_path,before)
        if expected_native is not None and before['native']['release']!=expected_native:raise ValueError('Expected previous frontend changed')
        processes=process_snapshot(root,before['runtime'])
        if not apply:return {'status':'ready','scope':'frontend_only','backend':before['runtime'],'previous_native':before['native'],'native':native,'acceptance':proof,'processes':processes,'applied':False}
        client=None;selected=False
        try:
            client=authenticate()
            if controls(root)!=before or process_snapshot(root,before['runtime'])!=processes:raise ValueError('Live runtime or processes changed before frontend activation')
            _,_,fresh=validate(root,acceptance_path,before)
            if fresh!=proof:raise ValueError('Acceptance changed before activation')
            atomic(root/'data/active-native.json',native);selected=True
            checked=frontend_smoke(client,root,native)
            after=controls(root);current_processes=process_snapshot(root,before['runtime'])
            if after!={**before,'native':native} or current_processes!=processes:raise ValueError('Runtime or processes changed during frontend activation')
            # Revalidate evidence/source without changing the original baseline.
            if validate(root,acceptance_path,before)[2]!=proof:raise ValueError('Acceptance changed during activation')
            result={'status':'live','scope':'frontend_only','backend':before['runtime'],'previous_native':before['native'],'native':native,
                    'acceptance':proof,'smoke':checked,'before_processes':processes,'after_processes':current_processes,
                    'backend_changed':False,'workers_restarted':False,'business_database_opened':False,'admission_changed':False}
            atomic(state/'frontend-upgrades'/(native['release']+'.json'),result)
            return result
        except BaseException as error:
            rollback=False
            if selected:
                try:
                    now=controls(root)
                    if now=={**before,'native':native}:
                        atomic(root/'data/active-native.json',before['native']);rollback=True
                except (OSError,ValueError,TypeError,KeyError):pass
            failure={'status':'failed','scope':'frontend_only','backend':before['runtime'],'previous_native':before['native'],
                     'native':native,'error_type':type(error).__name__,'pointer_changed':selected,'native_rolled_back':rollback,
                     'runtime_stop_requested':False,'business_database_opened':False,'acceptance':proof}
            atomic(state/'frontend-upgrades'/(native['release']+'.failure-'+uuid.uuid4().hex+'.json'),failure)
            raise
        finally:
            if client is not None:client.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--acceptance',required=True,type=Path);parser.add_argument('--expected-native');parser.add_argument('--apply',action='store_true')
    options=parser.parse_args()
    print(json.dumps(execute(options.acceptance,apply=options.apply,expected_native=options.expected_native),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
