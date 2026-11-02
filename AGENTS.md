# Easel 私有工作台约定

## 当前产品方向

以本项目为主工程，自有工作流位于 `easel_workbench/`，宿主适配位于
`web/frontend/src/workbench/`，共通界面以原 `App.tsx` 和原组件为唯一实现。上游 `easel/` 保持通用；
从 `upstream` 跟进更新，保留本地 fork 的 Python 自定义采集协议。
`D:/Projects/ai-news-desk` 保留原件、历史版本与迁移证据，不再启动另一组业务写入者。

- 2026-10-30 基座对齐授权：共通页面、侧栏、控件、样式、账号登录和设置必须直接复用 Easel 官方实现；禁止另写平行页面、复制函数生成副本或用私有 CSS 覆盖共通外观。确需抽取时只保留一份通用实现，原入口与私有宿主共同调用；通用模块不得反向依赖私有服务。
- 私有开发默认直接在自有 fork 的 `main` 上进行；每批通过对应检查后提交并推送 `origin/main`，不为私有改动默认创建分支或 PR。只有用户明确要求隔离开发时才另开私有分支，完成后整合回 `main`。总调度协调每个文件的负责人；子任务不得独立提交、切换活动指针或部署。历史数据、冻结版本及未知操作身份不因代码合并而重写。
- 只有用户明确要求向 Easel 官方贡献时，才从准确官方基线创建独立贡献分支，推送自有 fork 的该分支，再向 `ZJU-REAL/Easel` 创建 PR 并等待官方审查、合并。`upstream` 是只读官方来源及 PR 目标，禁止直接推送；私有工作台代码、数据和文档不得混入官方贡献。贡献分支与其官方 PR 保持准确绑定，不因私有 `main` 整合而更新或替官方合并。
- 本项目 Git 交付规则详见 `docs/workbench/GIT-DELIVERY.md`。旧私有分支和其他工作树保留历史，不再作为默认开发入口；提交、推送、官方 PR 与正式部署分别核验，推送 `main` 不代表已部署。
- 私有扩展统一使用原 Easel 的设计 tokens 与组件：短详情使用 `ExtensionDetails`，长记录经 `TextRecord`/`JsonDetails` 进入同一 `Modal`，任务历史状态通过 `TaskStatus` 附着准确消息或版本。不得再添加默认三角折叠、平行控件框架、固定顶部历史故障条或正常轮询闪烁提示。按钮沿用原 `.btn`，扩展样式限定 `.ew-*`；真实连接/授权错误仍须可见。异步导航复用 navigation ticket，修改/采纳/不采纳分别绑定原版本且不得自动制作；准则与验收见 `docs/workbench/MOBILE-EXTENSION-UI-20261101.md`。
- 显式文件下载统一复用公共 `DownloadManager`/`DownloadLink`；私有鉴权只通过宿主 resolver 接入。不得再各页创建下载流程、交给原生下载器裸 Cookie 地址，或将 HTTP 交接冒称实体设备已保存。能力链接必须限时、绑定目标与原会话、退出可撤销；文件读取复用原服务。
- 私有工作台只有工作台、对话、技能库、内容库、账号、画像六个主入口，设置置底；工具注册唯一来源仍为 `/api/config.tools`。
- 贴图/文章通过内容生产技能与同一作品流程执行；原始反馈、精确版本、冻结文本、附件和操作ID保持。未确认发送及回执未知不可重放，反馈不自动制作。
- 创作画像、执行身份、真实平台账号独立建模。2026-10-30 最新授权：本项目 `skills/builtin/*/SKILL.md` 是当前技能与资源声明的唯一来源；`skills/shared/workbench/` 保存迁入资源，不安装到全局，不再实时依赖 neo-content 的技能目录。旧注册、规范及版本只保留来源证据与历史兼容。
- 新任务使用原 Easel `ChatPage`、所选原生引擎适配器、RPC 会话连接池及 `_sessions` 原生绑定，默认 Codex。2026-10-30 设置对齐授权：支持 API 仅聊天、OpenClaw、OpenCode、Codex、ACP 与六通道配置；明确保存仅作用于新会话，已有会话和受理任务保留准确配置修订。API 模式不得受理本机技能或制作。画像固定在会话，技能通过 `/` 或 `+` 显式选择；先核对方案，再受理准确冻结输入。`chat.py` 只包服务器会话与回执，`chat_business.py` 只处理画像、作品版本、原始意见和交付授权，不另写模型传输。
- `easel_workbench/skills.py` 只管任务范围、必选规则和启动动作投影。内容生产的实际方法来自项目 `content-production/SKILL.md`，写作、配图与后续独立检查各自绑定准确版本；事务、停止、重连、幂等和未知回执继续由程序负责，不能写成由模型自行解释的工作流。
- 本轮冻结正文和 `outputs/_sessions/skill-inputs/<snapshot>/` 版本副本优先于当前磁盘技能；严格使用本轮所选技能、素材和输出目录。仅制作不包含采纳、发布、修改账号或长期规则的授权。新会话可以关联不同作品；修改保留准确父版、画像、技能和原始意见，另存版本。
- 内部已受理执行快照须核对SHA、任务、画像和准确技能版本后传递，不在重试时重解析候选状态。HTTP不得注入该内部快照参数。
- 沿用原 Codex 执行与交付授权合同。采纳、归档、Git同步及平台交付分别核验；连接成功不等于已验证发布能力。用户授权按需整理经验，无新增自动学习、无人值守制作或发布。
- 原通知页、通知设备、顶部通知/设置、旧自动账号检测与个人资料库继续退役。私有 profile 的模型、权限与媒体通道只在用户明确保存后供后续新会话使用；不自动启用发布驱动。OpenClaw 使用项目隔离配置及原生本地 CLI，独立只读核验仍保留专用 Codex 配置。安装使用项目隔离依赖与同一持久安装队列，不替换固定 Node/Python。

