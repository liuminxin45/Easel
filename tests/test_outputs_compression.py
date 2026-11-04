"""Large output catalog must preserve JSON while negotiating small transfers."""
from unittest.mock import patch
from fastapi.testclient import TestClient
from web import app as web


def test_output_tree_gzip_keeps_all_projects_and_unicode():
    tree=[{'name': '迁入项目'+str(i), 'type':'dir','children':[],
           'meta':{'title':'完整保留标题与原件'*30}} for i in range(193)]
    with patch.object(web,'get_output_tree',return_value=tree):
        with TestClient(web.app,base_url='http://localhost:7860') as client:
            plain=client.get('/api/outputs',headers={'accept-encoding':'identity'})
            compressed=client.get('/api/outputs',headers={'accept-encoding':'gzip'})
    assert plain.status_code==compressed.status_code==200
    assert plain.json()==compressed.json()==tree
    assert compressed.headers['content-encoding']=='gzip'
    assert int(compressed.headers['content-length'])<len(plain.content)//5
    assert 'Accept-Encoding' in compressed.headers['vary']


def test_sse_is_excluded_from_compression():
    from starlette.middleware.gzip import DEFAULT_EXCLUDED_CONTENT_TYPES
    assert 'text/event-stream' in DEFAULT_EXCLUDED_CONTENT_TYPES


def test_shared_delete_keeps_the_standalone_filesystem_behavior_and_system_guard(tmp_path):
    import asyncio
    import pytest
    from fastapi import HTTPException
    from easel.web_services.outputs import create_outputs_context
    source=tmp_path/'outputs/project/original.txt';source.parent.mkdir(parents=True);source.write_text('original')
    context=create_outputs_context(tmp_path)
    result=asyncio.run(context.api_output_delete('project/original.txt'))
    assert result=={'ok':True,'deleted':'project/original.txt','kind':'file'} and not source.exists()
    protected=tmp_path/'outputs/_sessions/private.txt';protected.parent.mkdir();protected.write_text('private')
    with pytest.raises(HTTPException) as error:asyncio.run(context.api_output_delete('_sessions/private.txt'))
    assert error.value.status_code==403 and protected.read_text()=='private'
