# PC-04 本机草稿、附件及离线输入保留

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

- **状态：** 已确认保留；类型：私有保留。
- **需求依据：** 用户要求移动返回流畅，断线/401/退出时保留已输入内容及附件。 依据见下方原始规则/Spec；本卡不额外授予执行、采纳或发布权限。
- **能力范围：** 获准的浏览器草稿、IndexedDB 附件、操作身份、页面位置和恢复入口；不在浏览器建立业务历史主库。
- **官方复用与必要差异：** 复用 ChatPage/各原页面的受控输入、草稿和 viewState 端口；私有仓库只保存允许的本机内容。
- **不可破坏的合同：** 登录过期和升级不清输入；已提交/未知操作身份保持；页面卸载不取消服务器任务，不把服务器作品和凭据整体缓存到浏览器。

**接口与状态归属：** 接口是本机输入仓库和 session-open-flow；持久输入/附件按 persistence 模块管理，页面恢复状态按 view-state 管理。服务器会话与任务回执不得降级为本机数据。

**私有入口／资源：** [web/frontend/src/workbench/core/persistence.ts](../../../web/frontend/src/workbench/core/persistence.ts)、[web/frontend/src/workbench/core/session-open-flow.ts](../../../web/frontend/src/workbench/core/session-open-flow.ts)、[web/frontend/src/workbench/platform/view-state.ts](../../../web/frontend/src/workbench/platform/view-state.ts)、[web/frontend/src/workbench/ui/system.tsx](../../../web/frontend/src/workbench/ui/system.tsx)

**官方复用／共通接缝：** [web/frontend/src/components/ChatPage.tsx](../../../web/frontend/src/components/ChatPage.tsx)、[web/frontend/src/components/IdeasPage.tsx](../../../web/frontend/src/components/IdeasPage.tsx)

**验证入口：** [tests/frontend/draftPendingGuard.test.mjs](../../../tests/frontend/draftPendingGuard.test.mjs)、[tests/frontend/mobileResourceRuntime.test.mjs](../../../tests/frontend/mobileResourceRuntime.test.mjs)

**需求与设计记录：** [specs/mobile-return-state-20261102/spec.md](../../../specs/mobile-return-state-20261102/spec.md)、[docs/workbench/SESSION-RECOVERY-20261103.md](../../../docs/workbench/SESSION-RECOVERY-20261103.md)

**后续维护：** 变更时先核对上述调用链与当前官方实现；优先共用、缩小上游补丁。同步维护本卡的范围、入口、共通差异及验证依据；被上游吸收时移除对应适配并更新登记状态。原方法、历史输入和交付证据不在本卡复制或改写。

**登记记录：** 2026-11-05 按业务源码 `1901f83` 建立首版；本次只读盘点及文档登记，未新增启用能力，未逐项重新执行产品验收。
