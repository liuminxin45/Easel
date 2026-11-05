# PC-11 版本化画像、素材与账号绑定

[返回私有能力登记表](../PRIVATE-CAPABILITIES.md)

**实际公共文件差异：** 见 [共通源码逐文件台账](../SHARED-SOURCE-CHANGES.md)，按 `PC-11` 查询实际关联路径、修改理由与同步核对点；纯复用或开发维护项不据此新增官方改动。

- **状态：** 已确认保留；类型：私有业务。
- **需求依据：** 用户要求保留画像身份、修订、素材与账号关联，并直接使用官方创建/编辑/删除/增强能力。 依据见下方原始规则/Spec；本卡不额外授予执行、采纳或发布权限。
- **能力范围：** 画像稳定 ID、修订/历史、素材绑定、账号归属、默认保护、明确导入及后台增强的安全存储。
- **官方复用与必要差异：** 原 ProfilePage、OnboardingWizard、画像基线/增强及删除用例；私有层提供存储和 revision CAS。
- **不可破坏的合同：** 增强不覆盖手工新修订；停用画像不用于新会话但历史可读；配置冻结，API 仅聊天不执行本机增强；不恢复私有技能 pins 管理。

**接口与状态归属：** 原 /api/personas、/api/persona/*、/api/profile/build 由 NativeApi 适配；ProfileService 管理既有画像/素材修订与归属记录，历史会话继续引用准确版本。

**私有入口／资源：** [easel_workbench/features/profiles/service.py](../../../easel_workbench/features/profiles/service.py)、[easel_workbench/runtime/native_api.py](../../../easel_workbench/runtime/native_api.py)、[web/frontend/src/workbench/ui/nativeProfiles.tsx](../../../web/frontend/src/workbench/ui/nativeProfiles.tsx)

**官方复用／共通接缝：** [easel/web_services/profiles.py](../../../easel/web_services/profiles.py)、[web/frontend/src/components/ProfilePage.tsx](../../../web/frontend/src/components/ProfilePage.tsx)、[web/frontend/src/components/OnboardingWizard.tsx](../../../web/frontend/src/components/OnboardingWizard.tsx)

**验证入口：** [tests/test_workbench_profile_enhancement.py](../../../tests/test_workbench_profile_enhancement.py)、[tests/test_workbench_native_deletion.py](../../../tests/test_workbench_native_deletion.py)、[tests/frontend/profileRevisions.test.mjs](../../../tests/frontend/profileRevisions.test.mjs)

**需求与设计记录：** [specs/easel-shared-runtime-20261104/spec.md](../../../specs/easel-shared-runtime-20261104/spec.md)、[docs/workbench/EASEL-REUSE-DELIVERY-20261105.md](../../../docs/workbench/EASEL-REUSE-DELIVERY-20261105.md)

**后续维护：** 变更时先核对上述调用链与当前官方实现；优先共用、缩小上游补丁。同步维护本卡的范围、入口、共通差异及验证依据；被上游吸收时移除对应适配并更新登记状态。原方法、历史输入和交付证据不在本卡复制或改写。

**首版登记记录：** 2026-11-05 按业务源码 `1901f83` 建立首版；首版为只读盘点及文档登记，未新增启用能力，未逐项重新执行产品验收。本轮补充项按当前源码及各自验证记录另行核对，不将首版记录冒称本轮业务验收。
