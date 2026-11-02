"""Compatibility entry; implementation is owned by application/collection.py."""
if __name__ == "__main__" and not __package__:
    import sys
    from pathlib import Path
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from easel_workbench.application.collection import (
    concurrent, hashlib, json, os, Path, re, shutil, sqlite3, threading, uuid, ROOT, CollectionService, LeaseLost, timestamp, TERMINAL, COUNTERS, atomic, locked, process_creation, owner_is_gone, CollectionWorker, run
)

if __name__ == "__main__":run()
