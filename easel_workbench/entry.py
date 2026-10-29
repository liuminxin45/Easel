"""Explicit process entry; no process is started merely by importing Easel."""
import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('role', choices=('server','worker','collector','publisher','learning','local','feedback'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--port', type=int, default=9124)
    options = parser.parse_args()
    root = options.root.resolve()
    os.environ['AI_DESK_PROJECT_ROOT'] = str(root)
    if os.name=='nt':
        import msvcrt
        directory=root/'.local/workbench-deployment/roles';directory.mkdir(parents=True,exist_ok=True)
        role_lock=(directory/(options.role+'.lock')).open('a+b')
        role_lock.seek(0);role_lock.write(b'0');role_lock.flush();role_lock.seek(0)
        try:msvcrt.locking(role_lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:return
    os.environ['EASEL_WORKBENCH_COLLECTORS'] = 'python'
    if os.environ.get('AI_DESK_RELEASE'):
        os.environ['EASEL_WORKBENCH_ADMISSION']='1'
    from .runtime import server_logging as journal
    journal.configure(root/'data/logs/toolbox','worker' if options.role in ('collector','publisher') else options.role)
    journal.install_exception_hooks()
    journal.emit('process_started')
    if options.role == 'server':
        import uvicorn
        from .application import create_app
        import threading
        from .runtime.news_overviews import background
        app=create_app(root=root)
        stop=threading.Event()
        def start_background():
            if os.environ.get('EASEL_WORKBENCH_ADMISSION')=='1':
                import json
                while not stop.is_set():
                    try:
                        if json.loads((root/'.local/workbench-deployment/admission.json').read_text(encoding='utf-8')).get('workers') is True:break
                    except (OSError,ValueError):pass
                    stop.wait(1)
            if not stop.is_set():background(app.state.overviews,stop)
        threading.Thread(target=start_background,daemon=True).start()
        try:
            uvicorn.run(app, host='127.0.0.1', port=options.port, access_log=False)
        finally:
            stop.set()
        return
    from importlib import import_module
    module, function = {'worker':('poster_executor','run'),'collector':('collection_worker','run'),
        'publisher':('distribution_worker','run'),'learning':('learning_worker','run'),
        'local':('local_worker','run'),'feedback':('news_feedback','worker')}[options.role]
    service = getattr(import_module('easel_workbench.runtime.'+module),function)
    if options.role == 'feedback':
        from .runtime.desk import Store
        service(Store())
    else:
        service()


if __name__ == '__main__':
    main()
