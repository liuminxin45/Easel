# 升级项目开发工具至 Codex Spec 0.1.0

Spec: codex-spec-upgrade

## 目标与约束

用户要求以 https://github.com/liuminxin45/codex-spec/releases/tag/v0.1.0
替换本项目的 speckit 并移除旧版本。确认新版主动取消旧接口兼容，唯一入口改为 `$codex-spec`。

保留全部业务代码、AGENTS 项目约定、上游同步技能、历史任务、原始反馈和验收证据；
只退役旧开发工具，不改全局工具，不影响正在运行的工作台。

## 实现

- 发行包及其 SHA256 固定在 `scripts/requirements-codex-spec.txt`，独立环境 `.runtime/codex-spec/`。
- 使用发行版原生 `init` 安装同一份技能与七份指南，替换 AGENTS 工具入口；不另写兼容引擎。
- 新安装器只同步锁定包并核对受管理文件，包装器透传参数、UTF-8 和失败退出码。
- 旧配置、技能、CLI、包装器与依赖清单归档在 `.local/tooling-archive/spec-kit-20261101/`，
  1,643 个文件逐一核对 SHA256，22 个任务目录保留；移除旧活动入口与忽略规则。
- 使用说明、发行提交及归档索引见 `docs/workbench/CODEX-SPEC-20261101.md`。

## 验证与交付

验证均已完成，证据目录：`.local/codex-spec-upgrade-20261101/`。

- Release wheel 校验值匹配发布清单；无运行依赖，独立环境 `uv pip check` 通过。
- `installed`、`generated-context`、`knowledge-index`、`context-budget` 四类检查通过。
- `validation.json`：8 组检查通过，覆盖归档字节、旧入口退役、原约定及产品代码保留、
  异目录包装调用、中文 Spec/上下文读取、非零失败码、重复 init 幂等及定制技能不被覆盖。
- `fresh-index-validation.json`：从 Git 暂存内容还原 17 个工具文件，独立安装、复装与
  包装入口读取成功，受管理文件字节不变；不依赖本机旧 Spec Kit 环境。
- `project-regression.txt`：架构、技能策略、技能命令三组回归 `85 passed`。
- `git diff --cached --check` 通过；交付仅推送自有 fork 的集成分支。

人工反馈尚未收到。本次不需要生产版本切换；开发工具可用性与产品实机验收分别记录。
