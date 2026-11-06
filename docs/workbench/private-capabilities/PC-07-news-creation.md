# PC-07 私有新闻原文页与讨论/创作衔接

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

**实际公共文件差异：** 见 [共通源码逐文件台账](../SHARED-SOURCE-CHANGES.md)，按 `PC-07` 查询实际关联路径、修改理由与同步核对点；纯复用或开发维护项不据此新增官方改动。

- **状态：** 已确认保留；类型：私有业务。
- **需求依据：** 用户明确保留私有新闻页，用于讨论怎么写或附加贴图/文章技能；首页与雷达统一进入原文。 依据见下方原始规则/Spec；本卡不额外授予执行、采纳或发布权限。
- **能力范围：** 来源阅读、讨论与制作的显式选择、风格及角色素材、准确新闻关联、完整冻结输入和消息内新闻链接。
- **官方复用与必要差异：** 复用原 Drawer、ChatPage、技能选择和原生引擎；私有内容仅在新闻页和必要业务扩展区提供。
- **不可破坏的合同：** 点击新闻不自动发送；选技能不自动执行；不加聊天底部新闻/制作专用按钮，不恢复已删除的本轮创作设置页；素材/风格按本轮冻结，不回填当前默认。

**接口与状态归属：** NewsCreation 与 news_links 通过现有新闻/会话接口传递来源及创作上下文；冻结输入与准确新闻关联归服务器会话/任务，临时选项不构成发布授权。

**格式选择唯一入口：** [ui/newsCreation.ts](../../../web/frontend/src/workbench/ui/newsCreation.ts) 的 `creationSkillId(format)` 将已明确的 poster/article 映射到两个独立油猪技能；兼容新建页与普通历史草稿共用此映射，不回落新执行的 content-production。旧已受理命令/冻结材料/回执身份不在升级或重试时重写。

**私有入口／资源：** [web/frontend/src/workbench/ui/NativeNews.tsx](../../../web/frontend/src/workbench/ui/NativeNews.tsx)、[web/frontend/src/workbench/ui/NewsCreationDrawer.tsx](../../../web/frontend/src/workbench/ui/NewsCreationDrawer.tsx)、[easel_workbench/features/news_creation.py](../../../easel_workbench/features/news_creation.py)、[easel_workbench/features/conversations/news_links.py](../../../easel_workbench/features/conversations/news_links.py)

**官方复用／共通接缝：** [web/frontend/src/components/Drawer.tsx](../../../web/frontend/src/components/Drawer.tsx)、[web/frontend/src/components/ChatPage.tsx](../../../web/frontend/src/components/ChatPage.tsx)、[easel/web_services/skills.py](../../../easel/web_services/skills.py)

**验证入口：** [tests/test_workbench_news_creation.py](../../../tests/test_workbench_news_creation.py)、[tests/workbench_news_creation_browser.py](../../../tests/workbench_news_creation_browser.py)

**需求与设计记录：** [docs/workbench/NEWS-NATIVE-CHAT-20261104.md](../../../docs/workbench/NEWS-NATIVE-CHAT-20261104.md)、[specs/news-creation-20261103/spec.md](../../../specs/news-creation-20261103/spec.md)

**后续维护：** 变更时先核对上述调用链与当前官方实现；优先共用、缩小上游补丁。同步维护本卡的范围、入口、共通差异及验证依据；被上游吸收时移除对应适配并更新登记状态。原方法、历史输入和交付证据不在本卡复制或改写。

**旧草稿新调用验证：** [privateDraftCreation.test.mjs](../../../tests/frontend/privateDraftCreation.test.mjs)、[nativeSkillDrafts.test.mjs](../../../tests/frontend/nativeSkillDrafts.test.mjs) 和 [workbenchNativeChat.test.mjs](../../../tests/frontend/workbenchNativeChat.test.mjs) 核对明确格式→对应油猪技能、原字与附件不改写、只预填普通会话且不自动发送；未知格式拒绝猜测，原pending身份仍阻止新增转发。

**首版登记记录：** 2026-11-05 按业务源码 `1901f83` 建立首版；首版为只读盘点及文档登记，未新增启用能力，未逐项重新执行产品验收。本轮补充项按当前源码及各自验证记录另行核对，不将首版记录冒称本轮业务验收。

**贴图风格便捷预设（2026-11-06）：** [Spec](../../../specs/poster-style-presets-20261106/spec.md)。原私有制作抽屉优先画像默认、否则采用已有editorial-poster组合；允许恢复默认及服务器最近completed贴图的四项风格，只填选项、保留本条补充，不自动发送/改默认。最近记录通过原NewsCreation.context只读投影，无新表、无浏览器业务历史。前端唯一选择逻辑见 [newsCreation.ts](../../../web/frontend/src/workbench/ui/newsCreation.ts)，样式仅限 [news-creation.css](../../../web/frontend/src/workbench/ui/news-creation.css)。

**预设交互验收：** [workbench_poster_presets_browser.py](../../../tests/workbench_poster_presets_browser.py) 覆盖原新闻抽屉的桌面/320px/390px明暗主题、默认选项、打开后新增服务器记录再恢复、补充原字、无自动执行/画像写入及文章隔离。

**更新记录：** 2026-11-06 优秀模板通过 PC-32 私有服务附加到既有制作请求，原 SettingsSelect/Drawer 与默认及恢复上次风格保留；仅显式选择后冻结模板修订、方法及参考，不自动选择或自动制作。
