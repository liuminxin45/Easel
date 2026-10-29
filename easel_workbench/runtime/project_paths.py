import os,pathlib
if 'AI_DESK_RELEASE' in os.environ:
    selected_root=os.environ.get('AI_DESK_PROJECT_ROOT')
    if not selected_root or not pathlib.Path(selected_root).is_absolute():
        raise RuntimeError('冻结运行包必须显式指定绝对路径的业务根目录')
ROOT=pathlib.Path(os.environ.get("AI_DESK_PROJECT_ROOT",pathlib.Path(__file__).resolve().parent)).resolve()