## 运行与验证

- Node 固定 24.19.0。私有工作台 Python 位于 `.runtime/workbench-python`，使用已验证的 Python 3.14.7 及依赖闭包；原 `.venv` 保持上游独立环境。
- 前端在 `web/frontend` 运行 `npm run check:workbench` 与 `npm run build:workbench`。原 Easel build 保持独立，正式私有界面为 `/native/`。
- 架构改动运行 `tests/test_workbench_architecture.py`、`test_workbench_skill_policy.py` 和 `test_workbench_skill_commands.py`；验证依赖方向、真实TEMP排队与准确冻结版本，不能以页面展示替代执行证据。
- 正式后端来自不可变 `workbench-releases/`，前端来自 `native-releases/`；指针位于 `data/active-workbench.json` 和 `data/active-native.json`。不得手改历史资产。
- `launcher.pyw` 只监督私有profile。每个角色持有OS锁，进程接管/停止必须核对完整创建时间和准确启动参数。暂停文件不是进程已停止的证据。
- `.local/workbench-deployment/admission.json` 控制业务写入与后台启动；迁移期间外部 handoff/review CLI 也必须遵守 cutover/owner 标识，不能回落旧库。
- 部署先核对身份、空闲、原生队列和未知回执，再围栏停写、核对不可变前后端及技能源码。内置技能迁入只按预览 SHA 在停写期间新增版本与明确的默认 pin，不改写旧版本、旧任务或冻结输入，不恢复旧数据库。
- 业务数据仍以服务器为准；浏览器只保留获准输入、附件与操作身份/统计队列。保留原HTTPS origin、草稿键和未知请求身份；401/退出不删草稿。
- 模拟制作与平台操作只用TEMP数据和假执行器。明确区分合成执行、真实只读采集、实际Windows浏览器与模拟移动端，不冒称真实模型质量、真实发布或实体vivo验收。

## 迁移与维护记录

架构与验收记录位于 `docs/workbench/`，不可变候选和实际证据位于
`.local/workbench-validation/`、`.local/workbench-deployment/`。
两份外部CLI适配器位于 neo-content 的 `工具/内容工作流/`，它们验证活动manifest后
使用私有命名空间；修改时不得顺带改技能、规范、历史冻结输入或原话。

## 本项目 Codex Spec 命令

- 开发工作流入口为 `$codex-spec`，与 `skills/builtin/` 中的产品内容生产技能独立。
- 本项目文档及技能里的 `codex-spec ...` 一律通过 `pwsh -NoProfile -File ./scripts/codex-spec.ps1 ...` 调用；CLI 隔离在 `.runtime/codex-spec/`，不依赖全局安装。
- 复装使用 `pwsh -NoProfile -File ./scripts/install_codex_spec.ps1`；发行包 SHA256 已固定，安装、升级与旧记录归档位置见 `docs/workbench/CODEX-SPEC-20261101.md`。
- Codex Spec 沿用上述项目约定、准确版本和交付授权；不恢复旧 Spec Kit 阶段引擎，也不替代工作台的服务器事务、安装队列、业务技能注册或部署验收。人工反馈只记录真实用户反馈。

<!-- codex-spec:begin -->
## Codex Spec

Use `$codex-spec` for software changes, diagnosis and verification.
Read `.agents/skills/codex-spec/SKILL.md` when applying it.
Project knowledge is indexed by `.codex-spec/config.json`; load relevant sources.
Feature records live in `specs/<id>/spec.md`; use the relevant record explicitly.
Work in the current checkout. Multiple specs and conversations may run concurrently.
Commits reference `Spec:` and `Spec-Docs:` in the existing project message style.
<!-- codex-spec:end -->
