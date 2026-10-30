# 2026-10-30：Easel 原生会话、项目技能与直接制作已上线

正式入口：https://leopc.tail2ce65.ts.net:8443/native/

- 后端：`workbench-20261030-020901`，manifest `65fa424eeca11996ae1fdd622bb3d1d4393e74cb8868889c3b770b62a4ad4f2c`。
- 前端：`native-easel-workbench-20261030031621`，manifest `6471dccf38a94955b3cfac64f2c34deb861bb45b08e031db5fb63316358f9265`。
- 主工程与权威数据目录：`D:/Projects/Easel`；切换使用原数据库，没有复制或恢复旧库。
- 2026-10-29 的部署与迁移记录保留在 `STATUS-20261029.md`，以下为本轮最终状态。

## 完成的核心对齐

新建对话、贴图与文章入口统一使用原 Easel ChatPage、Sidebar、SkillPage/Drawer、CodexAdapter、原生 RPC 连接池和项目 session binding。服务器先建立会话；`/` 或 `+` 选择真实技能，发送即冻结并提交。一个会话可关联多份作品，修改保持准确父版；只讨论版本不会误触发制作。停止需要原生 ACK，重连只订阅原任务，未知回执不重放。

8 项业务技能在 `skills/builtin/`，资源在 `skills/shared/workbench/`。当前声明唯一来源是各 SKILL.md，来源报告不是第二份注册。全局目录没有安装这些技能。实际发布版本 v2 与油猪大侠画像修订 2 已通过审核过的机械迁入计划激活；旧 v1、画像历史、任务及冻结输入未改写。候选、明确试用、发布/恢复与项目源码同步保留，源码同步失败时不可假装可用。

参考分析、按需经验整理、独立核验和新闻增强的新本地技能通过同一 Easel CodexAdapter 执行；保留只读配置、图片、schema、推理配置、预算和真实回执。没有新增学习定时器或无人值守初始制作。原授权一次的有据内部修正继续同一原生会话、准确技能与独立子目录；后到用户输入先接管，旧执行器不接新会话的纠错任务。

对话、作品、核验和交付事务分开记录。预览在一次性数据库副本编译真实核验合同，受理时在同一事务核对；有文件不能绕过独立核验与采纳门禁。只缺设计说明时补说明并保护主成品字节。新闻原件/来源/provenance、产品文章类型、旧草稿明确要求和附件随本轮冻结。原始反馈、人工文案、局部采纳、归档和平台授权继续沿原合同。

通知、通知设备、顶部通知/设置、旧自动账号检测、个人资料库与未授权媒体设置保持退役。账号、画像和内容库继续保留真实账号实例、修订与准确版本台账，不以扫描目录代替发布事实。

## 设置页简化

按用户要求删除“外观”和“登录与安全”条目及对应面板，设置页直接显示“使用与路径”，移除单项分类栏和不再使用的设置组件参数。旧设置分类链接及 `/account` 进入剩余设置内容；侧栏主题切换和服务端登录保护继续有效。

178 项现有前端测试通过；Windows Edge 与模拟手机共 8 项设置/旧链接检查及 8 项在线升级恢复检查通过，截图已查看。验收只使用 TEMP 服务，无真实 AI 调用或平台写入。前端单独切换，后台 manager 和 7 个角色的 PID/创建时间均未变化。

验收位于 `.local/workbench-validation/settings-031621/`，实际切换回执为 `.local/workbench-deployment/frontend-upgrades/native-easel-workbench-20261030031621.json`。

## 直接制作更新与验证

移除只读的“确认本次制作方案”弹窗。对话、旧作品修改与首版制作均在同一次操作中编译冻结输入并提交，服务器原有凭据、受理和回执合同保持。产物和成品页提供折叠的“制作参数”，仅在展开时按准确版本读取保存的画像、技能、完整指令及 SHA，不回填当前默认设置。明确拒绝后可修正再发；等待期间的新输入不被受理回执清除。

最终 Node 24.19.0 前端测试 178/178，通过 Windows Edge 与模拟手机的 12 项定向操作检查，实际生成 6 组 TEMP 文件（贴图、文章及指定父版修改）。准确核对参数与数据库冻结正文、SHA、技能版本；连续点击仅 1 次 plan/stream，未知回执重查和刷新不重发。两端展开参数截图可读，无横向溢出。模型为隔离假执行器，真实 AI 调用与平台写入均为 0，未声称实体 vivo 验收。

