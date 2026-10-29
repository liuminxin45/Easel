"""Topic collection through the existing read-only fixed-thread discussion queue."""
import hashlib
from easel_workbench.runtime.article_drafts import save
from easel_workbench.runtime.toolbox_store import ident, text
from easel_workbench.runtime.work_discussions import enqueue


def collect(box, value):
    operation = ident(value.get('id'))
    # Both stages have deterministic IDs and durable receipts. A lost response
    # resumes the original save/discussion; it cannot schedule a second search.
    draft = save(box, {**value, 'revision': 0, 'format': value.get('format', 'poster')})
    job_id = 'topic-' + hashlib.sha256(operation.encode()).hexdigest()
    question = ('请围绕已保存的主题与素材，进行只读资料采集与核查。'
                '优先找直接来源，逐条保留标题、可打开的原始链接、日期和来源类型，'
                '区分已确认事实、他人观点与待核实信息，指出材料缺口。'
                '最后给出可继续制作的内容方向和选材理由。'
                '本次只收集与讨论，不制作成品、不修改规范、不采纳或发布。')
    result = enqueue(box, draft['work_id'], {
        'id': job_id, 'revision': draft['revision'], 'candidate_id': None,
        'text': question, 'files': [], 'creative': value.get('creative'),
    })
    return {**result, 'research': True}
