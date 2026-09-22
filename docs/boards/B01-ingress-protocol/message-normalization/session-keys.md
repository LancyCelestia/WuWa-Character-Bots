# 消息归一与身份中央件 · 会话键派生

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B01.message-normalization · 会话键派生

- 层级：一级 B01 → 二级 message-normalization → 三级 `session-keys`
- 实现落点：`plugins/bot_unified_runtime/domains/core/session_keys.py`、`plugins/bot_unified_runtime/domains/core/text_boundary.py`、`plugins/bot_unified_runtime/domains/core/board_placement.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

全仓会话键形态的唯一判据与唯一构造器。给定一个字符串键，它回答三件事：这是不是群会话、群号与发送者段分别是什么、以及反过来「按群号+用户号把键拼出来」。读写共用同一份实现，因此不可能再出现「写侧一种形态、读侧另一种形态」的分裂。

## 怎么调用

真身 `domains/core/session_keys.py`（纯函数件，零 I/O、零 config 依赖，任意域可直接 import；它不是登记能力）：

- `parse_session_key(value) -> SessionKey`：唯一判据入口，其余函数都从这里派生。返回冻结 dataclass，字段 `raw/normalized/kind/form/group_id/user_id`，属性 `is_group`。
- `is_group_session_key(value) -> bool`、`group_id_of_session_key(value) -> str`（非群键返回空串，调用方据此判无数据，绝不退化成全表扫）。
- 构造侧：`build_session_key(group_id, user_id)`（逐字镜像 OneBot V11 `get_session_id()`：群=`group_<gid>_<uid>`，uid 空→`unknown`；私聊=`<uid>`）、`private_session_key(user_id)`、`group_session_prefix(group_id)`（读侧 LIKE 前缀）。
- `normalize_session_key(value)`：字符串化 + 去两端空白。

## 开关与参数

没有开关、没有配置键、不可热改——它是一张判据表，行为由常量决定：`GROUP_SESSION_PREFIX="group_"`（权威形）、`LEGACY_GROUP_SCHEME="group:"`（历史/合成/出站形）、`UNKNOWN_SENDER="unknown"`（缺段兜底）、形态枚举 `FORM_*` 与会话种类 `KIND_*`。

口径要点（钉死在 `tests/test_session_keys_central.py`）：

- 下划线权威形必须有群号**且**有发送者段，两段都不含内部空白；半截键与夹换行的脏键不判群。
- 冒号形按构造即「整群」语义：判群、无发送者段。
- 前缀识别大小写不敏感、先剥两端空白。这是相对旧判据的**有意放宽**：没有任何适配器产出大写或带空白的键，所以对全部真实输入逐字节等价，放宽的价值是让两个消费方共用同一份判据。
- 私聊裸键（OneBot `str(user_id)`、mail 发件人 id、console 频道键、`channel_`/`guild_`/`friend_` 等）一律判私聊。

## 失败时看到什么

它自己不失败，也不抛：任何无法归类的输入都落到 `KIND_UNKNOWN` + `FORM_OTHER`，语义是「不是群」，即 fail-closed。真正的历史故障形态是「静默零报错却恒不命中」（群摘要读零行那一族），现在的对策是接线锁 `tests/test_session_keys_wiring.py`——判据存在不等于有人用它，消费方绕开中央件会被该门点名。

手上已经有 `IncomingMessage` 时不要用本件判会话类型：走契约字段 `message.session_type` / `message.group_id`（参考实现 `domains/chat_reply/policy/rate_limit.py:is_group_session`）。

## 测试与验收

`tests/test_session_keys_central.py`（判据与 falsy 钉死）、`tests/test_session_keys_wiring.py`（消费方必须走中央件）。真机无独立条目：它的验收是全量门禁绿 + 群摘要、私聊名单门、反应表情等历史咬人点不再复现。
