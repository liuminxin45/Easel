# 稳定性上线与真实故障演练（2026-11-01）

当前线上后端 `workbench-20261101-032442`（caeddd51c039694ddaadef013ab74d472b93ab1a883873411c57db963ee430e9），前端 `native-mobile-loop-20261101`（22e19e192f347d04c28bf86407dc8a94097cb87ae15fed389c5c3495c31faa1d）。后端冻结源码 `232de6fc96e94c2b9228b30d005506c4af8d4b85`。

Windows AINewsDesk 任务以原凭据所有者启动管理器，并无限期每分钟补位；IgnoreNew 与现有 OS 锁阻止重复启动。升级后的真实父进程链核对为系统任务来源，不依附 Codex 或部署命令。

本次完整定向后端回归266项、冻结前后端桌面/模拟移动制作闭环34项通过。此前两项部署测试旧fixture导致的失败保留；修复后整组266项已重新执行，不沿用旧失败声明。闭环涵盖自动采集、选题、贴图V1、拒绝、修改V2、独立检查、下载和采纳；外部模型使用TEMP合成执行器，非实际用户制作或发布。

上线只读检查：八入口、七角色，旧后端进程0；六个认证请求并发时，本地健康检查64次全部响应，最大0.5110秒。两个HTTPS入口路径均一次跳转到实际登录页。模拟390px真实Edge，未冒称已验实体vivo或独立公网链路。

真实故障演练只终止准确创建身份的管理器，系统在63.95秒后重新启动并接管原七个角色PID；22次连续HTTP检查成功，前后端选择器字节不变。此前超时及检查器错误报告保留，不抹去失败。

原贴图冻结输入、输出和22个注册文件保留；两个历史unknown缓存字节不变，未重放未知请求。新中断回合7a31d532-5b62-4d3a-a7cb-7b881c78e085通过准确原生thread/read、原始行哈希和TEMP演练核对，追加原记录日志，未制造成功回执。未复制或恢复权威数据库。

切换前先等待实际采集自然结束；新闻概述仍可能继续进入，因此使用既有cutover_paused临时开关阻止自动增强继续启动，保留原配置字节，完成随后授权集成后恢复。没有绕过空闲、队列或unknown门禁。

实现与后续最小方案见[连接恢复方案](CONNECTION-RECOVERY-20261101.md)。本批已实现进程退出自动恢复和同步IO隔离；HTTP假死自动终止、分层Tailscale探针与冷却熔断属于下一阶段，未算作已上线。最初管理器退出原因仍未确定。Windows原所有者需保持登录，锁屏可以；主机电源与网络仍是单机边界。

实际证据：`.local/workbench-validation/connection-20261101`，Spec Kit `t-e108ccddebcb4f71`。全部代码仅推自有origin，upstream push保持disabled。任务调度[IgnoreNew语义](https://learn.microsoft.com/en-us/windows/win32/taskschd/taskschedulerschema-multipleinstancespolicy-settingstype-element)另经微软文档核对。
