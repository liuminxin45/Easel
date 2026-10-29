"""Single-owner supervisor for the immutable private workbench profile."""
from pathlib import Path
import json
import msvcrt
import os
import subprocess
import sys
import time
import re


def main(root=None):
    root=Path(root or Path(__file__).resolve().parents[1]).resolve()
    state=root/'.local/workbench-deployment';state.mkdir(parents=True,exist_ok=True)
    with (state/'manager.lock').open('a+b') as lock:
        lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:return
        children={};logs={};running_release=None
        def flag(name,key):
            try:return json.loads((root/'data'/name).read_text(encoding='utf-8'))[key] is True
            except (OSError,ValueError,KeyError):return False
        while True:
            choice=json.loads((root/'data/active-workbench.json').read_text(encoding='utf-8'))
            if not re.fullmatch(r'workbench-[A-Za-z0-9_-]+',str(choice.get('release',''))):raise RuntimeError('Invalid runtime selection')
            release=(root/'workbench-releases'/choice['release']).resolve()
            if not release.is_relative_to((root/'workbench-releases').resolve()):raise RuntimeError('Runtime outside releases')
            if running_release is not None and running_release!=choice['release'] and any(child.poll() is None for child in children.values()):
                raise RuntimeError('Stop owned roles before changing runtime selection; existing roles were not relabelled')
            running_release=choice['release']
            import hashlib
            if hashlib.sha256((release/'workbench-release.json').read_bytes()).hexdigest()!=choice['manifest_sha256']:
                raise RuntimeError('Selected runtime changed')
            paused=(state/'paused').exists()
            try:admitted=json.loads((state/'admission.json').read_text(encoding='utf-8')).get('workers') is True
            except (OSError,ValueError):admitted=False
            roles=[] if paused else ['server']
            if not paused and admitted:
                roles.extend(['worker','publisher'])
                if (root/'data/feedback-config.json').exists():roles.append('feedback')
                if flag('collection-config.json','enabled'):roles.append('collector')
                if flag('learning-enabled.json','enabled'):roles.append('learning')
                if flag('automation-enabled.json','local_io'):roles.append('local')
            for role in roles:
                if role in children and children[role].poll() is None:continue
                if role in children and hasattr(children[role],'close'):children[role].close()
                from .processes import existing
                previous=existing(root,release,role)
                if previous is not None:
                    children[role]=previous;continue
                if role in logs:logs[role].close()
                logs[role]=(state/(role+'.log')).open('ab')
                env=dict(os.environ);env.pop('PYTHONPATH',None)
                node='C:/Users/38482/AppData/Local/nvm/v24.19.0'
                env['PATH']=node+os.pathsep+env.get('PATH','')
                env.update(PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
                command=[sys.executable,str(release/'launch.py'),role,'--root',str(root),'--port','9123']
                children[role]=subprocess.Popen(command,cwd=release,env=env,stdin=subprocess.DEVNULL,
                    stdout=logs[role],stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
            status={'manager':os.getpid(),'release':choice['release'],'paused':paused,
                'roles':{k:v.pid for k,v in children.items() if v.poll() is None},'heartbeat':time.time()}
            temporary=state/'pids.new';temporary.write_text(json.dumps(status),encoding='utf-8');os.replace(temporary,state/'pids.json')
            time.sleep(3)


if __name__=='__main__':main()
