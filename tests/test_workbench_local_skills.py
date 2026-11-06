"""TEMP-only contracts for local methods; no network, Agent or production writes."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from easel_workbench.features.local_skills.catalog import Library
from easel_workbench.features.local_skills.install import atomic, digest
from easel_workbench.features.local_skills import stars


@pytest.fixture
def library(tmp_path):
    home = tmp_path / '.local/third-party-skills'
    content = {
        'methods/writer/SKILL.md': '# Writer\nRead ../shared/style.md when needed.\n',
        'methods/writer/references/rules.md': 'Exact writing rules, not injected in list.',
        'methods/shared/style.md': 'Shared same-repository reference.',
        'methods/image/SKILL.md': '# Illustrator\n',
        'methods/layout/SKILL.md': '# Formatter\n',
        'methods/publish/SKILL.md': '# Publisher\n',
        'methods/other/SKILL.md': 'UNSELECTED METHOD MUST NOT BE FROZEN',
    }
    commit = 'a' * 40
    package = home / 'packages/author/methods' / commit
    for name, value in content.items():
        path = package / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding='utf-8')
    source = {'repository': 'author/methods', 'commit': commit,
              'directory': package.relative_to(home).as_posix(),
              'files': {name: digest((package / name).read_bytes()) for name in content},
              'license_paths': []}
    rows = []
    for suffix, category, stages_, blocked in (
        ('writer', 'writing', ['writing', 'review'], ''),
        ('image', 'image', ['cover', 'illustration'], ''),
        ('layout', 'layout', ['layout'], ''),
        ('publish', 'publish', [], '需配置：测试发布通道'),
    ):
        rows.append({'id': 'local-' + suffix, 'repository': source['repository'],
                     'commit': commit, 'entry': f'methods/{suffix}/SKILL.md',
                     'original_name': suffix, 'display_name': '油猪·测试' + suffix,
                     'description': 'Display-only metadata', 'category': category,
                     'category_label': category, 'layer': 'produce', 'stages': stages_,
                     'tags': [suffix], 'installed': True, 'execution_blocked': blocked,
                     'validation_state': 'source_checked'})
    atomic(home / 'catalog.json', {'schema': 1, 'revision': 'fixed-source-revision',
                                  'sources': [source], 'skills': rows})
    return Library(tmp_path)


def frozen_manifest(library):
    return next((library.root / 'outputs/_sessions/local-skill-inputs').rglob('manifest.json'))


def test_empty_machine_has_no_local_methods_or_io(tmp_path):
    library = Library(tmp_path)
    assert library.rows() == []
    assert library.summary()['skills'] == []
    assert library.verify() == {'revision': '', 'repositories': 0, 'skills': 0}
    assert library.freeze([], 'unused') == ''
    assert not (tmp_path / 'outputs').exists()


def test_listing_reads_summaries_without_source_body_or_hashing(library, monkeypatch):
    original = Path.read_bytes
    def guarded(path):
        assert not path.is_relative_to(library.home / 'packages'), 'listing read full source bytes'
        return original(path)
    monkeypatch.setattr(Path, 'read_bytes', guarded)
    result = library.summary()
    assert len(result['skills']) == 4
    encoded = json.dumps(result, ensure_ascii=False)
    assert 'Exact writing rules' not in encoded
    assert 'UNSELECTED' not in encoded
    assert all(item['display_name'].startswith('油猪·') for item in result['skills'])
    assert all(item['local_skill']['stars'] is None for item in result['skills'])
    assert next(item for item in result['skills'] if item['name'] == 'local-publish')['executionBlocked']


def test_missing_original_is_visible_but_blocked(library):
    row = library.find('local-writer')
    _, package = library.package(row)
    (package / row['entry']).unlink()
    descriptor = next(item for item in library.descriptors() if item['name'] == row['id'])
    assert descriptor['executionBlocked']
    with pytest.raises(ValueError):
        library.selection({'writing': row['id']}, 'fixed-source-revision', 'poster')


@pytest.mark.parametrize('choices,revision,format_', [
    ([], 'fixed-source-revision', 'poster'),
    ('local-writer', 'fixed-source-revision', 'poster'),
    ({'unknown': 'local-writer'}, 'fixed-source-revision', 'poster'),
    ({'writing': 'local-image'}, 'fixed-source-revision', 'poster'),
    ({'writing': 'local-missing'}, 'fixed-source-revision', 'article'),
    ({'writing': 'local-writer'}, 'stale-revision', 'article'),
    ({'layout': 'local-layout'}, 'fixed-source-revision', 'poster'),
    ({'writing': ['local-writer', 'local-writer']}, 'fixed-source-revision', 'article'),
])
def test_selection_rejects_invalid_stage_skill_revision_or_format(library, choices, revision, format_):
    with pytest.raises(ValueError):
        library.selection(choices, revision, format_)
    assert not (library.root / 'outputs').exists()


def test_default_is_no_auxiliary_and_article_can_select_layout(library):
    assert library.selection({}, 'irrelevant', 'poster') == []
    chosen = library.selection({'layout': 'local-layout'}, 'fixed-source-revision', 'article')
    assert chosen[0]['id'] == 'local-layout' and chosen[0]['stage'] == 'layout'


def test_blocked_tool_cannot_execute_as_a_selected_method(library):
    document = json.loads((library.home / 'catalog.json').read_text(encoding='utf-8'))
    document['skills'][0]['execution_blocked'] = '需配置：测试 CLI'
    atomic(library.home / 'catalog.json', document)
    with pytest.raises(ValueError, match='测试 CLI'):
        library.selection({'writing': 'local-writer'}, 'fixed-source-revision', 'article')


def test_freeze_copies_selected_resources_and_preserves_relative_links(library):
    selected = library.selection({'writing': 'local-writer'}, 'fixed-source-revision', 'poster')
    text = library.freeze(selected, 'turn-selected')
    path = frozen_manifest(library)
    saved = json.loads(path.read_text(encoding='utf-8'))
    assert saved['selection'][0]['commit'] == 'a' * 40
    assert set(saved['files']) == {
        'local-writer/methods/writer/SKILL.md',
        'local-writer/methods/writer/references/rules.md',
        'local-writer/methods/shared/style.md',
    }
    assert 'UNSELECTED' not in ''.join(p.read_text(encoding='utf-8') for p in path.parent.rglob('*.md'))
    assert str(path) in text
    assert '油猪·测试writer' in text
    assert '不得自动切换模型' in text
    assert '发布不能继承' in text
    assert len(list(path.parent.parent.iterdir())) == 1


def test_frozen_turn_reuses_original_bytes_after_current_source_changes(library):
    selected = library.selection({'writing': 'local-writer'}, 'fixed-source-revision', 'article')
    first = library.freeze(selected, 'same-turn')
    row = selected[0]
    _, package = library.package(row)
    (package / row['entry']).write_text('NEW UNREVIEWED CURRENT BYTES', encoding='utf-8')
    assert library.freeze(selected, 'same-turn') == first
    assert 'NEW UNREVIEWED' not in (frozen_manifest(library).parent / row['id'] / row['entry']).read_text(encoding='utf-8')
    with pytest.raises(ValueError):
        library.freeze(selected, 'different-turn')


def test_tampered_frozen_resource_is_not_silently_recreated(library):
    selected = library.selection({'writing': 'local-writer'}, 'fixed-source-revision', 'article')
    library.freeze(selected, 'same-turn')
    path = frozen_manifest(library)
    (path.parent / 'local-writer/methods/writer/references/rules.md').write_text('TAMPERED', encoding='utf-8')
    with pytest.raises(ValueError):
        library.freeze(selected, 'same-turn')


@pytest.mark.parametrize('turn_id', ['../../outside', '../..', '/absolute', '.', '..', 'NUL', 'x\\y', 'x:y'])
def test_freeze_rejects_output_traversal_and_windows_reserved_names(library, turn_id):
    selected = library.selection({'writing': 'local-writer'}, 'fixed-source-revision', 'article')
    with pytest.raises(ValueError):
        library.freeze(selected, turn_id)


def test_frozen_manifest_cannot_reference_outside_files(library):
    selected = library.selection({'writing': 'local-writer'}, 'fixed-source-revision', 'article')
    library.freeze(selected, 'same-turn')
    path = frozen_manifest(library)
    outside = library.root / 'outside.txt'
    outside.write_bytes(b'not a frozen resource')
    saved = json.loads(path.read_text(encoding='utf-8'))
    # An absolute name would cause Path / name to discard the protected root.
    saved['files'][str(outside)] = digest(outside.read_bytes())
    atomic(path, saved)
    with pytest.raises(ValueError):
        library.freeze(selected, 'same-turn')
    assert outside.read_bytes() == b'not a frozen resource'


def test_verify_detects_modified_and_removed_source_resources(library):
    assert library.verify() == {'revision': 'fixed-source-revision', 'repositories': 1, 'skills': 4}
    _, package = library.package(library.find('local-writer'))
    (package / 'methods/shared/style.md').write_bytes(b'changed')
    with pytest.raises(ValueError):
        library.verify()
    (package / 'methods/shared/style.md').unlink()
    with pytest.raises(ValueError):
        library.verify()


def test_source_entry_and_parent_links_cannot_escape_package(library, monkeypatch):
    document = json.loads((library.home / 'catalog.json').read_text(encoding='utf-8'))
    document['skills'][0]['entry'] = '../outside/SKILL.md'
    atomic(library.home / 'catalog.json', document)
    with pytest.raises(ValueError):
        library.available(library.find('local-writer'))
    # Windows junctions are checked on every path segment, before resolution.
    original = getattr(Path, 'is_junction', lambda _: False)
    monkeypatch.setattr(Path, 'is_junction', lambda path: path.name == 'packages' or original(path), raising=False)
    with pytest.raises(ValueError):
        library.package(library.find('local-image'))


def test_star_metadata_is_per_repository_and_does_not_change_content_revision(library):
    original = (library.home / 'catalog.json').read_bytes()
    requests = []
    def transport(request):
        requests.append(request)
        return httpx.Response(200, json={'stargazers_count': 12345}, headers={'etag': '"v1"'})
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        stars.refresh(library.root, client=client)
    assert len(requests) == 1  # Four skills share one source repository.
    assert requests[0].url == 'https://api.github.com/repos/author/methods'
    assert (library.home / 'catalog.json').read_bytes() == original
    assert library.verify()['revision'] == 'fixed-source-revision'
    assert {item['local_skill']['stars'] for item in library.descriptors()} == {12345}
    assert all(item['local_skill']['checked_at'] > 0 for item in library.descriptors())


def test_star_refresh_uses_conditional_request_and_retains_304_value(library):
    atomic(library.home / 'stars.json', {'sources': {'author/methods': {'count': 23, 'etag': '"cached"', 'checked_at': 1}}})
    def transport(request):
        assert request.headers['if-none-match'] == '"cached"'
        return httpx.Response(304)
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        stars.refresh(library.root, client=client)
    result = stars.values(library.root)['author/methods']
    assert result['count'] == 23 and result['checked_at'] > 1
    assert result['etag'] == '"cached"'


@pytest.mark.parametrize('status', [403, 429])
def test_star_rate_limit_keeps_prior_value_and_backs_off(library, status):
    atomic(library.home / 'stars.json', {'sources': {'author/methods': {'count': 44, 'checked_at': 1}}})
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(status, headers={'retry-after': '120'}))) as client:
        result = stars.refresh(library.root, client=client)
    assert result['rate_limited'] and not result['complete']
    cache = json.loads((library.home / 'stars.json').read_text(encoding='utf-8'))
    assert cache['sources']['author/methods']['count'] == 44
    assert cache['retry_at'] > cache['checked_at']
    assert stars.schedule(library.root, force=True) is False


@pytest.mark.parametrize('response', [httpx.Response(500), httpx.Response(200, json={'stargazers_count': 'N/A'}), httpx.Response(200, json={'stargazers_count': -1})])
def test_missing_or_invalid_star_count_stays_unknown_instead_of_zero(library, response):
    with httpx.Client(transport=httpx.MockTransport(lambda _: response)) as client:
        stars.refresh(library.root, client=client)
    assert 'author/methods' not in stars.values(library.root)
    assert all(item['local_skill']['stars'] is None for item in library.descriptors())


def test_fresh_star_cache_never_starts_network_thread(library, monkeypatch):
    import time
    atomic(library.home / 'stars.json', {'sources': {}, 'checked_at': time.time()})
    monkeypatch.setattr(stars.threading, 'Thread', lambda **_: pytest.fail('fresh cache started a network thread'))
    assert stars.schedule(library.root) is False


def test_native_host_reuses_the_official_prompt_port_and_exact_local_freeze(library, monkeypatch):
    from easel_workbench.runtime.native_skills import NativeSkills
    calls = []
    native = SimpleNamespace(
        prepare_skill_message=lambda skill, value, persona: calls.append((skill, value, persona)) or 'OFFICIAL:' + value,
        _publishing_message=lambda text: 'POLICY:' + text,
    )
    service = NativeSkills(SimpleNamespace(root=library.root), None)
    monkeypatch.setattr(service, 'context', lambda: native)
    result = service.prepare_message('local-writer', '原始用户输入', 'profile', turn_id='native-turn')
    assert result.startswith('POLICY:OFFICIAL:原始用户输入')
    assert len(calls) == 1 and calls[0][0] == 'local-writer' and calls[0][2] == 'profile'
    assert '本轮明确选定' in calls[0][1]
    assert frozen_manifest(library).is_file()


def test_native_default_has_no_auxiliary_or_new_executor(library, monkeypatch):
    from easel_workbench.runtime.native_skills import NativeSkills
    calls = []
    service = NativeSkills(SimpleNamespace(root=library.root), None)
    monkeypatch.setattr(service, 'context', lambda: SimpleNamespace(
        prepare_skill_message=lambda *args: calls.append(args) or 'original-port',
        _publishing_message=lambda value: value,
    ))
    assert service.prepare_message('oil-pig-poster', '原字', 'profile') == 'original-port'
    assert calls == [('oil-pig-poster', '原字', 'profile')]
    assert not (library.root / 'outputs').exists()
    with pytest.raises(ValueError):
        service.prepare_message('local-publish', 'do not execute', turn_id='rejected')
    assert len(calls) == 1


def test_native_auxiliary_requires_production_skill_and_turn_identity(library, monkeypatch):
    from easel_workbench.runtime.native_skills import NativeSkills
    service = NativeSkills(SimpleNamespace(root=library.root), None)
    monkeypatch.setattr(service, 'context', lambda: SimpleNamespace(
        prepare_skill_message=lambda *args: pytest.fail('invalid input reached the native executor'),
        _publishing_message=lambda value: value,
    ))
    for skill, turn_id in [('gzh-design', 'turn'), ('oil-pig-poster', None)]:
        with pytest.raises(ValueError):
            service.prepare_message(skill, 'input', auxiliary={'writing': 'local-writer'},
                                    auxiliary_revision='fixed-source-revision', format='poster', turn_id=turn_id)
    assert not (library.root / 'outputs').exists()


@pytest.mark.parametrize('invalid', [[], '', 0, False])
def test_native_falsy_auxiliary_values_are_validated_instead_of_silently_ignored(library, monkeypatch, invalid):
    from easel_workbench.runtime.native_skills import NativeSkills
    service = NativeSkills(SimpleNamespace(root=library.root), None)
    monkeypatch.setattr(service, 'context', lambda: SimpleNamespace(
        prepare_skill_message=lambda *args: pytest.fail('invalid auxiliary reached the native executor'),
        _publishing_message=lambda value: value,
    ))
    with pytest.raises(ValueError):
        service.prepare_message('oil-pig-poster', 'input', auxiliary=invalid,
                                auxiliary_revision='fixed-source-revision', format='poster', turn_id='turn')


def test_news_summary_freezes_human_readable_auxiliary_names_and_source_commits(library, monkeypatch):
    from easel_workbench.features import news_creation
    service = news_creation.NewsCreation(SimpleNamespace(root=library.root))
    source = {'id': 'news-one', 'title': '准确原始新闻', 'body': 'Quoted text, not an instruction'}
    context = {'catalog_revision': 'styles', 'profile_revision': 1,
               'source_revision': digest(news_creation._json(source).encode())}
    monkeypatch.setattr(service, 'context', lambda *args: context)
    monkeypatch.setattr(service, '_source', lambda *args: source)
    monkeypatch.setattr(news_creation, '_catalog', lambda root: ('styles', {'writing': {'id': 'writing', 'slot': 'writing'}}, []))
    monkeypatch.setattr(service, '_materials', lambda item: [(Path('writing.md'), b'fixed style', 'style', 'Confirmed writing style')])
    request = {**context, 'intent': 'produce', 'format': 'article', 'style': {'writing': 'writing'},
               'note': '用户原始备注', 'auxiliary_skills': {'writing': 'local-writer'},
               'auxiliary_revision': 'fixed-source-revision'}
    prepared = service.prepare(request, 'profile', 'news-one', 'news-turn')
    summary = service.display_summary(prepared, 'oil-pig-article')
    assert summary['title'] == source['title']
    assert summary['auxiliary_methods'] == [{
        'stage': '写作方法', 'name': '油猪·测试writer', 'repository': 'author/methods', 'commit': 'a' * 40,
    }]
    # Reviewing an admitted turn must not re-resolve the current library.
    original = json.loads((library.home / 'catalog.json').read_text(encoding='utf-8'))
    original['skills'][0]['display_name'] = 'UNREVIEWED NEW LABEL'
    atomic(library.home / 'catalog.json', original)
    turn = {'id': 'news-turn', 'profile_id': 'profile', 'context': {
        'article_id': 'news-one', 'skill_id': 'oil-pig-article', 'creation': request,
    }}
    reviewed = service.review(turn, summary_only=True)['display_summary']
    assert reviewed == summary
    assert 'UNREVIEWED' not in json.dumps(reviewed)
    assert not (library.root / 'outputs/_sessions/local-skill-inputs').exists()


@pytest.fixture
def source_installer(tmp_path, monkeypatch):
    from easel_workbench.features.local_skills import install as installer
    source = tmp_path / 'fake-download'
    source.mkdir()
    files = {
        'LICENSE': 'Fixture license, preserve original attribution.',
        'methods/writer/SKILL.md': '---\nname: fixture-writer\ndescription: Fixture method for testing only\n---\n# Original bytes\n',
        'methods/writer/references/style.md': 'Exact reference material',
        'methods/writer/scripts/do_not_run.py': 'raise RuntimeError("INSTALLER MUST NOT EXECUTE ME")\n',
        '.env': 'TEST_ONLY_SECRET_DO_NOT_COPY',
    }
    for name, text in files.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    calls = []
    def pin(command, **kwargs):
        calls.append(command)
        return 'b' * 40 + '\tHEAD\n'
    helper = SimpleNamespace(_download_repo_zip=lambda *args: str(source))
    monkeypatch.setattr(installer, 'helper', lambda: helper)
    monkeypatch.setattr(installer.subprocess, 'check_output', pin)
    root = tmp_path / 'workspace'
    root.mkdir()
    return installer, root, source, calls


def test_install_pins_complete_source_keeps_license_and_never_executes_scripts(source_installer):
    installer, root, source, calls = source_installer
    result = installer.install(root, repositories=['fixture/methods'], progress=lambda *args, **kwargs: None)
    assert result['repositories'] == 1 and result['skills'] == 1
    assert calls == [['git', 'ls-remote', 'https://github.com/fixture/methods.git', 'HEAD']]
    library = Library(root)
    row = library.rows()[0]
    package, directory = library.package(row)
    assert package['commit'] == 'b' * 40
    assert package['license_paths'] == ['LICENSE']
    assert (directory / 'LICENSE').read_bytes() == (source / 'LICENSE').read_bytes()
    assert (directory / row['entry']).read_bytes() == (source / row['entry']).read_bytes()
    assert (directory / 'methods/writer/scripts/do_not_run.py').read_bytes() == (source / 'methods/writer/scripts/do_not_run.py').read_bytes()
    assert not (directory / '.env').exists()
    assert row['display_name'].startswith('油猪·')
    assert (root / 'skills/builtin' / row['id'] / 'SKILL.md').is_file()
    assert library.verify()['revision'] == result['revision']
    again = installer.install(root, repositories=['fixture/methods'], progress=lambda *args, **kwargs: None)
    assert again == result
    assert Library(root).rows()[0]['id'] == row['id']


def test_failed_source_does_not_activate_partial_catalog_or_replace_existing(source_installer, monkeypatch):
    installer, root, source, calls = source_installer
    installer.install(root, repositories=['fixture/methods'], progress=lambda *args, **kwargs: None)
    before = (root / '.local/third-party-skills/catalog.json').read_bytes()
    def download(owner, repo, *args):
        if repo == 'missing':
            raise OSError('Synthetic unavailable source')
        return str(source)
    monkeypatch.setattr(installer, 'helper', lambda: SimpleNamespace(_download_repo_zip=download))
    with pytest.raises(ValueError):
        installer.install(root, repositories=['fixture/methods', 'fixture/missing'], progress=lambda *args, **kwargs: None)
    assert (root / '.local/third-party-skills/catalog.json').read_bytes() == before
    assert len(Library(root).rows()) == 1
    errors = json.loads((root / '.local/third-party-skills/install-errors.json').read_text(encoding='utf-8'))
    assert errors[0]['repository'] == 'fixture/missing'


def test_install_refuses_unpinned_source_identity(source_installer, monkeypatch):
    installer, root, source, calls = source_installer
    monkeypatch.setattr(installer.subprocess, 'check_output', lambda *args, **kwargs: 'not-a-commit\tHEAD')
    with pytest.raises(ValueError):
        installer.install(root, repositories=['fixture/methods'], progress=lambda *args, **kwargs: None)
    assert not (root / '.local/third-party-skills/catalog.json').exists()
    assert not (root / 'skills/builtin').exists()


@pytest.mark.parametrize('repo,path,meta,category,label,stage', [
    ('fixture/wechat-publisher', 'skills/research/SKILL.md', {}, 'research', '研究', 'research'),
    ('fixture/wechat-publisher', 'skills/formatting/SKILL.md', {}, 'layout', '排版', 'layout'),
    ('fixture/wechat-publisher', 'skills/article-writing/SKILL.md', {}, 'writing', '文章·写作', 'writing'),
    ('aiworkskills/wechat-article-skills', 'skills/aws-wechat-article-images/SKILL.md', {}, 'image', '公众号文章配图', 'illustration'),
    ('isjiamu/gzh-design-skill', 'SKILL.md', {'name': 'gzh-design'}, 'layout', '甲木公众号排版', 'layout'),
    ('op7418/Humanizer-zh', 'SKILL.md', {'name': 'Humanizer-ZH'}, 'polish', '中文去 AI 味', 'polish'),
    ('nashsu/Viral_Writer_Skill', 'SKILL.md', {'name': 'Viral Writer'}, 'writing', '内容洞见写作', 'writing'),
    ('fixture/tools', 'skills/formatting/SKILL.md', {'name': 'Content Research V2'}, 'research', '内容·研究', 'research'),
    ('momozi1996/awesome-ai-persona-skills', 'skills/research/SKILL.md', {'name': 'Research'}, 'voice', '研究', 'writing'),
    ('KKKKhazix/khazix-skills', 'hv-analysis/SKILL.md', {'name': 'hv-analysis'}, 'research', '卡兹克横纵分析', 'research'),
    ('JimLiu/baoyu-skills', 'skills/baoyu-translate/SKILL.md', {'name': 'baoyu-translate'}, 'writing', '宝玉翻译', 'writing'),
    ('SpaceZephyr/creator-buddy', 'gzh-Skills/baokuan-title-generator/SKILL.md', {}, 'title', '公众号标题设计', 'writing'),
    ('social-media-skills/skills', 'skills/before-after-and-transformation/SKILL.md', {}, 'writing', '前后对比与变化叙事', 'writing'),
    ('social-media-skills/skills', 'skills/instagram-growth/SKILL.md', {}, 'planning', 'Instagram 增长策略', 'research'),
    ('social-media-skills/skills', 'skills/canva/SKILL.md', {}, 'image', 'Canva 视觉设计', 'illustration'),
    ('social-media-skills/skills', 'skills/viral-reverse-engineering/SKILL.md', {}, 'research', '热门内容拆解', 'research'),
    ('blacktwist/social-media-skills', 'skills/content-pattern-analyzer-sms/SKILL.md', {}, 'analytics', '高效内容规律分析', None),
])
def test_chinese_taxonomy_uses_selected_skill_identity_not_repository_name(repo, path, meta, category, label, stage):
    from easel_workbench.features.local_skills.taxonomy import classify
    result = classify(repo, path, meta)
    assert result['category'] == category
    assert result['display_name'] == '油猪·' + label
    assert result['stages'] == ([stage] if stage else [])
    assert repo in result['tags']


@pytest.mark.parametrize('name', ['wewrite', 'aws-wechat-article-main', 'creator-buddy', 'space-xhs-buddy', 'release-skills', 'storage-analyzer', 'leader'])
def test_full_workflow_and_project_tools_are_not_offered_as_auxiliary_writing_methods(name):
    from easel_workbench.features.local_skills.taxonomy import classify
    result = classify('fixture/tools', f'skills/{name}/SKILL.md', {'name': name})
    assert result['stages'] == []


@pytest.mark.parametrize('name', ['Article V1', 'article-v2', 'Article_v2.3', '中文写作 V3'])
def test_chinese_display_hides_version_suffix_but_retains_searchable_original_name(name):
    from easel_workbench.features.local_skills.taxonomy import classify
    result = classify('fixture/methods', 'SKILL.md', {'name': name})
    assert not __import__('re').search(r'\b[vV]\d', result['display_name'])
    assert name in result['tags']
    assert result['display_name'].startswith('油猪·')


def temp_git(root, *args):
    """Local-only repository operations with no global settings or hooks."""
    import subprocess
    return subprocess.run([
        'git', '-c', 'core.hooksPath=NUL', '-c', 'core.autocrlf=false',
        '-c', 'commit.gpgsign=false', '-c', 'user.name=Local Skill Test',
        '-c', 'user.email=local-skill-test@example.invalid', '-C', str(root), *args,
    ], check=True, capture_output=True, encoding='utf-8', timeout=30).stdout.strip()


@pytest.fixture
def publication_repo(tmp_path):
    root = tmp_path / 'publication-test'
    root.mkdir()
    temp_git(root, 'init')
    (root / '.gitignore').write_text('.local/\nskills/builtin/local-*/\n', encoding='utf-8')
    (root / 'README.md').write_text('Synthetic own integration source only.\n', encoding='utf-8')
    temp_git(root, 'add', '--', '.gitignore', 'README.md')
    temp_git(root, 'commit', '-m', 'Clean local fixture baseline')
    return root, temp_git(root, 'rev-parse', 'HEAD')


def test_publication_guard_catches_force_added_originals_and_generated_entries(publication_repo):
    from scripts.check_workbench_local_skills import check
    root, _ = publication_repo
    paths = ['.local/third-party-skills/packages/author/source/fixed/SKILL.md',
             'skills/builtin/local-1234567890abcdef/SKILL.md']
    for name in paths:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('TEST THIRD PARTY CONTENT, MUST NEVER BE PUBLISHED', encoding='utf-8')
    assert check(root) == []  # Ignored local content is allowed on disk.
    temp_git(root, 'add', '-f', '--', *paths)
    assert check(root) == sorted(paths)


def test_publication_guard_checks_push_history_even_after_originals_are_removed(publication_repo):
    from scripts.check_workbench_local_skills import check
    root, base = publication_repo
    paths = ['.local/third-party-skills/packages/author/source/fixed/SKILL.md',
             'skills/builtin/local-1234567890abcdef/SKILL.md']
    for name in paths:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('Synthetic forbidden publication bytes', encoding='utf-8')
    temp_git(root, 'add', '-f', '--', *paths)
    temp_git(root, 'commit', '-m', 'Synthetic accidental inclusion')
    temp_git(root, 'rm', '--', *paths)
    temp_git(root, 'commit', '-m', 'Synthetic later deletion')
    head = temp_git(root, 'rev-parse', 'HEAD')
    assert check(root) == []
    assert check(root, base_ref=base, head_ref=head) == sorted(paths)


def test_sparse_git_install_materializes_every_nested_skill_and_preserves_utf8_bytes(tmp_path, monkeypatch):
    from easel_workbench.features.local_skills import install as installer
    source = tmp_path / 'source-origin'
    source.mkdir()
    temp_git(source, 'init')
    originals = {
        'LICENSE': b'Synthetic fixture license, preserve verbatim.\n',
        'SKILL.md': '---\nname: root-workflow\ndescription: 根级入口\n---\n# 原始总入口\n'.encode(),
        'skills/writer/SKILL.md': '---\nname: nested-writer\ndescription: 中文写作方法\n---\n# 完整嵌套技能\n'.encode(),
        'skills/writer/references/中文规范.md': '中文原字、LF 换行\n第二行\n'.encode(),
        'skills/writer/assets/reference.bin': b'\x00\xff\x01\r\n\x80',
        'skills/writer/scripts/do_not_execute.py': b'raise RuntimeError("do not execute source scripts")\n',
    }
    for name, raw in originals.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    temp_git(source, 'add', '--', *originals)
    temp_git(source, 'commit', '-m', 'Complete nested UTF8 source')
    commit = temp_git(source, 'rev-parse', 'HEAD')
    clone = tmp_path / 'sparse-clone'
    temp_git(tmp_path, 'clone', '--no-checkout', '--', str(source), str(clone))
    temp_git(clone, 'sparse-checkout', 'init', '--cone')
    temp_git(clone, 'sparse-checkout', 'set', '.')
    temp_git(clone, 'checkout', '--detach', commit)
    assert (clone / 'SKILL.md').is_file()
    assert not (clone / 'skills/writer/SKILL.md').exists(), 'fixture must begin as the root-only sparse helper output'
    calls = []
    def sparse_checkout(url, revision, paths, temporary):
        calls.append((url, revision, paths))
        return str(clone)
    helper = SimpleNamespace(
        _git_sparse_checkout=sparse_checkout,
        _run_git=lambda command: pytest.fail('installer did not provide its bounded, hook-free git runner'),
        InstallError=RuntimeError,
    )
    monkeypatch.setattr(installer, 'helper', lambda: helper)
    original_check_output = installer.subprocess.check_output
    def pinned_remote(command, *args, **kwargs):
        if command[:2] == ['git', 'ls-remote']:
            return commit + '\tHEAD\n'
        return original_check_output(command, *args, **kwargs)
    monkeypatch.setattr(installer.subprocess, 'check_output', pinned_remote)
    root = tmp_path / 'workspace'
    root.mkdir()
    result = installer.install(root, repositories=['fixture/nested-methods'], workers=1,
                               progress=lambda *args, **kwargs: None)
    assert calls == [('https://github.com/fixture/nested-methods.git', commit, ['.'])]
    assert result['repositories'] == 1 and result['skills'] == 2
    library = Library(root)
    document = library.document()
    assert {row['entry'] for row in document['skills']} == {'SKILL.md', 'skills/writer/SKILL.md'}
    _, directory = library.package(document['skills'][0])
    assert not (directory / '.git').exists()
    for name, raw in originals.items():
        assert (directory / name).read_bytes() == raw, name
    assert library.verify()['skills'] == 2


def test_default_install_rebuilds_configured_commit_without_following_remote_head(source_installer):
    installer, root, source, calls = source_installer
    config=root/'config/local-skill-sources.json'
    config.parent.mkdir()
    atomic(config, {'repositories':['fixture/methods'],'commits':{'fixture/methods':'b'*40}})
    result=installer.install(root,progress=lambda *args, **kwargs: None)
    assert calls == []
    assert result['skills'] == 1
    assert Library(root).rows()[0]['commit'] == 'b'*40
