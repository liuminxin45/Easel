import importlib.util
from pathlib import Path
import subprocess

import pytest

spec=importlib.util.spec_from_file_location('source_release',Path(__file__).resolve().parents[1]/'scripts/workbench_release.py')
release=importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def test_release_rejects_parallel_dirty_or_untracked_source(tmp_path):
    def git(*args):
        return subprocess.check_output(['git',*args],cwd=tmp_path,text=True).strip()
    git('init','-q')
    path=tmp_path/'source.py';path.write_text('original\n',encoding='utf-8')
    git('add','source.py')
    git('-c','user.name=Fixture','-c','user.email=fixture@invalid','commit','-qm','fixture')
    head=git('rev-parse','HEAD')
    assert release.committed_source(tmp_path)==head
    path.write_text('parallel edit\n',encoding='utf-8')
    with pytest.raises(ValueError,match='working tree is not clean'):
        release.committed_source(tmp_path)
    git('restore','source.py')
    untracked=tmp_path/'another.py';untracked.write_text('pending\n',encoding='utf-8')
    with pytest.raises(ValueError,match='working tree is not clean'):
        release.committed_source(tmp_path)
    git('add','another.py')
    with pytest.raises(ValueError,match='working tree is not clean'):
        release.committed_source(tmp_path)
