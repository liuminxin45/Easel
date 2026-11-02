# 官方界面唯一实现整改

Spec：[official-ui-reuse-20261102](../../specs/official-ui-reuse-20261102/spec.md)。
官方参考 `0f43dc98277eac85fb48952878acad349731d3fc`；私有起点 main/d19d60a。
本记录区分源码验证、准确冻结包验收和正式部署，不把原审计或旧版本验收改称新组合结果。

## 实现与删除清单

| 审计项 | 当前实现 |
|---|---|
| F1 技能协议/依赖 | 原 web/app.py 的七项需求表、解析与脱敏函数移到 easel/web_services/skills.py，两个入口立即共用；删除私有六项映射，保留冻结版本附加字段 |
| F2 技能运行 | 原配置/运行/执行/结果区恢复。默认原函数不变；宿主通过 services 接原 SessionRuntime、submit/plan/last，同回执unknown不重发；真实QuestionCards仅实际问题存在时出现 |
| F3 新建画像 | 原四步 OnboardingWizard；官方六文件基线生成器抽到单一profiles服务，版本画像与平台/记忆/原表单文档在同一事务创建，返回stable ID，不自动执行额外AI增强 |
| F4 聊天空态 | 恢复原Easel品牌、原图标、默认文案及可用建议，只集中解析不可变资产URL |
| F5/F6 移动 | 删除顶部占位横栏，保留悬浮按钮+原侧栏；取消drawer-header粗暴flex覆盖，关闭按钮仍为原结构 |
| F7 列表 | 公共样式限高删除；已有listMaxHeight通用可选参数只由宿主明确传入 |
| C1 私有弹窗 | 从原SkillDrawer最小提取Drawer，官方与版本/经验/记录/确认直接用同一个壳；common只保留history/focus生命周期适配 |
| C2 默认反馈 | 原入口恢复原save-note/desc/notice-error及文案，私有反馈仅由明确宿主端口启用，真实错误可见 |
| C3 公共结构 | Ideas/Trends/Dashboard JSX回到原页面；删除IdeasView、TrendsView、DashboardNews、newsResources以及Sidebar未用品牌替换接口 |

已删除的平行外壳：common.Modal、ew-dialog、独立sheet及其样式，所有私有详情调用改用同一官方Drawer。
Drawer的header/body/关闭控件采用原结构和原CSS，只有通用ARIA及组合接口；无私有依赖。
嵌套抽屉的宿主适配只管理Back、背景inert、焦点与portal所有权，保留原生dialog/设置菜单自己的行为。

## 保存与执行边界

技能配置仍走原/api/env协议，私有服务使用同一官方白名单和值校验，凭据进入加密配置修订；
不写生产.env、不存入浏览器草稿，不影响旧会话已捕获修订。
私有制作先由/api/chat/plan返回真实冻结方案，用户看到原输入/技能/画像后确认，才提交同session/turn/token。
关闭、改输入或改动作使未提交预览失效；模型结果与作品接收hook未核对不能当作成功或开启重放。
执行订阅属于应用，同一技能重开只读恢复；实际原生授权问题复用原QuestionCards，不增加常驻操作栏。

原技能、原始资源、历史ID/父版/意见、冻结输入、回执及采纳/交付授权继续保留。
自写五字段画像草稿仍保存原件，不猜测映射到新向导字段。原作者方法/内容生产技能正文未因UI修改。

## 当前验证

- 综合后端216项通过：共享协议/画像文档回滚/配置修订、原HTTP、会话业务、架构和技能策略/命令。
- 原Easel独立环境95项设置/供应商/思考配置回归通过。
- 全前端408项通过；TypeScript与两项源码审计通过。
- 另增3项准入反例检查：拒绝宿主隐藏/替换技能区域、重写默认聊天空态、重建私有Modal与向公共列表写入私有限高；真实服务/业务内容槽仍可通过。该规则进入原基座审计和构建链路。
- 独立编译组件在5尺寸×明暗主题50项可信触摸检查通过；真实Edge嵌套Drawer焦点检查通过。
  这些局部装配证据不能代替最终冻结包的全页、闭环和线上验收。
- 首次后端报告的3+1个旧测试直接索引已清理的_tasks引发竞态；改为真实events尾流并保持原结果断言，未改模型调度来迁就测试。
- 初次新配置测试只填key未填官方要求的baseURL，原规则正确拒绝就绪；已补全TEMP输入，未放宽注册表。
- 原构建已有大于500KB的打包提示保留，不冒称零警告。

源码/原始报告位于 `.local/workbench-validation/official-ui-reuse-20261102/`，
前端日志位于 `.local/workbench-validation/official-shell-implementation-20261102/`，
嵌套焦点证据位于 `.local/workbench-validation/official-shell-focus-20261102/`。
尚待最终准确冻结包的全页/弹窗/闭环/恢复验收以及正式部署；真实AI、平台发布和实体vivo不由模拟验收代填。

## 冻结前恢复与配置交错修复

只读复核发现：unknown后后台已完成的技能槽可能一直submitted并拒绝新输入；关闭重开现先只读核对准确终态，
收到完成回执才释放原槽，unknown或登记hook未核对仍禁止重发。
又以确定性交错复现旧resume的慢回执清掉新回合权限问题；现在清题/重连与完成写回都核对准确session/turn所有权。
原false探针保留，新2项真实store交错回归通过。
技能详情现从同一不可变配置快照产生脱敏字段和configuration_revision，保存不再静默GET最新父修订；
R8表单遇到R9更改仍409并保留当前输入。后端原协议/修订/架构相关76项与新增恢复、陈旧保存测试通过，
与之前216项重叠，不相加冒称独立测试。

详情重开与保存回执也按owner读取序号隔离：旧详情/旧保存迟到不能覆盖当前可见父修订，
三项确定性交错先红后绿。部署预检另发现两个未改采集策略文件被Windows检出为CRLF，
已核对当前Git内容与已发布原件一致后恢复原LF字节，并在.gitattributes逐文件固定；
原策略SHA和历史unknown回执不变，33项保留证据校验回归通过。
