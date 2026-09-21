# v21r2 DSP 席日志（V21-DISPATCH-001 + 风险 5 收口：中央 Dispatcher 生产接线）

> 席位合同：把 A16/S6 出站收编地基（`decision/outbound.py` 门面 + 登记表）按登记表逐点接到生产直连出站点上，
> 并把 `tests/test_v21_risk_red_dispatch_and_telegram.py` 的 3 条 strict xfail 转正为回归锁。
> 纪律：行为零变化（同样的回戳/贴表情效果）；复用既有 call_api 通道本体；禁新建第二出站通道；零 git 写操作。

## 一、计划（开工时落盘）

### 坐标复核（2026-09-18 实测工作树）

| 直连点 | 现坐标 | 性质 |
|---|---|---|
| group_poke 回戳 | `plugins/bot_unified_runtime/__init__.py:4811-4815`（简报 4745-4751 系 A1 冻结坐标，行号已漂移） | BY_DESIGN 直发（登记表 DirectSendEntry） |
| friend_poke 回戳 | `__init__.py:4817` | 同上 |
| set_msg_emoji_like | `domains/meme/reactions/engine.py:652-656`（runtime/reactions.py:652 已随 RW6 迁移，旧位为纯 re-export 垫片） | BY_DESIGN 旁路 |
| set_message_reaction | `domains/meme/reactions/engine.py:681-687` | TG reaction（docstring 自述未接线触发点，但字面量在 AST 扫描面内） |
| AST 扫描面豁免 | `control_plane/dispatcher.py`、`decision/dispatcher.py` | 两份 dispatcher 定义模块 |

- `decision/` 目录未被 RWOC 迁走（`decision/outbound*.py` 与 `decision/dispatcher.py` 均在原位；RWC2/RW12 日志确认「未动 decision/ 一字」）→ 本席按旧路径消费。
- 根 `__init__.py` 无在飞写者（COORDINATION 复核：RWC1/RWPA1/RW13/RW14/RW15/RW16 收官；RWC4 在飞域=runtime 核心+ingest/pipeline，不含根 `__init__.py`；RW6 已收官）→ 本席认领 Dispatcher 相关段独占。
- `control_plane/dispatcher.py`（77 行门面：route/review/send 三 callable + Poke/Reaction/Meme 服务）为未提交在飞件、无席位认领占用；包 `__init__` 顶层零 fastapi/uvicorn 依赖（惰性加载）→ 生产码可安全导入。
- decision/engine.py：`ActionPlan` 无 outbound_intents 字段、DecisionContext 无 mode 字段（阶段 0 形态）→ dispatcher 侧全部防御式 getattr。

### 方案（OutboundIntent → 许可租约 → 统一出站路径）

1. **`control_plane/dispatcher.py` 扩 `OutboundSideEffectExecutor`**（统一出站执行器，直连点唯一执行面）：
   `execute(intent, bot)` = cancel_requested 前置闸（取消在途不假成功）→ `OutboundAdmissionGate.admit`
   （发送前复验）→ `PermitLease.acquire`（线性化点，同键在途二次申请 DuplicateClaim 拒绝）→
   `mark_irreversible`（真实平台调用前）→ `TransportRegistry.resolve` 固定映射解析平台方法名
   （绝不拼接 API 名；TG POKE 有意未注册→显式 UnregisteredTransportError）→
   `bot.call_api(方法名, **params)`（**与 SendQueue worker 同一通道本体，非第二出站通道**）→
   finally `lease.release`（在途租约即用即还；顺序性事件不误伤）。返回 SideEffectReceipt，绝不抛半个发送。
2. **`decision/dispatcher.py`（最小手术，唯一触及 decision/ 的点）**：`dispatch(plan, ctx)` 从恒抛
   NotImplementedError 改为真实派发周期：shadow/未知语境只记录绝不发送（阶段 0 语义保持）；
   engine_only 语境下对 plan 携带的出站意图（防御式 `outbound_intents`）逐一过统一出站执行器；
   执行器未绑定=显式结果（outbound_not_bound）而非异常。透明登记：此文件属 RWOC 迁移面，
   本席仅动 dispatch 实现+DispatchOutcome，迁 domains/core/decision 时按现状随迁。
