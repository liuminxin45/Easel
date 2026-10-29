# Easel 私有工作台已上线（2026-10-30）

正式入口：https://leopc.tail2ce65.ts.net:8443/native/

- 主工程及正式业务库：`D:/Projects/Easel`、`data/desk.sqlite`。
- 后端：`workbench-20261029-181552`，SHA `db62ba039639b19fb99a7fc3584446157c217d3067f5c520404ba2bf0ad7d57c`。
- 前端：`native-easel-workbench-20261029180737`，SHA `ce998b0aa3016925281e88becd7af45363048e95ee2c0cc6608534aa0a63d024`。
- 原HTTPS地址、账号登录、浏览器草稿与操作身份保持；旧项目原件和版本保留。

## 功能与数据

采集、内容生产、画像、技能、作品版本、反馈、采纳、归档与发布管理已接入自有扩展。
九个现有来源通过 fork 的 Python 自定义采集器协议，完整原始载荷保留，模型编辑和入库/ack仍在父流程。
上游普通Easel入口与私有profile独立，避免把私有流程散入上游页面和执行器。
已退役的通知、设备、自动账号检测、资料库和未授权媒体引擎没有恢复。

停写后复制4,422个文件及14个SQLite数据库，逐表完整schema/行指纹和文件SHA核对通过。
旧库与新库的2,611条资讯、78份作品、213条制作记录、567个产物记录、919条历史通知一致；
850个附件经迁入读取路径及内容哈希检查通过。历史冻结输入、未知回执、原始反馈与发布历史保留。
旧服务写入者均已停止，启动任务与兼容launcher已转至Easel。
neo-content两个接续CLI也验证新owner/manifest，切换期间不能回落旧库。

## 验收

- 当前准确不可变包完成184项业务合同、29项完整流程浏览器检查、30项页面检查、8项升级/IME/离线重连。
- 贴图/文章×桌面/模拟手机，实际驱动假native完成首版与修改8次，以及两端讨论后同作品首版2次，共10次；验证准确反馈、采纳、存草稿授权及原讨论快照保留。
- 两端另经真实页面操作核对选题讨论、参考拆解、整理经验、发布复盘的候选v2、明确试用与准确画像进入真实TEMP队列。
- 153项专项回归通过，包括31项架构边界、12项技能策略、40项真实服务命令路径，以及迁移、账号连接、外部CLI与升级控制。
- 10项前端合同、TypeScript strict、实际构建产物退役写接口清理、原Easel独立构建通过。
- 清除102个旧flat模块别名后完整流程通过；旧包负控能准确抓住旧desk动态导入。
- 迁入时9源真实只读采集通过，本轮重跑20项桥接及切换安全测试。NewsNow的36kr上游HTTP500保留partial状态，其他候选仍可用。
- 初次迁移曾修复collector/publisher日志角色映射；本轮7角色按最终包再次独立启动验证，当前业务/UI检查均重新执行。
- 正式地址桌面/模拟手机页面与7角色稳定性在切换后复查；迁入时既有图片下载SHA、外部CLI和登录启动注册证据继续保留。

测试没有调用真实AI制作或平台发布；移动端为浏览器模拟，不冒称实体vivo验收。

## 本轮架构收敛

- `skills.py`集中任务要求与启动动作，从唯一能力注册的已选版本派生；前端不再按技能ID各写一套启动逻辑。
- 内容生产作为组合技能连接写作、配图和独立核验；组合登记不增加模型回合。版本、账号、授权、幂等队列和未知回执由程序服务负责。
- 新受理严格验证技能适用任务、准确版本与明确试用；页面显示实际画像固定版本，已冻结历史直接按原记录接续。
- 参考拆解/经验整理/复盘统一显式执行选择；待改善技能作为材料。复盘准备中断后沿同一冻结SHA重试，候选后来发布也不改变原试用身份。
- 修复新讨论缺少草稿修订、只读讨论误编译制作方案、讨论后首版缺少生产技能选择等真实路径问题。
- 删除闲置自动账号检测与撤回媒体前端模块；连接/发布复用独立环境策略，不反向加载媒体执行器。冻结运行包缺少明确业务根目录时拒绝启动。
- 空闲后在同一写入围栏下切换绑定的前后端；本次未复制、回退或恢复数据库，历史未知请求保持不重放。

## 证据

- `.local/workbench-validation/architecture-181552/report.json`：本轮最终准确包的184/29/30/8与10次模拟执行、命名空间、完整文件哈希。
- `.local/workbench-validation/architecture-entry-181552/report.json`：最终7角色入口实测。
- `.local/workbench-validation/architecture-regressions.xml`：153项专项回归。
- `.local/workbench-validation/frontend-180737/report.json`：10项前端合同、strict及准确构建输入。
- `.local/workbench-validation/architecture-live-181552/report.json`：正式地址14页、实际8项技能源投影、7角色稳定心跳；仅登录与只读检查。
- `.local/workbench-deployment/upgrade-acceptance.json`：准确前后端、源码、能力目录与验收控制绑定。
- `.local/workbench-deployment/upgrades/workbench-20261029-181552.json`：本轮真实空闲切换、前一版本、同一数据库及历史未知回执保留。
- `.local/workbench-validation/final-170756/report.json`：完整业务/UI/命名空间隔离。
- `.local/workbench-validation/final-172153/report.json`：入口修复验证及准确复用映射。
- `.local/workbench-validation/entry-172153/report.json`：7角色真实启动与日志。
- `.local/workbench-validation/collectors-170756-reuse.json`：采集冻结与9源实测映射。
- `.local/workbench-validation/audit/final-audit-tests.xml`：迁移、控制和外部CLI。
- `.local/workbench-validation/live/`：正式页面、图片、进程和启动注册。
- `.local/workbench-deployment/deployment.json`：真实迁移和切换；migration-verification.json为最终停写复制核验。

初次复制后两个后台曾因日志角色名不兼容未启动；原失败日志及候选保留。
修复通过独立启动负控与7角色验证后，在空闲和写入围栏下更换运行包，始终保留同一新业务库。
回退只使用兼容运行包/前端并保留新库，不恢复旧数据库、不重放未知任务。
