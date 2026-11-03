---
name: publication-analysis
description: "根据实际发布内容、统计窗口和读者反馈进行复盘，不编造指标或自动改变长期规则。"
layer: attribute
metadata:
  openclaw:
    workbench: {"id":"publication-analysis","tasks":["analysis"],"executor":"agent","input_contract":{"required":["user_input"],"optional":["persona","attachments","source_files"]},"output_contract":{"required":["actual_result"],"optional":["output_paths"]},"acceptance_cases":["通过 Easel 原生技能调用执行","核对真实产物与原文，不伪造用户采纳或平台发布"],"schema_version":1,"display_name":"发布复盘","resources":[{"path":"skills/shared/workbench/规范/发布与归档要求.md","kind":"reference","scope":"on-demand"},{"path":"skills/shared/workbench/production-contract.md","kind":"contract","scope":"on-demand","required":true}],"source":{"registry_path":".agents/skills/capabilities.json","registry_sha256":"014bafced32c43692d7d6eb25b5f00216f45e18676f9c6f4b23837845a1079e8","entry_path":".agents/skills/neo-publication-analysis/SKILL.md","entry_sha256":"e260e736afb9e9267d8689408fa7f9b284473f5f5337837df6d993a1cba37c92"},"migration":{"kind":"project_builtin_mechanical","published_style_change":false},"execution_model":"easel-native"}
---

# 发布复盘

输入绑定实际发布实例、平台账号、内容版本、统计时间与来源。指标计算、同口径分组、趋势计算和去重由程序完成，本能力解释程序结果与原始读者反馈。缺失显示未取得，未知发布时间不生成24小时或7天比较。

平台分别分析，只有指标口径和观察窗口可比时对照。没有曝光分母不计算点击率，没有对应证据不编造读完率；非随机分流的不同主题内容只称观察比较，不宣布流量赢家或技能因果效果。

归纳原评论中的认可、问题、误解、纠错及后续需求，能回看原话与内容位置。分别讨论内容是否兑现承诺、是否符合目标读者、制作返工与传播观察，不合成虚构风格总分。

输出有来源的观察、限制及可采取的下一步，可建议选题、作品修改或技能修订。建议不等于授权；不自动发布、回复、重做作品或改写长期技能。长期调整须有用户单独明确要求，本技能不创建或发布私有候选。

## Easel 原生调用

本技能通过官方“技能名＋用户输入＋画像”执行。按需读取 [项目内容工作流](../../shared/workbench/production-contract.md) 与实际使用的参考文件，不要求私有制作计划、技能候选、试用版本或业务服务回执。产物写入 outputs/；多步骤按官方 manifest.py 传递文件路径。历史资源仅作来源依据，不执行旧私有API或外项目脚本。用户未要求时，不整理经验、不修改长期技能或画像，不采纳或发布。
