# P2：会话与作品闭环拆分

Spec：`private-workbench-architecture`。用户本轮明确要求实施 P2；P3–P6 不在本批范围。
基线：`3246babaaf1ecd22ecdd88217d6e33a3c974d067`。
主目录正进行另一批官方同步，本批在 `D:/Projects/Easel-p2` 的既有
`codex/easel-base-alignment` 工作树实施，不混入同步改动，不切换其分支或生产指针。

## 唯一实现与状态归属

| 实现 | 职责与保留合同 |
|---|---|
| `http/chat.py` | 原认证宿主后的 HTTP/SSE 转发，端点、错误形状及续订保持 |
| `features/conversations/service.py` | 会话、回合、事件、问题、停止及 unknown；继续调用原 Easel adapter/RPC 池 |
| `features/conversations/receipts.py` | 原聊天标识、序列化、摘要和状态，不与同名历史工具函数自动合并 |
| `application/chat.py` | 冻结方案、准确输入校验、跨域受理及调用台账；技能、画像和资源解析留给 P3 单独整理 |
| `features/works/versions.py` | 准确父版、原始反馈、版本登记、制作开始及交付接收，沿用既有 work store 和核验程序 |
| `features/works/products.py` | 准确回合产物、未完成文件与字节查询，使用明确的会话和作品只读依赖 |
| `contracts/production.py` | 各层共享的原 PlanConflict 类型，HTTP 和作品无需反向导入协调器 |

原 `chat.py`、`chat_business.py`、`chat_api.py`、`chat_products.py` 仅导出同一对象。
原 `application.py` 显式转换为 `application/__init__.py`，保持
`easel_workbench.application.create_app`，源码根定位同步调整，不并存同名文件和包。
宿主直接装配新入口，明确传入 store、settings、creator；旧构造参数仍可用。

`submit` 的事务语句未改：BEGIN IMMEDIATE → 同步 on_accept(c,turn)
→ 回合及 pending 会话 → 提交 → 启动原生异步任务。
作品 accept(c,plan) 和 started(c,...) 不新建连接或提交事务。
parent 只读核对会话关联，作品层不写会话状态；调用台账由跨域协调器维护。
成品继续通过原 record_delivery 接收，不混淆模型完成、成品登记与用户采纳。
旧表、ID、JSON、哈希、冻结输入、旧角色、技能正文和历史资产不变。

## 验证与证据

证据目录：`.local/workbench-validation/private-architecture-p2-20261102/`。

- 固定旧提交独立工作树与新实现运行同一组 77 项会话、作品、响应性、超时、中断、核对及独立检查回归，均通过：`baseline-clean.xml`、`after.xml`。
- 架构、私有边界、技能策略/命令及 P2 故障回滚 130 项通过：`architecture.xml`。
- 设置、原生核对/归属/API/响应性、媒体、下载、外部 CLI、合同及冻结源码兼容检查 174 项通过：`compatibility.xml`。
- 57 处迁移 AST 语句对照一致，包含完整 submit/_run、父版/登记、开始/完成及产物查询；只归一化导入、准确重命名和显式读取依赖：`statement-parity.json`。
- 155 个私有 Python 模块的迁移边界违规、职责审查错误均为零：`inventory.json`。19 个历史审查 SHA 仍提示变化，经逐字节核对均与固定旧提交的独立检出一致，本批未改这些源码；保留提示而不重写原 P0 记录，见 `historical-review-source-drift.json`。新增 feature 边界有局部/动态导入反例，不放宽上游边界。
- 真实 TEMP HTTP 中，在作品、版本和 workflow 写入后，通过 SQLite trigger 使调用登记失败：原宿主返回既有 503，业务写入一起回滚，pending/执行所有权清空，模型调用为零。
- Windows Edge 桌面及 390px 模拟手机：自动 RSS→选题→讨论→V1→不采纳→准确父版 V2→独立核验→下载→采纳→TEMP 归档→刷新，34 项通过：`closedloop-r2/content-closedloop-browser.json`。
- Node 24.19.0 的 check:workbench、build:workbench 通过；前端产品源码未改。复用现有锁定依赖目录，不冒称独立重装。浏览器验证使用原 R6 不可变前端，新构建未上线。

首次浏览器失败保留在 `closedloop/`。原 SyntheticAdapter 缺少 descriptor，
harnesses.describe 抛 AttributeError，运行环境检测失败且菜单不可用。
直接复现后补齐假执行器的原生 descriptor；实际安装检测和产品逻辑未被替换。
恢复故障注入改为包装宿主真实使用的 http.chat.stream，而非兼容模块导出别名。
最初同目录基线运行期间发生源码提取，不用该报告证明纯旧版本；
固定提交独立运行的 baseline-clean.xml 才是基线。

## 发布边界

源码验证、冻结包验证、正式生产升级分别记录。本批没有切生产指针，
没有迁入技能或复制/恢复生产库；统一部署需与官方同步确定最终组合后按既有准入执行。
推理和独立检查为 TEMP 合成执行，真实 AI、真实平台发布为零。
实体 vivo/WebToApp 保存及实际用户体验反馈仍待验，不以模拟手机代填。

## 冻结候选验证与交付

功能提交：`6bbb1f0eb7429d6c9b877986cc2dd79d108033d1`。
独立候选 `workbench-20261102-004153`，manifest SHA256
`e745d5bf19047fa25d45354222b1a93134e4d7afa551ad9d30d030688ee9a64b`。
绑定原 R6 前端 `native-mobile-unified-r6-20261102001420`，manifest SHA256
`8ba00a9eb9f8285a0058fe1c12d5872bb3d6720aabf62f4e045a240713654ed5`。

候选位于本批隔离工作树，未写主工程共享 candidate 或活动指针。
1126 包成员、391 个 Python 文件编译、capabilities/workspace 原字节绑定通过；
新包入口齐全，无旧 application.py 与新包冲突，见 `frozen-package.json`。
准确冻结包另跑 Edge 桌面/模拟手机内容闭环 34 项及移动断线/停止/unknown 9 项，均通过。
实际加载模块均来自该冻结包、所有 manifest 原成员字节保持；
见 `frozen-closedloop/content-closedloop-browser.json`、`frozen-recovery/chat-recovery-browser.json`。
已实际查看移动 V1 成品和 unknown 截图，不用截图证明事务或模型质量。

本批代码与文档提交至自有 origin 的 `codex/easel-base-alignment`，最终推送以 Git 远端 SHA 核对。
P2 实现与隔离运行验证完成；正式生产升级仍交统一准入与上游同步最终组合处理。
