# U-01 已核对的采纳与准确版本记录边界

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

- **状态：** 已核对／既有能力说明；对应 PC-12、PC-15。本 ID 保留首版核对历史，不是独立新增能力或删除清单。
- **需求依据：** 用户要求保留准确版本、采纳/不采纳及独立交付授权，并删除会话里的“本轮创作设置”按钮和页面。两者作用位置不同，不能相互替代。
- **复核修正：** 首版将采纳窗口描述为包含“复盘/学习选项”不准确。当前 `Completion` 的选择只有 `archive`、`distribute`、`manual_published`；`learningQuality`、`learning_acknowledged`、`learning_quality_token` 用于本版质量及检查修订确认，不是整理经验、自动学习或技能发布。

## 当前行为与所属能力

| 入口 | 实际行为与合同 | 归属 |
| --- | --- | --- |
| 版本详情 → 采纳并完成 → 原 Drawer | 按准确版本和范围采纳；“完成并归档”保存完成快照；“按本次授权交付”仍核对准确账号/动作/批准；“登记我已手动发布”只登记用户提供的事实，不冒充平台调用成功。 | [PC-12](PC-12-versioned-works.md)、[PC-15](PC-15-authorized-delivery.md) |
| 采纳质量确认 | 客观交付缺失会阻止提交；需要确认时绑定当前检查 token，旧确认不能覆盖新的检查修订。字段名带 learning 不改变其实际用途。 | PC-12 |
| 内容库准确版本 → 制作参数／版本与记录 | `ProductionParameters` 按需只读 `/api/creative/prompts/<version>`，展示该版本保存的指令、SHA 和历史配置，不保存当轮设置、不触发制作、不重新解析今日默认。历史版本号/试用记录只能作为历史事实。 | PC-12 的历史可追溯性 |
| 会话消息下方“本轮创作设置” | 已明确删除，不因保留准确版本历史而恢复聊天按钮、私有查看页或设置抽屉。 | [PC-07](PC-07-news-creation.md) |

**源码与状态归属：** [VersionOperations.tsx](../../../web/frontend/src/workbench/ui/VersionOperations.tsx)、[WorkCompletion.tsx](../../../web/frontend/src/workbench/ui/WorkCompletion.tsx)、[ProductionParameters.tsx](../../../web/frontend/src/workbench/ui/ProductionParameters.tsx)、[completion_service.py](../../../easel_workbench/runtime/completion_service.py)。完成快照、批准和历史原文沿用现有服务器台账；无新存储。

**官方复用与差异：** 所有详情/确认共用原 [Drawer](../../../web/frontend/src/components/Drawer.tsx)；私有准确版本操作填入原内容库详情扩展区，不另建弹窗或替代官方内容库。本次没有为此增加官方改动。

**验证入口：** [test_workbench_native_completion.py](../../../tests/test_workbench_native_completion.py) 核对历史完成与准确版本只读；[test_workbench_version_view.py](../../../tests/test_workbench_version_view.py) 核对版本读取；[test_workbench_chat_business.py](../../../tests/test_workbench_chat_business.py) 核对作品/回合边界。列出测试入口不等于本轮已经运行全部 UI/平台交付。

**依据：** [native-product-experience Spec](../../../specs/native-product-experience/spec.md)、[新闻创作及删除本轮设置记录](../../../specs/news-creation-20261103/spec.md)、[原生新闻会话记录](../NEWS-NATIVE-CHAT-20261104.md)。

**维护要求：** 修改采纳、质量门槛或历史展示时更新 PC-12/PC-15 与本卡；发布授权、平台回执和用户采纳分别记录。不得把本次纠正文档解释成删除质量确认、准确版本历史或恢复整理经验。

**核对记录：** 2026-11-05 在 `49193c8` 基础上按实际组件和完成服务复核，纠正首版用途推断；文档更正本身不修改业务数据、接口或授权。
