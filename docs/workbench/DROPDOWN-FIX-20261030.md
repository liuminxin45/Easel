# 下拉菜单显示修复与上线验收

2026-10-30 已上线：前端 `native-easel-workbench-20261030082604`，manifest SHA256 `adb1767cd1af9db2a96c62abdbe210a1107388becc89395663aa645934cbbd29`。
后端继续使用 `workbench-20261030-065654`。

共享 `OptionsDropdown` 使用 portal，但缺少可供所有使用方加载的浮层和选项视觉定义，导致角色、设置与数据源弹窗里的菜单出现透明背景、缺少边框和选中态。原定位还按固定行高估算，无法准确处理触控行高和长名称。

修复位于 `web/frontend/src/components/SettingsSelect.tsx` 和新增的同目录 `SettingsSelect.css`：

- 样式由共享组件直接加载，浮层使用主题的不透明表面、边框、阴影、选中态和焦点；原生 select 的 option/optgroup 同步使用主题背景与文字颜色。
- 根据最终宽度下的实际内容测量高度，按可视窗口空间向上或向下展开，限制滚动高度，跟随窗口、滚动、缩放及触发器尺寸变化。
- 保留原生 dialog 的 top layer；支持 Escape、方向键、Home/End、Tab 与外部指针关闭。触控滚动不再因按下选项立即触发选择。

为避免带入其他未发布工作，先按线上 `build-inputs.json` 核对并恢复全部 122 项源码，再仅替换共享组件、添加共享样式；其余 121 项源码哈希保持原值。原历史发布包未修改。

验收证据位于 `.local/workbench-validation/dropdowns-20261030/`：

- `frontend-tests.txt`：215 项前端测试通过，包含共享菜单的 Escape、原生弹窗 portal、实测高度和缩放窗口边界回归。主目录和隔离源码的 `check:workbench`、隔离源码的 `build:workbench` 通过，Node 为 24.19.0。
- `browser-final-r2/browser.json`：实际 Windows Edge，桌面与模拟手机各含深浅色，26 项检查通过；覆盖长列表、触控滚动、键盘操作、右下角反向展开、设置选中反馈及原生弹窗遮罩层级。使用 TEMP 服务、合成角色和假模型列表，无真实模型调用或平台写入；未声称实体手机验收。
- `upgrade/upgrade.json`：8 项桌面与模拟手机升级回归通过，验证输入法组合期、准确草稿、离线与重连均保留且不发送模型请求。
- `acceptance.json`、`baseline-source-final.json`：准确前后端、源码范围及证据 SHA 绑定。
- `deployment-live.json`：通过 `scripts/activate_workbench_frontend.py` 原子切换前端；后端版本、管理器及 7 个角色的 PID、完整创建时间和启动参数一致，无重启、业务库直写或 admission 变更。
- `live-browser.json`：正式 HTTPS origin 的桌面深浅色与模拟手机复查均通过；仅打开/关闭角色和设置菜单，无提交模型或平台操作。

对应部署回执：`.local/workbench-deployment/frontend-upgrades/native-easel-workbench-20261030082604.json`。
