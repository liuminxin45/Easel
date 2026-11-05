# C-02 旧生产/媒体执行与 vendor

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

- **状态：** 兼容受限／部分入口已退役。本条不是“已确认能力”登记，不能用于新增私有功能。
- **记录范围：** 旧任务的核对、进程及准确源码保护，旧媒体/生产方法与历史 vendor 原件。
- **处理边界：** 新技能走 PC-03/PC-10；当前媒体共用主树官方脚本，源码摘要不符在发送前拒绝；旧未知只读核对。角色/文件保留不等于恢复旧制作入口。

**当前存量位置：** [easel_workbench/runtime/poster_executor.py](../../../easel_workbench/runtime/poster_executor.py)、[easel_workbench/runtime/easel_media_worker.py](../../../easel_workbench/runtime/easel_media_worker.py)、[easel_workbench/runtime/easel_integration.py](../../../easel_workbench/runtime/easel_integration.py)、[easel_workbench/runtime/vendor/easel](../../../easel_workbench/runtime/vendor/easel)

**需求／退役／核对依据：** [specs/private-workbench-architecture/spec.md](../../../specs/private-workbench-architecture/spec.md)、[docs/workbench/HEALTH-COLLECTION-AND-VENDOR-20261105.md](../../../docs/workbench/HEALTH-COLLECTION-AND-VENDOR-20261105.md)

**相关验证入口：** [tests/test_workbench_media_source.py](../../../tests/test_workbench_media_source.py)、[tests/test_workbench_native_media_routes.py](../../../tests/test_workbench_native_media_routes.py)

**后续维护：** 先核对真实调用方、请求准入和历史依赖；未经明确需求不恢复退役业务。待核对项只有补齐需求依据并确认范围后，才能迁入新的已确认能力维护卡；不得把本表当作自动启用或删除清单。

**首版登记记录：** 2026-11-05 按业务源码 `1901f83` 记录存量；首次登记仅记录存量；后续整改与部署以本轮Spec/正式交付为准，不据本卡推断活动版本。
