# PC-20 官方基线、PR 补丁及 fork 交付

2026-11-06 核对维护：会话恢复验收发现学习技能已上线但架构夹具遗漏两个已登记目录，且中文名称映射的 reviewed_private_blobs 仍指向新增学习名称之前的字节。核对当前映射只有已登记油猪技能名称、没有私有执行或 I/O 后，更新准确 blob；架构检查继续按明确目录和准确哈希校验，不扩大目录豁免，不改变官方基线或 PR 集成状态。

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

**实际公共文件差异：** 见 [共通源码逐文件台账](../SHARED-SOURCE-CHANGES.md)，按 `PC-20` 查询实际关联路径、修改理由与同步核对点；纯复用或开发维护项不据此新增官方改动。

- **状态：** 已确认保留；类型：开发维护。
- **需求依据：** 用户要求跟进官方、记录准确基线、可独立整理通用修复；私有提交只推自有 fork。 依据见下方原始规则/Spec；本卡不额外授予执行、采纳或发布权限。
- **能力范围：** 基线 JSON/历史标记、显式 PR overlay、同步技能、差异审计、技能字节与可复现交付。
- **官方复用与必要差异：** Git 上游历史和原独立构建保持；相同代码以官方为基座，维护少量公开接缝与私有适配。
- **不可破坏的合同：** 完整基线与单独 cherry-pick 分开记；按用户同步流程解决冲突后 mark；不谎称最新，不向 upstream 直接推送或混入私有内容。

**接口与状态归属：** 开发入口为 easel-upstream-sync 技能及审计脚本，无独立产品 API；基线/overlay 只在 docs/workbench 的对应 JSON 与版本记录维护，远端 SHA 核对不能被本表代替。

**私有登记自动检查：** [check_private_capabilities.py](../../../scripts/check_private_capabilities.py) 及 [.github/workflows/private-capabilities.yml](../../../.github/workflows/private-capabilities.yml) 检查文档ID/路径、受影响源码与公共差异登记，不增加产品运行时注册表。生产源码提交声明 `Private-Change: feature|maintenance`、`Private-Capabilities: <IDs>`、`Private-Reason:`；feature须同提交更新索引和全部声明卡，maintenance仅修正既有实现且不扩能力可不改索引，但新增私有源码仍须在所属卡链接并同提交维护。纯文档/测试提交不强制这些trailer。登记/门禁不能代替明确需求、业务授权或运行验收。

**私有入口／资源：** [.agents/skills/easel-upstream-sync/SKILL.md](../../../.agents/skills/easel-upstream-sync/SKILL.md)、[docs/workbench/upstream-base.json](../../../docs/workbench/upstream-base.json)、[docs/workbench/upstream-overlays.json](../../../docs/workbench/upstream-overlays.json)、[scripts/audit_easel_base.mjs](../../../scripts/audit_easel_base.mjs)

**官方历史例外：** 已记录准确官方基线的祖先原提交不要求补写私有trailer，不能为通过本项目CI改写官方原历史；自有整合提交仍须登记PC-20影响，最终公共文件差异仍全部核对台账，不能借此跳过私有适配登记。

**本机强制入口：** [scripts/git-hooks/pre-push](../../../scripts/git-hooks/pre-push) 在保留官方远端推送拒绝、原技能字节检查的同时执行登记结构检查；推送main还读取Git提供的准确新旧SHA检查每个提交，不把“配置了CI”当成已运行。2026-11-05实际dispatch收到GitHub 422 “Actions has been disabled for this repository”，即便workflow元数据active也不能报告远端通过；本机hook继续拒绝失败推送，不以跳过检查交付。该限制不影响自有fork源码推送和本机正式部署。

**饱和会话修复切换：** [upgrade_workbench_runtime.py](../../../scripts/upgrade_workbench_runtime.py) 仅在旧会话已达到旧上限且候选已移除上限时允许显式延后认证；先围栏与切换，成功登录并通过配对 smoke 后才恢复准入。失败保留围栏，不删除或伪造现存会话。

**官方复用／共通接缝：** [web/app.py](../../../web/app.py)、[web/frontend/src/App.tsx](../../../web/frontend/src/App.tsx)、[easel/web_services](../../../easel/web_services)

**验证入口：** [tests/test_easel_base_alignment.py](../../../tests/test_easel_base_alignment.py)、[tests/test_workbench_git_delivery.py](../../../tests/test_workbench_git_delivery.py)、[tests/test_workbench_skill_bytes.py](../../../tests/test_workbench_skill_bytes.py)、[tests/test_private_capability_registry.py](../../../tests/test_private_capability_registry.py)。自动规则须验证漏登记等负例，不能以文档链接存在代替能力行为验证。

**需求与设计记录：** [docs/workbench/UPSTREAM-VERSIONS.md](../../../docs/workbench/UPSTREAM-VERSIONS.md)、[docs/workbench/GIT-DELIVERY.md](../../../docs/workbench/GIT-DELIVERY.md)

**后续维护：** 变更时先核对上述调用链与当前官方实现；优先共用、缩小上游补丁。同步维护本卡的范围、入口、共通差异及验证依据；被上游吸收时移除对应适配并更新登记状态。原方法、历史输入和交付证据不在本卡复制或改写。

**首版登记记录：** 2026-11-05 按业务源码 `1901f83` 建立首版；首版为只读盘点及文档登记，未新增启用能力，未逐项重新执行产品验收。本轮补充项按当前源码及各自验证记录另行核对，不将首版记录冒称本轮业务验收。
