---
name: reference-analysis
description: "油猪·参考拆解：分析用户指定样本的标题、封面、结构与方法；适用于研究可借鉴的写法，不自动修改技能、画像或创建作品。"
layer: plan
metadata:
  openclaw:
    workbench: {"id":"reference-analysis","tasks":["reference"],"executor":"agent","input_contract":{"required":["user_input"],"optional":["persona","attachments","source_files"]},"output_contract":{"required":["actual_result"],"optional":["output_paths"]},"acceptance_cases":["通过 Easel 原生技能调用执行","核对真实产物与原文，不伪造用户采纳或平台发布"],"schema_version":1,"display_name":"油猪·参考拆解","resources":[{"path":"skills/shared/workbench/provenance/.agents/skills/neo-content/references/文章学习.md","kind":"legacy_operation","scope":"on-demand","executable":false,"historical":true},{"path":"skills/shared/workbench/资料/风格研究/样本索引.md","kind":"historical_index","scope":"on-demand","executable":false,"historical":true},{"path":"skills/shared/workbench/.agents/skills/neo-reference-analysis/references/reference-observation.md","kind":"contract","scope":"on-demand"},{"path":"skills/shared/workbench/production-contract.md","kind":"contract","scope":"on-demand","required":true}],"source":{"registry_path":".agents/skills/capabilities.json","registry_sha256":"014bafced32c43692d7d6eb25b5f00216f45e18676f9c6f4b23837845a1079e8","entry_path":".agents/skills/neo-reference-analysis/SKILL.md","entry_sha256":"366d5becdb31bdb4d7d409aeb3e25aac96dfbe425868022eecba213e3934b344"},"migration":{"kind":"project_builtin_mechanical","published_style_change":false},"execution_model":"easel-native"}
---

# 油猪·参考拆解

## 适用场景与边界

参考拆解：分析用户指定样本的标题、封面、结构与方法；适用于研究可借鉴的写法，不自动修改技能、画像或创建作品。

## 当前画像

使用本次会话选择的 Easel 画像确定身份、读者与表达方式；本轮明确要求优先。只有完成本次任务所需的画像信息缺失或与关键要求冲突时才询问，不猜测账号、授权或默认风格。

## 输入

指定样本、来源和希望学习的问题；全文、图片或片段的实际可得范围需明确。

## 执行流程


读取用户指定样本及想学习的部分，区分实际取得的全文、图片与局部片段。按需读取 `../../shared/workbench/production-contract.md`；样本身份、来源、原话、附件和局部认可范围保持准确。

分析标题如何建立阅读动机，封面怎样传递信息，正文如何兑现承诺，页面间如何分工；指出能复用的方法、适用主题、与当前画像的关系、不能照搬的内容及证据不足。建议绑定具体样本位置，不能只给抽象赞美或主观分数。

两套效果好的相反风格可分别保留。先区分条件不同、可以组合、同条件互斥或证据不足；不能根据新旧、星数或流量自行覆盖。没有随机分流和可比观察窗口，只称观察比较；缺曝光分母不计算点击率。

输出带来源的方法候选和可验证的尝试，不擅自更新长期提示词、画像、默认风格或新建制作任务。如用户另行要求调整技能，按原生项目文件维护流程提出明确建议；本次拆解不自动更新技能。

## 输出与核验

带样本位置与来源的观察、适用条件、可验证尝试及证据不足之处。

## Easel 原生调用

本技能通过官方“技能名＋用户输入＋画像”执行。按需读取 [项目内容工作流](../../shared/workbench/production-contract.md) 与实际使用的参考文件，不要求私有制作计划、技能候选、试用版本或业务服务回执。产物写入 outputs/；多步骤按官方 manifest.py 传递文件路径。历史资源仅作来源依据，不执行旧私有API或外项目脚本。用户未要求时，不整理经验、不修改长期技能或画像，不采纳或发布。
