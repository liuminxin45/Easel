# PC-10 原生技能宿主、配置与私有图标

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

**实际公共文件差异：** 见 [共通源码逐文件台账](../SHARED-SOURCE-CHANGES.md)，按 `PC-10` 查询实际关联路径、修改理由与同步核对点；纯复用或开发维护项不据此新增官方改动。

- **状态：** 已确认保留；类型：共通适配。
- **需求依据：** 用户要求技能页面、抽屉、使用方式与 Easel 一致，移除私有候选/试用/经验管理。 依据见下方原始规则/Spec；本卡不额外授予执行、采纳或发布权限。
- **能力范围：** 磁盘 SKILL 目录、详情/资源、配置修订、服务器操作身份和私有图标注入；支持技能另见 PC-22 至 PC-27。
- **官方复用与必要差异：** 原 SkillPage、SkillDrawer 及唯一 skills 服务；通用 icons 参数仅由宿主传入小猪映射。
- **不可破坏的合同：** 新调用不依赖私有发布指针/候选计划；公共模块不导入私有品牌；当前技能以 SKILL 和准确资源为准，历史 pin 不恢复成新调用门槛。

**接口与状态归属：** 接口由 NativeSkills 绑定共享技能服务；当前内容来自磁盘 SKILL 与资源，保存配置经现有修订机制；旧技能发布版本不作为新执行前提，不新增另一套技能状态机。

**私有技能名称：** 油猪制作技能与学习技能均以“油猪·”开头；卡片、原生抽屉和选择器共用既有 [技能名称映射](../../../web/frontend/src/lib/skillDisplayNames.ts)。官方技能映射不变，更新官方时按overlay记录核对并尽量减少共通文件差异。

**私有入口／资源：** [easel_workbench/runtime/native_skills.py](../../../easel_workbench/runtime/native_skills.py)、[easel_workbench/skill_catalog.py](../../../easel_workbench/skill_catalog.py)、[web/frontend/src/workbench/ui/NativeSkills.tsx](../../../web/frontend/src/workbench/ui/NativeSkills.tsx)、[web/frontend/src/workbench/ui/skillIcons.tsx](../../../web/frontend/src/workbench/ui/skillIcons.tsx)

**官方复用／共通接缝：** [easel/web_services/skills.py](../../../easel/web_services/skills.py)、[web/frontend/src/components/SkillPage.tsx](../../../web/frontend/src/components/SkillPage.tsx)、[web/frontend/src/components/SkillDrawer.tsx](../../../web/frontend/src/components/SkillDrawer.tsx)

**验证入口：** [tests/test_workbench_official_skills.py](../../../tests/test_workbench_official_skills.py)、[tests/test_workbench_skill_retirement.py](../../../tests/test_workbench_skill_retirement.py)、[tests/frontend/workbenchSkillViews.test.mjs](../../../tests/frontend/workbenchSkillViews.test.mjs)

**需求与设计记录：** [docs/workbench/NATIVE-SKILLS-20261103.md](../../../docs/workbench/NATIVE-SKILLS-20261103.md)、[docs/workbench/PRIVATE-SKILL-AVATAR-20261104.md](../../../docs/workbench/PRIVATE-SKILL-AVATAR-20261104.md)

**后续维护：** 变更时先核对上述调用链与当前官方实现；优先共用、缩小上游补丁。同步维护本卡的范围、入口、共通差异及验证依据；被上游吸收时移除对应适配并更新登记状态。原方法、历史输入和交付证据不在本卡复制或改写。

**首版登记记录：** 2026-11-05 按业务源码 `1901f83` 建立首版；首版为只读盘点及文档登记，未新增启用能力，未逐项重新执行产品验收。本轮补充项按当前源码及各自验证记录另行核对，不将首版记录冒称本轮业务验收。

**更新记录：** 2026-11-06 用户明确取消私有生成费用二次确认。在私有[指令适配](../../../easel_workbench/application/generation_policy.py)及[会话组装](../../../easel_workbench/application/chat.py)中集中调整本轮授权解释，官方工作区/原harness保持原样；不新增UI、收费网关或模型执行器。测试：[生成授权](../../../tests/test_workbench_generation_authorization.py)。
