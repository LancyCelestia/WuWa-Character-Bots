# UNI1 · fix1 台账（评审 C-1 阻断 + M-1/M-2/M-3 收口）

> 评审件 = `.superpowers/sdd/FRONTEND-AUDIT/review-UNI1-report.md`（针对 `f4f4572`）。
> 本台账 = 修复轮 1/5 的全部改动、实跑取证与注册项。工作树时点 HEAD=`7c566f7`（波次在飞，
> 锚点全部现场复grep）；本席零 git 写、零删除、未 build、未读 `.env`。

## 〇、总裁决（四条 finding 全部落地）

| Finding | 处置 | 证据 |
|---|---|---|
| **C-1（阻断）** | `node --test` 套件恢复**密封**：`labels.test.ts` 三件后端 `.py` 直读**全部删除**，跨语言同值移交新 pytest 门 `tests/test_webui_labels_backend_parity.py`（缺模块显式 `pytest.skip` 并点名路径） | §一（红→绿双向 + skip 分支活证） |
| **M-1** | **把活干完**（不留「单源+锁」话术）：`tokens.tsx` 的 `WINDOWS` 手抄 / `useState('24h')` / `t(\`calls.window.*\`)` 迁到 `labels.ts` 单源；该页同时清掉两处 `'—'` 字面量（§四-4）并入严检清单。`UNI1-impl.md` §〇 同步改写成实况 | §三 |
| **M-2（=评审 I-2）** | 负断言棘轮改 **shrink-only 下限**：全 `pages/` 目录扫描 + 「数量 ≤ 在册基线」 + 「每个命中必须仍在册」双断言，还债恒绿、新抄即红 | §四（探针三向实跑） |
| **M-3（=评审 I-1）** | 「后端可产出 reason 码 ⊆ 前端白名单」锁落在 **pytest 侧**（字面量扫描 + 动态点注册表 + 候选值溯源）；前端侧死条目锁 = `semantics.test.ts` 三向对账（白名单==zh==en，原已存在，逐条核验）；`isKnownReason` docstring 改为指向**真实存在**的两把锁 | §五（含首跑实抓 `not_recorded_reliably`） |

改动文件（全部在授权清单内）：`webui/src/lib/labels.ts`（注释锚点）、`labels.test.ts`（重写）、
`semantics.ts`（docstring）、`webui/src/pages/tokens.tsx`（迁移）、`tests/test_webui_labels_backend_parity.py`（新增，本席所有）、
`docs/design/unify-audit-20260919/UNI1-impl.md`（§〇/§二/§四/§五 修订）、本台账。
**`tests/test_webui_constitution.py` 未动**（pass 计数 29→29 不变，下限不抬不降，见 §六）。
locale 未动（只读，**无需新键**）；`layout-constitution.mjs`/`logs.tsx`/`graph/**`/`api-client.ts` 零触碰。

## 一、C-1：跨语言锁移交 pytest，node 套件恢复密封

**机制**（照裁定实施，未复议）：
- `labels.test.ts` 删除 `CONTROL_PLANE` 常量、`pyWindowLiterals` 解析器与两条直读后端用例；
  替换为「窗口跨度内部自洽」纯前端锁（键集=图谱枚举、`all:null` 无界、有限档恰为 1/7/30 天整），
  文件头写明密封纪律与移交指针。例数保持 8 → 总数 29 不变。
- 新 pytest 门只读源码字面量、不 import 不执行任何一侧代码；`_read_backend()` 对缺失文件
  `pytest.skip(f"后端模块缺失：{path}（控制面在本 checkout 属可选特性，随控制面整波入库）")`。
- **skip 分支非死代码的活证通道**：模块级测试缝 `UNI1_CONTROL_PLANE_DIR`（docstring 说明用途）。

**红→绿双向取证**（同一手法 = 干净克隆模拟：`%TEMP%` 内只放 webui 件，无 `plugins/` 兄弟树）：

