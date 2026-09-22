# 门禁与限流 · 入站幂等

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B02.policy-gate · 入站幂等

- 层级：一级 B02 → 二级 policy-gate → 三级 `idempotency`
- 实现落点：`plugins/bot_unified_runtime/policy`、`plugins/bot_unified_runtime/domains/chat_reply/policy`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

防同一事件被重复处理。OneBot/SnowLuma 断线重连会重放事件，同一 `(adapter, bot_id, message_id)` 若被同一能力处理两次就会出现重复回复。本件对每个「事件键 + 能力」组合只放行一次，重复的出现返回「已见过」。它是入站侧幂等，与出站发送队列的 part 级幂等（B08）不是一回事。

## 怎么调用

两个后端同一接口 `claim(key, *, capability_id) -> bool`（True=首次、放行）：进程内 TTL 表 `plugins/bot_unified_runtime/domains/chat_reply/runtime/event_idempotency.py::EventIdempotencyTable`，SQLite 持久化表 `SqliteEventIdempotencyTable`（跨重启仍拦重放）。构造工厂 `build_event_idempotency_table(*, enabled, db_path, ttl_seconds, max_entries)`：`enabled=False` 返回 `None`（整链关闭）、`db_path` 非空走 SQLite、否则进程内。事件键由 `build_event_dedupe_key(message)` 拼成 `adapter|bot_id|message_id`；**无稳定 `message_id` 时返回空串，调用方据此跳过去重**（避免误伤）。

## 开关与参数

`ttl_seconds` 缺省 3600、`max_entries` 缺省 4096，过期与超容量自动回收（`_prune`）。构造入参由装配层从配置读出后传入；具体读自哪些 `bot_*` 键未确认——以根 `__init__.py` 装配点为准。SQLite 版时间戳用 wall clock 存储，使重启后 TTL 判定仍成立；写路径串行在本进程锁内，跨进程靠 SQLite 文件锁兜底。

## 失败时看到什么

本件不抛业务异常，只回答放行与否：`claim` 返回 False 即代表「这条已被同能力处理过」，调用方应跳过而非报错。空键恒返回 True（不去重）。注意语义细节：重复出现会**刷新时间戳**并拒绝，所以同一能力对同一事件的抑制会随重放滑动。

## 测试与验收

`tests/test_event_idempotency.py`（两后端同接口、空键跳过、TTL/容量回收）。与限流回滚的联动见 `tests/test_a18_gate_idempotency_rollback.py`。
