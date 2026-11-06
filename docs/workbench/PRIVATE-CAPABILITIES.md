# 私有能力登记表

这是 AI 和维护者查找“我们增加了什么、在哪里接入 Easel、哪些不能继续扩展”的唯一文档索引。每项独立能力有一份维护卡；卡片链接当前源码、需求依据和验证入口，不复制技能方法或另建运行时注册表。

首版盘点日期：**2026-11-05**，首版业务源码基线 `1901f832684e8d11f3d63bdca70aa0a803f37916`。本次按 `49193c8` 及后续复核整改补全到36张维护卡；官方完整集成基线仍以 [upstream-base.json](upstream-base.json) 为准，选取的 PR 另见 [upstream-overlays.json](upstream-overlays.json)，不将本次整改冒称跟进官方最新main。部署与验证结果另按 [本轮 Spec](../../specs/private-registry-hardening-20261105/spec.md) 记录，登记表自身不证明已上线。

## 使用方法与状态

最近一次完整复核与正式交付见 [2026-11-05整改记录](PRIVATE-REGISTRY-HARDENING-20261105.md)：业务源码bb68720，36张卡及85个受审共通源码差异；开发门控、Git结果和活动配对分别登记，首版只读说明不代表此后的部署状态。

开发前依次阅读 [AGENTS.md 的强制规则](../../AGENTS.md)、本表对应行、独立维护卡，再进入当前源码及相关 Spec。历史架构和交付记录用于追溯，不能覆盖用户最新决定或当前退役状态。

- **已确认保留（PC）**：已有需求对应的能力边界；允许维护该边界，不代表任意扩大功能或取得制作、采纳、发布授权。
- **退役／兼容（C）**：为历史、迁移或受理任务保留的代码，不能作为新增功能许可。
- **存量核对记录（U）**：保留初版核对ID及本轮结论；已核对/已分类不等于新能力批准，仍保留各调用的限制，不授予新增许可或直接删除授权。
- 文档描述的能力状态不等同于每个函数都正确实现或已通过本轮运行验收。首版是按页面组装、服务入口、SKILL 与既有记录建立的能力级清单，不是逐行代码合规证明。新发现的遗漏必须补登记，不因“首版没列”自动删除或默认获批。

## 已确认能力（30 项）

表内的“官方复用／共通接缝”列是阅读入口，完整代码、合同与验证入口见各维护卡。文件被引用不表示它全部属于私有代码；改动官方文件时还须核对实际 diff。

