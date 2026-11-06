# PC-01 工作台访问、身份与请求安全

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

**实际公共文件差异：** 见 [共通源码逐文件台账](../SHARED-SOURCE-CHANGES.md)，按 `PC-01` 查询实际关联路径、修改理由与同步核对点；纯复用或开发维护项不据此新增官方改动。

- **状态：** 已确认保留；类型：宿主适配。
- **需求依据：** 用户通过 Tailscale 暴露本机工作台，由 WebToApp/PC 浏览器登录使用；保留现有身份和授权。 依据见下方原始规则/Spec；本卡不额外授予执行、采纳或发布权限。
- **能力范围：** TOTP 登录、服务器会话、同源/CSRF、操作身份与准入；Tailscale 仅提供网络暴露，不承载业务。
- **官方复用与必要差异：** 复用 Easel 页面和普通 API；认证策略集中在宿主边界，不改变原独立入口的默认认证方式。
- **不可破坏的合同：** 鉴权失败不执行写入；401/退出不清草稿；不能把平台账号登录或网络可达当作发布授权。
- **登录会话：** 按用户要求不设置会话数量上限；已认证访问续期七天，续期写入和 Cookie 刷新最多每分钟一次，附加一分钟宽限避免过早过期。旧会话缺少访问时间，升级时最多保留七天及一分钟缓冲，访问后转为新规则。登录时清理过期会话，保留 TOTP 防重放、失败频率限制、同源和 CSRF 检查，不因数量注销设备。

**接口与状态归属：** 接口由 auth_forms、auth_totp、api_security 及 toolbox_server 统一处理；登录/鉴权状态归服务器，客户端不保存可替代服务器授权的业务主库。

**私有入口／资源：** [easel_workbench/runtime/auth_totp.py](../../../easel_workbench/runtime/auth_totp.py)、[easel_workbench/runtime/auth_forms.py](../../../easel_workbench/runtime/auth_forms.py)、[easel_workbench/runtime/api_security.py](../../../easel_workbench/runtime/api_security.py)、[easel_workbench/runtime/toolbox_server.py](../../../easel_workbench/runtime/toolbox_server.py)

**官方复用／共通接缝：** [web/frontend/src/App.tsx](../../../web/frontend/src/App.tsx)、[web/frontend/src/lib/api.ts](../../../web/frontend/src/lib/api.ts)

**验证入口：** [tests/test_workbench_chat_business.py](../../../tests/test_workbench_chat_business.py)、[tests/test_workbench_native_upload_http.py](../../../tests/test_workbench_native_upload_http.py)

**需求与设计记录：** [AGENTS.md](../../../AGENTS.md)、[specs/private-workbench-architecture/spec.md](../../../specs/private-workbench-architecture/spec.md)

**后续维护：** 变更时先核对上述调用链与当前官方实现；优先共用、缩小上游补丁。同步维护本卡的范围、入口、共通差异及验证依据；被上游吸收时移除对应适配并更新登记状态。原方法、历史输入和交付证据不在本卡复制或改写。

**首版登记记录：** 2026-11-05 按业务源码 `1901f83` 建立首版；首版为只读盘点及文档登记，未新增启用能力，未逐项重新执行产品验收。本轮补充项按当前源码及各自验证记录另行核对，不将首版记录冒称本轮业务验收。
