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
