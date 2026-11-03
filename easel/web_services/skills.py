"""Official skill metadata and dependency rules shared by both Easel hosts.

The implementations below were moved verbatim from web/app.py. Hosts add only
storage/version information; API requirements and masked status have one source.
"""
from __future__ import annotations
import importlib.util
from pathlib import Path
from functools import lru_cache
import asyncio
import uuid
from easel.direct_api import read_settings, history_path
from easel.manual_publish import publishing_mode
from easel.persona import chat_turn_message
from fastapi import HTTPException
from easel.timeouts import TIMEOUT_PRODUCE, TIMEOUT_CHAT
from .settings import _k, _is_set
from .binding import bind_functions

@lru_cache(maxsize=1)
def _model_registry():
    path=Path(__file__).resolve().parents[2]/'skills/shared/scripts/model_registry.py'
    spec=importlib.util.spec_from_file_location('easel_shared_skill_registry',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def model_group(group):
    return _model_registry().model_group(group)


def _model_spec(group: str, label: str | None = None) -> dict:
    spec = model_group(group)
    return {
        "label": label or spec["label"],
        "settings": spec.get("settings", []),
        "providers": spec["providers"],
    }


def _short_drama_spec() -> dict:
    """Image is required; video and cloud voice settings remain optional enhancements."""
    image = model_group("image")
    optional = []
    for group_name in ("video", "voice"):
        group = model_group(group_name)
        optional.extend({**key, "required": False} for key in group.get("settings", []))
        for provider in group["providers"]:
            optional.extend({**key, "required": False} for key in provider["keys"])
    seen = set()
    optional = [key for key in optional if not (key["env"] in seen or seen.add(key["env"]))]
    return {
        "label": "AI 短剧（生图必需 + 生视频/云配音可选）",
        "settings": [],
        "providers": [{
            "id": "drama",
            "name": "关键帧生图（必需）+ 视频生成与闭源配音（可选）",
            "keys": [*image["providers"][0]["keys"], *optional],
        }],
    }


SKILL_API_REQUIREMENTS: dict[str, dict] = {
    "ai-image-gen": _model_spec("image"),
    "ecom-details-image": _model_spec("image", "电商配图（AI 生图）"),
    "ai-video-gen": _model_spec("video"),
    "ai-music": _model_spec("music"),
    "voice-clone": _model_spec("voice", "声音克隆 / 云端 TTS"),
    # AI 短剧：编排 ai-image-gen(关键帧,必需) + ai-video-gen(生视频,可选,缺则退化图片短剧)。
    # 以生图为「已配置」基线（缺生图无法出关键帧）；生视频 key 同框可选填，也可在 ai-video-gen 卡片配。
    "short-drama": _short_drama_spec(),
    # 论文解读：MinerU 与生图均为可选（缺 MinerU 用 pdfplumber 兜底、缺生图用信息图/图表）。
    # 全 key 可选 → 不误报感叹号；但仍进注册表以便就地填 MINERU_API_TOKEN（无其它叶子 skill 承载它）。
    "paper-explainer": {
        "label": "论文解读（MinerU / 生图 均可选）",
        "providers": [
            {
                "id": "paper",
                "name": "MinerU 解析(可选, 缺则 pdfplumber) + 封面/概念生图(可选)",
                "keys": [
                    _k("MINERU_API_TOKEN", "MinerU API Token（可选，缺则用 pdfplumber 兜底）",
                       required=False),
                    _k("IMG_API_KEY", "生图 API Key（可选，用于封面/概念图）", required=False,
                       aliases=["OPENAI_API_KEY", "API_KEY"]),
                    _k("IMG_BASE_URL", "生图 API 根地址（可选）", required=False, secret=False,
                       aliases=["OPENAI_BASE_URL", "OPENAI_API_BASE", "BASE_URL"]),
                ],
            },
        ],
    },
}

_ENV_ALLOWLIST: set[str] = {
    "EASEL_DIRECT_API_BASE_URL", "EASEL_DIRECT_API_KEY", "EASEL_DIRECT_API_MODEL",
}
for _spec in SKILL_API_REQUIREMENTS.values():
    for _key in _spec.get("settings", []):
        _ENV_ALLOWLIST.add(_key["env"])
        _ENV_ALLOWLIST.update(_key.get("aliases", []))
    for _prov in _spec["providers"]:
        for _key in _prov["keys"]:
            _ENV_ALLOWLIST.add(_key["env"])
            _ENV_ALLOWLIST.update(_key.get("aliases", []))


def _parse_skill_md(path: Path) -> tuple[str, str, str]:
    return parse_skill_text(path.read_text(encoding='utf-8'))


def parse_skill_text(text: str) -> tuple[str, str, str]:
    """解析 SKILL.md → (description, layer, body)。body 为去掉 frontmatter 的正文。
    正确处理 YAML 块标量 description（`>-` / `>` / `|` 后跟缩进多行）。"""
    desc, layer, body = '', '', text
    lines = text.splitlines()
    if not (lines and lines[0].strip() == '---'):
        return desc, layer, body
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == '---':
            end = i
            break
    if end is None:
        return desc, layer, body
    body = '\n'.join(lines[end + 1:]).strip()
    fm = lines[1:end]
    i = 0
    while i < len(fm):
        st = fm[i].strip()
        if st.startswith('layer:'):
            layer = st.split(':', 1)[1].strip().strip('"').strip("'")
            i += 1
        elif st.startswith('description:'):
            val = st.split(':', 1)[1].strip()
            if val and val[0] in '|>':
                block = []
                j = i + 1
                while j < len(fm):
                    if fm[j].strip() == '':
                        block.append('')
                        j += 1
                        continue
                    indent = len(fm[j]) - len(fm[j].lstrip())
                    if indent == 0:
                        break
                    block.append(fm[j].strip())
                    j += 1
                desc = ' '.join(x for x in block if x).strip()
                i = j
            else:
                desc = val.strip('"').strip("'")
                i += 1
        else:
            i += 1
    return desc, layer, body


def _mask(val: str) -> str:
    """脱敏：只留尾 4 位（短值全遮）。"""
    v = val.strip()
    if len(v) <= 4:
        return '••••'
    return '••••' + v[-4:]


def _key_configured(key: dict, env: dict[str, str]) -> bool:
    '某个 key（含别名）是否已配置。'
    if _is_set(env.get(key['env'])):
        return True
    return any(_is_set(env.get(a)) for a in key.get('aliases', []))


def _skill_api_configured(skill: str, env: dict[str, str] | None = None) -> bool:
    'SKILL 是否已具备可用配置：任一 provider 的全部 required key 齐全。'
    spec = SKILL_API_REQUIREMENTS.get(skill)
    if not spec:
        return True
    env = _read_env() if env is None else env
    for prov in spec['providers']:
        if all(_key_configured(k, env) for k in prov['keys'] if k['required']):
            return True
    return False


def _api_spec_status(skill: str, env: dict[str, str]) -> dict:
    '返回注册表项 + 每个 key 当前配置状态与脱敏值（不回传明文）。'
    spec = SKILL_API_REQUIREMENTS[skill]

    def key_status(k: dict) -> dict:
        raw = env.get(k['env'], '')
        return {
            'env': k['env'],
            'label': k['label'],
            'required': k['required'],
            'secret': k['secret'],
            'choices': list(k.get('choices', [])),
            'configured': _key_configured(k, env),
            'masked': _mask(raw) if k['secret'] and _is_set(raw) else (raw if not k['secret'] else ''),
        }

    providers = []
    for prov in spec['providers']:
        keys = [key_status(k) for k in prov['keys']]
        providers.append({'id': prov['id'], 'name': prov['name'], 'keys': keys})
    return {
        'label': spec['label'],
        'settings': [key_status(k) for k in spec.get('settings', [])],
        'providers': providers,
    }


def skill_status(name, environment):
    """The native response fields, with only registered masked credentials."""
    needed=name in SKILL_API_REQUIREMENTS
    return {'needsApi':needed,
            'apiConfigured':_skill_api_configured(name,environment) if needed else True,
            'apiSpec':_api_spec_status(name,environment) if needed else None}


def find_skill(name: str) -> str | None:
    """查找 SKILL，返回完整名或 None。与 CLI skill.py 一致。"""
    cands = [name, f'skill-{name}'] if not name.startswith('skill-') else [name]
    for cand in cands:
        if (SKILLS_DIR / 'builtin' / cand / 'SKILL.md').is_file():
            return cand
    return None


def get_skills() -> list[dict]:
    env = _read_env()
    result = []
    sd = SKILLS_DIR / 'builtin'
    if sd.is_dir():
        for d in sorted(sd.iterdir()):
            if d.is_dir() and (d / 'SKILL.md').is_file():
                desc, layer, _ = _parse_skill_md(d / 'SKILL.md')
                needs_api = d.name in SKILL_API_REQUIREMENTS
                result.append({
                    'name': d.name,
                    'description': desc,
                    'layer': layer,
                    'needsApi': needs_api,
                    'apiConfigured': _skill_api_configured(d.name, env) if needs_api else True,
                })
    return result


async def api_skills():
    return get_skills()


async def api_skill_detail(name: str):
    """单个 SKILL 详情：描述 + 正文 + API 需求与当前配置状态（脱敏）。"""
    full = find_skill(name)
    if full is None:
        raise HTTPException(404, f"SKILL '{name}' 不存在")
    desc, layer, body = _parse_skill_md(SKILLS_DIR / "builtin" / full / "SKILL.md")
    needs_api = full in SKILL_API_REQUIREMENTS
    env = _read_env()
    return {
        "name": full,
        "layer": layer,
        "description": desc,
        "body": body,
        "needsApi": needs_api,
        "apiConfigured": _skill_api_configured(full, env) if needs_api else True,
        "apiSpec": _api_spec_status(full, env) if needs_api else None,
    }


async def api_skill(req):
    if _direct_api_enabled():
        raise HTTPException(409, "API 直连模式支持聊天；SKILL 执行需要具备本机工具的 Agent 运行时")
    skill_full = find_skill(req.skill)
    if skill_full is None:
        raise HTTPException(404, f"SKILL '{req.skill}' 不存在")
    message = prepare_skill_message(skill_full, req.input, req.persona)
    # 统一给足超时：制作类 SKILL（生视频/多镜合成）可能跑很久，取安全上界
    timeout = TIMEOUT_PRODUCE
    result = await _run_skill_message(message, timeout)
    return {"response": result}

async def _run_skill_message(message, timeout, session_id=None):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, run_agent_sync, message, timeout, session_id)


