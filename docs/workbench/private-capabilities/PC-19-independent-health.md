# PC-19 独立健康中控与每日全链路检查

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

**实际公共文件差异：** 见 [共通源码逐文件台账](../SHARED-SOURCE-CHANGES.md)，按 `PC-19` 查询实际关联路径、修改理由与同步核对点；纯复用或开发维护项不据此新增官方改动。

- **状态：** 已确认保留；类型：运维能力。
- **需求依据：** 用户明确要求独立于项目的定时检测、自愈，并每天最多一次真实 Agent 生成贴图作为流程依据。 依据见下方原始规则/Spec；本卡不额外授予执行、采纳或发布权限。
- **能力范围：** 项目外监控进程、入口/业务/性能检测、受控恢复、隔离浏览器旅程及每日真实 Agent canary。
- **官方复用与必要差异：** 执行继续调用同一原生 Agent 和当前冻结版本；中控不成为第二套业务执行器或消息平台。
- **不可破坏的合同：** 一天最多一次真实 canary，隔离数据和输出，不采纳/发布/学习；未知只核对；第三方 partial/空结果不重启健康后端；保持真实版本绑定。

**接口与状态归属：** 检测入口为独立 monitor、canary、business_health 和 health_endpoint；独立控制进程保存自己的计划/报告，业务检测只读取正式状态，canary 使用隔离数据/输出目录。

**公网入口探测：** 用户2026-11-05报告普通4G的 ERR_CONNECTION_CLOSED，现有本机健康不能代表外部入口可达。本轮在 [public_ingress.py](../../../tools/health-control/easel_health_control/public_ingress.py) 增加独立公网探测，monitor 通过 `public_ingress_enabled=true` 启用采样；使用DoH取得公网地址，TLS/SNI保持原host，绕开本机MagicDNS/系统代理造成的本机路径假绿，并复用nonce/release/PID响应核对。公网失败/变慢但本机正常时只记 network_degraded，不授权重启健康业务、更换业务状态或重发任务。配置仍归 [config.example.json](../../../tools/health-control/config.example.json) 及安装后的独立配置，不进入前端。服务器侧公网探测成功也不等于运营商4G、实体vivo/WebToApp已经实测通过。

**巡检自身的可追溯性：** 观测完成时间与开始时间、检查耗时分别记录；短暂IPC/检查不可用必须保留脱敏错误类型到独立事件日志，不因下一条成功覆盖而丢失诊断。检查失败仍不授予重启权限。2026-11-05持续观察曾见一条inspection_unavailable后自动恢复、后端PID不变；该旧错误未记原因，不能事后猜成确定超时或业务崩溃。

**私有入口／资源：** [tools/health-control/easel_health_control/monitor.py](../../../tools/health-control/easel_health_control/monitor.py)、[tools/health-control/easel_health_control/canary.py](../../../tools/health-control/easel_health_control/canary.py)、[easel_workbench/business_health.py](../../../easel_workbench/business_health.py)、[easel_workbench/health_endpoint.py](../../../easel_workbench/health_endpoint.py)

**官方复用／共通接缝：** [easel/harnesses/codex.py](../../../easel/harnesses/codex.py)

**验证入口：** [tools/health-control/tests/test_monitor_core.py](../../../tools/health-control/tests/test_monitor_core.py)、[tools/health-control/tests/test_public_ingress.py](../../../tools/health-control/tests/test_public_ingress.py)、[tools/health-control/tests/test_canary.py](../../../tools/health-control/tests/test_canary.py)、[tests/test_workbench_business_health.py](../../../tests/test_workbench_business_health.py)。TLS/代理/响应身份及健康后端不误重启的测试，与真实运营商线路回执分开报告。

**需求与设计记录：** [specs/independent-health-control-20261103/spec.md](../../../specs/independent-health-control-20261103/spec.md)、[docs/workbench/HEALTH-COLLECTION-AND-VENDOR-20261105.md](../../../docs/workbench/HEALTH-COLLECTION-AND-VENDOR-20261105.md)

**后续维护：** 变更时先核对上述调用链与当前官方实现；优先共用、缩小上游补丁。同步维护本卡的范围、入口、共通差异及验证依据；被上游吸收时移除对应适配并更新登记状态。原方法、历史输入和交付证据不在本卡复制或改写。

**首版登记记录：** 2026-11-05 按业务源码 `1901f83` 建立首版；首版为只读盘点及文档登记，未新增启用能力，未逐项重新执行产品验收。本轮补充项按当前源码及各自验证记录另行核对，不将首版记录冒称本轮业务验收。
