# 私有架构第一批：基线、叶子合同与下载 HTTP 边界

Spec：`private-workbench-architecture`，方案见 `specs/private-workbench-architecture/spec.md`。

用户已授权按方案分批实施。当前完成 P0 的可复核源码基线和 P1 的基础合同/下载试点；会话、作品、技能、画像、采集、交付、安装、进程及前端归组仍按后续切片推进，不据此宣称整套架构已迁完。

## 本批实现

| 唯一实现 | 原入口兼容 | 当前调用关系 |
|---|---|---|
| `contracts/values.py` 的 ident/text/pack | `runtime/toolbox_store.py` 导出相同函数对象 | 37 个既有调用者直接使用叶子合同；真实 Toolbox 类依赖保留 |
| `contracts/legacy_jobs.py` 的 ACTIVE/KINDS | toolbox_store 导出相同集合对象 | 固定线程历史状态保持，不混入原生回合状态 |
| `contracts/media_paths.py` | native_api 导出相同分类函数与正则对象 | 原生媒体路由与下载校验共同调用；下载校验不再加载 native API |
| `http/downloads.py` | toolbox_server 保留 download_request 导出与原两个 HTTP 地址 | 宿主注入原文件处理回调；HTTP 解析从总路由移出 |
| `http/response_lifecycle.py` | toolbox_server 保留 close_read_response 导出 | HEAD、签发前探测及 ZIP 的响应清理继续复用 |

纯合同包不加载存储、Web 或引擎模块。数据库、表、业务状态、序列化/签名算法、冻结技能、公共 Easel 代码及下载控件未变更。

认证和准入仍由宿主执行；下载接口仍在检查目标文件后签发五分钟、绑定目标/文件名/原会话且可撤销的能力。实际文件读取继续走原处理器，保留 HEAD、Range、CSP、ZIP 和原件字节语义。

## P0 如何继续使用

`scripts/audit_workbench_private_architecture.py` 只读源码，可输出：

- 全部私有 Python 模块的 SHA、符号范围、静态调用者及导入；不包含 vendor。
- SQL 写入/建表的所属符号；动态 SQL 明确标记待核对，不伪装成完整运行时写入图。
- 字符串/未解析动态 import、七个角色声明及六个动态角色目标。
- `__file__`/相邻资源引用与已迁移边界违规。

它是维护证据，不被产品加载，不是另一份技能注册或任务调度器。复杂业务域和兼容代码仍按切片核对，清单不构成删除授权。

```powershell
# 从准确旧版本重建基线
pwsh -NoProfile -Command "& '.runtime/workbench-python/Scripts/python.exe' scripts/audit_workbench_private_architecture.py --revision 88a7cc9185976065fe6b2b9af2652ccf9eafc31d --output .local/workbench-validation/private-architecture-p0p1-20261101/baseline-inventory.json"

# 检查当前已迁移边界
pwsh -NoProfile -Command "& '.runtime/workbench-python/Scripts/python.exe' scripts/audit_workbench_private_architecture.py --check --output .local/workbench-validation/private-architecture-p0p1-20261101/current-inventory.json"
```

本批新规则在旧源码上报告的旧式依赖仅作为对照，不表示新增生产故障；当前 P1 范围的违规为零。检查包含局部 import、动态 import、别名属性和应失败反例，没有放宽原上游边界检查。

## 已执行验证

- 原架构、技能策略/命令、下载和媒体路由：133 项通过。
- 新纯合同语义、原导出对象、叶子加载及依赖反例：43 项通过。
- 会话/作品/中断/响应性、设置、原生 API/完成/归属/核对及迁移审计：148 项通过。
- 同一原下载 HTTP 合同对照旧源码 88a7cc9 与当前 P1：两侧各 45 项，合计 90 项通过。
- 53 项准确旧源码合同对照通过：错误、Unicode JSON、路径分类、签名链接和撤销判断一致。
- 38 个既有模块的业务 AST 对照保持一致：仅移除 import 与本批明确提取的定义后比较；总路由的提取另由 HTTP 前后合同验证。
- 新的私有边界已接入原 `test_workbench_architecture.py`；最后一次原架构与新增私有依赖检查共 54 项通过。
- 真实 Windows Edge 桌面与模拟移动视口通过：画廊、放大图、正文、内容库、中断产物及版本 ZIP 下载；匿名签名链接、未签名拒绝和原件 SHA 均核对。

浏览器使用不可变前端 `native-mobile-ui-download-20261101093213`，SHA256 `e7b9d51a293db55978187c8dc5818daebb7830c170a2848d90792a6996dc5f23`，后端是当前工作目录源码。仅证明本批源码与该前端的 TEMP 联通，不代表新后端已冻结发布或实体手机下载完成。

模型执行使用现有 TEMP 合成适配器；真实模型调用、平台写入和生产数据访问为零。测试中的 FastAPI/Python 弃用警告如实保留，不与功能失败混淆。

证据位于 `.local/workbench-validation/private-architecture-p0p1-20261101/`：`baseline-inventory.json`、`current-inventory.json`、`contract-parity.json`、`service-regressions.xml`、`http-parity.xml` 及 `download-browser/report.json`。

## 集成与发布边界

本批只交付私有后端结构及相关审查资料；并行移动 UI 由其原会话负责，不纳入本批提交。当前活动后端指针与生产进程未在本批切换。新后端的冻结配对、空闲/队列/未知回执核对和上线按项目既有流程由总调度统一进行，不能把上述源码验收当成正式上线证据。
