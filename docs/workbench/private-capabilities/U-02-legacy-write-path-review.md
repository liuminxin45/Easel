# U-02 旧生产写入口的逐路由归类

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

- **状态：** 已分类／受限存量；不是新增业务许可。不能将“旧页面未挂载”当成“全部接口只读或不可达”。
- **范围：** 原生主壳不再挂载旧 `production.tsx`，但服务器仍有下表分支。每个分支分别归入现有能力、受限兼容卡或明确退役动作，不能用一个“旧代码”标签整体删除或恢复。
- **需求依据：** 用户要求保留预期私有能力、历史、输入和授权，只替换重复/错误共通实现；两个油猪技能保持分离，退役经验管理不恢复。

## HTTP 与业务边界

旧分支首先经过服务器 Host、登录会话、同源、CSRF 和 JSON 校验；其操作身份/修订由各服务继续核对。它们不因位于同一服务器就自动取得平台授权，也不能笼统宣称全部经 `NativeApi._mutate` 的新原生事务。下表是源码事实，不是本轮实际调用这些写接口的回执。

| 路径／动作 | 当前分类与实际作用 | 专门维护位置 |
| --- | --- | --- |
| `POST /api/works`、`/api/article-drafts`、`/api/drafts`、`/api/works/<id>/draft` | 作品/草稿存量写入口。保留已保存输入、原 ID、附件及修订；不因为仍有函数就恢复旧生产页面。 | [PC-04](PC-04-local-inputs.md)、[PC-12](PC-12-versioned-works.md) |
| `POST /api/works/<id>/finalize`、`/discussions`、`/api/tasks/<id>/retry` | 存量制作/讨论/重试边界，可能触发原队列；不能标为只读。新普通创作从原生对话及明确格式技能进入；旧已受理任务仍按原冻结身份核对，unknown 不重放。 | [PC-03](PC-03-persistent-chat.md)、[C-02](C-02-legacy-production-media.md)、[C-04](C-04-legacy-content-production-skill.md) |
| `POST /api/text-works`、`/api/works/<id>/text`、`/actions`、`/versions/<id>/review` | 手工文案、准确版本决定/反馈与批注仍属于既有作品链路；修改另存版本，反馈不自动制作。不能与旧技能管理一起删除。 | PC-12、[U-01](U-01-completion-options-review.md) |
| `POST /api/works/<id>/project-binding`、`/local-operations/retry` | 会写关联/恢复队列，操作本身不受 `local_io` worker 开关替代；必须核对原操作、作品与关联修订。 | [C-05](C-05-local-project-operations.md) |
| `POST /api/works/<id>/versions/<vid>/manual-review` | 显式独立检查可能排入只读模型核验队列，不是自动学习；绑定准确作品/版本及操作 ID。 | PC-12、C-05 |
| `POST /api/creative/commands`，`/api/creative/preview` | 旧样本/图稿方案命令含真实写入，preview 则是只读准备；不可仅按路径前缀判成已退役或纯读取。 | [C-07](C-07-legacy-creative-recipes.md) |
| `POST /api/learning/commands` | 分动作：index-refresh、evidence-update、分析设置/暂停/恢复及提案 dismiss 仍可能写记录；模型分析与提案创建/预览/确认/回退在 HTTP 层返回 410。 | [C-06](C-06-evidence-index-compatibility.md) |
| `POST /api/studio/commands` | foundation/config 编辑动作返回410，长期 scope 的提案受退役限制；作品 scope 的既有命令不能自动等同全部退役。发布相关仍受准确版本/授权约束。 | PC-12、[PC-15](PC-15-authorized-delivery.md)、C-06 |
| `POST /api/creator/commands`、`/api/easel/commands` | 共享兼容入口，具体动作由技能退役门控及服务核对；画像业务与历史回执保持，候选/试用/发布/回退/整理经验不能恢复。 | [PC-11](PC-11-profiles.md)、[C-01](C-01-retired-skill-management.md) |
| `POST /api/style-presets` | 已退役，返回410；不能通过更改提示文案恢复风格参数预设。 | C-07 |

## 页面与新旧技能

旧 `production.tsx` 不是原生壳当前页面，但 `NativeNewChat` 的兼容新建路径及 `DraftOperations` 是不同调用点。本轮已将这两处的新普通草稿选择统一为 [newsCreation.ts](../../../web/frontend/src/workbench/ui/newsCreation.ts) 的 `creationSkillId(format)`：按已明确的 poster/article 使用 [PC-08](PC-08-oil-pig-poster.md)/[PC-09](PC-09-oil-pig-article.md)，无有效格式时拒绝而不猜测。保留原始草稿、已受理旧命令、冻结资源和历史 `content-production`，不在恢复时改写旧请求签名；代码完成与运行验收分开报告。

**源码入口：** [toolbox_server.py](../../../easel_workbench/runtime/toolbox_server.py)、[production.tsx](../../../web/frontend/src/workbench/ui/production.tsx)、[index.tsx](../../../web/frontend/src/workbench/ui/index.tsx)、[DraftOperations.tsx](../../../web/frontend/src/workbench/ui/DraftOperations.tsx)、[article_drafts.py](../../../easel_workbench/runtime/article_drafts.py)、[content_studio.py](../../../easel_workbench/runtime/content_studio.py)、[easel_frontend.py](../../../easel_workbench/runtime/easel_frontend.py)。

**状态／存储归属：** 沿用原服务器作品、草稿、任务、准确回执及对应兼容服务的表/文件；本卡不创建新 registry、运行开关或主库。

**验证入口：** [test_workbench_private_architecture.py](../../../tests/test_workbench_private_architecture.py)、[test_workbench_skill_retirement.py](../../../tests/test_workbench_skill_retirement.py)、[test_workbench_oil_pig_skills.py](../../../tests/test_workbench_oil_pig_skills.py)、[test_workbench_version_view.py](../../../tests/test_workbench_version_view.py)。HTTP 鉴权、每类真实写动作、重试与新旧草稿选择应分别验证，不能由静态登记替代。

**依据与维护：** [私有架构 Spec](../../../specs/private-workbench-architecture/spec.md)、[技能原生化](../NATIVE-SKILLS-20261103.md)、[油猪流程拆分](../../../specs/news-creation-20261103/spec.md)。变更时同步对应 PC/C 卡、入口和测试；没有新的用户需求不得扩张存量接口或创建旧页面。

**核对记录：** 2026-11-05 从首版大项细分到具名接口；本次文档不触发制作、文件归档、模型调用或平台发布，不将源码可达报告成已经发生的操作。
