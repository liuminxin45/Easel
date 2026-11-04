# PC-20 官方基线、PR 补丁及 fork 交付

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

- **状态：** 已确认保留；类型：开发维护。
- **需求依据：** 用户要求跟进官方、记录准确基线、可独立整理通用修复；私有提交只推自有 fork。 依据见下方原始规则/Spec；本卡不额外授予执行、采纳或发布权限。
- **能力范围：** 基线 JSON/历史标记、显式 PR overlay、同步技能、差异审计、技能字节与可复现交付。
- **官方复用与必要差异：** Git 上游历史和原独立构建保持；相同代码以官方为基座，维护少量公开接缝与私有适配。
- **不可破坏的合同：** 完整基线与单独 cherry-pick 分开记；按用户同步流程解决冲突后 mark；不谎称最新，不向 upstream 直接推送或混入私有内容。

**接口与状态归属：** 开发入口为 easel-upstream-sync 技能及审计脚本，无独立产品 API；基线/overlay 只在 docs/workbench 的对应 JSON 与版本记录维护，远端 SHA 核对不能被本表代替。

**私有入口／资源：** [.agents/skills/easel-upstream-sync/SKILL.md](../../../.agents/skills/easel-upstream-sync/SKILL.md)、[docs/workbench/upstream-base.json](../../../docs/workbench/upstream-base.json)、[docs/workbench/upstream-overlays.json](../../../docs/workbench/upstream-overlays.json)、[scripts/audit_easel_base.mjs](../../../scripts/audit_easel_base.mjs)

**官方复用／共通接缝：** [web/app.py](../../../web/app.py)、[web/frontend/src/App.tsx](../../../web/frontend/src/App.tsx)、[easel/web_services](../../../easel/web_services)

**验证入口：** [tests/test_easel_base_alignment.py](../../../tests/test_easel_base_alignment.py)、[tests/test_workbench_git_delivery.py](../../../tests/test_workbench_git_delivery.py)、[tests/test_workbench_skill_bytes.py](../../../tests/test_workbench_skill_bytes.py)

**需求与设计记录：** [docs/workbench/UPSTREAM-VERSIONS.md](../../../docs/workbench/UPSTREAM-VERSIONS.md)、[docs/workbench/GIT-DELIVERY.md](../../../docs/workbench/GIT-DELIVERY.md)

**后续维护：** 变更时先核对上述调用链与当前官方实现；优先共用、缩小上游补丁。同步维护本卡的范围、入口、共通差异及验证依据；被上游吸收时移除对应适配并更新登记状态。原方法、历史输入和交付证据不在本卡复制或改写。

**登记记录：** 2026-11-05 按业务源码 `1901f83` 建立首版；本次只读盘点及文档登记，未新增启用能力，未逐项重新执行产品验收。
