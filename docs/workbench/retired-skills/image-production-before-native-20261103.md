---
name: image-production
description: "按冻结参考与逐图分工生成实际图片；保存逐图提示词、原图和真实工具证据。当用户需要配图设计与生成时使用，读取本项目已选择的画像、版本和冻结材料；只处理明确任务范围，候选、反馈和发布授权分别保存，不把旧任务按当前目录重解释。"
layer: produce
metadata:
  openclaw:
    workbench: {"id":"image-production","tasks":["poster","image","change","article"],"executor":"agent","input_contract":{"required":["goal","frozen_prompt","references"],"optional":["image_plan","fixed_master","locked_text","character"]},"output_contract":{"required":["artifacts","image_records","design_response"],"prohibits":["声称未取得的工具调用已核实","替换固定母版","未经授权重画历史图片"]},"acceptance_cases":["角色原图缺失时如实说明","逐图记录与交付文件指纹对应","场景风格与排字风格分开试用"],"schema_version":1,"display_name":"配图设计与生成","resources":[{"path":"skills/shared/workbench/规范/图片制作要求.md","kind":"reference","scope":"on-demand"},{"path":"skills/shared/workbench/规范/模板/油猪大侠角色库.md","kind":"reference","scope":"on-demand"},{"path":"skills/shared/workbench/规范/模板/TechPulse-图生-v1/模板.json","kind":"contract","scope":"on-demand"},{"path":"skills/shared/workbench/规范/模板/TechPulse-图生-v1/风格说明.md","kind":"reference","scope":"on-demand"},{"path":"skills/shared/workbench/provenance/工具/内容工作流/poster_imagegen.py.txt","kind":"legacy_script","scope":"on-demand","executable":false,"historical":true},{"path":"skills/shared/workbench/production-contract.md","kind":"contract","scope":"on-demand","required":true}],"source":{"registry_path":".agents/skills/capabilities.json","registry_sha256":"014bafced32c43692d7d6eb25b5f00216f45e18676f9c6f4b23837845a1079e8","entry_path":".agents/skills/neo-image-production/SKILL.md","entry_sha256":"b65468ee7062278b157bf5f6e3075c5b18feabb92fd5b89c0a0a8916b7db1520"},"migration":{"kind":"project_builtin_mechanical","published_style_change":false}}
---

# 配图设计与生成

输入为本次目标、明确选择的视觉变体、逐图分工、准确参考原件、尺寸及文字锁定要求。先核对参考存在与指纹；原字、事实、尺寸、真实文件与工具证据要求适用于所有画像。`../../shared/workbench/规范/图片制作要求.md` 中油猪大侠的角色、水印、场景偏好及栏目母版属于该画像或明确选中的视觉变体，不能因读取通用技能而套给其他画像。资源清单是可选目录，不等于本轮全部采用。

仅当前画像明确绑定或本轮明确选择小猪资产时，按需读取 `../../shared/workbench/规范/模板/油猪大侠角色库.md`，保留所选身份和红围巾；可以按主题使用色彩、光线和环境色，不重做历史角色资产。其他画像使用自身明确绑定的角色和署名，未提供时不自动使用油猪大侠角色、水印或个人风格。仅明确选择固定 Tech Pulse 时，使用其已认可图生母版，不能用普通视觉切换或 HTML 截图替换。

普通制作直接完成逐图分工与生成；用户选择先准备图稿方案时，只提交逐张提示词、参考、尺寸和目的，确认后才生成。每张实际交付绑定 `生图执行记录.json`：完整提示词、真实参考及 SHA、尺寸、工具名、成品文件及 SHA。

文章加载本能力是为了在需要配图时使用对应参考和制作方法，不代表已经调用生图工具。只有本轮要求或明确文章交付合同需要图片时才生成；没有实际工具事件与成品就不记录“已生图”。可用官方原件、真实截图和自制图按本轮用途区分。

准备方案、制作方记录、实际工具事件是不同证据。没有真实结构化工具事件，只能声明制作方提交，不能自我升级“工具入参已核实”。查看实际成品后提交图片及设计说明；发现缺字、错页或错误资产按生产合同处理，不擅自变更锁定文案、发布或采纳。

## Easel 项目执行边界

读取[本地生产合同](../../shared/workbench/production-contract.md)及本次资源清单。历史索引、旧操作及脚本快照仅作来源证据，不执行其命令、不扫描外项目；任务实际材料和反馈以冻结输入为准。

