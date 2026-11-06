# C-05 本地项目关联、作品归档与 Git 同步存量

2026-11-06：PC-12 原生对话入口明确不采纳时，复用决定记录并保留文件，不创建旧临时候选清理任务；其他历史来源的原有行为保留。

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

- **状态：** 受限兼容／保留既有原操作；不是新增自动归档、清理或 Git 推送许可。
- **需求依据：** 用户要求保留原件、历史、准确版本、采纳/不采纳及已有授权，不回退整个私有层；既有本地归档在 [功能健康整改](../FUNCTIONAL-HEALTH-20261103.md) 和 [私有架构合同](../../../specs/private-workbench-architecture/spec.md) 中作为当前写入者处理。此依据只支持保留原边界，不能推定每个新增作品均获外部同步许可。
- **能力范围：** 已有作品项目目录关联、准确决定/版本记录、已排队归档/清理、有限恢复和绑定原意图的 Git 核对；不负责模型传输或平台发布。

## 接口、门控与存储

| 位置 | 实际作用与现有门控 |
| --- | --- |
| `POST /api/works/<id>/project-binding` | 经登录/同源/CSRF；LocalOperations.bind 核对准确作品、operation_id、expected_revision 和安全项目相对路径，记录关联证据。不是只读；不以 `local_io=false` 宣称此写入已关闭。 |
| `POST /api/works/<id>/local-operations/retry` | 核对原任务/作品和恢复操作身份，只将允许状态的现有任务排回队列，不启动新 AI 制作。 |
| `GET /api/works/<id>/local-operations` | 读取现有关联/任务；关联歧义不能凭标题占用独立文章或猜测原目录。 |
| `LocalOperations.process_one` | 只有 `data/automation-enabled.json` 的 `local_io=true` 才消费本地任务；该开关不是 HTTP 写入授权。慢目录扫描在写事务外，随后重核准确任务/作品/关联快照。 |
| `_sync` | 仅接受有来源决定且 kind 为 accept/reject/archive 的原任务，验证明确文件SHA、Git工作区/暂存区、远端/分支和持久提交意图；推送未知时先核对原提交，不重做制作或猜成功。源码中存在此动作不能代替用户的外部 Git 授权。 |

**状态归属：** 既有 `toolbox_local_tasks`、`toolbox_project_bindings`、`toolbox_local_ops`、原始交付/记录输入与 `data/local-operations/` 日志；作品原件仍归原作品/文件台账。归档、清理及同步为不同结果，不因一个步骤成功就冒称全部完成。

**私有源码：** [local_operations.py](../../../easel_workbench/runtime/local_operations.py)、[toolbox_server.py](../../../easel_workbench/runtime/toolbox_server.py)、[completion_service.py](../../../easel_workbench/runtime/completion_service.py)。

**官方复用与必要差异：** 页面仍由原 [OutputsPage](../../../web/frontend/src/components/OutputsPage.tsx)、共通 [Drawer](../../../web/frontend/src/components/Drawer.tsx) 及 [PC-12](PC-12-versioned-works.md) 版本扩展承接；本地项目文件/Git 服务没有官方通用 CRUD 等价实现，不将它塞入 Tailscale 或共通页面。本次登记无新增官方源码修改。

**不可破坏合同：** 不覆盖操作前已有修改；拒绝越界/链接目录；不删除原始反馈/产物；unknown不重放；没有原决定与准确范围不得推送。开关关闭时保留队列，不能删除历史来让健康检查变绿。

**验证入口：** [test_workbench_local_locking.py](../../../tests/test_workbench_local_locking.py) 检查慢扫描/并发写及快照；[test_workbench_native_completion.py](../../../tests/test_workbench_native_completion.py) 检查准确历史；[test_workbench_deployment_controls.py](../../../tests/test_workbench_deployment_controls.py) 检查切换围栏。仅列出测试不表示真实 Git/文件清理已获本轮执行或验收。

**后续维护：** 修改任何外部目录、清理条件、同步规则或新增调用者，须先核对独立需求及准确授权，并更新本卡和PC-12/PC-15；不借存量代码新增无人值守行为。上游若提供共通归档接缝，接回原实现并保留私有证据合同。

**登记记录：** 2026-11-05 由 U-02 的宽泛“旧写路径”拆出专门维护卡；只登记当前源码与限制，不改变开关、队列或授权。
