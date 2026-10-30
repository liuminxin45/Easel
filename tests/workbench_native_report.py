"""Combine exact-candidate native acceptance evidence without rerunning writes."""
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def suite(path,expected):
    root=ET.parse(path).getroot();suites=[root] if root.tag=='testsuite' else list(root.iter('testsuite'))
    counts={key:sum(int(value.attrib.get(key,0)) for value in suites) for key in ('tests','failures','errors','skipped')}
    assert counts=={'tests':expected,'failures':0,'errors':0,'skipped':0},counts
    return counts

def main():
    p=argparse.ArgumentParser();p.add_argument('--backend',required=True);p.add_argument('--native',required=True);p.add_argument('--browser',required=True);p.add_argument('--upgrade',required=True);p.add_argument('--completion',required=True);p.add_argument('--completion-binding',required=True);p.add_argument('--frontend',required=True);p.add_argument('--output',required=True);args=p.parse_args()
    backend=Path(args.backend).resolve();native=Path(args.native).resolve();backend_manifest=read(backend/'workbench-release.json');native_manifest=read(native/'native-manifest.json')
    binding={'release':backend_manifest['release'],'manifest_sha256':sha(backend/'workbench-release.json')};web={'release':native_manifest['release'],'manifest_sha256':sha(native/'native-manifest.json')}
    for folder,manifest in [(backend,backend_manifest),(native,native_manifest)]:assert all(sha(folder/path)==digest for path,digest in manifest['files'].items())
    browser=read(args.browser);upgrade=read(args.upgrade);frontend=read(args.frontend)
    assert browser['passed'] and upgrade['passed'] and frontend['passed']
    assert browser['native']==upgrade['native']==frontend['native']==web
    for value in (browser,upgrade):
        assert value['backend']['manifest_sha256']==binding['manifest_sha256'] and Path(value['backend']['directory']).resolve()==backend
        assert value['module_roots_valid'] and value['module_count']>0
    assert len(browser['checks'])==27 and all(check['passed'] for check in browser['checks'])
    assert len(browser['simulated_executions'])==7
    for profile in ('desktop','mobile'):
        executions=[value['format'] for value in browser['simulated_executions'] if value['profile']==profile]
        assert executions==(['poster','article','change','poster-trial-news'] if profile=='desktop' else ['poster','article','change']),executions
    assert len(upgrade['checks'])==8 and all(check['passed'] for check in upgrade['checks'])
    assert frontend['frontend_tests']==173
    for value in (browser,upgrade):assert value['real_AI_calls']==0 and value['real_platform_writes']==0
    completion=suite(args.completion,1)
    bound=read(args.completion_binding)
    assert bound['passed'] and bound['backend']==binding and bound['junit_sha256']==sha(args.completion)
    assert bound['module_roots_valid'] and bound['module_count']>0
    evidence={str(Path(path).resolve()):sha(path) for path in (args.browser,args.upgrade,args.completion,args.completion_binding,args.frontend,__file__)}
    report={'schema_version':1,'passed':True,'backend':binding,'native':web,'checks':{'native_browser':27,'native_file_executions':7,'online_upgrade_and_offline':8,'native_review_adoption_completion':completion,'frontend_contracts':173},'evidence':evidence,'real_AI_calls':0,'real_platform_writes':0,'desktop_validation':'actual Windows Edge on TEMP HTTPS with synthetic inference','mobile_validation':'responsive browser simulation; physical vivo not tested','scope':'native Easel conversation and private version/adoption contracts; synthetic execution is not real model quality or platform publication evidence'}
    target=Path(args.output);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
