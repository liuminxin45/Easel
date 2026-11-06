"""Install user-selected third-party skills locally; never stage their bytes."""
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from easel_workbench.features.local_skills.install import install
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=ROOT);args=p.parse_args()
 print(json.dumps(install(args.root),ensure_ascii=False),flush=True)
