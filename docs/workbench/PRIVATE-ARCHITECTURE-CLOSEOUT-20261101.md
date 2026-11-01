# P0/P1 余项处理

Spec：`private-workbench-architecture`。本轮授权：用户要求逐项处理此前列出的职责、符号归类、动态/历史入口及 P1 发布余项；随后明确实体设备暂不可用，先完成其余项。

## P0：职责证据补齐

原清单中的 **42 个 per-slice-review + 7 个 split-by-symbol** 已逐项形成源码职责记录，见 [机器可核查清单](private-architecture-review.json)。这份清单只用于维护，不被应用加载，不是第二份任务/工具注册表。原始初步清单保留为历史，不覆盖其规划状态。

每个模块记录职责、目标归属、当前/历史读取/旧执行/核对/退役围栏等用途、状态合同、后续切片和本次源码 SHA。调用者、SQL 写入目标和资源位置从当前源码重新生成，不把这些易变事实复制到另一张人工台账。其余非本轮待核对模块仍沿用原清单，本轮不据此声称全部运行路径均已实测。

七个混合模块的 **257 个符号** 已覆盖，分类包括：

| 模块 | 已确认的不同职责 |
|---|---|
| creator_runtime | 启动种子、画像绑定、技能版本/发布、跨域快照解析、资源与 ZIP；`_publish` 属技能发布，不能按方法名误归为画像操作 |
| desk | SQLite 连接/初始化、资讯采集与查询、规范化采集文件落盘、旧 CLI；`Store.action` 当前只允许已读及选题反馈 |
| distribution_runtime | 当前仍复用的 DPAPI/ACL、进程身份/锁，与旧 bridge 接入分开；整文件不能按旧名称删除 |
| easel_integration | 配置修订、方案与同事务受理、作品查询、子进程及未知任务核对；新任务继续遵守原运行标志 |
| learning_service | 证据索引、候选命令、规则解析/冻结与任务租约；索引刷新不等于自动制作或经验采纳 |
| task_runtime | 快照、原生目标适配、调用台账、状态投影及显式经验/引用任务；保留准确输入及 unknown 语义 |
| toolbox_store | 启动装配、历史导入、作品命令/查询、文件登记；初始化顺序与同一连接事务不变 |

类容器的归类不能自动覆盖未核对的方法。检查会拒绝漏掉的方法、冲突归属和已不存在的符号；闭包可继承已归类函数的职责。源码 SHA 变化会明确报告，不把旧记录继续当作当前证据。

这里只完成 P0 的职责与迁移依据，**没有执行 P2–P6 的搬迁**，也没有把尚在运行的业务文件改名为 compat 后宣称已完成。

## 动态入口与历史职责

- `entry.main` 的静态未解析导入由七个 argparse 角色与固定 module/function 字典约束，server 单独走原应用装配。
- 账号脚本的模块名由平台分支决定；默认原生登录走原 Easel 适配，旧账号 runner 已关闭。保留的 `easel_account_worker` 仍供发布子进程发送前身份核对。
- 发布脚本的 readonly 分支仅选择读回所需模块；发送分支的固定通道脚本仍由准确版本/账号及交付授权保护。未进行真实平台写入。
- `easel_media_worker`、`easel_publish_worker`、`native_package_worker` 由显式子进程入口调用，缺少普通 import 调用者不等于死代码。
- `direct_handoff` 是外部桌面 CLI；既有 TEMP 子进程回归核查活动清单及 cutover/owner，不能落回旧业务库。
- `EaselMigration` 与 `easel_readback` 当前默认装配没有调用，保留显式迁移工具/只读兼容转换；这不足以授权删除历史入口。
- `notifications.retire` 保留历史查询，删除旧触发器并以数据库围栏阻止新增；注册和轮询已拒绝。不能把迁移方法中出现的 CREATE/INSERT 当作通知功能恢复。

4 处静态未解析导入都有来源、有限取值及职责说明；任意 Python 反射和生产运行可达性仍不由静态清单证明。

## 写入者与资源绑定

审计增加 SQL 的目标表与常量模板，区分真实写表、动态目标和仅作为值出现的 SQL 字样；不把 UPSERT 的 `DO UPDATE SET` 误识别为写 `SET` 表。使用真实 TEMP SQLite authorizer 对照 INSERT/UPSERT/UPDATE/REPLACE/DELETE 的实际写入，动态表名仍保持未解析标记。

特别保留：

- `media_install_jobs` 仍由原安装合同使用；当前配置/账号入口调用 `connection_environment`，`media_environment` 仍被旧媒体接入引用。没有新建第二个安装队列，也没有误删同名旧状态。
- 作品、画像、技能、交付的跨域写入仍共享原连接/事务；本轮没有移动存储实现、改表、改 ID 或恢复数据库。
- 67 处 `__file__`/相邻资源定位继续保留准确源码证据；原子临时文件命名与代码资源绑定分开理解。本轮未移动任何资源。
- 清单额外列出 15 个关键冻结包成员，覆盖 vendor 来源、媒体脚本、平台回读、B站和公众号固定 builtin 脚本、浏览器清理、旧 bridge 与 PWA 入口。B站上传实际来自 `skill-bilibili-upload/scripts`，不能假设在 shared/scripts 下。

重建当前证据：

```powershell
& .runtime/workbench-python/Scripts/python.exe scripts/audit_workbench_private_architecture.py --check --review docs/workbench/private-architecture-review.json --output .local/workbench-validation/private-architecture-closeout-20261101/reviewed-inventory.json
```

## 验证与 P1 交付

本轮原始结果保存在 `.local/workbench-validation/private-architecture-closeout-20261101/`。首次全组结果 193 通过、1 失败：并行 UI 增加的 `useBrushPopover.ts` 尚未登记到上游修改面。总调度核查了共享叶子接缝及实际浏览器依据后，仅登记该准确文件；未放宽目录边界。最终原架构与私有审计 **71 项通过**（`boundary-final.xml`）；平台账号、真实 TEMP 外部 CLI、旧归档、部署围栏、源码冻结和迁移审计 **119 项通过**（`compatibility.xml`）。合同、技能、下载/媒体等未受后续维护改动影响的检查沿用首次对应通过结果，不把这些重叠轮次相加冒称不同测试数量。

P1 产品源码未改；本轮只修改维护审计、职责清单、测试和说明。原 P1 源码对照及下载证据仍对应准确源文件。冻结候选必须使用已提交源码与总调度确认的前端，继续核对所有成员 SHA、关键资源、导入/角色合同及 TEMP 下载路径，再交总调度按准入、空闲、原生队列、未知回执与进程身份部署。

实体 vivo/WebToApp：用户本轮明确暂时没有设备，实机保存验收保留待办，不再作为当前可完成项，不冒称模拟视口已覆盖实体保存。
