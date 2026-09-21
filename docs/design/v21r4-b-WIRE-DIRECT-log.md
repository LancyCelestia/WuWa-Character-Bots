# v21r4-B WIRE-DIRECT 席日志（B2③：L56/L57/L58/L65）

> 席位=WIRE-DIRECT｜工作包=B2③ 生产直连点收编（4 行）｜开工=2026-09-19 00:2x｜全批未 commit/未重启/未部署。
> 硬约束遵守：零 git 写操作、零子代理、零真实对外发送、零真实 LLM 调用、零重启；矩阵文件零改动；`theme_tokens.py`/`render_hashes.json`/`domains/render/**`/`output/card_render/**`/`card_render/templates/**` 零触碰；`verify_hashes.py --write` 未执行。
> 解释器固定 `ChatBot_Runtime/venv/Scripts/python.exe`；pytest 带 `PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 --basetemp=$TEMP/<唯一名> -p no:cacheprovider`。

## 〇、认领与让步（已同步 docs/design/v21r4-b-coordination.md）

- 认领写域：本日志 + `tests/test_v21_wiredirect_unified_path.py`（新增）。只读取证面：`domains/schedule/**`、`domains/divination/**`、根 `__init__.py`、`domains/core/decision/outbound_registry.py`、`control_plane/api/divination.py`。
- **让步（WIRE-SVC，协调表已记）**：根 `__init__.py` 服务装配段（含 L56-L58 课表/提醒生产装配与 tick 调度注册面）归 WIRE-SVC，本席零写入；`domains/chat_reply/character/`、`contracts/` broker 接线零触碰；L41（memory）一行不动。
- 实测并发佐证：取证期间根 `__init__.py` 行号两度漂移（WIRE-SVC 在飞插入装配段），本席对该文件保持只读是硬决定。

## 一、逐行核实结论（先只读取证；证据=实读源码+席位日志交叉）

**总裁定：四行经逐一取证，均不含「绕过统一出站路径（SendQueue/UnifiedDeliveryGateway）的生产直连点」。plan §三 B2③ 的动作描述（"把绕过统一出站路径的直连点收编"）与本四行实际内容不符（规划期推测未落核实）；按简报边界裁定协议逐行改判如下，不硬造收编。**

### L56 = V21-SCHEDULE-001（课表截图→结构草稿→确认提醒）

- 矩阵原文（docs/design/backend-v2-acceptance-matrix.md:56）：implementation=unknown（草案建议 implemented）｜production_wiring=unknown（草案 not_wired：无 matcher/装配；三装配助手就位 s11 §四.1）。
- 直连点核实：`domains/schedule/` 全域 AST 级零 `call_api`/零直发方法调用（本席新增结构锁测试实证）。timetable.py/llm_draft.py 只产出草稿不发送。
- **处置=改判 blocked（装配+授权双阻塞）**：①生产装配=在根 `__init__.py` 调用 `build_schedule_llm`（llm_draft.py:457）/`build_timetable_provider`（timetable.py:434）+matcher/命令面——装配段归 WIRE-SVC（让步已记）；②live 需真机截图+识图 registry+**真实出站授权**（s11 §五原话）——出站授权属用户裁决，简报红线"绝不实装真实对外发送"。不猜、不代办。

### L57 = V21-SCHEDULE-002（工作/出行/游玩/票课/购物/吃饭完整事务链）

- 矩阵原文（:57）：unknown 行（草案 implemented/not_wired）。
- 直连点核实：同 L56——W10 引擎+七模板链种子到 `draft_to_plan_payload` 为止，无任何出站步（"不擅自购买"结构性成立，s11 §一）。
- **处置=改判 blocked（同 L56）**：装配面+出站授权同上。本行域内无直连点可收编。

### L58 = V21-SCHEDULE-003（提醒恢复/晚点/安静时间/取消/防风暴）

