"""The official skill parser and invocation preserve the private skills' contracts."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
IDS = ('oil-pig-poster', 'oil-pig-article', 'topic-research', 'content-writing',
       'image-production', 'delivery-review', 'reference-analysis', 'publication-analysis')


@pytest.mark.parametrize('skill', IDS)
def test_official_skill_parser_exposes_conventions_and_persona_in_native_request(skill):
    from easel.web_services.skills import create_skills_context
    context = create_skills_context(ROOT, environment=lambda: {}, execute=lambda *_: None,
        persona=lambda name: f'当前画像：{name}\n', direct_api=lambda: False)
    row = next(item for item in context.get_skills() if item['name'] == skill)
    description, layer, body = context._parse_skill_md(ROOT/'skills/builtin'/skill/'SKILL.md')
    assert row['description'] == description and row['layer'] == layer and description
    assert description.startswith('油猪·')
    for section in ('适用场景与边界', '当前画像', '输入', '执行流程', '输出与核验'):
        assert f'## {section}' in body
    message = context.prepare_skill_message(skill, '原始材料\n保留', '实际画像')
    assert '实际画像' in message and f'/{skill}' in message and '原始材料\n保留' in message
