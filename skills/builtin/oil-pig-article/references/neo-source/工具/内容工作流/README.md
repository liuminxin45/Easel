# 内容工作流工具

Codex直接对话的作品接续使用[工作台交接操作](../../.agents/skills/neo-content/references/工作台交接.md)和本目录toolbox_handoff.py，开始时明确绑定作品与当前回合，完成后由现有工作台worker接收；不复用旧请求标记，不增加通用聊天或重复制作任务。

阅读台选文批注见[批注接续操作](../../.agents/skills/neo-content/references/文章批注.md)。网页任务自动携带冻结的 `审阅与风格反馈.json`；直接对话核对指定版本可用 `python 工具/内容工作流/toolbox_review.py --work-id <作品ID> --candidate-id <版本ID>`。工具从既有阅读台读取，核验活动包哈希；异地布局用 `--desk-root` 指定项目，不猜测作品或发起制作。新版另附真实 `风格权重.json` 及逐条批注回应。

neo-content负责核查、写作与目视。程序保存三源快照、冻结要求、校验结构、准备图生、导入原件、检查和归档；不调用模型、不启用调度、不认可或发布内容。

## 当前默认

Tech Pulse｜科技脉搏使用用户认可的[图生首版v01](../../规范/模板/TechPulse-图生-v1/风格说明.md)，三张1086×1448 PNG；图内简明说明，配文按01–15逐条稍具体介绍，不挂链接且1000字内。完整URL、编号与证据映射另存。母版/风格保持到用户明确修改；其他题材和文章排版不套本母版。旧HTML及引用配文分支仅用于历史冻结版本复查。

## 准备与核查

Python3.10+及requirements；图片解码使用Pillow。Node22+与贴图生产工具用于现成PNG的材料/字数检查，文章预览另需Playwright。

```powershell
python -m pip install -r 工具/内容工作流/requirements.txt
npm --prefix 工具/贴图生产 ci
python 工具/内容工作流/workflow.py prepare --date 2026-10-09
python 工具/内容工作流/workflow.py capture --date 2026-10-09 --source github --id owner/repo --url https://github.com/owner/repo --scope "README用途" --file 已取得的公开原件
```

prepare/resume只重采失败来源，不补造历史数据。默认上海当天，已有同日期目录原样接续，来源快照固定。capture绑定证据到来源ID、URL、范围与原始字节，不能用其他条目的核查冒充。本程序匿名采公开内容；不得入库凭证。

输入另存版本，保持schema_version、snapshot_id、十五条source/id/顺序。每条填display_title、summary、verification=verified、refs，不填趣味收尾。2.5.0另填稍具体的caption_explanation，可填准确短名caption_name；poster_imagegen.explanation_caption固定三源与编号，caption_text按冻结模式选择简介或历史引用配文。程序校验十五条完整、顺序、网址及1000字上限；引用映射仍完整保存。新增配文事实须由refs支持，不能冒充亲测。指标只来自快照，程序通过不替代事实核查。

## 图生交接

```powershell
python 工具/内容工作流/workflow.py build --date 2026-10-09 --format poster --input 内容/技术晚报-2026-10-09/内容输入-v07.json
```

build保存准确提示词、认可母版、输入、引用、来源和任务，阶段awaiting_images，不生成HTML。AI读imagegen技能、查看本期认可PNG，逐页把提示词文件原样传给内置imagegen，以认可PNG为风格和尺寸参考。使用现有登录和可用内置工具，不要求另设图片API账号。工具不可用则记录阻塞，不退回HTML或暗换外部服务。

每次实际调用保存来源JSON：tool、mode=generated、actual_prompt_file、reference_image_sha256、真实原图路径、实际参考路径及工具是否公开模型名。mode=approved_sample_reuse只用于同快照Product Hunt认可母版，须保存sample_snapshot_id与原始实际提示词；不把样稿的后来认可说成最初调用曾引用自己。

```powershell
python 工具/内容工作流/workflow.py import-image --date 2026-10-09 --page 1 --file 原始生成图.png --record 实际调用.json
python 工具/内容工作流/workflow.py check --date 2026-10-09 --format poster
```

