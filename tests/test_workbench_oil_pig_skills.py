"""Contracts for project-local separated skills and imported source evidence."""
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_separated_skills_keep_their_primary_standards_exact_and_local():
    from easel_workbench.skill_catalog import ProjectSkillCatalog
    entries={row['id']:row for row in ProjectSkillCatalog(ROOT).entries()}
    for sid in ('oil-pig-poster', 'oil-pig-article'):
        skill_dir=ROOT/'skills/builtin'/sid
        standards=skill_dir/'references/standards'
        assert len(list(standards.glob('*.md')))>=2
        for path in standards.glob('*.md'):
            source=ROOT/'skills/shared/workbench/neo-source/规范'/path.name
            if not source.is_file():source=ROOT/'skills/shared/workbench/规范'/path.name
            assert path.read_bytes()==source.read_bytes()
            assert path.relative_to(ROOT).as_posix() in {r['path'] for r in entries[sid]['resources']}


def test_each_skill_creative_review_works_without_the_shared_skill_tree(tmp_path):
    import shutil, subprocess
    for sid, format in (('oil-pig-poster', 'poster'), ('oil-pig-article', 'article')):
        package=tmp_path/'skills/builtin'/sid
        shutil.copytree(ROOT/'skills/builtin'/sid,package)
        script=package/'scripts/内容工作流/creative_review.py'
        spec=importlib.util.spec_from_file_location('isolated_'+format,script)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        output=tmp_path/'outputs'/format/'创作检查.json';output.parent.mkdir(parents=True)
        module.prepare_packet(output,root=tmp_path,format=format,profile='custom',work_id='test',version='v1',title='测试标题')
        assert json.loads(output.read_text(encoding='utf8'))['format']==format
        installer=package/'scripts/install_oil_pig_tools.py'
        install_spec=importlib.util.spec_from_file_location('install_'+format,installer)
        install=importlib.util.module_from_spec(install_spec);install_spec.loader.exec_module(install)
        assert install.ROOT==tmp_path and install.SOURCE.is_relative_to(package)
        assert all((install.SOURCE/name).is_file() for name in ('package.json','package-lock.json'))
        if format=='poster':
            node=shutil.which('node')
            assert node, 'Node is required for the poster tools'
            library=(package/'scripts/贴图生产/lib.mjs').as_uri()
            code=f"import({json.dumps(library)}).then(async x => {{ const p=await x.readPolicy(); if (!p.width || !p.titleLimit) process.exit(1); }})"
            import os
            subprocess.run([node,'--input-type=module','-e',code],env={**os.environ,'EASEL_ROOT':str(tmp_path)},check=True,capture_output=True)
    assert not (tmp_path/'skills/shared').exists()


def test_two_skill_catalog_resources_stay_inside_their_own_packages():
    from easel_workbench.skill_catalog import ProjectSkillCatalog
    entries={row['id']:row for row in ProjectSkillCatalog(ROOT).entries()}
    for sid in ('oil-pig-poster','oil-pig-article'):
        folder=(ROOT/'skills/builtin'/sid).resolve()
        for resource in entries[sid]['resources']:
            path=(ROOT/resource['path']).resolve()
            assert path.is_relative_to(folder) and path.is_file(), resource['path']


def test_absorbed_methods_resolve_their_local_shared_references():
    import re
    for sid in ('oil-pig-poster','oil-pig-article'):
        folder=ROOT/'skills/builtin'/sid
        for document in (folder/'references/absorbed').glob('*.md'):
            text=document.read_text(encoding='utf8')
            for name in re.findall(r'(?:`|\]\()(shared/[^`)]+)',text):
                path=(document.parent/name).resolve()
                assert path.is_relative_to(folder.resolve()) and path.is_file(), (document,name)


def test_imported_workflow_snapshot_matches_exact_source_manifest():
    manifest=json.loads((ROOT/'skills/shared/workbench/neo-source/source-manifest.json').read_text(encoding='utf8'))
    paths=set()
    for item in manifest['files']:
        path=(ROOT/item['destination']).resolve()
        assert path.is_relative_to(ROOT/'skills') and path.is_file()
        assert item['destination'] not in paths
        paths.add(item['destination'])
        assert hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256']
        assert path.stat().st_size==item['size']
    assert any('贴图生产原文' in path for path in paths)
    assert any('文章生产原文' in path for path in paths)


