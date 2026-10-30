"""Install repository-local protection against pushing private work upstream."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def configure():
    def git(*args):
        return subprocess.run(['git', *args], cwd=ROOT, check=True,
                              capture_output=True, text=True, encoding='utf-8').stdout.strip()
    origin = git('remote', 'get-url', 'origin')
    if origin.removesuffix('.git').rstrip('/').lower() not in ('https://github.com/liuminxin45/easel','git@github.com:liuminxin45/easel','ssh://git@github.com/liuminxin45/easel'):
        raise RuntimeError('Verify the private fork remote before configuring delivery')
    previous = subprocess.run(['git', 'config', '--get', 'core.hooksPath'], cwd=ROOT,
                              capture_output=True, text=True).stdout.strip()
    if previous not in ('', 'scripts/git-hooks'):
        raise RuntimeError('Existing hooksPath must be integrated without replacing its hooks')
    if not previous and (ROOT / '.git/hooks/pre-push').is_file():
        raise RuntimeError('Existing pre-push hook must be integrated before changing hooksPath')
    git('config', 'remote.pushDefault', 'origin')
    git('config', 'remote.upstream.pushurl', 'disabled://official-easel-read-only')
    git('config', 'core.hooksPath', 'scripts/git-hooks')
    return {'push_remote': 'origin', 'upstream_fetch': git('remote', 'get-url', 'upstream'),
            'upstream_push': git('remote', 'get-url', '--push', 'upstream')}


if __name__ == '__main__':
    import json
    print(json.dumps(configure()))
