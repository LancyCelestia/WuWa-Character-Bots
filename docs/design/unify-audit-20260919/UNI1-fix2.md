# UNI1 · fix2 台账（对账门补强轮 2/5：评审 I-1 / I-2 / I-3 + Minor M-a / M-b）

> 被修对象 = `tests/test_webui_labels_backend_parity.py`（fix1 新建、随 `45d3874` 入库的跨语言对账门）。
> 评审件 = `.superpowers/sdd/FRONTEND-AUDIT/review-UNI1-fix1-report.md`（变异探针 M1–M13 + 棘轮探针 A/B/C 系）。
> 三枚 Important 已由评审变异实审定性（M6/M13/M12 修前门绿），本席不复议、只修 + 双向自测。
> 工作树时点 = 2026-09-20 凌晨（v21r5 波在飞）；本席零 git 写、零删除、未 build、未跑
> `verify_hashes/doc_sync/command_catalog --write`、后端 `.py` 与前端在写面全程只读；
> 一次性件与克隆全部在 `%TEMP%/uni1fix2-harness/`，pytest 全程
> `PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 -p no:cacheprovider --basetemp=` 指仓库外
> （`../ChatBot_Runtime/cache/pytest_uni2/` 或 harness 目录）。

## 〇、总裁决

| Finding | 处置 | 双向证据 |
|---|---|---|
| **I-1**（M6：payload 面动态赋值零报警） | payload 扫描从「三张字面量正则」改为**逐点值表达式分类器**：静态可判定形态（字面量/双分支字面量三元/`None if … else "码"`）取码进判据；f-string / `.format(` / 变量 / 调用等**不可判定点必须登记** `PAYLOAD_DYNAMIC_REASON_SITES`（键=(文件, 值表达式原文)）并给溯源规则，不注册即红、注册了解出的候选码继续过该文件所属面的判据——**无静默跳过路径** | M6 变异 → RED；PC2 等价重写 → GREEN |
| **I-2**（M13：全局并集稀释组级严判→裸码门绿上屏） | `test_backend_payload_reasons_are_handled_by_frontend` 改**按文件分面**：`plugins/stats/metrics/memory_graph` 四面 ⊆ `KNOWN_REASONS`（describeReason 消费链，白名单独走）；短标签并集**只**给 `webui_knowledge.py` 一面（`SHORT_LABEL_FACET_FILES`，knowledge.tsx 短标签表唯一消费面）；豁免 `NON_RENDERED_PAYLOAD_REASONS` 从全局码集改为 (码→登记文件) **按文件生效**。test 4（_failure→白名单严判）原样未动（M9 已证其本来就严） | M13 变异（组级 `= "no_dedicated_store"`）→ RED，且失败消息点名「本面判据=白名单」；PC1 还债 → GREEN |
| **I-3**（M12：docstring 宣称锁 metrics 桶集、实现只读 `_BUCKETS`） | **选「实现追上宣称」**（理由见 §二）：`test_buckets_match_backend` 增解析 `metrics.py` 两张**内联**桶组——`bucket not in (…)`（trends 422 准入门，即 :278 那枚）与 `view in (…)`（`_read` 分派门）——集合比较 ⊆/== 前端 `BUCKETS`；锚点解析不到=断言红点名同步。docstring 同步改写为逐锚点描述并**诚实划界**（`_GROUP_EXPRESSIONS` 的 hour/day 键是内部 SQL 映射、非前端可达面，明文写出不在宣称内） | M12 变异（准入门删 `"day"`）→ RED；M12b（分派门删值）→ RED；真树 → GREEN |
| **M-a**（未登记页新 `'—'` 门绿） | **封**（在本席写权的 pytest 侧，非 labels.test.ts——它无写权）：新例 `test_page_unknown_symbol_literals_are_ratcheted` 扫 `pages/*.tsx` **全部页面**，`'—'` 字面量/`>—<` 内联命中数 ≤ 在册基线 `UNKNOWN_SYMBOL_DASH_DEBT`（现仅 `logs.tsx: 1`，即 impl §四-3 在册债）；新页/新枚一律红，还债（命中减少）恒绿 | B3p 探针（knowledge.tsx 新写 `'—'`）→ RED；Ap 探针（还清 logs+迁走枚举）→ GREEN |
| **M-b**（棘轮基线清单自身无锁） | **封**：新例 `test_enum_ratchet_baseline_is_honest` 机器核验 labels.test.ts 的 `trackedUnmigrated`——①锚点正则解析不到（清单改名/删除）即红；②基线每个条目必须指向**真实存在**的 pages 文件（改名换假页即红）；③实际扫到的 `const WINDOWS` 页必须仍在册（把真债页摘出清单即红）。还债不砸门：语义取「命中 ⊆ 清单」超集允许（迁完不清单仍绿，与 fix1 M-2 shrink-only 同规） | C3p（换页为存在的非债页）→ RED；C3bp（清单整串改名）→ RED；Ap → GREEN |

