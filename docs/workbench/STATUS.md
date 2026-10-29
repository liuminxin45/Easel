# Easel 私有工作台已上线（2026-10-30）

正式入口：https://leopc.tail2ce65.ts.net:8443/native/

- 主工程及正式业务库：`D:/Projects/Easel`、`data/desk.sqlite`。
- 后端：`workbench-20261029-172153`，SHA `6b5c112632c15f84c7d60e7731dc8c843bacf2c4e7c3d8864ab0b53430fc4d81`。
- 前端：`native-easel-workbench-20261029164526`，SHA `9919b778cbfc4b6f6316062d187886c013668ed03fc02d1ec92f1b23f2a40b2d`。
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

- 184项业务合同、17项完整制作浏览器流程、30项页面检查、8项升级/IME/离线重连通过。
- 贴图/文章×桌面/模拟手机，实际驱动假native执行器完成首版与修改共8次，验证准确版本反馈、采纳及账号存草稿授权。
- 清除102个旧flat模块别名后完整流程通过；旧包负控能准确抓住旧desk动态导入。
- 9源真实只读采集、20项桥接合同与切换安全测试通过。NewsNow的36kr上游HTTP500保留partial状态，其他候选仍可用。
- 上线后补齐collector/publisher日志角色映射和workbench版本日志，7角色独立进程启动测试通过；其他202个源成员、依赖及前端字节相同，业务/UI证明按明确哈希映射复用。
- 正式地址桌面/模拟手机14页面、既有图片下载SHA、7角色稳定PID/版本日志、两个外部CLI和登录启动注册已实查。

测试没有调用真实AI制作或平台发布；移动端为浏览器模拟，不冒称实体vivo验收。

## 证据

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
