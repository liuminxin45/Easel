# PC-12 准确作品版本、修改、采纳与反馈

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

- **状态：** 已确认保留；类型：私有业务。
- **需求依据：** 用户要求制作→修改→采纳/不采纳形成闭环，保留准确版本、父版、原始意见和授权。 依据见下方原始规则/Spec；本卡不额外授予执行、采纳或发布权限。
- **能力范围：** 成品接收、文件登记、版本/父版、独立检查、采纳/不采纳、仅记录本版反馈和准确继续制作链接。
- **官方复用与必要差异：** 原 OutputsPage、ChatPage、Drawer/DownloadLink；私有操作放原详情扩展区，不替代内容库。
- **不可破坏的合同：** 只接收本回合准确产物，修改另存父版；反馈不自动制作，采纳不等于发布；制作状态与交付事实分开。附加完成选项的授权差异另列 U-01，不以本卡一并批准。

**接口与状态归属：** 接口沿 chat_business、WorkVersions 与现有作品/反馈操作；WorkVersions 使用调用方的 store、work_store 及事务保存准确版本关联，不复制作品主库。

**私有入口／资源：** [easel_workbench/chat_business.py](../../../easel_workbench/chat_business.py)、[easel_workbench/features/works/products.py](../../../easel_workbench/features/works/products.py)、[easel_workbench/features/works/versions.py](../../../easel_workbench/features/works/versions.py)、[web/frontend/src/workbench/ui/VersionOperations.tsx](../../../web/frontend/src/workbench/ui/VersionOperations.tsx)

**官方复用／共通接缝：** [web/frontend/src/components/OutputsPage.tsx](../../../web/frontend/src/components/OutputsPage.tsx)、[web/frontend/src/components/ChatPage.tsx](../../../web/frontend/src/components/ChatPage.tsx)、[web/frontend/src/components/Drawer.tsx](../../../web/frontend/src/components/Drawer.tsx)

**验证入口：** [tests/test_workbench_chat_business.py](../../../tests/test_workbench_chat_business.py)、[tests/test_workbench_version_view.py](../../../tests/test_workbench_version_view.py)、[tests/test_workbench_chat_products.py](../../../tests/test_workbench_chat_products.py)

**需求与设计记录：** [specs/native-product-experience/spec.md](../../../specs/native-product-experience/spec.md)、[docs/workbench/NATIVE-PRODUCT-EXPERIENCE-20261102.md](../../../docs/workbench/NATIVE-PRODUCT-EXPERIENCE-20261102.md)

**后续维护：** 变更时先核对上述调用链与当前官方实现；优先共用、缩小上游补丁。同步维护本卡的范围、入口、共通差异及验证依据；被上游吸收时移除对应适配并更新登记状态。原方法、历史输入和交付证据不在本卡复制或改写。

**登记记录：** 2026-11-05 按业务源码 `1901f83` 建立首版；本次只读盘点及文档登记，未新增启用能力，未逐项重新执行产品验收。
