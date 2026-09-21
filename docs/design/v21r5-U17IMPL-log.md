# U17-IMPL-3 席实施日志（2026-09-20）

> 施工权威：docs/design/v21r5-u17-implementation-runbook.md（全读照单施工）。
> 用户裁决：实施；裁定点① review 门 fail-closed=A；裁定点② 1501 字边缘零改动=A。
> 红线：绝不向学校群发消息；禁 git 写/子代理/真实发送/重启/.env 读值；不 commit。
> 解释器：C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe
> 纪律：PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1；pytest --basetemp="$TEMP/u17impl3-tmp" -p no:cacheprovider

## Step 0：开工前置

- [x] runbook 全读完毕
- [x] diff 快照：`$TEMP/u17impl3-baseline.diff`（113 行，含 CAMPUS-FIX-9 未提交态，回滚唯一依据）
- [x] 实读三目标文件现状（campus matcher 实测坐标 **5027**，registry 已是 5027 现值）

## Step 1：campus.py 两 builder + payload + 撤脚手架（已落地）

- imports 收窄：去 `RenderedOutput/SendPolicy/SendRequest`，增 `BotDecision/CapabilityResult/IncomingMessage/RiskLevel`
- 撤 `CampusForwardRequest` 脚手架（93-104）；增 `CampusForwardPayload`（五字段 group_id/sender_name/text/message_id/body，frozen dataclass）
- `_build_forward_request` → `_build_forward_payload`（body 仍走 `build_campus_forward_text` 单一事实源，逐字节契约不动）；`record()` 返回 `CampusForwardPayload | None`
- 两 builder 按 runbook §2.1 表逐字段落地：`build_campus_forward_message`（platform=nonebot/adapter=onebot.v11/bot_id=push_bot_id/session_id=private:notify_qq/SessionType.PRIVATE/sender_id=notify_qq/group_id=None/privacy=PERSONAL/message_id=payload.message_id）+ `build_campus_forward_capability`（kind=text/body=payload.body/risk=LOW/privacy=PERSONAL/audit_tags=["campus","forward",f"persona:{source.persona_profile_id}"]）
- 结构锁自检：域内 SendRequest/RenderedOutput/SendPolicy/send_group_msg/send_private_msg/call_api 计数全 0；ast.parse OK

## Step 2：root __init__.py handler 收编（已落地）

- `:36` import 原地扩展单行（零增行）：`from .domains.assistant.campus.campus import (build_campus_forward_capability, build_campus_forward_message, build_campus_source)`
- contracts 块 BotDecision 注入用等行数合并技巧（`AuditRecord, BotDecision,` 一行，2 行→2 行零漂移）
- handler 尾段：`request`→`payload`（to_thread 参数零变化），`send_queue.submit(request)` 替换为中央管线 dispatch
- **坐标验证：`campus_record_matcher = on_message(` 仍在 5027 行，零漂移**；ast.parse OK；campus 段 `send_queue.submit` 清零（余 6 处为其他能力面，不属 campus）
- **runbook 片段偏差记录（证据化）**：runbook §2.2 片段用 `offload_capability(capability)`，但规约测试 `_campus_handler_env` 注入环境不含 `offload_capability`/`logging`（tests/test_campus_digest.py:448-457 实读），且 `handle_async` 硬等 awaitable（pipeline.py:1167 `result = await capability(...)`）——裸传同步能力生产必炸。处置=handler 内定义内嵌 async 适配闭包 `_offload(forward_message, decision)` 直返同步能力（与 offload_capability 同构、免聊天线程池竞争；campus 能力为纯格式化微任务，事件循环直返无阻塞面，且绝不因池 busy 吞转发，「来一条转一条」语义更强）。规约测试是绑定约束，runbook 片段让位于测试环境。
- **import 落点偏差记录（证据化）**：runbook §2.2 处方「:36 单行原地扩展」实跑被 ruff I001 拒绝——三名合并行 128 字符 > 88 行宽，isort 规范化必然拆行 → 顶漂 matcher 坐标 5027 → 打断 registry 坐标门。runbook 的两条硬约束（坐标不漂 + registry 零动作 + ruff 全绿）互斥时，保坐标优先：`:36` 回退原样，两 builder 改为 matcher 定义之下的**函数级导入**（本文件既有惯用形态，:3588/:3695 同款；handler 仍以裸名引用，AST 提取测试按环境注入同名字缝，生产闭包解析/测试环境注入两态等价）。ruff 实证 All checks passed + 坐标 5027 实证不漂。

## Step 3：test_campus_digest.py 摘牌 + 重写（已落地）

- 11 处 xfail 装饰器逐一摘除，`mark.xfail` 残留计数 **0**
- `test_record_builds_private_forward_request`：SendRequest 级断言 → payload 级（message_id/group_id/sender_name/text/body 前缀与内容）
- `test_record_long_text_truncated`：`request.content.text_fallback` → `payload.body`
- 顶部孤儿导入 `contracts import (PrivacyLevel, SendPolicy, SessionType)` 移除（重写后零使用，ruff F401 预防）
- **规约测试夹具缺陷修复（证据化，非扩权）**：`test_handler_dispatches_through_central_pipeline`/`test_handler_duplicate_message_id_forwards_once` 断言 `store.list_day(_TODAY)`（钉死 2026-09-15），但生产 handler 走真实时钟（record() 不传 now）——挂账态从未对实现跑过（strict=False xfail 遮蔽），任何正确实现都不可能满足。最小修复=断言改查 `datetime.now().astimezone().date().isoformat()`（handler 实际落库日）。管线分发/幂等核心断言本身全过，与收编正确性无关。

