---
name: oil-pig-learn-article
description: "油猪·学习文章：阅读用户指定文章，分析结构、语言与读者切入点；只学习，不自动写稿或修改规范。"
layer: plan
metadata:
  openclaw:
    workbench: {"id":"oil-pig-learn-article","tasks":["reference"],"executor":"agent","input_contract":{"required":["user_input"],"optional":["persona","attachments","source_files"]},"output_contract":{"required":["actual_result"]},"acceptance_cases":["说明文章和媒体实际阅读范围","学习不触发写稿或修改规范"],"schema_version":1,"display_name":"油猪·学习文章","resources":[]}
---

# 油猪·学习文章

## 适用范围与画像

用户明确要求学习、分析或拆解指定文章时使用。参考本次选择的 Easel 画像与读者；不假设样本观点已经获得认可。

## 输入与流程

用户提供链接时优先用可用的内置浏览器打开并阅读正文和可见媒体；若登录、验证或加载失败，说明实际阻碍，不把片段说成全文。记录来源、作者、可见范围；分析文章要回答的读者问题、标题、开头、结构推进、论证、例子和语言。引用或定位实际段落，区分作者观点、可核验事实和自己的推断，不把借鉴表达方式变成照搬事实或立场。

## 输出与边界

给出带具体依据的方法、适用条件和阅读限制。只学习，不自动写稿、修改技能或规范、更新画像、发布、归档或提交。长期规则变更需用户明确决定，保留原文和反馈。