3. **`__init__.py` poke 回戳收编**：`_handle_poke_notice` 的 group_poke/friend_poke 直连段改走
   `PokeInteractionService`（control_plane 门面，真实 route→review→send 派发周期：route 构造严格
   DTO `OutboundIntent`、review 形态复验、send=执行器）→ 外层保持原 try/except 静默（零行为变化）。
4. **`domains/meme/reactions/engine.py` 收编**：`react_to_message` 与 `react_telegram_message` 内部
   改走 `ReactionService` 门面+执行器；签名/返回值/参数 coercion（int/str）/两条日志措辞全保；
   `maybe_react_on_message` 五层门及 `__init__.py:158,6817,7140` 消费方零改动。
5. **xfail 转正**：三测转绿后移除 strict xfail 标记留作回归锁（AST 扫描两条 + dispatch 行为一条）；
   TG risk6 两条按实测判定（预期本就 green）。
6. **幂等/租约语义测试补齐**（新建 `tests/test_v21_dispatch_outbound_wiring.py`）：
   同键在途二次申请拒绝、租约用毕释放后可重入、cancel_requested 永不假成功、准入拒绝不发、
   未注册 transport 诚实拒绝、QQ/TG 两 reaction 经门面出站、decision dispatcher shadow 不发/engine_only 执行。
7. 门禁：PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0，pytest `--basetemp=%TEMP%/v21r2-dsp -p no:cacheprovider`；
   回归面 = risk-red 文件 + poke/reactions 存量族 + test_outbound_v21 + `-k "poke or reaction or emoji"` 扫掠 + ruff/mypy 本域。

### 零行为变化论证

- 回戳：同一 `bot.call_api("group_poke"/"friend_poke", 同参数)`，同一 try/except 静默语义；唯一新增=同键在途并发去重（同 (会话,戳者) 毫秒级双事件不再双回戳，属修复而非行为变化）；顺序性多次戳不受影响（租约即用即还）。
- 贴表情：同一 API 名与参数 coercion；五层防刷门在 react_to_message 上游不变；执行器只在途线性化、无永久去重注册表（永久幂等归 ProactiveGate._reacted 所有，不双管）。
- 失败面：平台拒绝/不支持 → 原样静默（receipt.status=failed，调用方日志措辞不变）。

## 二、实施记录

### 〇、断点续收取证（2026-09-18 05:10，DSP 续跑席）

前任实际存活至 ~04:34（比移交简报的 04:24 更长），遗产比简报多两件：

| 文件 | mtime | 状态 |
|---|---|---|
| `control_plane/dispatcher.py` | 04:34 | `OutboundSideEffectExecutor`+`SideEffectReceipt`+`build_interaction_dispatcher` 全部落盘 |
| `tests/test_v21_dispatch_outbound_wiring.py` | 04:34 | 19 例幂等/租约/门面/decision 阶段 1 测试全落盘 |
| `domains/core/decision/dispatcher.py` | 04:33 | dispatch 阶段 1 最小手术已做（shadow 绝不发送语义保持） |
| `tests/test_v21_risk_red_dispatch_and_telegram.py` | 04:22 | 3 条 xfail 已摘标转回归锁 |
| `__init__.py` Dispatcher 段 / `domains/meme/reactions/engine.py` | 04:24 | poke 回戳与 QQ/TG 贴表情已收编门面 |

关键事实：**计划落盘（04:09）后 RWOC 才迁移 `decision/`**（04:15 全目录变 `domains/core/decision/` 真身+旧位 PEP 562 live re-export 垫片）——计划 §一「decision/ 未被迁走」的前提已过时；前任随机应变把 dispatch 手术做在真身文件上，消费面走旧路径 import（`decision.outbound`/`decision.dispatcher` 垫片解析到真身，monkeypatch 双向一致）。本席沿袭该格局，未再动 domains/core（RWOC 只读约束）。

前任死于「写完未验」：日志 §二/三/四全空，无任何实跑记录。本席五文件 `py_compile` 全过（无语法残破），随后实跑收口。

### 一、本席收口动作（仅补未完成）