修复前（`f4f4572` 原样，copy=`/tmp/uni1-fresh-195649/webui`）：
```
ℹ tests 23  ℹ pass 20  ℹ fail 3
Error: ENOENT ... Temp\uni1-fresh-195649\plugins\bot_unified_runtime\control_plane\metrics.py
Error: ENOENT ... Temp\uni1-fresh-195649\plugins\bot_unified_runtime\control_plane\webui_stats.py   （等）
exit=1
```
（评审说「至少 2 例红」——实测 3 例：两条后端对账 + 依赖它们之一的连带文件级失败。）

修复后（copy=`/tmp/uni1-fresh-after-200506/webui`，`node_modules` 以 junction 挂回——真干净克隆
`npm install` 后必有件，d3-force 是 graph-layout 的合法 **webui 内** 依赖）：
```
ℹ tests 29  ℹ pass 29  ℹ fail 0  ℹ cancelled 0
HERMETIC_EXIT=0
```

skip 分支实跑（`UNI1_CONTROL_PLANE_DIR=C:/definitely/not/here/uni1-skip-demo`）：
```
sssss
SKIPPED [4] ...: 后端模块缺失：C:\definitely\not\here\uni1-skip-demo\metrics.py（控制面在本 checkout 属可选特性，随控制面整波入库）
SKIPPED [1] ...: 后端模块缺失：C:\definitely\not\here\uni1-skip-demo\webui_stats.py（…）
5 skipped in 1.64s   SKIP_DEMO_EXIT=0
```

**密封性静态证明**：修复后 `labels.test.ts` 的全部 fs 目标 = `./labels.ts`、`../locales/{zh-CN,en}/common.json`、
`../pages/*`、`../components/semantic/semantic-state.tsx`——无一越出 `webui/`；
`grep -rn "plugins" webui/src/lib/*.test.ts` → 只剩注释里的移交说明。

## 二、新 pytest 门覆盖（5 例）

| 用例 | 断言 |
|---|---|
| `test_stats_window_enum_matches_backend` | `STATS_WINDOWS` 键集 == `metrics._WINDOW_SECONDS` == `webui_stats._WINDOW_SECONDS`（防把 422 送上生产） |
| `test_graph_windows_and_seconds_match_backend` | `GRAPH_WINDOWS` == `_WINDOWS` 键集；`WINDOW_SECONDS` 与三张后端闭集**逐项同值**，含 `all` 双侧同为 None（不造上界） |
| `test_buckets_match_backend` | `BUCKETS` == `_BUCKETS`（顺序敏感，等价旧 JS 锁全部语义） |
| `test_backend_failure_reason_codes_are_whitelisted` | 五件失败面（metrics/webui_stats/webui_knowledge/webui_plugins/webui_memory_graph）的 `_failure("source_unavailable", "码")` 字面量 ∪ **已注册动态点**候选码 ⊆ `KNOWN_REASONS`；动态点按 `(文件,变量)` 注册表治理：`metrics.py:430 reason`（候选自 `reason = "x" if … else "y"`）、`webui_knowledge.py:270/275 status`（候选自 `return "码", None`）——新增动态点不注册即红（评审 I-1「显式豁免」要求） |
| `test_backend_payload_reasons_are_handled_by_frontend` | 条目/组级 payload 的 `"reason"` 字面量（含 `*_REASON* =` 常量）⊆ `KNOWN_REASONS` ∪ `knowledge.tsx DISABLED_REASON_LABEL_KEYS` 键集 ∪ 防腐豁免（见 §五） |

## 三、M-1：tokens.tsx 迁移 + 视觉同一性证明

`tokens.tsx`：删 `const WINDOWS: StatsWindow[] = ['24h','7d','30d']`；`useState<StatsWindow>('24h')`
→ `useState<StatsWindowCode>(DEFAULT_WINDOW)`；`WINDOWS.map` → `STATS_WINDOWS.map`；
`t(\`calls.window.${item}\`)` → `windowLabel(t, item)`；`block.value === null ? '—' : formatInt(...)` ×2
→ `formatInt(block.value)`；api-client 的 `StatsWindow` 型引用移除。

**操作者所见逐键对照（前 = 渲染取值链，后 = 渲染取值链，值 = 双语 locale 实dump）**：

