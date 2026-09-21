# U17-CAMPUS-WIRE：校园自动转发收编进中央决策/分发管线（2026-09-20）

> **交接纪律声明（AGENTS 铁律 5）**：本席**未 commit、未重启 bot、生产零变化**；下文一切
> 「已完成/测试通过」均附**可复跑命令 + 实跑输出原文**，否则一律按未完成记账。
> 席位：U17-CAMPUS-WIRE（后端 Python，只碰 campus 域 + 注册册 + 出站登记表 campus 一条）。
> 禁令遵守：无子代理、无 git 写操作、无 `--write`（verify_hashes/doc_sync/command_catalog 全 --check
> 或未触碰）、无真实发送/重启/真实 LLM 调用、未读 `.env` 明文值、未写 `ChatBot_Runtime/`。
> 基线：HEAD=`56d1461`（分支 `heads/v0.0.1-alpha.2`，工作树多会话共享、大量未提交改动）。

## §0 现状复核（动手前重新 grep 的坐标，行号会漂）

### §0.1 旁路本体与触发点（复核结论）

| 项 | 复核坐标 | 事实 |
|---|---|---|
| 旁路转发决策 | `plugins/bot_unified_runtime/domains/assistant/campus/campus.py:94-172` | `CampusForwardService.record()` 自建 `SendRequest`（`_build_forward_request` :137-172，capability_id=`bot.campus_forward`、`request_id=campus-fwd-<mid>`、`dedupe_key=campus_fwd:<mid>`、`cooldown_key=campus_fwd:<notify_qq>`、`audit_tags=["campus","forward"]`） |
| 触发 matcher | `plugins/bot_unified_runtime/__init__.py:4997-4999`（`campus_record_matcher = on_message(rule=_is_campus_group_message, priority=8, block=False)`） | 在 `_register_nonebot_handlers()`（:3544 起）内 |
| 绕过中央的出站 | `plugins/bot_unified_runtime/__init__.py:5019-5029` | `record()` 经 `asyncio.to_thread` 后**直接** `send_queue.submit(request)` —— 绕过 `_prepare` 门禁/幂等 claim/decision shadow/review |
| 装配段 | `plugins/bot_unified_runtime/__init__.py:3669-3686` | 三重门任一空（含 `notify_qq`）= 不装配 `campus_service` |

### §0.2 旧路径两件的归属判定（**只记归属，不动它们**）

- `plugins/bot_unified_runtime/capabilities/campus.py` → **退役垫片（v21r2 重组 W12 薄壳）**，
  纯 `import *` + 两个私有名显式转出，真身=`domains/assistant/campus/campus.py`。
- `plugins/bot_unified_runtime/sources/campus_store.py` → **同类垫片**，真身=`domains/assistant/campus/campus_store.py`。
- 佐证：两文件首行 docstring 自述 "Compat shim: moved to …"；无第二真身、无双写。
- 本席不改垫片；`tests/test_campus_digest.py` 现有 import 走垫片旧路径（能跑，因为垫片是活引用），
  本席把测试 import 收敛到**真身新路径**（垫片陷阱惯例：monkeypatch 必须打真身，见方案书 §3.1）。

### §0.3 中央入口与「异会话投递」既有表达（关键取证）

- 中央入口：`domains/chat_reply/runtime/ingress.py::IngressGateway.from_event` →（根 `__init__.py:2512`
  `_run_capability_through_pipeline`）→ `pipeline.handle/handle_async` → `_prepare`（feature_gate/
  runtime 暂停/role/policy/quiet_hours/reply_budget/rate_limit/幂等 claim）→ 能力 → `_complete`
  （review → render → 合并转发判定 → `SendRequest` → `send_queue.submit`）。
- **`_complete` 的目标推导是硬编码的**（`pipeline.py:807-835`）：`session_id=message.session_id`、
  `target_scope=decision.target_scope`（=`message.session_type`，:666）、
  `target_id=message.group_id or message.sender_id`（:811）、`bot_id=message.bot_id`、
  `adapter=message.adapter`、`persona_profile_id=_resolve_persona_profile_id(decision, result)`（:293-302
  ——认 `audit_tags` 里的 `persona:<id>`）。**结论：目标会话完全由传入的 `IncomingMessage` 决定。**
- 因此项目里表达「群消息→异会话投递」的**既有做法 = 按目标会话构造 `IncomingMessage` 后交给中央管线**，
  三处同构先例（全部在根 `__init__.py`）：
  1. `:1819-1862` 历史上的今天推送 `_push`：`private:<target>` / `group:<target>` 合成 `IncomingMessage`
     → `pipeline.handle_async(message, offload_capability(cap), capability_id="bot.today_history")`；
  2. `:4314-4351` 订阅推送：逐目的地合成 `IncomingMessage`（`session_id=f"{scope}:{id}"`、
     `sender_id="sub-push"`）→ `pipeline.handle_async(..., capability_id="bot.subscribe")`，
     能力是闭包工厂 `build_subscription_push_capability(text)`（`domains/link_parse/capabilities/content_parser.py:548-567`）；
  3. `domains/ops/monitor/alerts.py:536-540` 管理员告警：`session_id=f"private:{admin_id}"` 同构。
- 另有一族「调度器侧无事件」形态 B（`SendRequest`→`submit`→内联投递→`SENT/REDIRECTED` 才算送达）：
  提醒 `__init__.py:2915-2977`、cookie 到期 `:2980-3078`、群摘要 `:3188-3211`、日常助理 `:3335-3357`。
  **本席不取形态 B**——campus 有真实事件、且要求出站经中央 `_complete`，故取形态 A（合成目标会话消息 + 中央管线）。
