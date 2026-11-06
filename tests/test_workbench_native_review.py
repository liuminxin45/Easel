import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest

spec=importlib.util.spec_from_file_location('native_review_fixture',Path(__file__).with_name('test_workbench_skill_commands.py'))
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
runtime,commands=fixture.runtime,fixture.commands
from easel_workbench.features.works.native_review import binding,instructions,receive

def test_completed_native_skill_registers_exact_files_once(commands):
    box=commands;business=SimpleNamespace(root=box.root,store=box.store,box=box,_session=lambda value:{'profile_id':'oil-pig'})
    frame=binding(business,{'turnId':'review-turn','sessionId':'review-session','context':{'skill_id':'oil-pig-poster'}})
    directory=Path(frame['product_directory']);directory.mkdir(parents=True)
    path=directory/'标题与配文.txt';path.write_text('准确标题\n准确配文',encoding='utf8')
    turn={'id':'review-turn','session_id':'review-session','status':'completed','message':'制作贴图','actual_prompt_sha256':'a'*64,
          'native_turn_id':'exact-native-turn','created_at':'2026-11-06','output':'[配文]('+path.as_posix()+')','frozen_instructions':instructions(frame)}
    receipt=receive(business,turn);assert receipt['version_id']=='review-turn'
    receive(business,turn)
    with box.store.connect() as c:
        assert c.execute('SELECT count(*) FROM toolbox_jobs WHERE id=?',('review-turn',)).fetchone()[0]==1
        assert c.execute('SELECT count(*) FROM artifacts WHERE task_id=?',('review-turn',)).fetchone()[0]==1
    assert receive(business,{**turn,'status':'unknown'}) is None
    path.write_text('源文件随后改变，但准确已接收原件不覆盖',encoding='utf8')
    assert receive(business,turn)==receipt

def test_learning_and_plain_chat_never_create_review_binding(commands):
    business=SimpleNamespace(root=commands.root)
    for skill in ('oil-pig-learn-poster','oil-pig-learn-article',None):
        assert binding(business,{'turnId':'test-turn','sessionId':'test-session','context':{'skill_id':skill}}) is None

def test_discussion_or_quoted_source_never_becomes_a_decision(commands):
    from easel_workbench.features.works.native_review import decision,modifying
    business=SimpleNamespace(root=commands.root,store=commands.store)
    for message in ('不采纳会怎么样','如果采纳这版会发布吗','新闻里说“采纳这版”','不要采纳这版','采纳这版？'):
        assert decision(business,{'sessionId':'none','message':message}) is None
    assert not modifying('再改会怎么样？')
    assert not modifying('修改上一版，缩短正文')
