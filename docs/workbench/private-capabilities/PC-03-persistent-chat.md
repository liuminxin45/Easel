# PC-03 服务器会话、持久受理与停止恢复

2026-11-06 断线恢复三批整改：准确 session/turn 回执统一收敛，覆盖已完成历史、半开流、漏 done、前台/在线恢复、旧回调及登录代数；服务器终态优先于浏览器旧 pending，保留后写草稿和附件。私有看门狗每15秒核对活动任务，连续30秒无流字节时只更换 GET 订阅。真实 unknown 通过同源 CSRF 的 `/api/chat/reconcile` 读取 Codex 准确线程/回合终态，缺失或歧义证据继续 unknown，不调用模型或 resume。恢复提示复用消息旁状态卡，短断线5秒内静默；状态诊断沿现有有界脱敏日志，每回合至多12次阶段上报。参见 [本轮 Spec](../../../specs/chat-reconnect-convergence-20261106/spec.md)。

新增私有入口：[原生终态只读核验](../../../easel_workbench/features/conversations/native_receipts.py)、[HTTP 接口](../../../easel_workbench/http/chat.py)、[会话视图适配](../../../web/frontend/src/workbench/ui/ChatSessionView.tsx)。共通文件 `web/frontend/src/lib/api.ts` 仅增加可选 `onStreamActivity` 回调供宿主观察流字节，默认行为不变；不复制传输实现。同步 upstream 时保留可选参数及每次读取的通知即可。

验证入口：[原生回执恢复测试](../../../tests/test_workbench_chat_reconcile.py)、[移动浏览器故障旅程](../../../tests/workbench_chat_recovery_browser.py)、[前端状态与竞态测试](../../../tests/frontend/workbenchNativeChat.test.mjs)。完整构建、Git 与部署证据在上述 Spec 按实际结果登记。

2026-11-06：明确的版本决定沿原持久受理入口，保存本地回合和准确操作身份，复用事件日志。重启只核对/恢复同一幂等本地记录，模型 unknown 仍不重放；见 PC-12 的对话闭环测试。

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

**实际公共文件差异：** 见 [共通源码逐文件台账](../SHARED-SOURCE-CHANGES.md)，按 `PC-03` 查询实际关联路径、修改理由与同步核对点；纯复用或开发维护项不据此新增官方改动。

- **状态：** 已确认保留；类型：可靠性适配。
- **需求依据：** 用户要求跨设备历史、发送后立即暂停可靠、断线自动同步且不重发。 依据见下方原始规则/Spec；本卡不额外授予执行、采纳或发布权限。
- **能力范围：** 服务器 session/turn 身份、持久受理、SSE 重读、准确停止意图、冻结执行配置、原生问题与未知回执。
- **官方复用与必要差异：** 复用 ChatPage、QuestionCards、原生 RPC/引擎适配器及同一原生/API supervisor。
- **不可破坏的合同：** 断线只重新订阅；未知不重放；取消 HTTP/CLI 不冒称远端停止；旧会话和已受理任务保持准确配置，完成与暂停按真实回执收敛。

**接口与状态归属：** HTTP 受理/查询经宿主组装，业务状态由 ChatService 保存于 easel_chat_sessions、easel_chat_turns、easel_chat_operations；模型执行仍走共享聊天服务和原 harness，不能建立第二个执行器。

**私有入口／资源：** [easel_workbench/features/conversations/service.py](../../../easel_workbench/features/conversations/service.py)、[easel_workbench/features/conversations/session_creation.py](../../../easel_workbench/features/conversations/session_creation.py)、[easel_workbench/application/chat_admission.py](../../../easel_workbench/application/chat_admission.py)、[web/frontend/src/workbench/ui/chatRuntime.ts](../../../web/frontend/src/workbench/ui/chatRuntime.ts)

**官方复用／共通接缝：** [easel/web_services/chat.py](../../../easel/web_services/chat.py)、[easel/harnesses/codex.py](../../../easel/harnesses/codex.py)、[web/frontend/src/components/ChatPage.tsx](../../../web/frontend/src/components/ChatPage.tsx)

**验证入口：** [tests/test_workbench_chat.py](../../../tests/test_workbench_chat.py)、[tests/test_workbench_chat_admission.py](../../../tests/test_workbench_chat_admission.py)、[tests/frontend/workbenchNativeChat.test.mjs](../../../tests/frontend/workbenchNativeChat.test.mjs)

**需求与设计记录：** [specs/easel-shared-runtime-20261104/spec.md](../../../specs/easel-shared-runtime-20261104/spec.md)、[specs/session-create-recovery-20261103/spec.md](../../../specs/session-create-recovery-20261103/spec.md)

**后续维护：** 变更时先核对上述调用链与当前官方实现；优先共用、缩小上游补丁。同步维护本卡的范围、入口、共通差异及验证依据；被上游吸收时移除对应适配并更新登记状态。原方法、历史输入和交付证据不在本卡复制或改写。

**首版登记记录：** 2026-11-05 按业务源码 `1901f83` 建立首版；首版为只读盘点及文档登记，未新增启用能力，未逐项重新执行产品验收。本轮补充项按当前源码及各自验证记录另行核对，不将首版记录冒称本轮业务验收。
