# 后台新闻合同与退役技能解耦

## 目标与边界

用户要求完整修复热点雷达只剩 GitHub Trending，验证、推送自有 fork、部署上线。
仅在私有层修复；复用官方 TrendsPage、DashboardPage、原生执行器与既有采集队列。
不恢复 topic-research 等退役技能，不改变油猪四个用户技能、来源筛选标准、当天面板或发布权限。

## 已复现根因

2026-11-06 活动包 workbench-20261106-083810：AIHOT、NewsNow、观猹抓取成功后
因 task_runtime/观猹依赖已退役 topic-research，在模型发送前抛 ValueError。
HN/PH 当天各入库10条，但中文标题同样在准备前失败，展示投影各为0；GitHub实际4条。
标题队列3次准备失败后耗尽，下一次空轮询刷新心跳并掩盖业务失败。
中控把 NewsNow 局部 HTTPError 覆盖诊断当成整个失败的提供者原因，掩盖本地错误。

## 实施

- PC-05/06：后台 news_enhancement 使用 features/collection/news_contracts.py 与专用 references。
  三份原方法合同原样迁入私有采集目录；旧资源仅保留历史出处，后台不再读取退役技能。
  直接复用画像读取函数，不初始化技能默认/pin；冻结合同、画像修订、资源字节SHA及完整输入。
- 普通技能合同和旧已冻结 snapshot 保持原路径。后台 snapshot 明确 skills=[]，
  单独记录 execution_contract，不冒称选择了用户技能；中文概述复用原 Easel 只读执行器。
  采集筛选沿用已审计 collection_model 的传输、指纹、缓存和未知回执阻止规则。
- 覆盖 AIHOT/NewsNow、观猹、标题以及每周周刊的同类合同读取遗漏，观猹传递准确 root。
- PC-19：当前来源本地处理失败与第三方覆盖异常分别计数；存在本地失败不归为纯提供者故障。
  SQL聚合当天 HN/PH 标题结果，准备失败、耗尽或超时不被正常心跳清除。
  保持健康后端不因业务故障重启，保留中控每日预算与未知不重放。
- 显式恢复：仅重开当天已知旧 ValueError、准确输入SHA且没有任何原模型调用账本的标题。
  有原调用一律保留并核对，不重置未知或已完成调用。来源通过原队列 retry 的准确阶段恢复。

## 验收

回归测试使用 TEMP 数据、旧技能解析禁止器、假传输，验证后台合同、准确调用账本、
筛选缓存复用、中文标题原生边界、原调用禁止重发、当前日业务健康及第三方故障分类。
运行架构、技能策略/命令、原只读执行器、采集新鲜度及回执保留检查。
冻结候选后在模拟移动浏览器核对既有雷达页面，不改官方控件或增加失败条幅。
上线后准确恢复当天任务并核对真实结果；空来源保留空面板，无旧缓存替代。

## 进度与证据

已通过271项回归、2项子测试（含架构、技能、只读执行、准确回执、画像及中控）；前端check:workbench通过。
已正式上线并完成真实恢复；本地证据目录 `.local/workbench-validation/background-news-20261106/`。
提交、活动版本、真实采集/模型回执与浏览器结果分别记录，不以 TEMP 结果冒称线上恢复。


## 正式交付结果

- 业务源码提交 `5d2c3cb04a11095bbf90197a194975e460a636ec`，仅推送自有 `origin/main`；无官方提交或PR。
- 正式后端 `workbench-20261106-094618`，manifest SHA256 `d3873a59e2f28ef12961e3cd1671a51bdd31daa583c261a9a48c2754a919af5c`。
- 复用未改动的正式前端 `native-private-title-20261106-r2`，配对SHA256 `ccfed21f584bf9c93b1b2340f4014baad142c0ea8ab9ba6c2e5b254d3202c0a1`。
- 项目外中控已更新到 `e0b4a2d05aa444f3`，原每日回执/预算逐字保持，未额外触发canary。
- 本机271项回归、2项子测试通过；冻结包60项检查通过；check:workbench及登记/原技能175文件字节门禁通过。
- 线上24条准备失败标题均无任何原调用账本，显式重开后2次真实原生调用全部完成。
  三来源通过原CollectionService.retry续接准确旧阶段，4次真实筛选调用全部完成。
  不复位其他日期/错误/未知记录，不伪造采集、制作、采纳或发布。
- 2026-11-06 17:58:46恢复回执：AIHOT completed（抓取19、选中/新增16），
  NewsNow partial（抓取31、选中/新增1；覆盖补查后仍有第三方HTTP读取不完整），
  观猹 completed（抓取7、选中/新增5）。已有正常排期继续执行，包括18:00下一轮，未关闭自动采集。
- 正式雷达GET投影：AIHOT16、NewsNow1、观猹5、GitHub4、HN10、PH10；HN/PH均完整中文句子。
  无真实结果的来源保持空面板，不读旧缓存，不增加常驻失败提示。
- 线上只读浏览器验收4页：390x844模拟触控和1280x900桌面，分别覆盖工作台与雷达；
  原控件显示、列数、当天数据、无横向溢出、无脚本错误均通过。诊断POST仅在验收浏览器内拦截，未提交业务POST。
  工作台按原接口limit=6预览，雷达各10条；初版验收误把首页预览当完整列表，已纠正验收断言，未修改产品限制。
- 正式数据库inode保持；会话、回合、画像/历史、作品与附件数量保持，新增新闻22条。
  旧已审计unknown保持、不重放；恢复调用无新unknown。独立中控当天标题失败=0、本地来源失败=0，公网探测成功。
- 证据：final-tests.xml/log、frozen-tests.xml/log、acceptance.json、deploy.log、
  title-repair-preview/applied.json、collection-recovery-plan/receipts.json、model-recovery-audit.json、
  recovery-observation.json、live-browser.json/PNG、controller-install.log、delivery.json。
  浏览器为本机Edge自动化与模拟移动端，不冒称实体vivo/WebToApp实测。远端Actions未作为本轮通过证据。
