# PC-24 配图制作与核验

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

- **状态：** 已确认保留；类型：辅助业务 SKILL。
- **需求依据：** 用户要求保留迁入的业务 SKILL，并通过 Easel 原生技能方式组织能力；本项已在项目能力元信息中声明。 依据见下方原始规则/Spec；本卡不额外授予执行、采纳或发布权限。
- **能力范围：** 根据准确输入制作配图，保留参考素材和真实产物；按需组合，不冒称实际调用未发生的生图能力。
- **官方复用与必要差异：** 共用原 SkillPage/SkillDrawer、skills 服务及原生执行；方法正文以所列 SKILL 为唯一来源，宿主不重写其业务方法。
- **不可破坏的合同：** 只在本轮显式选择或已确认调用链内执行；当前 SKILL 与资源冻结分别处理；不借辅助技能恢复候选/试用/经验管理或无人值守制作。

**接口与状态归属：** 接口沿原技能服务；方法与资源以本项 SKILL.md 为源，无独立 HTTP 或技能数据库。调用记录、冻结输入与真实输出由既有会话/任务保管，不在维护卡维护第二份技能正文。

**私有入口／资源：** [skills/builtin/image-production/SKILL.md](../../../skills/builtin/image-production/SKILL.md)、[easel_workbench/skill_catalog.py](../../../easel_workbench/skill_catalog.py)、[easel_workbench/runtime/native_skills.py](../../../easel_workbench/runtime/native_skills.py)

**官方复用／共通接缝：** [easel/web_services/skills.py](../../../easel/web_services/skills.py)、[web/frontend/src/components/SkillDrawer.tsx](../../../web/frontend/src/components/SkillDrawer.tsx)

**验证入口：** [tests/test_workbench_chat_products.py](../../../tests/test_workbench_chat_products.py)、[tests/test_workbench_upstream_skills.py](../../../tests/test_workbench_upstream_skills.py)

**需求与设计记录：** [docs/workbench/NATIVE-SKILLS-20261103.md](../../../docs/workbench/NATIVE-SKILLS-20261103.md)、[specs/native-skills-only-20261103/spec.md](../../../specs/native-skills-only-20261103/spec.md)

**后续维护：** 变更时先核对上述调用链与当前官方实现；优先共用、缩小上游补丁。同步维护本卡的范围、入口、共通差异及验证依据；被上游吸收时移除对应适配并更新登记状态。原方法、历史输入和交付证据不在本卡复制或改写。

**登记记录：** 2026-11-05 按业务源码 `1901f83` 建立首版；本次只读盘点及文档登记，未新增启用能力，未逐项重新执行产品验收。
