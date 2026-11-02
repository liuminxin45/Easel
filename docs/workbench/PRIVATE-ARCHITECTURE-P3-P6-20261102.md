# 私有架构 P3–P6 分阶段交付

对应 `specs/private-workbench-architecture/spec.md`。起点 `892485c`，官方基线
`0f43dc98277eac85fb48952878acad349731d3fc`，当前集成分支
`codex/easel-sync-20261102-082005`。各批验证后提交并推送自有 origin；源码交付与正式切换分开。

## P3：技能、画像、冻结输入与证据

唯一实现分到 `features/skills/`、`features/profiles/`、`features/evidence/`。
`application/creator.py` 保留跨技能发布与画像默认版本更新的原事务，
`application/evidence.py` 保留显式候选命令、任务与运行回执协调。
旧 creator/learning 入口仅导出同一实现；task 使用原 JSON 快照签名算法，
没有与 creator 的原字节哈希混用。Chat 冻结文件物化直接使用已受理快照与 blob。

第一次完整回归暴露两处拆分遗漏：画像绑定调用的 `read_owner` 未迁入，
以及迁移脚本无实例调用 `_release_hash` 的兼容合同被破坏。根据实际堆栈修正：
归属读取唯一实现归画像模块，保留纯版本哈希调用。未放宽业务断言。
早期测试与编辑重叠的 126 项结果不计验收；失败日志与修复后结果均保留。

修复后：269 项技能/画像/会话/事务/旧版本/边界回归通过；
另 39 项原生完成与只读核验回归通过；真实 Windows Edge 桌面及模拟移动端
TEMP 内容闭环 34 项通过。模型与平台为合成执行，不代表真实模型质量或发布。
80 处迁移函数/方法 AST 语句对照保持一致；构造装配和兼容委托另经回归验证。
职责清单随唯一实现更新，链接准确旧提交；170 模块边界违规和职责核查错误均为零。

927 份官方/技能/资源原字节、活动前后端与共享候选均保持。
无新注册、自动学习、制作或发布授权。P3 不切生产。
原始证据：`.local/workbench-validation/architecture-p3-p6-20261102/p3/`，
主要为 `fixed.xml`、`evidence.xml`、`statement-parity.json`、
`inventory-final.json`、`protected.json` 与 `closedloop-fixed/`。

## P4 采集：排期、队列和来源适配

`features/collection/` 保留唯一来源版本、排期规则和原 SQLite 队列；
`integrations/collection/` 负责原内置采集器、通用协议及 Python 资产校验。
`application/collection_sources.py` 显式装配来源适配与队列，
`application/collection.py` 保留原 worker 生命周期。历史模块与直接脚本入口继续可用。
包内 sources、排期与 newsnow 资源仍定位原冻结成员；没有另建注册表、队列或脚本副本。

185 项来源/采集器/历史行形状/架构/技能检查通过；生产者改用唯一适配模块后，
20 项采集器检查重跑通过（与 185 项重叠，不相加）。真实 Edge TEMP RSS、
桌面/模拟移动制作与采纳闭环 34 项通过。来源注册本身不触发采集，250 条协议批量
入库、准确来源快照、幂等和删除后历史可读均按原断言验证。迁移中的 19 个
未改方法语句对照保持；构造装配与资源路径单独验证。927 份保护字节和正式指针保持。
证据：`.local/workbench-validation/architecture-p3-p6-20261102/p4-collection/`。

## P4 交付：批准台账、资产核对与平台适配

`features/distribution/service.py` 是原批准、租约、attempt 与远端状态的唯一实现；
资产前置读取在 `features/distribution/assets.py`，worker 在 `application/distribution.py`。
账号与平台调用位于 `integrations/platform_accounts.py`、`integrations/publishing.py`，
保留原 vault、账号连接、平台脚本与 CLI 入口。未新增平台支持或扩展回退。
66 个函数/方法的完整语句保持；改变的导入和发布 worker 路径另经回归核查。