1. **实跑取证**：risk-red + wiring + outbound_v21 + poke/reactions 全族 **152 passed**（含 3 条转正回归锁 + 19 例新接线测试全绿）——前任代码零修即过。
2. **补漏一处**：`-k "poke or reaction or emoji or outbound or dispatch"` 全仓扫掠抓到第 4 处陈旧断言——`tests/test_decision_engine_shadow.py::test_dispatcher_is_explicitly_disabled_in_phase1` 仍断言旧合同 `pytest.raises(NotImplementedError)`（前任只扫了 risk-red 文件内的 3 条）。按阶段 1 合同改写：dispatch 显式返回 `DispatchOutcome("shadow_recorded", "...not sent...")`（守住「未接管能力派发+shadow 绝不发送」两条边界），测试名与守卫意图不变。改后该文件 8 例全绿。
3. 静态门：ruff 5 文件 + 修正文件全绿；mypy 本域 6 文件零错误（全仓 10 错均为域外既有：8 缺库 stub（psutil/yt_dlp/openpyxl/pypdf/qrcode）+2 `control_plane/api/platform.py`（#36 已登记既有））。
4. 陈旧断言终扫：全 tests/ 无其他 NotImplementedError+dispatch 断言；`group_poke/set_msg_emoji_like` 字面量仅存于登记表数据测试与门面接线测试（合法面）。

### 二、行为零变化核验

- 回戳：同 `group_poke`/`friend_poke` 同参（`test_poke_v2` 13 例 + wiring 逐字节参数断言）；外层 try/except 静默保持；唯一新增=同键在途并发去重（毫秒级双事件不双发，租约即用即还，连续戳不受影响）。
- 贴表情：`react_to_message` 签名/返回值/参数 coercion（message_id int / emoji_id str）逐字节断言锁死（wiring `test_react_to_message_routes_through_unified_outbound`）；失败日志措辞与返回 False 语义不变；`maybe_react_on_message` 五层门与 `__init__.py` 三个消费点（走 `runtime/reactions` 垫片）零改动。
- TG `set_message_reaction`：仍无触发接线（诚实标注保持），仅出站路径换门面。

## 三、实跑证据

```text
# 全族（risk-red + wiring + outbound_v21 + poke/reactions 8 文件）
pytest tests/test_v21_risk_red_dispatch_and_telegram.py tests/test_v21_dispatch_outbound_wiring.py \
  tests/test_outbound_v21.py tests/test_poke_v2.py tests/test_reactions.py tests/test_reaction_store.py \
  tests/test_poke_notice_ingest.py tests/test_poke_unified_reaction_b10.py
→ 152 passed in 7.90s

# 全仓关键词扫掠（修复 shadow 陈旧断言后）
pytest tests/ -k "poke or reaction or emoji or outbound or dispatch"
→ 221 passed（修复前 1 failed = test_dispatcher_is_explicitly_disabled_in_phase1，已按阶段 1 合同改写）

# 复核三文件
pytest tests/test_decision_engine_shadow.py tests/test_v21_risk_red_dispatch_and_telegram.py \
  tests/test_v21_dispatch_outbound_wiring.py → 47 passed in 4.85s

# 静态门（解释器=ChatBot_Runtime venv；env PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0；
# pytest --basetemp=%TEMP%/v21r2-dspb* -p no:cacheprovider）
ruff check <5 DSP 文件 + test_decision_engine_shadow.py> → All checks passed! ×2
mypy --explicit-package-bases <6 文件> → 10 errors 全部域外既有（8 stub 缺失 + platform.py ×2），DSP 域零错误
# 前置：py_compile ×5 前任文件全过（无语法残破）
```

## 四、遗留

1. `domains/core/decision/dispatcher.py` 属 RWOC 迁移面，本批手术（dispatch 阶段 1 实现+DispatchOutcome）已按「随迁现状」落在真身——RWOC 收官对账时请把该文件计入 DSP 席改动（git 认账时注意区分）。
2. 能力派发（文本/卡片走 pipeline）仍属阶段 2+（B2 规划内，非本席范围）；engine_only 触发点生产侧尚无调用方（dispatch 目前仅测试面触达），接管待决策引擎阶段 2。
3. 全量 `dev.ps1` 四门禁未跑（纪律禁用 dev.ps1 + 工作树多席在飞，全量红绿归属本席无法切割）；本席域内回归与扫掠已全绿，CMD 总闸门以当日全量实跑为准。
4. 生产未重启，接线重启生效（与全批 WIP 同一窗口）。
