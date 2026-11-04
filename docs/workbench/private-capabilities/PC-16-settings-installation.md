# PC-16 配置修订、凭据与隔离安装队列

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

- **状态：** 已确认保留；类型：共通适配。
- **需求依据：** 用户要求官方设置页和模型/引擎通道，保留配置修订、项目隔离安装，固定 Node/Python。 依据见下方原始规则/Spec；本卡不额外授予执行、采纳或发布权限。
- **能力范围：** 服务器加密凭据、会话准确配置、明确保存、环境/依赖检测和持久安装操作身份。
- **官方复用与必要差异：** 原 SettingsPanel/HarnessSettings、settings/environment 服务和同一安装逻辑；不复制函数或另起模型设置页。
- **不可破坏的合同：** 新保存只影响后续新会话；未知安装不重放；不替换固定解释器或全局凭据；API 模式不执行本机技能。

**接口与状态归属：** 原 /api/settings/*、/api/env 进入共享处理函数；SettingsService 保存 workbench_settings_versions/operations，凭据及安装任务分别在现有 vault/queue 边界管理。

**私有入口／资源：** [easel_workbench/settings.py](../../../easel_workbench/settings.py)、[easel_workbench/features/installations/queue.py](../../../easel_workbench/features/installations/queue.py)、[easel_workbench/infrastructure/installations/host.py](../../../easel_workbench/infrastructure/installations/host.py)、[web/frontend/src/workbench/ui/settingsApi.ts](../../../web/frontend/src/workbench/ui/settingsApi.ts)

**官方复用／共通接缝：** [easel/web_services/settings.py](../../../easel/web_services/settings.py)、[easel/web_services/environment.py](../../../easel/web_services/environment.py)、[web/frontend/src/components/SettingsPanel.tsx](../../../web/frontend/src/components/SettingsPanel.tsx)

**验证入口：** [tests/test_workbench_settings.py](../../../tests/test_workbench_settings.py)、[tests/test_workbench_install_queue.py](../../../tests/test_workbench_install_queue.py)

**需求与设计记录：** [docs/workbench/SETTINGS-ALIGNMENT-20261030.md](../../../docs/workbench/SETTINGS-ALIGNMENT-20261030.md)、[specs/settings-native-cleanup-20261103/spec.md](../../../specs/settings-native-cleanup-20261103/spec.md)

**后续维护：** 变更时先核对上述调用链与当前官方实现；优先共用、缩小上游补丁。同步维护本卡的范围、入口、共通差异及验证依据；被上游吸收时移除对应适配并更新登记状态。原方法、历史输入和交付证据不在本卡复制或改写。

**登记记录：** 2026-11-05 按业务源码 `1901f83` 建立首版；本次只读盘点及文档登记，未新增启用能力，未逐项重新执行产品验收。
