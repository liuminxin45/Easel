# PC-13 内容索引、分层请求与返回性能

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

**实际公共文件差异：** 见 [共通源码逐文件台账](../SHARED-SOURCE-CHANGES.md)，按 `PC-13` 查询实际关联路径、修改理由与同步核对点；纯复用或开发维护项不据此新增官方改动。

- **状态：** 已确认保留；类型：可靠性适配。
- **需求依据：** 用户要求内容库/技能库避免一次性拉取全文，返回页面保持状态，减少大量复制和无效重载。 依据见下方原始规则/Spec；本卡不额外授予执行、采纳或发布权限。
- **能力范围：** 摘要/目录/详情/文件分层、会话历史窗口、内容索引、缓存代数、失效标签和有界读取。
- **官方复用与必要差异：** 原 OutputsPage、SkillPage、ProfilePage 的数据源/状态端口；通用渲染不另写一份。
- **不可破坏的合同：** 摘要不携全文/资源字节；按需读准确版本；认证切换拒绝旧响应；索引不是采纳/发布事实，不为性能丢失原始数据。

**接口与状态归属：** 原 /api/outputs 与 /api/library/items、/api/library/resolve 提供分层读取；library_index 是可重建的索引，权威作品/文件仍在服务器；resource-cache 只作可失效的内存读取缓存。

**私有入口／资源：** [easel_workbench/features/works/library_index.py](../../../easel_workbench/features/works/library_index.py)、[easel_workbench/features/works/topic_read_views.py](../../../easel_workbench/features/works/topic_read_views.py)、[web/frontend/src/workbench/core/resource-cache.ts](../../../web/frontend/src/workbench/core/resource-cache.ts)、[web/frontend/src/workbench/core/library.ts](../../../web/frontend/src/workbench/core/library.ts)

**官方复用／共通接缝：** [web/frontend/src/components/OutputsPage.tsx](../../../web/frontend/src/components/OutputsPage.tsx)、[web/frontend/src/components/SkillPage.tsx](../../../web/frontend/src/components/SkillPage.tsx)、[web/frontend/src/components/ProfilePage.tsx](../../../web/frontend/src/components/ProfilePage.tsx)

**验证入口：** [tests/test_workbench_private_read_views.py](../../../tests/test_workbench_private_read_views.py)、[tests/test_workbench_catalog_reads.py](../../../tests/test_workbench_catalog_reads.py)、[tests/test_workbench_performance_diagnostics.py](../../../tests/test_workbench_performance_diagnostics.py)

**需求与设计记录：** [specs/content-library-lazy-20261103/spec.md](../../../specs/content-library-lazy-20261103/spec.md)、[specs/private-lazy-pages-20261103/spec.md](../../../specs/private-lazy-pages-20261103/spec.md)

**后续维护：** 变更时先核对上述调用链与当前官方实现；优先共用、缩小上游补丁。同步维护本卡的范围、入口、共通差异及验证依据；被上游吸收时移除对应适配并更新登记状态。原方法、历史输入和交付证据不在本卡复制或改写。

**首版登记记录：** 2026-11-05 按业务源码 `1901f83` 建立首版；首版为只读盘点及文档登记，未新增启用能力，未逐项重新执行产品验收。本轮补充项按当前源码及各自验证记录另行核对，不将首版记录冒称本轮业务验收。
