---
name: reference-analysis
description: "从具体文章和图片解释可学习的方法、适用条件与不能照搬的部分。当用户需要参考拆解时使用，读取本项目已选择的画像、版本和冻结材料；只处理明确任务范围，候选、反馈和发布授权分别保存，不把旧任务按当前目录重解释。"
layer: plan
metadata:
  openclaw:
    workbench: {"id":"reference-analysis","tasks":["reference"],"executor":"agent","input_contract":{"required":["materials","learning_goal"],"optional":["profile","comparison_samples","performance_evidence"]},"output_contract":{"required":["methods","conditions","source_refs","limitations"],"prohibits":["自动改默认技能","从高阅读量推出因果","复制他人经历"]},"acceptance_cases":["单例只标观察","相反优秀样本按条件共存","缺少曝光分母不计算CTR"],"schema_version":1,"display_name":"参考拆解","resources":[{"path":"skills/shared/workbench/provenance/.agents/skills/neo-content/references/文章学习.md","kind":"legacy_operation","scope":"on-demand","executable":false,"historical":true},{"path":"skills/shared/workbench/资料/风格研究/样本索引.md","kind":"historical_index","scope":"on-demand","executable":false,"historical":true},{"path":"skills/shared/workbench/.agents/skills/neo-reference-analysis/references/reference-observation.md","kind":"contract","scope":"on-demand"},{"path":"skills/shared/workbench/production-contract.md","kind":"contract","scope":"on-demand","required":true}],"source":{"registry_path":".agents/skills/capabilities.json","registry_sha256":"014bafced32c43692d7d6eb25b5f00216f45e18676f9c6f4b23837845a1079e8","entry_path":".agents/skills/neo-reference-analysis/SKILL.md","entry_sha256":"366d5becdb31bdb4d7d409aeb3e25aac96dfbe425868022eecba213e3934b344"},"migration":{"kind":"project_builtin_mechanical","published_style_change":false}}
---

# 参考拆解

读取用户指定样本及想学习的部分，区分实际取得的全文、图片与局部片段。按需读取 `../../shared/workbench/production-contract.md`；样本身份、来源、原话、附件和局部认可范围保持准确。

分析标题如何建立阅读动机，封面怎样传递信息，正文如何兑现承诺，页面间如何分工；指出能复用的方法、适用主题、与当前画像的关系、不能照搬的内容及证据不足。建议绑定具体样本位置，不能只给抽象赞美或主观分数。

两套效果好的相反风格可分别保留。先区分条件不同、可以组合、同条件互斥或证据不足；不能根据新旧、星数或流量自行覆盖。没有随机分流和可比观察窗口，只称观察比较；缺曝光分母不计算点击率。

输出带来源的方法候选和可验证的尝试，不擅自更新长期提示词、画像、默认风格或新建制作任务。需要沉淀技能时交由用户按需发起经验提炼，再用实际差异评审。

## Easel 项目执行边界

读取[本地生产合同](../../shared/workbench/production-contract.md)及本次资源清单。历史索引、旧操作及脚本快照仅作来源证据，不执行其命令、不扫描外项目；任务实际材料和反馈以冻结输入为准。

