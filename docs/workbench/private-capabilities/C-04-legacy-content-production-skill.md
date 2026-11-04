# C-04 旧 content-production 组合技能

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

- **状态：** 隐藏入口／兼容资源。本条不是“已确认能力”登记，不能用于新增私有功能。
- **记录范围：** 原组合方法和历史冻结输入仍可解释；新贴图/文章入口分别使用 PC-08/PC-09。
- **处理边界：** ProjectSkillCatalog 中仍有该资源声明，NativeSkills 列表显式排除旧入口；不得因目录或旧ID存在就重新合并油猪两个流程。

**当前存量位置：** [skills/builtin/content-production/SKILL.md](../../../skills/builtin/content-production/SKILL.md)、[easel_workbench/features/creation_skills.py](../../../easel_workbench/features/creation_skills.py)、[easel_workbench/runtime/native_skills.py](../../../easel_workbench/runtime/native_skills.py)

**需求／退役／核对依据：** [docs/workbench/NEWS-NATIVE-CHAT-20261104.md](../../../docs/workbench/NEWS-NATIVE-CHAT-20261104.md)、[docs/workbench/NATIVE-SKILLS-20261103.md](../../../docs/workbench/NATIVE-SKILLS-20261103.md)

**相关验证入口：** [tests/test_workbench_official_skills.py](../../../tests/test_workbench_official_skills.py)、[tests/test_workbench_news_creation.py](../../../tests/test_workbench_news_creation.py)

**后续维护：** 先核对真实调用方、请求准入和历史依赖；未经明确需求不恢复退役业务。待核对项只有补齐需求依据并确认范围后，才能迁入新的已确认能力维护卡；不得把本表当作自动启用或删除清单。

**登记记录：** 2026-11-05 按业务源码 `1901f83` 记录存量；本次不修改接口、运行开关、历史数据或部署版本。
