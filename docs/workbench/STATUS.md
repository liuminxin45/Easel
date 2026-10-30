# 2026-10-30：Easel 平台扫码、原生会话与项目技能已上线

最新发布：全局交互与设置、技能库、菜单、热点更新已整合上线，后端 `workbench-20261030-091754`，前端 `native-easel-workbench-20261030091709`。准确 SHA、最终验收与数据保护结果见 [交互整合发布记录](INTERACTION-RELEASE-20261030.md)。下文旧版本编号保留对应阶段的历史记录，当前版本以活动指针及最新发布记录为准。

本轮设置对齐已上线。原阻塞任务已通过准确原生 `thread/read` 核对为中断，保留原输入、
回执和文件，没有重跑或标记制作完成。三类设置、六通道、真实 CLI 状态及原生模型目录
已完成线上核验。详见 `SETTINGS-ALIGNMENT-20261030.md`。

正式入口：https://leopc.tail2ce65.ts.net:8443/native/

- 后端：`workbench-20261030-065654`，manifest `02bbc5f1c7f9d6d878b1e69bdf1e802246ce421adb89f52587ad05f662086818`。
- 前端：`native-easel-workbench-20261030065600`，manifest `e5cda00307c95941cf36ad6abcf64aa785067d9f4b5acf35aaafddb5fcee19cc`。
- 主工程与权威数据目录：`D:/Projects/Easel`；切换使用原数据库，没有复制或恢复旧库。
- 2026-10-29 的部署与迁移记录保留在 `STATUS-20261029.md`，以下为本轮最终状态。

## 完成的核心对齐

新建对话、贴图与文章入口统一使用原 Easel ChatPage、Sidebar、SkillPage/Drawer、CodexAdapter、原生 RPC 连接池和项目 session binding。服务器先建立会话；`/` 或 `+` 选择真实技能，发送即冻结并提交。一个会话可关联多份作品，修改保持准确父版；只讨论版本不会误触发制作。停止需要原生 ACK，重连只订阅原任务，未知回执不重放。

8 项业务技能在 `skills/builtin/`，资源在 `skills/shared/workbench/`。当前声明唯一来源是各 SKILL.md，来源报告不是第二份注册。全局目录没有安装这些技能。实际发布版本 v2 与油猪大侠画像修订 2 已通过审核过的机械迁入计划激活；旧 v1、画像历史、任务及冻结输入未改写。候选、明确试用、发布/恢复与项目源码同步保留，源码同步失败时不可假装可用。

参考分析、按需经验整理、独立核验和新闻增强的新本地技能通过同一 Easel CodexAdapter 执行；保留只读配置、图片、schema、推理配置、预算和真实回执。没有新增学习定时器或无人值守初始制作。原授权一次的有据内部修正继续同一原生会话、准确技能与独立子目录；后到用户输入先接管，旧执行器不接新会话的纠错任务。

对话、作品、核验和交付事务分开记录。预览在一次性数据库副本编译真实核验合同，受理时在同一事务核对；有文件不能绕过独立核验与采纳门禁。只缺设计说明时补说明并保护主成品字节。新闻原件/来源/provenance、产品文章类型、旧草稿明确要求和附件随本轮冻结。原始反馈、人工文案、局部采纳、归档和平台授权继续沿原合同。

通知、通知设备、顶部通知/设置、旧自动账号检测、个人资料库与未授权媒体设置保持退役。账号、画像和内容库继续保留真实账号实例、修订与准确版本台账，不以扫描目录代替发布事实。

## 平台扫码迁移与扩展退役

之前的账号页仅接入了独立登录服务，仍暴露同步助手兼容入口，分发适配器也会回落旧桥接；现有 5 条账号记录没有任何 Easel 扫码会话。本次移除该入口与回退，账号页直接列出七个平台的扫码卡片，公众号、视频号优先，无须先填写连接名称。二维码按登录修订及实际图片更新，扫码期间使用活动任务刷新频率；关闭/刷新后可以回到原登录，不重复创建请求。

实际驱动使用当前项目 `skills/shared/scripts/`，随不可变后端冻结。公众号 AppID 校验与浏览器身份分别保存，凭据不进入浏览器草稿。平台浏览器环境补齐 `opencv-python==4.14.0.94`、`numpy==2.4.6`，检测同时验证二维码识别与浏览器二进制，避免只有 Playwright 就宣称可用。

旧扩展的桥接配置、账号发现、人工检测及提交报告接口退役；旧辅助链接清除票据片段后转到账号页，新构建不再包含检测页。历史账号、加密凭据和回执保留。明确重新扫码并核对到相同身份时沿用原连接 ID、增加修订；身份不符不替换。Easel 尚无对应驱动的掘金、CSDN、博客园仅保留历史记录，不能继续走扩展。

分发唯一适配器改为 Easel，继续使用准确版本与显式批准的动作，未恢复任何无人值守发布。首次交付仅为明确试运行，登录成功不升级为发布已验证。视频号原脚本的超时恢复循环被一次提交保护约束；回执未知不再次按发表。未提供独立内容读回的平台保持待核对，B站缺少冻结分区/版权元数据时不开放上传。

验收：最终不可变后端 375 项回归、Node 24.19.0 前端 178 项通过；Windows Edge 与模拟手机账号流程 8 项、制作流程 12 项（6 次 TEMP 成品）、在线升级/IME/离线恢复 8 项通过，截图已查看。并行验收时两次升级等待超时的失败报告保留，补充失败诊断后的独立复核通过。公众号和视频号分别实际生成了真实平台二维码，未由用户扫码，不能据此宣称真实账号登录或发布成功。真实 AI 调用、平台发布写入均为 0。

服务空闲后完成前后端切换，没有恢复或复制业务数据库，也没有激活新技能版本。上线只读复核确认 7 个角色运行、旧桥接接口 410、连接器为 `easel`，原 5 条账号及 81 份冻结输入逐项 SHA 不变；真实账号需用户在新页重新扫码。

- `.local/workbench-validation/native-accounts/final-domain.json`、同名 XML：375 项准确冻结后端测试及模块绑定。
- `.local/workbench-validation/native-accounts/browser.json`：账号流程与截图；`production-final/native-browser.json`：制作回归。
- `.local/workbench-validation/native-accounts/upgrade-diagnostic/upgrade.json`：最终升级恢复验收。
- `.local/workbench-validation/native-accounts/public-qr-final.json`：两个实际平台出码与源码哈希，未宣称扫码完成。
- `.local/workbench-validation/native-accounts/live.json`：正式只读检查及历史字节保护。
- `.local/workbench-deployment/upgrades/workbench-20261030-041324.json`：实际空闲切换回执。

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
