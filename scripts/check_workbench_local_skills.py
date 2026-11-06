"""Reject accidental publication of local third-party methods and generated entries."""
from pathlib import Path
import argparse,json,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
def check(root=ROOT,base_ref=None,head_ref=None):
 command=['git','ls-tree','-rz','--name-only',head_ref] if head_ref else ['git','ls-files','-z']
 paths=subprocess.check_output(command,cwd=root).decode('utf-8').split('\0')
 if head_ref:
  history=['git','log','--format=','--name-only','-z','--diff-filter=AM',base_ref+'..'+head_ref if base_ref else head_ref,'--','.local/third-party-skills/','skills/builtin/local-*']
  paths+=subprocess.check_output(history,cwd=root).decode('utf-8').split('\0')
 return sorted({path for path in paths if path.lower().startswith(('.local/third-party-skills/','skills/builtin/local-'))})
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--base-ref');parser.add_argument('--head-ref');args=parser.parse_args()
 errors=check(base_ref=args.base_ref,head_ref=args.head_ref);print(json.dumps({'passed':not errors,'third_party_paths_in_index_or_new_commits':errors},ensure_ascii=False));sys.exit(bool(errors))
