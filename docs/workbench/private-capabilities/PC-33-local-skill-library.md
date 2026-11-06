# PC-33 本地第三方技能库、分类与辅助选择

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

- **状态：** 已确认新增；本轮正在实现与验证，提交、推送、安装及正式上线分别记录。
- **需求依据：** 用户明确要求全量接入其列出的29个仓库，中文展示、油猪头像加分类角标、技能分类与显眼的当前仓库Star，并尽量复用Easel；两个油猪制作技能允许显式选用其他写作方法。完整边界见[本轮Spec](../../../specs/local-skill-library-20261107/spec.md)。
- **能力范围：** 完整来源本地安装、准确提交和文件哈希清单、来源及细分类筛选、Star排序和核查时间、原生技能详情/执行入口，以及每阶段最多一个辅助方法的明确选择。保持官方六层分组。索引仓库仅安装其自身有效技能，不递归安装其链接指向的其他仓库；不把安装等同真实工具验证。
- **官方复用与必要差异：** 唯一原[SkillPage](../../../web/frontend/src/components/SkillPage.tsx)、[SkillDrawer](../../../web/frontend/src/components/SkillDrawer.tsx)、[技能服务](../../../easel/web_services/skills.py)、原生Agent和停止/回执流程。共享页面只提供可选展示端口、通用展示名和阻塞原因；分类、仓库数据和业务选择留在私有层。没有私有平行页面、技能执行器或模型工作流。
- **不可破坏的合同：** 原生产技能未选辅助时保持；贴图不套文章排版；所选方法不继承第三方账号、作者经历、自动学习或发布授权，不重新询问已经提供的任务范围。旧冻结输入及未知回执保持且不重放。第三方原文、依赖、本地生成入口及归档只留本机，不提交公开fork；许可证保留原件，不因个人使用改写授权。

**接口与状态归属：** [本地库](../../../easel_workbench/features/local_skills/)仅管理目录与准确输入；[HTTP宿主](../../../easel_workbench/http/chat.py)沿用鉴权/CSRF，提供`GET /api/local-skills`、`GET /api/local-skills?view=sources`、`GET /api/local-skills/sources`和`POST /api/local-skills/sources/refresh`。列表和来源视图只传摘要，详情按需读正文，执行前只冻结选定包与必要同仓资源。原件、安装清单、catalog与独立Star缓存位于Git忽略的`.local/third-party-skills/`；本轮输入在`outputs/_sessions/local-skill-inputs/<turn>/`。没有独立业务数据库或技能执行状态机。

**来源与安装：** [29源清单](../../../config/local-skill-sources.json)、[安装入口](../../../scripts/install_workbench_local_skills.py)和[安装实现](../../../easel_workbench/features/local_skills/install.py)复用skill-installer原有Git稀疏克隆、准确SHA检出及归档下载/安全解压帮助函数；来源获取最多3个并发，安装持有本地锁，完整校验并生成入口后一次激活目录。保留完整资源与许可，禁用Git钩子和交互凭据，不在下载/检出/安装时执行第三方脚本或包管理器。归档链路实测速度过低导致超时，当前优先使用原helper的Git获取，归档帮助函数保留为兼容后备。未具备CLI、登录或外部服务的条目须明确待配置，不能虚报可用。生成的`skills/builtin/local-*/`仅供原生发现，过期/未登记入口不可新执行，旧原件不覆盖历史。

**展示与选择：** [分类与中文标签](../../../easel_workbench/features/local_skills/taxonomy.py)、[私有筛选/来源/辅助选择](../../../web/frontend/src/workbench/ui/LocalSkillLibrary.tsx)、[扩展样式](../../../web/frontend/src/workbench/ui/local-skills.css)、[NativeSkills组装](../../../web/frontend/src/workbench/ui/NativeSkills.tsx)及[小猪图标](../../../web/frontend/src/workbench/ui/skillIcons.tsx)。原[API类型](../../../web/frontend/src/lib/api.ts)只加可选展示字段，原[会话选择器](../../../web/frontend/src/workbench/ui/ChatSessionView.tsx)使用同一中文名。原[新闻制作抽屉](../../../web/frontend/src/workbench/ui/NewsCreationDrawer.tsx)、[请求类型](../../../web/frontend/src/workbench/ui/newsCreation.ts)传送阶段→技能ID与库修订；[新闻服务](../../../easel_workbench/features/news_creation.py)和[会话受理](../../../easel_workbench/application/chat.py)验证后交给[原生技能宿主](../../../easel_workbench/runtime/native_skills.py)，固定资源由[目录服务](../../../easel_workbench/features/local_skills/catalog.py)提供，同一Agent应用方法。

