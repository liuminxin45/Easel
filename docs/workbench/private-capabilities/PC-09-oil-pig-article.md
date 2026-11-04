# PC-09 油猪·做文章

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

- **状态：** 已确认保留；类型：业务 SKILL。
- **需求依据：** 用户要求恢复独立文章流程、内化 neo-content 原内容，与官方公众号技能区分。 依据见下方原始规则/Spec；本卡不额外授予执行、采纳或发布权限。
- **能力范围：** 选题/提纲/完整文章或局部修改、按需配图与 HTML 等指定交付；以本技能正文和本轮要求为准。
- **官方复用与必要差异：** 原技能浏览和执行，不复制官方公众号文章页面，不把贴图组合技能作为文章必经流程。
- **不可破坏的合同：** 不套用贴图组图或配文字数规则；不推断用户已授权配图/发布；文章和修改另存准确版本，保留原话与事实边界。

**接口与状态归属：** 技能接口沿原技能服务；方法与资源以 oil-pig-article/SKILL.md 为源，无独立 HTTP 或技能数据库；文章版本和交付状态归会话/作品台账。

**私有入口／资源：** [skills/builtin/oil-pig-article/SKILL.md](../../../skills/builtin/oil-pig-article/SKILL.md)、[skills/shared/workbench](../../../skills/shared/workbench)、[easel_workbench/features/creation_skills.py](../../../easel_workbench/features/creation_skills.py)

**官方复用／共通接缝：** [easel/web_services/skills.py](../../../easel/web_services/skills.py)、[web/frontend/src/components/SkillDrawer.tsx](../../../web/frontend/src/components/SkillDrawer.tsx)

**验证入口：** [tests/workbench_news_creation_browser.py](../../../tests/workbench_news_creation_browser.py)、[tests/test_workbench_news_native_context.py](../../../tests/test_workbench_news_native_context.py)

**需求与设计记录：** [docs/workbench/NEWS-NATIVE-CHAT-20261104.md](../../../docs/workbench/NEWS-NATIVE-CHAT-20261104.md)、[docs/workbench/NATIVE-SKILLS-20261103.md](../../../docs/workbench/NATIVE-SKILLS-20261103.md)

**后续维护：** 变更时先核对上述调用链与当前官方实现；优先共用、缩小上游补丁。同步维护本卡的范围、入口、共通差异及验证依据；被上游吸收时移除对应适配并更新登记状态。原方法、历史输入和交付证据不在本卡复制或改写。

**登记记录：** 2026-11-05 按业务源码 `1901f83` 建立首版；本次只读盘点及文档登记，未新增启用能力，未逐项重新执行产品验收。
