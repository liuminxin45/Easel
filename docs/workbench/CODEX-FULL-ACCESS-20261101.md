# Codex 永久通过授权：Full access

2026-11-01 用户明确要求：开启「永久通过授权」后，所有 Codex 任务使用 Full access，不再请求人工执行审批。

原开关只自动接受普通操作白名单。现保持同一设置字段 `codex_auto_approve`，开启时原生 `thread/start`、`thread/resume` 使用 `approvalPolicy=never` 与 `sandbox=danger-full-access`，每个 `turn/start` 使用 `approvalPolicy=never` 与 `sandboxPolicy={type:dangerFullAccess}`。完整访问不再保留工作区写入或联网限制。原生兼容性命令和文件变更审批直接接受；若原生策略没有可接受决定则报错，不回退人工审批。

对应官方语义：[Codex Full access](https://learn.chatgpt.com/docs/sandboxing)。本机 Codex CLI 0.166.0 的真实临时 `thread/start` 已返回 `approvalPolicy=never` 和 `sandbox.type=dangerFullAccess`，未发起模型回合。

关闭后沿用保存的 read-only/workspace-write 沙箱与 on-request 审批。设置仅作用于新会话；已有会话及已受理任务保留准确配置快照，不重写历史输入。专用只读核验请求没有开启此字段时仍使用只读权限。OpenClaw、OpenCode、ACP、API 模式不受此开关影响。公开发布、采纳和账号状态等业务授权仍按各自合同执行；工具执行权限不新增业务任务。

冻结工作区指令与制作前检查均识别 Full access，避免旧只读回退值阻挡已授权制作。通用 Codex 适配器只使用通用请求字段，不依赖私有服务；设置继续复用原 HarnessSettings。

验收包含 TEMP 假 stdio 的新建/恢复/命令/文件审批、设置保存与会话快照、前端构建，以及真实 Windows Edge 的隔离 HTTPS 设置开关保存/重载。假执行器中的命令只作为协议数据，不实际执行系统操作或生成图片。正式部署由总调度整合独立候选后统一执行；证据和待整合补丁在 `.local/workbench-validation/codex-full-access-20261101/`。