**Star与性能边界：** [Star服务](../../../easel_workbench/features/local_skills/stars.py)按来源仓库共享缓存，后台24小时TTL及手动刷新，串行条件请求、304和限流退避；原页面请求不等待GitHub。未知数量不当作0，页面注明仓库关注数而非单技能使用量，详情显示核查时间。Star不进入技能内容修订，更新不改变受理输入或重建全部资源。

**发布边界：** [Git排除](../../../.gitignore)、[pre-push](../../../scripts/git-hooks/pre-push)及[本地原件防发布检查](../../../scripts/check_workbench_local_skills.py)拦截第三方原件/生成入口入库；[不可变发布](../../../scripts/workbench_release.py)不打包本地入口原件，并绑定校验后的本机库指纹。自有集成代码仅推`origin/main`，禁止向官方推私有代码。Git新检出可构建集成代码，恢复完整本机技能库需另行运行本地安装并核对准确提交，不能宣称公开fork含有第三方原件。

**实际公共文件差异：** [共通源码台账](../SHARED-SOURCE-CHANGES.md)按PC-33核对`SkillPage.tsx`的可选controls/filter/compare/searchText/metadata/icon、`SkillDrawer.tsx`的可选详情头部内容与阻塞原因、`lib/api.ts`的可选展示字段。缺省调用保持原分组、搜索、详情、依赖、运行及结果区域，公共模块不得导入私有业务。

**验证入口：** [本地库与准确输入测试](../../../tests/test_workbench_local_skills.py)、[前端分类/辅助选择测试](../../../tests/frontend/localSkillLibrary.test.mjs)、[真实浏览器检查入口](../../../tests/workbench_local_skills_browser.py)、[原技能回归](../../../tests/test_workbench_official_skills.py)、[新闻制作合同](../../../tests/test_workbench_news_creation.py)、[架构检查](../../../tests/test_workbench_architecture.py)、[登记门禁](../../../scripts/check_private_capabilities.py)。本轮浏览器、构建、安装数量及线上配对结果由主调度在Spec按实际完成记录；此卡不声称已通过真实模型、外部CLI、发布或实体手机验收。

**后续维护：** 跟进上游先核对共享可选端口能否被原生能力替代，移除被吸收的适配，不复制页面。新增来源先登记与核对许可证/依赖，再固定提交并生成准确目录；展示缓存和内容修订继续分开，升级不改已受理输入。辅助方法只在本次显式选择阶段起作用，不恢复退役技能管理/自动学习，也不扩展采纳与发布权限。

**更新记录：** 2026-11-07依据用户批准方案登记PC-33，补充PC-07/08/09/10/18接入和三个公共文件的必要差异。当前安装、测试与正式部署仍由本轮Spec分别给出事实，不能以登记代替验收。

**架构复核记录（2026-11-07）：** [职责原件](../private-architecture-review.json)登记本地库五模块的准确符号归属；同时纠正历史记录缺失的画像只读、当天采集、分层读取、对话恢复/采纳、交付投影等既有符号及已不存在的旧方法名。没有为了通过检查改生产实现或测试；旧审阅哈希保留以显示后续变更。[只读审计](../../../scripts/audit_workbench_private_architecture.py)与[职责回归](../../../tests/test_workbench_private_architecture.py)用于核对，不代替真实模型或发布验收。

**额外验证与元数据分层：** [自有CI](../../../.github/workflows/workbench-skill-bytes.yml)运行本地原件防发布与选择/冻结合同。`view=selection`仅返回生产下拉框所需字段，列表不传原件正文。Git链接保留指针原字而不跟随，别名SKILL不重复发现；安装不执行这些链接或测试样例。

**重建依据：** 来源清单同时记录本轮29个准确提交；默认安装按清单重建，不在后台追随HEAD。将来显式升级原件时先更新该清单、核对许可与工具差异再运行安装及验收。Star后台更新不更新这些提交。

**交付核验（2026-11-07）：** 已安装29源/303入口/13分类并上线准确配对，29源Star有本轮核查时间；27条需CLI/服务/通道保持待配置。最终冻结浏览器16项及正式入口桌面/390/320只读核对通过，历史42回合与数据库保持；产品源码、配对与测试限制见本轮Spec最终交付。实体手机、真实模型和外部发布没有冒称验收。
