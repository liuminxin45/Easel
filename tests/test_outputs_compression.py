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
