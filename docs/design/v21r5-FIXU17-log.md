# v21r5 FIX-U17 席工作日志（关闭 U17-REVIEW-3 实锤的 I1/I2 两个 Important）

> 席位：FIX-U17。对象=U17-REVIEW-3 发现的 I1（泄拦面窄于文档+BLOCK 静默永久丢）与
> I2（门禁 BLOCK 永久丢失零可观测）。红线：纯监听零削弱、告警/日志不含源文本原文、
> 改动面仅 campus.py / root `__init__.py` campus 段 / tests/test_campus_digest.py / runbook 注记。
> 解释器：C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe
> 纪律：PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1；pytest --basetemp="$TEMP/fixu17-tmp*" -p no:cacheprovider
> 零 git 写操作、零 commit、零部署、未重启（重启后才生效）。

## 修复方案（实读定坐标后的最小落点）

1. **I1-泄拦面**（`domains/assistant/campus/campus.py` `_build_forward_payload` 出口）：
   `body` 出域前过 `domains/render/plain_text.py::redact_local_secrets`（真身路径 grep 定位；
   output/plain_text.py 为 shim）。只包出站正文——三重来源门/幂等/store 原文落库/截断预算/
   `build_campus_forward_text` 单一事实源逐字节契约全部零触碰（无哨兵形态文本打码器恒等）。
2. **I1-静默丢失 + I2-门禁 BLOCK 可观测**（root `__init__.py` campus handler 段，全部在
   matcher 坐标 5027 之下=零坐标漂移、outbound_registry.py 零触碰）：handler 消费
   `pipeline.handle_async` 回执（try/except/else 重构），`state is ReceiptState.BLOCKED`
   （review 泄拦/feature gate 停用/运行时暂停三类同路覆盖）→
   ①`logging.warning` 守岸人一句话「有一条校园消息因安全门未送达（capability=…gate=…session=…）」
   留痕（无源文本）；②嵌套 `_notify_campus_block` 走既有 runtime/alerts 通道
   `notify_operational_issue`（stage=campus、kind=blocked_<transport>（=拦截类别，kind 不截断）、
   detail=capability+目标会话 56 字符<60 截断窗、复用 operational_alert_suppression 防刷屏、
   best effort try/except 不反噬监听主链路）。不改管线 review 本体（共享咽喉零触碰）。
3. **I2-runbook 勘误注记**：§1.4 行为差表后新增「§1.4a 勘误注记」，只加注不改既有正文
   ——「路径形态命中即拦」修正为实际泄拦面 + redact 前置后的三路新行为
   （打码直达/拦截+可观测/永久丢失语义补充）。
4. **回归锁**（tests/test_campus_digest.py 新增 ⑤节两例 + harness env 补 `ReceiptState`
   注入——BLOCK 判定 `is` 比较每次执行都会求值该名）。

## 实测对照（全部实跑，输出原文）

### 前置实读证据

- reviewer 实际拦截面（`domains/render/reviewer.py:20-30`）：api_key/token/cookie/authkey/
  authorization Bearer/bearer sk-/裸 sk-≥9/注入标记；**无盘符路径、无 BOT_XXX=**（印证 REVIEW 席 D2）。
- 打码器占位：`<已隐藏>`/`<本机路径已隐藏>`（plain_text.py:310-311）；键值词干打码后
  值长 3<8 不触发二次匹配（替换产物幂等）；reviewer 词面对 `token=<已隐藏>` 仍命中
  （负向先行 `(?!(?:set|missing|\[redacted\])\b)` 不含该占位）→ 键值词干形态仍由 review 拦，
  与「打码直达」三形态（BOT_XXX=/盘符路径/sk-）分工互补。
- alert 链（root `__init__.py` 既有装配）：`_operational_alert_targets`(:3912)/`_deliver_admin_alert`
  (:3921)/`operational_alert_suppression`(:3888)/`_all_online_bots`(:3840) 均定义于 campus handler
  之前的同函数作用域；OperationalIssue/ReceiptState/RiskLevel/notify_operational_issue 皆模块顶导入。
- **坐标红线核验**：`campus_record_matcher = on_message(` 两轮 grep 均 **5027 行零漂移**
  （全部根文件改动落在 matcher 之下）；outbound_registry.py 本席零接触。

### Step 1 campus.py 打码前置 → 即时实跑

```
$ python -m pytest tests/test_campus_digest.py -q
29 passed in 5.53s        # 逐字节 verbatim 契约零回归（无哨兵形态打码恒等）
```

### Step 2 root `__init__.py` BLOCK 可观测 → 结构核验

```
$ grep -n "campus_record_matcher = on_message(" plugins/bot_unified_runtime/__init__.py
5027:        campus_record_matcher = on_message(     # 零漂移
$ python -c "import ast; ast.parse(...); print('AST OK')"
AST OK
```

