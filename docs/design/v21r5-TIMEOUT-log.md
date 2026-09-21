# v21r5 A 席 — 回复超时代码级根因修复 log

## 任务简报摘要
- 用户 09-19 告警：13:57 chain=11 跳全败 kind=network；14:06 chain=2 跳 last=potccv-gpt-56-terra:config_missing；14:43 chain=5 跳 network；15:02 chain=15 跳全败 network。同分钟 TG 也告警 = 外网整体故障是诱因。
- 用户感知「回复超时」根因 = 全网故障时 failover 链遍历全部渠道 × 每跳 ~20s 读超时，最长烧满 BOT_CHAT_FAILOVER_MAX_SECONDS=300s 才给降级回复。300 是用户裁定值，禁改 .env。
- 既有机制（待核实）：渠道 90s cooldown 降速；`_failover_min_hop_seconds`≈3s 链止损；config_missing 刻意不冷却。

## 任务目标
1. 读真身 model_router.py failover 循环 + channel_health.py 冷却机制（真身路径 domains/chat_reply/llm_engine/，垫片在 llm/ 下为 18 行 PEP 562 转发）。
2. 链级 fail-fast：单次请求链内连续 ≥5 跳网络类失败（connect/timeout 类，不含 config_missing/4xx）→ 中止剩余链，走既有失败面（私聊五池话术 / 群聊 A-19 降级池），必须产出用户可见回复。常量 `_FAILFAST_CONSECUTIVE_NETWORK = 5`。不改 config.py；新键需求提案写 log。
3. config_missing 重复冷却：同渠道 config_missing 进程生命周期累计 ≥3 次 → 按既有 cooldown 机制降速（10×bot_chat_channel_cooldown_seconds 量级），前两次不冷却；更新设计注释。
4. .env 存在性检查 `grep -c "BOT_POTCCV_API_KEY" .env` 结果写 log（0=未配置 = 14:06 config_missing 实锤，附修复建议）。
5. 测试全离线：①连续 5 跳网络失败→链中止且降级回复仍产出；②config_missing 累计 3 次→渠道被冷却跳过；③单渠道失败不影响后续渠道正常 failover；④既有 failover 回归全绿。实跑输出原文贴本 log。
6. 收尾：改动文件清单（路径+行号区间）、改前/改后对照、测试实跑输出、遗留问题，末尾 `A-SEAT DONE`。

