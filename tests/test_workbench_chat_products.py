import asyncio
import importlib.util
import json
from pathlib import Path

import pytest
from easel import harnesses
from easel.harnesses.base import HarnessError
from easel_workbench.chat_products import ChatProducts

spec=importlib.util.spec_from_file_location('product_fixtures',Path(__file__).with_name('test_workbench_chat_business.py'))
fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
business=fixtures.business


@pytest.mark.parametrize('interrupted',[False,True])
def test_registered_and_interrupted_products_are_read_only_and_exact(business,monkeypatch,interrupted):
    async def scenario():
        b=business
        class Adapter:
            async def run(self,request,emit,ask,bind):
                bind('product-native');request.on_native_turn('product-native','product-turn')
                data=json.JSONDecoder().raw_decode(request.prompt.split('## 本轮冻结输入\n')[-1])[0]
                folder=Path(data['output_directory']);folder.mkdir(parents=True,exist_ok=True)
                image=folder/'成品.png';image.write_bytes(b'\x89PNG\r\n\x1a\n'+b'\x00\x00\x00\rIHDR'+(1).to_bytes(4,'big')*2+b'\x08\x02\x00\x00\x00')
                copy=folder/'标题与配文.txt';copy.write_text('精确标题\n\n  原字正文\n第二段  ',encoding='utf-8')
                if interrupted:raise HarnessError('TEMP unknown receipt')
                emit('token',json.dumps({'deliverables':[str(image),str(copy)],'production_result':{'schema_version':1,'status':'completed'}},ensure_ascii=False))
        monkeypatch.setattr(harnesses,'adapter',lambda _:Adapter())
        value,_=fixtures.confirmed(b);turn=await b.chat.submit(value,**b.prepare(value));await b.chat._tasks[turn['id']]
        def saved():
            with b.store.connect() as c:return {name:c.execute('SELECT * FROM '+name).fetchall() for name in ('easel_chat_turns','artifacts','creator_skill_versions','toolbox_jobs')}
        before=saved();view=ChatProducts(b).describe(turn['id']);assert saved()==before
        assert [block['label'] for block in view['text_blocks']]==['标题','正文']
        assert view['text_blocks'][0]['text']=='精确标题'
        assert bool(view['incomplete'])==interrupted
        assert view['can_adopt'] is not interrupted
        image=next(file for file in view['files'] if file['mime']=='image/png')
        if interrupted:
            assert image['partial'] and b.chat.get_turn(turn['id'])['status']=='unknown'
            info,path=ChatProducts(b).file(turn['id'],image['id']);assert path.read_bytes().startswith(b'\x89PNG')
            path.write_bytes(b'changed')
            with pytest.raises(ValueError):ChatProducts(b).file(turn['id'],image['id'])
            with pytest.raises(ValueError):ChatProducts(b).file('other-turn',image['id'])
        assert saved()==before
        await b.chat.close()
    asyncio.run(scenario())


def test_partial_scan_rejects_outside_links_and_private_names(business):
    b=business;folder=b.root/'outputs/test-chat/owned/products';folder.mkdir(parents=True)
    (folder/'credentials.json').write_text('{}');(folder/'.env').write_text('secret');(folder/'safe.txt').write_text('safe')
    products=ChatProducts(b);files=products._partial({'id':'owned','session_id':'test-chat'})
    assert [file['name'] for file in files]==['safe.txt']
    outside=b.root/'outside.txt';outside.write_text('outside')
    try:(folder/'escape.txt').symlink_to(outside)
    except OSError:pass
    assert [file['name'] for file in products._partial({'id':'owned','session_id':'test-chat'})]==['safe.txt']
