# PC-08 油猪·做贴图

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

- **状态：** 已确认保留；类型：业务 SKILL。
- **需求依据：** 用户要求恢复 neo-content 的原贴图流程，与文章流程分离，名称加油猪前缀，保留小猪身份和独立规范。 依据见下方原始规则/Spec；本卡不额外授予执行、采纳或发布权限。
- **能力范围：** 微信公众号贴图制作、贴图修改、准确角色/画面风格、参考资源及成品文件；方法正文只在本技能维护。
- **官方复用与必要差异：** 原 SkillPage/SkillDrawer 与原生执行，资源内化到本项目；不另建贴图执行器供新技能调用。
- **不可破坏的合同：** 与油猪文章技能互不串流程；不带 V1/V2 展示版本号；旧版本只归档/历史读取；保留规范和原件，制作不等于采纳或发布。

**接口与状态归属：** 技能接口沿原技能服务；方法与资源以 oil-pig-poster/SKILL.md 为源，无独立 HTTP 或技能数据库；本轮快照、产物和采纳分别归会话/作品台账。

**私有入口／资源：** [skills/builtin/oil-pig-poster/SKILL.md](../../../skills/builtin/oil-pig-poster/SKILL.md)、[skills/shared/workbench](../../../skills/shared/workbench)、[easel_workbench/features/creation_skills.py](../../../easel_workbench/features/creation_skills.py)、[web/frontend/src/workbench/ui/skillIcons.tsx](../../../web/frontend/src/workbench/ui/skillIcons.tsx)

**官方复用／共通接缝：** [easel/web_services/skills.py](../../../easel/web_services/skills.py)、[web/frontend/src/components/SkillPage.tsx](../../../web/frontend/src/components/SkillPage.tsx)

**验证入口：** [tests/test_workbench_news_creation.py](../../../tests/test_workbench_news_creation.py)、[tests/frontend/workbenchSkillIcons.test.mjs](../../../tests/frontend/workbenchSkillIcons.test.mjs)

**需求与设计记录：** [docs/workbench/NEWS-NATIVE-CHAT-20261104.md](../../../docs/workbench/NEWS-NATIVE-CHAT-20261104.md)、[docs/workbench/SKILL-CHINESE-20261104.md](../../../docs/workbench/SKILL-CHINESE-20261104.md)

**后续维护：** 变更时先核对上述调用链与当前官方实现；优先共用、缩小上游补丁。同步维护本卡的范围、入口、共通差异及验证依据；被上游吸收时移除对应适配并更新登记状态。原方法、历史输入和交付证据不在本卡复制或改写。

**登记记录：** 2026-11-05 按业务源码 `1901f83` 建立首版；本次只读盘点及文档登记，未新增启用能力，未逐项重新执行产品验收。
