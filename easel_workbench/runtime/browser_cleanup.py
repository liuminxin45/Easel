"""Terminal-decision browser lifecycle; cleanup receipts never replay decisions."""
import json,pathlib,re
from easel_workbench.runtime.desk import THREAD,stamp
RECEIPT=re.compile(r'<!-- TOOLBOX_BROWSER_CLEANUP (\{[^\r\n]*\}) -->')


def public_reply(reply):
    return RECEIPT.sub('',reply).strip() if isinstance(reply,str) else reply


def initialize(c):
    c.execute('CREATE TABLE IF NOT EXISTS toolbox_browser_cleanup(job_id TEXT PRIMARY KEY,status TEXT NOT NULL,result TEXT,updated_at TEXT NOT NULL)')


def require(c,jid):
    c.execute('INSERT INTO toolbox_browser_cleanup VALUES(?,?,?,?)',(jid,'pending',None,stamp()))


def instructions(job):
    if job['kind'] not in ('accept','reject'):return ''
    module=(pathlib.Path(__file__).resolve().parent/'scripts/close_production_browser.mjs').as_uri()
    return ('\n结束后的必做收尾（本次采纳/不采纳均适用）：先完成相应版本记录、必要归档与素材/截图/录屏保存，再关闭当前固定制作会话的所有内置浏览器页面，包括此前标记为交付或接续的页面。采纳只认可指定范围；关闭页面不删除作品、附件或源文件。\n'
        '使用可用的 mcp__cua_repl.js 浏览器工具；若尚未初始化，该工具首次调用必须仅执行 await cua.getState(); 并阅读返回文档。随后运行以下已提供的收尾模块，模块只选择本制作会话的 iab，逐个关闭并重新列举核对，不操作其他会话、Chrome/Edge 或整个浏览器进程：\n'
        'var cleanupModule = await import('+json.dumps(module)+');\n'
        'var cleanupReport = await cleanupModule.closeProductionBrowser(cua,'+json.dumps(THREAD)+','+json.dumps(job['id'])+');\n'
        'nodeRepl.write(cleanupModule.cleanupReceipt(cleanupReport));\n'
        '最终回执自然说明实际关闭结果，并原样附上工具返回的 TOOLBOX_BROWSER_CLEANUP HTML 注释，供工具箱核对。只有实际核对 remaining_count 为 0 才能说已全部关闭；原本没有页面也按 already_empty 回执。工具缺失、会话不符或清理失败时如实报告，禁止伪造回执、扩大清理范围或重复采纳/归档。未明确采纳或不采纳之前，讨论、制作、修改、普通反馈都不执行这项收尾。\n')


def record(store,jid,reply):
    with store.connect() as c:
        if not c.execute('SELECT 1 FROM toolbox_browser_cleanup WHERE job_id=?',(jid,)).fetchone():return None
        receipt=None
        for match in RECEIPT.finditer(reply):
            try:
                item=json.loads(match[1])
                if item.get('operation_id')==jid and item.get('thread_id')==THREAD:receipt=item
            except (ValueError,AttributeError):continue
        valid=receipt is not None and receipt.get('status') in ('closed','already_empty') and type(receipt.get('remaining_count')) is int and receipt['remaining_count']==0 and type(receipt.get('closed_count')) is int and receipt['closed_count']>=0 and type(receipt.get('browser_count')) is int and receipt['browser_count']>0
        status='completed' if valid else 'incomplete' if receipt else 'unconfirmed'
        c.execute('UPDATE toolbox_browser_cleanup SET status=?,result=?,updated_at=? WHERE job_id=?',(status,json.dumps(receipt,ensure_ascii=False) if receipt else None,stamp(),jid))
    if not valid:return '采纳或不采纳的回执已记录；内置浏览器清理尚未确认，请在 Codex 制作会话核对。不会自动重复采纳、归档或制作。'
    return None
