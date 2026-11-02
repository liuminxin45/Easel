import importlib.util
from pathlib import Path
import subprocess
import hashlib
import json

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


@pytest.mark.parametrize('isolated', [False, True])
def test_actual_freeze_respects_candidate_destination_and_preserves_raw_inputs(tmp_path, monkeypatch, isolated):
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=tmp_path, text=True).strip()
    for directory in ('easel_workbench', 'easel', 'config', 'skills/builtin/temp-skill', 'agents/workspace'):
        (tmp_path/directory).mkdir(parents=True, exist_ok=True)
    skill=tmp_path/'skills/builtin/temp-skill/SKILL.md'
    raw=b'---\nname: temp-skill\nlayer: general\nmetadata:\n  openclaw:\n    workbench:\n      schema_version: 1\n      id: temp-skill\n      tasks: [discuss]\n---\nTEMP exact bytes.\n'
    skill.write_bytes(raw)
    (tmp_path/'agents/workspace/AGENTS.md').write_bytes(b'TEMP workspace.\r\n')
    (tmp_path/'.gitignore').write_text('.local/\nworkbench-releases/\nnative-releases/\n', encoding='utf-8')
    git('init', '-q');git('add', '.gitignore', 'skills', 'agents')
    git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@invalid', 'commit', '-qm', 'freeze fixture')
    native=tmp_path/'native-releases/native-fixture';native.mkdir(parents=True)
    (native/'index.html').write_bytes(b'TEMP native shell')
    (native/'native-manifest.json').write_text(json.dumps({'release':'native-fixture', 'files':{'index.html':release.sha(native/'index.html')}}), encoding='utf-8')
    shared=tmp_path/'.local/workbench-deployment/candidate.json';shared.parent.mkdir(parents=True)
    retained=b'{"release":"retained shared candidate"}\n';shared.write_bytes(retained)
    candidate=Path('.local/validation/isolated-candidate.json') if isolated else None
    monkeypatch.setattr(release, 'ROOT', tmp_path)
    result=release.freeze('native-fixture', candidate_path=candidate)
    selected=tmp_path/candidate if isolated else shared
    assert json.loads(selected.read_text(encoding='utf-8')) == result
    if isolated:assert shared.read_bytes() == retained
    package=tmp_path/'workbench-releases'/result['release']
    manifest=release.verify(package,result['manifest_sha256'])
    release.validate_source_binding(manifest,tmp_path)
    assert manifest['source_commit'] == git('rev-parse', 'HEAD')
    assert (package/'skills/builtin/temp-skill/SKILL.md').read_bytes() == raw
    assert (package/'agents/workspace/AGENTS.md').read_bytes() == b'TEMP workspace.\r\n'
    assert manifest['files']['skills/builtin/temp-skill/SKILL.md'] == hashlib.sha256(raw).hexdigest()
