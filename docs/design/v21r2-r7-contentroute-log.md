# v21r2-R7 席交付日志：content_route / R-18 可达性族（2026-09-17）

席位文件域：`plugins/bot_unified_runtime/runtime/content_route.py`（只读复核，零改动）、
新建 `scripts/probe_intimate_route.py`、新建 `tests/test_v21r2_content_probe.py`。
只读复核域：`llm/model_router.py`（R1 独占）、`capabilities/chat.py`、`policy/*`。

## 一、路由健康结论（复核 verified）

**content_route 检测链与候选序端到端健康，域内零缺陷，无需修码。**逐项证据：

| 项 | 结论 | 证据 |
|---|---|---|
| L1 强词（+70 即切） | ✓ | 探针实测「强词」样例 → intimate，grok 组第一 |
| L2 上下文（+35，两轮过阈） | ✓ | 单轮停滞回带保持 normal、两轮才 intimate（test_probe_l2_context_two_turn_slow_burn 锁死）；chat.py 只扫 user 行（攻击评审 #4 修复在位，chat.py:2007-2016） |
| L4 手动开关（含倒装） | ✓ | 「开启亲密模式/打开亲密模式」命中；否定/疑问句（"我不想开启亲密模式"）不误触 |
| INTIMATE 候选 grok 第一 | ✓ | 生产快照实跑：axon-grok-46 → aiprc-grok → qian-night-grok（注册表 priority 序，无 EWMA 重排）；回归锁 test_intimate_head_follows_registry_priority_not_latency 在位 |
| 影子跳过 | ✓ | model_router `_generate_impl`:1768 `not content_intimate` 门 + 生产 .env 影子总开关已关（#36 成本三刀），双保险 |
| fail-open 全覆盖 | ✓ | 引擎五方法 + router cb 异常回默认队列 + explicit_allowed 异常按不放行（test_explicit_allowed_fail_open_closed） |
| Master Love 不覆盖显式 normal 钉 | ✓ | chat.py:1944-1955 `pinned_mode != "normal"` 守卫在位；引擎合同 test_probe_master_love_auto_pin_respects_explicit_normal_pin 锁死 |
| 群黑白名单制 | ✓ | 黑名单优先、白名单空=关闭（config 字段确为 list[str]，与代码迭代口径一致） |
| 升级重试（评审 A1） | ✓ | 标签注入层与升级重试已删净（model_router 全文无 escalation 重试）；chat.py:1842-1873 拒答模板只记日志 |

生产快照要点：`.env` **没有** `BOT_MODEL_REGISTRY`（权威注册表=运行时 store
`ChatBot_Runtime/data/settings/runtime_settings_shorekeeper.json`，当前 16 条）；
探针已按生产同源合并语义加载（store 无 `source:env` 标记的条目按纯运行时条目生效）。

## 二、修了什么

content_route.py 域内**零代码缺陷 → 零改动**（复核后判定）。实际修复面：

1. **测试缺口补齐**：`explicit_allowed_for_session` 在全部测试树中**零覆盖**
   （grep 全 tests/ 无一处引用）。新增 6 例：私聊/控制台常放行、群白名单命中、
   黑名单优先、白名单空=关闭、其余会话类型（channel/mail/move_private）不放行、
   int 条目宽容、fail-open 方向=不放行。文件：`tests/test_v21r2_content_probe.py`。
2. 探针本身 14 例（分类/候选序/零密钥保证/live 门禁），详见下节。

## 三、探针用法（用户验证枪）

```powershell
# 离线体检（默认；零网络零模型调用，打印分类+候选序+是否会到 grok）
.\ChatBot_Runtime\venv\Scripts\python.exe scripts\probe_intimate_route.py
# 附加自定义样例
.\ChatBot_Runtime\venv\Scripts\python.exe scripts\probe_intimate_route.py --text "想你了"
# 实弹（用户自己扣扳机；向 grok-4.6 发一次温和亲密请求，走既有 providers 通道与超时语义）
$env:BOT_PROBE_LIVE='1'; .\ChatBot_Runtime\venv\Scripts\python.exe scripts\probe_intimate_route.py --live
```

- 离线模式密钥零解析（`env:` 引用保持原样，实跑断言 `spec.api_key == ""`）。
- `--live` 无 `BOT_PROBE_LIVE=1` 时拒绝执行（exit 2，实跑验证）；单候选无故障
  转移，死在哪报哪；只打印判定（success/refusal/timeout/error）+ 前 80 字 + 轨迹，
  bearer/api-key 形态全打码；提示词为温和亲密语气（不露骨，露骨守界归
  content_safety，不归本探针）。拒答判定复用 chat.py 观测正则口径（本地镜像）。