| 登记 ID / 专门维护文档 | 类型 | 保留的私有边界 | 官方复用／共通接缝 |
| --- | --- | --- | --- |
| [PC-01 工作台访问、身份与请求安全](private-capabilities/PC-01-owner-access.md) | 宿主适配 | TOTP 登录、服务器会话、同源/CSRF、操作身份与准入；Tailscale 仅提供网络暴露，不承载业务。 | `App.tsx`、`api.ts` |
| [PC-02 原生外壳与移动端宿主适配](private-capabilities/PC-02-native-host.md) | 共通适配 | 六主入口、导航/返回/焦点、触控会话长按菜单及其遮罩、移动视口/键盘、统一状态卡与静默刷新。 | `App.tsx`、`Sidebar.tsx`、`ResponsiveSidebar.tsx`、`Drawer.tsx`、`InteractionNotice.tsx` |
| [PC-03 服务器会话、持久受理与停止恢复](private-capabilities/PC-03-persistent-chat.md) | 可靠性适配 | 准确回执、原生终态核对、停止恢复及首条标题原子保存；保留冻结输入，未知不重发。 | `chat.py`、`codex.py`、`ChatPage.tsx` |
| [PC-04 本机草稿、附件及离线输入保留](private-capabilities/PC-04-local-inputs.md) | 私有保留 | 获准的浏览器草稿、IndexedDB 附件、操作身份、页面位置和恢复入口；不在浏览器建立业务历史主库。 | `ChatPage.tsx`、`IdeasPage.tsx` |
| [PC-05 自定义来源、自动采集与当天面板](private-capabilities/PC-05-collection.md) | 私有业务 | 来源修订、排期 slot、任务身份、入库/去重/回执、当日视图和明确手动采集。 | `runner.py`、`TrendsPage.tsx`、`DashboardPage.tsx` |
| [PC-06 新闻摘要、中文标题与原始反馈](private-capabilities/PC-06-news-intelligence.md) | 私有业务 | 新闻概览、标题增强、原文/判断区分、准确来源和反馈记录；仅在既有任务边界调用只读执行。 | `TrendsPage.tsx`、`DashboardPage.tsx`、`codex.py` |
| [PC-07 私有新闻原文页与讨论/创作衔接](private-capabilities/PC-07-news-creation.md) | 私有业务 | 来源阅读、讨论与制作的显式选择、风格及角色素材、准确新闻关联、完整冻结输入和消息内新闻链接。 | `Drawer.tsx`、`ChatPage.tsx`、`skills.py` |
| [PC-08 油猪·做贴图](private-capabilities/PC-08-oil-pig-poster.md) | 业务 SKILL | 微信公众号贴图制作、贴图修改、准确角色/画面风格、参考资源及成品文件；方法正文只在本技能维护。 | `skills.py`、`SkillPage.tsx` |
| [PC-09 油猪·做文章](private-capabilities/PC-09-oil-pig-article.md) | 业务 SKILL | 选题/提纲/完整文章或局部修改、按需配图与 HTML 等指定交付；以本技能正文和本轮要求为准。 | `skills.py`、`SkillDrawer.tsx` |
| [PC-10 原生技能宿主、配置与私有图标](private-capabilities/PC-10-native-skill-host.md) | 共通适配 | 磁盘 SKILL 目录、详情/资源、配置修订、服务器操作身份和私有图标注入；支持技能另见 PC-22 至 PC-27。 | `skills.py`、`SkillPage.tsx`、`SkillDrawer.tsx` |
| [PC-11 版本化画像、素材与账号绑定](private-capabilities/PC-11-profiles.md) | 私有业务 | 画像稳定 ID、修订/历史、素材绑定、账号归属、默认保护、明确导入及后台增强的安全存储。 | `profiles.py`、`ProfilePage.tsx`、`OnboardingWizard.tsx` |
| [PC-12 准确作品版本、修改、采纳与反馈](private-capabilities/PC-12-versioned-works.md) | 私有业务 | 对话采纳/不采纳只更新准确产物目录状态标记，保留原话、范围和子版本；不触发归档或 Git。 | 原生会话与内容库，私有服务接入 |
| [PC-13 内容索引、分层请求与返回性能](private-capabilities/PC-13-read-performance.md) | 可靠性适配 | 摘要/目录/详情/文件分层、会话历史窗口、内容索引、缓存代数、失效标签和有界读取。 | `OutputsPage.tsx`、`SkillPage.tsx`、`ProfilePage.tsx` |
| [PC-14 真实账号身份与私有授权台账](private-capabilities/PC-14-account-ledger.md) | 共通适配 | 原生登录和退出与私有账号 ID/连接修订映射；历史凭据、授权与读回证据保持。 | `accounts.py`、`AccountsPage.tsx` |
| [PC-15 准确渠道稿、交付授权与回执](private-capabilities/PC-15-authorized-delivery.md) | 私有业务 | 渠道稿修订、实际账号、动作批准、草稿/发布/读回回执与只读核对；保留已有交付记录。 | `PublishingPage.tsx`、`manual_publish.py`、`web_publisher.py` |
| [PC-16 配置修订、凭据与隔离安装队列](private-capabilities/PC-16-settings-installation.md) | 共通适配 | 服务器加密凭据、会话准确配置、明确保存、环境/依赖检测和持久安装操作身份。 | `settings.py`、`environment.py`、`SettingsPanel.tsx` |
| [PC-17 附件上传、文件预览、下载与导出](private-capabilities/PC-17-artifact-delivery.md) | 共通适配 | 附件 ID/幂等注册、流式上传、受保护预览、限时下载凭证、HEAD/Range、导出与原件 SHA。 | `uploads.py`、`outputs.py`、`DownloadLink.tsx` |
| [PC-18 托管运行、不可变配对与安全部署](private-capabilities/PC-18-runtime-delivery.md) | 运维能力 | 角色监督、OS 锁与进程身份、活动前后端指针、写入围栏、准确候选验收、旧包归档和保留未知回执。 | `rpc.py`、`chat.py` |
| [PC-19 独立健康中控与每日全链路检查](private-capabilities/PC-19-independent-health.md) | 运维能力 | 项目外监控进程、入口/业务/性能及独立公网探测、受控恢复、隔离浏览器旅程及每日真实 Agent canary；外网异常不误重启健康后端。 | `codex.py` |
| [PC-20 官方基线、PR 补丁及 fork 交付](private-capabilities/PC-20-upstream-maintenance.md) | 开发维护 | 基线/PR记录、同步技能、公共差异逐文件台账、登记自动门禁与可复现fork交付；不替代业务授权。 | `app.py`、`App.tsx`、`web_services` |
| [PC-21 项目 Codex Spec 工作流与维护知识](private-capabilities/PC-21-project-tooling.md) | 开发维护 | 项目开发技能、隔离 CLI、spec 记录、维护文档和本私有能力速查表；与产品内容技能分开。 | 不修改产品代码；仅开发工作流 |
| [PC-22 油猪·选题研究](private-capabilities/PC-22-topic-research.md) | 新选择入口停用，历史兼容 | 讨论、选题与新闻增强的方法和事实边界；是否调用由本轮所选技能或既有明确调用链决定。 | `skills.py`、`SkillDrawer.tsx` |
| [PC-23 油猪·图文写作](private-capabilities/PC-23-content-writing.md) | 新选择入口停用，历史兼容 | 结构、表述、事实与原字约束；供明确选择的内容流程组合，不将所有文章变成贴图。 | `skills.py`、`SkillDrawer.tsx` |
| [PC-24 油猪·配图制作与核验](private-capabilities/PC-24-image-production.md) | 新选择入口停用，历史兼容 | 根据准确输入制作配图，保留参考素材和真实产物；按需组合，不冒称实际调用未发生的生图能力。 | `skills.py`、`SkillDrawer.tsx` |
| [PC-25 油猪·交付核验](private-capabilities/PC-25-delivery-review.md) | 新选择入口停用，历史兼容 | 按准确版本的真实文件/合同核对交付，区分制作方自检与独立核验；不自动采纳或发布。 | `skills.py`、`SkillDrawer.tsx` |
| [PC-26 油猪·参考拆解](private-capabilities/PC-26-reference-analysis.md) | 新选择入口停用，历史兼容 | 读取明确指定的参考、保留事实和判断边界；分析不自动发布为长期技能或经验。 | `skills.py`、`SkillDrawer.tsx` |
| [PC-27 油猪·发布复盘](private-capabilities/PC-27-publication-analysis.md) | 新选择入口停用，历史兼容 | 基于实际发布/反馈证据复盘，不凭生成结果虚构曝光或平台回执，不自动改规则。 | `skills.py`、`SkillDrawer.tsx` |
| [PC-28 页面性能诊断](private-capabilities/PC-28-page-performance.md) | 可靠性诊断 | 首屏、导航和慢请求的脱敏有界汇总与中控内存观察，不触碰草稿或业务操作。 | 私有宿主与原页面就绪接缝 |
| [PC-29 油猪·学习贴图](private-capabilities/PC-29-oil-pig-learn-poster.md) | 业务 SKILL | 独立分析指定贴图，学习不触发制作或规则更改。 | Easel 原生技能页 |
| [PC-30 油猪·学习文章](private-capabilities/PC-30-oil-pig-learn-article.md) | 业务 SKILL | 独立分析指定文章，学习不触发写稿或规则更改。 | Easel 原生技能页 |