每页原图、实际提示词、来源JSON、尺寸和SHA入本期产物。拒绝缩放冒充母版尺寸。成功页固定；失败页原件仍保留，初稿加两轮失败则阻塞。相同输入再次build复用待完成任务，import-image重复同图可复用，已检查成品须新版本。三页都完成才awaiting_visual_check，缺任一页不能交付。

## 文章、目视与归档

article复用同快照，每源首条填detail/detail_refs，其他四条简述，另填intro。新增说明绑定证据。正文Markdown与公众号HTML来自同结构，执行现有文章模板与检查，文章无1000字上限。文章HTML预览需安装贴图工具的浏览器依赖。

```powershell
python 工具/内容工作流/workflow.py build --date 2026-10-09 --format article --input 文章输入.json
python 工具/内容工作流/workflow.py visual --date 2026-10-09 --format poster --record 实际目视检查.md
```

AI须实际查看三图/文章预览，核对字词、事实、编号、指标、水印、可读性和来源后写记录。程序不能证明目视发生。visual自动生成带文件SHA的归档索引；每期贴图及文章交付前规范归档，AI同时维护内容档案、进度、反馈、完整指导和修改前后入口。不以全局缓存或聊天替代项目。ready_for_user_review才可交付，仍pending_user_review/not_published；已认可风格不替代本期成品认可。

## 版本与边界

同日互斥锁位于忽略的.runtime，异步生成时没有占用长时间跨命令锁；图生导入在同日锁内串行执行并校验既有字节。异常锁只在确认原进程退出后手动解除。快照、模板、母版、指引、规范及产物均保存SHA；普通更新只影响新期。用户明确重做当前期时，先保存原话再revise --record冻结新约定，保留旧来源和旧成品。同一指导原文字节识别修订组，最多初稿加两轮，不靠自动revise规避上限。

1000字只检查贴图配文；图内文字另检可读性；文章不限1000。default_format=poster。目标23点，enabled=false，没有启用调度、无人值守生产或发布，也不自动提交和推送。退出码0只代表命令成功，仍须检查阶段、deliverable及review。

## 验证

```powershell
python -m unittest discover -s 工具/内容工作流 -p test_workflow.py -v
node --test 工具/内容工作流/render.test.mjs
npm --prefix 工具/贴图生产 test
```

构造数据与PNG仅为临时测试，不是生产采集、实际图生或核查证据。检查覆盖来源失败、字段证据、字节保护、仅索引配文、错误尺寸、部分图接续、完整归档、待评审状态及历史HTML兼容。

## 当前采纳收尾：2.1.0

2026-10-10起覆盖上文“交付前直接归档贴图”的旧安排。新poster候选全部在忽略的.runtime/贴图待采纳，visual只完成实际目视，阶段ready_for_user_review。程序/来源/实际原件仍完整，archive_complete=false直到用户采纳；文章保持原归档。内容输入也写候选区，内容标题目录只保存过程和核查。

AI展示完整版本并必须询问用户是否采纳，保存真实问题和全文答复。继续修改/未答复不能执行review。用户选择后：

```powershell
python 工具/内容工作流/workflow.py review --date 2026-10-09 --decision accepted --record 实际采纳答复.md
python 工具/内容工作流/workflow.py review --date 2026-10-09 --decision rejected --record 实际否决答复.md
```

采纳将缓存原件按字节核对后转存产物/版本，生成采纳状态及归档索引；不采纳只留价值过程并清除指定缓存。旧规则下已经保存历史成品不追溯删除。通用贴图用poster_review.py decide --item内容标题目录 --bundle实际候选包 --decision accepted或rejected --record真实答复；采纳须程序检查.json通过且目视检查.md存在。文件路径参数保持独立，不把空格目录串为多个参数。

AI列明逐文件同步范围JSON：decision、approval_record（项目相对路径）、approval_sha256、files数组、remote、remote_url、branch。否决另设process_only=true；用户提供的参考附件可单独列process_attachments=[{file,sha256,kind:"user_provided_reference"}]，不得伪装候选。范围文件放.runtime，禁止目录/通配符/临时文件/凭证。确认远端后运行：

