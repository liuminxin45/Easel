# PC-28 页面性能诊断

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

- **状态：** 已确认；私有可靠性诊断。
- **需求依据：** 用户要求定位 WebToApp 与 PC 首次打开、页面切换及“正在打开”的等待，以汇总加慢例控制开销。
- **能力范围：** 首屏、外壳、数据就绪、慢请求和内存采样；不记录业务正文、完整地址、账户凭据或用户输入。
- **官方复用：** 原 Easel 页面与状态卡保持不变；只在私有宿主、导航和原有请求适配处采集。
- **接口与状态归属：** 同源、登录、CSRF 校验的 `/api/diagnostics/page-performance` 接收受限元数据；独立有界日志位于 `data/logs/page-performance`，手机端仅保存有限待发诊断，不触及草稿。
- **不可破坏的合同：** 上报丢失、失败或磁盘异常不可阻塞或重放业务；关闭诊断不能清除草稿；内存压力不能触发自动重启；未运行客户端脚本的失败不可冒称已观测。

**私有入口／资源：** [page-performance.ts](../../../web/frontend/src/workbench/platform/page-performance.ts)、[navigation.ts](../../../web/frontend/src/workbench/platform/navigation.ts)、[host.tsx](../../../web/frontend/src/workbench/host.tsx)、[entry.ts](../../../web/frontend/src/workbench/entry.ts)、[workbench.html](../../../web/frontend/workbench.html)、[auth.html](../../../web/frontend/auth.html)、[transport.ts](../../../web/frontend/src/workbench/core/transport.ts)、[page_performance.py](../../../easel_workbench/diagnostics/page_performance.py)、[native_preview.py](../../../easel_workbench/runtime/native_preview.py)、[toolbox_server.py](../../../easel_workbench/runtime/toolbox_server.py)、[entry.py](../../../easel_workbench/entry.py)、[独立中控](../../../tools/health-control/easel_health_control/)。

**验证入口：** [test_workbench_page_performance.py](../../../tests/test_workbench_page_performance.py)、[pagePerformance.test.mjs](../../../tests/frontend/pagePerformance.test.mjs)、[test_page_performance.py](../../../tools/health-control/tests/test_page_performance.py)。

**后续维护：** 更新此卡、速查表和相关验证；合并上游时检查宿主接缝。调试事件只用于诊断，不修改业务身份、历史、用户授权或每日真实 Agent 预算。

**登记记录：** 2026-11-06 根据用户明确要求登记；实际版本与部署结果另行核验。
