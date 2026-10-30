"""Native Easel implementation shared by default and hosted applications.

Moved from web/app.py; do not generate a private copy of these functions.
Host-specific roots, persistence and configuration are supplied by bind().
"""
from __future__ import annotations
import asyncio, ipaddress, json, os, re, shutil, socket, subprocess, sys, threading, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path
from fastapi import HTTPException
from pydantic import BaseModel, Field, StrictBool
from easel.direct_api import DirectAPIError, api_config, read_settings
from easel.gateway_endpoint import chat_completions_url, port_source
from easel import harnesses
from easel.harnesses import store as harness_store
from easel.harnesses.base import HarnessError
from easel.openclaw_workspace import config_path as _oc_config_path
from .binding import bind_functions


def _k(env, label, required=True, secret=True, aliases=None):
    return {"env": env, "label": label, "required": required, "secret": secret, "aliases": aliases or []}


_PLACEHOLDER_RE = re.compile(r"replace_me|your[-_]?api[-_]?key|xxx|^\.{3}$|^<.*>$", re.I)


def _is_set(val: str | None) -> bool:
    """非空且非占位符才算真正配置了。"""
    if not val or not val.strip():
        return False
    return not _PLACEHOLDER_RE.search(val.strip())


_ENV_VALUE_OK = re.compile(r'[A-Za-z0-9_.:/@+\-=~,%?#\[\]]*')


def _is_local_gateway_base(url: str) -> bool:
    """这个供应商当前是不是挂在本地模型网关上。

    网关模式下 openclaw.json 里存的 baseUrl 是 127.0.0.1:8890，真实上游在 easel-models.yaml，
    面板显示/回传的是上游地址 —— 两边天生不相等。凡是拿「baseUrl 变了」当判据的逻辑都得先问过这里，
    否则网关用户每次保存都被判成「换了地址」。
    """
    return str(url or '').startswith('http://127.0.0.1:8890')


_SLOT_ENV_KEYS = {
    'direct-api': ('EASEL_DIRECT_API_BASE_URL', 'EASEL_DIRECT_API_KEY'),
    'openai': ('OPENAI_BASE_URL', 'OPENAI_API_KEY'),
    'relay': ('EASEL_LLM_BASE_URL', 'EASEL_LLM_API_KEY'),
    'anthropic': ('ANTHROPIC_BASE_URL', 'ANTHROPIC_API_KEY'),
    'siliconflow': ('SILICONFLOW_BASE_URL', 'SILICONFLOW_API_KEY'),
}


def _valid_base_url(u: str) -> bool:
    '整串校验（不是只看开头）：必须是 http(s)://host，且不带控制字符与 URL 内嵌凭据。'
    if any(c in u for c in '\r\n\t\x00') or '@' in u:
        return False
    try:
        p = urllib.parse.urlparse(u)
    except ValueError:
        return False
    return p.scheme in ('http', 'https') and bool(p.hostname)


def _ssrf_safe(u: str) -> bool:
    """自测会带着真 Key 去打这个地址，所以不许指向本机/内网/云元数据——
    这些地址上的服务通常无鉴权，一旦被当成「模型端点」就成了打内网的跳板。"""
    try:
        host = urllib.parse.urlparse(u).hostname or ''
        infos = socket.getaddrinfo(host, None)
    except Exception:  # noqa: BLE001  解析不了就当不安全
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


def _direct_api_enabled() -> bool:
    return _harness_settings()["runtime"] == "api"


def _model_target_allowed(base: str, slot: str = "") -> bool:
    # Trust only the exact gateway configured by the user, not arbitrary private URLs.
    settings = read_settings(ENV_FILE)
    configured = settings.get("EASEL_DIRECT_API_BASE_URL", "").strip().rstrip("/")
    if slot == "direct-api" and _direct_api_enabled() and base.rstrip("/") == configured:
        try:
            api_config(settings, require_model=False)
            return True
        except DirectAPIError:
            return False
    return _ssrf_safe(base)


def _mask_key(v: str) -> str:
    v = (v or "").strip()
    if not v:
        return ""
    return f"«{v[:5]}…{v[-4:]}»" if len(v) > 14 else "«已配置»"


