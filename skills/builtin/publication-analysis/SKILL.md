---
name: publication-analysis
description: "解释准确发布实例的数据与读者反馈，输出有依据的下一步建议。当用户需要发布复盘时使用，读取本项目已选择的画像、版本和冻结材料；只处理明确任务范围，候选、反馈和发布授权分别保存，不把旧任务按当前目录重解释。"
layer: attribute
metadata:
  openclaw:
    workbench: {"id":"publication-analysis","tasks":["analysis"],"executor":"agent","input_contract":{"required":["publication_id","snapshots","sources"],"optional":["comments","comparable_window","skill_versions","user_feedback"]},"output_contract":{"required":["observations","reader_value","suggestions","limitations"],"prohibits":["伪造指标","混连不同统计口径","自动发布或回复","自动改长期默认"]},"acceptance_cases":["24h与7d窗口分别比较","不同主题非随机分流只称观察比较","数据缺失显示未取得"],"schema_version":1,"display_name":"发布复盘","resources":[{"path":"skills/shared/workbench/规范/发布与归档要求.md","kind":"reference","scope":"on-demand"},{"path":"skills/shared/workbench/production-contract.md","kind":"contract","scope":"on-demand","required":true}],"source":{"registry_path":".agents/skills/capabilities.json","registry_sha256":"014bafced32c43692d7d6eb25b5f00216f45e18676f9c6f4b23837845a1079e8","entry_path":".agents/skills/neo-publication-analysis/SKILL.md","entry_sha256":"e260e736afb9e9267d8689408fa7f9b284473f5f5337837df6d993a1cba37c92"},"migration":{"kind":"project_builtin_mechanical","published_style_change":false}}
---

# 发布复盘

输入绑定实际发布实例、平台账号、内容版本、统计时间与来源。指标计算、同口径分组、趋势计算和去重由程序完成，本能力解释程序结果与原始读者反馈。缺失显示未取得，未知发布时间不生成24小时或7天比较。

平台分别分析，只有指标口径和观察窗口可比时对照。没有曝光分母不计算点击率，没有对应证据不编造读完率；非随机分流的不同主题内容只称观察比较，不宣布流量赢家或技能因果效果。

归纳原评论中的认可、问题、误解、纠错及后续需求，能回看原话与内容位置。分别讨论内容是否兑现承诺、是否符合目标读者、制作返工与传播观察，不合成虚构风格总分。

输出有来源的观察、限制及可采取的下一步，可建议选题、作品修改或技能修订。建议不等于授权；不自动发布、回复、重做作品或改写长期技能。长期调整通过技能差异、明确范围及用户确认生效。

## Easel 项目执行边界

读取[本地生产合同](../../shared/workbench/production-contract.md)及本次资源清单。历史索引、旧操作及脚本快照仅作来源证据，不执行其命令、不扫描外项目；任务实际材料和反馈以冻结输入为准。

