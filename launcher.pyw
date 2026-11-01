"""Private profile logon entry; upstream Easel launchers stay independent."""
from pathlib import Path
from easel_workbench.supervisor import main
import datetime
import os
import traceback


def launch(root):
    try:
        main(root)
    except Exception:
        # pythonw has no console. Preserve the real manager failure for the
        # next investigation while still failing the OS task for recovery.
        directory = root / '.local/workbench-deployment'
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / 'manager.log').open('a', encoding='utf-8') as stream:
            stream.write(f'\n{datetime.datetime.now(datetime.timezone.utc).isoformat()} manager={os.getpid()} failed\n')
            traceback.print_exc(file=stream)
        raise


if __name__ == '__main__':
    launch(Path(__file__).resolve().parent)