```powershell
python 工具/内容工作流/poster_review.py sync --scope .runtime/贴图同步/本次范围.json --message "Archive adopted poster and workflow records"
```

此步骤已获用户长期授权，不再问提交推送权限。只暂存明确文件，保护其他改动/暂存，fetch核对远端（脏工作区不pull、不stash、不重置）。正常推送后ls-remote确认HEAD；重复sync无新改动时不额外commit。远端分叉、认证或网络失败保留用户决策和本地提交，报告实际阻塞；不强推。成功Git同步不代表平台发布，也不启用调度。程序不能自行取得人类答复或代替Agent识别本次范围，收尾由唯一neo-content组织执行。

## 固定标题：2.2.0

新期统一使用`Tech Pulse｜科技脉搏 YYYY-MM-DD`，由配置title_pattern生成并逐字检查日期；用户指定栏目标题例外，其他题材20字内部上限保留。历史冻结标题不改。

## 每日栏目：2.3.0

poster.section_subtitles冻结每日趋势、每日热议、每日速览，直接使用原有红色副标题位置。每天观察快照，重复条目按来源原顺序保留，不宣称全新；Product Hunt仍为订阅速览。交付配文使用纯文本代码块，块内不加字数或过程注释。旧期按其冻结值复查。

## 用户指定单条中文标题

用户明确要求调整本期每条标题时，`revise --record 全文指导.md --item-titles editorial`将选择冻结到本期修订合同，不改旧期合同。2026-10-12用户明确采纳v02并要求记住做法，配置2.4.0将editorial设为新期默认，文案执行唯一贴图规范。GitHub与Product Hunt显示准确的中文定位标题，Hacker News显示直接事件标题；GitHub原始owner/repo保留在指标行，排名、数值和引用不变。标题和说明各承担信息，不增加空泛口号。图生仍使用已认可母版的几何与视觉，实际新产物另行评审。`original`恢复原标题模式，仍须用户明确指导及新版本。

## 混合文件的限定同步

同一规范或索引有其他未提交工作时，Agent先对照HEAD与工作区，只暂存已授权片段；同步范围的partial_files逐项保存file、原head_blob、已暂存staged_blob及工作区worktree_sha256，新文件的head_blob为null。sync核对这些值后跳过对该文件的整文件git add，保留其余未暂存内容；变化或范围外暂存会阻止同步。普通文件仍逐项暂存，远端、答复、分支和重试检查不变。测试使用临时本地bare远端，不代表实际GitHub推送。部分提交的真实范围以提交树为准，不用工作区完整文件SHA冒充已提交内容。

## 本期独立编排试作

用户明确要求新版UI时，`revise --record 原始指导.md --edition-plan 项目相对编排.json`冻结本期封面、三源总览和重点说明页，以及对应生成指引；不修改默认三张配置或旧模板。编排首张为cover，三个source页保持github/hackernews/producthunt顺序，focus用01–15中的reference及三个headings，对应条目的detail须有三段并绑定detail_refs。图生准备、导入、检查依据本期页数，未齐全不得交付。`--page`以实际任务为界，旧版仍限三页。

实际生成需要清理或修正时，将完整`revision_instructions`写入制作记录；实际提示词必须为冻结提示词加`REVISION INSTRUCTIONS:`及该指令。初稿和修正原件均保存，不能把旧模板样稿冒充新编排。该能力不代表新视觉或新页数已获认可，仍走询问采纳、归档与限定同步。2026-10-13五页仅为本期候选。

## 标题与配图反馈检查

