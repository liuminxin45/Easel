"""CI-only exact-byte lock for private skill sources; never a runtime registry.

Default is read-only. After an intentional reviewed skill change, --record
updates this source lock; publishing a DB version remains a separate operation.
"""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
LOCK=Path('docs/workbench/skill-source-bytes.json')


def inventory(root):
    from easel_workbench.skill_catalog import ProjectSkillCatalog
    root=Path(root).resolve();files={}
    for skill in ProjectSkillCatalog(root).entries():
        for name in [skill['entry'],*[r['path'] for r in skill['resources']]]:
            files[name]=hashlib.sha256((root/name).read_bytes()).hexdigest()
    if not files:raise ValueError('No private skill source files found')
    return dict(sorted(files.items()))


def verify(root):
    root=Path(root).resolve();value=json.loads((root/LOCK).read_text(encoding='utf-8'))
    if value.get('schema')!=1 or value.get('purpose')!='ci_exact_byte_lock_not_runtime_registry':
        raise ValueError('Invalid private skill source lock')
    actual=inventory(root);expected=value['files']
    changed=sorted(name for name in set(actual)|set(expected) if actual.get(name)!=expected.get(name))
    if changed:raise ValueError('Private skill raw bytes changed (review before updating the lock): '+', '.join(changed))
    result=subprocess.check_output(['git','check-attr','-z','--stdin','text'],cwd=root,
                                   input=('\0'.join(actual)+'\0').encode('utf-8')).decode('utf-8').split('\0')
    unprotected=[result[i] for i in range(0,len(result)-1,3) if result[i+2]!='unset']
    if unprotected:raise ValueError('Private skill files allow Git EOL conversion: '+', '.join(unprotected))
    return {'passed':True,'files':len(actual),'git_text_conversion_disabled':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record',action='store_true',help='Explicitly record reviewed source bytes; never run automatically in CI')
    args=parser.parse_args()
    if args.record:
        value={'schema':1,'purpose':'ci_exact_byte_lock_not_runtime_registry','files':inventory(ROOT)}
        (ROOT/LOCK).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(verify(ROOT),ensure_ascii=False))


if __name__=='__main__':main()
