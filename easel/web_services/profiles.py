"""Deterministic official onboarding baseline, shared by both storage hosts.

The six-document builder is extracted from web/app.py without changing its text.
The ordinary host writes files; authenticated hosts retain versioned documents.
"""
from __future__ import annotations
import asyncio
import inspect
import shutil
from pathlib import Path
from fastapi import HTTPException
from easel.persona import valid_persona_name


async def delete_profile(name, root=None, *, resolve=None, remove=None):
    """The native delete action with an optional historical storage adapter."""
    if not valid_persona_name(name):raise HTTPException(400,'画像名非法')
    def filesystem():
        base=Path(root).resolve();target=(base/name).resolve()
        if base not in target.parents or not target.is_dir():raise HTTPException(404,'画像不存在')
        return target
    target=await asyncio.to_thread(resolve,name) if resolve else await asyncio.to_thread(filesystem)
    result=await asyncio.to_thread(remove or shutil.rmtree,target)
    if inspect.isawaitable(result):await result
    return {'ok':True,'deleted':name}

def baseline_profile_files(name: str, form: dict) -> dict:
    """从表单确定性生成六维基线文件。链接派生字段标 [待 AI 分析]。"""
    files = {}

    def g(k: str, default: str='') -> str:
        v = form.get(k)
        if isinstance(v, list):
            return '、'.join((str(x) for x in v))
        return str(v).strip() if v not in (None, '') else default
    direction = g('direction') or '[待补充]'
    reason = g('reason') or '[待补充]'
    goal = g('goal')
    formats = g('formats')
    tone = g('tone') or '[待分析]'
    likes = g('likes')
    avoid = g('avoid')
    platforms = form.get('platforms') or []
    links = form.get('links') or {}
    files['identity.md'] = f"# 身份定位\n\n## 我是谁\n\n{direction}\n\n## 差异化\n\n{reason}\n\n## 内容方向\n\n{direction}{('（形式：' + formats + '）' if formats else '')}\n{('运营目标：' + goal if goal else '')}\n"
    files['style.md'] = f"# 内容风格\n\n## 语气\n\n{tone}\n\n## 开头结构\n\n[待 AI 分析已发内容]\n\n## 视觉风格\n\n[待 AI 分析]\n\n## 内容节奏\n\n{formats or '[待补充]'}\n\n## 标志性元素\n\n[待 AI 分析]\n"
    files['audience.md'] = '# 目标受众\n\n## 核心人群\n\n[待 AI 分析/待补充]\n\n## 兴趣标签\n\n[待补充]\n\n## 痛点\n\n[待补充]\n\n## 互动特征\n\n[待 AI 分析已发内容]\n'
    plat_lines = []
    for p in platforms:
        url = links.get(p, '')
        plat_lines.append(f"## {p}\n\n主页：{url or '[待补充]'}\n粉丝量级 / 内容形式：[待补充]\n")
    files['platforms.md'] = '# 平台运营\n\n' + ('\n'.join(plat_lines) if plat_lines else '[待补充]\n')
    files['preferences.md'] = f"# 偏好与红线\n\n## 要做的\n\n{direction}\n\n## 不做的\n\n{avoid or '[待补充]'}\n\n## 合规底线\n\n{avoid or '[待补充]'}\n"
    files['memory.md'] = f"# 经验沉淀\n\n## 内容洞察\n\n{('喜欢的内容/对标：' + likes if likes else '[待 AI 分析已收藏/点赞]')}\n\n## 踩过的坑\n\n[待积累]\n"
    return files


def form_to_instruction(name: str, form: dict) -> str:
    def g(k: str, default: str = '（未填）') -> str:
        v = form.get(k)
        if isinstance(v, list):
            return '、'.join(str(x) for x in v) if v else default
        return str(v).strip() if v not in (None, '') else default
    links = form.get('links') or {}
    links_txt = '\n'.join(f'  - {p}: {u}' for p, u in links.items() if u) or '  （未提供）'
    return (f"画像名：{name}\n运营平台：{g('platforms')}\n起号状态：{g('accountStage')}"
            f"\n社媒主页链接：\n{links_txt}\n想做的方向：{g('direction')}"
            f"\n为什么做/我的优势：{g('reason')}\n运营目标：{g('goal')}"
            f"\n想产出的形式：{g('formats')}\n喜欢看的内容/对标账号：{g('likes')}"
            f"\n期望调性：{g('tone')}\n不做的内容/红线：{g('avoid')}\n")



def profile_enhancement_message(name, form):
    instruction = form_to_instruction(name, form)
    return (f"请执行 /skill-profile-builder 完善已存在的画像「{name}」。用户已通过表单提供以下信息，我已按此写好 profiles/{name}"
            f"/ 的基线六维文件。请：①尽力抓取用户给的社媒链接分析已发内容/风格/受众（抓不到就降级，标注[待补充]，勿臆造）②据分析结果润色/补全各维度文件 ③给出一句话完成度摘要。表单信息如下：\n\n{instruction}")


def start_profile_enhancement(name, form, *, execute, write_status, apply=None, message_suffix='', background=None):
    """Original background lifecycle; storage hosts supply execution and revision-safe apply."""
    import threading
    from easel.timeouts import TIMEOUT_PRODUCE
    message = profile_enhancement_message(name, form) + message_suffix
    write_status(name, 'running', 'AI 正在分析并增强画像…')
    def enhance():
        try:
            log = execute(message, TIMEOUT_PRODUCE)
            if apply is not None: apply(log)
            write_status(name, 'done', log)
        except Exception as error:
            write_status(name, 'failed', f'AI 增强失败（基线画像已可用）：{error}')
    if background is not None: background(enhance)
    else: threading.Thread(target=enhance, daemon=True).start()
