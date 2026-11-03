"""Persisted native work/version completion reads survive retired orchestration."""
import importlib.util
import json
from pathlib import Path
import pytest
from easel_workbench.features.works.products import ChatProducts
from easel_workbench.runtime.completion_service import CompletionService

spec=importlib.util.spec_from_file_location('historical_completion_fixture',Path(__file__).with_name('test_workbench_version_view.py'))
fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
runtime,commands=fixtures.runtime,fixtures.commands


def saved(box):
    with box.store.connect() as c:
        return {name:[tuple(r) for r in c.execute('SELECT * FROM '+name+' ORDER BY rowid')] for name in ('toolbox_jobs','toolbox_review_inputs','toolbox_completions','artifacts')}


def test_historical_native_products_retain_exact_version_decision_without_new_execution(commands):
    box=commands;wid=fixtures.seed(box)
    with box.store.connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS easel_chat_turns(id TEXT PRIMARY KEY,session_id TEXT,operation_id TEXT UNIQUE,signature TEXT,document TEXT)')
        turn={'id':'version-1','session_id':'historical-session','status':'completed','snapshot':{'task':'poster'},'work':{'work_id':wid,'version_id':'version-1'}}
        c.execute('INSERT INTO easel_chat_turns VALUES(?,?,?,?,?)',('version-1','historical-session','historical-operation','signature',json.dumps(turn)))
    completion=CompletionService(box)
    before=saved(box)
    product=ChatProducts(root=box.root,store=box.store,work_store=box).describe('version-1')
    assert product['work_id']==wid and product['version_id']=='version-1'
    assert product['text_blocks']==[{'label':'标题','text':'Title 1'},{'label':'正文','text':'Body 1'}]
    assert product['decision']['text']=='original user decision'
    assert product['incomplete'] is False and len(product['files'])==1
    assert saved(box)==before


def test_historical_completion_options_read_original_version_and_cannot_forge_a_foreign_version(commands):
    box=commands;wid=fixtures.seed(box);service=CompletionService(box);before=saved(box)
    value=service.options(wid,'version-1')
    assert value['work_id']==wid and value['version_id']=='version-1'
    assert saved(box)==before
    with pytest.raises(ValueError):service.options(wid,'foreign-version')
    assert saved(box)==before
