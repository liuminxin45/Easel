# 发送后立即停止与可恢复会话

用户批准：停止持久意图、原生终态优先、受控关闭本地执行、保留未知结果、同一应用会话换新原生执行代数；完整验证、提交自有 fork 并部署。包含上一批点按复制。

## 根因与保留合同

原私有停止在取得 turn/start ID 后取消外层任务；CodexAdapter 等待 turn/interrupt ACK 两秒，吞掉异常后退出。准确 interrupted/completed 通知不能参与停止收敛。停止早于 turn/start 时也仍会派发。当前受影响回合的 native rollout 为空，不能凭此捏造停止或完成。

保留原任务、输入 SHA、技能快照、原生绑定、作品与未知回执，不重发。Tailscale 仅网络转发。官方无 cooperative stop 的调用保留既有取消接口；私有正常停止使用同一适配器的可选 stop_event，不另建执行器。

## 实施

- `RunRequest.stop_event` 可选；准备阶段可取消，可能发出的 turn/start 有界等待准确 ID。
- 同一 RPC 请求一次 interrupt；原生终态优先于 ACK，漏通知只读 thread/read；有界等待结束退役原连接。
- 原 RPC 连接池回传本次租用的进程 token / PID 与树退出回执。原生 unknown 与已证实本地关闭分开；无关闭证据继续阻止新任务。
- 私有会话在准确 pending ID 和执行代数下释放等待，必要时使用新 native_session_key，旧绑定不改。首条显式新消息附只读历史，不执行历史命令。旧回调不得改写已完成记录。
- 重启后优先使用已持久准确原生终态，其次使用退出证据；原后端确实死亡而原CLI仍存活时，按已持久的进程创建身份与树关系回收遗留执行，再保留unknown并释放等待；原生准确终态仍沿既有只读核验。历史空日志回合只在候选验收绑定、准入围栏、精确进程身份退休后保留 unknown 并解锁。
- 前端仅认服务器 execution_closed 允许解锁；沿已有状态卡，不新增顶部提示/弹窗。未知状态本身继续保留。
- 受控退休为部署的显式、准确计划，不是 unknown 白名单；其他在途/未知仍阻止切换。

## 验证与交付

已通过后端相关185项、原引擎106项（4项环境跳过）、前端72项；最终恢复用例另复核23项通过。私有check/build与原Easel独立build通过。证据：`.local/workbench-validation/immediate-stop-recovery-20261106/` 的 backend-final.log、recovery-final.log、harness-tests.log、frontend-final.log、frontend-check.log、native-build.log、official-build.log。

冻结候选、实际浏览器、Git远端及正式切换继续执行，尚不冒称上线。测试使用 TEMP 数据/假原生协议、真实本地 stdio 及受控子进程，不能冒称真实模型或实体手机验收。最终候选、推送、上线和当前旧会话恢复结果在执行后补全。


## 最终候选验收

产品源码6d2f6f24f0041447030dc402024bf67ec491fdb0；后端workbench-20261106-152722（547f23eb50d4042c5297abe5bec87f7e69390ba16fb842232aaf82a5219faad1），前端native-stop-recovery-20261106-r3（7e4e0fa630bffa9ca9aa5f7161c56eeb1322faab7ae47ecab72d4bef76328e13）。

最终显示补充后，相关后端67项、前端73项通过；先前185项架构/业务及原引擎106项通过。最终两套实际Edge/TEMP HTTPS验收覆盖桌面、390/320明暗主题：停止/刷新/后写草稿/新原生代数/旧unknown保留/消息状态卡/无横向溢出五组全部通过；点按复制30项通过。准备阶段与原生阶段另由真实CodexAdapter+假协议回归覆盖，真实本地进程树及后端死亡回收也通过。浏览器发送验收等待原按钮可用后点击，不以测试脚本即时Enter取代用户触控。

证据：同目录message-state-final.log、frontend-card-final.log、native-card-build.log、official-card-build.log、final-browser-stop-verified/report.json、final-browser-copy/report.json。旧空rollout不当作原生停止证明；准确退休计划SHA已记录，正式切换和上线后核对下一步执行。
