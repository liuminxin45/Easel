# Easel 项目级 Codex Spec

2026-11-01 按用户要求从 Spec Kit 2.0.0 干净升级至
[liuminxin45/codex-spec v0.1.0](https://github.com/liuminxin45/codex-spec/releases/tag/v0.1.0)。
迁移按发行版的[安装与干净升级说明](https://github.com/liuminxin45/codex-spec/blob/v0.1.0/docs/agent-setup.md)执行。

## 当前入口

在 `D:/Projects/Easel` 的新一轮 Codex 对话中使用：

```text
$codex-spec 按项目约定处理这项需求。
```

技能入口为 `.agents/skills/codex-spec/SKILL.md`，含发行版的七份按需指南。
若当前客户端尚未发现新技能，可直接读取该入口，或在本项目中新建会话。
项目配置为 `.codex-spec/config.json`，需求记录使用 `specs/<id>/spec.md`。
CLI 不包含旧阶段引擎、任务执行器、锁或分支管理；项目自身的交付、并发与部署约定继续有效。

技能和发行版文档中的 `codex-spec ...` 均使用项目包装入口：

```powershell
pwsh -NoProfile -File ./scripts/codex-spec.ps1 --version
pwsh -NoProfile -File ./scripts/codex-spec.ps1 context --json
pwsh -NoProfile -File ./scripts/codex-spec.ps1 check --kind installed --json
```

包装入口以本项目根目录运行，透传参数和退出码，并为子进程启用 UTF-8。
既有全局 `specify` 属于其他项目，不修改；本项目不再提供旧命令别名。

## 锁定安装与复装

- 发行提交：`cee4fdd00a4cba7ef43fa842327714e1cc84332b`。
- wheel：`codex_spec-0.1.0-py3-none-any.whl`。
- SHA256：`de46d2df56ca97de72b26b95a5d7da24d087244739a6aace928429f838f427aa`，
  已同时核对 Release 元数据与 `SHA256SUMS.txt`。
- CLI 独立安装在 `.runtime/codex-spec/`，Python 使用已有 3.14.7，不安装或替换项目 Python。
- 包无运行依赖；`scripts/requirements-codex-spec.txt` 固定 URL 和 SHA256，安装启用 `--require-hashes`。

```powershell
pwsh -NoProfile -File ./scripts/install_codex_spec.ps1
```

需要 PowerShell 7、uv 及已有 `.runtime/workbench-python/Scripts/python.exe`。
新检出可通过 `-PythonPath <已有 Python 3.11+ 的绝对路径>` 指定解释器。
受管理技能、配置和入口已经入库；复装只同步独立环境并只读核对安装结果，不覆盖自定义指南。
将来更新发行版时需审查差异后再显式运行 `init`；有定制冲突时不得盲目使用 `--replace`。

## 旧版本退役与档案

以下旧内容已移出活动项目路径：`.specify/`、`.agents/skills/speckit/`、
`.runtime/spec-kit/`、`scripts/specify.ps1`、`scripts/install_spec_kit.ps1`、
`scripts/requirements-spec-kit.txt`；旧 AGENTS 入口与旧忽略、字节规则同步移除。

本机完整归档位于 `.local/tooling-archive/spec-kit-20261101/`，按原相对路径保存，
`manifest.json` 记录 1,643 个文件的大小与 SHA256，移动后逐一核对一致。
包括 22 个历史任务目录、原始请求、人工反馈状态及旧证据引用；未把旧日志转换成新 Spec 或重写验收结果。
旧虚拟环境仅为字节档案，移动后不作为可运行环境使用。

历史文档中的 `.specify/tasks/...` 可在上述归档内按同一路径查阅。
旧安装说明保留为已退役的历史记录；受版本管理的旧代码可从升级前提交
`9de5a78d659e8c52e486d111271fb3c5786cfdf4` 找回。
任务日志及本机档案不推入 Git，避免把本地请求和操作记录带入开发工具源码。

产品业务文档、`easel-upstream-sync` 技能、内容生产技能及其冻结版本均保留。
本次只迁移开发工具，不切换、重启或部署生产前后端。

## 验证

迁移的原始 Release 元数据、校验清单与本地验证输出位于
`.local/codex-spec-upgrade-20261101/`。具体检查结果随
`specs/codex-spec-upgrade/spec.md` 记录；这类检查证明开发工具可用，不代表新增产品或实体手机验收。

四类 CLI 结构检查、8 组迁移检查及 Git 暂存内容的独立安装/复装均通过，
原项目架构、技能策略和技能命令三组回归 `85 passed`。
