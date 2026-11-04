# PC-07 私有新闻原文页与讨论/创作衔接

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

- **状态：** 已确认保留；类型：私有业务。
- **需求依据：** 用户明确保留私有新闻页，用于讨论怎么写或附加贴图/文章技能；首页与雷达统一进入原文。 依据见下方原始规则/Spec；本卡不额外授予执行、采纳或发布权限。
- **能力范围：** 来源阅读、讨论与制作的显式选择、风格及角色素材、准确新闻关联、完整冻结输入和消息内新闻链接。
- **官方复用与必要差异：** 复用原 Drawer、ChatPage、技能选择和原生引擎；私有内容仅在新闻页和必要业务扩展区提供。
- **不可破坏的合同：** 点击新闻不自动发送；选技能不自动执行；不加聊天底部新闻/制作专用按钮，不恢复已删除的本轮创作设置页；素材/风格按本轮冻结，不回填当前默认。

**接口与状态归属：** NewsCreation 与 news_links 通过现有新闻/会话接口传递来源及创作上下文；冻结输入与准确新闻关联归服务器会话/任务，临时选项不构成发布授权。

**私有入口／资源：** [web/frontend/src/workbench/ui/NativeNews.tsx](../../../web/frontend/src/workbench/ui/NativeNews.tsx)、[web/frontend/src/workbench/ui/NewsCreationDrawer.tsx](../../../web/frontend/src/workbench/ui/NewsCreationDrawer.tsx)、[easel_workbench/features/news_creation.py](../../../easel_workbench/features/news_creation.py)、[easel_workbench/features/conversations/news_links.py](../../../easel_workbench/features/conversations/news_links.py)

**官方复用／共通接缝：** [web/frontend/src/components/Drawer.tsx](../../../web/frontend/src/components/Drawer.tsx)、[web/frontend/src/components/ChatPage.tsx](../../../web/frontend/src/components/ChatPage.tsx)、[easel/web_services/skills.py](../../../easel/web_services/skills.py)

**验证入口：** [tests/test_workbench_news_creation.py](../../../tests/test_workbench_news_creation.py)、[tests/workbench_news_creation_browser.py](../../../tests/workbench_news_creation_browser.py)

**需求与设计记录：** [docs/workbench/NEWS-NATIVE-CHAT-20261104.md](../../../docs/workbench/NEWS-NATIVE-CHAT-20261104.md)、[specs/news-creation-20261103/spec.md](../../../specs/news-creation-20261103/spec.md)

**后续维护：** 变更时先核对上述调用链与当前官方实现；优先共用、缩小上游补丁。同步维护本卡的范围、入口、共通差异及验证依据；被上游吸收时移除对应适配并更新登记状态。原方法、历史输入和交付证据不在本卡复制或改写。

**登记记录：** 2026-11-05 按业务源码 `1901f83` 建立首版；本次只读盘点及文档登记，未新增启用能力，未逐项重新执行产品验收。
