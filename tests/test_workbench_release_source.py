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


def test_baseline_record_is_authoritative_and_overlay_mismatch_is_rejected(tmp_path):
    directory=tmp_path/'docs/workbench';directory.mkdir(parents=True)
    base=directory/'upstream-base.json';overlays=directory/'upstream-overlays.json'
    for commit in ('1'*40,'2'*40):
        base.write_text(json.dumps({'upstream_commit':commit}),encoding='utf-8')
        assert release.upstream_baseline(tmp_path)['upstream_commit']==commit
    base.write_text(json.dumps({'upstream_commit':'0f43dc9'}),encoding='utf-8')
    with pytest.raises(ValueError,match='full official baseline'):release.upstream_baseline(tmp_path)
    base.write_text(json.dumps({'upstream_commit':'1'*40}),encoding='utf-8')
    overlays.write_text(json.dumps({'full_upstream_baseline':'2'*40}),encoding='utf-8')
    with pytest.raises(ValueError,match='overlay ledger'):release.upstream_baseline(tmp_path)


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
    (tmp_path/'docs/workbench').mkdir(parents=True)
    baseline=json.loads((release.ROOT/'docs/workbench/upstream-base.json').read_text(encoding='utf-8'))
    (tmp_path/'docs/workbench/upstream-base.json').write_text(json.dumps(baseline),encoding='utf-8')
    (tmp_path/'.gitignore').write_text('.local/\nworkbench-releases/\nnative-releases/\n', encoding='utf-8')
    git('init', '-q');git('add', '.gitignore', 'skills', 'agents', 'docs')
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
    assert manifest['upstream_commit']==manifest['easel_base']==baseline['upstream_commit']
    assert manifest['upstream_baseline']['sha256']==release.sha(package/'docs/workbench/upstream-base.json')
    assert (package/'skills/builtin/temp-skill/SKILL.md').read_bytes() == raw
    assert (package/'agents/workspace/AGENTS.md').read_bytes() == b'TEMP workspace.\r\n'
    assert manifest['files']['skills/builtin/temp-skill/SKILL.md'] == hashlib.sha256(raw).hexdigest()
    original=(tmp_path/'docs/workbench/upstream-base.json').read_bytes()
    (tmp_path/'docs/workbench/upstream-base.json').write_bytes(original+b'\n')
    with pytest.raises(ValueError,match='baseline record changed'):
        release.validate_source_binding(manifest,tmp_path)
