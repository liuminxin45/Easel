---
name: delivery-review
description: "在程序完成字节、ID与原字检查后，只读核查实际成品的语义和视觉。当用户需要交付核验时使用，读取本项目已选择的画像、版本和冻结材料；只处理明确任务范围，候选、反馈和发布授权分别保存，不把旧任务按当前目录重解释。"
layer: general
metadata:
  openclaw:
    workbench: {"id":"delivery-review","tasks":["review","poster","article","change"],"executor":"readonly-agent","input_contract":{"required":["frozen_requirements","artifact_manifest","actual_artifacts"],"optional":["program_checks","previous_observation"]},"output_contract":{"required":["observations","evidence","unverified"],"prohibits":["写入成品","自行采纳","用制作方自述代替看图"]},"acceptance_cases":["文件缺失交程序处理且不调用模型","伪造依据ID不能通过","无法判断时标未核验","明确问题内部修改最多一次"],"schema_version":1,"display_name":"交付核验","resources":[{"path":"skills/shared/workbench/规范/模板/创作检查-v1.json","kind":"contract","scope":"on-demand"},{"path":"skills/shared/workbench/规范/模板/设计说明-v2.md","kind":"contract","scope":"on-demand"},{"path":"skills/shared/workbench/provenance/工具/内容工作流/creative_review.py.txt","kind":"legacy_script","scope":"on-demand","executable":false,"historical":true},{"path":"skills/shared/workbench/.agents/skills/neo-delivery-review/references/independent-check.md","kind":"contract","scope":"on-demand"},{"path":"skills/shared/workbench/production-contract.md","kind":"contract","scope":"on-demand","required":true},{"path":"skills/builtin/delivery-review/scripts/check_deliverables.py","kind":"script","scope":"on-demand"}],"source":{"registry_path":".agents/skills/capabilities.json","registry_sha256":"014bafced32c43692d7d6eb25b5f00216f45e18676f9c6f4b23837845a1079e8","entry_path":".agents/skills/neo-delivery-review/SKILL.md","entry_sha256":"8832123f5576cdeac7d2310199e839e94ef8e8a0acfc2416f7c867fea118ef2b"},"migration":{"kind":"project_builtin_mechanical","published_style_change":false}}
---

# 交付核验

本能力只读，不能修改成品、接受作品、发布、回复用户或更新长期规则。输入须含准确版本、冻结依据、实际交付清单及程序检查；先确认可读取实际成品，缺文件、错路径、解码失败、错误 SHA、伪造 ID 和锁定原字不符由程序拦截，不发送无意义模型核验。

按冻结要求检查标题、正文、各图分工、事实与视觉关系。读取实际图片及文本，指出每条问题所用依据 ID、原字引文或画面区域、具体发现、证据和置信限制；无法判断时标未核验，不用制作方自述代替观察。

设计说明合同按需读取 `../../shared/workbench/规范/模板/设计说明-v2.md`，标题与配图检查使用项目现行检查合同。制作方声明、程序结果、独立观察、人类评价分别保留，检查通过不等于用户认可。

可确定的问题允许生产执行端沿冻结输入内部修正一次，保留前后文件及原因；检查过程本身不能直接写入。只缺说明时补说明，不重画。剩余主观分歧交给用户；客观交付缺失必须补齐，未知回执不得以修正为由重放。

程序前置字节检查可运行 `scripts/check_deliverables.py`；它不判断语义、审美或用户采纳，也不访问模型、网络或业务数据库。


## Easel 项目执行边界

读取[本地生产合同](../../shared/workbench/production-contract.md)及本次资源清单。历史索引、旧操作及脚本快照仅作来源证据，不执行其命令、不扫描外项目；任务实际材料和反馈以冻结输入为准。

