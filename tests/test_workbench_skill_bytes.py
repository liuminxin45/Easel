"""Read-only CI lock catches checkout conversion and unintended source changes."""
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('workbench_skill_bytes',ROOT/'scripts/check_workbench_skill_bytes.py')
checker=importlib.util.module_from_spec(spec);spec.loader.exec_module(checker)


@pytest.fixture
def source(tmp_path):
    entry=tmp_path/'skills/builtin/topic-research/SKILL.md';entry.parent.mkdir(parents=True)
    entry.write_bytes(b'---\nname: topic-research\nlayer: discover\nmetadata:\n  openclaw:\n    workbench:\n      schema_version: 1\n      id: topic-research\n      tasks: [discuss]\n      resources:\n        - path: skills/shared/workbench/test.md\n---\nTEMP skill\n')
    resource=tmp_path/'skills/shared/workbench/test.md';resource.parent.mkdir(parents=True)
    resource.write_bytes(b'Preserve intentional\r\nmixed line endings\n')
    (tmp_path/'.gitattributes').write_bytes((ROOT/'.gitattributes').read_bytes())
    subprocess.run(['git','init','-q'],cwd=tmp_path,check=True)
    lock=tmp_path/checker.LOCK;lock.parent.mkdir(parents=True)
    lock.write_text(json.dumps({'schema':1,'purpose':'ci_exact_byte_lock_not_runtime_registry','files':checker.inventory(tmp_path)}),encoding='utf-8')
    return tmp_path,resource,lock


def test_ci_byte_lock_accepts_exact_mixed_eol_sources_without_rewriting(source):
    root,resource,lock=source;before=(resource.read_bytes(),lock.read_bytes())
    assert checker.verify(root)=={'passed':True,'files':2,'git_text_conversion_disabled':True}
    assert (resource.read_bytes(),lock.read_bytes())==before


@pytest.mark.parametrize('mutation',['eol','content','missing'])
def test_ci_fails_on_changed_resource_and_keeps_reviewed_lock(source,mutation):
    root,resource,lock=source;before=lock.read_bytes()
    if mutation=='eol':resource.write_bytes(resource.read_bytes().replace(b'\r\n',b'\n'))
    elif mutation=='content':resource.write_bytes(b'Unreviewed content')
    else:resource.unlink()
    with pytest.raises(ValueError):checker.verify(root)
    assert lock.read_bytes()==before


def test_ci_rejects_attributes_that_allow_next_checkout_conversion(source):
    root,_,_=source;(root/'.gitattributes').write_text('* text eol=crlf\n',encoding='utf-8')
    with pytest.raises(ValueError,match='allow Git EOL conversion'):checker.verify(root)


def test_ci_rejects_changed_method_until_explicit_review(source):
    root,_,_=source;entry=root/'skills/builtin/topic-research/SKILL.md'
    entry.write_bytes(entry.read_bytes().replace(b'---\nTEMP skill',b'---\nChanged method'))
    with pytest.raises(ValueError,match='SKILL.md'):checker.verify(root)
