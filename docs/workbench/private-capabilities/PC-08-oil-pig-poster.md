# PC-08 油猪·做贴图

2026-11-06：技能已补充交付后对话询问及禁止虚报决定回执的要求；对话到准确版本的采纳链路仍在整改，见 [PC-12](PC-12-versioned-works.md)。

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

**实际公共文件差异：** 见 [共通源码逐文件台账](../SHARED-SOURCE-CHANGES.md)，按 `PC-08` 查询实际关联路径、修改理由与同步核对点；纯复用或开发维护项不据此新增官方改动。

- **状态：** 已确认保留；类型：业务 SKILL。
- **需求依据：** 用户要求恢复 neo-content 的原贴图流程，与文章流程分离，名称加油猪前缀，保留小猪身份和独立规范。 依据见下方原始规则/Spec；本卡不额外授予执行、采纳或发布权限。
- **能力范围：** 微信公众号贴图制作、贴图修改、准确角色/画面风格、参考资源及成品文件；方法正文只在本技能维护。
- **官方复用与必要差异：** 原 SkillPage/SkillDrawer 与原生执行，资源内化到本项目；不另建贴图执行器供新技能调用。
- **不可破坏的合同：** 与油猪文章技能互不串流程；不带 V1/V2 展示版本号；旧版本只归档/历史读取；保留规范和原件，制作不等于采纳或发布。

**技能收敛进行中：** 基础规范、创作检查工具和辅助技能方法已纳入本技能目录；共享原件继续保留给历史流程。目录内脚本和资源清单已做隔离检查，六个旧技能源文件及旧组合源文件已归档；仍须完成全链路测试、独立中控与部署验收。

**包内维护范围：** [参考及素材](../../../skills/builtin/oil-pig-poster/references/)、[技能专用脚本](../../../skills/builtin/oil-pig-poster/scripts/)。

**新任务选择边界：** [技能任务规则](../../../easel_workbench/skills.py) 和 [技能快照](../../../easel_workbench/features/skills/snapshots.py) 不再组合退役技能；不修改既有用户数据。

辅助方法中的共享资料链接按该方法文档所在目录解析；链接回归与旧来源的历史追溯链接分开检查。

**接口与状态归属：** 技能接口沿原技能服务；方法与资源以 oil-pig-poster/SKILL.md 为源，无独立 HTTP 或技能数据库；本轮快照、产物和采纳分别归会话/作品台账。

**本项目工具与依赖：** [neo-tools/贴图生产/cli.mjs](../../../skills/builtin/oil-pig-poster/scripts/贴图生产/cli.mjs) 及 [lib.mjs](../../../skills/builtin/oil-pig-poster/scripts/贴图生产/lib.mjs) 负责贴图草稿包 check/render；[creative_review.py](../../../skills/builtin/oil-pig-poster/scripts/内容工作流/creative_review.py) 负责准确版本的创作检查/绑定/反馈，显式指定 `--root <项目根>`。这些是当前技能按需调用的本项目工具，不是独立工作台执行器。原来源与字节以 [source-manifest.json](../../../skills/shared/workbench/neo-source/source-manifest.json) 维护，旧项目API/自动同步命令不能直接执行。

**安装与实际交付边界：** [install_oil_pig_tools.py](../../../skills/builtin/oil-pig-poster/scripts/install_oil_pig_tools.py) 从已内化锁文件安装项目 `.runtime/neo-poster-tools` 的 Playwright 依赖，要求既有 Node 24.19.0，不安装全局包。安装器只核对浏览器是否已有，并非保证已安装浏览器或完成真实渲染。工具退出、程序检查、实际图片查看、用户采纳和外部 Git/平台发布是不同证据；手机能看工作台不等于实体设备已保存文件。

**私有入口／资源：** [skills/builtin/oil-pig-poster/SKILL.md](../../../skills/builtin/oil-pig-poster/SKILL.md)、[skills/shared/workbench](../../../skills/shared/workbench)、[easel_workbench/features/creation_skills.py](../../../easel_workbench/features/creation_skills.py)、[web/frontend/src/workbench/ui/skillIcons.tsx](../../../web/frontend/src/workbench/ui/skillIcons.tsx)

**官方复用／共通接缝：** [easel/web_services/skills.py](../../../easel/web_services/skills.py)、[web/frontend/src/components/SkillPage.tsx](../../../web/frontend/src/components/SkillPage.tsx)

**验证入口：** [tests/test_workbench_oil_pig_skills.py](../../../tests/test_workbench_oil_pig_skills.py) 核对内化原文字节、两个独立技能与工具隔离输入；[tests/test_workbench_news_creation.py](../../../tests/test_workbench_news_creation.py) 核对明确格式/材料；[tests/frontend/workbenchSkillIcons.test.mjs](../../../tests/frontend/workbenchSkillIcons.test.mjs) 核对中文技能图标。TEMP测试不冒称实际生图质量或实体手机验收。

**需求与设计记录：** [油猪两个流程拆分与内化](../../../specs/news-creation-20261103/spec.md)、[docs/workbench/NEWS-NATIVE-CHAT-20261104.md](../../../docs/workbench/NEWS-NATIVE-CHAT-20261104.md)、[docs/workbench/SKILL-CHINESE-20261104.md](../../../docs/workbench/SKILL-CHINESE-20261104.md)。拆分记录优先于早期“制作贴图 / 文章”合并名称描述。

**后续维护：** 变更时先核对上述调用链与当前官方实现；优先共用、缩小上游补丁。同步维护本卡的范围、入口、共通差异及验证依据；被上游吸收时移除对应适配并更新登记状态。原方法、历史输入和交付证据不在本卡复制或改写。

**首版登记记录：** 2026-11-05 按业务源码 `1901f83` 建立首版；首版为只读盘点及文档登记，未新增启用能力，未逐项重新执行产品验收。本轮补充项按当前源码及各自验证记录另行核对，不将首版记录冒称本轮业务验收。

**2026-11-05 规范整理：** SKILL 增加适用场景、当前画像、输入、执行流程和输出核验，方法正文和资源仍以原 SKILL 与引用原件为准；不新增发布或采纳授权。验证见本轮技能规范 Spec。