## 约束
- 禁 git 写操作；禁再派子代理；禁真实 LLM 调用/对外发送/生产重启；不 commit。
- config.py 只读；禁碰 domains/chat_reply/{runtime,capabilities,security,character}/。
- 文件所有权：domains/chat_reply/llm_engine/**、tests/test_llm_failfast.py、tests/test_model_router_*.py 归本席。
- 测试纪律：`PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 <venv> -m pytest <files> --basetemp="$TEMP/seatA2-tmp" -p no:cacheprovider -q`。

## 进度
- [2026-09-19 开场] 开始探索。先读本 log 落盘（断点保障），随后读 model_router.py failover 循环与 channel_health.py。
- [探索完成] 关键取证（全部 verified 实读）：
  - **.env 检查**：`grep -c "BOT_POTCCV_API_KEY" .env` = **1（已配置）**。⇒ 14:06 `potccv-gpt-56-terra:config_missing` **不是 .env 缺 key**。config_missing 的产生路径=路由循环里 `spec.all_api_keys()` 为空（model_router.py:2124-2131）或 provider 侧 key 解析为空（providers.py:414-418）。.env 有 key 的前提下仍报 config_missing，最可能是**生产 bot 进程启动早于 POTCCV 渠道加入（09-17 晚五段增补才上车）且未重启**，或注册表条目 env: 槽位名与 .env 键名不一致——用户重启后应消失；若重启后仍现，建议核对该渠道条目 `api_key: env:BOT_POTCCV_API_KEY` 拼写或剪掉该渠道。本席不改 .env/注册表。
  - **failover 主循环**：`_generate_impl`（model_router.py:1932-2266）。循环体：deadline 检查（2106-2120 含 `_failover_min_hop_seconds`≈3s 链止损）→ spec 缺失 continue → `api_keys` 空 = config_missing 记号（2124-2131，**无冷却**）→ 逐 key 尝试 → LLMProviderError 记号+健康记录+hop 日志（2199-2214）→ auth 换 key（2217-2218）→ `should_failover` 不可转移则 raise（2219-2222）→ 其余 continue 下一候选。链尾（2248-2266）：last_error raise（挂 attempts）→ deadline 空转则 kind=timeout → 全无候选则 provider_not_configured。**失败面由能力层承接 LLMProviderError 产出降级回复（既有），路由侧只需 raise 即可让用户可见回复发生**。
  - **错误分类（providers.py）**：`_FAILOVER_ERROR_KINDS`（31-48 行）= timeout/network/server/rate_limited/provider_error/empty_response/model_not_found/unsupported_model/bad_request/invalid_request/unsupported_parameter/http/auth/schema。网络类（connect/timeout 类）= **{"network", "timeout"}**（providers.py:559-620：连接类异常→network，超时→timeout）。4xx（bad_request/invalid_request/unsupported_parameter/auth/model_not_found/unsupported_model/http）与 server/rate_limited 都是「服务端可达」证据 → 不计入 fail-fast 且**重置**连续计数；`provider_error`（未分类异常包装）按保守原则**重置**（宁可少触发不误杀）；config_missing **中性**（既不计数也不重置——它根本没碰网络）。
  - **冷却机制（channel_health.py）**：`ChannelHealthStore`（54 行起，进程级单例 `_GLOBAL_STORE`，SQLite 持久化 + `self._lock`）。`record_failure(model_id, error_summary, cooldown_seconds)`（197-251）写 `cooldown_until`（now+cooldown，UTC ISO）；`cooling_ids()`（253）取冷却集；`demote_cooling_candidates`（477）把冷却渠道**降级队尾不剔除**。`_health_record_failure`（model_router.py:589-609）对 `{"auth","config_missing"}` 显式 return 不冷却（599-601 注释「配置问题≠渠道不可用」）。`resolve_channel_cooldown_seconds` 缺省 90s（`_DEFAULT_COOLDOWN_SECONDS`，channel_health.py:41）。
  - **hedged 影子路径**：`_hedge_attempt`（1329-1456）config_missing 分支在 1362-1371（同样只记号不冷却）。生产 BOT_CHAT_HEDGED_REQUESTS_ENABLED=false（09-17 成本三刀），fail-fast 主战场是串行主循环；影子路径只补 config_missing 计数，不引 fail-fast（保持改动面最小）。
  - **测试 mock 模式**：tests/test_model_router_failover.py 顶部 autouse fixture `_reset_channel_health_singleton`（每测换新 store 到 tmp_path + 钉健康层关）+ FakeProvider（按 model_id 查 failures 字典抛 LLMProviderError）+ `_router()`/`_spec()` 工厂。新测试照抄此模式。
- [设计定稿] 实施方案：
  1. model_router.py 常量区（`_PARAM_STRIP_RETRY_KINDS` 后）加 `_FAILFAST_CONSECUTIVE_NETWORK = 5`、`_NETWORK_FAILFAST_KINDS = frozenset({"network","timeout"})`、`_CONFIG_MISSING_COOLDOWN_THRESHOLD = 3`、`_CONFIG_MISSING_COOLDOWN_MULTIPLIER = 10`。
  2. `_generate_impl`：循环前置 `consecutive_network_failures=0` + `failfast_abort=False`；except LLMProviderError 分支在 hop 日志后插计数/重置逻辑，达阈值 → `attempts.append("failover:failfast_network")` + warning 日志 + 置 flag break 内层 key 循环；内层循环后 `if failfast_abort: break` 外层。链尾既有 raise last_error 路径原样承接（错误 kind=network/timeout，能力层失败面产出五池/A-19 降级回复）。新记号 `failover:` 前缀已被 `_last_channel_id`（1698）跳过，计费归因零影响。
  3. config_missing 重复冷却：channel_health.py `ChannelHealthStore.__init__` 加内存计数 dict + `record_config_missing(model_id)->int`（进程生命周期语义，不落库）；model_router.py 新 helper `_health_record_config_missing`（健康层开启时计数，≥3 次调既有 `record_failure(cooldown_seconds=10×bot_chat_channel_cooldown_seconds≈900s)`）；调用点=主循环 2124-2131 config_missing 分支 + `_hedge_attempt` 1362-1371。`_health_record_failure` 的 config_missing 跳过语义保留（冷却由新 helper 决定），注释同步更新。
  4. 新测试 tests/test_llm_failfast.py：①5 连跳网络失败→中止+raise（ attempts 含 failfast 记号、后续渠道未拨号）+阈值内 4 跳仍正常转移+auth 打断连续计数；②config_missing 3 次进冷却（第 1/2 次不冷、第 3 次冷却 ≈900s 且 cooling_ids 命中+队尾降级）；③单渠道失败不影响后续 failover（既有用例复盖+补一条 config_missing 中性用例）；④既有 failover 回归实跑。
- [实现完成] 代码改动已落盘（ast.parse 双文件 SYNTAX OK）：
  - `channel_health.py`：`__init__` 加 `_config_missing_counts` 内存计数 dict（进程生命周期语义，不落库）+ 新方法 `record_config_missing(model_id)->int`（锁内 O(1)，插在 cooling_ids 与 unavailable_ids 之间）。
  - `model_router.py`：
    - 常量区（`_PARAM_STRIP_RETRY_KINDS` 后）：`_FAILFAST_CONSECUTIVE_NETWORK = 5`、`_NETWORK_FAILFAST_KINDS = frozenset({"network","timeout"})`、`_CONFIG_MISSING_COOLDOWN_THRESHOLD = 3`、`_CONFIG_MISSING_COOLDOWN_MULTIPLIER = 10`（各带设计注释）。
    - 新 helper `_health_record_config_missing`（`_health_record_failure` 之后）：健康层开启时计数，≥3 次调既有 `record_failure(kind=config_missing_repeated, cooldown_seconds=10×resolve_channel_cooldown_seconds)` + warning 日志；全链 try/except 静默（与既有健康面同纪律）。
    - `_health_record_failure` 注释更新：config_missing 跳过语义保留，指向新 helper。
    - `_generate_impl`：循环前置 `consecutive_network_failures=0`/`failfast_abort=False`；外层循环改 `enumerate(candidate_ids)`（取剩余候选数）；config_missing 分支接 `_health_record_config_missing`；except LLMProviderError 的 hop 日志后插计数/重置+达阈值中止（`attempts.append("failover:failfast_network")` + warning + 内层 break）；内层 key 循环后 `if failfast_abort: break` 外层；链尾既有 raise last_error 原样承接（能力层失败面产出用户可见回复）。
    - `_hedge_attempt`：config_missing 分支同样计数（影子路径同语义；生产影子默认关，fail-fast 不入影子路径=改动面最小）。
  - 过程事故（已修复）：插入 helper 时一度吞掉 `_strict_priority_enabled` 的 def 行，Read 回现场后补回，ast.parse 全绿。
- [待办→测试] 下一步：写 tests/test_llm_failfast.py 并实跑。
- [测试完成] tests/test_llm_failfast.py 8 用例全部通过（首轮 7 passed/1 failed = 本席测试断言笔误——config_missing 不构造 provider，`bad` 不出现在 FakeProvider.calls；修正断言后 8/8 绿，实现零改动）。静态门 scoped 实跑：ruff 首轮 1 处 I001 import 排序（--fix 自修）→ 终态 `All checks passed!`（model_router.py + channel_health.py + test_llm_failfast.py 三文件）；mypy（dev.ps1 同参 `--explicit-package-bases --ignore-missing-imports`，cache 落 %TEMP%）`Success: no issues found in 3 source files`。树卫生：llm_engine/ 与 tests/ 零 `__pycache__`、零 `data/`、零 `.pytest_cache`（basetemp 全部落 $TEMP）。

---

## 改动文件清单（路径 + 行号区间；全部未 commit，提交裁决权在用户）

| 文件 | 位置 | 内容 |
|---|---|---|
| `plugins/bot_unified_runtime/domains/chat_reply/llm_engine/model_router.py` | L62-99 常量区 | 新增 4 常量 `_FAILFAST_CONSECUTIVE_NETWORK=5` / `_NETWORK_FAILFAST_KINDS={"network","timeout"}` / `_CONFIG_MISSING_COOLDOWN_THRESHOLD=3` / `_CONFIG_MISSING_COOLDOWN_MULTIPLIER=10`（各带 v21r5 设计注释） |
| 同上 | L626-630 | `_health_record_failure` 内注释更新：config_missing 跳过语义保留，指向新 helper |
| 同上 | L642-685 | 新 helper `_health_record_config_missing(model_id, config)`：健康层开启时计数，≥3 次调既有 `record_failure(kind=config_missing_repeated, cooldown_seconds=10×resolve_channel_cooldown_seconds)` + warning 日志；全链 try/except 静默 |
| 同上 | L1436-1440 | `_hedge_attempt` config_missing 分支接计数（影子路径同语义） |
| 同上 | L2174-2181 | `_generate_impl` 循环前置 `consecutive_network_failures=0` / `failfast_abort=False`；外层循环改 `enumerate(candidate_ids)`（取剩余候选数用） |
| 同上 | L2214-2218 | 主循环 config_missing 分支接 `_health_record_config_missing`（中性于 fail-fast 计数） |
| 同上 | L2301-2323 | except LLMProviderError 的 hop 日志后：网络类计数/非网络类重置；达阈值 → `attempts.append("failover:failfast_network")` + `llm failfast network abort` warning + 内层 key 循环 break |
| 同上 | L2357-2360 | 内层 key 循环后 `if failfast_abort: break` 跳出外层候选循环；链尾既有 `raise last_error`（L2361-2363 原样）承接 |
| `plugins/bot_unified_runtime/domains/chat_reply/llm_engine/channel_health.py` | L57-64 | `__init__` 新增 `_config_missing_counts: dict[str,int]`（内存态=进程生命周期，不落库） |
| 同上 | L281-296 | 新方法 `record_config_missing(model_id)->int`（锁内 O(1) 累计，带 v21r5 语义 docstring） |
| `tests/test_llm_failfast.py` | 全文（新建，约 320 行） | 8 用例，FakeProvider 模式照抄 test_model_router_failover.py（含 A50 同款单例复位 fixture） |

**未动**：config.py（零改动，无新 config 键——阈值/倍率全为模块常量，改行为需改代码）、.env、providers.py、capabilities/（失败面承接方）、runtime/、security/、character/。

## 改前 / 改后行为对照

| 场景 | 改前 | 改后 |
|---|---|---|
| 全网故障，链 15 渠道全 network/timeout 超时 | 遍历全部 15 跳 × ~20s ≈ 烧满 300s 预算才 raise → 用户等 5 分钟才见降级回复 | 第 5 跳网络失败即中止（5×~20s ≈ ≤100s）→ raise last_error(kind=network/timeout) → 同一失败面产出五池/A-19 降级回复；attempts 带 `failover:failfast_network` 记号，日志 `llm failfast network abort` |
| 链内 4 跳网络失败后第 5 渠道成功 | 成功 | 成功（阈值内不干预，行为不变） |
| 链内混入 auth/4xx/server/rate_limited/provider_error | 转移 | 转移，且打断连续网络失败计数（服务端可达=网络通）；config_missing 中性（不计数不打断） |
| 单渠道失败 | failover 下一渠道 | 不变（测试锁死） |
| 同渠道 config_missing | 永不冷却，每个候选链都当前排白跳一次（无网络成本但耗链预算/诊断注意力） | 进程生命周期累计：第 1/2 次照旧放行；第 3 次起每次写 `cooldown_until = now + 10×bot_chat_channel_cooldown_seconds`（缺省 90s→900s），候选队列降级队尾（不剔除，修复后自然恢复）；健康层关闭时整体空转=零行为变化 |
| 计费/归因 | — | 不受影响：`failover:` 前缀记号被 `_last_channel_id` 跳过 |

## 测试实跑输出（原文）

环境：`PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 ChatBot_Runtime/venv/Scripts/python.exe -m pytest … --basetemp="$TEMP/seatA2-tmp" -p no:cacheprovider -q`（全离线 mock，零真实 LLM 调用）。

新文件（终态）：
```
tests/test_llm_failfast.py …………… 8 passed in 1.98s
```
（首轮 `1 failed, 7 passed in 1.95s`：失败为测试断言笔误非实现缺陷，已修正）

既有回归家族（12 文件合跑，含简报点名两件）：
```
tests/test_model_router_failover.py tests/test_model_router_channel_failover.py
tests/test_llm_failfast.py tests/test_channel_health.py tests/test_channel_health_v2.py
tests/test_auditfix_llm_route.py tests/test_bgroup_llm_route.py
tests/test_llm_route_priority_v21r2.py tests/test_llm_ledger.py
tests/test_model_context_caps.py tests/test_vision_and_failover.py
tests/test_llm_error_classification.py
→ 204 passed in 17.49s
```

相邻 LLM 面（8 文件）：
```
tests/test_model_admin_and_schedule.py tests/test_model_effort_groups_and_pricing.py
tests/test_model_family_pricing.py tests/test_prfix_llm.py tests/test_v21_s11_llm_draft.py
tests/test_v21_s9_llm_api.py tests/test_memory_router_reuse.py tests/test_llm_httpx_client.py
→ 89 passed in 19.69s
```

ruff 自修后终态复跑（3 文件 + 点名回归 2 文件 + 新文件 pytest）：
```
ruff check model_router.py channel_health.py test_llm_failfast.py → All checks passed!
pytest test_llm_failfast.py test_model_router_failover.py test_model_router_channel_failover.py
→ 35 passed in 2.42s
```

mypy（dev.ps1 同参，scoped 3 文件）：
```
Success: no issues found in 3 source files
```

## .env 存在性检查（任务 4）

`grep -c "BOT_POTCCV_API_KEY" .env` → **1（已配置，非 0）**。

**给用户的结论与修复建议**：14:06 `potccv-gpt-56-terra:config_missing` **不是 .env 缺 key**（key 在）。config_missing 产生于路由循环 `spec.all_api_keys()` 为空——在 key 已存在的前提下，最可能是 **生产 bot 进程启动早于 POTCCV 渠道加入（09-17 晚才上车）且未重启**，重启后该告警应消失；若重启后仍现，则核对注册表 potccv 两条目的 `api_key: env:BOT_POTCCV_API_KEY` 槽位拼写，或直接剪掉该渠道（本次改动后，该渠道 config_missing 累计 3 次也会自动被 900s 冷却降速到队尾，不再每链白跳）。

## 遗留问题（诚实清单）

1. **离线 passed ≠ 生产生效**：全部改动未重启、未部署、未 commit；生产进程仍是旧代码。生效需用户提权重启 bot（铁律）。
2. **hedged 影子路径不参与 fail-fast**：影子并发（生产缺省关，BOT_CHAT_HEDGED_REQUESTS_ENABLED=false）内部失败不累计连续网络失败计数，仅其后的串行链从 0 计起。若用户未来重开影子并发，全网故障的早停阈值语义按串行链部分生效——已记录，不构成本轮改动面。
3. **fail-fast 阈值为固定常量 5**：不可配置（不改 config.py 约束下的取舍）。如需调优改 `_FAILFAST_CONSECUTIVE_NETWORK` 一行即可。
4. **config_missing 计数为内存态**：重启清零（=「进程生命周期」语义的既有定义）；若用户希望跨重启持久，需 SQLite 落库，本轮不做（避免与 cooldown_until 落库语义混淆）。
5. **`failover:failfast_network` 记号消费面**：`_last_channel_id` 已跳过（计费归因零影响）；call-record 出口把无 `failover:deadline` 的失败链记为 `provider_failed`（failfast 链同归此类，语义成立）。若审计/WebUI 侧未来想单列 failfast 链，需另行消费该记号。
6. 全量套件（dev.ps1 -Task test）未跑——多席位并行改树期间跑全量会混入他席在飞改动，回归以本席所有权面（293 passed）+ 点名两文件（27 passed）为准，全量收口留给合流席。

A-SEAT DONE
