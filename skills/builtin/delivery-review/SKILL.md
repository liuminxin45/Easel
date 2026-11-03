---
name: delivery-review
description: "只读检查用户指定的实际文本和图片，说明可复核问题与限制，不替用户采纳或发布。"
layer: general
metadata:
  openclaw:
    workbench: {"id":"delivery-review","tasks":["review","poster","article","change"],"executor":"readonly-agent","input_contract":{"required":["user_input"],"optional":["persona","attachments","source_files"]},"output_contract":{"required":["actual_result"],"optional":["output_paths"]},"acceptance_cases":["通过 Easel 原生技能调用执行","核对真实产物与原文，不伪造用户采纳或平台发布"],"schema_version":1,"display_name":"交付核验","resources":[{"path":"skills/shared/workbench/规范/模板/创作检查-v1.json","kind":"contract","scope":"on-demand"},{"path":"skills/shared/workbench/规范/模板/设计说明-v2.md","kind":"contract","scope":"on-demand"},{"path":"skills/shared/workbench/provenance/工具/内容工作流/creative_review.py.txt","kind":"legacy_script","scope":"on-demand","executable":false,"historical":true},{"path":"skills/shared/workbench/.agents/skills/neo-delivery-review/references/independent-check.md","kind":"contract","scope":"on-demand"},{"path":"skills/shared/workbench/production-contract.md","kind":"contract","scope":"on-demand","required":true},{"path":"skills/builtin/delivery-review/scripts/check_deliverables.py","kind":"script","scope":"on-demand"}],"source":{"registry_path":".agents/skills/capabilities.json","registry_sha256":"014bafced32c43692d7d6eb25b5f00216f45e18676f9c6f4b23837845a1079e8","entry_path":".agents/skills/neo-delivery-review/SKILL.md","entry_sha256":"8832123f5576cdeac7d2310199e839e94ef8e8a0acfc2416f7c867fea118ef2b"},"migration":{"kind":"project_builtin_mechanical","published_style_change":false},"execution_model":"easel-native"}
---

# 交付核验

本能力只读，不能修改成品、接受作品、发布、回复用户或更新长期规则。输入为用户指定的原文件、本轮要求及实际交付清单；先确认可读取实际成品，先检查文件存在、可读及原文一致性；缺少材料时说明具体限制，不假定有私有服务替你验证。

按本轮要求检查标题、正文、各图分工、事实与视觉关系。读取实际图片及文本，指出每条问题所用依据 ID、原字引文或画面区域、具体发现、证据和置信限制；无法判断时标未核验，不用制作方自述代替观察。

设计说明合同按需读取 `../../shared/workbench/规范/模板/设计说明-v2.md`，标题与配图检查使用项目现行检查合同。制作方声明、程序结果、独立观察、人类评价分别保留，检查通过不等于用户认可。

可确定的问题允许制作方沿本轮要求修正并保留记录，保留前后文件及原因；检查过程本身不能直接写入。只缺说明时补说明，不重画。剩余主观分歧交给用户；客观交付缺失必须补齐，未知回执不得以修正为由重放。

程序前置字节检查可运行 `scripts/check_deliverables.py`；它不判断语义、审美或用户采纳，也不访问模型、网络或业务数据库。


## Easel 原生调用

本技能通过官方“技能名＋用户输入＋画像”执行。按需读取 [项目内容工作流](../../shared/workbench/production-contract.md) 与实际使用的参考文件，不要求私有制作计划、技能候选、试用版本或业务服务回执。产物写入 outputs/；多步骤按官方 manifest.py 传递文件路径。历史资源仅作来源依据，不执行旧私有API或外项目脚本。用户未要求时，不整理经验、不修改长期技能或画像，不采纳或发布。
