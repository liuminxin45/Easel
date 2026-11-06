# PC-06 新闻摘要、中文标题与原始反馈

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

**实际公共文件差异：** 见 [共通源码逐文件台账](../SHARED-SOURCE-CHANGES.md)，按 `PC-06` 查询实际关联路径、修改理由与同步核对点；纯复用或开发维护项不据此新增官方改动。

- **状态：** 已确认保留；类型：私有业务。
- **需求依据：** 用户要求 HN/PH 一句话中文标题，保留原新闻和反馈；没有采到的项目不显示。 依据见下方原始规则/Spec；本卡不额外授予执行、采纳或发布权限。
- **能力范围：** 新闻概览、标题增强、原文/判断区分、准确来源和反馈记录；仅在既有任务边界调用只读执行。
- **官方复用与必要差异：** 继续使用原 Dashboard/Trends 展示；共用原生只读 Agent，方法来自私有后台新闻合同，不依赖用户技能，不另建模型客户端。
- **不可破坏的合同：** 中文标题不能退化成单词，不杜撰事实/发布时间；保留原文、原始意见；部分失败不生成固定前台警告，不自动制作或发布。

**接口与状态归属：** Overviews 维护既有 overviews/overview_sources 记录；原始反馈由 news_feedback 管理。读取使用只读执行入口，新闻状态仍以服务器任务与文章为准。

**私有入口／资源：** [easel_workbench/runtime/news_overviews.py](../../../easel_workbench/runtime/news_overviews.py)、[easel_workbench/runtime/news_feedback.py](../../../easel_workbench/runtime/news_feedback.py)、[easel_workbench/readonly_runner.py](../../../easel_workbench/readonly_runner.py)

**官方复用／共通接缝：** [web/frontend/src/components/TrendsPage.tsx](../../../web/frontend/src/components/TrendsPage.tsx)、[web/frontend/src/components/DashboardPage.tsx](../../../web/frontend/src/components/DashboardPage.tsx)、[easel/harnesses/codex.py](../../../easel/harnesses/codex.py)

**验证入口：** [tests/test_workbench_chinese_trend_titles.py](../../../tests/test_workbench_chinese_trend_titles.py)、[tests/test_workbench_collection_partial_diagnostics.py](../../../tests/test_workbench_collection_partial_diagnostics.py)

**需求与设计记录：** [specs/chinese-trend-titles-20261103/spec.md](../../../specs/chinese-trend-titles-20261103/spec.md)、[specs/functional-health-20261103/spec.md](../../../specs/functional-health-20261103/spec.md)

**后续维护：** 变更时先核对上述调用链与当前官方实现；优先共用、缩小上游补丁。同步维护本卡的范围、入口、共通差异及验证依据；被上游吸收时移除对应适配并更新登记状态。原方法、历史输入和交付证据不在本卡复制或改写。

**首版登记记录：** 2026-11-05 按业务源码 `1901f83` 建立首版；首版为只读盘点及文档登记，未新增启用能力，未逐项重新执行产品验收。本轮补充项按当前源码及各自验证记录另行核对，不将首版记录冒称本轮业务验收。

**2026-11-06 后台合同修复：** [本轮Spec](../../../specs/background-news-contracts-20261106/spec.md)。后台新闻方法迁入 [news_contracts.py](../../../easel_workbench/features/collection/news_contracts.py) 及 [references](../../../easel_workbench/features/collection/references/)，覆盖中文摘要、观猹编辑与周刊归一化。合同与准确画像独立冻结，skills=[]，不选择已退役topic-research。[readonly_runner.py](../../../easel_workbench/readonly_runner.py) 接受准确内部合同并复用原 Easel 执行器。标题reopen_unstarted仅允许明确准备失败且没有原模型账本的当天条目恢复；原调用一律核对不重发。[回归测试](../../../tests/test_workbench_news_contracts.py)。