| 按钮 | 前（键 → 值） | 后（键 → 值） | 等 |
|---|---|---|---|
| zh×3 | `calls.window.24h/7d/30d` → 「近 24 小时/近 7 天/近 30 天」 | `window.24h/7d/30d` → 「近 24 小时/近 7 天/近 30 天」 | ✅ 逐字 |
| en×3 | 同上 → Last 24 hours / Last 7 days / Last 30 days | 同上 → 同三串 | ✅ 逐字 |
| 缺省态 | `useState('24h')` → queryKey `['stats-tokens','24h','page']`、24h 按钮高亮 | `useState(DEFAULT_WINDOW)` 值 `'24h'` → queryKey/高亮同 | ✅ |
| 空值格 ×2 | `null ? '—'(U+2014) : formatInt(v)` | `formatInt(null)` → `UNKNOWN_VALUE`(U+2014)（format.ts:14-16 实测）；非 null 两侧同走 `formatInt` | ✅ 同字节 |
| DOM | 按钮类名/结构零改动 | 同（宪法门 exit=0 复跑，见 §七） | ✅ |

**副证——严检锁活的证据**：本席迁移后写在 tokens.tsx 的头注释含字面 `const WINDOWS` 与
`` t(`calls.window.*`)``，**立即被新加该页进严检清单的两条负断言打红**（npm test 首跑 fail 2），
改写注释措辞后才绿——锁对本席自己也开火，不是摆设。

迁后格局：`const WINDOWS` 手抄全树仅剩 `memory-graph.tsx`（只读面，在册 §四-2）；
`calls.window.*` 镜像表失去最后一个消费者 → 转 §四-11 登记待删（locale 只读，本波不删；
删前值等由 `labels.test.ts` 镜像锁钉死）。**因此 §〇 无需靠「话术」——残余只剩一处手抄 + 一张孤儿表，均有机器锁。**

## 四、M-2：棘轮三向探针实跑（`%TEMP%/uni1-ratchet-200857/probe.mjs`，副本上演，不碰工作树）

新棘轮语义 = `readdirSync(pages/)` 全扫描 + `count ≤ 基线(1)` + `每个命中 ∈ 在册清单`：

```
A 现树     ["memory-graph.tsx"] 新棘轮 => {"countOk":true,"allKnown":true} | 旧棘轮会红？ true
B 还债后   []                  新棘轮 => {"countOk":true,"allKnown":true} | 旧棘轮会红？ true
C 新抄一枚 ["affinity.tsx","memory-graph.tsx"] 新棘轮 => {"countOk":false,"allKnown":false} | 旧棘轮会红？ true
```

解读：B 行 = 「下一席迁完 memory-graph」**不再砸门**（f4f4572 的 `deepEqual` 精确清单在 B 上必红，
右列实证——这正是评审 I-2 的病根）；C 行 = 新页再抄枚举 → 双断言同时转红（评审担心的方向零漏防）。
A 行右列 true 还说明：**旧棘轮在 fix1 之后本来就已经站不住**（tokens 迁完即红），换 shrink-only 是必须。

## 五、M-3 / I-1：reason 锁 + 首跑实抓

- **pytest 侧**（§二第 4/5 例）：后端产出码 ⊆ 白名单 的机器锁已立。`isKnownReason` docstring
  原先自述的用途从此有了实体。
- **前端侧死条目锁**：`semantics.test.ts` 既有两例覆盖——「白名单逐项在双语 locale 有值」+
  「三向对账：白名单 == zh 键集 == en 键集」（任何一侧多键即红 → 白名单里不可能存在无上屏文案的
  死条目，也不可能存在有文案没登记的码）。本席核验未削弱，未改该文件。
- **首跑实抓一枚**（本锁价值当场兑现）：payload 锁抓到 `metrics.py:200/:205`
  `"reason": "not_recorded_reliably"`（attempt_total/failover_calls 质量块）。核查：api-client
  `TokenBlock` 无 reason 字段、`attempt_total|failover_calls|provider_identity_quality` 在 webui/src
  **0 消费者**（grep 实测）→ 永不上屏，属豁免而非缺陷。登记进
  `NON_RENDERED_PAYLOAD_REASONS` 并配**防腐断言**：该码一旦出现在 webui/src 任何 .ts/.tsx/.json
  （前端开始消费）或从登记的后端文件消失（后端挪家），锁转红。同时补 §四-12 台账行。