改动文件 = 授权清单内 **2 件**：`tests/test_webui_labels_backend_parity.py`（重写判据，5 例 → **7 例**）、
本台账。**`webui/src/lib/labels.ts` 未加任何新导出**——分面判据全部由解析既有导出
（`KNOWN_REASONS` / `DISABLED_REASON_LABEL_KEYS`）达成，授权的「加导出」通道本波无需动用，
前端判定语义零触碰；`describeReason` 未知码原样上屏策略 = 已登记待用户裁的 R-2，**一字未动**
（本席修的是门抓不到，不是界面藏起来）。

## 一、判据结构（修后终形，评审复跑对照用）

- **面 4（DataState 严判，未动）**：`_failure("source_unavailable", 字面量)` ∪ 已注册动态点
  （`DYNAMIC_REASON_SITES`：metrics.reason / webui_knowledge.status，溯源规则同 fix1）⊆ `KNOWN_REASONS`。
- **面 5（payload，按文件分面）**：站点扫描器 = `"reason": <expr>`（dict 条目）+ `["reason"] = <expr>`
  （下标赋值）+ `*_REASON* = "码"`（模块常量定义，保守计入其所在文件）。逐 expr 分类：
  - 静态形态 → 候选码进**该文件的面**判据：plugins/stats/metrics/memory_graph = 白名单（+该文件登记豁免）；
    knowledge = 白名单 ∪ 短标签集。
  - 不可判定形态 → 动态点，键=(文件, expr strip 原文) 查 `PAYLOAD_DYNAMIC_REASON_SITES`：
    不注册=红（M6 路封死）；注册=按声明规则解候选码再过同一判据，规则解不动（注册腐烂/常量改名/
    return 形态漂移）=断言红点名重审。
- **在册动态点全录（8 枚，均为现存代码显式化，非新增豁免）**：
  五件 `_failure` 助手体 `{"reason": reason}` → `failure_helper_forward`（本体零候选，调用点已由面 4 严判；
  规则附带「本文件确有 `def _failure(`」防注册腐烂）；
  `webui_knowledge.py` `None if kb_status == "ok" else kb_status` 与 `None if meme_status == "ok" else meme_status`
  → `status_return_codes`（候选 {missing_source, incomplete_schema} ⊆ 白名单，走 `_STATUS_RETURN_LINE`）——
  fix1 门对这两点正是**静默滑过**的实例（pattern 2 只吃 `else "字面量"`），本轮起在册受检；
  `webui_knowledge.py` `_NOT_AVAILABLE_REASON` → `reason_constant`（常量字面量 `no_dedicated_store`
  ∈ knowledge 面短标签集——它**只**能出现在这块面，挪去 plugins 即 M13 同款红）。
- **豁免按文件**：`not_recorded_reliably → metrics.py`；同码出现在别面不再被全局豁免稀释
  （fix1 松侧的另一处顺带收口）；防腐双断言原样保留。
- **面 6/7（新增，纯前端件不依赖后端 → 不受 `UNI1_CONTROL_PLANE_DIR` skip 缝影响，恒真跑）**：见 §〇 表。

## 二、I-3 选路说明：为什么「实现追上宣称」而非「docstring 改口」

两个内联锚点都是单行字面量元组（`bucket not in ("hour", "day")` / `elif view in ("hour", "day"):`），
正则一次匹配 + 解析不到即响亮红，与门内其它解析器同一风险等级——读它**可靠**。
docstring 改口只在「读不动/形态复杂」时才优于补实现，此处不成立；且 422 防线的语义本体就是这两张门
（`_BUCKETS` 只是命名常量那份），只锁 `_BUCKETS` 的锁名不副实。内部 SQL 映射 `_GROUP_EXPRESSIONS`
确实不该进前端对账面（非用户输入可达），已在 docstring 明文划界，不另立锁。

