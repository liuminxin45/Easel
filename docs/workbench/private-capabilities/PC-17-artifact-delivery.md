# PC-17 附件上传、文件预览、下载与导出

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

**实际公共文件差异：** 见 [共通源码逐文件台账](../SHARED-SOURCE-CHANGES.md)，按 `PC-17` 查询实际关联路径、修改理由与同步核对点；纯复用或开发维护项不据此新增官方改动。

- **状态：** 已确认保留；类型：共通适配。
- **需求依据：** 用户要求手机文件可用、按需加载和保留原件，下载不能冒称实体设备已保存。 依据见下方原始规则/Spec；本卡不额外授予执行、采纳或发布权限。
- **能力范围：** 附件 ID/幂等注册、流式上传、受保护预览、限时下载凭证、HEAD/Range、导出与原件 SHA。
- **官方复用与必要差异：** 共用 uploads/outputs 服务、原 DownloadManager/DownloadLink 和 manual_publish；私有边界只处理身份、存储及授权。
- **不可破坏的合同：** 鉴权/CSRF 前不读文件；流式上限一致、取消清理；系统文件受保护；退出可撤销下载能力；不改原件，不缓存整库。

**接口与状态归属：** 原 /api/upload、/api/output/*、/api/media/* 与下载交付边界使用共享文件服务；附件/文件登记与限时下载资格归服务器，原件及 SHA 保留。

**私有入口／资源：** [easel_workbench/runtime/native_api.py](../../../easel_workbench/runtime/native_api.py)、[easel_workbench/http/downloads.py](../../../easel_workbench/http/downloads.py)、[easel_workbench/runtime/download_delivery.py](../../../easel_workbench/runtime/download_delivery.py)、[web/frontend/src/workbench/ui/nativeApi.ts](../../../web/frontend/src/workbench/ui/nativeApi.ts)

**官方复用／共通接缝：** [easel/web_services/uploads.py](../../../easel/web_services/uploads.py)、[easel/web_services/outputs.py](../../../easel/web_services/outputs.py)、[web/frontend/src/components/DownloadLink.tsx](../../../web/frontend/src/components/DownloadLink.tsx)

**验证入口：** [tests/test_workbench_native_upload_http.py](../../../tests/test_workbench_native_upload_http.py)、[tests/test_shared_upload_streaming.py](../../../tests/test_shared_upload_streaming.py)、[tests/test_workbench_download_delivery.py](../../../tests/test_workbench_download_delivery.py)

**需求与设计记录：** [docs/workbench/MOBILE-EXTENSION-UI-20261101.md](../../../docs/workbench/MOBILE-EXTENSION-UI-20261101.md)、[specs/easel-shared-runtime-20261104/spec.md](../../../specs/easel-shared-runtime-20261104/spec.md)

**后续维护：** 变更时先核对上述调用链与当前官方实现；优先共用、缩小上游补丁。同步维护本卡的范围、入口、共通差异及验证依据；被上游吸收时移除对应适配并更新登记状态。原方法、历史输入和交付证据不在本卡复制或改写。

**首版登记记录：** 2026-11-05 按业务源码 `1901f83` 建立首版；首版为只读盘点及文档登记，未新增启用能力，未逐项重新执行产品验收。本轮补充项按当前源码及各自验证记录另行核对，不将首版记录冒称本轮业务验收。
