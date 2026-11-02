"""Verified external-package bootstrap for the application Python under -I."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from easel_health_control.canary_worker import main
raise SystemExit(main())
