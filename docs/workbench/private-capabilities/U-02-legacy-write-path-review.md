# U-02 旧私有写接口与生产页面的剩余调用

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

- **状态：** 待核对存量／非新增许可。本条不是“已确认能力”登记，不能用于新增私有功能。
- **记录范围：** 旧制作表单、风格/研究/长期业务辅助代码及旧 REST 写路径中，已退役、历史核对和仍可执行部分的逐项分类。
- **处理边界：** 原生壳当前不挂载旧 production.tsx 表单，服务端仍保存兼容分支；不能笼统声称全已删除或全部有新写入许可。发现未被已确认ID覆盖的写能力，先登记具体路径与需求证据，不开放、不直接删除历史。

**调用补充：** `DraftOperations.tsx` 仍可从历史草稿的“按当前草稿制作”选择 `content-production`。该调用与两个油猪技能分离后的新创作入口存在待核对差异；不能仅因旧生产页未挂载就认定全部旧写链路不可达。本次记录事实，不修改或重发历史任务。

**当前存量位置：** [web/frontend/src/workbench/ui/production.tsx](../../../web/frontend/src/workbench/ui/production.tsx)、[easel_workbench/runtime/toolbox_server.py](../../../easel_workbench/runtime/toolbox_server.py)、[easel_workbench/runtime/content_studio.py](../../../easel_workbench/runtime/content_studio.py)、[easel_workbench/runtime/learning_service.py](../../../easel_workbench/runtime/learning_service.py)、[web/frontend/src/workbench/ui/DraftOperations.tsx](../../../web/frontend/src/workbench/ui/DraftOperations.tsx)

**需求／退役／核对依据：** [specs/private-workbench-architecture/spec.md](../../../specs/private-workbench-architecture/spec.md)、[docs/workbench/NATIVE-SKILLS-20261103.md](../../../docs/workbench/NATIVE-SKILLS-20261103.md)

**相关验证入口：** [tests/test_workbench_private_architecture.py](../../../tests/test_workbench_private_architecture.py)、[tests/test_workbench_skill_retirement.py](../../../tests/test_workbench_skill_retirement.py)

**后续维护：** 先核对真实调用方、请求准入和历史依赖；未经明确需求不恢复退役业务。待核对项只有补齐需求依据并确认范围后，才能迁入新的已确认能力维护卡；不得把本表当作自动启用或删除清单。

**登记记录：** 2026-11-05 按业务源码 `1901f83` 记录存量；本次不修改接口、运行开关、历史数据或部署版本。
