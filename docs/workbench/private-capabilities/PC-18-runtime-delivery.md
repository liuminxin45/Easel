# PC-18 托管运行、不可变配对与安全部署

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

**实际公共文件差异：** 见 [共通源码逐文件台账](../SHARED-SOURCE-CHANGES.md)，按 `PC-18` 查询实际关联路径、修改理由与同步核对点；纯复用或开发维护项不据此新增官方改动。

- **状态：** 已确认保留；类型：运维能力。
- **需求依据：** 用户要求稳定、自愈、只上线新版本并备份旧版本，提交可复现且不打断在途任务。 依据见下方原始规则/Spec；本卡不额外授予执行、采纳或发布权限。
- **能力范围：** 角色监督、OS 锁与进程身份、活动前后端指针、写入围栏、准确候选验收、旧包归档和保留未知回执。
- **官方复用与必要差异：** 共享 Easel 原生队列/引擎核对；进程和发布生命周期集中在私有运维层，不放进 Tailscale 或页面业务。
- **不可破坏的合同：** 核对 PID+创建时间+启动参数；不恢复旧库、不重放任务；旧未知保留必须凭准确证据，活跃写入始终阻止切换；推送与上线分别报告。

**接口与状态归属：** 运维入口为 supervisor/launcher 及发布脚本；活动配对以 data/active-workbench.json、data/active-native.json 和不可变包为准，部署准入/围栏以既有控制文件与进程身份为准；无新增业务 API。

**私有入口／资源：** [easel_workbench/supervisor.py](../../../easel_workbench/supervisor.py)、[launcher.pyw](../../../launcher.pyw)、[scripts/workbench_release.py](../../../scripts/workbench_release.py)、[scripts/upgrade_workbench_runtime.py](../../../scripts/upgrade_workbench_runtime.py)、[scripts/native_chat_receipt_retention.py](../../../scripts/native_chat_receipt_retention.py)

**官方复用／共通接缝：** [easel/harnesses/rpc.py](../../../easel/harnesses/rpc.py)、[easel/web_services/chat.py](../../../easel/web_services/chat.py)

**验证入口：** [tests/test_workbench_deployment_controls.py](../../../tests/test_workbench_deployment_controls.py)、[tests/test_workbench_native_chat_retention.py](../../../tests/test_workbench_native_chat_retention.py)、[tests/test_workbench_local_locking.py](../../../tests/test_workbench_local_locking.py)

**需求与设计记录：** [docs/workbench/GIT-DELIVERY.md](../../../docs/workbench/GIT-DELIVERY.md)、[docs/workbench/EASEL-REUSE-DELIVERY-20261105.md](../../../docs/workbench/EASEL-REUSE-DELIVERY-20261105.md)

**后续维护：** 变更时先核对上述调用链与当前官方实现；优先共用、缩小上游补丁。同步维护本卡的范围、入口、共通差异及验证依据；被上游吸收时移除对应适配并更新登记状态。原方法、历史输入和交付证据不在本卡复制或改写。

**首版登记记录：** 2026-11-05 按业务源码 `1901f83` 建立首版；首版为只读盘点及文档登记，未新增启用能力，未逐项重新执行产品验收。本轮补充项按当前源码及各自验证记录另行核对，不将首版记录冒称本轮业务验收。

**更新记录：** 2026-11-06 部署空闲检查纳入制作复盘running、私有提示操作running以及公众号指标reserved/running。新后台工作遵守admission及cutover_paused；未知回执保留、只核对不重发，不因重启重跑已受理请求。

**2026-11-06 旧停止未知的受控退休：** 部署命令仅接收候选验收 SHA 绑定的准确 chat-retirement 预览，核对行、原生绑定及旧 manager/server 创建时间和参数，围栏后复核，精确停止原profile并保存进程树退出证据后才释放该会话。旧结果仍unknown，不重发、不恢复数据库、不跳过其他在途；实现及验证归 [PC-03](PC-03-persistent-chat.md) 的退休模块与竞态测试维护。原 stop_new_profile 复用已存在的创建时间证明及持有句柄，允许其证明归属的原生子进程，绝不按名称扫描杀进程。

进程证明复用 [原生句柄](../../../easel_workbench/runtime/scripts/windows_process_identity.py) 和 [后代归属及收尾](../../../easel_workbench/processes.py)，后端死亡后仅凭已持久PID/创建时间回收准确旧执行，仍存活的原所有者不会被接管。收尾复查终止窗口中新生后代；无法证明退出则不发退出回执。

[部署准入与准确进程退休](../../../scripts/activate_workbench.py) 同属本卡；停止未知的放行只限验收绑定的准确计划，普通未知继续阻止切换。
