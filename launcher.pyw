"""Private profile logon entry; upstream Easel launchers stay independent."""
from pathlib import Path
from easel_workbench.supervisor import main

main(Path(__file__).resolve().parent)
