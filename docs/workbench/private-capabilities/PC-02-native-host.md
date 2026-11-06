# PC-02 原生外壳与移动端宿主适配

2026-11-06：用户批准移动触控侧栏改为450ms长按操作菜单，默认只显示会话标题；点击仍打开原会话，8px移动/滚动/取消/第二触点取消识别，吞掉原长按的合成点击，下一次触摸不受影响。菜单复用官方Drawer、图标、原生重命名编辑器及已有归档/删除确认；桌面hover行为保持。键盘/读屏有具名操作入口，菜单绑定准确会话，导航/侧栏关闭/来源修订变化时退出。

私有实现：[SessionItemMenu.tsx](../../../web/frontend/src/workbench/ui/SessionItemMenu.tsx)、[sessionPress.ts](../../../web/frontend/src/workbench/ui/sessionPress.ts)、[菜单样式](../../../web/frontend/src/workbench/ui/styles/sidebar.css)、[原抽屉宿主适配](../../../web/frontend/src/workbench/ui/common.tsx)。必要共通接缝：[Sidebar.tsx](../../../web/frontend/src/components/Sidebar.tsx) 只增加可选条目呈现接口并传出原动作；ResponsiveSidebar增加可见性通知和嵌套对话框键盘让行；Drawer增加可选overlayClassName，供此私有菜单扩展遮罩到视口并呈现紧凑底部操作区，原默认外观不变。所有共通文件均无私有依赖、不复制会话操作。移除mobile.css强制常显session-actions的旧规则，样式只用于新私有菜单和手势区域。

新增验证入口：[手势及原生操作复用测试](../../../tests/frontend/sessionItemMenu.test.mjs)、[真实触控输入的隔离浏览器旅程](../../../tests/workbench_sidebar_touch_browser.py)，实施与上线依据见 [本轮Spec](../../../specs/sidebar-touch-menu-20261106/spec.md)。同步官方时核对可选参数、原操作回调及嵌套键盘行为，缺省参数仍使用官方行与按钮。

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

**实际公共文件差异：** 见 [共通源码逐文件台账](../SHARED-SOURCE-CHANGES.md)，按 `PC-02` 查询实际关联路径、修改理由与同步核对点；纯复用或开发维护项不据此新增官方改动。

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

**首版登记记录：** 2026-11-05 按业务源码 `1901f83` 建立首版；首版为只读盘点及文档登记，未新增启用能力，未逐项重新执行产品验收。本轮补充项按当前源码及各自验证记录另行核对，不将首版记录冒称本轮业务验收。
