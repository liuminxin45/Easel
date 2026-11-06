# PC-31 制作复盘与逐条核销

[返回登记表](../PRIVATE-CAPABILITIES.md)

- **状态：** 已确认；私有业务。

**需求依据：** 2026-11-06用户明确批准，已实施并上线，见[交付记录](../PRODUCTION-INSIGHTS-20261106.md)。
- **能力范围：** 仅两项油猪生产技能真实完整交付后的对话提炼、原始反馈、逐条核销及每技能总文档。AI建议与人类反馈分开；不得运行时编辑技能。
- **官方复用：** 原生只读 Codex 适配器、准确作品回执、原 Drawer/状态卡；不恢复 C-01/C-06 退役管理。
- **接口与状态归属：** [production_insights](../../../easel_workbench/features/production_insights/)、[HTTP适配](../../../easel_workbench/http/production_insights.py)、[作品回执](../../../easel_workbench/features/works/native_review.py)、[入口](../../../easel_workbench/entry.py)、[私有服务组装](../../../easel_workbench/runtime/toolbox_server.py)、[只读调用](../../../easel_workbench/readonly_runner.py)、[部署空闲](../../../scripts/activate_workbench.py)、[复盘界面](../../../web/frontend/src/workbench/ui/ProductionInsights.tsx)、[版本操作](../../../web/frontend/src/workbench/ui/VersionOperations.tsx)、[请求客户端](../../../web/frontend/src/workbench/core/client.ts)。路由 `/api/production-insights/`。
- **存储：** 私有SQLite复盘/操作记录；`data/production-insights` 下每技能Markdown可重建投影。完整证据和准确回执保留；未知不重发。
- **核销：** 同意仍为待实施；技能真正落地需要明确源码交付证据。未采纳保留原因。
- **私有样式：** [production-insights.css](../../../web/frontend/src/workbench/ui/production-insights.css) 仅控制本扩展内长SHA断行与条目分隔，不改变官方Drawer或共通控件。
- **验证入口：** [后端用例](../../../tests/test_workbench_production_reviews.py)、[端到端入口](../../../tests/test_workbench_production_insights_api.py)、本轮[Spec](../../../specs/production-feedback-templates-20261106/spec.md)。

**后续维护：** 继续以原生技能、原 Drawer 和准确版本为核心；不恢复退役技能管理，不运行时更改SKILL。接口变更同步维护测试与本卡。

**登记记录：** 2026-11-06 按用户批准方案新增；实施和上线证据另见本轮Spec。