当前正式前端到本候选的 8 项在线升级、IME、草稿及离线恢复检查全部通过。前端独立切换工具另有 17 项 TEMP 测试；上线仅原子更新 `active-native.json`，7 个后台角色及 manager 的 PID/创建时间前后相同，没有重启后端或围栏中断制作。运行包 manifest 中的 native 保留其构建时配套记录，当前服务实际读取独立前端指针。

- `.local/workbench-validation/direct-send-025529/browser-root/native-browser.json`：12 项操作与 6 次模拟执行，含截图哈希。
- `.local/workbench-validation/direct-send-025529/frontend.json`：178 项测试及原始日志哈希。
- `.local/workbench-validation/direct-send-025529-upgrade/upgrade.json`：8 项正式前版升级恢复检查。
- `.local/workbench-validation/audit/frontend-activation.xml`：17 项独立切换工具测试。
- `.local/workbench-validation/direct-send-live-parameters-baseline.json`：正式旧作品参数与保存正文、SHA 一致。
- `.local/workbench-deployment/frontend-upgrades/native-easel-workbench-20261030025529.json`：实际切换、线上资源核验及进程身份。

## 此前原生会话对齐验证

- 328 项专项回归在准确后端快照通过；所有已载入 easel/easel_workbench 模块均来自该快照。
- 184 项既有业务合同通过，覆盖旧任务、发送恢复、版本、核验、采纳、平台连接、发布授权、鉴权与退役接口。
- 27 项 Windows Edge / 模拟手机浏览器检查，7 次真实 TEMP 文件制作/修改通过。
- 8 项在线升级、IME 推迟切换、离线启动与联网恢复通过；新会话路径和原字草稿保持。
- 原生制作→独立核验→补说明→采纳→本地完成清单通过；主成品 SHA 保持，采纳没有新增模型回合。
- 173 项前端合同、原 Easel TypeScript 与私有 strict/build 通过。
- 原上游 harness/workspace 96 通过、6 项平台跳过；默认上游行为保持。
- 实际 Codex CLI 0.164.0 零模型核验：准确主工程、现有登录、模型目录、原生 thread 同连接与连接池复用、工具能力及进程收尾通过。项目技能按 Easel 工作区路径和冻结正文传入，未冒称原生全局 /skill 发现。

制作和平台验收使用 TEMP 与假推理/假平台，真实 AI 制作及平台写入为 0；手机是浏览器模拟，未声称实体 vivo 通过。

## 切换后复查

2026-10-30 10:20 +08 在空闲门禁和停写围栏下激活，前一运行包与前端仍保留。正式 8 个页面响应、8 项本地技能 v2 可用、画像 pins、7 个后台进程准确路径/身份均通过。11 类历史表的 1,175 行原记录哈希保持，历史图片下载 SHA 与迁入原件一致。本轮没有重排历史任务、重写旧版本或恢复旧数据库。

本次制作失败的准确未发送记录已修正其错误的 running 投影；原任务、重试额度与冻结输入不变。修复前的运行记录和核对证据保留在本地证据目录。

## 证据

- `.local/workbench-deployment/upgrade-acceptance.json`：准确候选与全部验收证据 SHA。
- `.local/workbench-deployment/upgrades/workbench-20261030-020901.json`：实际空闲切换及技能激活回执。
- `.local/workbench-validation/final-020901-unit-passed.json` 与 XML：328 项专项及运行模块绑定。
- `.local/workbench-validation/final-020901-legacy/`：184 项既有合同。
- `.local/workbench-validation/native-final-020901/report.json`：27/7/8/1 及 173 项前端证据。
- `.local/workbench-validation/final-020901-native-zero.json`：准确冻结包的实际原生零模型核验。
- `.local/workbench-validation/final-020901-live.json`：正式页面、技能、历史字节与 7 角色复查。
- `.local/workbench-validation/builtin-skill-activation/dry-run-final.json`：机械迁入的预览、范围与计划 SHA。
- `.local/workbench-deployment/backups/`：切换前独立数据库备份，只保留恢复证据，没有用于回滚。

当前架构与保留边界见 `ARCHITECTURE.md`。后续回退只使用兼容运行包并保留当前业务库，不恢复旧库、不重放未知请求。
