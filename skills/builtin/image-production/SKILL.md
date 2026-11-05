---
name: image-production
description: "配图设计与生成：按照主题、尺寸、画面要求和参考素材制作或修改图片；适用于明确的图片任务，不代替文章写作或发布。"
layer: produce
metadata:
  openclaw:
    workbench: {"id":"image-production","tasks":["poster","image","change","article"],"executor":"agent","input_contract":{"required":["user_input"],"optional":["persona","attachments","source_files"]},"output_contract":{"required":["actual_result"],"optional":["output_paths"]},"acceptance_cases":["通过 Easel 原生技能调用执行","核对真实产物与原文，不伪造用户采纳或平台发布"],"schema_version":1,"display_name":"配图设计与生成","resources":[{"path":"skills/shared/workbench/规范/图片制作要求.md","kind":"reference","scope":"on-demand"},{"path":"skills/shared/workbench/规范/模板/油猪大侠角色库.md","kind":"reference","scope":"on-demand"},{"path":"skills/shared/workbench/规范/模板/TechPulse-图生-v1/模板.json","kind":"contract","scope":"on-demand"},{"path":"skills/shared/workbench/规范/模板/TechPulse-图生-v1/风格说明.md","kind":"reference","scope":"on-demand"},{"path":"skills/shared/workbench/provenance/工具/内容工作流/poster_imagegen.py.txt","kind":"legacy_script","scope":"on-demand","executable":false,"historical":true},{"path":"skills/shared/workbench/production-contract.md","kind":"contract","scope":"on-demand","required":true}],"source":{"registry_path":".agents/skills/capabilities.json","registry_sha256":"014bafced32c43692d7d6eb25b5f00216f45e18676f9c6f4b23837845a1079e8","entry_path":".agents/skills/neo-image-production/SKILL.md","entry_sha256":"b65468ee7062278b157bf5f6e3075c5b18feabb92fd5b89c0a0a8916b7db1520"},"migration":{"kind":"project_builtin_mechanical","published_style_change":false},"execution_model":"easel-native"}
---

# 配图设计与生成

## 适用场景与边界

配图设计与生成：按照主题、尺寸、画面要求和参考素材制作或修改图片；适用于明确的图片任务，不代替文章写作或发布。

## 当前画像

使用本次会话选择的 Easel 画像确定身份、读者与表达方式；本轮明确要求优先。只有完成本次任务所需的画像信息缺失或与关键要求冲突时才询问，不猜测账号、授权或默认风格。

## 输入

主题、用途、尺寸及本轮画面要求；角色、风格和参考图片按用户选择或明确绑定的画像提供。关键条件缺失时询问。

## 执行流程


输入为本次目标、明确选择的视觉变体、逐图分工、准确参考原件、尺寸及文字锁定要求。先核对参考存在与指纹；原字、事实、尺寸、真实文件与工具证据要求适用于所有画像。`../../shared/workbench/规范/图片制作要求.md` 中油猪大侠的角色、水印、场景偏好及栏目母版属于该画像或明确选中的视觉变体，不能因读取通用技能而套给其他画像。资源清单是可选目录，不等于本轮全部采用。

仅当前画像明确绑定或本轮明确选择小猪资产时，按需读取 `../../shared/workbench/规范/模板/油猪大侠角色库.md`，保留所选身份和红围巾；可以按主题使用色彩、光线和环境色，不重做历史角色资产。其他画像使用自身明确绑定的角色和署名，未提供时不自动使用油猪大侠角色、水印或个人风格。仅明确选择固定 Tech Pulse 时，使用其已认可图生母版，不能用普通视觉切换或 HTML 截图替换。

普通制作直接完成逐图分工与生成；用户选择先准备图稿方案时，只提交逐张提示词、参考、尺寸和目的，确认后才生成。每张实际交付绑定 `生图执行记录.json`：完整提示词、真实参考及 SHA、尺寸、工具名、成品文件及 SHA。

文章加载本能力是为了在需要配图时使用对应参考和制作方法，不代表已经调用生图工具。只有本轮要求或明确文章交付合同需要图片时才生成；没有实际工具事件与成品就不记录“已生图”。可用官方原件、真实截图和自制图按本轮用途区分。

准备方案、制作方记录、实际工具事件是不同证据。没有真实结构化工具事件，只能声明制作方提交，不能自我升级“工具入参已核实”。查看实际成品后提交图片及设计说明；发现缺字、错页或错误资产按生产合同处理，不擅自变更锁定文案、发布或采纳。

## 输出与核验

交付实际生成或修改的图片及路径，报告真实工具、参考与检查结果；无法生成时说明缺口。

## Easel 原生调用

本轮新闻创作材料若提供角色身份参考图，应实际查看附件并在可用生图工具的参考图片参数中使用这些文件，不能仅在文字中提到角色名称。以本轮附件的真实路径和SHA为准，保留工具实际采用的参考与成品记录；选择文章配图风格不等于要求立即生图，仍按用户明确要求与本轮交付需要执行。

本技能通过官方“技能名＋用户输入＋画像”执行。按需读取 [项目内容工作流](../../shared/workbench/production-contract.md) 与实际使用的参考文件，不要求私有制作计划、技能候选、试用版本或业务服务回执。产物写入 outputs/；多步骤按官方 manifest.py 传递文件路径。历史资源仅作来源依据，不执行旧私有API或外项目脚本。用户未要求时，不整理经验、不修改长期技能或画像，不采纳或发布。
