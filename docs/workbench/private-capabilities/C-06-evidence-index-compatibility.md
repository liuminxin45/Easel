# C-06 证据索引、分类与分析设置存量

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

- **状态：** 受限兼容／确定性索引与历史记录；不是新整理经验、自动学习或长期规则修改许可。
- **需求依据：** 保留原始反馈、证据与历史回执，技能原生化明确退役私有经验/候选管理。索引与证据分类的存在不等于自动学习仍获准。
- **能力范围：** 既有证据索引/分类、历史提案 dismiss 和兼容设置读写；显式作品独立核验归 [PC-12](PC-12-versioned-works.md)，不能因代码文件带 learning 就删除独立检查或称其自动学习。

## 逐动作分类

`POST /api/learning/commands` 经登录、同源、CSRF；LearningService.command 按 operation_id/签名复用原回执并在既有事务写入。它不经 NativeApi._mutate，不能把服务器登录态当成任意长期业务授权。

| action | 当前结果与边界 |
| --- | --- |
| `index-refresh` | 调用确定性证据索引，会写索引/覆盖记录；不是纯GET，也不代表模型已读原件。 |
| `evidence-update` | 按 expected_revision 更新证据分类/范围/理由/条件，保留证据原件，不产生用户采纳或规则发布授权。 |
| `analysis-settings`、`analysis-pause`、`analysis-resume` | 更新兼容周期设置与修订。BatchLearning.runtime_enabled 恒False；公开设置强制 enabled=False、mode=manual、automatic_retired=True；enabled=True 被拒绝，不能恢复无人值守模型学习。 |
| `proposal-dismiss` | 只允许原候选/预览提案按准确修订标记 dismissed，属于历史管理写入，不创建或采纳新长期规则。 |
| `analyze-evidence`、`analysis-start`、`proposal-create`、`proposal-preview`、`proposal-confirm`、`proposal-revert` | 当前 HTTP 层返回410；服务内部保留方法用于历史/内部兼容，不是开放新入口的许可。 |
| `GET /api/learning/*` 与原件读取 | 读取原证据、历史和处理状态；是否可读取不能作为允许新执行的证据。 |

**状态与存储：** 既有 learning_operations、learning_evidence、learning_index_state、提案/批次历史及 data/learning；原始正文、来源SHA和用户原话不在本卡复制。自动索引/预处理与真实模型执行的结果必须区分。

**私有源码：** [application/evidence.py](../../../easel_workbench/application/evidence.py)、[features/evidence/index.py](../../../easel_workbench/features/evidence/index.py)、[features/evidence/records.py](../../../easel_workbench/features/evidence/records.py)、[runtime/batch_learning.py](../../../easel_workbench/runtime/batch_learning.py)、[runtime/learning_service.py](../../../easel_workbench/runtime/learning_service.py)、[toolbox_server.py](../../../easel_workbench/runtime/toolbox_server.py)。

**官方复用与差异：** 无独立新业务页面，不恢复私有经验详情/候选弹窗；当前技能浏览与执行仍由 [PC-10](PC-10-native-skill-host.md) 共用原 SkillPage/SkillDrawer。证据存储属于私有边界，本卡没有新增官方源码修改。

**验证入口：** [test_workbench_learning_idle_cost.py](../../../tests/test_workbench_learning_idle_cost.py) 检查空闲轮询/并发索引无新模型调用；[test_workbench_archived_evidence.py](../../../tests/test_workbench_archived_evidence.py) 检查历史证据；[test_workbench_skill_retirement.py](../../../tests/test_workbench_skill_retirement.py) 与 [test_workbench_skill_retirement_cutover.py](../../../tests/test_workbench_skill_retirement_cutover.py) 检查退役合同。列出测试不代表本轮实际执行全部写动作。

**依据与维护：** [技能原生化](../NATIVE-SKILLS-20261103.md)、[原始证据/任务职责](../../../specs/private-workbench-architecture/spec.md)。新增证据写动作、模型入口或长期规则变更必须有新需求登记，不能通过更新设置绕过410。官方若提供等价索引/读取接缝则共用，原证据和历史身份继续保留。

**登记记录：** 2026-11-05 从 C-01/U-02 的混合描述拆出，明确仍有写动作与自动模型学习退役是两回事；不修改生产记录或恢复退役功能。
