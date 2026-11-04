# PC-02 原生外壳与移动端宿主适配

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

- **状态：** 已确认保留；类型：共通适配。
- **需求依据：** 用户要求官方外壳、控件和样式；移动抽屉可收起、保留一个悬浮展开入口，并改善返回/滚动。 依据见下方原始规则/Spec；本卡不额外授予执行、采纳或发布权限。
- **能力范围：** 六主入口、服务器导航、返回和页面状态、弹层焦点、移动视口/键盘、统一状态卡与静默刷新。
- **官方复用与必要差异：** 复用 App、Sidebar、ResponsiveSidebar、Drawer、各原页面及 InteractionNotice；宿主只提供数据与通用端口。
- **不可破坏的合同：** 不另画官方页面/弹窗，不用私有 CSS 改写共通外观；正常轮询不闪烁；保留真正错误；旧状态不能覆盖新导航。

**接口与状态归属：** 接口是原 ApplicationFrame 的宿主参数与 navigation/modal-focus 端口，不另建页面协议；页面位置和临时视图由宿主保存，业务数据仍从服务器读取。

**私有入口／资源：** [web/frontend/src/workbench/ui/index.tsx](../../../web/frontend/src/workbench/ui/index.tsx)、[web/frontend/src/workbench/platform/navigation.ts](../../../web/frontend/src/workbench/platform/navigation.ts)、[web/frontend/src/workbench/platform/modal-focus.ts](../../../web/frontend/src/workbench/platform/modal-focus.ts)、[web/frontend/src/workbench/ui/styles/mobile.css](../../../web/frontend/src/workbench/ui/styles/mobile.css)

**官方复用／共通接缝：** [web/frontend/src/App.tsx](../../../web/frontend/src/App.tsx)、[web/frontend/src/components/ResponsiveSidebar.tsx](../../../web/frontend/src/components/ResponsiveSidebar.tsx)、[web/frontend/src/components/Drawer.tsx](../../../web/frontend/src/components/Drawer.tsx)、[web/frontend/src/components/InteractionNotice.tsx](../../../web/frontend/src/components/InteractionNotice.tsx)

**验证入口：** [tests/frontend/workbenchPageReuse.test.mjs](../../../tests/frontend/workbenchPageReuse.test.mjs)、[tests/workbench_navigation_close_browser.py](../../../tests/workbench_navigation_close_browser.py)

**需求与设计记录：** [docs/workbench/MOBILE-EXTENSION-UI-20261101.md](../../../docs/workbench/MOBILE-EXTENSION-UI-20261101.md)、[specs/mobile-return-state-20261102/spec.md](../../../specs/mobile-return-state-20261102/spec.md)

**后续维护：** 变更时先核对上述调用链与当前官方实现；优先共用、缩小上游补丁。同步维护本卡的范围、入口、共通差异及验证依据；被上游吸收时移除对应适配并更新登记状态。原方法、历史输入和交付证据不在本卡复制或改写。

**登记记录：** 2026-11-05 按业务源码 `1901f83` 建立首版；本次只读盘点及文档登记，未新增启用能力，未逐项重新执行产品验收。
