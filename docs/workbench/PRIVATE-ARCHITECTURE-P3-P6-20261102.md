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

## 后续切片

P4 分采集、交付、安装三批；P5 整理装配与共享基础能力；P6 核对前端依赖、
干净检出及准确不可变配对。各批完成后在此记录实际范围、失败原因和证据，不预填通过。
