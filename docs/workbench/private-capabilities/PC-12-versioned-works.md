# PC-12 准确作品版本、修改、采纳与反馈

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

**本版修改入口：** [VersionOperations.tsx](../../../web/frontend/src/workbench/ui/VersionOperations.tsx) 读取准确版本与作品格式；文章选择油猪·做文章，贴图选择油猪·做贴图，格式未知时不猜测、不启动会话。修改仍保留原件，选择技能不等于发送请求。

**贴图配文复制：** 用户要求在原文件预览中分别复制标题与正文。[nativePages.tsx](../../../web/frontend/src/workbench/ui/nativePages.tsx) 注入 [PosterCopyActions.tsx](../../../web/frontend/src/workbench/ui/PosterCopyActions.tsx)，仅处理已登记 `标题与配文.txt`，复用加载结果；不改写文件。共通 OutputsPage 只提供可选文本预览动作接缝，默认保持官方行为，异常格式不推测。

**对话采纳：** 两个油猪制作技能冻结本轮专属目录、画像和身份；成品登记后使用原生会话文本询问。明确回复“采纳这版”“只采纳图片/配文/正文”“不采纳这版（可附原因）”保存准确决定，并在产物目录原子更新 `【采纳状态】.md`：未处理／已采纳／未采纳，局部采纳注明范围。按用户最新要求，不创建完成、项目归档、清理或 Git 提交同步任务；私有内容库入口执行同一策略。模糊表态先确认，不猜测来源或旧版。

**标记适配：** [review_marker.py](../../../easel_workbench/features/works/review_marker.py) 将既有决定记录投影为醒目的目录标记，受版本路径校验和串行原子写入保护；[toolbox_store.py](../../../easel_workbench/runtime/toolbox_store.py) 识别已登记原生版本，复用原决定校验但绕过旧完成/队列。私有 [WorkCompletion.tsx](../../../web/frontend/src/workbench/ui/WorkCompletion.tsx) 简化对应版本确认，仍复用 Easel Drawer 和控件；没有官方源码改动。

**私有桥接：** [native_review.py](../../../easel_workbench/features/works/native_review.py) 经 [chat.py](../../../easel_workbench/application/chat.py) 复用 capture_artifacts 和 production_outcome 登记准确文件，冻结父版与画像；修改另存子版。受理沿 [chat_admission.py](../../../easel_workbench/application/chat_admission.py)，本地决定沿 [service.py](../../../easel_workbench/features/conversations/service.py) 的原回合与事件仓库；不调用模型。复用 [local_operations.py](../../../easel_workbench/runtime/local_operations.py)，本入口不采纳保留原文件。验证见 [登记测试](../../../tests/test_workbench_native_review.py)、[贴图/文章闭环与重启恢复](../../../tests/test_workbench_native_review_flow.py)、[浏览器验收](../../../tests/workbench_native_review_browser.py)。旧对话缺可信版本关联时不推测历史归属；代码完成、检查与正式发布分别核验。

**实际公共文件差异：** 见 [共通源码逐文件台账](../SHARED-SOURCE-CHANGES.md)，按 `PC-12` 查询实际关联路径、修改理由与同步核对点；纯复用或开发维护项不据此新增官方改动。

- **状态：** 已确认保留；类型：私有业务。
- **需求依据：** 用户要求制作→修改→采纳/不采纳形成闭环，保留准确版本、父版、原始意见和授权。 依据见下方原始规则/Spec；本卡不额外授予执行、采纳或发布权限。
- **能力范围：** 成品接收、文件登记、版本/父版、独立检查、采纳/不采纳、仅记录本版反馈和准确继续制作链接。
- **官方复用与必要差异：** 原 OutputsPage、ChatPage、Drawer/DownloadLink；私有操作放原详情扩展区，不替代内容库。
- **不可破坏的合同：** 只接收本回合准确产物，修改另存父版；反馈不自动制作，采纳不等于发布；制作状态与交付事实分开。采纳完成的三种mode、质量确认及准确版本只读历史已在 [U-01](U-01-completion-options-review.md) 按实际用途核对，不将字段名带learning误认作整理经验。

**接口与状态归属：** 接口沿 chat_business、WorkVersions 与现有作品/反馈操作；WorkVersions 使用调用方的 store、work_store 及事务保存准确版本关联，不复制作品主库。

**私有入口／资源：** [easel_workbench/chat_business.py](../../../easel_workbench/chat_business.py)、[easel_workbench/features/works/products.py](../../../easel_workbench/features/works/products.py)、[easel_workbench/features/works/versions.py](../../../easel_workbench/features/works/versions.py)、[web/frontend/src/workbench/ui/VersionOperations.tsx](../../../web/frontend/src/workbench/ui/VersionOperations.tsx)

**官方复用／共通接缝：** [web/frontend/src/components/OutputsPage.tsx](../../../web/frontend/src/components/OutputsPage.tsx)、[web/frontend/src/components/ChatPage.tsx](../../../web/frontend/src/components/ChatPage.tsx)、[web/frontend/src/components/Drawer.tsx](../../../web/frontend/src/components/Drawer.tsx)

**验证入口：** [tests/test_workbench_chat_business.py](../../../tests/test_workbench_chat_business.py)、[tests/test_workbench_version_view.py](../../../tests/test_workbench_version_view.py)、[tests/test_workbench_chat_products.py](../../../tests/test_workbench_chat_products.py)

**需求与设计记录：** [specs/native-product-experience/spec.md](../../../specs/native-product-experience/spec.md)、[docs/workbench/NATIVE-PRODUCT-EXPERIENCE-20261102.md](../../../docs/workbench/NATIVE-PRODUCT-EXPERIENCE-20261102.md)

**后续维护：** 变更时先核对上述调用链与当前官方实现；优先共用、缩小上游补丁。同步维护本卡的范围、入口、共通差异及验证依据；被上游吸收时移除对应适配并更新登记状态。原方法、历史输入和交付证据不在本卡复制或改写。

**首版登记记录：** 2026-11-05 按业务源码 `1901f83` 建立首版；首版为只读盘点及文档登记，未新增启用能力，未逐项重新执行产品验收。本轮补充项按当前源码及各自验证记录另行核对，不将首版记录冒称本轮业务验收。

**更新记录：** 2026-11-06 完整原生交付事务内追加 PC-31 复盘队列；准确版本、采纳标记、原始反馈继续由原作品流程维护。内容详情仅增加进入原Drawer的制作复盘入口，不增加会话工具条。

**更新记录：** 2026-11-06 用户要求会话内标题/正文直接点按复制。[chatTextCopy.ts](../../../web/frontend/src/workbench/ui/lib/chatTextCopy.ts) 在原[ChatSessionView](../../../web/frontend/src/workbench/ui/ChatSessionView.tsx)外集中适配，复用原Markdown/消息布局及浏览器剪贴板，不改官方组件；只识别非流式助手消息的明确字段，避免滚动/长按/选区误触。反馈样式限定[chat-text-copy.css](../../../web/frontend/src/workbench/ui/chat-text-copy.css)，由私有[host.css](../../../web/frontend/src/workbench/host.css)载入。用例：[前端](../../../tests/frontend/chatTextCopy.test.mjs)、[浏览器](../../../tests/workbench_chat_text_copy_browser.py)，[Spec](../../../specs/chat-tap-copy-20261106/spec.md)。
