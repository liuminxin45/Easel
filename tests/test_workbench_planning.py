"""Shared planning handlers preserve optional source identities in TEMP files."""
import asyncio
import json

import pytest

from easel.web_services.planning import create_planning_context


def test_optional_idea_binding_round_trip_and_legacy_edits(tmp_path):
    planning = create_planning_context(tmp_path)
    created = asyncio.run(planning.api_ideas_create(planning.IdeaItem(
        title=' Exact source ', source='Source label', source_id='source-one', note='Original note')))
    assert created['source_id'] == 'source-one'
    for fields in ({'title': 'Edited'}, {'title': 'Edited again', 'source_id': None}):
        edited = asyncio.run(planning.api_ideas_update(created['id'], planning.IdeaItem(**fields)))
        assert edited['source_id'] == 'source-one'
    restored = create_planning_context(tmp_path)
    assert asyncio.run(restored.api_ideas_list())[0]['source_id'] == 'source-one'
    assert json.loads((tmp_path / 'outputs/_ideas.json').read_text(encoding='utf-8'))[0] == edited


@pytest.mark.parametrize('binding', [{}, {'source_id': None}])
def test_manual_ideas_keep_original_storage_shape(tmp_path, binding):
    planning = create_planning_context(tmp_path)
    created = asyncio.run(planning.api_ideas_create(planning.IdeaItem(title='Manual', **binding)))
    assert 'source_id' not in created
    updated = asyncio.run(planning.api_ideas_update(created['id'], planning.IdeaItem(title='Manual edit')))
    assert 'source_id' not in updated


def test_shared_planning_treats_source_id_as_opaque_host_metadata(tmp_path):
    planning = create_planning_context(tmp_path)
    created = asyncio.run(planning.api_ideas_create(planning.IdeaItem(title='Original', source_id='opaque-one')))
    updated = asyncio.run(planning.api_ideas_update(created['id'], planning.IdeaItem(title='Edited', source_id='opaque-two')))
    assert updated['source_id'] == 'opaque-two'
