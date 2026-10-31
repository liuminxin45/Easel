# 移动端制作会话的恢复状态

用户报告制作贴图时顶部持续显示“连接暂时中断，正在恢复原任务状态。输入已保留”。本批不重新提交模型制作，不清草稿、附件、原回合或历史关联。

实际回合 `b2ef839a-9640-4190-9e5e-3a0053187bfc` 曾运行约 30 分钟，包含模型输出和执行授权等待。工作台已记录原生中断确认，却在超时分支写成 `unknown`，会话一直保留 pending。只读 `thread/read` 再次核对相同原生 thread/turn 为 `interrupted`、线程为 `notLoaded`、项目目录匹配，没有发起新模型回合。

先用既有 `reconcile_workbench_native_receipt.py` 在 TEMP 数据库备份中演练，再按准确原行 SHA 和原生回执应用。原行保存在追加式核对日志中；只将该已确认中断收敛为 stopped/interrupted，并收敛相关模型与业务回执。原会话 pending 已解除，282 字符的原回复、冻结输入、原生 ID、附件及作品绑定不变，22 个已登记文件保留。不制造完成或交付回执，不自动重做。

另有独立的前端漏洞：SSE 中断后 GET 已成功续接，但静默制作只有 accepted/keep-alive；旧 onAccepted 整轮仅触发一次，顶部中断提示要等新 token 才清除。共享 `api.ts` 新增可选 `onConnectionRestored`，仅在实际恢复的 SSE accepted/注释后通知，HTTP 200 空流不算恢复。私有 SessionRuntime 只清自身传输警告，不重复确认受理、不清后写草稿、不改变回合 ID，不解除未知执行回执。服务器明确返回未知执行时显示“原任务执行结果待核对”及原原因，避免误称断网。

后端源码另修正：只有准确原生中断已确认的 TimeoutError 才记 stopped/interrupted；未确认继续 unknown，原取消语义不变。该补丁通过 TEMP 假执行器测试，但**后端尚未上线**。它不将未完成制作视为成功，也不扩大采纳、继续制作或发布授权。

共通页面、侧栏、布局和 CSS 未改；共享 SSE 的新增回调为可选接缝，原 onAccepted 单次语义保留。旧浏览器测试同步当前未知状态文案，等待真实可发送状态再用 Enter 选技能，并在同一输入节点核对长草稿确实可滚动，不替换应用 DOM、文本或样式。

冻结后的正式回执 `ev-dea0e8737556`：301 项 Node、117 项 Python（聊天、超时、架构、技能策略/命令）、原 Easel TypeScript/Vite 构建、包输入/成员 SHA、9 项移动端真实 SSE 故障注入、27 项完整会话浏览器、8 项升级和线上原回执核对全部通过。移动专项包括只用 accepted+keep-alive 恢复、原字/ID 保持、一次 POST 后仅 GET 续接、真实 stop 回执、unknown 刷新不重放；实际检查 4 张 390px 截图。均为 TEMP Edge 模拟手机，不冒称实体 vivo 验收或真实模型产出质量。

当前配对：

- 活动后端仍为 `workbench-20261030-202529`，SHA `d34e02d8a1428ea144341567b4e6be340abf0b887c7de40f1e74db408604ce65`。
- 活动前端为 `native-chat-recovery-20261031`，SHA `1146eda40ffc49f8e68eba43e91c8a7c90e6b446ea012a3410922eb7127ca3ae`，通过前端独立发布上线。
- 后端候选 `workbench-20261031-074757`，SHA `8df3a920310760ad301a131b53fc752fb7744b2e18c19a40f7e6c3271cfe72c6`，与活动后端仅 chat.py 和新增 Spec Kit AGENTS 约定不同，其余包成员 SHA 一致。已验证候选准入，但升级返回 waiting：另一笔 `collection_model_receipt` `1255ac07…` 仍 uncertain。未绕过检查、未清该回执、未停止后台；不能把候选说成线上版本。

上线后回执 `ev-5141c9946e89`：原回合仍 stopped/interrupted、会话无该 pending、原内容与绑定未变、22 个文件仍登记；公网入口返回新前端 200 登录页。前端发布未打开业务数据库、未重启后台角色，过程中的唯一业务修复是上述精确回执核对。

代码提交 `1281226`（共享传输）、`b04c5a5`（私有运行态和后端分类）、`5347084`（浏览器验证），仅推送自有 fork，官方 PR 保持关闭。证据在 `.local/workbench-validation/chat-recovery-20261031/`，其中原回执核对记录含私有原始行，仅留本地，不提交源码仓库。Spec Kit 任务 `t-be85c9d55fd3450d`，用户实际手机确认仍待反馈。
