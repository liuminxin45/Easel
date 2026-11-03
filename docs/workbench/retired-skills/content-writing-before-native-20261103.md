---
name: content-writing
description: "制作或修改贴图标题配文与长文章，保留原话、事实和明确修改范围。当用户需要图文写作时使用，读取本项目已选择的画像、版本和冻结材料；只处理明确任务范围，候选、反馈和发布授权分别保存，不把旧任务按当前目录重解释。"
layer: produce
metadata:
  openclaw:
    workbench: {"id":"content-writing","tasks":["poster","article","change"],"executor":"agent","input_contract":{"required":["task","materials","profile","frozen_prompt"],"optional":["version","annotations","locked_text","reference_variant"]},"output_contract":{"required":["title","body","sources","design_response"],"prohibits":["虚构原话","把AI自评当采纳","改写锁定原字"]},"acceptance_cases":["配文修改与标题保留分别生效","两种相反风格按本轮选择使用","固定Tech Pulse仅在明确选择时采用"],"schema_version":1,"display_name":"图文写作","resources":[{"path":"skills/shared/workbench/规范/写作要求.md","kind":"reference","scope":"on-demand"},{"path":"skills/shared/workbench/规范/公众号贴图写作要求.md","kind":"reference","scope":"on-demand"},{"path":"skills/shared/workbench/provenance/.agents/skills/neo-content/references/文章生产.md","kind":"legacy_operation","scope":"on-demand","executable":false,"historical":true},{"path":"skills/shared/workbench/provenance/.agents/skills/neo-content/references/贴图生产.md","kind":"legacy_operation","scope":"on-demand","executable":false,"historical":true},{"path":"skills/shared/workbench/规范/创作方案/目录.json","kind":"contract","scope":"on-demand"},{"path":"skills/shared/workbench/production-contract.md","kind":"contract","scope":"on-demand","required":true}],"source":{"registry_path":".agents/skills/capabilities.json","registry_sha256":"014bafced32c43692d7d6eb25b5f00216f45e18676f9c6f4b23837845a1079e8","entry_path":".agents/skills/neo-content-writing/SKILL.md","entry_sha256":"10592a68f9fb70353b62a41b7576ad9d09c50fc792081e9f8327fe0f939a34e7"},"migration":{"kind":"project_builtin_mechanical","published_style_change":false}}
---

# 图文写作

以冻结的本轮指令为制作合同，先确认内容类型、目标读者、核心问题、原始材料、准确所改版本与文字范围。修改标题、修改配文、只配图分别处理；锁定原字须逐字保留，不能因整体风格变化改写用户文本。

通用文字要求读取项目 `../../shared/workbench/规范/写作要求.md`；贴图按需读取 `../../shared/workbench/规范/公众号贴图写作要求.md` 和 `../../shared/workbench/production-contract.md`，长文读取 `../../shared/workbench/production-contract.md`。定位由当前画像提供，默认油猪大侠沿用现行定位原件。候选参考与历史反馈遵守自身适用范围，不转成无条件禁令。

标题承诺必须由正文和图片兑现；以材料支持具体变化、解释、体验或判断，不编造经历、来源和数据。用户选择固定 Tech Pulse 才加载对应母版与固定工作流，不能将固定栏目计数套给普通主题。

输出实际标题、配文或正文及来源，按准确依据 ID 提供设计回应，指向成品中的真实位置。成品之外保存提示词、反馈来源及版本；不以模型自评替用户采纳。长文交付前归档，贴图按明确采纳决定归档；授权范围继续由主工作流检查。

## Easel 项目执行边界

读取[本地生产合同](../../shared/workbench/production-contract.md)及本次资源清单。历史索引、旧操作及脚本快照仅作来源证据，不执行其命令、不扫描外项目；任务实际材料和反馈以冻结输入为准。

