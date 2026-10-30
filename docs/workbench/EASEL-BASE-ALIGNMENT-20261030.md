# Easel 基座统一整改

官方基线：`5a597e5f3ef5b01098b53f36caf719dd9a32b7bf`，来源为 ZJU-REAL/Easel。
集成分支：`codex/easel-base-alignment`；交付目标仅为 `origin` 自有 fork `liuminxin45/Easel`。官方 upstream 仅拉取，不推送、不提交私有 PR。

`configure_workbench_git.py` 设置默认推送 origin、禁用 upstream 的 push URL，并安装仓库内 pre-push 检查；包括改名远端指向官方地址也会被拒绝。

## 存量与分工

保留原集成历史的 20 个提交。119 份未提交源码、测试与说明已按原字节保存至
`.local/workbench-validation/easel-base-alignment-20261030/before/`，并以 `6920288`
登记为可恢复的存量集成基线。该提交不是新版本的验收证明。

总调度负责 App、侧栏、统一请求、共享样式、构建、Git 和部署。
三个子任务分别负责公共后端、私有原生协议适配、原生页面与浏览器检查。
原有相关聊天已确认停止重叠写入，不独立切换版本。

## 唯一实现

- `App.tsx` 的 `ApplicationFrame` 同时服务默认 Easel 与服务器宿主。宿主不运行默认浏览器会话存储。
- 账号直接渲染 `AccountsPage`；未连接时只有原生登录动作，依赖诊断和历史账号列表退出界面。
- 首页、热点、选题、内容库、画像、日历、发布和拆解均使用原 Page 组件；版本、素材绑定、采纳等是明确的业务扩展。
- 公共登录、设置、选题/排期和输出处理位于 `easel/web_services/`。原入口与私有入口绑定同一函数代码，配置和目录按实例隔离。
- 移除设置函数生成副本与生成脚本；旧样式副本改为指向原样式。私有样式只能作用于独立扩展容器。
- 原 RPC、原引擎和 `_sessions` 绑定继续承接执行，没有第二套模型传输。

## 协议与授权

原生页面保留原 URL、HTTP 方法和消息结构。唯一操作 ID 通过请求头传递，不覆盖来源或选题的业务 ID。
跨断线只查询原操作回执，不重发 JSON、附件或模型回合；浏览器只持久保存恢复元数据和获准的未提交输入，接口密钥不入本地存储。画像与选题的原生编辑器使用可选草稿端口；画像草稿保存原修订，冲突后仅明确核对才能基于新修订继续。
账号显示缓存仅在宿主当前内存有效，服务器仍为权威。

账号身份与交付能力分开。稳定 ID 由原驱动提供，不在执行时替换驱动函数。
新账号操作统一进入原登录服务；历史私有登录记录和回执保留可读，旧写入入口退役。
手工导出、排期、浏览和登录均不新增平台发布授权。

## 验证与发布

官方原件单独归档并构建于验证目录的 `canonical-source/`，用于同一数据下的原版对照。
工作台构建执行交互与基座检查；新增架构负对照验证重复实现、反向依赖及共通样式覆盖会被拒绝。
真实模型、真实扫码完成和平台发布不由 TEMP 假执行器或模拟手机结果推定。

集中适配点、采用的端口/适配器、组装入口、扩展槽与边界装饰模式，以及后续同步顺序见 [ADAPTATION-POINTS.md](ADAPTATION-POINTS.md)。新增共通功能必须先改原模块；私有业务不进入原模块。当前分支包含私有历史，不整体提交给官方；以后仅整理通用模块的独立补丁。

公众号手工包复用原 `build_package`；Markdown 3.11.2 经既有持久安装队列进入项目 media-tools 环境，未改变固定服务 Python 或上游 .venv。本地大文件登记与原上传共用同一原子写入，HTTP 仍限 20MB，本地导出流式上限 2GB。

## 最终交付

最终运行源码为 `59026d2250783b5d64c706134465ca58b8588fb5`，补充浏览器验收提交为 `a7c4cbddbfdcf45e864ee2155de9f3be62dd3b23`；两者之间只增加测试。代码已推送到 [自有 fork 的集成分支](https://github.com/liuminxin45/Easel/tree/codex/easel-base-alignment)。2026-10-30 复查官方 main 仍为上述固定 `5a597e5`。

| 正式配对 | release | manifest SHA256 |
|---|---|---|
| 后端 | `workbench-20261030-125044` | `287732da2bcafd4e7174f03e6f021fc8241fe4a0dd4ee74ebac313eee4b666f9` |
| 前端 | `native-easel-workbench-20261030125003` | `31158a97214b9c1c783a65665a94e63327d086da6e3a1c90a63e2d87e957eade` |

最终冻结候选通过 454 项工作台回归、24 项基座与共享服务补充检查，136 个运行模块全部来自此候选；1,098 个后端文件测试后重核无变化。前端 244 项通过，原 Easel 与工作台检查、独立构建均通过。原生后端专项 390 项通过、14 项按环境跳过。

冻结浏览器 72 项通过，含 Windows 桌面与模拟手机、明暗主题、官方同数据样式对照、扫码所有状态、准确修订冲突恢复、真实 HTTP 401 保稿及未知操作不重放。56 张截图保存 SHA。私有账号页初始不发 whoami，手动核验与扫码成功仍调用原 `force=true` 服务。模拟手机保留官方固定侧栏的布局限制，不能称为已解决移动适配或实体手机验收。

首轮上线复核发现原账号页自动 whoami 会恢复已退役行为，已通过共享缓存端口的可选策略修正；原页面、样式和官方默认行为保持。最终候选重新冻结并完整回归，首轮配对及失败/修正证据没有覆盖。正式 Windows Edge 只读复查显示七个平台均未登录、原生登录按钮可见、无额外账号操作，账号自动核验和业务写请求均为零。

切换使用既有准入围栏、空闲/原生队列、进程创建时间和完整参数检查。最终 manager 与七个角色身份匹配，18 张历史表原有 1,291 行的整行哈希及重数全部保留；没有复制/恢复数据库、重放历史未知请求或激活新技能版本。真实扫码完成、真实模型制作与平台发布没有由本轮合成验收推定。

远端干净克隆使用固定 Node 24.19.0、锁文件及 `npm ci --ignore-scripts`，原生与私有三项检查/构建全部通过，构建前后 Git 干净。fork 的 [Easel 基座 CI](https://github.com/liuminxin45/Easel/actions/runs/41058882631) 与 [自定义采集协议 CI](https://github.com/liuminxin45/Easel/actions/runs/41058123670) 均通过。

准确证据根目录：`.local/workbench-validation/easel-base-alignment-20261030/`。

- `final-acceptance-r2.json`：最终候选、当前发布基线和 115 份验收文件 SHA。
- `frozen-backend-r2/final-backend-summary-r2.json`：完整冻结回归与源码/模块身份。
- `base-browser-frozen-r2/report.json`：72 项浏览器检查、测试脚本和截图 SHA。
- `remote-reproduction-r2.json`：远端新检出的源码与可复现构建。
- `after-live.json`、`history-after.json`、`live-after-summary.json`：原行哈希、队列及准确进程身份。
- `owner-live-r2.json`：正式 owner HTTP 与 Windows Edge 只读账号页；认证状态未写盘。
- `.local/workbench-deployment/upgrades/workbench-20261030-125044.json`：实际正式切换回执（此路径相对于仓库根目录）。
