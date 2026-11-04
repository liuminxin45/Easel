# Easel 基座的适配点

## 两类变更

通用修复与可选宿主接口放在原 Easel 目录，保留无宿主时的默认行为，能够单独审查、测试及整理给上游。准确版本、冻结输入、画像绑定、授权、历史回执及项目采集属于本项目业务，只能由私有适配层提供。本轮提交推送到 origin；官方 upstream 只作为读取和合并来源，不向官方提交私有业务 PR。

## 采用的模式

- **端口与适配器（Ports and Adapters）。** 原页面通过原 API 函数工作，共享后端通过工厂取得目录、存储和执行器。服务器鉴权、作品台账、画像修订及安装队列由私有适配器接入；公共模块不认识工作台业务。
- **集中组装（Composition Root）。** 原 `App.tsx` 保有唯一应用布局；私有入口集中绑定传输、缓存和路由。认证代数变更时先重建绑定再挂载页面，避免旧缓存或迟到响应混入新身份。
- **扩展槽与策略注入。** 页面通过可选 props 接收草稿仓库、保存策略和详情区域。默认参数保留官方行为；私有业务只填入扩展槽，不复制页面或覆盖其 CSS。
- **边界装饰（Decorator）。** 原请求进入共享处理函数前，由私有边界包住准入、准确操作身份、授权事务和回执。处理结果仍沿用原协议；未知回执只查询，不通过重新执行补救。

这些模式落实为少量函数、类型和可选参数，不建立第二套页面框架或通用依赖注入容器。`binding.py` 是迁出原函数时的兼容桥，约束见下文；新增服务优先显式工厂参数，不能继续扩散运行时替换。

## 当前接缝及职责

| 位置 | 通用实现和默认行为 | 私有接入点 |
|---|---|---|
| `web/frontend/src/App.tsx` | `ApplicationFrame` 唯一绘制侧栏、子导航和页面容器；不传 `host` 时运行原 `NativeApp` | `workbench/ui/index.tsx` 组装服务器会话、路由转换和页面内容，不另画应用壳 |
| `web/frontend/src/lib/api.ts`、`lib/whoami.ts` | 原页面仍调用原 API 函数；无绑定时沿用原 fetch、账号显示缓存和自动核验默认策略 | `workbench/ui/nativeApi.ts` 连接鉴权客户端、操作身份和内存缓存；入口按客户端与认证修订完成绑定后才挂载原页面；缓存代数拒绝旧宿主的迟到响应；私有绑定关闭自动核验，手动及扫码后的明确核验仍走原服务 |
| 原页面的可选 props | `IdeasPage`、`ProfilePage` 的草稿存储，`DashboardPage` 的缓存/读取策略，预览与发布页的回调均保留默认行为 | `nativePages.tsx`、`nativeProfiles.tsx`、`nativePublishing.ts` 只转换数据、批准输入和业务回调；仍渲染完整原组件 |
| `components/SkillPage.tsx` 的可选 `icons` | 不传宿主时仅使用官方图标映射，不导入项目头像或工作台模块 | `NativeSkills` 从私有 `workbench/ui/skillIcons.tsx` 注入精确技能 ID 映射；批准原图与用途角标保持，映射不写入模块全局 |
| `easel/web_services/{accounts,settings,planning,outputs,environment,analytics,skills,profiles}.py` | 从 `web/app.py` 移出的单一函数实现；原路由继续绑定同一代码；技能七项依赖/脱敏与画像六维基线也只保留一份 | 工厂接收目录、环境、执行器、存储和检查回调；不得导入 `easel_workbench`；私有层只补准确版本与配置修订 |
| `easel/web_services/binding.py` | 用同一函数代码建立独立上下文；原 `web/app.py` 绑定自身命名空间，保留原测试入口 | 仅工厂组装上下文，不复制源码、不修改进程环境，不把此桥接扩展成通用依赖注入框架 |
| `easel/web_services/concurrency.py` | 原共享 planning 与私有服务共用同一阻塞 I/O 线程边界 | 通用 helper 不含私有依赖；取消时等待线程真实结束，不提前释放调用者持有的写锁或操作身份。共通规划函数仍只有一份，通用响应性修复可单独维护 |
| `easel_workbench/runtime/native_api.py` | 保持原页面的 HTTP 协议，调用共享处理函数 | 连接现有作品、画像、选题与排期存储；`_mutate` 包住准入、请求身份、事务与回执；未知结果不重发 |
| `easel_workbench/settings.py`、`runtime/easel_accounts.py` | 分别调用共享配置、安装、登录和身份查询实现 | 保管配置修订、加密凭据、原账号关联及交付证据；连接成功不授予发布权 |
| `workbench/host.tsx`、`ui/styles/workbench.css` | 原页面使用原样式入口 | 仅处理宿主生命周期和私有扩展布局；不得借页面外层覆盖原侧栏、账号、控件或主题 |
| `workbench/ui/styles/mobile.css` | 2026-10-31 用户授权修复窄屏布局；原组件、桌面外观、主题和字体继续来自官方 | 只在 `html[data-native-platform]` 与窄屏/低高度媒体查询内约束几何、滚动及触摸目标；生产审计器拒绝颜色、字体、隐藏控件或裁切溢出来掩盖问题。上游修复同项后移除对应规则 |
| `workbench/platform/modal-focus.ts`、`navigation.ts` | 原弹窗、抽屉及导航控件不另写一份；不新增原组件没有的 Escape 行为 | 宿主集中隔离移动弹窗的焦点、背景 inert 与恢复焦点；关闭事务避免递归、重复弹层和深链接关两次，不拦截触摸/滚轮 |
| `workbench/ui/nativePages.tsx`、`ChatSessionView.tsx` | 原工作台摘要和原聊天仍由官方组件渲染 | 移动端用原摘要默认平铺，移除嵌套短滚动区；私有会话投影按实际消息内容保持引用，避免草稿输入/相同轮询触发原组件自动滚动 |