首次整组运行 216 项通过，旧登录测试失败：其全局 Thread 替换阻断 Python 3.14
asyncio 的执行器退出，线程转储与 300 秒超时记录均保留。将替换限制在旧执行入口
拒绝检查内后，该组 7 项在 3.53 秒通过；完整 217 项在 65.49 秒通过。
没有修改产品行为或放宽账号、版本、发送边界、unknown 不重放与 readback 断言。
187 模块职责/边界核查无错；保护文件与正式指针保持。
同时清理上一采集提交中两个文件的末尾空行。
证据：`.local/workbench-validation/architecture-p3-p6-20261102/p4-delivery/`。

## P4 安装：唯一入队事务与隔离宿主

当前协调入口位于 `application/installation.py`；原配方在
`features/installations/recipes.py`，唯一入队事务在 `queue.py`，
宿主检测、进程运行与依赖路径在 `infrastructure/installations/host.py`。
历史 MediaEnvironment 也调用同一入队实现，继续使用自己的原配方、哈希函数和异常合同。
两入口都使用原 `media_install_jobs`，没有新表、新锁系统或任务转换；不自动运行历史任务。

187 项回归通过，包括真实 TEMP 数据库上当前/历史任一入口先受理、同操作重复读取，
两个队列实例并发受理只成功一个、同操作不能换配方，以及中断安装仅复测、不重放。
新增测试最初误把原 ValueError 合同写成 RuntimeError，依实际异常定义修正测试，
没有改变产品异常类型。原安装执行与五个宿主方法语句对照保持；检测通过显式 run 端口委托。
194 模块静态职责/边界无错，保护字节与正式指针保持。未下载或安装真实依赖。
证据：`.local/workbench-validation/architecture-p3-p6-20261102/p4-installation/`。

## P5：存储装配与复用基础能力

`bootstrap/storage.py` 集中 Store/Toolbox 原初始化调用次序及一次性历史导入，
`infrastructure/storage/schema.py` 保存对应原始 schema 片段；原入口按原连接调用。
技能/任务 initializer 仍逐条 execute，保持调用方事务，不改成隐式提交的 executescript。
没有新增迁移框架、库或迁移标记。显式 `create_app(root=...)` 的默认 Store 改为
该 root 的 `data/desk.sqlite`，修复此前落到全局路径的问题。

`infrastructure/credentials.py` 保存同一 DPAPI vault/异常对象、熵、NDV1 格式和 ACL；
`infrastructure/processes.py` 保存原 PID/创建时间及采集 owner 判断。
设置、账号、安装和历史角色直接复用；旧桥接继续兼容导出，不启用退役功能。
七角色参数、OS 锁、原 Windows handle 实现、vendor 与脚本资产均保留。
边界检查增加新 feature 经旧兼容模块反向进入应用，以及复用能力反向依赖退役桥接的反例。

247 项存储/并发/进程身份/部署围栏/冻结/账号/技能回归通过；增加边界守卫与纯叶子导入后，
143 项受影响检查重跑通过（与前组重叠）。真实 TEMP SQLite 的 158 个 master 成员，
包括 SQL 与创建次序，与保存的原 Store/Toolbox 实现完全一致；21 处完整语句/行为对照通过。
实际当前 Windows 用户 DPAPI TEMP 往返、连接隔离与密文头验证通过。
Edge TEMP 内容闭环 34 项通过；200 模块边界/职责无错，927 份原字节和正式指针保持。
证据：`.local/workbench-validation/architecture-p3-p6-20261102/p5/`。

## P6：客户端与 UI hooks 的真实依赖边界

原 `core/react.tsx`、`use-completion.ts`、`use-session-media.ts` 归到 `ui/hooks/`，
客户端 barrel 停止导出 UI hooks。14 个 hooks/类型显式从 UI 导入；原组件、控件、
样式、导航、草稿键与请求身份逻辑不变。17 个迁移声明文本保持一致。
新增实际 core import/export 图反例，以及客户端入口不加载 React 的运行检查。
旧 VM 测试夹具同步明确的 UI hooks 端口，模块加载器补齐目录 index 的解析。
378 项前端回归通过；check:workbench、私有和官方构建通过，原大包体积提示保留。
最终后端组合 323 项回归通过。干净检出及冻结配对仍待本批收尾验证，尚未切换正式运行。

## 验证与交付边界

每批保留独立提交与原始失败依据；最终源码、候选和生产状态分别登记。
实体 vivo/WebToApp、真实模型质量与平台发布继续按实际可用条件验收，不由 TEMP 或模拟移动端代填。
