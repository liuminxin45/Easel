"""CI-only exact-byte lock for private skill sources; never a runtime registry.

Default is read-only. After an intentional reviewed skill change, --record
updates this source lock; publishing a DB version remains a separate operation.
"""
from pathlib import Path
import argparse
import hashlib
import io
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
    # Attribute changes can leave Git's stat cache saying "clean" while the
    # index still contains formerly normalized bytes. Check the actual blobs,
    # not git status, so a push cannot omit the correct mixed/CRLF originals.
    payload=''.join(':'+name+'\n' for name in actual).encode('utf-8')
    stream=io.BytesIO(subprocess.check_output(['git','cat-file','--batch'],cwd=root,input=payload))
    index_changed=[]
    for name,expected_sha in actual.items():
        header=stream.readline().split()
        if len(header)!=3 or header[1]!=b'blob':raise ValueError('Private skill is not staged in Git: '+name)
        raw=stream.read(int(header[2]));assert stream.read(1)==b'\n'
        if hashlib.sha256(raw).hexdigest()!=expected_sha:index_changed.append(name)
    if index_changed:raise ValueError('Git index differs from reviewed skill bytes; explicitly stage exact resources: '+', '.join(index_changed))
    return {'passed':True,'files':len(actual),'git_text_conversion_disabled':True,'git_index_matches':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record',action='store_true',help='Explicitly record reviewed source bytes; never run automatically in CI')
    args=parser.parse_args()
    if args.record:
        value={'schema':1,'purpose':'ci_exact_byte_lock_not_runtime_registry','files':inventory(ROOT)}
        (ROOT/LOCK).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(verify(ROOT),ensure_ascii=False))


if __name__=='__main__':main()