def prepare_skill_message(skill, value, persona=None):
    full = find_skill(skill)
    if full is None:
        raise HTTPException(404, f"SKILL '{skill}' 不存在")
    return f"{_persona_prefix(persona)}请执行 /{full}，内容如下：\n\n{value}"


def create_skills_context(root, *, environment, execute, persona, direct_api, skills=None, ports=None):
    return bind({'SKILLS_DIR':Path(skills or Path(root)/'skills'), '_read_env':environment,
        '_run_skill_message':execute, '_persona_prefix':persona, '_direct_api_enabled':direct_api,
        'ENV_FILE':Path(root)/'.env','read_settings':lambda path:environment(),**(ports or {})})


def _publishing_message(message: str) -> str:
    if publishing_mode(read_settings(ENV_FILE)) == "manual":
        return ("【当前 Web 发布方式：人工提交】AI 只负责创作、排版、素材和审核建议。"
                "不要调用发布脚本、发布接口、浏览器代填或代点发布。"
                "引导用户在发布中心审核、复制或导出，再在官方页面亲自提交。"
                "导出、复制、打开网页和排期均不代表已发布。\n\n" + message)
    return message


def _chat_message(req) -> str:
    context = _attachment_context(req)
    message = req.message.strip()
    if context:
        message = f"{message}\n\n{context}" if message else context
    if not message:
        raise HTTPException(400, "消息不能为空")
    return _publishing_message(chat_turn_message(message, req.persona))


