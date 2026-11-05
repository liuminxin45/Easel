"""Exercise the installed-style hook without contacting a Git remote."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('failure', ['structure', 'impact', 'none'])
def test_private_main_push_checks_structure_and_exact_commit_range(tmp_path, failure):
    subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True)
    script = tmp_path/'scripts/check_private_capabilities.py'
    script.parent.mkdir()
    script.write_text('import json,sys\nfrom pathlib import Path\n'
        'with Path("calls.jsonl").open("a") as f:f.write(json.dumps(sys.argv[1:])+"\\n")\n'
        f'failure={failure!r}\n'
        'sys.exit(1 if failure=="structure" and not sys.argv[1:] or failure=="impact" and "--base-ref" in sys.argv else 0)\n', encoding='utf-8')
    shell = shutil.which('sh') or str(Path('C:/Program Files/Git/bin/sh.exe'))
    old, new = 'a'*40, 'b'*40
    result = subprocess.run([shell, str(ROOT/'scripts/git-hooks/pre-push'), 'origin', 'https://github.com/liuminxin45/Easel.git'],
        cwd=tmp_path, input=f'refs/heads/main {new} refs/heads/main {old}\n', capture_output=True, text=True)
    calls = [json.loads(v) for v in (tmp_path/'calls.jsonl').read_text().splitlines()]
    assert result.returncode == (0 if failure=='none' else 1), result.stderr
    assert calls[0] == []
    assert calls[1:] == ([] if failure=='structure' else [['--base-ref', old, '--head-ref', new]])


def test_hook_is_itself_registered_production_source():
    import importlib.util
    spec = importlib.util.spec_from_file_location('private_hook_checker', ROOT/'scripts/check_private_capabilities.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.production_path('scripts/git-hooks/pre-push', {}, {'include': [], 'exclude': []})