- timeout 判定附说明：对应 axonhub 控制台「已取消」= bot 侧超时掐断、上游挂起。

## 四、实跑证据（2026-09-17）

```
pytest tests/test_v21r2_content_probe.py tests/test_content_route.py tests/test_content_safety_v2.py
→ 44 passed in 1.48s   （R7 新增 14 + 存量 content_route 21 + content_safety_v2 5 + …）

ruff check scripts/probe_intimate_route.py tests/test_v21r2_content_probe.py plugins/.../content_route.py
→ All checks passed!

mypy --explicit-package-bases --ignore-missing-imports <同三文件>
→ 本席 3 文件 0 错误（全局余 2 错均 control_plane/api/platform.py 既有档案，#36 已记）

探针离线实跑（生产注册表快照）节选：
强词        intimate  grok第一  axon-grok-46(grok-4.6) → aiprc-grok(grok-4.6) → qian-night-grok(grok-4.6) → axon-gemini-38-flash(...) → …
L2语境升级  intimate  grok第一  （同上 grok 组第一）
倒装开      intimate  grok第一  （同上）
正常/擦边   normal    -         axon-gemini-38-flash → default → … → axon-grok-46(第9位) → …
[OK] 全部样例判定符合预期
--live 无扳机实跑 → exit=2（拒绝执行）
```

## 五、失败透明化：现状与给 R1 的坐标（chat.py/model_router.py 只读，未动手）

**现状已可辨**（无需改）：LLM 整链失败时 `chat.py:2088-2107` 把 `exc.attempts`
转成 `llm_route_attempt:<id>:<kind>` 审计标签，`_llm_error_result`
（chat.py:2313-2339）告警 safe_summary 带 `chain=N last=axon-grok:timeout`——
「timeout 卡在 grok 渠道、试了几跳」生产已可见。axonhub 控制台「已取消」=
bot 20s 超时掐断（providers httpx read timeout → error_kind=timeout）。

**真实盲点**：INTIMATE 会话 grok 超时后 **failover 到 gemini 成功**的场景——
成功路径无告警，`_apply_content_route_reply`（chat.py:1869-1872）只打
`served_by=gemini-3.8-flash`，不带 `reply.attempts`，看不出 grok 死过。两个
候选修复坐标（任选其一，A 最小）：

- **坐标 A（chat.py 一行）**：`capabilities/chat.py:1870` 的 `logger.info`
  增加字段 `attempts=%s`，值 `list(getattr(reply, "attempts", []) or [])`。
  LLMReply.attempts 已由 ModelRouter 成功路径填好（model_router.py:1914），
  无需动 router。
- **坐标 B（model_router 可选告警）**：`llm/model_router.py:1908` 附近
  （`attempts.append(f"{model_id}:success")` 后）当 `content_intimate` 为真
  （同函数 1749-1757 已算好）且 attempts 含 grok 家族渠道的 `:timeout/:network`
  记号时，logger.warning 一条 `intimate_route_failover: <grok渠道:kind> served_by=<winner>`。

## 六、观察项移交（R1 域，本席不动手）

1. **时段分组 head 对渠道 id 注册表疑似 no-op**：`_auto_route_ids`
   （model_router.py:1370-1375）用 `group_order`（模型**名**）对 `known`
   （模型 **id**）做 `in` 匹配；生产注册表 id 形如 `axon-grok-46`，名字形如
   `grok-4.6`，恒不命中 → `BOT_MODEL_PRIORITY_GROUPS` 疑似从未生效（INTIMATE
   路由不受影响：内容头插在其后独立生效且已实测正确）。请 R1 核实是否按名聚合。
2. **gemini -high 变体不进 intimate head**：head 匹配按精确模型名
   （`gemini-3.8-flash`），`gemini-3.8-flash-high`/caps 变体落在候选尾部
   （实测排在 deepseek/terra/luna 之后）。grok 组仍整体在前，多数场景无感；
   若想变体同组，需在 `bot_content_route_order` 或 head 匹配语义上扩别名。
3. **store 残留**：运行时 store 有 `axon-gpt-56-luna(gpt-5.6-luna)` 渠道
   （luna 已从 presets 删除）；`default` 兜底 spec（bot_chat_model）在注册表
   为空时以非 manual 标签参与自动路由（正常链第 2 位）。均不影响 intimate 面。
