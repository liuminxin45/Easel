"""Attest narrow startup/logging hotfix reuse without relabeling old tests."""
import argparse
import hashlib
import json
from pathlib import Path


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(directory):
    directory=Path(directory).resolve();manifest=directory/'workbench-release.json';data=read(manifest)
    for name,expected in data['files'].items():
        path=(directory/name).resolve()
        assert path.is_relative_to(directory) and sha(path)==expected,name
    return data,{'release':data['release'],'manifest_sha256':sha(manifest)}


def main(args):
    before,old=verify(args.before);after,new=verify(args.after)
    assert set(before['files'])==set(after['files'])
    changes={p:{'before_sha256':before['files'][p],'after_sha256':digest} for p,digest in after['files'].items() if before['files'][p]!=digest}
    assert set(changes)=={'easel_workbench/entry.py','easel_workbench/runtime/server_logging.py'},changes
    for key in ('native','python','python_executable','installed_dependencies','capabilities_sha256'):
        assert before[key]==after[key],key
    previous=read(args.previous_report);startup=read(args.startup_report)
    assert previous['passed'] is True and previous['backend']==old
    assert previous['namespace_isolation']['enabled'] and previous['namespace_isolation']['passed']
    assert startup['passed'] is True and startup['backend']==new and startup['role_count']==7
    assert len(startup['roles'])==7
    for row in startup['roles']:
        assert row['passed'] and row['backend']==new and row['ran_as_main'] and row['real_journal_configure']
        assert row['journal_release']==new['release'] and row['flat_aliases']==0 and not row['forbidden_import_attempts']
    output={'passed':True,'backend':new,'native':after['native'],
        'validation_kind':'unchanged-business-and-UI-reuse-plus-real-entry-startup-tests',
        'business_and_UI_reused_from':{'backend':old,'report':str(Path(args.previous_report).resolve()),'report_sha256':sha(args.previous_report),
            'counts':previous['counts'],'namespace_isolation':previous['namespace_isolation']},
        'new_candidate_actual_startup_test':{'report':str(Path(args.startup_report).resolve()),'report_sha256':sha(args.startup_report),
            'roles':7,'real_journal_configure':True,'journal_release_matches':True,'flat_aliases':0},
        'changed_sources':changes,'unchanged_source_members':len(after['files'])-len(changes),
        'python_and_dependency_closure_unchanged':True,'native_bytes_unchanged':True,'capability_registry_unchanged':True,
        'real_AI_calls':0,'real_platform_writes':0}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in output.items() if k not in ('business_and_UI_reused_from','changed_sources')},ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('before','after','previous-report','startup-report','output'):p.add_argument('--'+name,type=Path,required=True)
    main(p.parse_args())
