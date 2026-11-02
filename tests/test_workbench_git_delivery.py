"""Repository-local push protection, without contacting either Git remote."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_private_configuration_preserves_official_fetch_and_disables_official_push(tmp_path):
    subprocess.run(['git', 'init', str(tmp_path)], check=True, capture_output=True)
    for name, url in [('origin', 'https://github.com/liuminxin45/Easel.git'),
                      ('upstream', 'https://github.com/ZJU-REAL/Easel.git')]:
        subprocess.run(['git', '-C', str(tmp_path), 'remote', 'add', name, url], check=True)
    spec = importlib.util.spec_from_file_location('delivery_git', ROOT / 'scripts/configure_workbench_git.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = tmp_path
    result = module.configure()
    assert result['push_remote'] == 'origin'
    assert result['upstream_fetch'] == 'https://github.com/ZJU-REAL/Easel.git'
    assert result['upstream_push'].startswith('disabled://')


def test_hook_rejects_official_urls_even_when_remote_is_renamed():
    shell = shutil.which('sh') or str(Path('C:/Program Files/Git/bin/sh.exe'))
    hook = ROOT / 'scripts/git-hooks/pre-push'
    for name, url in [('upstream', 'disabled://official'),
                      ('origin', 'https://github.com/ZJU-REAL/Easel.git'),
                      ('renamed', 'git@github.com:ZJU-REAL/Easel.git')]:
        assert subprocess.run([shell, str(hook), name, url], capture_output=True).returncode == 1
    assert subprocess.run([shell, str(hook), 'origin', 'https://github.com/liuminxin45/Easel.git'],
                          capture_output=True).returncode == 0


@pytest.mark.parametrize('status',[0,1])
def test_push_hook_runs_readonly_skill_guard_and_blocks_failure(tmp_path,status):
    subprocess.run(['git','init','-q'],cwd=tmp_path,check=True)
    script=tmp_path/'scripts/check_workbench_skill_bytes.py';script.parent.mkdir()
    script.write_text('from pathlib import Path\nimport sys\nPath("guard-called").write_text("read-only-check")\nsys.exit('+str(status)+')\n',encoding='utf-8')
    shell=shutil.which('sh') or str(Path('C:/Program Files/Git/bin/sh.exe'))
    result=subprocess.run([shell,str(ROOT/'scripts/git-hooks/pre-push'),'origin','https://github.com/liuminxin45/Easel.git'],cwd=tmp_path,capture_output=True)
    assert result.returncode==status,result.stderr
    assert (tmp_path/'guard-called').read_text()=='read-only-check'