`creative_review.py`把[写作要求](../../规范/写作要求.md#标题与配图的反馈检查)和[图片要求](../../规范/图片制作要求.md#标题与配图的反馈检查)接到制作流程。它检查记录、适用范围和文件字节；标题吸引力、动作意义与实际目视仍由Agent判断，不运行模型训练、不自动采纳或发布。字段由[模板](../../规范/模板/创作检查-v1.json)定义，比较材料来自[有原话的案例索引](../../资料/风格研究/反馈检查案例.json)。

新制作按[用户任务与技术解释](../../规范/写作要求.md#用户任务与技术解释2026-10-23)回应本篇用户任务或具体变化，机制和用法只在有解释价值且有材料支持时展开，配图取舍按[图片要求](../../规范/图片制作要求.md)执行。仍在现有`context`和四项`checks`中写具体理由，不新增风格评分；更新后的提问只进入新准备的记录，固定栏目约定与历史内嵌冻结合同保持兼容。

### 新版本制作前

在本版候选目录创建待填记录，不覆盖现有记录。`work_id`对应实际作品，`version`对应本次候选版本；工具箱版本ID与本地v0.x应在本篇交接中明确映射，不能猜最新版本。

```powershell
python 工具/内容工作流/creative_review.py prepare --file ".runtime/贴图待采纳/本篇/v0.1/创作检查.json" --format poster --profile custom --work-id "实际作品ID" --version "实际版本ID" --title "暂定标题"
```

记录须与草稿包或文章交付清单同层。按实际情况填写：

| 字段 | 填写内容 |
| --- | --- |
| `context` | `topic/audience/reader_need/core_message`：主题、真正的读者、需要解决的问题与核心信息 |
| `title` | `mode=explore`时，`candidates`至少两种不同角度，每项有`text/reason`；`selected`取其中一个，另写最终取舍`reason`。固定栏目用`fixed`，用户逐字指定用`user_exact`，`lock`记录项目相对`file`、原件`sha256`及精确`quote`；固定引文须匹配标题全文或`{date}`日期模式 |
| `source_inventory` | 每项写`source/decision/reason`，说明看了哪些真实素材、为什么采用或不用 |
| `visuals` | 每图写`id/final_file/purpose/increment/action/kind`；`kind`区分`generated/screenshot/diagram/source`，避免重复装饰和把插画当实测。新生图另写实际`prompt_file`和布尔值`uses_mascot`；有角色时填`identity_files`身份参考 |
| `comparisons` | 对冻结的每个历史案例写`status/reason`，判断`pass/not_applicable`及范围；`pending/needs_revision`不能放行，不能只填“已参考” |
| `checks` | 保留模板四项ID与阶段，逐项填写具体判断。标题项不能“不适用”；无图文章可把图像项说明为不适用 |

`profile`用`custom`（自制）、`source-only`（仅真实素材）、`fixed`（固定母版）或`none`（实际无图）。候选还没生成，不要求成品文件已存在；实际提示词、身份参考须在生成前绑定。以下材料路径均相对记录目录：

```powershell
python 工具/内容工作流/creative_review.py bind --file ".runtime/贴图待采纳/本篇/v0.1/创作检查.json" --stage plan --materials "素材/实际生图提示词.txt" "素材/身份参考.png"
python 工具/内容工作流/creative_review.py check --file ".runtime/贴图待采纳/本篇/v0.1/创作检查.json" --stage plan
```

不用生图时按实际绑定材料，可省略`--materials`。计划通过后才进入生图或最终排版；工具不代填主观结论。

### 交付前与文件变更

通用贴图草稿包增加`creative_review: "创作检查.json"`，新包同时写实际`work_id/version`。带该字段始终检查；新制作另加`--require-creative-review`，缺记录也会阻塞。`render`先检查plan，最终`check`检查delivery。没有HTML页的图生包，把实际成品列入`assets`；有HTML页时，以各页`output`作为最终图片。

```powershell
node 工具/贴图生产/cli.mjs render --manifest ".runtime/贴图待采纳/本篇/v0.1/草稿包.json" --require-creative-review
```

实际查看每张完整成图和独立手机尺度预览，填写`delivery.views`：`target`为成图路径，`file`为查看文件，`scale=full/phone`，`note`写看到的问题与结果。完整查看指向成图本身，手机查看指向另存的真实预览；工具不会生成或声称完成目视。之后绑定所有实际交付文件与图片，再完成delivery阶段两项判断：

```powershell
python 工具/内容工作流/creative_review.py bind --file ".runtime/贴图待采纳/本篇/v0.1/创作检查.json" --stage delivery --files "配文.txt" "标题与配文.txt" "01.png" --images "01.png"
node 工具/贴图生产/cli.mjs check --manifest ".runtime/贴图待采纳/本篇/v0.1/草稿包.json" --require-creative-review
```

正文、成图、预览或实际提示词变了，旧哈希不再放行；标题和计划变动也须重新完成plan。重绑变更须`--reason "具体改动原因"`，并重新填写已重置的delivery判断。`--report`可用于`check/summary`，仅写项目内的新文件，不覆盖旧报告。程序通过始终是`assistant_assessment`，用户采纳仍由既有评审流程单独登记。

新文章的`文章交付.json`增加`work_id/version/creative_review/html_file/images`，`images`列本包相对配图文件，无图明确`[]`。HTML中实际`img`必须与清单一致，用明确的本地相对`src`，不使用远程图或`srcset/picture source`分支隐藏其他配图。正文、HTML和全部配图一起绑定；产品实测与来源验收仍独立执行。

```powershell
python 工具/内容工作流/creative_review.py check --article-manifest "内容/本篇/产物/v0.1/文章交付.json"
node 工具/内容工作流/article-check.mjs "内容/本篇/产物/v0.1/公众号排版.html" "内容/本篇/产物/v0.1/预览" --article-manifest "内容/本篇/产物/v0.1/文章交付.json" --require-creative-review
```

原两参数文章入口继续用于历史复查和初次排版预览，不能代替新稿的完整交付检查。固定三源配置2.6.0冻结模板与案例，build自动准备本期待填记录；准备、图生导入不因pending循环阻塞，最终check/visual才要求完成，成功目视后锁定记录字节。复用build生成的记录，勿再prepare覆盖。旧冻结合同、已采纳作品和历史记录保持原样，不补造检查。

### 动图说明

GIF/WebP候选使用同一检查记录，`final_file`和`--images`填写实际动图；手机预览保留真实查看所得的文件。通用HTML导出器只识别PNG/JPEG，动图沿用GIF Sticker Studio/Remotion的帧序、时长、回环与播放检查，不调用旧导出器冒充动图验收。通过本检查器验证记录与文件绑定：

```powershell
python 工具/内容工作流/creative_review.py check --file ".runtime/贴图待采纳/本篇/v0.1/创作检查.json" --stage delivery --expected-format poster --expected-work-id "实际作品ID" --expected-version "实际版本ID" --expected-title "最终标题" --expect-file "01.gif" --expect-file "标题与配文.txt"
```

制作前同样执行`--stage plan`，尚未生成的动图不列`--expect-file`。绑定文件本身不检查动画是否自然，也不代替动态预览。

### 后续反馈与观察

先按原有文章学习流程保存完整原话、对应版本与范围，再登记一次具体观察。`--evidence-file`相对项目根目录，`--quote`必须逐字出现在原件中；如原件含工具箱作品ID/目标版本ID，必须与提交标识一致。

```powershell
python 工具/内容工作流/creative_review.py feedback --file "内容/本篇/反馈/检查观察-操作ID.json" --work-id "实际作品ID" --version "被评价版本ID" --case-id "title-audience-fit" --evidence-file "内容/本篇/反馈/用户原话.md" --quote "精确用户原话" --outcome repeat_issue --reason "本次原话与案例的具体关系，不能外推其他维度"
python 工具/内容工作流/creative_review.py summary --files "内容/本篇/产物/v0.1/创作检查.json" --feedback-events "内容/本篇/反馈/检查观察-操作ID.json"
```

`outcome`为`repeat_issue/positive_example/unclear`。分类是助手解释，不自动修改规范、不推定其他认可。汇总只读指定记录，拒绝同版本和同反馈重复计数；没有真实新反馈时明确未采集，不把自审通过数变成质量、点击率或“提升百分比”。

### 验证

```powershell
python -m unittest discover -s 工具/内容工作流 -p test_creative_review.py -v
node --test 工具/内容工作流/test_article_creative_review.mjs
node --test 工具/贴图生产/test/*.test.mjs
python -m unittest discover -s 工具/内容工作流 -p test_workflow.py -v
```

测试使用隔离夹具，不代表正式创作或真实用户认可。
