# U-01 采纳附加动作与旧创作参数的范围

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

- **状态：** 待核对存量／非新增许可。本条不是“已确认能力”登记，不能用于新增私有功能。
- **记录范围：** 核心采纳与版本保留已登记 PC-12；采纳完成窗口中的附加归档/复盘/学习选项，以及旧制作参数显示范围，需要分别对照后续用户决定。
- **处理边界：** 当前 VersionOperations 仍有这些引用；不能将历史卡片或旧 options 推断为恢复整理经验/本轮创作设置的授权，也不能在本次文档盘点顺带删除采纳核心。后续先核对实际条件、用户依据和准确调用，再决定保留/整改。

**当前存量位置：** [web/frontend/src/workbench/ui/WorkCompletion.tsx](../../../web/frontend/src/workbench/ui/WorkCompletion.tsx)、[web/frontend/src/workbench/ui/ProductionParameters.tsx](../../../web/frontend/src/workbench/ui/ProductionParameters.tsx)、[easel_workbench/runtime/completion_service.py](../../../easel_workbench/runtime/completion_service.py)

**需求／退役／核对依据：** [specs/native-product-experience/spec.md](../../../specs/native-product-experience/spec.md)、[docs/workbench/NEWS-NATIVE-CHAT-20261104.md](../../../docs/workbench/NEWS-NATIVE-CHAT-20261104.md)、[AGENTS.md](../../../AGENTS.md)

**相关验证入口：** [tests/test_workbench_native_completion.py](../../../tests/test_workbench_native_completion.py)、[tests/test_workbench_version_view.py](../../../tests/test_workbench_version_view.py)

**后续维护：** 先核对真实调用方、请求准入和历史依赖；未经明确需求不恢复退役业务。待核对项只有补齐需求依据并确认范围后，才能迁入新的已确认能力维护卡；不得把本表当作自动启用或删除清单。

**登记记录：** 2026-11-05 按业务源码 `1901f83` 记录存量；本次不修改接口、运行开关、历史数据或部署版本。
