# PC-32 优秀制作模板

[返回登记表](../PRIVATE-CAPABILITIES.md)

- **状态：** 已确认；私有业务。

**需求依据：** 2026-11-06用户明确批准，已实施并上线，见[交付记录](../PRODUCTION-INSIGHTS-20261106.md)。
- **能力范围：** 人工从准确完整版本确认优秀制作方法、图片规范、风格及参考；不可变模板按画像/技能/格式隔离，下次明确选择后附加给同一原生生产技能。
- **官方复用：** 原新闻制作 Drawer、SettingsSelect、两个生产 SKILL；不增加技能或会话按钮。
- **接口与状态归属：** [模板服务](../../../easel_workbench/features/production_insights/templates.py)、[新闻制作](../../../easel_workbench/features/news_creation.py)、[请求类型](../../../web/frontend/src/workbench/ui/newsCreation.ts)、[制作表单](../../../web/frontend/src/workbench/ui/NewsCreationDrawer.tsx)、[模板确认](../../../web/frontend/src/workbench/ui/ProductionInsights.tsx)、[HTTP](../../../easel_workbench/http/production_insights.py)。
- **存储：** `data/production-insights/templates` 的准确模板、参考快照和SHA；本轮沿原素材冻结，重试不得换用当前模板或当前技能。
- **限制：** AI不能批准；不能夹带旧新闻事实、旧一次性要求、跨技能资源或自动发布。技能资源变化须重新核对。
- **验证入口：** [后端](../../../tests/test_workbench_production_templates.py)、[入口](../../../tests/test_workbench_production_insights_api.py)、[Spec](../../../specs/production-feedback-templates-20261106/spec.md)。

**后续维护：** 继续以原生技能、原 Drawer 和准确版本为核心；不恢复退役技能管理，不运行时更改SKILL。接口变更同步维护测试与本卡。

**登记记录：** 2026-11-06 按用户批准方案新增；实施和上线证据另见本轮Spec。
