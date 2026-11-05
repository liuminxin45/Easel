# C-03 旧工作台、通知、资料库与自动检测

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

- **状态：** 已退役／迁移兼容。本条不是“已确认能力”登记，不能用于新增私有功能。
- **记录范围：** 旧 URL、旧壳/SW/安装入口、通知/设备、个人资料库、旧桥接与自动账号检测。
- **处理边界：** 仅保留已实现的重定向、410、原件和输入迁移；不能启动旧写入者。明确的登录/手动资料导入不等于恢复自动账号检测。

**当前存量位置：** [easel_workbench/runtime/toolbox_server.py](../../../easel_workbench/runtime/toolbox_server.py)、[easel_workbench/assets/legacy-handoff.html](../../../easel_workbench/assets/legacy-handoff.html)、[easel_workbench/assets/legacy-handoff-sw.js](../../../easel_workbench/assets/legacy-handoff-sw.js)、[easel_workbench/runtime/distribution_entry.py](../../../easel_workbench/runtime/distribution_entry.py)

**需求／退役／核对依据：** [docs/workbench/RETIREMENT-20261031.md](../../../docs/workbench/RETIREMENT-20261031.md)、[AGENTS.md](../../../AGENTS.md)

**相关验证入口：** [tests/test_workbench_skill_retirement.py](../../../tests/test_workbench_skill_retirement.py)、[tests/test_workbench_deployment_controls.py](../../../tests/test_workbench_deployment_controls.py)

**使用统计兼容：** 私有统计设置/页面入口已迁出（见 [PRIVATE-ROUTES-20261103.md](../PRIVATE-ROUTES-20261103.md)）；旧采集/聚合代码仍在 [usage_service.py](../../../easel_workbench/runtime/usage_service.py)、[diagnostics/usage.py](../../../easel_workbench/diagnostics/usage.py) 与 [core/usage.ts](../../../web/frontend/src/workbench/core/usage.ts)。保留既有队列/历史不代表允许恢复私有统计面板，也不得凭仍有接口推断新产品需求。

**本机网络残留清理（2026-11-05）：** Tailscale 8443 的 `/api/workbench/agent/` 仍转发到已无监听的9140，与应用对旧桥接返回410的退役行为不一致。保存配置后仅移除此具体handler，8443根路径仍转发9123，443/10000/9446及Funnel标志保持；Tailscale不再为旧Agent路径另做业务分流。它不是此次 `/native` 短暂断连的已证实原因，也不恢复旧桥接。

**后续维护：** 先核对真实调用方、请求准入和历史依赖；未经明确需求不恢复退役业务。待核对项只有补齐需求依据并确认范围后，才能迁入新的已确认能力维护卡；不得把本表当作自动启用或删除清单。

**登记记录：** 2026-11-05 按业务源码 `1901f83` 记录存量；本次不修改接口、运行开关、历史数据或部署版本。