### Step 3 回归锁两例落地 → campus 全文件

```
$ python -m pytest tests/test_campus_digest.py -q
...............................                                          [100%]
31 passed in 5.77s        # 29 例零回归 + 2 新例（打码断言/BLOCK 告警断言）
```

### Step 4 棘轮族合跑（campus + outbound_v21 + F3 + feature_gate + subfeatures）

```
$ python -m pytest tests/test_campus_digest.py tests/test_outbound_v21.py \
    tests/test_v21_f3_outbound_capability_registration.py \
    tests/test_runtime_feature_gate.py tests/test_runtime_subfeatures.py -q
........................................................................ [ 55%]
.........................................................                [100%]
129 passed in 16.42s      # U17IMPL 基线 127 + 本席 2 新例
```

（坐标棘轮 `test_outbound_registry_campus_coordinate_is_live` 含于上列 31 例内，绿。）

### Step 5 静态门

```
$ python -m ruff check plugins/bot_unified_runtime/domains/assistant/campus/campus.py \
    plugins/bot_unified_runtime/__init__.py tests/test_campus_digest.py --no-cache
All checks passed!        # 中途 2 错已修：RUF100（noqa: BLE001 冗余，去 noqa 留注释，
                          # 同 U17IMPL 先例）+ I001（harness 内 import 排序）

$ python -m mypy --cache-dir=$TEMP/fixu17-mypy-cache --explicit-package-bases --ignore-missing-imports plugins
Success: no issues found in 636 source files
```

### 树卫生

`find plugins tests -name __pycache__ -o -name .pytest_cache -o -name "*.pyc"` 零命中；
无 `data/` 残留；qx.json 完好（未触碰 weather 域）。

## 修复后行为总账（对照 REVIEW 席 I1/I2 原文）

| 场景 | 改前 | 改后 |
|---|---|---|
| 源群文本含 `BOT_XXX=`/盘符路径/裸 `sk-` | 原文裸奔直达主人（reviewer 无此三类词面） | 出站前打码 → 打码版直达（不再命中 review），`_unsafe_output_reasons(body)==[]` 有回归锁 |
| 源群文本含 `token=`/`cookie=`/`authorization: Bearer` 等 | review BLOCK → 主人零接收、零告警（静默永久丢） | 打码后仍被 review 词面拦（设计如此）→ BLOCK **不再静默**：告警+日志双通道，detail=capability/session/拦截类别，源文本零携带 |
| 门禁 BLOCK（控制面停用/运行时暂停） | 同上静默永久丢 | 同一观测路径覆盖（I2）；runbook §1.4a 注记补「不可恢复」知情 |

## 改动面总账

| 文件 | 改动 |
|---|---|
| `plugins/bot_unified_runtime/domains/assistant/campus/campus.py` | +import `redact_local_secrets`（域真身）；`_build_forward_payload` body 出口包打码（+4 行注释） |
| `plugins/bot_unified_runtime/__init__.py`（仅 campus handler 段，matcher 之下） | 嵌套 `_notify_campus_block`（走既有 alerts 通道）；handle_async 回执消费 try/except/else：BLOCK→warning 留痕+告警 |
| `tests/test_campus_digest.py` | harness env 补 `ReceiptState` 注入；⑤节两新例（打码断言+BLOCK 告警断言，真 notify 链仅 mock 叶子） |
| `docs/design/v21r5-u17-implementation-runbook.md` | 新增 §1.4a 勘误注记（只加注不改既有正文） |

未触碰：outbound_registry.py、config.py、llm_engine/、domains/chat_reply/、tests/test_affinity.py、
AGENTS.md、HANDBOOK.md、.env、管线 review 本体。纯监听红线零削弱（对学校群仍只读不写，
出站目标恒主人私聊；告警目标是管理员通道，非学校群）。

## 遗留与移交

1. 重启后才生效（铁律）；真机验收建议：构造含 `token=xxx` 的学校群消息 → 主人零接收但
   管理员侧收到 stage=campus kind=blocked_reviewer 告警 + 日志一句话（I1 静默消除实证）；
   构造含 `BOT_XXX=`/盘符路径消息 → 主人收打码版（I1 泄拦面收口实证）。
2. detail 截断窗 60 字符内装 capability+session（56 字符），拦截类别走 kind 字段
   （blocked_<transport>，不截断）——三要素全在告警行内，无信息丢失。
3. 告警复用 operational_alert_suppression 折叠抑制：同类 BLOCK 刷屏场景按既有窗口折叠，
   首条放行带折叠清单，防教务通知批量触码时告警风暴。

FIXU17-SEAT DONE — 2026-09-20
