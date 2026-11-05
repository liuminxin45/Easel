# C-01 私有技能管理与整理经验

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

- **状态：** 已退役／历史只读。本条不是“已确认能力”登记，不能用于新增私有功能。
- **记录范围：** 候选、试用、发布/回退、私有技能 pins 与整理经验；保留历史版本、原任务及准确回执。
- **处理边界：** RETIRED_ACTIONS 与 410 边界；存在旧类/数据库表/worker 不代表可新增调用。不得恢复按钮、隐藏抽屉或自动学习。

**当前存量位置：** [easel_workbench/features/skills/retirement.py](../../../easel_workbench/features/skills/retirement.py)、[easel_workbench/features/skills/releases.py](../../../easel_workbench/features/skills/releases.py)、[easel_workbench/runtime/learning_service.py](../../../easel_workbench/runtime/learning_service.py)

**模块与动作不能混同：** learning_service 是兼容导出，其余确定性证据索引、分类与设置存量写入另见 [C-06](C-06-evidence-index-compatibility.md)；本条“历史只读”描述的是已退役私有技能管理动作，不表示整个 LearningService 模块均只读。作品独立质量检查仍归 [PC-12](PC-12-versioned-works.md)，不得因文件名误删。

**需求／退役／核对依据：** [docs/workbench/NATIVE-SKILLS-20261103.md](../../../docs/workbench/NATIVE-SKILLS-20261103.md)、[specs/native-skills-only-20261103/spec.md](../../../specs/native-skills-only-20261103/spec.md)

**相关验证入口：** [tests/test_workbench_skill_retirement.py](../../../tests/test_workbench_skill_retirement.py)、[tests/test_workbench_skill_retirement_cutover.py](../../../tests/test_workbench_skill_retirement_cutover.py)

**后续维护：** 先核对真实调用方、请求准入和历史依赖；未经明确需求不恢复退役业务。待核对项只有补齐需求依据并确认范围后，才能迁入新的已确认能力维护卡；不得把本表当作自动启用或删除清单。

**登记记录：** 2026-11-05 按业务源码 `1901f83` 记录存量；本次不修改接口、运行开关、历史数据或部署版本。
