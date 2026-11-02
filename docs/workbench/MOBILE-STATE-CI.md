# 移动端状态回归 CI

`.github/workflows/workbench-mobile-state.yml`只在自有fork `liuminxin45/Easel`执行。
相关源码推送到main、相关PR或手动触发后，Windows/Linux分别执行同一组检查：

- Node固定24.19.0，使用锁文件`npm ci`，完整Git历史用于官方祖先与唯一实现检查。
- 全部前端Node测试，含返回快照/滚动状态、认证隔离、轮询、版本检查、弹层与原回执不重放。
- Python3.12只安装轻量验证依赖；历史窗口、架构、技能策略和命令检查使用TEMP数据。
- 宿主类型/交互/官方祖先检查，原Easel独立构建和私有宿主构建。

工作流只有contents:read权限，不调用生产模型、不发布内容、不部署，也不向官方仓库提交。
媒体与模型运行时没有进入这组检查的安装闭包。完整页面与实体vivo验收仍由对应的部署验收提供，
不能用Node用例冒充实体WebToApp结果。

最近已核对的仓库级限制是：既有验证工作流的GitHub实际dispatch返回HTTP422：`Actions has been disabled for this repository.`，
即使仓库enabled=true、workflow active也不能声称托管CI已经运行。服务端限制恢复后，这个工作流
才会按触发条件自动运行；本地检查和部署准入继续独立生效。每次交付应记录真实run URL与结论，
未运行时保留明确的未运行状态。
