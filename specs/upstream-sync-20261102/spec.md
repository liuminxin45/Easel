# Easel 官方基线同步（2026-11-02）

Spec: upstream-sync-20261102

## 目标和保留行为

按项目 easel-upstream-sync/codex-spec 工作流跟进官方更新：pull rebase、解决冲突与适配、验证、mark基线并推送自有fork。
官方旧基线 `5a597e5f3ef5b01098b53f36caf719dd9a32b7bf` → 目标 `0f43dc98277eac85fb48952878acad349731d3fc`，目标固定为本次pull的FETCH_HEAD。
旧私有 `3246babaaf1ecd22ecdd88217d6e33a3c974d067`、分支 `codex/easel-base-alignment` 保留；新分支 `codex/easel-sync-20261102-082005`。
不重写已共享分支，不推官方，不修改历史标签/快照、业务数据、冻结任务/原文/反馈或未知操作身份。
本次同步不隐含生产部署，现有不可变前后端继续运行。

## 当前进展与集成范围

官方15新提交、64文件；多数采集与代理改动先前已以相同patch引入。
本次rebase自动识别6条官方等价提交，110条完成重放，无手动skip；
唯一显式冲突为SettingsSelect的Tab焦点注释，保留官方措辞和兼容行为。
官方collector cleanup、thinking env重复值/乱码处理、CLI前端过期诊断已进入源码。
核对并纠正历史私有提交覆盖官方Sidebar画像下拉、primary配色/hover、profile滚动和dropdown唯一CSS的偏差；
保留宿主可选接口、移动抽屉、下载及CopyableText扩展，移除已由官方解决的重复实现。
官方dropdown.css新增为私有冻结构建输入；共享服务仍只有一份，私有Python采集/来源修订继续调用官方runner。

## 验证与交付

已完成：376项前端、原生与私有build/check、212官方相关测试（1平台跳过）、59私有采集/回执、102架构/技能检查。
官方原检出独立build通过；未修改的官方技能预算34项也通过，fork测试按123个真实技能保留全部预算/运行可见性约束。
R2完整390/1280明暗各144项共288通过；最后portal一行修复后，R3同数据对照/菜单/设置/画像定点612项通过，
不将R2报告改称R3全量。原官方菜单遮盖已真实复现；修复后desktop/phone均centerHit=true，选择不关抽屉。
当前视觉复核无遗留；原始失败、过期探针、字节守卫诊断都保留，不放松产品约束。
已mark准确官方SHA和annotated tag，历史JSON仅新增，旧快照/标签不改。
本轮仅推新分支和标签到自有origin，无force、不向官方提交，也未切正式配对。
旧分支出现并行P2两提交，完整保留并登记；本次验证不冒称包含P2，后续应单独接到新基线上复验。
人工反馈：尚未收到本轮反馈。

原始证据：`.local/workbench-validation/upstream-sync-20261102-082005/`。


冷启动诊断：rebase按Git规范化重放时，120个未改内容的运行输入发生换行字节转换，
其中内容寻址提示词触发原始SHA守卫。已从活动不可变包逐个验证SHA，仅恢复Git语义相同的原始字节；
capabilities与workspace修订恢复且与活动包相同，历史文件/哈希声明不变。
新增真实仓库内容寻址原件回归，先红后绿；原有.gitattributes已声明LF，不能依赖重放完成后自动重写既有工作文件。
初个隔离包/全零检查报告保留为诊断，重新冻结后再运行浏览器，不放松守卫。


官方0f43原始构建的额外真实回归：SkillDrawer新choices控件将菜单portal到body（z100），
被drawer-overlay（z1000）遮挡；桌面和手机的实际elementFromPoint均命中panel而非菜单。
本fork仅在SettingsSelect增加最近drawer-overlay挂载点，不改官方CSS层级，并补共享控件回归及编译后真实命中验证。
旧测试的z1000/桌面36px阈值改为实际命中及24px鼠标/44px触控标准；保留真实可见范围、键盘和触控断言。
横屏单次160px触控可能未覆盖178px滚动范围，已用真实maxScroll证明可达；改为有界可信手势并逐次检查响应，不改生产CSS。

## 后续 P2 集成（2026-11-02）

用户随后明确要求把 P2 接到本轮新基线上。在本同步分支的交付提交 4e93bcf 之后，
已接入原 P2 两提交的改动并完成组合回归；功能提交 8747400。
新官方前端源码保持，936 份官方/技能/资源/来源原始 SHA 不变，私有 SourceRegistry 保留。
本次组合新跑 84 项 P2、256 项合同/架构/来源、376 项前端，以及准确冻结包的
34 项内容闭环和 9 项恢复；与原同步验收分别记录，不改写旧报告为已含 P2。
当前主工作区分支已含 P2，旧 P2 分支和提交未重写，生产仍未由本批切换。
配对与证据见 `docs/workbench/PRIVATE-ARCHITECTURE-P2-INTEGRATION-20261102.md` 和
`.local/workbench-validation/p2-upstream-integration-20261102/`。
