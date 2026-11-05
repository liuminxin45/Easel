# C-04 旧 content-production 组合技能

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

- **状态：** 已退役，旧技能源文件归档。本条不能用于新增私有功能。
- **记录范围：** 新贴图/文章入口分别使用 PC-08/PC-09；旧业务数据保留，不提供旧技能历史兼容入口。
- **处理边界：** 不再被 ProjectSkillCatalog 或 Easel 技能目录发现；不得因归档文件或旧ID存在就重新启用或合并流程。

**当前存量位置：** [skills/builtin/content-production/SKILL.retired.md](../../../skills/builtin/content-production/SKILL.retired.md)、[easel_workbench/features/creation_skills.py](../../../easel_workbench/features/creation_skills.py)、[easel_workbench/runtime/native_skills.py](../../../easel_workbench/runtime/native_skills.py)

**需求／退役／核对依据：** [docs/workbench/NEWS-NATIVE-CHAT-20261104.md](../../../docs/workbench/NEWS-NATIVE-CHAT-20261104.md)、[docs/workbench/NATIVE-SKILLS-20261103.md](../../../docs/workbench/NATIVE-SKILLS-20261103.md)

**相关验证入口：** [tests/test_workbench_official_skills.py](../../../tests/test_workbench_official_skills.py)、[tests/test_workbench_news_creation.py](../../../tests/test_workbench_news_creation.py)

**后续维护：** 先核对真实调用方、请求准入和历史依赖；未经明确需求不恢复退役业务。待核对项只有补齐需求依据并确认范围后，才能迁入新的已确认能力维护卡；不得把本表当作自动启用或删除清单。

**首版登记记录：** 2026-11-05 按业务源码 `1901f83` 记录存量；首次登记仅记录存量；后续整改与部署以本轮Spec/正式交付为准，不据本卡推断活动版本。

**退役目录归属：** [原技能目录](../../../skills/builtin/content-production/)，入口文件已归档且不再发现。