def _model_channels(runtime: str | None = None) -> dict:
    env = _read_env()
    primary = ""
    direct = runtime == "api" if runtime else _direct_api_enabled()
    try:
        oc = _oc_config_path()
        if not direct and oc.is_file():
            primary = str(json.loads(oc.read_text(encoding="utf-8-sig"))
                          .get("agents", {}).get("defaults", {}).get("model", {}).get("primary", ""))
    except Exception:  # noqa: BLE001
        pass
    if direct:
        env = read_settings(ENV_FILE)
        primary = f"direct-api/{env.get('EASEL_DIRECT_API_MODEL', '')}"
    direct_ready = False
    if direct:
        try:
            api_config(env)
            direct_ready = True
        except DirectAPIError:
            pass

    chat_rows = []
    ob = (env.get("OPENAI_BASE_URL") or "").strip()
    om = (env.get("OPENAI_MODEL") or "").strip()
    ok_key = _is_set(env.get("OPENAI_API_KEY"))
    if direct:
        chat_rows.append({
            "slot": "direct-api", "order": 1, "name": "本地 / 内网 API 直连",
            "sub": "独立直连配置", "type": "openai",
            "model": env.get("EASEL_DIRECT_API_MODEL", "").strip(),
            "baseUrl": env.get("EASEL_DIRECT_API_BASE_URL", "").strip(),
            "keyMasked": _mask_key(env.get("EASEL_DIRECT_API_KEY", "")),
            "role": "主", "result": "已配置" if direct_ready else "缺配置",
        })
    elif ob or ok_key:
        chat_rows.append({
            "slot": "openai", "order": 1, "name": "deepseek",
            "sub": "官方直连",
            "type": "openai", "model": om or "deepseek-chat",
            "baseUrl": ob, "keyMasked": _mask_key(env.get("OPENAI_API_KEY", "") if ok_key else ""),
            "role": "主" if primary.startswith("openai/") else "备",
            "result": "已配置" if ok_key else "缺 key",
        })
    def _is_primary(pkey: str, model: str) -> bool:
        """这一行是不是当前的主模型。

        不能像 openai 行那样只比 provider 前缀：anthropic 与 relay 两个槽位现在都落在
        同一个 anthropic provider 上（见 _sync_anthropic_provider），只比前缀会让两行
        同时显示「主」。所以连模型一起比；model 本身可能已是 provider/model 形式
        （CLAUDE_MODEL 按约定就这么写），两种写法都要认。
        """
        if not primary or not model:
            return False
        return primary == model or primary == f"{pkey}/{model}"

    ab = (env.get("ANTHROPIC_BASE_URL") or "").strip()
    ak = (env.get("ANTHROPIC_API_KEY") or "").strip()
    ak_ok = _is_set(ak)
    if not direct and (ab or ak):
        chat_rows.append({
            "slot": "anthropic", "order": len(chat_rows) + 1, "name": "anthropic", "sub": "官方直连",
            "type": "anthropic", "model": (env.get("CLAUDE_MODEL") or "claude-sonnet-4-6").strip(),
            "baseUrl": ab or "官方", "keyMasked": _mask_key(ak if ak_ok else ""),
            # 原来写死「备」：主模型明明是 anthropic/... 时面板也显示备用，和 openai 行
            # 的处理不一致，用户据此判断「哪个在生效」会判错。
            "role": "主" if _is_primary("anthropic", (env.get("CLAUDE_MODEL") or "").strip()) else "备",
            "result": "已配置" if ak_ok else "缺 key",
        })
    lb = (env.get("EASEL_LLM_BASE_URL") or "").strip()
    lk = (env.get("EASEL_LLM_API_KEY") or "").strip()
    lk_ok = _is_set(lk)
    if not direct and (lb or lk):
        chat_rows.append({
            "slot": "relay", "order": len(chat_rows) + 1, "name": "relay", "sub": "中转站",
            "type": "openai", "model": (env.get("CLAUDE_MODEL") or "deepseek-chat").strip(),
            "baseUrl": lb or "（未配置）", "keyMasked": _mask_key(lk if lk_ok else ""),
            # relay 槽位落的也是 anthropic provider（与 setup.sh 的 EASEL_LLM_* 分支一致）
            "role": "主" if _is_primary("anthropic", (env.get("CLAUDE_MODEL") or "").strip()) else "备",
            "result": "已配置" if lk_ok else "缺 key",
        })

    custom_rows = []
    try:
        oc = _oc_config_path()
        if not direct and oc.is_file():
            provs = (json.loads(oc.read_text(encoding="utf-8-sig"))
                     .get("models", {}).get("providers", {})) or {}
            for pkey, pv in provs.items():
                if pkey in ("openai", "anthropic", "relay") or not isinstance(pv, dict):
                    continue
                models = pv.get("models") if isinstance(pv.get("models"), list) else []
                mid = models[0].get("id", "") if models and isinstance(models[0], dict) else ""
                model_entry = models[0] if models and isinstance(models[0], dict) else {}
                compat = model_entry.get("compat")
                compat = compat if isinstance(compat, dict) else {}
                custom_rows.append({
                    "slot": "custom", "order": 0, "name": pkey, "sub": "自定义",
                    "type": "openai",
                    "protocol": "anthropic" if pv.get("api") == "anthropic-messages" else "openai",
                    "thinking": model_entry.get("reasoning") is True,
                    "thinkingFormat": compat.get("thinkingFormat", ""),
                    "model": mid or "", "baseUrl": pv.get("baseUrl") or "",
                    "keyMasked": _mask_key(str(pv.get("apiKey") or "")
                                           if _is_set(str(pv.get("apiKey") or "")) else ""),
                    "role": "主" if primary == f"{pkey}/{mid}" else "备",
                    "result": "已配置" if _is_set(str(pv.get("apiKey") or "")) else "缺 key",
                    "deletable": True,
                })
    except Exception:  # noqa: BLE001
        pass
    chat_rows.extend(custom_rows)

    sf = bool((env.get("SILICONFLOW_API_KEY") or "").strip())
    trans_rows = [
        {"order": 0, "name": "自带字幕", "sub": "视频自带 SRT/VTT 时直接读", "type": "脚本层",
         "model": "—", "baseUrl": "—", "keyMasked": "—", "role": "免配", "result": "优先"},
        {"slot": "siliconflow", "order": 1, "name": "siliconflow", "sub": "硅基流动", "type": "openai",
         "model": "SenseVoiceSmall", "baseUrl": "https://api.siliconflow.cn/v1",
         "keyMasked": _mask_key(env.get("SILICONFLOW_API_KEY", "")), "role": "主",
         "result": "已配置" if sf else "缺 key"},
    ]
    channels: dict = {"chat": {"rows": chat_rows}, "transcribe": {"rows": trans_rows}}
    try:
        import model_registry as _mr  # skills/shared/scripts 已在 sys.path 上
        _setting_env = {"video": "VIDEO_PROVIDER", "music": "MUSIC_PROVIDER", "voice": "VOICE_PROVIDER"}
        for _gid, _ch in (("image", "image"), ("video", "video"), ("music", "music"), ("voice", "speech")):
            _spec = _mr.MODEL_GROUPS[_gid]
            _chosen = (env.get(_setting_env.get(_gid, ""), "") or "").strip()
            _rows = []
            for _p in _spec["providers"]:
                _req = [k for k in _p["keys"] if k["required"]]
                _bk = next((k for k in _p["keys"] if not k["secret"]
                            and ("BASE" in k["env"] or "URL" in k["env"])), None)
                _mk = next((k for k in _p["keys"] if not k["secret"] and "MODEL" in k["env"]), None)
                _edit_keys = [k for k in _req if k is not _bk and k is not _mk]
                _k1 = _edit_keys[0] if _edit_keys else None
                _k2 = _edit_keys[1] if len(_edit_keys) > 1 else None
                _ok = all(_is_set(env.get(k["env"])) or any(_is_set(env.get(a)) for a in k.get("aliases", []))
                          for k in _req)
                _masked = ""
                if _k1:
                    _raw = env.get(_k1["env"], "")
                    if not _raw:
                        for _a in _k1.get("aliases", []):
                            if env.get(_a):
                                _raw = env[_a]
                                break
                    _masked = _mask_key(_raw)
                _rows.append({
                    "slot": _p["id"], "order": 0, "name": _p["name"], "sub": _gid,
                    "type": _p["id"], "model": (env.get(_mk["env"]) or "").strip() if _mk else "",
                    "baseUrl": (env.get(_bk["env"]) or "").strip() if _bk else "",
                    "keyMasked": _masked, "role": "主" if (_gid == "image" or _chosen == _p["id"]) else "备",
                    "result": "已配置" if _ok else "未配置",
                    "key2Label": _k2["label"] if _k2 else "",
                    "key2Masked": _mask_key(env.get(_k2["env"], "")) if _k2 and _k2["secret"] else "",
                    "modelEditable": _mk is not None,
                    "baseEditable": _bk is not None,
                    "baseOptional": (_bk is None) or (not _bk["required"]),
                })
            channels[_ch] = {"rows": _rows}
    except Exception:  # noqa: BLE001
        pass
    return {"channels": channels, "primary": primary,
            "transport": "api" if direct else "openclaw"}