## 维护边界和已知约束

后台显示策略集中在私有 `Notice` 与资源读取层：正常 `busy/refreshing` 不生成全页提示，真实错误及显式断连/未知回执反馈保留到成功。`TrendsPage.quietBackgroundRefresh` 默认关闭，仅私有宿主启用以消除忙碌来源重试的状态行跳动；详见 [静默刷新记录](QUIET-POLLING-20261031.md)。

发布确认仅首次读取准确渠道稿时使用共用 `StatusCard`；已有修订的后台刷新不闪烁状态卡。批准按钮仍须绑定已核对的 revision ID/hash 与原授权，错误继续由 `Notice` 显示。

官方完整集成基线唯一数据来源为 `upstream-base.json` 的 `upstream_commit`。审计器、冻结运行时和前端许可证说明均读取它；新快照同时保存原记录及 SHA。`upstream-overlays.json` 独立登记已选择的 PR，核对其基线一致，不将这些 PR 冒称为后续所有官方提交已集成。当前准确基线仍为既有 `0f43dc9`；本次没有同步新的 upstream 版本。

生产审计器通过 TypeScript AST 检查共通代码的 import、re-export、动态导入、require 和类型导入，拒绝反向依赖工作台或其私有资产；发布确认的原始平铺 status 元素也受检查。负例测试与共享聊天函数代码身份测试检查真实边界。`easel-base.yml` 现覆盖 main 的这些合同与冻结基线；已有 `workbench-mobile-state.yml` 继续运行全部前端回归、类型检查及原生/私有独立构建，不重复新增整套构建链。

- **组装集中在宿主入口。** API/缓存绑定、共享服务工厂、鉴权和停止钩子均由组装层负责。原组件只接收通用接口；业务判断不得放进组件或共享服务。一个文档只运行一个应用宿主，不能依赖模块级 API 绑定同时支持多个 App。
- **绑定上下文是兼容桥。** 共享函数从自己的 `__globals__` 读取依赖；返回对象是命名空间快照。运行后直接给对象重赋属性不会可靠改变函数依赖，标量状态更新也未必反映到快照属性。调用者只用工厂参数及公开方法；后续可用只读上下文句柄集中消除此差异，不在页面或业务层追加 monkeypatch。未来若新增闭包、类方法或配置校验器，须单独确认其依赖仍能隔离。
- **长操作不能简单拆锁。** `NativeApi._operation` 当前依靠写锁保护，存储回调从它取得请求身份。新增耗时动作前先显式传递操作上下文，再考虑资源级并行；直接去掉锁会串用回执。已有设置、采纳和交付事务继续使用自己的原台账，不再创建平行日志。
- **路由和常量各有单一来源。** Page→URL 转换集中在私有 `platform/native-routes.ts`；主入口仍只认 `/api/config.tools`。输出类型/保护目录、规划状态及登录驱动注册只在共享服务定义，原入口绑定同一对象，不再保留常量副本。`NativeApi.supports()` 与 `dispatch()` 的协议匹配仍须同步维护，新增路由时应同时验证声明与实际处理。
- **扩展槽不能变成替代页面。** `host.content`、详情扩展和回调只容纳原页面或已授权业务扩展。增加共通能力先检查原组件和原服务；不能新增一份相似页面、生成函数副本，或通过私有 CSS 隐藏旧实现。
- **移动修复集中且可撤回。** `mobile.css` 是几何例外的唯一入口，审计器 `inspectMobileCss` 和实际触摸浏览器验收共同约束；不向原页面散布设备判断。HTML 预览仍使用原 iframe，私有服务边界提供不含同源权限的沙箱响应；图片/媒体协议的精确路由也只在私有边界处理。

