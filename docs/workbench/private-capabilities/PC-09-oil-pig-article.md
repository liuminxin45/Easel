# PC-09 油猪·做文章

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

**技能收敛进行中：** 基础规范、创作检查与批注工具和辅助技能方法已纳入本技能目录；共享原件继续保留给历史流程。目录内脚本和资源清单已做隔离检查，六个旧技能源文件及旧组合源文件已归档；仍须完成全链路测试、独立中控与部署验收。

**包内维护范围：** [参考及素材](../../../skills/builtin/oil-pig-article/references/)、[技能专用脚本](../../../skills/builtin/oil-pig-article/scripts/)。

**新任务选择边界：** [技能任务规则](../../../easel_workbench/skills.py) 和 [技能快照](../../../easel_workbench/features/skills/snapshots.py) 不再组合退役技能；不修改既有用户数据。

辅助方法中的共享资料链接按该方法文档所在目录解析；链接回归与旧来源的历史追溯链接分开检查。

**实际公共文件差异：** 见 [共通源码逐文件台账](../SHARED-SOURCE-CHANGES.md)，按 `PC-09` 查询实际关联路径、修改理由与同步核对点；纯复用或开发维护项不据此新增官方改动。

- **状态：** 已确认保留；类型：业务 SKILL。
- **需求依据：** 用户要求恢复独立文章流程、内化 neo-content 原内容，与官方公众号技能区分。 依据见下方原始规则/Spec；本卡不额外授予执行、采纳或发布权限。
- **能力范围：** 选题/提纲/完整文章或局部修改、按需配图与 HTML 等指定交付；以本技能正文和本轮要求为准。
- **官方复用与必要差异：** 原技能浏览和执行，不复制官方公众号文章页面，不把贴图组合技能作为文章必经流程。
- **不可破坏的合同：** 不套用贴图组图或配文字数规则；不推断用户已授权配图/发布；文章和修改另存准确版本，保留原话与事实边界。

**接口与状态归属：** 技能调用沿原技能服务，方法与资源以 oil-pig-article/SKILL.md 为源，不另建技能数据库；文章版本和交付状态归会话/作品台账。可选批注工具有独立本机 HTTP 服务，不能将“技能调用复用官方 API”误写成所有工具均无HTTP。

**本项目工具与文件：** [creative_review.py](../../../skills/builtin/oil-pig-article/scripts/内容工作流/creative_review.py) 核对准确版创作检查；[article-check.mjs](../../../skills/builtin/oil-pig-article/scripts/内容工作流/article-check.mjs) 检查真实 HTML/图片；[文章批注 review.py](../../../skills/builtin/oil-pig-article/scripts/文章批注/review.py) 及其 [review.js](../../../skills/builtin/oil-pig-article/scripts/文章批注/review.js)、[review.css](../../../skills/builtin/oil-pig-article/scripts/文章批注/review.css) 读写对应文章目录的批注及修订。原始方法和来源SHA见 [source-manifest.json](../../../skills/shared/workbench/neo-source/source-manifest.json)，本卡不复制正文。

**HTTP与移动端边界：** review.py 的 GET/PUT 服务仅绑定服务器 `127.0.0.1`，校验Host及写请求Origin，保存批注时核对generation/version/content_hash/edit_seq。手机的 `127.0.0.1` 指向手机本身，工作台经Tailscale可达不代表此本机服务可远程打开；不得随意改成公网监听或将其冒称已接入工作台。远程批注需单独需求、鉴权适配和验证。

**依赖与验证边界：** [install_oil_pig_tools.py](../../../skills/builtin/oil-pig-article/scripts/install_oil_pig_tools.py) 将锁定Node依赖装入 `.runtime/neo-poster-tools`；固定Node24.19.0不变，安装器核对浏览器存在但不保证实际HTML已渲染。程序检查、独立目视审阅、公众号后台粘贴、用户采纳及发布分别报告，未执行不能写完成。

**私有入口／资源：** [skills/builtin/oil-pig-article/SKILL.md](../../../skills/builtin/oil-pig-article/SKILL.md)、[skills/shared/workbench](../../../skills/shared/workbench)、[easel_workbench/features/creation_skills.py](../../../easel_workbench/features/creation_skills.py)

**官方复用／共通接缝：** [easel/web_services/skills.py](../../../easel/web_services/skills.py)、[web/frontend/src/components/SkillDrawer.tsx](../../../web/frontend/src/components/SkillDrawer.tsx)

**验证入口：** [tests/test_workbench_oil_pig_skills.py](../../../tests/test_workbench_oil_pig_skills.py) 核对两个技能隔离、原文哈希、创作检查和批注修订冲突；[tests/workbench_news_creation_browser.py](../../../tests/workbench_news_creation_browser.py)、[tests/test_workbench_news_native_context.py](../../../tests/test_workbench_news_native_context.py) 核对原生会话材料。上述入口不证明手机可直接访问本机批注HTTP或真实模型质量。

**需求与设计记录：** [油猪两个流程拆分与内化](../../../specs/news-creation-20261103/spec.md)、[docs/workbench/NEWS-NATIVE-CHAT-20261104.md](../../../docs/workbench/NEWS-NATIVE-CHAT-20261104.md)、[docs/workbench/NATIVE-SKILLS-20261103.md](../../../docs/workbench/NATIVE-SKILLS-20261103.md)。拆分记录为当前两技能边界，不沿用更早的组合制作入口。

**后续维护：** 变更时先核对上述调用链与当前官方实现；优先共用、缩小上游补丁。同步维护本卡的范围、入口、共通差异及验证依据；被上游吸收时移除对应适配并更新登记状态。原方法、历史输入和交付证据不在本卡复制或改写。

**首版登记记录：** 2026-11-05 按业务源码 `1901f83` 建立首版；首版为只读盘点及文档登记，未新增启用能力，未逐项重新执行产品验收。本轮补充项按当前源码及各自验证记录另行核对，不将首版记录冒称本轮业务验收。

**2026-11-05 规范整理：** SKILL 增加适用场景、当前画像、输入、执行流程和输出核验，方法正文和资源仍以原 SKILL 与引用原件为准；不新增发布或采纳授权。验证见本轮技能规范 Spec。
