---
name: content-production
description: "把选题与素材制作成贴图配文或文章，支持讨论、改稿、看稿和归档。当用户需要内容生产时使用，读取本项目已选择的画像、版本和冻结材料；只处理明确任务范围，候选、反馈和发布授权分别保存，不把旧任务按当前目录重解释。"
layer: produce
metadata:
  openclaw:
    workbench: {"id":"content-production","tasks":["poster","article","change"],"executor":"agent","input_contract":{"required":["creator_profile","format","materials","frozen_instruction","skill_versions"]},"output_contract":{"required":["actual_deliverables","version","feedback","execution_receipts"]},"acceptance_cases":["贴图与文章进入原服务且冻结准确技能版本","修改继承父版，未知回执不重放","本入口不新增匿名模型调用"],"schema_version":1,"display_name":"内容生产","resources":[{"path":"skills/shared/workbench/production-contract.md","kind":"contract","scope":"on-demand","required":true}],"composition":{"requires":["content-writing","image-production","delivery-review"],"role":"production"},"source":{"registry_path":".agents/skills/capabilities.json","registry_sha256":"014bafced32c43692d7d6eb25b5f00216f45e18676f9c6f4b23837845a1079e8","entry_path":".agents/skills/content-production/SKILL.md","entry_sha256":"9706888490c1ee01fff2b8831384d0434754a948f766eac8c5d95b92541a3568"},"migration":{"kind":"project_builtin_mechanical","published_style_change":false}}
---

# 内容生产

本技能是实际执行贴图和文章生产的根技能，读取本次已冻结的子技能与资源，按正文步骤完成制作，不复制文风、图片规范或平台规则。能力唯一登记在各本地内置技能的 `metadata.openclaw.workbench`；使用随任务冻结的版本，旧作品仍沿用准确父版。

## 执行

1. 核对目标、格式、画像、材料及准确来源，实际读取任务附带的图文写作与配图技能版本；独立交付核验技能由业务 hook 在成品后只读执行，制作方不能代替它自证。
2. 使用服务已确认并冻结的可读方案和准确输入；收到已受理任务后直接执行，不重复询问确认、不重新解析当前默认版本，重试沿原输入。
3. 讨论只讨论；贴图输出实际图片和标题配文，文章输出真实正文及所需配图。按既有规范保留制作计划、工具记录和成品文件。
4. 修改另存版本，继承准确父版的画像、技能和原始反馈。配图与文字范围按本次明确要求，不重新解释旧输入。
5. 程序交付检查与独立语义视觉检查沿原工作流执行。采纳、不采纳、普通反馈和归档决定直接写本地事务，不另开模型回合。
6. 交付仅按准确版本、账号和本次授权执行。未知回执先核对，不重放。

## 子技能与唯一来源

- 写作方法与正文规范：相邻目录 `../content-writing/SKILL.md` 及其已冻结资源。
- 配图方法与真实工具：`../image-production/SKILL.md` 及其已冻结资源。
- 独立核验：`../delivery-review/SKILL.md`，不能由制作方声明代替。
- 总体交接：`../../shared/workbench/production-contract.md` 与工作台交接引用。

本根技能必须被实际制作回合加载，回执绑定根技能及使用的准确子技能版本。编排步骤在本技能中定义，版本冻结、事务、幂等与独立检查交给业务服务；不能把目录登记冒充技能执行。没有真实交付不能标记完成，页面按钮和技能文件存在也不构成执行证据。

## Easel 项目执行边界

读取[本地生产合同](../../shared/workbench/production-contract.md)及本次资源清单。历史索引、旧操作及脚本快照仅作来源证据，不执行其命令、不扫描外项目；任务实际材料和反馈以冻结输入为准。