RESERVED_PROVIDER_KEYS = {"openai", "anthropic", "relay"}


THINKING_FORMATS = {
    "openai", "openrouter", "deepseek", "together", "qwen", "qwen-chat-template", "zai",
}


THINKING_COMPAT_KEYS = {
    "thinkingFormat", "supportsReasoningEffort", "supportedReasoningEfforts", "reasoningEffortMap",
}


def _openclaw_provider_creds() -> dict[str, tuple[str, str]]:
    """读 openclaw.json 里每个 chat 供应商现存的 (baseUrl, apiKey)。读不到就当空表（不阻断保存）。"""
    try:
        oc = _oc_config_path()
        provs = json.loads(oc.read_text(encoding='utf-8-sig')).get('models', {}).get('providers', {})
        return {k: (str(v.get('baseUrl') or ''), str(v.get('apiKey') or ''))
                for k, v in provs.items() if isinstance(v, dict)}
    except Exception:  # noqa: BLE001
        return {}


def _sync_openclaw_chat(provider_updates: dict[str, dict], keep_custom: set[str], primary_ref: str) -> str:
    """同步 chat 供应商到 ~/.openclaw-easel/openclaw.json：更新/新增 + 删除多余自定义 + 主模型。

    provider_updates: {pkey: {"model","base","key"}}；keep_custom: 保留的自定义键；primary_ref: 目标主模型（空=不改）。
    只有确有差异才落盘（改前备份 .bak-web）。
    """
    try:
        oc = _oc_config_path()
        if not oc.is_file():
            return ''
        data = json.loads(oc.read_text(encoding='utf-8-sig'))
        providers = data.setdefault('models', {}).setdefault('providers', {})
        changed = False
        for pkey in [k for k in list(providers.keys())
                     if k not in RESERVED_PROVIDER_KEYS and k not in keep_custom]:
            providers.pop(pkey, None)
            changed = True
        for pkey, vals in provider_updates.items():
            prov = providers.setdefault(pkey, {})
            base, key, model = vals.get('base', ''), vals.get('key', ''), vals.get('model', '')
            # 协议只在用户显式选择时落盘：anthropic → api=anthropic-messages；
            # openai/空 → 不写 api 字段（openclaw 默认 openai-completions，与既有配置零差异）。
            proto = (vals.get('protocol') or '').strip().lower()
            if proto == 'anthropic' and prov.get('api') != 'anthropic-messages':
                prov['api'] = 'anthropic-messages'
                changed = True
            elif proto == 'openai' and prov.get('api') == 'anthropic-messages':
                prov.pop('api', None)
                changed = True
            if base and prov.get('baseUrl') != base:
                if _is_local_gateway_base(prov.get('baseUrl')):
                    pass  # 本地模型网关模式：保留网关地址（真实上游在 easel-models.yaml），勿改回直连
                else:
                    prov['baseUrl'] = base
                    changed = True
            if key and prov.get('apiKey') != key:
                prov['apiKey'] = key
                changed = True
            if model:
                models = prov.get('models') if isinstance(prov.get('models'), list) and prov.get('models') else [{}]
                if not isinstance(models[0], dict):
                    models = [{}]
                old_model = models[0].get('id')
                if old_model != model:
                    models[0]['id'] = model
                    changed = True
                model_name = models[0].get('name')
                if (not isinstance(model_name, str) or not model_name.strip()
                        or (model_name == old_model and old_model != model)):
                    models[0]['name'] = model
                    changed = True
                prov['models'] = models
                thinking = vals.get('thinking')
                if thinking is not None:
                    before = json.dumps(models[0], sort_keys=True)
                    models[0]['reasoning'] = thinking
                    compat = models[0].get('compat')
                    compat = dict(compat) if isinstance(compat, dict) else {}
                    if thinking and prov.get('api') != 'anthropic-messages':
                        compat.setdefault('supportsReasoningEffort', True)
                        if vals.get('thinkingFormat'):
                            compat['thinkingFormat'] = vals['thinkingFormat']
                        models[0]['compat'] = compat
                    elif not thinking:
                        for compat_key in THINKING_COMPAT_KEYS:
                            compat.pop(compat_key, None)
                        if compat:
                            models[0]['compat'] = compat
                        else:
                            models[0].pop('compat', None)
                    if json.dumps(models[0], sort_keys=True) != before:
                        changed = True
        if primary_ref:
            ref = data.setdefault('agents', {}).setdefault('defaults', {}).setdefault('model', {})
            if ref.get('primary') != primary_ref:
                ref['primary'] = primary_ref
                changed = True
        if not changed:
            return ''
        shutil.copy2(oc, oc.parent / (oc.name + '.bak-web'))
        tmp = oc.parent / (oc.name + '.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(oc)
        return 'openclaw 已同步（下一条消息生效）'
    except Exception as e:  # noqa: BLE001
        return f'openclaw 同步失败：{e}'


def _sync_anthropic_provider(base: str, key: str) -> str:
    """把 Web 面板保存的 Anthropic 通道同步成 openclaw.json 里的 anthropic provider。

    bash setup.sh 用 oc_write_anthropic 写过同一块配置，但 Web 面板此前只更新 .env ——
    openclaw.json 里没有 anthropic provider，对话永远走不到新配的 Claude（问题：保存后
    界面显示「已配置」，实际不生效，且没有任何报错）。这里复刻 setup.sh 的写入：
    api=anthropic-messages、models 留空（agent 侧走 anthropic 扩展的内置 Claude 目录），
    原子写 + .bak-web 备份，风格与 _sync_openclaw_chat 一致。返回给用户的提示语。
    """
    try:
        oc = _oc_config_path()
        if not oc.is_file():
            return ''
        data = json.loads(oc.read_text(encoding='utf-8-sig'))
        providers = data.setdefault('models', {}).setdefault('providers', {})
        prov = providers.get('anthropic')
        target_base = base or 'https://api.anthropic.com'
        # 早退判据必须把 api 一起算上：否则一个「baseUrl/apiKey 都对、但缺 api」的
        # 残缺 provider（旧版本 Web 面板写出来的就是这样）永远修不回来。
        if isinstance(prov, dict) and prov.get('baseUrl') == target_base \
                and prov.get('api') == 'anthropic-messages' \
                and (not key or prov.get('apiKey') == key):
            return ''
        new_prov = dict(prov) if isinstance(prov, dict) else {'models': []}
        new_prov['baseUrl'] = target_base
        # api 必须显式写死。上面的 docstring 一直这么说，但代码此前漏了这一行 ——
        # 不写时 OpenClaw 2026.2.x 会把该 provider 当成 openai-responses、请求打到
        # /responses，上游的报错被 gateway 当成正常回复塞进 choices[0].message.content，
        # 于是 Web 对话静默显示「（无输出）」。与 setup.sh 的 oc_write_anthropic 对齐。
        new_prov['api'] = 'anthropic-messages'
        # setup.sh 同样会设这个；两边都写，provider 才不会因为「谁后写」而缺字段。
        new_prov.setdefault('timeoutSeconds', 600)
        if key:
            new_prov['apiKey'] = key
        new_prov.setdefault('models', [])
        # 一次性迁移：更早的 Web 面板会把中转站写成一个名叫 relay 的 provider，但从来
        # 不给它填内容，primary 却指过去。本次若没拿到 key，就把 relay 里的捡回来，
        # 免得老用户升级后 key 变成孤儿；迁移后删掉 relay，避免两处并存各写一半。
        legacy = providers.get('relay')
        if isinstance(legacy, dict):
            if not key and not base and not _is_set(new_prov.get('apiKey')) \
                    and _is_set(legacy.get('apiKey')) and legacy.get('baseUrl'):
                new_prov['apiKey'] = legacy['apiKey']
                new_prov['baseUrl'] = legacy['baseUrl']
            providers.pop('relay', None)
        providers['anthropic'] = new_prov
        shutil.copy2(oc, oc.parent / (oc.name + '.bak-web'))
        tmp = oc.parent / (oc.name + '.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(oc)
        return 'anthropic provider 已同步到 openclaw（下一条消息生效）'
    except Exception as e:  # noqa: BLE001
        return f'anthropic provider 同步失败：{e}'


class ModelSaveRow(BaseModel):
    slot: str = ""
    name: str = ""
    model: str = ""
    baseUrl: str = ""
    key: str = ""
    key2: str = ""
    primary: bool = False
    # 自定义供应商的上游协议：openai（默认，/chat/completions）或 anthropic
    # （原生 /v1/messages；中转站卖原生 Claude 格式时选它）。
    protocol: str = ""
    thinking: StrictBool | None = None
    thinkingFormat: str | None = None


class ModelSaveRequest(BaseModel):
    channel: str = "chat"
    rows: list[ModelSaveRow] = Field(default_factory=list)


async def api_settings_models_save(req: ModelSaveRequest):
    """保存模型通道：.env 就地更新（key 留空=不改）；chat 同步 openclaw；媒体通道写 provider 配置。"""
    ch0 = (req.channel or "").strip()
    if ch0 == "chat" and _harness_settings()["runtime"] not in ("api", "openclaw"):
        raise HTTPException(409, "当前底座使用原生认证；模型覆盖请在 Agent 底座设置中保存")
    direct = _direct_api_enabled()
    if direct and ch0 == "chat" and any(row.slot != "direct-api" for row in req.rows):
        raise HTTPException(400, "API 直连模式请使用独立的 API 直连通道")
    if any(row.slot == "direct-api" for row in req.rows) and not (direct and ch0 == "chat"):
        raise HTTPException(400, "请先切换到 API 直连模式再保存直连配置")
    if direct and ch0 == "chat" and any(
            name in os.environ for name in (
                "EASEL_DIRECT_API_BASE_URL", "EASEL_DIRECT_API_MODEL", "EASEL_DIRECT_API_KEY")):
        raise HTTPException(409, "运行环境已指定直连配置，请修改启动环境后重启")
    if ch0 in ("speech", "image", "video", "music"):
        import model_registry as _mr2
        _gid0 = {"speech": "voice", "image": "image", "video": "video", "music": "music"}[ch0]
        _spec0 = _mr2.MODEL_GROUPS[_gid0]
        _by_id = {p["id"]: p for p in _spec0["providers"]}
        _setting0 = {"video": "VIDEO_PROVIDER", "music": "MUSIC_PROVIDER", "voice": "VOICE_PROVIDER"}.get(_gid0)
        _mupd: dict[str, str] = {}
        _primary0 = ""
        _env0 = _read_env()
        for _row in req.rows:
            _pid = (_row.slot or "").strip()
            _p0 = _by_id.get(_pid)
            if not _p0:
                raise HTTPException(400, f"不认识的服务商：{_pid or '（空）'}")
            _base0 = (_row.baseUrl or "").strip().rstrip("/")
            _key0 = (_row.key or "").strip()
            _key20 = (_row.key2 or "").strip()
            _model0 = (_row.model or "").strip()
            if _base0 and not _valid_base_url(_base0):
                raise HTTPException(400, f'{_p0["name"]} 的根地址需是合法的 http(s):// 地址')
            if (_key0 and any(x.isspace() for x in _key0)) or (_key20 and any(x.isspace() for x in _key20)):
                raise HTTPException(400, f'{_p0["name"]} 的 Key 不能包含空白字符')
            _bk0 = next((k for k in _p0["keys"] if not k["secret"]
                         and ("BASE" in k["env"] or "URL" in k["env"])), None)
            _mk0 = next((k for k in _p0["keys"] if not k["secret"] and "MODEL" in k["env"]), None)
            _req0 = [k for k in _p0["keys"] if k["required"] and k is not _bk0 and k is not _mk0]
            # 与对话通道同一条规矩：只改根地址、Key 留空（留空=沿用旧 Key），等于把已存的真 Key
            # 指到新地址去——SILICONFLOW 这类通道还有「连通性自测」会把它当 Bearer 发过去。
            if _base0 and _bk0 and not _key0 and _base0 != (_env0.get(_bk0["env"], "") or "").strip().rstrip("/") \
                    and _req0 and (_env0.get(_req0[0]["env"], "") or "").strip():
                raise HTTPException(400, f'更换{_p0["name"]}的根地址时必须重新填写 Key')
            if _key0 and _req0:
                _mupd[_req0[0]["env"]] = _key0
            if _key20 and len(_req0) > 1:
                _mupd[_req0[1]["env"]] = _key20
            if _model0 and _mk0:
                _mupd[_mk0["env"]] = _model0
            if _base0 and _bk0:
                _mupd[_bk0["env"]] = _base0
            if getattr(_row, "primary", False):
                _primary0 = _pid
        if _primary0 and _setting0:
            _mupd[_setting0] = _primary0
        if not _mupd:
            raise HTTPException(400, "没有可保存的改动（key 留空表示不改）")
        _write_env_direct(_mupd)
        _resp0 = {"ok": True, "note": ""}
        _resp0.update(_model_channels())
        return _resp0

    updates: dict[str, str] = {}
    provider_updates: dict[str, dict] = {}
    keep_custom: set[str] = set()
    primary_ref = ''
    is_chat = (req.channel or '').strip() == 'chat'
    _cur_env = read_settings(ENV_FILE) if direct else _read_env()
    _cur_prov = _openclaw_provider_creds() if is_chat and not direct else {}
    for row in req.rows:
        slot = (row.slot or '').strip()
        name = (row.name or '').strip().lower()
        model = (row.model or '').strip()
        base = (row.baseUrl or '').strip().rstrip('/')
        key = (row.key or '').strip()
        if base and not _valid_base_url(base):
            raise HTTPException(400, f'Base URL 需是合法的 http(s):// 地址：{base[:60]}')
        if key and any(ch.isspace() for ch in key):
            raise HTTPException(400, 'API Key 不能包含空白字符')
        if len(model) > 120 or len(base) > 300 or len(key) > 400:
            raise HTTPException(400, '字段过长，请检查')
        # 改 Base URL 但把 Key 留空（留空=沿用旧 Key）＝ 把已存的真 Key 指向新地址，
        # 之后一次「连通性自测」就会把它当 Bearer 送到新地址去。换地址必须重填 Key。
        _be, _ke = _SLOT_ENV_KEYS.get(slot, ('', ''))
        if base and _be and not key and base != (_cur_env.get(_be, '') or '').strip().rstrip('/') \
                and (_cur_env.get(_ke, '') or '').strip():
            raise HTTPException(400, f'更换 Base URL 时必须重新填写 API Key（{slot}）')
        pkey = ''
        if slot == 'direct-api':
            if model:
                updates['EASEL_DIRECT_API_MODEL'] = model
            if base:
                updates['EASEL_DIRECT_API_BASE_URL'] = base
            if key:
                updates['EASEL_DIRECT_API_KEY'] = key
        elif slot == 'openai':
            if model:
                updates['OPENAI_MODEL'] = model
            if base:
                updates['OPENAI_BASE_URL'] = base
            if key:
                updates['OPENAI_API_KEY'] = key
            if is_chat:
                provider_updates['openai'] = {'model': model, 'base': base, 'key': key}
                pkey = 'openai'
        elif slot == 'relay':
            if base:
                updates['EASEL_LLM_BASE_URL'] = base
            if model:
                updates['CLAUDE_MODEL'] = model
            if key:
                updates['EASEL_LLM_API_KEY'] = key
            if is_chat:
                # 落进 anthropic provider，而不是造一个名叫 relay 的 provider。
                # setup.sh 的 EASEL_LLM_* 分支写的就是 models.providers.anthropic
                # （见 oc_write_anthropic）。此前这里只写 .env、从不创建 provider，
                # 却把 primary 指向 relay/<model> —— 对话直接报
                # 「No route-compatible authentication source is configured for relay」。
                pkey = 'anthropic'
        elif slot == 'anthropic':
            if model:
                updates['CLAUDE_MODEL'] = model
            if key:
                updates['ANTHROPIC_API_KEY'] = key
            if base:
                updates['ANTHROPIC_BASE_URL'] = base
            if is_chat:
                pkey = 'anthropic'
        elif slot == 'siliconflow':
            if base:
                updates['SILICONFLOW_BASE_URL'] = base
            if key:
                updates['SILICONFLOW_API_KEY'] = key
        elif slot == 'custom' and is_chat:
            if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,23}', name):
                raise HTTPException(400, f'供应商名只能用小写字母/数字/横线（最长24位）：{name[:30] or "（空）"}')
            if name in RESERVED_PROVIDER_KEYS:
                raise HTTPException(400, f'「{name}」是内置槽位名，请换一个')
            if not model or not base:
                raise HTTPException(400, f'自定义供应商「{name}」需要同时填模型和 Base URL')
            proto = (getattr(row, 'protocol', '') or '').strip().lower()
            if proto not in ('', 'openai', 'anthropic'):
                raise HTTPException(400, f'协议只支持 openai / anthropic：{proto}')
            thinking_format = (row.thinkingFormat or '').strip().lower()
            if thinking_format and thinking_format not in THINKING_FORMATS:
                raise HTTPException(400, f'不支持的思考格式：{thinking_format}')
            if thinking_format and row.thinking is None:
                raise HTTPException(400, '选择思考格式时需要显式声明是否启用思考')
            if proto == 'anthropic' and thinking_format:
                raise HTTPException(400, 'Anthropic 原生协议无需选择 OpenAI 兼容思考格式')
            provider_updates[name] = {'model': model, 'base': base, 'key': key, 'protocol': proto}
            if row.thinking is not None:
                provider_updates[name]['thinking'] = row.thinking
                if thinking_format:
                    provider_updates[name]['thinkingFormat'] = thinking_format
            keep_custom.add(name)
            pkey = name
        # 同一条规矩也得覆盖 openclaw.json 这一侧：_sync_openclaw_chat 只在 key 非空时改
        # apiKey，却无条件改 baseUrl —— 只换地址、Key 留空，下一轮对话就会拿着原 Key 去打新地址。
        # 自定义供应商压根不写 .env，前面那道 _SLOT_ENV_KEYS 闸拦不到它。
        # 但网关模式要放行：那边存的是 127.0.0.1:8890、面板回传的是真实上游，永远不相等，
        # 这道闸会把网关用户彻底锁死（连只改模型都保存不了）；而且下面 _sync_openclaw_chat
        # 本来就不会改网关的 baseUrl，没有「拿旧 Key 打新地址」这个风险。
        if is_chat and pkey and base and not key:
            # 换址校验的「现值」要跟配置的权威来源比：openai/relay/anthropic 的权威在 .env
            # （面板与 setup.sh 都写它），openclaw.json 只是保存时的镜像——setup.sh 配置后
            # 用户从没用面板保存过的话，镜像可能停在初始值（如 api.openai.com），拿它比对
            # 会把「原样回传真值」误判成「换址没填 key」，整个面板都保存不了（真机踩中）。
            # custom 供应商权威就在 openclaw.json，维持原比对。
            _be, _ke = _SLOT_ENV_KEYS.get(slot, ('', ''))
            if _be and _is_set(_cur_env.get(_ke)):
                _pb = (_cur_env.get(_be, '') or '').strip().rstrip('/')
                _pk = (_cur_env.get(_ke, '') or '').strip()
                if slot == 'anthropic' and not _pb:
                    _pb = 'https://api.anthropic.com'
            else:
                _pb, _pk = _cur_prov.get(pkey, ('', ''))
                _pb = _pb.strip().rstrip('/')
            if _pk and base != _pb and not _is_local_gateway_base(_pb):
                raise HTTPException(400, f'更换 Base URL 时必须重新填写 API Key（{pkey}）')
        if is_chat and slot == 'openai' and not key and _is_set(_cur_env.get('OPENAI_API_KEY')) \
                and (_cur_env.get('OPENAI_BASE_URL') or '').strip() \
                and not _is_local_gateway_base(_cur_prov.get('openai', ('', ''))[0]):
            provider_updates['openai']['key'] = _cur_env['OPENAI_API_KEY'].strip()
            provider_updates['openai']['base'] = (
                base or _cur_env['OPENAI_BASE_URL'].strip().rstrip('/'))
        if is_chat and pkey and getattr(row, 'primary', False) and model:
            # model 可能本来就是 provider/model 形式：anthropic 行的 model 直接取自
            # .env 的 CLAUDE_MODEL，而那个值按约定就写成 anthropic/claude-opus-4-7。
            # 无脑拼前缀会写出 anthropic/anthropic/claude-opus-4-7，主模型随即不可路由。
            # 自定义供应商的模型 ID 是上游原值，可能包含命名空间
            # （如 LiteLLM 的 dashscope/qwen-*），必须保留并加上实际供应商。
            primary_ref = (f'{pkey}/{model}' if slot == 'custom'
                           else model if model.startswith(f'{pkey}/') else f'{pkey}/{model}')
    if not updates and not provider_updates and not primary_ref:
        raise HTTPException(400, '没有可保存的改动（key 留空表示不改）')
    if is_chat and direct:
        try:
            api_config({**_cur_env, **updates})
        except DirectAPIError as error:
            raise HTTPException(400, str(error)) from None
    if updates:
        _write_env_direct(updates)
    note = ''
    if is_chat and direct:
        note = "API 直连配置已保存，下一轮生效；无需同步 OpenClaw"
    elif is_chat:
        note = _sync_openclaw_chat(provider_updates, keep_custom, primary_ref)
        # anthropic / relay 两个槽位都不在 provider_updates 里（它们不是自定义供应商），
        # 但同样要落到 openclaw.json 才真正生效 —— setup.sh 写的 provider 可能已过时。
        # 两者共用同一个 anthropic provider，和 setup.sh 的映射保持一致。
        _slots = {(r.slot or '').strip() for r in req.rows}
        effective_env = {**_cur_env, **updates}
        sync_slot = ''
        for candidate in ('relay', 'anthropic'):
            base_var, key_var = _SLOT_ENV_KEYS[candidate]
            if candidate in _slots and _is_set(effective_env.get(key_var)) \
                    and (candidate == 'anthropic' or effective_env.get(base_var, '').strip()):
                sync_slot = candidate
                break
        if not sync_slot:
            sync_slot = next((candidate for candidate in ('relay', 'anthropic')
                              if candidate in _slots), '')
        if sync_slot:
            base_var, key_var = _SLOT_ENV_KEYS[sync_slot]
            if _is_set(effective_env.get(key_var)):
                sync_base = effective_env.get(base_var, '').strip().rstrip('/')
                sync_key = effective_env[key_var].strip()
            else:
                sync_base = _cur_prov.get('anthropic', ('', ''))[0]
                sync_key = ''
            _an = _sync_anthropic_provider(sync_base, sync_key)
            if _an:
                note = f'{note}；{_an}' if note else _an
    resp = {"ok": True, "note": note}
    resp.update(_model_channels())
    return resp


class LocalAgentEnableRequest(BaseModel):
    id: str
    # 可选：从插件模型目录里选的模型 id（前端下拉列表）；不传用各家默认。
    model: str = ""


async def api_local_agents():
    """探测本机已装的 agent CLI（Claude Code / Gemini CLI / Codex…）。

    目的：装了 Claude Code / Gemini CLI 且已登录的用户**不需要再填 API Key** ——
    OpenClaw 底座有对应的 CLI 后端，直接复用 CLI 自己的登录态。返回值同时如实
    标出哪些 CLI 暂无底座后端（installed 但 supported=false），不假装支持。
    """
    from easel.local_agents import summarize_local_agents
    return await asyncio.to_thread(summarize_local_agents)


async def api_local_agent_enable(req: LocalAgentEnableRequest):
    """把一个本机 CLI agent（目前支持 claude-code / gemini-cli）接入 Easel。

    实现是把对应 provider 写进 openclaw.json（复用 _sync_anthropic_provider 的
    原子写套路）。CLI 登录态本身由 openclaw 的 auth store 管理 —— 这里只负责
    「声明 provider 并把主模型切过去」；未登录的 CLI 会在下一轮对话时暴露
    认证错误，返回体里用 hint 提前告知用户先去终端登录。

    req.model 可选：从插件模型目录里选一个（前端下拉列表），不传用各家默认。
    传了但不在目录里 → 400 拒绝，绝不静默写入一个不存在的模型引用。
    """
    from easel.local_agents import detect_local_agents, catalog_for_provider
    agents = {a["id"]: a for a in detect_local_agents()}
    agent = agents.get(req.id)
    if not agent:
        raise HTTPException(404, f"未知的本机 agent：{req.id}")
    if not agent["installed"]:
        raise HTTPException(400, f"本机没有找到 {agent['label']}（PATH 上没有 {agent['command'] or '可执行文件'}）")
    provider = agent["openclawProvider"]
    if not provider:
        raise HTTPException(400, f"{agent['label']} 暂无底座后端，无法免 key 接入")
    chosen = (req.model or "").strip()
    catalog = catalog_for_provider(str(agent["openclawProvider"]))
    if provider == "claude-cli":
        # base 必须读 .env（不是 os.environ）：面板/.env 里配的中转站或自建网关值
        # 只在项目 .env 里，不在进程环境里 —— 用 os.environ 会永远拿到空，然后把
        # 用户已配好的 baseUrl 静默覆盖成官方端点。
        note = _declare_anthropic_provider(
            (_read_env().get("ANTHROPIC_BASE_URL") or "").strip().rstrip("/")
            or "https://api.anthropic.com")
        model_id = chosen or "claude-sonnet-4-6"
        # claude-cli 后端的模型走 provider=claude-cli；把主模型指过去
        primary_ref = f"claude-cli/{model_id}"
    elif provider == "google-gemini-cli":
        # google 插件的 CLI 后端默认启用（enabledByDefault），无需写 provider 块；
        # 接入 = 把主模型指到 CLI 后端的一个真实模型上。
        model_id = chosen or "gemini-3.1-pro-preview"
        primary_ref = f"google-gemini-cli/{model_id}"
        note = ""
    else:
        # 不该到这：supported 的 CLI 都应在上面有明确分支。新后端接入时必须补写，
        # 否则会像 gemini 最初那样返回「已接入」却什么都没写（假成功）。
        raise HTTPException(500, f"{agent['label']} 的接入流程未实现（openclawProvider={provider}）")
    if chosen and catalog and model_id not in {m["id"] for m in catalog}:
        raise HTTPException(400, f"{model_id} 不在 {agent['label']} 的可选模型里（可选：{', '.join(str(m['id']) for m in catalog)}）")
    if primary_ref:
        _oc_note = _set_openclaw_primary(primary_ref)
        note = f"{note}；{_oc_note}" if note else _oc_note
        if not _oc_note:
            note = f"已接入（主模型此前已是 {primary_ref}）"
    return {"ok": True, "agent": agent, "note": note or "已接入"}


def _set_openclaw_primary(primary_ref: str) -> str:
    """把 agents.defaults.model.primary 指到给定 provider/model（原子写 + 备份）。"""
    try:
        oc = _oc_config_path()
        if not oc.is_file():
            return 'openclaw.json 不存在，请先运行 bash setup.sh'
        data = json.loads(oc.read_text(encoding='utf-8-sig'))
        ref = data.setdefault('agents', {}).setdefault('defaults', {}).setdefault('model', {})
        if ref.get('primary') == primary_ref:
            return ''
        ref['primary'] = primary_ref
        shutil.copy2(oc, oc.parent / (oc.name + '.bak-web'))
        tmp = oc.parent / (oc.name + '.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(oc)
        return f'主模型已切到 {primary_ref}（下一条消息生效）'
    except Exception as e:  # noqa: BLE001
        return f'主模型切换失败：{e}'


def _declare_anthropic_provider(base: str) -> str:
    """在 openclaw.json 里声明 anthropic provider（apiKey 缺省走 CLI 登录态/auth store）。

    与 setup.sh 的 oc_write_anthropic 同构；不写 key 时 agent 侧会回落到 claude-cli
    后端复用本机 Claude Code 的登录。原子写 + .bak-web 备份。
    """
    try:
        oc = _oc_config_path()
        if not oc.is_file():
            return 'openclaw.json 不存在，请先运行 bash setup.sh'
        data = json.loads(oc.read_text(encoding='utf-8-sig'))
        providers = data.setdefault('models', {}).setdefault('providers', {})
        prov = providers.get('anthropic')
        if isinstance(prov, dict) and prov.get('baseUrl') == base:
            return ''
        new_prov = dict(prov) if isinstance(prov, dict) else {'models': []}
        new_prov['baseUrl'] = base
        new_prov.setdefault('models', [])
        providers['anthropic'] = new_prov
        shutil.copy2(oc, oc.parent / (oc.name + '.bak-web'))
        tmp = oc.parent / (oc.name + '.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(oc)
        return 'anthropic provider 已声明'
    except Exception as e:  # noqa: BLE001
        return f'anthropic provider 声明失败：{e}'


class SelftestRequest(BaseModel):
    channel: str = "chat"


class ModelsFetchRequest(BaseModel):
    """「拉取模型列表」请求。

    key 优先用前端传来的草稿值（供应商还没落盘时也能拉）；留空则按 slot 从已存配置里取
    —— 用户已经存过 Key，不该为了拉一次列表再贴一遍明文。服务端全程不落盘、不写日志。

    baseUrl 允许留空由 slot 回落，否则「只用已存配置拉列表」这条路径就进不来。
    """
    baseUrl: str = ""
    key: str = ""
    protocol: str = "openai"  # openai | anthropic
    slot: str = ""
    name: str = ""  # 自定义供应商的 provider 名（slot='custom' 时用它查已存凭据）


_FETCH_KEY_BY_SLOT = {
    'direct-api': ('EASEL_DIRECT_API_BASE_URL', 'EASEL_DIRECT_API_KEY'),
    'openai': ('OPENAI_BASE_URL', 'OPENAI_API_KEY'),
    'relay': ('EASEL_LLM_BASE_URL', 'EASEL_LLM_API_KEY'),
    'anthropic': ('ANTHROPIC_BASE_URL', 'ANTHROPIC_API_KEY'),
    'siliconflow': ('SILICONFLOW_BASE_URL', 'SILICONFLOW_API_KEY'),
}


async def api_models_available(req: ModelsFetchRequest):
    """代前端拉一次 GET {base}/models，返回模型 id 列表（自定义供应商不用再手打模型名）。

    与 selftest 同一条安全线：带着用户 Key 出去的请求，目标必须过 _valid_base_url +
    _ssrf_safe；不落盘、不写日志。
    """
    base = (req.baseUrl or "").strip().rstrip("/")
    key = (req.key or "").strip()
    slot = (req.slot or "").strip()
    # 草稿没填 key 时，回落到该槽位已存的值（只在内存里用，不回显、不记日志）。
    if not key and slot:
        _env = read_settings(ENV_FILE) if _direct_api_enabled() else _read_env()
        if slot == 'custom':
            # 自定义供应商的凭据在 openclaw.json 里（provider 名 = 用户填的名字）
            _b, _k = _openclaw_provider_creds().get((req.name or '').strip().lower(), ("", ""))
        else:
            _bk, _kk = _FETCH_KEY_BY_SLOT.get(slot, ("", ""))
            _b, _k = _env.get(_bk, ""), _env.get(_kk, "")
        key = (_k or "").strip()
        if slot == "direct-api" and key and base and base != (_b or "").strip().rstrip("/"):
            raise HTTPException(400, "更换根地址时必须重新填写 Key，不能把已存 Key 发给其他地址")
        if not base and _b:
            base = _b.strip().rstrip("/")
    if not base:
        raise HTTPException(400, "Base URL 不能为空")
    if not _valid_base_url(base):
        raise HTTPException(400, "Base URL 不合法")
    if not _model_target_allowed(base, slot):
        raise HTTPException(400, "目标指向本机/内网地址，已拒绝（避免把 API Key 发给内网服务）")

    anthropic = slot != "direct-api" and (req.protocol or "").strip().lower() == "anthropic"
    if anthropic:
        url = base + "/v1/models"
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01",
                   "Authorization": f"Bearer {key}"}
    else:
        url = base + "/models"
        headers = {"Authorization": f"Bearer {key}"} if key else {}

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_a, **_kw):
            return None

    handlers = [_NoRedirect]
    if slot == "direct-api" and _direct_api_enabled() and base == read_settings(ENV_FILE).get("EASEL_DIRECT_API_BASE_URL", "").strip().rstrip("/"):
        handlers.append(urllib.request.ProxyHandler({}))
    _opener = urllib.request.build_opener(*handlers)

    def _fetch() -> list[str]:
        rq = urllib.request.Request(url, headers=headers)
        with _opener.open(rq, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
        # OpenAI / Anthropic 形状都是 {"data":[{"id":...}]}；有的网关直接给 ["id",...]。
        if isinstance(payload, dict):
            items = payload.get("data") or payload.get("models") or []
        elif isinstance(payload, list):
            items = payload
        else:
            items = []
        ids = []
        for it in items:
            mid = it.get("id") if isinstance(it, dict) else it
            if isinstance(mid, str) and mid.strip():
                ids.append(mid.strip())
        return sorted(set(ids))

    try:
        models = await asyncio.to_thread(_fetch)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"拉取失败：{type(e).__name__}: {e}"[:180]) from e
    return {"baseUrl": base, "models": models, "fetchedAt": int(time.time())}


async def api_models_selftest(req: SelftestRequest):
    """真自测：对已配置的 OpenAI 兼容通道发 GET {base}/models 并计耗时。"""
    channel = (req.channel or "all").strip()
    if channel in ("chat", "all") and _harness_settings()["runtime"] not in ("api", "openclaw"):
        raise HTTPException(409, "此底座使用原生模型配置，请新建对话或运行 easel ping 验证")
    direct = _direct_api_enabled()
    env = read_settings(ENV_FILE) if direct else _read_env()
    # (base, key, 是否为 Anthropic Messages 协议, slot)。协议决定鉴权头与路径：
    # Anthropic 是 x-api-key + /v1/models，OpenAI 兼容是 Bearer + /models。
    targets: list[tuple[str, str, bool, str]] = []
    if channel in ("chat", "all"):
        if direct:
            chat_targets = ((env.get("EASEL_DIRECT_API_BASE_URL", ""),
                             env.get("EASEL_DIRECT_API_KEY", ""), False, "direct-api"),)
        else:
            chat_targets = (
                (env.get("ANTHROPIC_BASE_URL", ""), env.get("ANTHROPIC_API_KEY", ""), True, "anthropic"),
                (env.get("OPENAI_BASE_URL", ""), env.get("OPENAI_API_KEY", ""), False, "openai"),
                (env.get("EASEL_LLM_BASE_URL", ""), env.get("EASEL_LLM_API_KEY", ""), False, "relay"),
            )
        for base, key, is_anthropic, slot in chat_targets:
            if base.strip() and (key.strip() or direct):
                targets.append((base.strip().rstrip("/"), key.strip(), is_anthropic, slot))
    if channel in ("transcribe", "all") and (env.get("SILICONFLOW_API_KEY") or "").strip():
        targets.append(((env.get("SILICONFLOW_BASE_URL") or "https://api.siliconflow.cn/v1").strip().rstrip("/"),
                        env["SILICONFLOW_API_KEY"].strip(), False, "siliconflow"))

    # 这里会把真实 API Key 当 Bearer 发出去，所以目标地址必须先过闸：
    # 合法 http(s)、且不指向本机/内网/云元数据；跳转也不跟（跟了等于绕过前面的判断）。
    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_a, **_kw):
            return None

    _opener = urllib.request.build_opener(_NoRedirect)

    def _probe(base: str, key: str, *, anthropic: bool = False, slot: str = "") -> dict:
        t0 = time.time()
        if not _valid_base_url(base):
            return {"baseUrl": base, "ok": False, "ms": 0, "detail": "Base URL 不合法，未发起请求"}
        if not _model_target_allowed(base, slot):
            return {"baseUrl": base, "ok": False, "ms": 0,
                    "detail": "目标指向本机/内网地址，已拒绝（避免把 API Key 发给内网服务）"}
        try:
            if anthropic:
                # Anthropic Messages 协议的鉴权头是 x-api-key（不是 Authorization: Bearer），
                # 且模型列表在 /v1/models。按 OpenAI 兼容方式探测只会得到 401/404，
                # 让用户误以为 Key 无效。同时带上两种头：兼容把 /v1/models 反代成
                # OpenAI 风格的中转站（它们只认 Bearer）。
                url = base + "/v1/models"
                rq = urllib.request.Request(url, headers={
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                    "Authorization": f"Bearer {key}",
                })
            else:
                headers = {"Authorization": f"Bearer {key}"} if key else {}
                rq = urllib.request.Request(base + "/models", headers=headers)
            opener = _opener
            if slot == "direct-api" and base == env.get("EASEL_DIRECT_API_BASE_URL", "").strip().rstrip("/"):
                opener = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler({}))
            with opener.open(rq, timeout=15) as resp:
                return {"baseUrl": base, "ok": resp.status == 200, "ms": int((time.time() - t0) * 1000)}
        except Exception as e:  # noqa: BLE001
            return {"baseUrl": base, "ok": False, "ms": int((time.time() - t0) * 1000),
                    "detail": f"{type(e).__name__}: {e}"[:140]}

    def _run_probes() -> list[dict]:
        out: list[dict] = []
        for base, key, is_anthropic, slot in targets:
            out.append(_probe(base, key, anthropic=is_anthropic, slot=slot))
        return out

    results = await asyncio.to_thread(_run_probes)
    return {"channel": channel, "results": results, "testedAt": int(time.time())}


