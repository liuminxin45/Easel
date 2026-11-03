"""Deployment entry for the exact frozen shared zero-model browser journey."""
from pathlib import Path
import sys

if __name__=='__main__':
    # Parse only the immutable module location here; the frozen module owns all
    # setup/scenarios. The independent controller executes the same module.
    import argparse
    parser=argparse.ArgumentParser(add_help=False);parser.add_argument('--backend',required=True,type=Path)
    args,_=parser.parse_known_args();sys.path.insert(0,str(args.backend.resolve()))
    from easel_workbench.diagnostics.session_journey import main
    raise SystemExit(main())
