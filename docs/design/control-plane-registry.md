# 控制面产品注册与执行快照契约

## 状态与边界

当前是已批准计划的增量，不是全量产品注册完成。`/api/v1/protocol` 保持
`subfeatures_complete=false`、`reload_drain=false`。路由、内部命令及下表细分项
由 `domains/ops/features/feature_catalog.py` 显式投影，运行时不扫描源码。
本批组合测试：`test_runtime_subfeatures + test_runtime_feature_gate + test_control_plane_services + test_feature_store_integrity + test_control_plane_v1 + test_sqlite_feature_store + test_poke_unified_reaction_b10` → **183 passed**；全量结果以 `COMPACT-CHECKPOINT.md` 顶部为准。

## Service 与协议

```mermaid
flowchart TD
    API[REST /api/v1/features] --> Service[FeatureControlService]
    Command[/bot feature] --> Service
    Service --> Store[SQLiteFeatureStateStore / 审计 / 图修订CAS]
    Store --> Gate[ProductFeatureGate]
    Gate --> Snapshot[异步获取整图不可变快照]
    Snapshot --> Ingress[入站富化与已登记旁路]
    Gate --> Pipeline[Pipeline 能力级执行门（层 1）]
    Gate --> Invoker[CapabilityInvoker 执行门面（层 2）]
```

- ID 不随显示名变化；alias、父级和依赖由现有注册表校验。
- Descriptor 新增 `implementation_ref`（源码相对路径#符号）、`reload_strategy`（本批为 `gate`）、`privacy_level`（`internal`），不向客户端返回绝对路径。
- `FeatureKind` 扩展 `sub_feature/auto_reply/config/trace_stage/model_provider/model_channel/model`；**有枚举不等于该类所有实际资源已登记**。
- 修改只允许 super_admin。SQLite 写操作同时提供 `expected_version` 与 `expected_revision`；冲突返回 409，不静默覆盖。
- 父级关闭时后代有效关闭；依赖失效继续显示 `blocked_by`。核心恢复、审计与安全边界不可关闭。
- 同一消息的预处理只读一次完整状态，SQLite 查询通过 `asyncio.to_thread` 离开事件循环，快照用 `MappingProxyType` 保证不可修改。
- 旧事件保留旧快照，新事件看到新配置；不同 SQLite 服务实例的下一快照能看到更改。Pipeline 后续能力级门禁仍单独检查。
- 快照源故障时细分项 fail-closed；核心恢复服务仍受自身权限保护。没有复用旧快照绕过故障。
- `gate` 只阻止新调用，不等于资源 drain/reload；没有假造 running_tasks 或 reload_status。

## 层 2 执行门（中央 `CapabilityInvoker`，2026-09-23/24 起开始执法；改动未 commit，重启后装配生效）

旧口径「feature 门只在层 1（`pipeline._prepare`）执法」已作废：绕过 pipeline 直呼
`runtime/capability_protocols.py::default_invoker` 的 `invoke()` 曾能静默穿过这道关
（AGENTS 台账 #49 的「在册未执法」项）。现 `CapabilityInvoker.invoke` 在「未登记能力」判定
之后、角色门之前插入层 2 门，门序与层 1 对齐。三条边界缺一不可，按此口径叙述：

- **只对在册受门者执法**：是否受门的答案是唯一投影
  `runtime/capability_protocols.py::gate_feature_bindings()`（`gate_scoped=True` 的能力才进这道门）。
- **未受门 pass-through**：绑定表查不到 ⇒ 放行到后续门，**绝不**照抄层 1 `check_capability`
  的「未登记 → `feature_unregistered` → 拒绝」语义——那会把今天真在跑的直呼型能力当场挡死
  （实算出处 `.superpowers/sdd/2026-09-24-central-dispatch/SEAT-S43.md` §1.3；受门/未受门枚数以
  `gate_feature_bindings()` 现算为准，本文不手写计数）。
- **读不到状态 fail-closed**：谓词抛异常 ⇒ 拒绝，原因码 `feature_state_unavailable`，终态 `DENIED`、
  `via="feature_gate"`，并照常走审计 emit——与层 1 `_prepare` 同口径。

单一真身：判定住在 `domains/ops/features/feature_gate.py::ProductFeatureGate.check_capability`，
历史签名 `__call__(message, capability_id)` 已降为纯转发（真身从不读 message），层 1/层 2 共用同一份
门序、禁第二套。恢复类旁路 `RECOVERY_CAPABILITIES` 的集合真身唯一住 `domains/ops/features/feature_catalog.py`，
层 2 不抄副本。注入口唯一：`runtime/capability_protocols.py::attach_default_feature_gate(predicate)`，
装配在根 `__init__.py`（`ProductFeatureGate` 构造之后一行）；构造形参 `feature_gate` 缺省 `None`＝不执法＝
该波之前的现网逐字节现状。

