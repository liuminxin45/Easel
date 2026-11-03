# Easel 独立健康中控

独立 Python 3.11+、仅标准库。代码随自有 Easel fork 的 `tools/health-control/` 提交；安装、任务和状态位于项目外 `D:/Services/EaselHealthControl/`。此路径避开打包应用对 LocalAppData 的虚拟重定向，确保 Windows 任务也能访问同一环境。控制器不导入 Easel；应用子进程端口复用准确冻结版本的诊断、原生执行与既有恢复围栏。

```powershell
pwsh -NoProfile -File ./install.ps1 -AppRoot D:/Projects/Easel -Start
& D:/Services/EaselHealthControl/python/Scripts/python.exe D:/Services/EaselHealthControl/launch.pyw report
```

- `EaselHealthControl`：登录时及每分钟独立启动，普通观察约50秒；含身份围栏的恢复有180秒IPC边界，OS兜底限制5分钟、失败重启。入口 nonce、版本和进程创建身份核对，本机/Tailscale分别检测。
- 业务：读各角色进度、实际启用采集源当前版本的结果及排期；循环存活不等于采集完成。
- 性能：最近5分钟请求耗时、实际整库复制字节、锁等待和写事务；读取有界内存快照及各角色日志尾，不复制正式数据库。
- 使用与路径：原报告展示最近7天操作、访问与常走路径，当前页面与退役历史分开。只读原统计库的聚合表，沿用原保留期限；不读取原始事件/正文/文件名/凭据，不修改统计开关或清空数据。缺失或不可读单独显示，不触发重启。私有路由清单见 `docs/workbench/PRIVATE-ROUTES-20261103.md`。
- 恢复：连续3次故障、启动宽限90秒、冷却120秒、30分钟最多2次，预算跨进程重启保持；二次核对准确版本/PID创建时间/空闲/未知操作与停写围栏。仅允许既有server恢复或manager OS任务恢复。提供者500、网络故障、慢请求、正常排期、正在执行/回执未知均不强制重启。
- `EaselHealthDaily`：每天09:10执行真实采集与真实Codex Agent工具绘制PNG检查；之后每30分钟仅核对当天原操作，绝不重复受理。隔离数据与输出、严格workspace-write、无正式采纳/发布/学习权限。不将工具绘图冒称专用AI生图。
- `state/report.html`：分别列出入口、业务、性能及每日制作结果。`policy.json`、`repair-*.json`及每日原始回执保留可追溯身份；损坏或未知时停止自动操作，不能删状态“恢复绿灯”。

机器休眠/关机、Windows凭据用户退出时不能运行真实Agent；下次可用时由OS补跑。未知原生请求只核对，永不自动重发。任意代码缺陷、上游服务故障不可能通过重启可靠修好；中控会留下真实失败及诊断证据，不能把这类故障涂绿。

核心标准库测试：`python -m unittest discover -s tests -v`。完整开发验收使用应用开发环境的 `python -m pytest tools/health-control/tests tests/test_workbench_canary_export.py`（包含图片解码依赖）。真实采集/模型调用不会由单元测试或安装器启动；只有已授权的daily任务执行。
