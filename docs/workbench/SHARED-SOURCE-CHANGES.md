# 共通源码差异台账

本台账回答“相对准确官方基线，哪些共通文件发生变化、为什么需要保留、归哪个私有能力维护、同步上游时检查什么”。**差异本身不等于错误，也不是删除或恢复功能的清单。**

逐文件理由与同步核对点的唯一明细是 [shared-source-changes.json](shared-source-changes.json)。本页提供阅读方法和文件/能力映射，不复制技能方法或建立运行时注册表。能力需求、状态与允许范围继续查 [私有能力登记表](PRIVATE-CAPABILITIES.md) 及对应维护卡，实际执行仍受本轮授权和原有回执边界约束。

## 对照范围

- 完整官方基线：`0f43dc98277eac85fb48952878acad349731d3fc`，来自 [upstream-base.json](upstream-base.json)；这不是远端当前最新main。
- 首版源码盘点：`49193c821055841ad6930eafd81cd662ff349be6`，2026-11-05；本次仅记录已有差异，没有启用新能力。
- 范围：`easel/**`、`web/app.py`、`web/frontend/src/**`，以及 `skills/shared/scripts/weixin_mp_stats.py`。
- 排除私有宿主 `web/frontend/src/workbench/**` 和私有头像资产 `web/frontend/src/assets/workbench/**`；它们仍需按所属能力维护卡登记，并非豁免私有能力规则。
- 共 **87** 个文件差异。官方PR来源及已审阅的私有blob仍以 [upstream-overlays.json](upstream-overlays.json) 为出处，不把官方选取补丁冒称全量同步。

## 分类与维护边界

| kind | 含义 | 当前文件数 |
| --- | --- | --- |
| `official-overlay` | 官方补丁 | 15 |
| `shared-extraction` | 共通提取 | 18 |
| `host-port` | 宿主端口 | 28 |
| `generic-fix` | 通用修复 | 6 |
| `private-policy` | 私有策略 | 1 |
| `mixed` | 混合差异 | 17 |

- `official-overlay`：本次盘点时文件blob与原官方补丁记录一致。不是说它永远不会变，也不通过本表锁死blob。仅有部分官方PR改动、又叠加宿主接缝的文件应登记为 `mixed`。
- `shared-extraction`：从原入口/组件最小提取并由两个入口调用同一实现，不意味着该新文件原本就在官方仓库。
- `host-port`：集中、可选的通用端口，默认调用沿用原行为，业务判断留在宿主。
- `generic-fix`：适合独立审查的通用可用性/可靠性修复；官方吸收后按实际语义去掉重复补丁。
- `private-policy`：已明确选择的私有策略，须连同适用条件和默认行为审查，不能当官方原默认。
- `mixed`：包含官方补丁与宿主端口/通用修复/私有策略等多种差异，按JSON中的理由及核对点逐项判断，不能整文件盲选 ours/theirs。

### 必须特别核对的接缝

- **CLI入口（PC-18）**：`easel web --profile workbench` 显式启动私有宿主，默认 `easel` 分支仍为原独立入口。这是共通文件内的宿主启动接缝，不能遗漏或当默认官方行为。
- **执行权限（PC-16，关联PC-03）**：`codex_auto_approve` 开启时映射为已选的 Full access；关闭时使用沙箱/原生权限确认。已有会话冻结配置；独立健康canary保有自己的严格权限，不能继承正式Full access。工具执行权限不增加平台发布、采纳或账号变更授权。
- **准确回执（PC-03）**：RunRequest/RPC/原生适配器只提供可选请求、回合、中断、消息及执行证据钩子；模型传输仍唯一。停止HTTP/CLI不是原生停止证明，unknown不重放。
- **控件/页面（PC-02、PC-10、PC-16）**：下拉定位、QuestionCards服务端口、受控主题、Drawer与设置API等均有具体差异条目。复用原文件不能被误写成“与官方完全无差异”。
- **共通服务（PC-20及业务ID）**：`easel/web_services` 是单一实现的提取与接缝目录。共享模块不能导入私有业务；binding只是兼容桥，不允许继续扩展函数替换或复制副本。
- **文件与列表（PC-13、PC-17）**：分页索引、鉴权下载、文本预览和本地文件链接各有独立合同；不能为了对齐上游重新拉取全树或丢失真实文件/授权约束。

## 逐文件映射

理由和具体更新检查见JSON中同路径的 `reason`、`upstream_check`；能力卡按 `capabilities` 中的ID查。状态 `A/M/D` 表示相对本次官方基线的新增/修改/删除，不表示业务启用状态。