### 技能登记边界

当前 `ProjectSkillCatalog` 读取两个油猪制作技能和两个独立学习技能：[PC-29 学习贴图](private-capabilities/PC-29-oil-pig-learn-poster.md)、[PC-30 学习文章](private-capabilities/PC-30-oil-pig-learn-article.md)。旧组合及六个辅助技能原文已归档，不再作为技能发现或执行；旧业务数据保留，但不提供旧技能历史兼容入口。其余官方内置技能继续由官方目录和流程管理。

油猪·做贴图与油猪·做文章分别维护，互不套用流程。方法正文、资源和组合依赖以各自 `SKILL.md` 为准；本表仅登记业务边界和接入位置。开发技能 `codex-spec`、`easel-upstream-sync` 与产品内容技能分开登记。

## 退役与受限兼容代码（7 项，不是新增许可）

| 登记 ID / 专门记录 | 状态 | 保留或限制的内容 |
| --- | --- | --- |
| [C-01 私有技能管理与整理经验](private-capabilities/C-01-retired-skill-management.md) | 已退役／历史只读 | 候选、试用、发布/回退、私有技能 pins 与整理经验；保留历史版本、原任务及准确回执。 |
| [C-02 旧生产/媒体执行与 vendor](private-capabilities/C-02-legacy-production-media.md) | 兼容受限／部分入口已退役 | 旧任务的核对、进程及准确源码保护，旧媒体/生产方法与历史 vendor 原件。 |
| [C-03 旧工作台、通知、资料库与自动检测](private-capabilities/C-03-retired-entrypoints.md) | 已退役／迁移兼容 | 旧 URL、旧壳/SW/安装入口、通知/设备、个人资料库、旧桥接与自动账号检测；旧统计页面不恢复，已有队列/历史保持。 |
| [C-04 旧 content-production 组合技能](private-capabilities/C-04-legacy-content-production-skill.md) | 已归档／不再执行 | 保留旧业务数据；不要求旧技能历史兼容。新贴图/文章入口分别使用 PC-08/PC-09。 |
| [C-05 本地项目关联、作品归档与 Git 同步存量](private-capabilities/C-05-local-project-operations.md) | 受限兼容／保留原操作 | 分别登记项目绑定/重试写入口、local_io worker开关、原决定和准确文件Git意图；不新增外部同步授权。 |
| [C-06 证据索引、分类与分析设置存量](private-capabilities/C-06-evidence-index-compatibility.md) | 受限兼容／确定性索引与历史 | 区分仍可写的索引/分类/设置和HTTP层410的分析/提案动作；自动模型学习持续关闭。 |
| [C-07 旧创作配方、图稿方案与样本导入存量](private-capabilities/C-07-legacy-creative-recipes.md) | 兼容受限／混合读写 | 区分只读预览、原件导入/方案保存、可能排Agent讨论的准备动作及退役参数预设；不恢复旧生产页。 |