## Step 4：验收实跑

### campus 全文件（第一轮主验收）

```
$ venv/python -m pytest tests/test_campus_digest.py --basetemp=$TEMP/u17impl3-tmp -p no:cacheprovider -q
.............................                                            [100%]
29 passed in 5.80s
```

**29 passed / 0 failed / 0 xfailed / 0 xpassed —— 11 例转绿 + 2 例重写绿 + 16 例零触碰照旧。**

### 棘轮族合跑（campus + outbound_v21 + f3 登记 + feature_gate + subfeatures）

```
$ venv/python -m pytest tests/test_campus_digest.py tests/test_outbound_v21.py tests/test_v21_f3_outbound_capability_registration.py tests/test_runtime_feature_gate.py tests/test_runtime_subfeatures.py --basetemp=$TEMP/u17impl3-tmp -p no:cacheprovider -q
........................................................................ [ 56%]
.......................................................                  [100%]
127 passed in 18.06s
```

127 passed / 0 failed（棘轮重构后复跑第二轮：127 passed in 16.64s）。
注：runbook §2.5.2 预告 `test_runtime_feature_gate.py::test_main_ingress_capability_ids_are_registered` 存量基线 FAIL——**实跑为绿**（S0 收编四条的登记已由并行席落盘，基线已收敛），本席未扩权触碰。

### 坐标门

`test_outbound_registry_campus_coordinate_is_live`（在 29 例内）绿；独立 grep 实证两轮（ruff 修正前后）：

```
$ grep -n "campus_record_matcher = on_message(" plugins/bot_unified_runtime/__init__.py
5027:        campus_record_matcher = on_message(
```

matcher 坐标 5027 全程零漂移；outbound_registry.py 本席零接触（其 M 状态系前席 note 字段+campus 条目刷新既有工作，git diff 实证内容与本席无关）。

### 静态门

```
$ venv/python -m ruff check plugins/bot_unified_runtime/domains/assistant/campus/campus.py plugins/bot_unified_runtime/__init__.py tests/test_campus_digest.py --no-cache
All checks passed!
```

（中途两处 ruff 错已修：I001=模块顶三名合并 import 超 88 行宽被 isort 拒 → 改函数级导入（见 Step 2 偏差记录）；RUF100=except 行 noqa: BLE001 冗余 → 去 noqa 留注释。）

```
$ venv/python -m mypy --cache-dir=$TEMP/u17impl3-mypy-cache --explicit-package-bases --ignore-missing-imports plugins
Success: no issues found in 635 source files
```

### 树卫生

源码树零污染：`find plugins tests -name __pycache__ -o -name .pytest_cache -o -name "*.pyc"` 零命中；无 `data/` 残留；mypy/pytest 缓存全部落在 `$TEMP`。qx.json 完好（本席未触碰 weather 域）。

## 改动面总账（本席净改动）

| 文件 | 改动 |
|---|---|
| `plugins/bot_unified_runtime/domains/assistant/campus/campus.py` | imports 收窄+增名；撤 `CampusForwardRequest` 脚手架；增 `CampusForwardPayload` 五字段载荷；`_build_forward_request`→`_build_forward_payload`（body 单一事实源不动）；增两 builder `build_campus_forward_message`/`build_campus_forward_capability`；服务类 docstring 去 SendRequest 字样 |
| `plugins/bot_unified_runtime/__init__.py`（仅 campus handler 段） | handler 尾段 `request`→`payload`；`send_queue.submit(request)` 旁路删除 → 中央管线 `pipeline.handle_async(message, _offload, capability_id="bot.campus_forward")`（review 门 fail-closed 随管线生效）；matcher 之下函数级导入两 builder；contracts 块/装配段/matcher 定义零触碰 |
| `tests/test_campus_digest.py` | 11 处 xfail 摘牌；2 例重写为 payload 级；顶部孤儿 contracts 导入移除；2 例 handler 测试落库日断言夹具修复（真实时钟，见 Step 3 缺陷记录） |

未触碰：outbound_registry.py、feature_catalog.py、config.py、llm_engine/、domains/chat_reply/、tests/test_affinity.py、AGENTS.md、HANDBOOK.md、.env。零 git 写操作、零 commit、零部署、未重启。

## 遗留与移交

1. 重启后才生效（铁律）；真机验收=acceptance-manual §6.6 校园段 + runbook §2.5.6。
2. 裁定点②生产 `BOT_RENDER_FORWARD_MIN_CHARS` 现值本席禁读未验（unknown）；1501 字边缘消息若嫌合并转发形态，纯配置面可调（≥1502）。
3. 本席三处 runbook 偏差均有证据化记录（offload 接缝/import 落点/夹具缺陷修复），供后续席与评审席复核。

U17IMPL-SEAT DONE