| 共通路径 | 能力 ID | 分类 | Git 状态 |
| --- | --- | --- | --- |
| [easel/cli.py](../../easel/cli.py) | PC-18 | 宿主端口 | M |
| [easel/commands/doctor.py](../../easel/commands/doctor.py) | PC-20 | 官方补丁 | M |
| [easel/harnesses/acp.py](../../easel/harnesses/acp.py) | PC-03 | 宿主端口 | M |
| [easel/harnesses/base.py](../../easel/harnesses/base.py) | PC-03、PC-16、PC-19 | 宿主端口 | M |
| [easel/harnesses/codex.py](../../easel/harnesses/codex.py) | PC-03、PC-16、PC-17、PC-19 | 混合差异 | M |
| [easel/harnesses/openclaw.py](../../easel/harnesses/openclaw.py) | PC-03、PC-16 | 宿主端口 | A |
| [easel/harnesses/permissions.py](../../easel/harnesses/permissions.py) | PC-16 | 私有策略 | M |
| [easel/harnesses/rpc.py](../../easel/harnesses/rpc.py) | PC-03 | 宿主端口 | M |
| [easel/harnesses/workspace.py](../../easel/harnesses/workspace.py) | PC-03、PC-16 | 混合差异 | M |
| [easel/openclaw_workspace.py](../../easel/openclaw_workspace.py) | PC-20 | 官方补丁 | M |
| [easel/skills_sync.py](../../easel/skills_sync.py) | PC-20 | 官方补丁 | A |
| [easel/web_services/__init__.py](../../easel/web_services/__init__.py) | PC-20 | 共通提取 | A |
| [easel/web_services/accounts.py](../../easel/web_services/accounts.py) | PC-14 | 共通提取 | A |
| [easel/web_services/analytics.py](../../easel/web_services/analytics.py) | PC-15 | 共通提取 | A |
| [easel/web_services/binding.py](../../easel/web_services/binding.py) | PC-20 | 共通提取 | A |
| [easel/web_services/chat.py](../../easel/web_services/chat.py) | PC-03 | 共通提取 | A |
| [easel/web_services/concurrency.py](../../easel/web_services/concurrency.py) | PC-03、PC-13 | 共通提取 | A |
| [easel/web_services/environment.py](../../easel/web_services/environment.py) | PC-16 | 共通提取 | A |
| [easel/web_services/outputs.py](../../easel/web_services/outputs.py) | PC-13、PC-17 | 共通提取 | A |
| [easel/web_services/planning.py](../../easel/web_services/planning.py) | PC-05、PC-07、PC-13 | 共通提取 | A |
| [easel/web_services/profiles.py](../../easel/web_services/profiles.py) | PC-11 | 共通提取 | A |
| [easel/web_services/settings.py](../../easel/web_services/settings.py) | PC-16 | 共通提取 | A |
| [easel/web_services/skills.py](../../easel/web_services/skills.py) | PC-10、PC-08、PC-09 | 共通提取 | A |
| [easel/web_services/uploads.py](../../easel/web_services/uploads.py) | PC-17 | 共通提取 | A |
| [web/app.py](../../web/app.py) | PC-03、PC-10、PC-11、PC-14、PC-16、PC-17 | 共通提取 | M |
| [web/frontend/src/App.tsx](../../web/frontend/src/App.tsx) | PC-02、PC-03、PC-07 | 宿主端口 | M |
| [web/frontend/src/assets/platform/README.md](../../web/frontend/src/assets/platform/README.md) | PC-20 | 官方补丁 | A |
| [web/frontend/src/assets/platform/bilibili.svg](../../web/frontend/src/assets/platform/bilibili.svg) | PC-20 | 官方补丁 | A |
| [web/frontend/src/assets/platform/kuaishou.svg](../../web/frontend/src/assets/platform/kuaishou.svg) | PC-20 | 官方补丁 | A |
| [web/frontend/src/assets/platform/wechat.svg](../../web/frontend/src/assets/platform/wechat.svg) | PC-20 | 官方补丁 | A |
| [web/frontend/src/assets/platform/xiaohongshu.svg](../../web/frontend/src/assets/platform/xiaohongshu.svg) | PC-20 | 官方补丁 | A |
| [web/frontend/src/assets/platform/zhihu.svg](../../web/frontend/src/assets/platform/zhihu.svg) | PC-20 | 官方补丁 | A |
| [web/frontend/src/components/AccountsPage.tsx](../../web/frontend/src/components/AccountsPage.tsx) | PC-14、PC-02 | 混合差异 | M |
| [web/frontend/src/components/ArtifactGallery.tsx](../../web/frontend/src/components/ArtifactGallery.tsx) | PC-12、PC-17 | 混合差异 | M |
| [web/frontend/src/components/BreakdownPage.tsx](../../web/frontend/src/components/BreakdownPage.tsx) | PC-26、PC-02 | 宿主端口 | M |
| [web/frontend/src/components/BrushEntry.tsx](../../web/frontend/src/components/BrushEntry.tsx) | PC-10、PC-02 | 宿主端口 | M |
| [web/frontend/src/components/CalendarPage.tsx](../../web/frontend/src/components/CalendarPage.tsx) | PC-02、PC-04、PC-13 | 宿主端口 | M |
| [web/frontend/src/components/ChatPage.tsx](../../web/frontend/src/components/ChatPage.tsx) | PC-03、PC-04、PC-10、PC-17 | 混合差异 | M |
| [web/frontend/src/components/ContentPanel.tsx](../../web/frontend/src/components/ContentPanel.tsx) | PC-02 | 混合差异 | A |
| [web/frontend/src/components/CopyableText.tsx](../../web/frontend/src/components/CopyableText.tsx) | PC-02、PC-12 | 共通提取 | A |
| [web/frontend/src/components/DashboardPage.tsx](../../web/frontend/src/components/DashboardPage.tsx) | PC-05、PC-07、PC-13、PC-02 | 混合差异 | M |
| [web/frontend/src/components/DownloadLink.tsx](../../web/frontend/src/components/DownloadLink.tsx) | PC-17 | 宿主端口 | A |
| [web/frontend/src/components/Drawer.tsx](../../web/frontend/src/components/Drawer.tsx) | PC-02 | 共通提取 | A |
| [web/frontend/src/components/EnvBoard.tsx](../../web/frontend/src/components/EnvBoard.tsx) | PC-16 | 宿主端口 | M |
| [web/frontend/src/components/HarnessSettings.tsx](../../web/frontend/src/components/HarnessSettings.tsx) | PC-16、PC-02 | 混合差异 | M |
| [web/frontend/src/components/IdeasPage.tsx](../../web/frontend/src/components/IdeasPage.tsx) | PC-04、PC-07、PC-13 | 混合差异 | M |
| [web/frontend/src/components/InteractionNotice.tsx](../../web/frontend/src/components/InteractionNotice.tsx) | PC-02 | 共通提取 | A |
| [web/frontend/src/components/ManualPublishPage.tsx](../../web/frontend/src/components/ManualPublishPage.tsx) | PC-15、PC-17 | 宿主端口 | M |
| [web/frontend/src/components/MessageBubble.tsx](../../web/frontend/src/components/MessageBubble.tsx) | PC-03、PC-17 | 混合差异 | M |
| [web/frontend/src/components/OnboardingWizard.tsx](../../web/frontend/src/components/OnboardingWizard.tsx) | PC-11、PC-02 | 宿主端口 | M |
| [web/frontend/src/components/OutputsPage.tsx](../../web/frontend/src/components/OutputsPage.tsx) | PC-12、PC-13、PC-17 | 宿主端口 | M |
| [web/frontend/src/components/ProfilePage.tsx](../../web/frontend/src/components/ProfilePage.tsx) | PC-11、PC-04、PC-13 | 混合差异 | M |
| [web/frontend/src/components/PublishingPage.tsx](../../web/frontend/src/components/PublishingPage.tsx) | PC-15 | 宿主端口 | M |
| [web/frontend/src/components/QuestionCards.tsx](../../web/frontend/src/components/QuestionCards.tsx) | PC-03 | 宿主端口 | M |
| [web/frontend/src/components/ResponsiveSidebar.tsx](../../web/frontend/src/components/ResponsiveSidebar.tsx) | PC-02 | 共通提取 | A |
| [web/frontend/src/components/SettingsApi.ts](../../web/frontend/src/components/SettingsApi.ts) | PC-16 | 宿主端口 | A |
| [web/frontend/src/components/SettingsPanel.tsx](../../web/frontend/src/components/SettingsPanel.tsx) | PC-16、PC-02 | 宿主端口 | M |
| [web/frontend/src/components/SettingsSelect.tsx](../../web/frontend/src/components/SettingsSelect.tsx) | PC-02、PC-16 | 通用修复 | M |
| [web/frontend/src/components/Sidebar.tsx](../../web/frontend/src/components/Sidebar.tsx) | PC-02、PC-03 | 宿主端口 | M |
| [web/frontend/src/components/SkillDrawer.tsx](../../web/frontend/src/components/SkillDrawer.tsx) | PC-10、PC-02 | 混合差异 | M |
| [web/frontend/src/components/SkillPage.tsx](../../web/frontend/src/components/SkillPage.tsx) | PC-10、PC-13 | 宿主端口 | M |
| [web/frontend/src/components/TextArtifact.tsx](../../web/frontend/src/components/TextArtifact.tsx) | PC-17 | 通用修复 | A |
| [web/frontend/src/components/ThemeToggle.tsx](../../web/frontend/src/components/ThemeToggle.tsx) | PC-02 | 宿主端口 | M |
| [web/frontend/src/components/TrendSourcesDialog.tsx](../../web/frontend/src/components/TrendSourcesDialog.tsx) | PC-05、PC-02、PC-04 | 混合差异 | M |
| [web/frontend/src/components/TrendsPage.tsx](../../web/frontend/src/components/TrendsPage.tsx) | PC-05、PC-07、PC-13、PC-02 | 混合差异 | M |
| [web/frontend/src/components/icons.tsx](../../web/frontend/src/components/icons.tsx) | PC-10、PC-20 | 官方补丁 | M |
| [web/frontend/src/components/skillIconsBrand.tsx](../../web/frontend/src/components/skillIconsBrand.tsx) | PC-10、PC-20 | 官方补丁 | A |
| [web/frontend/src/components/skillIconsPlanning.tsx](../../web/frontend/src/components/skillIconsPlanning.tsx) | PC-10、PC-20 | 官方补丁 | A |
| [web/frontend/src/components/skillIconsProduce.tsx](../../web/frontend/src/components/skillIconsProduce.tsx) | PC-10、PC-20 | 官方补丁 | A |
| [web/frontend/src/components/skillIconsPublish.tsx](../../web/frontend/src/components/skillIconsPublish.tsx) | PC-10、PC-20 | 官方补丁 | A |
| [web/frontend/src/components/useBrushPopover.ts](../../web/frontend/src/components/useBrushPopover.ts) | PC-02、PC-10 | 通用修复 | A |
| [web/frontend/src/lib/api.ts](../../web/frontend/src/lib/api.ts) | PC-01、PC-03、PC-10、PC-13、PC-16 | 宿主端口 | M |
| [web/frontend/src/lib/artifacts.ts](../../web/frontend/src/lib/artifacts.ts) | PC-12、PC-17 | 通用修复 | M |
| [web/frontend/src/lib/download.ts](../../web/frontend/src/lib/download.ts) | PC-17 | 宿主端口 | A |
| [web/frontend/src/lib/interaction.ts](../../web/frontend/src/lib/interaction.ts) | PC-02、PC-03 | 通用修复 | A |
| [web/frontend/src/lib/linkifyOutputs.ts](../../web/frontend/src/lib/linkifyOutputs.ts) | PC-12、PC-17 | 混合差异 | M |
| [web/frontend/src/lib/outputBrowser.ts](../../web/frontend/src/lib/outputBrowser.ts) | PC-13 | 宿主端口 | A |
| [web/frontend/src/lib/outputNavigation.ts](../../web/frontend/src/lib/outputNavigation.ts) | PC-12、PC-13 | 宿主端口 | A |
| [web/frontend/src/lib/personas.ts](../../web/frontend/src/lib/personas.ts) | PC-11、PC-20 | 官方补丁 | A |
| [web/frontend/src/lib/skillDisplayNames.ts](../../web/frontend/src/lib/skillDisplayNames.ts) | PC-10、PC-20 | 混合差异 | M |
| [web/frontend/src/lib/trendValidation.ts](../../web/frontend/src/lib/trendValidation.ts) | PC-05 | 宿主端口 | M |
| [web/frontend/src/lib/viewState.ts](../../web/frontend/src/lib/viewState.ts) | PC-02、PC-04 | 宿主端口 | A |
| [web/frontend/src/lib/visiblePoll.ts](../../web/frontend/src/lib/visiblePoll.ts) | PC-02、PC-14 | 通用修复 | A |
| [web/frontend/src/lib/whoami.ts](../../web/frontend/src/lib/whoami.ts) | PC-14、PC-13 | 宿主端口 | M |
| [web/frontend/src/styles/index.css](../../web/frontend/src/styles/index.css) | PC-02、PC-12、PC-17 | 混合差异 | M |

## 后续变更如何维护

1. 先核对相关维护卡与当前上游实现，再判断是否确需修改共通文件；能仅通过现有端口完成则不扩大公共差异。
2. 新增/移除共通差异或改变职责时，同提交更新JSON的路径、能力ID、分类、理由及同步核对点；文件内容改变但职责未变时，仍须审查现有条目是否充分，无需仅为过门槛更新无意义的blob哈希。
3. 同步官方后，以新准确基线重新比较，移除已不再存在的差异条目；保存原Git历史，不修改旧发布manifest。不能删除一行台账就绕过真实文件差异。
4. 本表不是审批系统；只有用户或已确认业务需求能够决定功能范围。C/U条目可记录兼容和待核对差异，绝不因登记而自动获批。
5. 文档检查只证明差异被解释、路径和归属可查，不能替代双入口构建、相关业务回归、视觉或真实设备/网络验收。

## 2026-11-06 公众号逐文章统计

新增登记 `skills/shared/scripts/weixin_mp_stats.py`（PC-14/PC-15）。保留原登录和统计流程，仅补有界文章窗口、准确URL身份与缺失值语义。实际理由和同步核对点见结构化台账；发布链接由用户手动提供，不自动发布。
