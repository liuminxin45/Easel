# 设置与运行配置对齐：已上线

本轮按用户明确选择实现完整三分类、五引擎和六通道设置。界面复用 Easel
`SettingsPanel`、`HarnessSettings`、`EnvBoard`，通过可选请求端口接入私有登录、CSRF
和操作回执。原 Easel 前端继续使用默认请求实现，没有反向导入私有服务。

## 运行合同

- 默认 Codex；明确保存后的引擎、模型覆盖、Codex 沙箱及自动授权只用于新会话。
  已有会话保持准确运行配置修订，受理回合保存其配置，不在恢复时读取新的默认值。
- 五个引擎为 API 仅聊天、OpenClaw、OpenCode、Codex、通用 ACP。API 模式使用原
  `easel.direct_api.stream_chat`，不能受理本机技能或制作。OpenCode/ACP 复用原
  ACP/RPC 连接池。独立核验仍保留原专用只读 Codex。
- OpenClaw 使用原生 `agent --local --json` 与项目隔离状态目录，配置按修订保存；
  不启动或改写已有网关。原生 JSON 没有 run ID 时记录完整 CLI 结果 SHA 与原生
  session ID，不伪造原生 turn ID。ACP 则明确记录实际 JSON-RPC 请求身份。
- 六通道为对话、转写、配音、生图、视频、音乐。供应商展示、字段校验、模型列表、
  主备选择及实际支持的自测来自上游设置实现的静态投影。投影不导入 `web.app`，
  由 `scripts/extract_workbench_settings.py` 重建，测试比较真实上游 AST 防止漂移。
- 凭据保存在服务器 DPAPI 凭据仓。浏览器不持久化 Key，只保存待核对操作 ID、
  路径和请求指纹。丢失回执查询原操作，不自动重复保存、自测或安装。
- `/api/status` 读取真实 CLI 发现结果，HTTP 可达不冒充 CLI 安装。已经安装、原生
  登录和模型可用性分别表达；实际 Codex CLI 发现通过，未声称已验证登录或模型。

## 界面与依赖

设置包含模型配置、环境安装、更多设置。原使用统计移入更多设置，官方未实现的
网关与通用设置仍标明预留。旧环境深链进入新的环境分类；退出登录不清除既有输入。
手机端模型表格纵向排列、环境卡片两列，提供字段名称与 44px 控件。内部确认框的
Escape 只关闭该确认框，不会同时关闭设置。

环境安装覆盖官方工具清单，并与账号页共享 `media_install_jobs` 和同一项目隔离目录。
Node 24.19.0、工作台 Python 3.14.7 仅检测，不能被全部安装替换；不修改上游 `.venv`
或全局 PATH。需要 Remotion 工程的配方检查项目内 lockfile。恢复中断安装只复测依赖，
不会重新执行安装。安装进程仍在运行时不准入部署。

## 候选与验收

- 后端：`workbench-20261030-065654`，manifest
  `02bbc5f1c7f9d6d878b1e69bdf1e802246ce421adb89f52587ad05f662086818`。
- 前端：`native-easel-workbench-20261030065600`，manifest
  `e5cda00307c95941cf36ad6abcf64aa785067d9f4b5acf35aaafddb5fcee19cc`。
- `check:workbench` 和 `build:workbench` 通过；前端 199 项测试通过。
- 设置、架构及技能合同测试 100 项通过，原生会话、交付、独立检查回归 96 项通过；原 Easel
  适配器使用独立 `.venv` 验证，96 项通过、6 项按原条件跳过。
- 实际 Windows Edge 与模拟手机分别验证设置、对话、制作流程，共 40 项检查通过。
  6 组 TEMP 制作文件实际生成，准确参数、SHA、父版与未知回执不重发均核对。
- 浏览器针对准确冻结候选执行并核对文件 SHA。截图已查看；真实模型调用、真实依赖
  安装和平台写入均为 0，没有实体手机或真实模型质量验收声明。

证据位于 `.local/workbench-validation/settings-final-065654/`、
`settings-chat-regression-065654/` 和 `settings-production-regression-065654b/`；
前端、合同及运行时测试原始日志保存在同一验证目录。

## 部署状态

首次准入检查曾发现真实制作任务
`561de46a-a18f-45c9-89b7-44386ce7d544` 的服务器与作品状态仍为回执未知。
只读检查其准确原生 session/turn 的 rollout 仅取得开始事件，没有完成或停止回执。
没有重发、停止或改写该任务，也没有把它手工改成空闲。按 AGENTS.md 的部署要求，
当时保留线上指针和进程，等待准确原回执核对。

已实际执行 `scripts/upgrade_workbench_runtime.py --acceptance
.local/workbench-deployment/settings-alignment-acceptance.json`，返回 `status: waiting`。
切换前后活动前后端指针、manager 与 7 个角色 PID 均相同，没有复制或恢复数据库。
实际输出与复核位于验收目录的 `deployment-attempt.log`、`selectors-and-processes.json`。

工作区存在其他任务的并行改动；本候选只对其冻结 manifest 负责，后续上线前仍须核对
准确候选、当前活动指针、技能源码、空闲与原生队列，不能据此恢复旧数据库。

## 后续实际部署

用户明确要求部署上线后，通过原生 `thread/read` 读取准确 session 和 turn，取得
`status: interrupted`、线程 `notLoaded` 的原生结果；不是把缺少 rollout 完成事件
推测为成功。对精确数据库副本先演练核对，再以原行 SHA 保护的单事务登记原回合中断。
原始 turn、session、job、model call、run 保存到独立核对台账；输入、技能、prompt、SHA、
附件、原生 ID、部分回复和已生成文件保留。原任务没有重发、采纳、发布或标为制作完成。

空闲和原生队列检查通过后，使用
`.local/workbench-deployment/settings-deploy-20261030-acceptance.json` 执行正式升级，返回
`status: live`。当前前后端就是上述冻结候选，数据库没有复制或恢复。

线上验证通过：三个设置分类、五引擎发现结果和六个模型通道正常；侧栏实际显示
`codex CLI 已安装`。原生模型目录实际读取 8 项，未进行模型推理或声称模型可用性已验证。
实际 Windows Edge 和模拟手机打开线上设置均无 JS 错误和横向溢出。manager 与 7 个角色
的完整创建时间、准确启动参数和存活状态已核对，后台准入恢复。

部署证据位于 `.local/workbench-validation/settings-deploy-20261030/`；正式切换回执为
`.local/workbench-deployment/upgrades/workbench-20261030-065654.json`。