- 另把评审 M-4（`latency.tsx:92` 整句内嵌裸码 `not_persisted`）补登 §四-13——fix1 前清单确实漏了它。

## 六、计数与门形状

- `node --test`：**29 例**（graph-layout 7 + semantics 14 + labels 8）→ 与 `f4f4572` 基线**同数**，
  故 `test_webui_constitution.py:114` 的 `passed >= 29` 下限与其说明串**原样未动**（任务书只允许在计数变化时动数——没变）。
- `tests/test_webui_labels_backend_parity.py`：**+5 例**（本席所有）。
- `tests/test_webui_constitution.py`：5 例（他席所有，未动）。

## 七、验证汇总（全部本席实跑；venv=`../ChatBot_Runtime/venv`，零缓存纪律见命令）

**终验 = 本台账落盘前的最后一轮全链复跑**（含 labels.ts 注释改动与 §八 注册之后，树形如 HEAD=`7c566f7`+本席在飞件）：

```
cd webui && npx tsc --noEmit -p tsconfig.app.json      → 无输出              TSC_EXIT=0
cd webui && npm test                                   → tests 29 pass 29 fail 0 cancelled 0   NPM_TEST_EXIT=0
cd webui && npm run lint:layout                        → stdout 含「全部通过」  LINT_EXIT=0
  （自测计数 102/102 为他席在飞改动——宪法脚本归另席，本席未触碰）
PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 venv python -m pytest
    tests/test_webui_labels_backend_parity.py tests/test_webui_constitution.py
    -p no:cacheprovider --basetemp=../ChatBot_Runtime/cache/pytest_unifix/basetemp -q
  → 10 passed in 5.15s                                PYTEST_EXIT=0
干净克隆模拟（终版件，copy=%TEMP%/uni1-final-*，无 plugins/ 兄弟树，node_modules junction 回挂）：
  → tests 29 pass 29 fail 0 cancelled 0               FINAL_HERMETIC_EXIT=0
门形状（常驻门同形，前轮实跑）：node --test --test-reporter=tap "src/**/*.test.ts"
  → # tests 29 / # pass 29 / # fail 0 / # cancelled 0
```

树卫生（终验后复查）：`find . -name __pycache__` = **0**；无 `.pytest_cache`/`.ruff_cache`
（`.mypy_cache/3.12` 为存量他席件，未触碰）；本席 diff 面 = §〇 所列 8 件，无它。

## 八、注册与移交（本波不动的）

| 项 | 去向 |
|---|---|
| `calls.window.*` 孤儿镜像表删除（双语 ×3 键） | impl §四-11；需 locale 写权席（删表须同步跑双语对账锁的自然退役） |
| `memory-graph.tsx` 枚举迁移 | impl §四-2（graph 席在飞；迁完棘轮计 0，框架保留防新页手抄） |
| `logs.tsx:98` `'—'` 字面量 | impl §四-3（坐标已按现树更正） |
| `not_recorded_reliably` 豁免 | impl §四-12 + pytest `NON_RENDERED_PAYLOAD_REASONS`（防腐断言随跑随验） |
| `latency.tsx:92` 裸码整句 | impl §四-13（文案口径，等用户裁） |
| locale 新键需求 | **无** |

## 九、纪律自证

零 git 写（HEAD/diffstat 仅 `git log/diff --stat` 只读）；零删除（temp 取证用**新建唯一目录**代替清理，
`rm` 本 shell 不可用亦未绕）；未跑 build/`tsc -b`/`npm install`；只写授权清单 8 件文件；
三个后端 `.py` 全程只读；未读未印 `.env`；操作员可见文本**变化集 = 空**（§三 对照表；
tokens 页按钮/空值格/queryKey 逐字节同前）。

—— UNI1 fix1 席，2026-09-19/20 之交落盘。
