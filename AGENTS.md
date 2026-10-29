# Easel 私有工作台约定

## 当前产品方向

以本项目为主工程，自有工作流位于 `easel_workbench/`，界面位于
`web/frontend/src/workbench/`。上游 `easel/` 与原 `App.tsx` 尽量保持独立；
从 `upstream` 跟进更新，保留本地 fork 的 Python 自定义采集协议。
`D:/Projects/ai-news-desk` 保留原件、历史版本与迁移证据，不再启动另一组业务写入者。

- 私有工作台只有工作台、对话、技能库、内容库、账号、画像六个主入口，设置置底；工具注册唯一来源仍为 `/api/config.tools`。
- 贴图/文章通过内容生产技能与同一作品流程执行；原始反馈、精确版本、冻结文本、附件和操作ID保持。未确认发送及回执未知不可重放，反馈不自动制作。
- 创作画像、执行身份、真实平台账号独立建模。技能源仍为 neo-content 的 `.agents/skills/capabilities.json`；不复制另一套规则、不自动发布候选或改变默认技能。
- `easel_workbench/skills.py` 只管任务范围、必选规则和启动动作投影；前端消费该策略，不按技能ID另写路由。组合技能不增加模型回合；版本、队列、授权与回执保留在程序服务。
- 内部已受理执行快照须核对SHA、任务、画像和准确技能版本后传递，不在重试时重解析候选状态。HTTP不得注入该内部快照参数。
- 沿用原 Codex 执行与交付授权合同。采纳、归档、Git同步及平台交付分别核验；连接成功不等于已验证发布能力。用户授权按需整理经验，无新增自动学习、无人值守制作或发布。
- 原通知页、通知设备、顶部通知/设置、旧自动账号检测与个人资料库继续退役。私有profile不自动启用上游媒体、发布驱动或任意模型切换。

## 运行与验证

- Node 固定 24.19.0。私有工作台 Python 位于 `.runtime/workbench-python`，使用已验证的 Python 3.14.7 及依赖闭包；原 `.venv` 保持上游独立环境。
- 前端在 `web/frontend` 运行 `npm run check:workbench` 与 `npm run build:workbench`。原 Easel build 保持独立，正式私有界面为 `/native/`。
- 架构改动运行 `tests/test_workbench_architecture.py`、`test_workbench_skill_policy.py` 和 `test_workbench_skill_commands.py`；验证依赖方向、真实TEMP排队与准确冻结版本，不能以页面展示替代执行证据。
- 正式后端来自不可变 `workbench-releases/`，前端来自 `native-releases/`；指针位于 `data/active-workbench.json` 和 `data/active-native.json`。不得手改历史资产。
- `launcher.pyw` 只监督私有profile。每个角色持有OS锁，进程接管/停止必须核对完整创建时间和准确启动参数。暂停文件不是进程已停止的证据。
- `.local/workbench-deployment/admission.json` 控制业务写入与后台启动；迁移期间外部 handoff/review CLI 也必须遵守 cutover/owner 标识，不能回落旧库。
- 部署先核对身份、空闲、原生队列和未知回执，再停旧写入者、复制/核对完整数据库行与文件SHA，最后开放新写入。采纳后的新数据不得通过恢复旧数据库丢失。
- 业务数据仍以服务器为准；浏览器只保留获准输入、附件与操作身份/统计队列。保留原HTTPS origin、草稿键和未知请求身份；401/退出不删草稿。
- 模拟制作与平台操作只用TEMP数据和假执行器。明确区分合成执行、真实只读采集、实际Windows浏览器与模拟移动端，不冒称真实模型质量、真实发布或实体vivo验收。

## 迁移与维护记录

架构与验收记录位于 `docs/workbench/`，不可变候选和实际证据位于
`.local/workbench-validation/`、`.local/workbench-deployment/`。
两份外部CLI适配器位于 neo-content 的 `工具/内容工作流/`，它们验证活动manifest后
使用私有命名空间；修改时不得顺带改技能、规范、历史冻结输入或原话。