## 已核对存量记录（2 项，不是新增许可）

保留首版U-ID用于追溯，本轮已纠正用途推断并完成逐路由分类。下列结论保留准确版本/授权边界，不意味着所有旧实现都需要删除、全部获准扩展或已经完成真实业务验收。

| 登记 ID / 专门记录 | 已见存量与需要核对的范围 |
| --- | --- |
| [U-01 已核对的采纳与准确版本记录边界](private-capabilities/U-01-completion-options-review.md) | 已核对：三种完成mode与质量token不是整理经验；准确版本只读记录不等同已删除的会话“本轮创作设置”。归PC-12/PC-15保留。 |
| [U-02 旧生产写入口的逐路由归类](private-capabilities/U-02-legacy-write-path-review.md) | 已分类：写/排队/只读/410逐项列出并关联PC/C卡；新普通草稿按明确format选两个油猪技能，旧受理身份不改写。 |

## 官方修改面与同步核对

采用 [适配点文档](ADAPTATION-POINTS.md) 中的端口与适配器、集中组装、可选扩展槽及边界装饰。共享页面和处理函数只保留一份。下面是集中核对位置，不是新建第二套页面或服务的许可。

实际公共源码差异统一查 [逐文件台账](SHARED-SOURCE-CHANGES.md) 及其 [结构化原件](shared-source-changes.json)：按路径、能力ID、官方PR/通用修复/宿主接缝分类，记录原因和同步核对点。维护卡通过ID关联此唯一清单，不复制第二份85文件列表；“文件与官方基线不同”不自动等于私有业务或应当删除。