- **未新造任何机制**：无第二 submit 通路、无 target 改写框架、无新配置键。

### §0.4 门语义实测取证（收编后哪些门会咬 campus）

判定对象=**传入管线的那条 `IncomingMessage` 的会话**（合成后=**主人私聊会话**，非源群）：

| 门 | 实现在哪 | 对 `bot.campus_forward`（私聊合成消息）的判定 | 证据 |
|---|---|---|---|
| feature_gate | `domains/ops/features/feature_gate.py:53-62` | **未登记即 `allowed=False`（`feature_unregistered`）→ 整链 BLOCKED** | `bindings.get(capability_id) is None` 分支 |
| runtime_enabled / runtime_control | `pipeline.py:501-546` | 全局暂停/能力暂停时拦（与现网旧旁路不同：旧旁路不理会） | `_prepare` |
| policy（黑白名单） | `domains/chat_reply/policy/gate.py:215-` | 私聊除 `sender_blocked`/`critical_input` 外一律放行；**群黑白名单只对 `session_type is GROUP` 生效**（:250） | `evaluate_policy` |
| quiet_hours | `domains/chat_reply/policy/quiet_hours.py:120-125` | **只拦 `bot.chat`/`bot.content`**；campus 命中 `direct_request_bypass` 恒放行 | `capability_id not in {"bot.chat","bot.content"}` |
| rate_limit | InMemory `:311-316` / SQLite `:703-708` | 非 `CHAT_CAPABILITY_IDS` **恒放行**（`non_chat_capability`）；且 pipeline 把 `capability_id != bot.chat` 记为 interactive（`pipeline.py:604-610`）→ `interactive_bypass` 更早放行 | 两实现同语义 |
| reply_budget | `domains/chat_reply/policy/reply_budget.py:143-149` | 非 chat 能力 `max_messages=1`（与旧旁路 `max_messages=1` 一致） | — |
| 幂等 claim | `pipeline.py:1053-1063` + `runtime/event_idempotency.py:25-32` | 键=`adapter\|bot_id\|message_id`；缺 `message_id` 返回空串=跳过去重；`bot_event_idempotency_enabled` 缺省 False→表为 None（恒放行）。**store 侧 `record_message` 幂等仍在**（双保险） | 见 §2 对照表 |
| review | `domains/render/reviewer.py:114-165` | `_unsafe_output_reasons` 命中即 BLOCK（**新增风险面**：源群文本含密钥/路径形态会被拦），`privacy_level` 取 `result.privacy_level`（能力显式 PERSONAL=与旧一致） | §4 裁定点 |
| 合并转发 | `pipeline.py:761-785` + `renderer.py:376-403` | `should_forward_long_text` 为 `len>=min_chars`；`min_chars` 代码缺省 1500、`.env.example` 样例 0（`docs/config-catalog-full.md` E1）→ **截断满额（1501 字）的边缘消息在 min_chars=1500 时会被转成合并转发**；按条数规则（node_chars=900、min_nodes=4 → ≥2700 字）永不可达（正文被 1500 预算钉死） | §4 裁定点 |

### §0.5 注册册现状（复核实锤）

- `bot.campus_forward` 全树仅两处出现：真身 `campus.py:155` 与 `tests/test_campus_digest.py:148`——
  **注册册零登记**（`CONTROLLED_INTERNAL_CAPABILITIES` 无、`ROUTE_CAPABILITY_DECLARATIONS` 无、帮助主题无）。
  收编后必须登记，否则 feature_gate 直接 BLOCK（§0.4 第一行）。
- canonical 位置：`domains/chat_reply/runtime/capability_registry.py:533`（`runtime/capability_registry.py`
  是 PEP 562 活垫片，feature_catalog 从旧路径 import 同源）。campus 无 RouteKind/无命令入口，
  与 `bot.group_digest_push` 同族 → 登记进 `CONTROLLED_INTERNAL_CAPABILITIES`（入站/通知链显式使用、
  尚不属于 RouteKind 主表）。
- **存量红（本席开工前既有，非本席造成）**：一致性门
  `tests/test_runtime_feature_gate.py::test_main_ingress_capability_ids_are_registered` **基线即 FAIL**，
  缺登记的是别席 S0 收编引入的四条：`bot.cookie_expiry_notice`、`bot.cookie_login`、`bot.file`、
  `bot.group_welcome`。原文见 §1.0。本席只补 `bot.campus_forward`，四条越界项记 §6 移交。

## §1 RED 证据（实现前实跑）

### §1.0 基线：既有一致性门实跑原文（改动前）

```
$ PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=1 ../ChatBot_Runtime/venv/Scripts/python.exe \
    -m pytest tests/test_runtime_feature_gate.py::test_main_ingress_capability_ids_are_registered \
    -p no:cacheprovider --basetemp="$TEMP/u17-base-<pid>" -q
E   AssertionError: 入站声明了未登记能力：['bot.cookie_expiry_notice', 'bot.cookie_login', 'bot.file', 'bot.group_welcome']
1 failed in 2.22s
```

### §1.1 新用例 RED（待补实跑原文）

## §2 改动清单 + 改前改后对照

## §3 GREEN 实跑

## §4 裁定点（必须用户过目）

## §5 阻塞（若有）

## §6 移交

## §7 树卫生
