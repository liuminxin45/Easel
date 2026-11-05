# PC-14 真实账号身份与私有授权台账

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

**实际公共文件差异：** 见 [共通源码逐文件台账](../SHARED-SOURCE-CHANGES.md)，按 `PC-14` 查询实际关联路径、修改理由与同步核对点；纯复用或开发维护项不据此新增官方改动。

- **状态：** 已确认保留；类型：共通适配。
- **需求依据：** 用户要求账号页/扫码链路完全复用官方，同时保留真实账号身份、画像归属及私有交付授权。 依据见下方原始规则/Spec；本卡不额外授予执行、采纳或发布权限。
- **能力范围：** 原生登录和退出与私有账号 ID/连接修订映射；历史凭据、授权与读回证据保持。
- **官方复用与必要差异：** 原 AccountsPage、accounts 服务与官方账号驱动；私有层不再维护账号卡片、登录编排或运行时替换驱动函数。
- **不可破坏的合同：** 未扫码不能误报成功；登录不授予发布权；身份不符不猜测映射；历史记录继续保存但不恢复历史账号 UI、依赖区或自动账号检测。

**接口与状态归属：** 原 /api/accounts、/api/login/*、/api/logout/* 进入共享账号服务；私有身份映射与授权证据由 easel_accounts/platform_accounts 保管，不新增登录态来源或把 ledger 行当成功回执。

**私有入口／资源：** [easel_workbench/runtime/easel_accounts.py](../../../easel_workbench/runtime/easel_accounts.py)、[easel_workbench/integrations/platform_accounts.py](../../../easel_workbench/integrations/platform_accounts.py)、[web/frontend/src/workbench/ui/PlatformAccounts.tsx](../../../web/frontend/src/workbench/ui/PlatformAccounts.tsx)

**官方复用／共通接缝：** [easel/web_services/accounts.py](../../../easel/web_services/accounts.py)、[web/frontend/src/components/AccountsPage.tsx](../../../web/frontend/src/components/AccountsPage.tsx)

**验证入口：** [tests/test_workbench_native_api.py](../../../tests/test_workbench_native_api.py)、[tests/test_easel_shared_services.py](../../../tests/test_easel_shared_services.py)

**需求与设计记录：** [AGENTS.md](../../../AGENTS.md)、[docs/workbench/ADAPTATION-POINTS.md](../../../docs/workbench/ADAPTATION-POINTS.md)

**后续维护：** 变更时先核对上述调用链与当前官方实现；优先共用、缩小上游补丁。同步维护本卡的范围、入口、共通差异及验证依据；被上游吸收时移除对应适配并更新登记状态。原方法、历史输入和交付证据不在本卡复制或改写。

**首版登记记录：** 2026-11-05 按业务源码 `1901f83` 建立首版；首版为只读盘点及文档登记，未新增启用能力，未逐项重新执行产品验收。本轮补充项按当前源码及各自验证记录另行核对，不将首版记录冒称本轮业务验收。