| 共通位置 | 关联能力 | 必要接缝与更新时核对 |
| --- | --- | --- |
| `App.tsx`、原侧栏、`ResponsiveSidebar`、`Drawer`、`InteractionNotice` | PC-02 | 应用壳、布局与控件由共通实现提供；宿主仅组装路由、状态和扩展内容。原入口默认行为、移动几何和焦点仍需分别验证。 |
| `lib/api.ts`、`lib/whoami.ts` | PC-01、PC-13、PC-14 | 请求绑定、身份、缓存代数和账号核验策略集中在宿主，不散布鉴权分支。 |
| `ChatPage`、共享 `chat.py`、原 harness | PC-03、PC-04、PC-17 | 继续复用模型传输、消息和问题 UI；持久受理、停止意图、冻结配置及未知不重放在边界保留。 |
| `SkillPage`、`SkillDrawer`、共享 `skills.py` | PC-08～10、PC-22～27 | 原详情、配置与执行为唯一流程；私有 SKILL/图标通过数据或可选映射接入，不能隐藏原区域或引入候选前提。 |
| `ProfilePage`、`OnboardingWizard`、共享 `profiles.py` | PC-11 | 原表单/向导与构造函数共用；版本、素材、账号映射由服务器存储适配。 |
| `DashboardPage`、`TrendsPage`、`IdeasPage`、`CalendarPage`、`BreakdownPage`、共享 planning/analytics | PC-05～07、PC-13 | 共通页及 CRUD 复用，来源/存储适配；私有新闻页只承接自己的阅读和创作输入，不重写官方会话。 |
| `OutputsPage`、`DownloadLink`、共享 outputs/uploads | PC-12、PC-13、PC-17 | 原列表、详情与文件读取共用；准确版本、授权和输入保留在私有边界。 |
| `AccountsPage`、`SettingsPanel`、`PublishingPage`、共享 accounts/settings/environment | PC-14～16 | 登录、设置和安装方法共用；连接态不代表交付授权，已有配置修订和回执不得丢失。 |
| 基线记录、PR overlay、审计与双入口检查 | PC-20 | 区分官方已集成基线、额外 PR、通用修复及私有适配；只推自有 fork，移除已被官方吸收的适配。 |

`easel/web_services/` 中有为复用而从官方入口**最小提取的共享函数**；不表示所有文件原本就存在于官方仓库。公共模块不得反向依赖 `easel_workbench` 或私有前端。具体理由、文件和测试沿维护卡及 [ADAPTATION-POINTS.md](ADAPTATION-POINTS.md) 核对；新增官方差异须在所属卡明确写出，不能只登记目录名。

## 新增与维护时必须完成

1. 先找已有官方实现及已有 PC-ID。能直接复用就不新增实现；属于已有能力的扩展更新原卡，独立能力另建稳定 ID。
2. 每张维护卡必须写清：状态/日期、用户需求或 Spec、允许范围、官方复用位置与必要修改理由、实际影响的官方文件、私有代码/API/存储入口、不可破坏合同、验证入口及上游更新/退役核对点。没有 HTTP 或存储的能力明确写“无独立接口/存储”，不创造多余机制。
3. 新卡放在 `docs/workbench/private-capabilities/<ID>-<name>.md`，在本表登记并链接。不得仅改本表一行而没有专门文档，或把运行时自动扫描结果当作用户授权。
4. 新能力/能力范围变更的登记、维护卡、实现和必要验证同一提交交付；纯维护修复不扩能力时按PC-20的maintenance规则声明原能力和理由，新增私有源码仍必须在所属卡登记。接口/存储名称应引用唯一源码，技能方法应引用原SKILL，不复制第二份实现或正文。自动检查能发现漏登记/失效路径，不能自动批准需求。
5. 功能迁移、退役、移除或被官方吸收时，同步更新本表、维护卡和官方差异；保留旧 ID 与历史依据。未登记或范围不清的存量先标记待核对，不在无需求依据时扩大或直接清理。

## 首版与本轮复核范围

首版按主入口、原生API/技能绑定、业务服务、运维入口及历史决定建立33张卡，其原始文档验证与只读限制保留在 [首版 Spec](../../specs/private-capability-registry-20261105/spec.md)。本轮复核拆出C-05/C-06/C-07，现为27项PC、7项C、2项U，共36张卡，并补齐官方差异、油猪工具、质量确认与入口门控事实；实际构建、测试、提交和部署分别见 [本轮 Spec](../../specs/private-registry-hardening-20261105/spec.md)。任何文档分类均不代替真实模型、平台发布或实体4G/WebToApp验收。

2026-11-05：PC-08、PC-09、PC-22～PC-27 按 Easel 技能写法补充画像、输入、流程和输出说明；见 [技能规范 Spec](../../specs/private-skill-conventions-20261105/spec.md)。

2026-11-06：PC-05/06/19修复后台新闻对退役技能的依赖、当天中文标题结果健康；PC-11提供唯一画像只读接缝。见 [后台合同修复](../../specs/background-news-contracts-20261106/spec.md)，不恢复退役技能或旧缓存。
