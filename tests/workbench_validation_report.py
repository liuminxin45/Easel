"""Combine only matching, successful immutable-candidate acceptance reports."""
import argparse
import hashlib
import json
from pathlib import Path


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def combine(prefix,output,browser_output=None):
    prefix=Path(prefix).resolve()
    parts={mode:prefix.with_name(prefix.name+'-'+mode) for mode in ('contracts','browser','surfaces','upgrade')}
    if browser_output:parts['browser']=Path(browser_output).resolve()
    validations={mode:read(directory/'validation.json') for mode,directory in parts.items()}
    reference=validations['contracts']
    for mode,v in validations.items():
        assert v['passed'] is True and v['mode']==mode
        for field in ('backend','native','python','python_version','runtime_inputs_sha256'):
            assert v[field]==reference[field],(mode,field)
        assert v['source_stable_throughout_run'] is True
        assert v['real_AI_calls']==v['real_platform_writes']==0
    contracts=read(parts['contracts']/'contracts.json')
    browser=read(parts['browser']/'execution-browser.json')
    surfaces=read(parts['surfaces']/'surfaces/report.json')
    upgrade=read(parts['upgrade']/'upgrade.json')
    for result in (contracts,browser,surfaces,upgrade):
        assert result['passed'] is True
        assert result['real_AI_calls']==result['real_platform_writes']==0
    assert contracts['tests']>=184
    assert len(browser['checks'])>=17 and len(browser['simulated_executions'])==8
    assert len(surfaces['checks'])>=30 and len(upgrade['checks'])>=8
    isolation=browser.get('namespace_isolation') or {}
    if isolation.get('enabled'):
        assert isolation.get('passed') and isolation.get('flat_aliases_during')==0 and not isolation.get('forbidden_import_attempts')
    files={}
    for directory in parts.values():
        for p in directory.rglob('*'):
            if p.is_file():files[str(p)]=sha(p)
    result={'passed':True,'backend':reference['backend'],'native':reference['native'],
        'python':reference['python'],'python_version':reference['python_version'],
        'counts':{'business_contract_tests':contracts['tests'],'execution_browser_checks':len(browser['checks']),
                  'page_browser_checks':len(surfaces['checks']),'upgrade_reconnect_checks':len(upgrade['checks']),
                  'simulated_native_executions':len(browser['simulated_executions'])},
        'real_AI_calls':0,'real_platform_writes':0,'mobile_validation':'browser simulation',
        'namespace_isolation':isolation,
        'harness_sha256_by_mode':{mode:v['harness_sha256'] for mode,v in validations.items()},'runtime_inputs_sha256':reference['runtime_inputs_sha256'],
        'evidence':files}
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='evidence'},ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--prefix',required=True);p.add_argument('--output',required=True)
    p.add_argument('--browser-output')
    args=p.parse_args();combine(args.prefix,args.output,args.browser_output)
