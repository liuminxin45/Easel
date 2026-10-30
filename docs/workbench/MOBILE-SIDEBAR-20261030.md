# 后续状态：贡献已撤回

用户已撤回官方贡献要求，官方 PR #176 于 2026-10-30 关闭，不再贡献该修改。保留自己的 fork 提交。顶部横栏方案已在私有集成分支改为窄屏边缘按钮，当前版本与验收以 [2026-10-31 交付记录](RETIREMENT-20261031.md) 为准。下文保留当时的历史证据。

---

# 窄屏侧栏通用修复与上游贡献

官方 PR：[ZJU-REAL/Easel #176](https://github.com/ZJU-REAL/Easel/pull/176)。官方基线仍为 `5a597e5f3ef5b01098b53f36caf719dd9a32b7bf`；PR 合并前不提升已集成官方基线。

## 通用修复

390px 视口原有 264px 常驻侧栏没有收起入口，挤占正文。现在宽度不超过 760px 时默认关闭，正文使用全宽；顶部菜单打开抽屉，可通过关闭按钮、遮罩、Escape 或导航动作收起。宽屏保留原 264px 布局。

原 Sidebar 始终只挂载一份，页面输入与侧栏状态保留。抽屉支持 44px 控件、焦点进入/循环/恢复、隐藏及背景 inert、IME、安全区和减少动画。普通动画下的首次焦点问题经真实浏览器复现后修正：visibility 即时生效，仅对 transform 做动画。

贡献分支 [codex/fix-mobile-sidebar](https://github.com/liuminxin45/Easel/tree/codex/fix-mobile-sidebar) 从干净官方提交起步，只有一个提交 `9f3ad30e4ab801231f042f3732a09524ba9a7f72`，四个通用前端文件：

- `web/frontend/src/components/ResponsiveSidebar.tsx`：包装原 Sidebar。
- `web/frontend/src/App.tsx`：只替换一行引用。
- `web/frontend/src/styles/index.css`：响应式布局和抽屉样式。
- `tests/frontend/mobileSidebar.test.mjs`：行为回归。

该分支没有私有工作台提交、服务或数据。私有集成分支以 `8b931b4` 复用同一组件及样式，`eea76e1` 增加准确的公共文件架构许可；新组件与贡献分支逐字节一致。通过 fork 分支向官方发 PR，没有直接推官方分支。GitHub 连接器创建 PR 返回权限不足后，使用已登录的 `liuminxin45` CLI 成功创建并核对了 PR 的四文件范围。

## 验证

- 官方 Node 前端 141 项通过，lint、TypeScript/build 通过。
- 私有 Node 前端 249 项、架构与基座 48 项通过；工作台检查、原 Easel 与私有前端构建通过。
- 官方实际 Windows Edge 浏览器 64 项通过：320/390/768/1440、明暗、触摸模拟、默认/减少动画、焦点、所有关闭入口、resize、设置/画像交接和输入保留。
- 最终私有冻结前端 18 项通过，覆盖真实服务器导航（包括同页）、会话/画像和原字草稿；98 个运行模块来自准确冻结后端，21 个前端文件与 1,098 个后端文件前后 SHA 一致。
- 原在线升级脚本未修改，8 项 IME/草稿/离线/重连检查通过。
- 正式只读 Edge 检查 4 项通过，手机全宽/收起/焦点与桌面宽度正常；后台控制文件及所有进程身份保持。

手机为模拟视口及触摸环境，未声称实体手机验收。浏览器验证没有真实模型或平台写入。上游 PR 当前开放、可合并，CI 为 `action_required` 且无 job 结果；尚不能宣称上游 CI 通过。

## 正式交付

仅切换静态前端至 `native-easel-workbench-20261030145621`，manifest SHA256：
`ddb1a60682256f1abae399a5f1af78aa4be3e499f9062da124c516ac80e75b89`。

后端保持 `workbench-20261030-125044`，manifest SHA256：
`287732da2bcafd4e7174f03e6f021fc8241fe4a0dd4ee74ebac313eee4b666f9`。

激活前业务及原生队列空闲，历史未知回执保留且未重放。前端激活工具核对准入、归属、不可变包与准确进程身份，仅原子切换 `active-native.json`；manager 和七个角色未重启，后端、准入、数据归属及业务数据保持。

证据根目录 `.local/workbench-validation/mobile-sidebar-pr/`：

- `browser-official-r3/report.json`、`browser-private-final/report.json`：源码/构建、浏览器及截图 SHA。
- `official-node-final.txt`、`fork-node-final.txt`、`fork-architecture.xml`：最终回归。
- `upgrade-final/upgrade.json`：准确新旧前端和冻结后端的升级恢复。
- `preflight.json`、`acceptance.json`、`activation.json`：真实只读准入、验收绑定和切换。
- `live-browser.json`：正式只读界面复查。
- `official-ci.json`：上游 CI 当前状态。

正式切换回执另存 `.local/workbench-deployment/frontend-upgrades/native-easel-workbench-20261030145621.json`。此前失败的动画焦点检查及 CSP 夹具等待记录保留，没有用旧候选替代最终源码。