## 跟进官方的检查顺序

官方准确版本、固定 Git 标签和后续基线登记流程统一见 [UPSTREAM-VERSIONS.md](UPSTREAM-VERSIONS.md)；远端观察值与已集成基线分开记录。

1. 按项目 [easel-upstream-sync 技能](../../.agents/skills/easel-upstream-sync/SKILL.md) 从私有 HEAD 新建同步分支，用 `git pull --rebase` 跟进官方并处理冲突，保留旧分支及 SHA；验证后更新基线档案和标记，通用接缝与私有业务分开审查。
2. 对照上游变更，先更新原组件、共享函数及相关常量；再核对宿主接口和工厂依赖。原生默认构建及反向依赖检查必须继续通过。
3. 验证首屏绑定顺序、认证切换、迟到请求、批准输入恢复、准确版本、停止和未知回执；模拟账号及制作只使用 TEMP 数据和假执行器。
4. 运行基座审计、相关原生/私有回归及桌面和模拟手机检查；按最终 SHA 重新冻结配对版本，由总调度统一验收和切换。

## 2026-11-01 内容闭环的来源接缝

热点、摘要与选题的 `onUseTopic` 在原标题参数后兼容新增可选来源 ID 与备注，旧单参数调用方继续有效。共享 `IdeaItem`/`IdeaInput` 的可选 `source_id` 是通用来源引用；旧客户端不传该字段时不覆盖已有引用。私有 `NativeApi` 才校验它是否为服务器文章 ID，宿主才将其映射为 `article_id`，公共组件和共享 planning 均不认识私有台账或模块。

准确新闻阅读属于私有采集扩展，`NativeNews` 组合现有 PageHead、Panel 和原 CopyableText，不替换原 TrendsPage。Worker/前台恢复状态机集中在私有 platform/native-resume.ts；不向共通页面散布 WebView 判断。验证及实际交付见 [移动闭环记录](MOBILE-CLOSEDLOOP-20261101.md)。


## 2026-11-02 跟进官方 0f43dc9

官方下拉、primary tokens/hover、暗色按钮及画像全宽滚动直接使用官方实现；
已删除旧 model-dd 样式副本和覆盖官方按钮的修复。Sidebar 画像使用同一个 SettingsSelect，
私有层只传 personaOptions 等已有可选接口。官方 dropdown.css 是私有 build-inputs 的显式 SHA 成员。

保留的通用差异：SettingsSelect 在原生 dialog 优先规则后，允许 portal 到最近的 drawer-overlay，
再回退 body。官方新 SkillDrawer 配置菜单原先被 z1000 遮罩盖住，已用原始官方构建实际复现，
该差异只修挂载所有权，不提高 z-index 或重画菜单；未来上游解决同项时移除对应差异。

官方采集器、协议、脚本校验与清理继续是唯一基础实现；私有来源修订、Python 协议及任务回执
仍通过现有 SourceRegistry/官方 runner 适配，没有增加另一套采集系统。

Git rebase 的文本等价不代表原始字节相同。内容寻址提示词必须匹配记录 SHA，
原有 gitattributes LF 规则与仓库原件测试共同检查；不能修改历史声明 SHA 或运行时归一化放行。
新基线的准确 SHA、固定标签、验证范围及未部署状态见 UPSTREAM-VERSIONS.md。

## 官方外壳唯一实现

`components/Drawer.tsx` 从原 SkillDrawer 的结构最小提取，原技能与全部私有详情/版本/经验/确认共同调用，
默认尺寸、header/body和关闭控件沿用原CSS。common.Drawer只负责history、portal所有权与焦点返回，
不再维护Modal/ew-dialog；原生OnboardingWizard/设置/数据源dialog保持其原实现。
Skills services只注入数据和执行，禁止canConfigure/onUse/useActions等参数重写官方默认区域。
`skillServices`复用既有SessionRuntime和准确plan/submit/last回执，原运行区域显示实际结果；
真实QuestionCards仍在原运行区后按需出现。unknown查询恢复与新回合分开，晚到的旧回执不能清除新回合问题。
技能详情附加configuration_revision，保存沿用用户实际看到的父修订；409不自动套用新修订。
原画像向导的六文件构造提为纯profiles服务，原入口写文件，私有入口在既有画像事务保存版本文档和完整原表单。
Ideas/Trends/Dashboard的JSX仍在原页面，私有限高只通过显式通用几何参数接入。
基座审计与反例测试检查宿主隐藏默认区域、平行外壳、聊天默认覆盖和公共列表限高。
完整实现及准确验收/部署范围见 OFFICIAL-UI-REUSE-20261102.md。
