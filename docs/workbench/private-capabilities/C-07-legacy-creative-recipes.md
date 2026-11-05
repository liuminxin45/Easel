# C-07 旧创作配方、图稿方案与样本导入存量

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

- **状态：** 兼容受限／混合读写存量；不是新增风格管理页、隐藏生产页或自动生图许可。
- **需求依据：** 用户保留风格/角色参考、准确创作材料、原件与历史，但新创作应使用两个油猪原生技能，并退役旧私有参数预设与技能管理。当前方案/样本记录只按已有调用与授权解释，不因源码存在扩展新功能。
- **范围：** 旧创作预览、样本原件导入和图稿方案记录；当前新闻材料/显式画像默认归 [PC-07](PC-07-news-creation.md)，本卡不接管其唯一来源。

| 入口/动作 | 当前源码行为与限制 |
| --- | --- |
| `POST /api/creative/preview` | 只读构造预览；不能排制作、复制全库、保存用户采纳或将预览当真实绘图。 |
| `POST /api/creative/commands` → `import-sample` | 校验原文字/链接与真实附件、类型/大小/SHA，保存项目“资料/风格研究/工作台导入/<operation>”原件并更新证据索引；会写文件及回执，不自动分析。 |
| 同路径 → `save-image-plan` | 按真实作品/候选、逐图提示词、参考SHA与尺寸保存 creative_image_plans；状态为 prepared，不冒称已调用生图。 |
| 同路径 → `prepare-image-plan` | 使用原讨论队列准备文字图稿方案，指令禁止生图/渲染/发布；可能排Agent讨论，不能标成只读。需明确原操作和作品/草稿修订。 |
| `GET /api/creative/{bootstrap,effects,image-plans,prompts/...}` | 读取旧记录、当前可读材料及准确版本指令；历史版本/试用字段只解释原记录，不成为新技能执行前提。 |
| `POST /api/style-presets` | 返回410；保留历史配置不恢复旧参数预设。 |

**HTTP 与存储：** 旧命令经服务器登录/同源/CSRF与操作身份检查；CreativeRecipes 复用既有 learning/box、creative_receipts、creative_image_plans 和源文件，不建立新技能数据库。鉴权不是新业务授权，也不替代 NativeApi._mutate 的原生事务边界。

**源码：** [creative_recipes.py](../../../easel_workbench/runtime/creative_recipes.py)、[creative_policy_files.py](../../../easel_workbench/runtime/creative_policy_files.py)、[toolbox_server.py](../../../easel_workbench/runtime/toolbox_server.py)、[ProductionParameters.tsx](../../../web/frontend/src/workbench/ui/ProductionParameters.tsx)。旧 `production.tsx` 未在当前壳挂载，但不能据此推断接口全部不可达。

**官方复用与差异：** 新技能使用 [PC-08](PC-08-oil-pig-poster.md)/[PC-09](PC-09-oil-pig-article.md) 及官方技能服务，版本详情使用共通 Drawer；不能为这些存量再造官方聊天/技能页面。本次登记无新增官方源码修改。

**验证入口：** [test_workbench_creative_preview_readonly.py](../../../tests/test_workbench_creative_preview_readonly.py) 检查真实预览与无写入/排队；[test_workbench_news_creation.py](../../../tests/test_workbench_news_creation.py) 检查新新闻材料的准确风格及来源。其他旧命令的实际执行和生产开关没有由这两组测试全部证明，本卡不作该声明。

**后续维护：** 新样本入口、配方持久化、图稿Agent调用或文件写位置变化，必须核对单独需求并更新对应能力卡及验证；不以旧文件方法替代当前SKILL。涉及退役时保留原始材料、回执及已受理任务。

**登记记录：** 2026-11-05 从 U-02 拆为专门文档，区分预览/保存/排讨论及410；不调用上述接口、不创建新许可。
