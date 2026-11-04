---
name: oil-pig-article
description: "油猪·做文章：研究、撰写或修改公众号文章及其按需配图和审阅稿；不用于制作贴图组。"
layer: produce
metadata:
  openclaw:
    workbench: {"id":"oil-pig-article","tasks":["article","change"],"executor":"agent","input_contract":{"required":["user_input"],"optional":["persona","attachments","source_files"]},"output_contract":{"required":["actual_result"],"optional":["output_paths"]},"acceptance_cases":["文章流程与贴图流程分开","文章按需配图，保留真实来源和修改范围"],"schema_version":1,"display_name":"油猪·做文章","resources":[{"path":"skills/builtin/oil-pig-article/references/文章生产原文.md","kind":"reference","scope":"on-demand","required":true},{"path":"skills/builtin/oil-pig-article/references/文章学习原文.md","kind":"reference","scope":"on-demand"},{"path":"skills/builtin/oil-pig-article/references/文章批注原文.md","kind":"reference","scope":"on-demand"},{"path":"skills/shared/workbench/neo-source/规范/写作要求.md","kind":"reference","scope":"on-demand","required":true},{"path":"skills/shared/workbench/neo-source/规范/公众号排版要求.md","kind":"reference","scope":"on-demand","required":true}]}
---

# 油猪·做文章

仅处理用户明确要求的公众号文章及其修改；贴图组使用油猪·做贴图，不自动启动。读取 `references/文章生产原文.md`、`../../shared/workbench/neo-source/规范/写作要求.md` 和 `../../shared/workbench/neo-source/规范/公众号排版要求.md`；按需读取文章学习、批注原文和对应规范。原文是从 neo-content 原样保存的业务依据；其中旧项目根、工作台 API、归档、自动同步与命令不能直接当成 Easel 可执行路径。当前项目的授权和原生输出路径优先。

确定读者、核心问题、来源与事实边界；区分亲历、原作者陈述和解释。结合本篇题材选择相关参考与结构，不机械套固定栏目；完整稿已获请求时直接完成，不强制中途停在提纲。保留用户锁定原字、原始反馈和修改前后，不虚构经历或实测。文章按需配图，不自动做贴图组，不套用贴图配文字数限制。

完整公众号文章须交付正文与公众号 HTML；用户明确只要提纲或局部修改时遵守指定范围。标题位于正文复制区外，核对来源、图片和手机断行。审阅、批注与改稿须保留原始意见和准确版本；使用实际可用的审阅方式，不能把浏览器预览说成公众号后台已验证。实际检查交付文件并说明证据和限制，不把制作方自检说成独立审阅。

保存到 Easel `outputs/<具体主题>/` 并保留来源和版本。文章、修改、用户采纳、归档和发布分别记录；发布与外部 Git 同步另按明确授权执行。原流程中的 HTML、批注或交付检查工具未实际通过时明确标为未完成，不编造回执或声明完成。

## 本项目工具

本项目适配后的原工具位于 `skills/shared/workbench/neo-tools/`。先阅读 `../../shared/workbench/neo-source/工具/内容工作流/README.md` 与 `../../shared/workbench/neo-source/工具/文章批注/README.md` 理解格式；将旧项目命令替换成本项目 `内容工作流/creative_review.py`、`内容工作流/article-check.mjs` 和 `文章批注/review.py`，作品与批注留在本项目，不调用旧工作台桥接。创作检查显式指定 `--root <项目根>`，文章校验绑定真实 HTML、配图及对应版本；程序检查与独立目视、公众号后台粘贴分别报告。文章批注服务仅监听服务器本机，手机不能把它当作已可访问的地址；未验证远程审阅时明确说明。Node Playwright 安装在项目 `.runtime/neo-poster-tools`；需要时运行 `python scripts/install_oil_pig_tools.py`，缺失或安装失败时如实报告。