- 矩阵原文（:58）：implementation=partial（character/reminders.py:323 旧括注）｜草案 not_wired（tick 无调度装配；SendQueue 协议就绪，真实出站端口未授权；**存量 reminders.py 生产线并行未切**）。
- 直连点核实（两线分别取证）：
  - **存量生产线已走统一路径（"并行未切"≠绕行，纠正误读）**：根 `__init__.py` `_deliver_due_reminders`（本席取证时 ~:2852-2963）构造 `SendRequest`→`send_queue.submit`→`_deliver_transport_send_request` 统一 transport+回执仓，送达才销账；行为面 `tests/test_reminder_delivery.py` 全覆盖（transport 投递/失败挂起/worker 已送防双发/调度装配）。
  - **新引擎（s11 delivery.py）出站咽喉=queue.submit 单一面**：`_QueueProtocol` 只消费 `submit`（delivery.py:51-54）；queue/request_builder 未注入→`not_authorized` 诚实干跑（detail="queue or request_builder not wired; real outbound port unauthorized"）；行为面 `tests/test_v21_s11_delivery.py` 17 例（含 test_not_authorized_outbound_is_honest_dry_run/test_assembly_factory_dry_run）。
- **处置=改判 blocked（同 L56）+ 澄清记录**：tick 调度装配在根 `__init__.py`（WIRE-SVC 域）；注入真队列=启用真实投递，须用户授权。遗留括注照录：重试计数进程内存（s11 §四.2）。

### L65 = V21-DIVINATION-002（塔罗无放回/阵型/正逆位/确定解读）

- 矩阵原文（:65）：implementation=partial（sources/tarot.py:164,228 旧括注）｜草案 implemented+partial（解释端口待接线 s12 §三.3）。
- 直连点核实：塔罗 QQ 出站走 `CapabilityResult`→pipeline→renderer→SendQueue 框架统一面（domains/divination/capabilities/divination.py:13-16 只返回 CapabilityResult）；域内 AST 级零 call_api。真实缺口=**LLM 人格化解释端口 503 not_wired 诚实位**：`control_plane/api/divination.py:196-208`（POST /draws/{id}/interpretation，404 优先于 not_wired）+ `domains/divination/api/errors.py`（INTERPRETATION_NOT_WIRED_CODE="not_wired"）+ `facet.py:253/303`（policy/capabilities 投影明示 not_wired+本地解读兜底）。
- **处置=改判端口组性质（与 L46 real_session 同型），维持 503 not_wired 不实装**：接线=真实 LLM 外呼（成本+question 上下文外流），本波硬约束禁真实 LLM 调用且未获用户授权；s12 §三.3 明言"真接线属后续席位"。改判理由照简报协议记录于此，现状零改动。后续归属建议：PORT-PLAN 的 B2② 端口方案材料（docs/design/v21r4-b2-port-wiring-plan.md）一并覆盖。

## 二、顺带取证（L35/L50 责任面交接线索；非本席四行，不越权收编）

S0 三组「疑似绕队列」+登记表坐标已陈旧（`domains/core/decision/outbound_registry.py:590-600` 记 4070/4878/5175，行号因多波迁移+在飞装配漂移）。本席 2026-09-19 00:4x 实测现坐标（**仍会随 WIRE-SVC 在飞编辑漂移，仅供定位**）：

| 组 | 现坐标（约） | 内容 | 归属 |
|---|---|---|---|
| S0 组1 | `__init__.py:~4300` | cookie 到期每日提醒→`send_private_msg` 私聊管理员（调度 job） | L35/DELIVERY-001 |
| S0 组2 | `__init__.py:~5184` | 入群欢迎→`send_group_msg`（group_increase notice） | L35/DELIVERY-001 |
| S0 组3 | `__init__.py:~5481/5487` | cookie 登录二维码图片→`send_group_msg`/`send_private_msg`（文本已走 `_send_text_through_unified_pipeline`，图片直连） | L35/DELIVERY-001 |
| 另发现 | `__init__.py:~5303/5310` | 文档导出→`upload_group_file`/`upload_private_file` 直连（文本走统一管线） | L50/FILE-002 |
| 已登记 | `domains/transport/sender/file_gateway.py:382` | Phase-1 文件网关 deliver 直连（PENDING_RULING） | L50/FILE-002 |
| 已收编先例 | poke 回戳/贴表情 | DSP 席经 `OutboundSideEffectExecutor` 门面收编（L34/L35） | 已完成 |

→ 以上移交主会话/L35 责任席裁量；本席不扩范围。

## 三、本席交付物

