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

## 后续切片

P4 分采集、交付、安装三批；P5 整理装配与共享基础能力；P6 核对前端依赖、
干净检出及准确不可变配对。各批完成后在此记录实际范围、失败原因和证据，不预填通过。
