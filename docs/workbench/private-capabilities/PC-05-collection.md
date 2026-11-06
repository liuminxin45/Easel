# PC-05 自定义来源、自动采集与当天面板

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

**实际公共文件差异：** 见 [共通源码逐文件台账](../SHARED-SOURCE-CHANGES.md)，按 `PC-05` 查询实际关联路径、修改理由与同步核对点；纯复用或开发维护项不据此新增官方改动。

- **状态：** 已确认保留；类型：私有业务。
- **需求依据：** 用户要求保留 Python 自定义采集协议、自动采集，并只显示当天采到的数据；无数据为空面板。 依据见下方原始规则/Spec；本卡不额外授予执行、采纳或发布权限。
- **能力范围：** 来源修订、排期 slot、任务身份、入库/去重/回执、当日视图和明确手动采集。
- **官方复用与必要差异：** 复用 Easel 采集器协议、runner、来源校验及 DashboardPage/TrendsPage；私有层提供来源与服务器存储。
- **不可破坏的合同：** 只显示当日真实结果，无旧缓存顶替；partial 与排期是否执行分开；原脚本、来源修订和未知回执保持，不重复投递。

**接口与状态归属：** 采集来源/排期经 collection 服务与 toolbox_server 接入；SourceRegistry 使用既有存储及 sources schema，真实任务/来源修订归服务器。原热点 API 只投影实际当日结果。

**私有入口／资源：** [easel_workbench/features/collection/registry.py](../../../easel_workbench/features/collection/registry.py)、[easel_workbench/features/collection/schedules.py](../../../easel_workbench/features/collection/schedules.py)、[easel_workbench/runtime/collection_service.py](../../../easel_workbench/runtime/collection_service.py)、[easel_workbench/runtime/collection_worker.py](../../../easel_workbench/runtime/collection_worker.py)

**官方复用／共通接缝：** [easel/trends/runner.py](../../../easel/trends/runner.py)、[web/frontend/src/components/TrendsPage.tsx](../../../web/frontend/src/components/TrendsPage.tsx)、[web/frontend/src/components/DashboardPage.tsx](../../../web/frontend/src/components/DashboardPage.tsx)

**验证入口：** [tests/test_workbench_collection_freshness.py](../../../tests/test_workbench_collection_freshness.py)、[tests/test_workbench_collection_partial_diagnostics.py](../../../tests/test_workbench_collection_partial_diagnostics.py)

**需求与设计记录：** [specs/daily-news-panel-20261103/spec.md](../../../specs/daily-news-panel-20261103/spec.md)、[docs/workbench/HEALTH-COLLECTION-AND-VENDOR-20261105.md](../../../docs/workbench/HEALTH-COLLECTION-AND-VENDOR-20261105.md)

**后续维护：** 变更时先核对上述调用链与当前官方实现；优先共用、缩小上游补丁。同步维护本卡的范围、入口、共通差异及验证依据；被上游吸收时移除对应适配并更新登记状态。原方法、历史输入和交付证据不在本卡复制或改写。

**首版登记记录：** 2026-11-05 按业务源码 `1901f83` 建立首版；首版为只读盘点及文档登记，未新增启用能力，未逐项重新执行产品验收。本轮补充项按当前源码及各自验证记录另行核对，不将首版记录冒称本轮业务验收。

**2026-11-06 后台合同修复：** [本轮Spec](../../../specs/background-news-contracts-20261106/spec.md)。后台筛选不再解析退役用户技能；内部合同归 [news_contracts.py](../../../easel_workbench/features/collection/news_contracts.py) 与其 [references](../../../easel_workbench/features/collection/references/)，保留原筛选、画像与准确回执。集中接缝 [task_runtime.py](../../../easel_workbench/runtime/task_runtime.py)、[capability_contracts.py](../../../easel_workbench/runtime/capability_contracts.py)，[watcha_pipeline.py](../../../easel_workbench/runtime/watcha_pipeline.py) 和 [builtin.py](../../../easel_workbench/integrations/collection/builtin.py) 使用相同合同；不恢复技能选择入口。