## 三、双向自测总表（全部实跑；venv=`../ChatBot_Runtime/venv`，命令见 §五）

**后端面（`UNI1_CONTROL_PLANE_DIR` 指入 `%TEMP%/uni1fix2-harness/<tag>` 变异副本，只跑 parity 文件，修后终形件）**：

| 探针 | 变异 | 修前（fix1 门，评审实测） | 修后实跑 | 红在哪例 |
|---|---|---|---|---|
| M6（I-1） | webui_plugins.py 追加 `group["reason"] = f"generated_{code}"` | **GREEN**（静默滑过） | **exit=1，1 failed/6 passed** | `test_backend_payload_reasons_are_handled_by_frontend`（未注册动态点，消息含精确键 `f"generated_{code}"`） |
| M12（I-3） | metrics.py `bucket not in ("hour", "day")` → `("hour",)` | **GREEN** | **exit=1，1 failed/6 passed** | `test_buckets_match_backend` |
| M12b（加验） | metrics.py `view in ("hour", "day")` → `("hour",)` | （评审未做） | **exit=1，1 failed/6 passed** | 同上（第二锚点也有牙） |
| M13（I-2） | webui_plugins.py `group["reason"] = "no_dedicated_store"` | **GREEN**（最危险路） | **exit=1，1 failed/6 passed** | payload 例，消息点名「本面判据=白名单 KNOWN_REASONS」→ `['no_dedicated_store']` |
| PC1 还债=绿 | knowledge `"reason": _NOT_AVAILABLE_REASON` → `"reason": "missing_source"`（动态点退役，登记变陈旧被容忍） | — | **exit=0，7 passed** | — |
| PC2 等价重写=绿 | plugins `group["reason"] = "domains_dir_unavailable"` → `None if False else "domains_dir_unavailable"`（同码静态换形） | — | **exit=0，7 passed** | — |
| PC3 近似合法=绿 | knowledge 新分支 `return "missing_table", None`（既有 status 注册点新增白名单内候选码，零登记动作） | — | **exit=0，7 passed** | — |

**前端棘轮面（克隆仓=`%TEMP%/uni1fix2-harness/<tag>/repo`，含 tests 件 + webui/src，后端指真树未变异件）**：

| 探针 | 变异 | 结果 | 红在哪例 |
|---|---|---|---|
| B3p（M-a 复现） | 未登记页 knowledge.tsx 新写 `const PROBE_DASH = '—';` | **exit=1，1 failed/6 passed** | `test_page_unknown_symbol_literals_are_ratcheted`（消息含计数 1>0） |
| C3p（M-b 复现） | labels.test.ts 基线换页：memory-graph → calls（存在但非债页） | **exit=1，1 failed/6 passed** | `test_enum_ratchet_baseline_is_honest`（命中 ⊄ 清单） |
| C3bp（M-b 变体） | `trackedUnmigrated` 整串改名 | **exit=1，1 failed/6 passed** | 同上（锚点解析不到=形态漂移红） |
| Ap（还债正控） | logs.tsx `'—'` 还清 + memory-graph 枚举迁走（两处清单都不许动） | **exit=0，7 passed** | — |

**skip 分支活证（fix1 形状变更登记）**：`UNI1_CONTROL_PLANE_DIR=C:/definitely/not/here/uni2-skip-demo` →
`2 passed, 5 skipped`，exit 0——后端五例（1–5）照旧整体 skip；新增例 6/7 为纯前端棘轮，**设计上不受
skip 缝影响恒真跑**（否则 M-a/M-b 在干净克隆上又成休眠门）。fix1 台账「5 skipped」口径由此更新为
「5 skipped + 2 前端恒跑」。

## 四、门形状与计数（修后）

- parity 文件：5 例 → **7 例**（+2 前端棘轮）；真树 scoped 合跑 parity+constitution = **12 passed**。
- node 侧 `49 pass / 0 fail` 不变（本席未触任何 webui 件）；`test_webui_constitution.py` 未动（他席所有）。
- 判据收紧清单（计数升且断言**变严**，非「计数升断言弱」）：payload 面并集→分面；豁免全局→按文件；
  动态赋值点无感→必登记；桶锁单源→三锚；新增两枚全页面/基线自锁棘轮。

## 五、完工实跑（本席最后一次全链，含 re.M→re.MULTILINE 别名归一后的终形件）