async def api_chat(req):
    """非流式对话（备选）。"""
    runtime = _chat_backend(req.sessionId)
    if runtime not in ("api", "openclaw"):
        message = _chat_message(req)
        sk = req.sessionId or uuid.uuid4().hex
        errors = []
        def emit(kind, text):
            if kind == "error":
                errors.append(text)
        result = await _run_harness_chat(req, sk, message, runtime, _harness_settings(), emit,
                                         interactive=False)
        if errors:
            raise HTTPException(502, errors[0])
        return {"response": result, "sessionKey": sk}
    if runtime == "api":
        content, system = _direct_chat_content(req)
        errors = []
        def emit(kind, text):
            if kind == "error":
                errors.append(text)
        sk = req.sessionId or uuid.uuid4().hex
        result = await _run_direct_chat(req, sk, content, system, emit)
        if errors:
            raise HTTPException(502, errors[0])
        return {"response": result, "sessionKey": sk}
    if req.sessionId and history_path(SESSIONS_DIR, req.sessionId).is_file():
        raise HTTPException(409, "此会话属于 API 直连，请新建会话使用 OpenClaw")
    # 每轮末尾追加「先查技能库」提醒，抗长对话指令衰减（对用户不可见）
    message = _chat_message(req)
    loop = asyncio.get_event_loop()
    # chat 可能中途触发制作层长任务 → 用 TIMEOUT_CHAT，与流式 /api/chat/stream 一致（勿用 300s）
    result = await _run_skill_message(message, TIMEOUT_CHAT, req.sessionId)
    return {"response": result}

EXPORTS=('_publishing_message','_chat_message','api_chat','find_skill','get_skills','api_skills','api_skill_detail','api_skill','prepare_skill_message','_run_skill_message','_model_spec','_short_drama_spec','_parse_skill_md','parse_skill_text','_mask','_key_configured','_skill_api_configured','_api_spec_status', 'SKILL_API_REQUIREMENTS', '_ENV_ALLOWLIST')

def bind(context=None, *, into=None):
    import sys
    return bind_functions(sys.modules[__name__], EXPORTS, context, into=into)
