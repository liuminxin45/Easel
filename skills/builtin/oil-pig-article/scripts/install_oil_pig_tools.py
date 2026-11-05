"""Install pinned local poster/article browser tooling without global packages."""
from pathlib import Path
import os
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[4]
SOURCE=ROOT/'skills/builtin/oil-pig-article/references/neo-source/工具/贴图生产'
TARGET=ROOT/'.runtime/neo-poster-tools'


def main():
    node=Path(os.environ.get('LOCALAPPDATA',''))/'nvm/v24.19.0/node.exe'
    npm=node.parent/'node_modules/npm/bin/npm-cli.js'
    if not node.is_file() or not npm.is_file():raise RuntimeError('需要项目约定的 Node 24.19.0')
    TARGET.mkdir(parents=True,exist_ok=True)
    for name in ('package.json','package-lock.json'):
        shutil.copyfile(SOURCE/name,TARGET/name)
    subprocess.run([str(node),str(npm),'ci','--ignore-scripts','--no-audit','--no-fund'],cwd=TARGET,check=True)
    subprocess.run([str(node),'-e',"const p=require('playwright');console.log('browser available:',require('fs').existsSync(p.chromium.executablePath()))"],cwd=TARGET,check=True)


if __name__=='__main__':
    try:main()
    except (RuntimeError,subprocess.CalledProcessError) as error:
        print(str(error),file=sys.stderr);raise SystemExit(1)