EXPORTS = ('_k', '_PLACEHOLDER_RE', '_is_set', '_ENV_VALUE_OK', '_is_local_gateway_base', '_SLOT_ENV_KEYS', '_valid_base_url', '_ssrf_safe', '_direct_api_enabled', '_model_target_allowed', '_mask_key', '_model_channels', 'RESERVED_PROVIDER_KEYS', 'THINKING_FORMATS', 'THINKING_COMPAT_KEYS', '_openclaw_provider_creds', '_sync_openclaw_chat', '_sync_anthropic_provider', 'ModelSaveRow', 'ModelSaveRequest', 'api_settings_models_save', 'LocalAgentEnableRequest', 'api_local_agents', 'api_local_agent_enable', '_set_openclaw_primary', '_declare_anthropic_provider', 'SelftestRequest', 'ModelsFetchRequest', '_FETCH_KEY_BY_SLOT', 'api_models_available', 'api_models_selftest')

def bind(context=None, *, into=None):
    return bind_functions(sys.modules[__name__], EXPORTS, context, into=into)


def create_settings_context(root, environment, state, config):
    """Use the native provider rules with a host-owned revision and secret store."""
    root, config = Path(root).resolve(), Path(config)
    return bind({
        'PROJECT_ROOT': root, 'OUTPUTS_DIR': root / 'outputs', 'ENV_FILE': root / '.env',
        '_read_env': lambda: dict(environment),
        'read_settings': lambda *args, **kwargs: dict(environment),
        '_harness_settings': lambda: dict(state),
        '_oc_config_path': lambda: config,
        '_write_env_direct': lambda updates: environment.update(
            {key: value for key, value in updates.items() if value.strip()}),
        '_warn_http_transport_unavailable': lambda *args: None,
    })
