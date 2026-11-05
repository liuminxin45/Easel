# PC-21 项目 Codex Spec 工作流与维护知识

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

**实际公共文件差异：** 见 [共通源码逐文件台账](../SHARED-SOURCE-CHANGES.md)，按 `PC-21` 查询实际关联路径、修改理由与同步核对点；纯复用或开发维护项不据此新增官方改动。

- **状态：** 已确认保留；类型：开发维护。
- **需求依据：** 用户明确将旧 Spec Kit 替换为项目隔离 Codex Spec，并要求按项目工作流诊断、实现和验证。 依据见下方原始规则/Spec；本卡不额外授予执行、采纳或发布权限。
- **能力范围：** 项目开发技能、隔离 CLI、spec 记录、维护文档和本私有能力速查表；与产品内容技能分开。
- **官方复用与必要差异：** 使用项目已有 Codex Spec 工具，不另建阶段引擎、运行时能力目录或文档服务。
- **不可破坏的合同：** 开发文档不替代服务器事务或技能注册；用户指令优先，源代码/运行证据优先于旧总结；不把登记当作自创需求授权。

**接口与状态归属：** 开发入口为项目 codex-spec 技能与脚本；配置归 .codex-spec，任务记录归 specs，隔离工具归 .runtime/codex-spec；无独立产品接口或业务存储。

**私有入口／资源：** [.agents/skills/codex-spec/SKILL.md](../../../.agents/skills/codex-spec/SKILL.md)、[scripts/codex-spec.ps1](../../../scripts/codex-spec.ps1)、[scripts/install_codex_spec.ps1](../../../scripts/install_codex_spec.ps1)、[.codex-spec/config.json](../../../.codex-spec/config.json)

**官方复用／共通接缝：** 无；本项不修改产品共通实现。

**验证入口：** 无；本项不修改产品共通实现。

**需求与设计记录：** [docs/workbench/CODEX-SPEC-20261101.md](../../../docs/workbench/CODEX-SPEC-20261101.md)、[specs/codex-spec-upgrade/spec.md](../../../specs/codex-spec-upgrade/spec.md)

**后续维护：** 变更时先核对上述调用链与当前官方实现；优先共用、缩小上游补丁。同步维护本卡的范围、入口、共通差异及验证依据；被上游吸收时移除对应适配并更新登记状态。原方法、历史输入和交付证据不在本卡复制或改写。

**首版登记记录：** 2026-11-05 按业务源码 `1901f83` 建立首版；首版为只读盘点及文档登记，未新增启用能力，未逐项重新执行产品验收。本轮补充项按当前源码及各自验证记录另行核对，不将首版记录冒称本轮业务验收。
