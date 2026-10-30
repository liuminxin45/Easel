---
name: experience-distillation
description: "用户按需发起，从指定画像和作品反馈提出可审阅、可试用的技能修订。当用户需要经验提炼时使用，读取本项目已选择的画像、版本和冻结材料；只处理明确任务范围，候选、反馈和发布授权分别保存，不把旧任务按当前目录重解释。"
layer: general
metadata:
  openclaw:
    workbench: {"id":"experience-distillation","tasks":["learning"],"executor":"readonly-agent","input_contract":{"required":["profile","target_skill","base_version","events","goal"],"optional":["previous_analyses","reference_assets"]},"output_contract":{"required":["changed","reason","prompt","conditions","evidence_refs","validation","responses","image_observations"],"prohibits":["自动发布技能","直接重写规范","合并丢失复现事件","发起新制作"],"bound_fields":["skill_id","base_version"]},"acceptance_cases":["候选不会自动成为默认","仅本篇意见不升级长期规则","无修改价值可明确结束","未取得原图不声称看过"],"schema_version":1,"display_name":"经验提炼","resources":[{"path":"skills/shared/workbench/资料/风格研究/用户指导记录索引.md","kind":"historical_index","scope":"on-demand","executable":false,"historical":true},{"path":"skills/shared/workbench/规范/创作策略.json","kind":"contract","scope":"on-demand"},{"path":"skills/shared/workbench/.agents/skills/neo-experience-distillation/references/incremental-learning.md","kind":"contract","scope":"on-demand"},{"path":"skills/shared/workbench/.agents/skills/neo-experience-distillation/references/skill-distillation.md","kind":"contract","scope":"on-demand","required":true},{"path":"skills/shared/workbench/production-contract.md","kind":"contract","scope":"on-demand","required":true}],"source":{"registry_path":".agents/skills/capabilities.json","registry_sha256":"014bafced32c43692d7d6eb25b5f00216f45e18676f9c6f4b23837845a1079e8","entry_path":".agents/skills/neo-experience-distillation/SKILL.md","entry_sha256":"8188ce8aa26b2f6ebbc399a3866569fce0cf6418e6965d55d113840fdda044ae"},"migration":{"kind":"project_builtin_mechanical","published_style_change":false}}
---

# 经验提炼

只处理本次冻结范围的画像、目标技能及基础版本、原始反馈、准确前后作品和样本。事件先由程序去重和关联，保留不同版本再次出现的复现身份；不能把整稿采纳解释为所有维度都好，也不能把不采纳解释为全盘否定。

提出最少必要的改动：针对什么问题、改哪段提示词或资源、原话依据、适用条件、例外、不能照搬之处和验证案例。作品局部纠正保留本篇；无复用价值、证据不足或没有必要修改时明确说明，可以结束处理，不强行生成新规则。

相反方法先判断条件差异，分别保留可选变体；同条件互斥时展示选择，不擅自平均。可用原图缺失时标明，不重建被删除成品，也不声称已经看过。流量和新近只能提供线索，不能单独证明应修改技能。

输出完整候选 `prompt`、`reason`、真实 `evidence_refs`、`conditions`、`validation`（验证案例）；执行器绑定冻结的 `skill_id` 和 `base_version`。无修改时返回 `changed=false` 与依据。执行器仅将结果存为候选并展示前后差异，不能直接写规范、发布技能、改变画像默认或制作内容。用户可只试一篇；确认发布并指定范围后才影响后续任务。

## Easel 项目执行边界

读取[本地生产合同](../../shared/workbench/production-contract.md)及本次资源清单。历史索引、旧操作及脚本快照仅作来源证据，不执行其命令、不扫描外项目；任务实际材料和反馈以冻结输入为准。

