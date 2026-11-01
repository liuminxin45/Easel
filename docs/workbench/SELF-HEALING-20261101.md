# 工作台独立健康监督与自愈

入口保持 Tailscale + WebToApp／PC浏览器。原 Easel App、页面、组件和样式没有重写；新增监督集中在私有工作台和 Windows 运维入口。

## 监督层

- `AINewsDesk` 持续监督原七个角色；退出后使用持久指数退避（3、6、12秒至120秒），观察稳定运行60秒后才清连续失败。管理器重新启动不会清空同版本退避记录。
- 独立 `AINewsDeskHealth` 使用相同凭据所有者、独立 OS 锁，每分钟触发。每次目标运行约50秒、每10秒检查；单次检查/恢复可能延长，Windows硬执行时限为2分钟，重叠启动 IgnoreNew。监督自身退出由系统下次触发接续。
- 私有 `/_workbench/health` 用专用随机token、32位nonce、准确版本和PID核对活的HTTP循环；不授予登录、制作或交付权限，token不进入前端、健康状态或事件日志。
- 分别记录本机HTTP、管理器心跳/进程身份与Tailscale HTTPS入口。公网失败而本机正常，只记网络降级，不终止业务或重置其它项目的Funnel。Tailscale现有Windows服务已配置递增失败重启，沿用其系统恢复设置。

## 恢复范围

连续三次本机连接失败／超时才进入恢复判断；新进程有90秒启动宽限。恢复动作先持久消耗预算，至少120秒冷却，30分钟最多两次。健康恢复、目标PID变化及监督重启均不清历史预算；状态损坏或时间倒退时关闭恢复。

服务器恢复依次持有后端/前端发布锁，复核活动不可变版本、权威owner、live准入、准确启动参数、创建时间、父子创建关系与监听PID。复用原升级空闲/原生队列/历史unknown门禁；原生UI预留操作新增统一检查：只有completed/rejected可视为已终结，未知或损坏记录不猜测。

无活动任务才建立带操作身份的暂停围栏，等待管理器确认暂停新增角色，再持SQLite `BEGIN IMMEDIATE`重新核对空闲与进程，最后重新探测HTTP。只有仍为连接失败／超时才终止完整、准确的server分支。其余六角色及管理器保留，原监督器负责启动替代server。不会复制数据库、改任务回执或重发请求。

正在制作、扫码、安装、交付、模型调用、未核对原生操作或无法确认身份时记录deferred，不强杀。HTTP假死时没有可靠的原生任务接管证据，不能以“恢复连接”为由把原任务当作可重发。管理器单独心跳失联时，可仅终止准确管理器，让Windows恢复并接管原角色。

暂停归属与阶段保存在 `health-recovery.json`。监督在围栏中退出时，下次持锁核对准确版本后只释放自己的遗留暂停，重新检查现实状态；不盲目续杀，不删除其他维护者的暂停。恢复历史追加到 `health-events.jsonl`，最新分层状态保存在 `health-status.json`，预算在 `health-policy.json`；不会周期改变界面布局或触发模型。

## 安装及诊断

通过本批准入并切换到包含监督模块的不可变后端后执行：

```powershell
pwsh -NoProfile -File scripts/ensure_workbench_health.ps1 -Start
```

该脚本保留原AINewsDesk身份，只登记独立健康任务；不终止业务。`-WhatIf`预览。运行中状态和日志均位于 `.local/workbench-deployment/`。硬时限仅适用于健康任务，不适用于制作worker或管理器。

`tests/workbench_health_recovery.py --exercise` 是显式Windows演练：先用现有维护开关排空可选增强，持准确句柄挂起空闲server制造“进程活着但HTTP不响应”；在健康监督拥有暂停围栏时终止该准确监督实例，观察Windows启动后续监督、接续自己的围栏并恢复server。失败时finally恢复仍存活的原挂起进程和原自动配置。该脚本不制作、不采纳、不发布。

验收必须覆盖活跃任务和pending操作不被终止、坏/重复/非ASCII健康header、真正并发token创建、坏预算、冷启动、抖动、网络单侧故障、PID复用、外来监听、维护锁、owned围栏接续、重启前预算落盘、其余六角色保持，以及冻结前后端的自动采集—选题—贴图—拒绝／修改—采纳闭环。模型使用TEMP合成执行器，不能冒称真实内容质量或实体vivo已验收。

## 单机边界

原凭据所有者仍需保持Windows登录，锁屏可用；主机断电、休眠、上游网络故障无法由工作台程序消除。主机域名探测是本机Tailscale路径，不是独立公网可用性证明。准确包、Git SHA和本轮真实故障结果见本批最终交付记录，不能用方案文本替代实际测试。

Windows[重复任务机制](https://learn.microsoft.com/en-us/windows/win32/taskschd/repeating-a-task)与Tailscale[后台Funnel持久行为](https://tailscale.com/docs/reference/tailscale-cli/funnel)另经官方文档核对；本批不重置既有Funnel或更改其它端口。