def test_native_catalog_has_two_distinct_skill_entries_and_retired_entries_are_not_addressable():
    from easel_workbench.skill_catalog import ProjectSkillCatalog
    entries={row['id']:row for row in ProjectSkillCatalog(ROOT).entries()}
    assert entries['oil-pig-poster']['tasks']==['poster','change']
    assert entries['oil-pig-article']['tasks']==['article','change']
    assert set(entries)=={'oil-pig-poster','oil-pig-article','oil-pig-learn-poster','oil-pig-learn-article'}
    for sid in ('oil-pig-learn-poster','oil-pig-learn-article'):
        assert entries[sid]['tasks']==['reference']
        assert entries[sid]['resources']==[]
    assert (ROOT/'skills/builtin/content-production/SKILL.retired.md').is_file()
    from easel.web_services.skills import create_skills_context
    context=create_skills_context(ROOT,environment=lambda:{},execute=lambda *_:None,persona=lambda _:'',direct_api=lambda:False)
    assert context.find_skill('oil-pig-poster')=='oil-pig-poster'
    assert context.find_skill('oil-pig-article')=='oil-pig-article'
    assert context.find_skill('oil-pig-learn-poster')=='oil-pig-learn-poster'
    assert context.find_skill('oil-pig-learn-article')=='oil-pig-learn-article'
    assert context.find_skill('content-production') is None


def test_native_host_hides_retired_private_entries_without_hiding_official_skills():
    from types import SimpleNamespace
    from easel_workbench.runtime.native_skills import NativeSkills
    adapter=NativeSkills.__new__(NativeSkills)
    adapter.context=lambda:SimpleNamespace(get_skills=lambda:[{'name':name} for name in ('content-production','content-writing','image-production','topic-research','delivery-review','reference-analysis','publication-analysis','oil-pig-poster','oil-pig-article','skill-wechat-article')])
    assert [row['name'] for row in adapter.items()]==['oil-pig-poster','oil-pig-article','skill-wechat-article']


def test_adapted_creative_review_imports_exact_evidence_and_prepares_in_isolated_root(tmp_path):
    import shutil
    source=ROOT/'skills/shared/workbench/neo-source'
    target=tmp_path/'skills/shared/workbench/neo-source'
    target.parent.mkdir(parents=True);shutil.copytree(source,target)
    path=ROOT/'skills/shared/workbench/neo-tools/内容工作流/creative_review.py'
    spec=importlib.util.spec_from_file_location('oil_pig_creative_review',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    output=tmp_path/'outputs/TEMP/创作检查.json';output.parent.mkdir(parents=True)
    module.prepare_packet(output,root=tmp_path,format='poster',profile='custom',work_id='temp-work',version='v1',title='测试标题')
    data=json.loads(output.read_text(encoding='utf8'))
    assert data['format']=='poster' and output.is_file()


def test_adapted_article_review_saves_feedback_and_rejects_stale_revision(tmp_path):
    import pytest
    path=ROOT/'skills/shared/workbench/neo-tools/文章批注/review.py'
    spec=importlib.util.spec_from_file_location('oil_pig_article_review',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    clean=tmp_path/'clean.html';clean.write_text('<html><head><title>标题</title></head><body><h1>标题</h1><section id="article"><p>正文甲，正文乙。</p></section></body></html>',encoding='utf8')
    rendered=tmp_path/'review.html';module.prepare(clean,rendered,tmp_path,'v1')
    md=tmp_path/'article.md';md.write_text('# 标题\n正文',encoding='utf8')
    store=module.Store(tmp_path,tmp_path/'runtime');state=store.initialize(rendered,'v1',md)
    request={key:state[key] for key in ('generation','version','content_hash','edit_seq')}
    request['annotations']=[{'id':'one','anchor':{'scope':'article','start':0,'end':3,'quote':'正文甲','prefix':'','suffix':'，正文乙。'},'comment':'修改意见'}]
    updated=store.update(request)
    assert updated['annotations'][0]['comment']=='修改意见'
    with pytest.raises(module.Conflict):store.update(request)