1. `tests/test_v21_wiredirect_unified_path.py`（新增，全离线零网络零 NoneBot）：四行「走统一路径」结构锁——schedule+divination 两域 AST 级零 `call_api`/零直发方法调用；delivery 出站咽喉=queue.submit 单一协议面；L65 解释端口 not_wired 诚实位防静默替换 tripwire。行为面不重复 s11/s12/存量已覆盖断言。
2. 本日志 + 协调表认领行。
3. 矩阵四行零改动（禁改文件）；production_wiring 四行均不升 wired（未 commit/未重启/未部署）。

## 四、实跑证据（命令+关键输出；诚实红线=离线 passed≠生产生效）

```text
# ① 新增契约锁（本席交付，4 例）
$ PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 \
  ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_v21_wiredirect_unified_path.py \
  --basetemp="$TEMP/v21r4-wd-t3" -p no:cacheprovider -q
....  [100%]
4 passed in 0.18s

# ② 新增+相关存量族合跑（s11 三件+s12+reminder 五件）
$ …同 env… -m pytest tests/test_v21_wiredirect_unified_path.py tests/test_v21_s11_delivery.py \
  tests/test_v21_s11_llm_draft.py tests/test_v21_s11_timetable.py tests/test_v21_s12_divination_api.py \
  tests/test_reminder_delivery.py tests/test_reminder.py tests/test_reminder_governance_receipt.py \
  tests/test_reminder_tone.py tests/test_v21r2_reminder_guards.py \
  --basetemp="$TEMP/v21r4-wd-t4" -p no:cacheprovider -q
149 passed in 10.55s        ← 新 4 + 存量 145，零失败零回归

# ③ 门禁
$ …python -m ruff check .
All checks passed!
$ …python scripts/command_catalog.py --check
command catalog is current (77 topics)
$ …python -m mypy --explicit-package-bases --ignore-missing-imports tests/test_v21_wiredirect_unified_path.py
Success: no issues found in 1 source file
```

- 树卫生：全程 `PYTHONDONTWRITEBYTECODE=1`，tests/plugins 零 `__pycache__` 增量；本席 `ruff check .` 产生的根 `.ruff_cache` 已清（rm 不可用走 `cmd rmdir /s /q`，实测 CLEANED）；未触碰 `data/`、Runtime、哈希台账（`verify_hashes --write` 未执行）。
- 全量套件未跑（本批多席在飞+简报未要求全量；全量红绿归属收口波/主会话，与 v21r2 各席同口径）。

## 五、遗留与移交

1. **矩阵四行零改动**：L56/L57/L58/L65 的 production_wiring 均未升 wired（未 commit/未重启/未部署）。收编落盘情况=**本席零收编**——四行经核实均无「绕过统一出站路径的生产直连点」（§一总裁定），离线证据只能支撑「结构锁+改判记录」，不支撑任何接线生效表述。
2. **L56/L57/L58 → 装配席（WIRE-SVC）+用户授权双依赖**：装配=根 `__init__.py` 调 s11 三助手（坐标见 §一）+tick 调度注册+matcher/命令面；注入真实 SendQueue 前必须获用户出站授权（queue=None 诚实干跑语义保持）。WIRE-SVC 装配时受 `tests/test_v21_wiredirect_unified_path.py` 结构锁保护：两域禁直连、delivery 出站面只许 queue.submit。
3. **L65 → 端口组**：解释端口维持 503 not_wired；tripwire 测试会在诚实位被移除时变红，实装须先获用户授权并同步矩阵 L65。建议 PORT-PLAN 的 B2② 材料将其纳入端口方案清单。
4. **L35/L50 责任面交接**：§二 表列 5 处直连/直传点（S0 三组现坐标+文档导出上传+file_gateway）归 DELIVERY-001/FILE-002 责任席；`domains/core/decision/outbound_registry.py` 登记表坐标陈旧（4070/4878/5175），修订归该表 owner（本席只读未动）。
5. 本席未触碰：根 `__init__.py`（WIRE-SVC 在飞，行号持续漂移）、`contracts/**`、`domains/chat_reply/character/**`、L41、`domains/render/**`、渲染门禁面、`tests/verify_hashes.py`。

——WIRE-DIRECT 席终（2026-09-19 00:5x）。
