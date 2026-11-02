"""Compatibility entry; implementation is owned by application/distribution.py."""
if __name__ == "__main__" and not __package__:
    import sys
    from pathlib import Path
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from easel_workbench.application.distribution import (
    dt, hashlib, os, pathlib, threading, ROOT, Store, stamp, process_identity, DistributionService, digest, preflight_assets, Toolbox, DistributionWorker, run
)

if __name__ == "__main__":run()