**执法面现状（与上段同读，防止把"机制存在"读成"已对所有能力执法"）**：今天绕过 pipeline 直呼
`invoke()` 的能力全部未受门 ⇒ 层 2 新增执法面**恰好为空**、行为逐字节中性；它的价值是把「未来任何
直呼入口自动受门」变成结构事实。锁：`tests/test_feature_gate_layer2.py`（pass-through 反例、
fail-closed、门序先于角色门、拒绝入审计、`__call__` 纯转发、层 2 不抄门与恢复名单、根装配真谓词）。

**副作用如实记（判据来自两处调用点：`orchestrated_command` 走 `default_invoker().invoke`、pipeline 侧
`_prepare` 也问同一道门，未做运行时测量）**：**受门且经 pipeline** 的能力同一判定会被问两次（真身只读、
判定幂等，语义不冲突，代价是多一次状态读）。今天直呼面皆未受门，故该双问不产生现行行为差异。

## 已接入的细分项

| 稳定 ID | 父节点 | 功能 | 执行位置 |
|---|---|---|---|
| `bot.plugin.poke.reply` | `bot.plugin.poke` | 戳一戳文字回复 | `__init__.py#_handle_poke_notice` |
| `bot.plugin.poke.poke_back` | `bot.plugin.poke` | 戳一戳反戳 | `__init__.py#_handle_poke_notice` |
| `bot.ingress.file_read` | `bot.ingress` | 入站文件内容读取 | `__init__.py#_incoming_from_nonebot_event` |
| `bot.ingress.audio_transcode` | `bot.ingress` | 语音段预转码 | `__init__.py#_transcode_record_segments` |
| `bot.ingress.telegram_media` | `bot.ingress` | Telegram 媒体文件富化 | `__init__.py#_handle_chat` |
| `bot.ingress.reply_lookup` | `bot.ingress` | 引用链远程反查 | `__init__.py#_handle_chat` |
| `bot.plugin.chat.recent_image` | `bot.plugin.chat` | 最近图片注入（群聊/私聊） | `__init__.py#_handle_chat` |
| `bot.plugin.chat.forward_lookup` | `bot.plugin.chat` | 合并转发内容反查 | `__init__.py#_handle_chat` |
| `bot.plugin.chat.video_preprocess` | `bot.plugin.chat` | 视频理解预处理 | `__init__.py#_handle_chat` |
| `bot.plugin.chat.parrot` | `bot.plugin.chat` | 群聊复读自动回应 | `__init__.py#_handle_chat` |
| `bot.plugin.affinity.passive` | `bot.plugin.affinity` | 被动好感画像与心情感知 | `__init__.py#_handle_chat` |
| `bot.plugin.chat.reactions.receive` | `bot.plugin.chat.reactions` | 接收表情回应上下文 | `__init__.py#_handle_msg_emoji_like_notice` |
| `bot.plugin.chat.reactions.emotion` | `bot.plugin.chat.reactions` | 情绪触发表情回应 | `__init__.py#_handle_chat` |
| `bot.plugin.chat.reactions.after_reply` | `bot.plugin.chat.reactions` | 回复后表情回应 | `__init__.py#_handle_chat` |
| `bot.plugin.meme_library.auto_absorb` | `bot.plugin.meme_library` | 群图自动收库 | `__init__.py#_handle_meme_absorb` |

### 行为限定

- 文件读取关闭时入站归一不调用 `read_supported_file`，不代表其他文件入口已经全部受控。
- 引用远程反查关闭时仍保留事件自带的本地引用信息；语音、Telegram 媒体富化可独立关闭。
- 群图自动收库关闭时不会调用收库处理器。被动好感、复读、视频预处理和表情的接收/情绪/回复后触发各自受控。
- 戳一戳父能力 `bot.poke` 已补登记，避免 Pipeline 报 `feature_unregistered`；父节点关闭时连冷却登记和反戳都不进入。reply/poke_back 两个子项控制实际输出分支。
- 原有 `BOT_POKE_*`、`BOT_REACTIONS_*` 等配置、概率、冷却及权限仍有效；树开关不能绕过它们。反戳默认仍受原配置默认关闭约束。
- 反戳/主动贴表情仍有直接平台 API 路径：**尚未完成统一 Review/SendQueue 收编**。不能将本批标成戳一戳全部验收。

## WebUI 与指令适配

- `GET /api/v1/features?kind=sub_feature` 查机器目录；`/features/tree` 查层级；不硬编码中文名。
- 先 GET 状态取版本，再 POST enable/disable/reset/preview；reset 恢复继承，并非强制开启。
- 例：`/bot feature disable bot.ingress.file_read`、`/bot feature reset bot.ingress.file_read`。
- `/bot feature disable bot.plugin.poke.reply` 只关闭文字回复，不自动启用反戳。
- `implementation_ref` 是文档定位信息，不是客户端可执行入口；禁止由此构造任意导入/路径读写。

## 下一步缺口

全量命令/help/文档/定时任务双向登记、所有子功能 config_keys 元数据、运行任务计数、资源 drain/reload、统一 Dispatcher 与全部出站门禁仍未完成。不得把纯内部实现函数机械包装成开关。
