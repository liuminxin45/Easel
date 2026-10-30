"""TEMP board records do not dispatch production or rewrite work versions."""
import json
import pytest
from easel_workbench.runtime.desk import Store
from easel_workbench.runtime.toolbox_store import Toolbox
from easel_workbench.runtime.easel_frontend import EaselFrontend,FrontendConflict
from easel_workbench.runtime.article_drafts import save


@pytest.fixture
def board(tmp_path):
    return EaselFrontend(Toolbox(Store(tmp_path/'desk.sqlite'),tmp_path))


def test_topic_save_advance_delete_have_exact_receipts_and_history(board):
    value={'id':'new-topic','action':'topic-save','base_revision':0,'title':'TEMP 选题','note':'原始备注','source':'手动','status':'pending'}
    result=board.command(value);topic=result['result']['topic']
    assert board.command(value)==result
    assert board.topics()['items']==[topic]
    with pytest.raises(FrontendConflict):board.command({**value,'title':'改变同一请求'})
    with pytest.raises(FrontendConflict):board.command({**value,'id':'stale','topic_id':topic['id']})
    updated={**value,'id':'advance','topic_id':topic['id'],'base_revision':1,'status':'doing'}
    assert board.command(updated)['result']['topic']['status']=='doing'
    board.command({**updated,'id':'remove','action':'topic-delete','base_revision':2})
    assert board.topics()['items']==[]
    with board.store.connect() as connection:
        assert connection.execute('SELECT count(*) FROM toolbox_jobs').fetchone()[0]==0
        history=[json.loads(row[0]) for row in connection.execute('SELECT document FROM easel_topic_history ORDER BY revision')]
        assert [row['revision'] for row in history]==[1,2,3]
        assert all(row['note']=='原始备注' for row in history)


def test_existing_drafts_remain_on_board_and_deletion_preserves_work(board):
    save(board.box,{'id':'legacy-draft','revision':0,'title':'原选题','material':'原始素材','files':[],'format':'poster'})
    before=board.box.work('legacy-draft')
    assert board.topics()['items'][0]['work_id']=='legacy-draft'
    board.command({'id':'edit-legacy','action':'topic-save','topic_id':'legacy-draft','base_revision':0,'title':'看板标题','note':'意见','status':'done'})
    assert board.topics()['items'][0]['status']=='done'
    assert board.box.work('legacy-draft')==before
    board.command({'id':'delete-legacy','action':'topic-delete','topic_id':'legacy-draft','base_revision':1,'title':'看板标题','status':'done'})
    assert board.topics()['items']==[]
    assert board.box.work('legacy-draft')==before
