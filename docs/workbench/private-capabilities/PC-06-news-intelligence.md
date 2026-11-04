# PC-06 新闻摘要、中文标题与原始反馈

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

- **状态：** 已确认保留；类型：私有业务。
- **需求依据：** 用户要求 HN/PH 一句话中文标题，保留原新闻和反馈；没有采到的项目不显示。 依据见下方原始规则/Spec；本卡不额外授予执行、采纳或发布权限。
- **能力范围：** 新闻概览、标题增强、原文/判断区分、准确来源和反馈记录；仅在既有任务边界调用只读执行。
- **官方复用与必要差异：** 继续使用原 Dashboard/Trends 展示；共用原生只读 Agent，方法引用项目 topic-research，不另建模型客户端。
- **不可破坏的合同：** 中文标题不能退化成单词，不杜撰事实/发布时间；保留原文、原始意见；部分失败不生成固定前台警告，不自动制作或发布。

**接口与状态归属：** Overviews 维护既有 overviews/overview_sources 记录；原始反馈由 news_feedback 管理。读取使用只读执行入口，新闻状态仍以服务器任务与文章为准。

**私有入口／资源：** [easel_workbench/runtime/news_overviews.py](../../../easel_workbench/runtime/news_overviews.py)、[easel_workbench/runtime/news_feedback.py](../../../easel_workbench/runtime/news_feedback.py)、[easel_workbench/readonly_runner.py](../../../easel_workbench/readonly_runner.py)

**官方复用／共通接缝：** [web/frontend/src/components/TrendsPage.tsx](../../../web/frontend/src/components/TrendsPage.tsx)、[web/frontend/src/components/DashboardPage.tsx](../../../web/frontend/src/components/DashboardPage.tsx)、[easel/harnesses/codex.py](../../../easel/harnesses/codex.py)

**验证入口：** [tests/test_workbench_chinese_trend_titles.py](../../../tests/test_workbench_chinese_trend_titles.py)、[tests/test_workbench_collection_partial_diagnostics.py](../../../tests/test_workbench_collection_partial_diagnostics.py)

**需求与设计记录：** [specs/chinese-trend-titles-20261103/spec.md](../../../specs/chinese-trend-titles-20261103/spec.md)、[specs/functional-health-20261103/spec.md](../../../specs/functional-health-20261103/spec.md)

**后续维护：** 变更时先核对上述调用链与当前官方实现；优先共用、缩小上游补丁。同步维护本卡的范围、入口、共通差异及验证依据；被上游吸收时移除对应适配并更新登记状态。原方法、历史输入和交付证据不在本卡复制或改写。

**登记记录：** 2026-11-05 按业务源码 `1901f83` 建立首版；本次只读盘点及文档登记，未新增启用能力，未逐项重新执行产品验收。
