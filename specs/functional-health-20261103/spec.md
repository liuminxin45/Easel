# 持续运行与全模块失败核查

用户报告雷达热点仍停在11月1日，要求逐模块核查失败、修复、提交自有fork并部署。
基线：交付3d636e7，应用36bd5be，运行workbench-20261102-170044/native-mobile-return-20261103-r3。

只读确认：articles最新入库11月1日，之后九来源均有failed；collector出现blocked/OperationalError；
feedback日志为SQLITE_BUSY。进程与HTTP在线不能代替业务成功。
TEMP对照确认local_operations将目录扫描/哈希放在BEGIN IMMEDIATE内：原实现阻塞独立writer，
新实现应让慢扫描期间collector/feedback仍可写，并按准确快照CAS校验，不自动猜测关联。
真实来源协议还确认collector_worker直接脚本路径使私有http包遮蔽stdlib http.client；
新增真实子进程bootstrap回归，修复不改上游runner或采集协议。

并行责任：根负责采集/新鲜度/API健康接缝及交付；runtime负责归档锁与业务loop心跳；
page_state负责热点订阅及首页/拆解/画像/日历/内容库真实失败反馈；boundaries负责集中只读业务健康。

保留官方页面与协议、旧ID/版本/原话、账号/画像、已有授权和未知回执不重放。
不将未配置发布、空选题或正常等待关联误报故障，不自动启用退役功能。
生产仅核查与恢复用户已有采集；制作、修改、采纳及平台交付验证用TEMP，不执行真实发布。

验收：原实现受控失败与修复回归；真实规模并发写；逐模块功能矩阵；原/宿主构建；
冻结实际前后端后TEMP闭环和真实只读来源验证；新鲜内容入库及页面可见；稳定排程/健康观察。
Git仅origin/main，upstream只读；精确配对切换、历史保留、数据不回滚。

当前实施证据：`.local/workbench-validation/functional-health-20261103/`。
当前状态：本轮确认的问题已修复、提交推送自有fork并配对上线。
应用23f59b0；后端workbench-20261102-181354，前端native-functional-health-20261103-r1。
真实失败批次已恢复，新增62条，最新入库11月3日02:10；8来源完成，NewsNow因36kr上游500部分完成。
前端486、不同后端416、完整内容闭环36通过；同一前端明暗主题各59区域覆盖，后端差异分层验证。
方案只读预览与原合同深等，最终线上方案校验约3秒；无制作/发布或未知重放，排期与历史保留。
详情及Git/manifest见`docs/workbench/FUNCTIONAL-HEALTH-20261103.md`。