```
PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 venv python -m pytest
    tests/test_webui_labels_backend_parity.py tests/test_webui_constitution.py
    -p no:cacheprovider --basetemp=../ChatBot_Runtime/cache/pytest_uni2/basetemp -q
  → 12 passed in 5.82s                                  PYTEST_EXIT=0
cd webui && npm test（重定向后直取 $?）
  → tests 49 / pass 49 / fail 0 / cancelled 0           NPM_TEST_EXIT=0
cd webui && npx tsc --noEmit -p tsconfig.app.json        TSC_EXIT=0
venv python -m ruff check --no-cache tests/test_webui_labels_backend_parity.py
  → All checks passed!                                  RUFF_EXIT=0
  （注：HEAD 版该文件在 ruff 0.16.4 下有 7 枚 FURB167 `re.M/re.S` 别名告警——
    修前已存在的静态门残红，本席文件顺手归一为 `re.MULTILINE/re.DOTALL` 清零；未跑全树 lint，它席在飞。）
venv python -m mypy --cache-dir ../ChatBot_Runtime/cache/mypy_uni2 <本件>
  → Success: no issues found in 1 source file           MYPY_EXIT=0
变异矩阵（§三两张表）                                    全部按预期 RED/GREEN
```

树卫生：本席全部运行零缓存入树（ruff `--no-cache`、mypy 缓存指 Runtime、pytest 无 cacheprovider、
basetemp 全在仓库外、`PYTHONDONTWRITEBYTECODE=1`）；`find plugins tests webui` 零 `__pycache__`/`*.pyc`。
仓库根 `.mypy_cache/`、`.ruff_cache/` 两目录 CACHEDIR.TAG 时间戳=09-19 17:58 / 09-20 00:53，
**均早于本席运行**，系他席在飞产物，按规程未删未触。git 写=零（状态查看仅 `git show/status` 只读）。

## 六、担心但没动的东西（登记，不扩大本席面）

1. **`_failure("invalid_request", …)` 码族无锁**：`invalid_bucket/invalid_window/invalid_limit/
   invalid_order/invalid_collection/invalid_page/…` 不经面 4 的 `"source_unavailable"` 严判，
   但经 api-client 的「非 ok 带 reason 一律降级」同样会到 describeReason → 裸码上屏。
   前端只发白名单参数、正常永不触发；要扩锁先裁语义（422 类码属「客户端 bug 诊断面」，裸码或许恰是对的）。
2. **五件闭包之外的 reason 面**：`llm_admin.py`（`no_sample` 不在白名单）、`resources.py`
   （`warming_up/counter_reset/…`）、`platform.py`、`api/v1.py`——fix1 溯源闭包未含、评审探针亦未打，
   属 legacy/资源端点消费面；扩闭包=改分面地图，另批裁。
3. **M-c（豁免防腐=「串不在 corpus」而非「面不被泛渲染」）**：评审原级 Minor，维持原状；
   豁免新增（现 1 枚）时应按 M-c 建议复核消费面而不只 grep 串。
4. **`describeReason` 未知码原样上屏** = R-2 用户裁定件，本席一字未触。
5. **payload 动态点键=值表达式原文**：后端给注册行加行尾注释/折行会改键 → 门红要求重登——
   设计上的响亮性，但对重构席偏烦；如嫌吵可下批改「行号无关的规范化键」，本波不动。
6. **labels.test.ts 基线与我面 7 的镜像**是双账：还债后 nodes 侧陈旧条目无害（超集允许），
   收尾席清账时请只删条目、保留 `const trackedUnmigrated = [` 锚点名（本席 M-b 锁依赖该锚）。
7. **三件后端 `.py` 未入库** → 面 1–5 在干净克隆/CI 上恒 skip（fix1 Verdict A 既有接受面）；
   本席新增两面 6/7 正是为此特意做成零后端依赖，任何克隆上恒开火。

## 七、纪律自证

只写 §〇 所列 2 件；后端三件+两件 `.py` 全程只读（变异一律 `%TEMP%` 副本上演）；
前端 lib/pages/locales/constitution/logs/graph 零触碰；零 git 写、零删除、未 build、
未跑任何 `--write` 生成器；未读 `.env`；操作员可见文本变化集 = **空**（本席只改 pytest 门与写本台账）。

—— UNI1-FIX-2 席（修复轮 2/5），2026-09-20 凌晨落盘。
