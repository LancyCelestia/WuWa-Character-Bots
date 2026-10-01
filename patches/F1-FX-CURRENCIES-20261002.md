# F1 工单 · 汇率币种补齐（P7；卢布/瑞郎/加元/澳元）— 2026-10-02

席位：F1（独占面＝`domains/finance/data/fx_data.py` + `domains/finance/capabilities/fx.py` + 新建测试 + 本工单）
HEAD 起点＝`5d581b2`。本席**零 git 写、零进程动作、零外发、零配置改**（未新增 config 键，故无 CONFIG-REQUEST）。
所有网络出口全部 monkeypatch；可达性实探一律列进 §5.1 待验清单交主会话。

> **一句话交付**：四枚币今天**没有任何已核实的报价腿**，所以本席没把它们写进宇宙表（写了＝编源），
> 而是建成**三态名册＋凭据册＋五把门**：待验者被端到端地诚实拒答并点名候选腿；
> 真机核实之后**加一行即全链通**（本工单附促升演练证明，不是口头承诺）。
> 顺手接通了 `fx_data` 头注从一开始就承诺、却从未接进能力层的 USD 三角换算，
> 因此「英镑/韩元/新加坡元汇率」这类问句不再答「暂无数据」。

---

## ① 现状核实（file:line；行号为**改动前 HEAD 当时值**，本波会漂，认符号名不认行号）

| 锚点 | 改动前真身 | 读数 |
|---|---|---|
| 在册币种名册 | `fx_data.py:62-74` `SUPPORTED_CURRENCIES` | 11 枚：USD/EUR/GBP/JPY/KRW/TWD/CNY/HKD/SGD/MOP/AED（当时值）。与用户点名 11 枚（USD/EUR/JPY/KRW/CNY/HKD/SGD/RUB/CHF/CAD/AUD）重合 **7**（`comm` 现算，非手抄） |
| 活源真身（唯一会外呼的面） | `fx_data.py:271-282` `_FX_PAIR_UNIVERSE` | 10 个货币对，涉及 8 枚币（USD/CNY/EUR/JPY/KRW/HKD/SGD/GBP）；RUB/CHF/CAD/AUD **整片不在** |
| 实测查无名册 | `fx_data.py:300` `FX_UNAVAILABLE_PAIRS` | USD/TWD、USD/MOP、USD/AED（2026-09-12 suggest 实测） |
| 别名/展示名 | `fx_data.py:487-515` `_CURRENCY_ALIASES`、`:530-542` `_CURRENCY_DISPLAY` | 均无新四币 ⇒ `parse_fx_query("卢布汇率")` 返回 `None` ⇒ **掉回面板＝答非所问**（S02 工单 §9-3 同判） |
| 第二份码清单 | `fx_data.py:594-597` `has_currency_term` | 函数体内**硬抄第二份 11 枚 ISO 码**（`_VALID_CODES` 已有正身）⇒ 扩币必「面板有、触发词没有」分裂 |
| 换算通路 | `fx_data.py:217-241` `cross_rate_from_usd` | 头注 `:23-24` 自陈「其它基准货币间的交叉价用 `cross_rate_from_usd` 按 USD 三角换算」，但 `git grep` 现算：**全树只有 `tests/` 引用它，能力层零调用点** ⇒ 承诺过、没接线 |
| 能力层拒答 | `fx.py:236-240` | 写死一句「暂无数据（**东财无该货币对行情**）」——对未探过的币这是**未经核实的断言**（把「还没查」说成「查无」） |
| 卡面缺席行 | `fx.py:111-119` | `sub` 写死「上游无该货币对行情」，同上 |
| 帮助册宣称 | `echo.py:1711-1714`；生成物同句 `docs/command-catalog.md:1749-1751` | 「覆盖 11 币种（USD/EUR/GBP/JPY/KRW/TWD/CNY/HKD/SGD/MOP/AED）」＋手写计数 |
| 前席同域账 | `patches/S02-FINANCE-COVERAGE.md` §2.1/§4 批 B | RUB/CHF/CAD/AUD 全部标 **待验**，并立判据「有源只认两种凭据：①模块头注自陈实测 ②本波真机重探落日期＋形态」；§9-4 点名 `has_currency_term` 的第二份码 |

**判据**：本席同样**没做真机实探**（禁外发）⇒ 四枚币今天既不能写「有源」也不能写「查无」，唯一诚实态是第三态。

---

## ② 改法与理由

### 2.1 三态名册＋凭据册（把「绝不编数」做成代码级防线，不是散文约定）

`fx_data.py` 新增（现行锚点，认符号名）：

- `REQUIRED_CURRENCIES`（`:87`）＝用户点名 11 枚，是「逐币必须有一票」对账的尺。
- `SUPPORTED_CURRENCIES`（`:103`）补 RUB/CHF/CAD/AUD ⇒ 在册面 = 点名 ∪ 历史清单（**在册≠有源**，这是本次改动的核心区分）。
- `_FX_SOURCED_EVIDENCE`（`:358`）secid→(实测日期,实测方式)；`_FX_ABSENT_EVIDENCE`（`:373`）货币对→查无凭据。**宇宙表里出现无凭据的 secid ＝ 把待验编成有源，门① 当场红**。
- `FX_PENDING_CANDIDATE_SECIDS`（`:384`）：每币三条候选腿——直盘**两个报价方向**（`119.USD<CUR>` 与 `119.<CUR>USD`，因 CAD/AUD 惯用方向是 `<CUR>/USD`，只探一侧会把有源误判成无源）＋ 中间价一族（`120.<CUR>CNYC`，命名规律来自已实测的 `EURCNYC/JPYCNYC/HKDCNYC`）。
- `FX_PENDING_FALLBACK_LEGS`（`:397`）：第二腿在册——er-api 快照链路（代码已实现、本机实测不可达）；RUB 另有 `iss.moex.com`（**主机** 2026-09-12 实证可达，见 `market_data.py:15-17`，**外汇端点未探**）；CHF/CAD/AUD **明写没有第二腿**。
- `_FX_PAIR_ABSENT_NOTE`（`:349`）＝「查无」这句话的唯一真身，覆盖表与用户可见拒答同读此处（不起第二份「暂无」文案）。
- 读点：`fx_currency_availability()`（`:453`，币种级三态）、`fx_pair_availability()`（`:429`，由二分扩成 **eastmoney/cross/unavailable/pending 四态封闭**，实测源永远优先、不重复发票）、`fx_unquoted_currencies()`（`:486`）、`fx_missing_note()`（`:507`）、`fx_missing_sub()`（`:540`）、`fx_no_quote_reason()`（`:547`）。
- `probe_fx_candidates()`（`:743`）：一次批量把候选腿打给**已实证的同一出口** `_fetch_payload`，逐币报「有行且 f2 有限正数／无行／非数／异常」。**纯运维/验收入口，生产链路零调用**（AST 锁执法，见门③附证）；不写缓存、不动宇宙表。

### 2.2 接通 USD 三角换算（把早已承诺的通路接进能力层）

`fx_usd_bridge()`（`:645`）＋`fx_per_usd()`（`:623`）＋`fx_derived_quote()`（`:669`）＋静态推断 `_spot_usd_legs()`（`:571`）/`_derived_pair_legs()`（`:605`）：

- **只吃 `rate_type=="spot"` 且与 USD 直接成交的行**；中间价（parity）行不参与——一格数字混两种口径正是「基准/中间价显式」红线的反面。
- 产出 `FxRate(rate_type="derived", unit_base=1.0)` ＋口径说明句「由 `<腿1>` 与 `<腿2>` 两条现货报价按 USD 三角换算：非中间价、非可成交价、延迟行情」；时点取两条腿里**较早**的那个，不造新时间戳。
- 缺任一腿／非有限值／`base==quote` ⇒ `None`（不硬凑、不用常数顶替）。
- **面板卡仍只列实测源行**，`derived` 不进面板（避免与中间价同格混口径）；换算只服务定向问句。
- 今天因此立刻受益的是 GBP/KRW/SGD 兑人民币（`_derived_pair_legs()` 现算输出，当时值＝3 对）——这三枚**本来就在帮助册里宣称覆盖**，此前却回「暂无数据」。

### 2.3 能力层（`fx.py`）

- 回答顺序改为：实测直盘 → 反向命中（倒数并标注，**逐字不变**）→ `fx_derived_quote` → 三态拒答（`:265-286`）。审计标签新增 `fx:cross:<对>`。
- 拒答话按态分列（`:270`）：查无＝「东财无该货币对行情」；待验＝「RUB（卢布）尚未接入已核实报价源，候选 119.USDRUB/119.RUBUSD/120.RUBCNYC 待真机核实」；未登记＝「没有可核的数就不报」。**待验币不再被说成查无**。
- 缺席可见（`:247`＋`:334`）：`missing_note = fx_missing_note(rates)` 一次算好，同供纯文本面板与卡面；卡面 `sub` 改走 `fx_missing_sub()`（新增可选参 `missing_sub`，缺省＝旧文案，既有调用方零改动）。三类缺席（实测查无／候选待验／**本轮上游缺行**）分句分列，限流空响应不再被掩成「没这个币」。
- `_FX_NON_HINT_RE`（`:60`）补 `(?:增加|追加)元素`：新收币名「加元」是「增加元素」的子串，沿用既有 话术/积分 的整句让路形态，不起第二把尺。

### 2.4 名册单一真身

- 别名表补 11 条（简/繁：卢布/俄罗斯卢布/盧布/俄羅斯盧布、瑞郎/瑞士法郎、加元/加拿大元、澳元/澳大利亚元/澳洲元/澳大利亞元），`_CURRENCY_DISPLAY` 同步补 4 枚。
- **故意不收**「澳币」（口语也指澳门元）、「加币」（撞加密语境）、「法郎」（裸词歧义）——顶替币种＝报错数。
- `has_currency_term` 的硬抄码清单删除，改由 `_ISO_CODE_RE`（`:991`，从 `_VALID_CODES` 派生）承担；识别用**只禁 ASCII 胶合**的 lookaround 而非 `\b`（CJK 在 Python re 里算 `\w`，用 `\b` 会把「usd换算」一起挡掉）。顺带修掉既存误伤：`audio换算`/`decade` 里的 `aud`/`cad` 不再被认成币名。
- `_parse_rates` 的行索引折进 `_diff_rows_by_code()`（`:726`），与探针共用一把尺，不起第二份。

### 2.5 测试面

- 新建 `tests/test_fx_currency_coverage.py`（60 条，当时值）＝五把门 × 注毒腿＋反向不误伤腿。
- 同批改动的既存锁（**都是扩判据，没有一处下调**）：
  - `tests/test_fx_data.py::test_fx_pair_availability_table`：二分封闭 → 四态封闭＋前缀白名单＋cross/pending 逐行精确相等。
  - `tests/test_finance_data.py::test_supported_currencies_cover_required_set`：加「点名 11 ⊆ 在册」断言。
  - `tests/test_finance_data.py` 的 `FX_SNAPSHOT_FIXTURE` 补四枚**形状值**（该节头注本就自陈「结构未实测，fixture 锁行为」）——否则「上游全量返回」被误判 DEGRADED。
  - `tests/test_fx_card_semantics.py::_PANEL_BODY`：面板 body 末尾多一行「暂无数据：…」（有意的诚实增量；文件 docstring 第 3 条同步注明，其余三条 body 仍逐字不变）。
  - **宇宙表一行未加 ⇒ 既有 `len(...)==10`、`len(calls)==1`、`test_parse_fx_rates_from_real_fixture` 等精确数锁全部原样通过**（这是选择「候选名册而非直接加行」的硬收益）。

---

## ③ 判据读数（实跑末行原样；卫生前缀 `PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 … -p no:cacheprovider --basetemp=$TEMP/qoder-F1/bt`）

起点（改动前，同尺 4 文件）
```
155 passed, 2 skipped in 16.10s
```
改动后
```
tests/test_fx_currency_coverage.py                                   60 passed in 3.87s
4 文件（fx_data/fx_coverage/fx_card/finance_data）                   186 passed, 2 skipped in 16.91s
15 文件全链（+market_backoff/seat_fix_fin_resil/finance_routing/
  finance_route_wiring/route_priority_disambiguation/market_exclusion_guard/
  stocks_hijack_guard/trigger_bidirectional_gate/documentation_consistency/
  doc_link_integrity/doc_sync_gates）                                543 passed, 2 skipped in 47.45s
文档面单独复跑（含 boards 正文改动后）                               488 passed in 29.24s
scripts/board_doc_sync.py --check            board-docs 同步正常（10 板块 / 58 功能 / 164 入口 / 主题 83）
ruff（本席 6 枚文件，--no-cache）              All checks passed!
```
注毒实跑（**仓外副本** `$TEMP/qoder-F1/poison`＝`git archive HEAD` 抽出后覆盖本席产物，再逐条破坏实现）
```
A 摘掉 RUB 的三态票            → 5 failed, 55 passed in 5.91s   （门②＋门③ 红）
B cross 换不出时返常数          → 60 passed                       （被后一道缺腿闸吸收＝纵深防御）
D 缺腿时补一条 1.0 的假腿       → 60 passed                       （同上）
E 两道缺腿闸都拆（真把估算端出去）→ 4 failed, 56 passed in 4.23s   （门⑤ 红）
```
⇒ 门不是永真：要漏出「编出来的数」必须同时拆掉两道闸，而拆掉后端到端判据立刻红。

---

## ④ 净新增红 A/B（按 #68★ 正道：`git archive HEAD` 抽到仓库外、同一把尺复跑）

| 尺 | HEAD（仓库外副本 `$TEMP/qoder-F1/head`） | 本轮 | 本席域净新增 |
|---|---|---|---|
| pytest（FX 4 文件） | 155 passed / 2 skipped / **0 failed** | 186 passed / 2 skipped / **0 failed** | **0** |
| pytest（15 文件全链） | — | 543 passed / 2 skipped / 0 failed | **0** |
| ruff（本席 5 枚既存文件） | `All checks passed!` | `All checks passed!` | **0**（中途出过 3 枚 SIM114/PIE810/SIM102，已清零） |
| ruff（全树 dev.ps1 -Task lint） | `Found 49 errors.`（其中本域 3 枚＝我引入） | `Found 36 errors.`，FX 面 grep **0 命中** | **0**（其余 36 枚全在别席在飞件：`quirks.py`/`db_backup.py`/`write_trace.py`/`providers.py`/`nonebot.py`/`mail_adapter.py` 及别席新建测试） |
| mypy（本域两文件，`--follow-imports=silent`，cache 外置） | `Success: no issues found in 2 source files`（exit 0） | `Success: no issues found in 2 source files`（exit 0） | **0**（中途 1 枚 `[assignment]` 已修） |
| mypy（全树 -Task typecheck） | 跑不完 | 跑不完：`quirks.py:474: error: Expected 'except' or 'finally' block [syntax]` → mypy exit 2 **中断全树** | 非本席；**提请主会话**：别席在飞件把语法错留在树里＝整道 typecheck 门对全席失明 |
| runtime-layout | — | `runtime-layout: FAIL` — `source workspace contains 2 Python cache path(s)`＝`plugins/bot_unified_runtime/runtime/__pycache__/db_backup.cpython-312.pyc` | 非本席。本席产物零缓存：`find` 全树只列出上面那一枚；`.mypy_cache`/`.ruff_cache` mtime＝2026-10-01（早于本席开工，属既存） |

**只签「本席域净新增红 0」，不签「全绿」**（HEAD 基线与别席在飞面自红）。

---

## ⑤ 未尽事项与原因

### 5.1 待验清单（**本席没真发一个包**；这一段必须主会话在线跑，跑完才谈「补齐」成立）

**V-1 东财候选腿（一条命令，走与生产完全同一出口 ⇒ 代理/UA/超时口径一致）**
```bash
cd "C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot"
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 \
  "C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe" \
  -c "import json;from plugins.bot_unified_runtime.domains.finance.data.fx_data import probe_fx_candidates as p;print(json.dumps(p(),ensure_ascii=False,indent=2))"
```
读数规则：`hit` 非空＝该币有活腿（记录 `f2` 与 `f14` 名称，并核 `f14` 是不是**该币**而非同名他物）；`no_row`＝板块无此代码；`bad_value`＝有行但 f2 非数；`error`＝网络/代理层问题（≠无源，别混判）。
**V-2 curl 同批交叉核对**（与 V-1 同 12 条 secid，两法一致才算实证）
```bash
curl -s "https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&secids=119.USDRUB,119.RUBUSD,120.RUBCNYC,119.USDCHF,119.CHFUSD,120.CHFCNYC,119.USDCAD,119.CADUSD,120.CADCNYC,119.USDAUD,119.AUDUSD,120.AUDCNYC&fields=f2,f3,f12,f13,f14,f18"
```
**V-3 suggest 双验**（S02 与 `stock_data.py:29-31` 的既有证据分级要求「ulist 实测＋suggest QuoteID 实证」两证齐；具体 searchapi 坐标**仓内未留字面 URL**，本席不造新坐标——由主会话按现行探针执行）。
**V-4 er-api 快照链路复测**：`fetch_fx_snapshot()` 现在生产无人调用（文档化保留）。若 V-1 全军，这是唯一已接线的兜底腿——2026-09-12 实测不可达，**是否已被 #71 的代理链根修复救活需重测**。⚠ 别踩 #71★：`httpx` 显式传 proxy 时 `NO_PROXY`/环境变量全失效；`proxy=None` ≠ 直连。
**V-5 MOEX 外汇端点（只关 RUB）**：`iss.moex.com` 主机 2026-09-12 实证可达，但**外汇板端点从未探过**；探到才谈得上第二腿，探不到就维持「只有一条候选腿」的在册说法。

**命中后的促升批（必须同批动，只动一边必红另一边＝#68★）**
1. `_FX_PAIR_UNIVERSE` 加行（pair 方向按实探回来的那条，`rate_type` 按板块：119→spot、120→parity 且注意 100 单位口径要不要 `unit_base=100`）；
2. `_FX_SOURCED_EVIDENCE` 同批补该 secid 的 (实测日期, 实测方式)，**方式要写清哪两条命令互相印证**；
3. 从 `FX_PENDING_CANDIDATE_SECIDS`/`FX_PENDING_FALLBACK_LEGS` **摘掉该币**（否则门② 的互斥判据红）；
4. `tests/test_fx_currency_coverage.py` 里 `_UNQUOTABLE` 与三条 pending 断言、`tests/test_fx_data.py::test_fx_pair_availability_table` 的 pending 行同批改；
5. 若命中 120 家族：`_FX_PARITY_ALTERNATES`（`fx_data.py:337-342`）与宇宙表的先后关系要一并裁（本席**没动**这张备用表，它至今不在取数链上）；
6. 帮助册交 G1/echo owner 批：`echo.py:1711-1714` 的「覆盖 11 币种」与 `docs/command-catalog.md:1749` 同句（见 §5.3），改完走 `scripts/doc_sync.py --check`＋`BOT_AUTOSYNC=0` 验收；
7. 重启 bot 才生效（铁律；台账 #10★）。
本席已用 `TestPromotionIsOneLineDeep` 把这条路径**在桩上跑通**（加行＋凭据 ⇒ 直盘出数、`fx:cross:RUB/CNY` 换算出数、三态票自动翻 `sourced`、缺席清单里自动消失、五把门全绿），并配了一条注毒腿：**只加宇宙表、忘了重建 `_PAIRS_BY_KEY`（真跑时它由导入期派生）时，能力层只能走三角换算，绝不允许假装成实测直盘行**。

### 5.2 本席**没有**做的（有意的）

- **没把四枚币写成有源**——这是本工单的核心裁定：需求书要的「补齐」在证据不足时的唯一诚实形态是三态名册＋候选腿在册；把它们塞进宇宙表能让所有面板读数「看起来齐了」，但那正是 #71/#72 反复在册、AGENTS 第四部分「汇率」行点名的最贵事故（北向净买入、LME 铜、1Y 国债、MOEX 无东财 kline 四次先例）。
- **没新增配置键**（复用 `bot_fx_enabled` 与 `bot_market_*` 族）⇒ 无 `F1-CONFIG-REQUEST.md`。若主会话要把「候选探针」做成运维命令面（新键如 `BOT_FX_PROBE_*`），那是控制面改动，不在本席面。
- **没动 `echo.py`/`__init__.py`/`config.py`/`market_data.py`**（别席或主会话持有）。
- **没动 `docs/HANDBOOK.md`/`docs/auto-facts.md`/`docs/command-catalog.md`**：本域增量的落账点与「覆盖 11 币种」那句的更正，留给主会话按 §59 之后的新节同批走。
- **面板不加 derived 行**：见 §2.2 的口径纯净裁定，属可回退的保守选择。

### 5.3 帮助册「宣称 ⊆ 实装」对账（P7 出口门；本席只登记不改）

现算（`echo.py:1697-1723` 汇率格子与 `fx_data` 真身对表；粗正则会把正文里的「ISO 代码」一词误认成币码，下表已剔该假阳性）：

| 项 | 读数 | 判定 |
|---|---|---|
| 帮助册宣称币码集合 | USD/EUR/GBP/JPY/KRW/TWD/CNY/HKD/SGD/MOP/AED | ⊆ 实装在册集合 ⇒ **无越权宣称**，违规 **0 条** |
| 手写计数「覆盖 **11** 币种」 | 实装在册 15 枚、sourced 8 枚（当时值） | **计数已过期**（rule 10 违规：随代码漂移的总数写进了叙述面）；方向是**少报**（安全侧），但仍是账 |
| 用户点名的 RUB/CHF/CAD/AUD | 帮助册**未宣称**，实装**待验** | 一致（都不承诺）⇒ 促升批 §5.1-6 时再同批改这句 |
| 「USD/TWD、USD/MOP、USD/AED 东财暂无行情」 | 与 `FX_UNAVAILABLE_PAIRS` 逐枚相符 | ✅ 真 |
| 生成物 `docs/command-catalog.md:1749-1751` | 同句同计数 | 随 `echo.py` 一起改，别只手改生成物 |
| `docs/boards/…/finance/fx.md`、`fx-panels.md` | 本席**已改正文**（标记外，AUTO 段未动；`board_doc_sync --check` 正常） | 若属板块归属账，主会话复跑 `doc_ownership_sync --generate` 即可 |

### 5.4 已知残余（登记，不掩盖）

1. 纯文本面板的缺席句依赖静态名册；渲染失败退回纯文本时仍会带上该行（已覆盖），但**面板卡不加 derived 行**这条保守裁定意味着：卡上看不见英镑/韩元/新加坡元兑人民币的换算结果（结果在消息文字里）——要不要把 derived 也纳入面板，请主会话裁。
2. `probe_fx_candidates()` 目前**没有任何命令面接线**（有意：核实前不许生产静默使用）。若要做成 `/bot` 运维令或接进 `scripts/e2e_acceptance.py`，那属别席的面（`echo.py`/控制面），提请排批。
3. 候选 secid 的命名规律是从**已实测同族行**推定的（119.直盘 / 120.`<币>CNYC`），推定 ≠ 实证；V-1 全军时**不要**据此写「东财无该币行情」——那句要的是 `_FX_ABSENT_EVIDENCE` 形态的查无凭据。
4. 「加元」子串风险只堵了 增加/追加元素 两个高频形；更宽的中文子串误伤（如地名＋元）未穷举。
5. `_FX_PARITY_ALTERNATES` 仍是「备用记录、不在取数链」的原状（V-1 命中 120 家族时才需要裁定它与宇宙表的先后）。

### 5.5 注入处置登记（AGENTS 规则 11）

本席**未遇到**伪装用户/主会话的祈使载荷，也未遇到伪造工具结果外壳（关键读数全部先落 `$TEMP/qoder-F1/*` 再 `Read`/`tail` 复核）。
一处需要点名的非白名单来源：`patches/S02-FINANCE-COVERAGE.md`（前席工单，非 ①用户 ②简报 ③在册规范 三类）正文含对未来席的施工祈使（「批 A 必须先合」「不得进宇宙表」一类）。本席**未把它当指令执行**：采纳的判据「待验者不得写成有源」与我自己的简报 §6 铁律（「拿不到就明写拿不到，不许用估算冒充报价」）同向，且未因此扩大交付面或改任何禁写面。指纹（原文不入册，防二次传播）：`sha256[:16]=0293b7de9b7b173c`，33,247 字节，正文首末各 40 字符见 `$TEMP/qoder-F1` 取证（本席已消毒，此处不复述）。

---

## 附：本席动过的文件清单

| 文件 | 动作 |
|---|---|
| `plugins/bot_unified_runtime/domains/finance/data/fx_data.py` | 改：三态名册＋凭据册＋USD 换算桥＋探针＋单一真身收口（1109 行，改动前 620） |
| `plugins/bot_unified_runtime/domains/finance/capabilities/fx.py` | 改：回答顺序＋三态拒答＋缺席可见＋`missing_sub` 可选参＋让路词（354 行） |
| `tests/test_fx_currency_coverage.py` | **新建**：五把门＋注毒自证＋促升演练（60 条用例） |
| `tests/test_fx_data.py` | 改：覆盖表锁由二分扩成四态封闭（判据**加严**） |
| `tests/test_finance_data.py` | 改：快照夹具补四枚形状值＋在册⊇点名断言 |
| `tests/test_fx_card_semantics.py` | 改：`_PANEL_BODY` 加诚实缺席行并注明缘由（其余三条 body 逐字锁不变） |
| `docs/boards/B05-external-data-services/finance/fx.md` | 改正文：三态、换算顺序、待验四币、验收样例 |
| `docs/boards/B05-external-data-services/finance/fx-panels.md` | 改正文：凭据册、四态覆盖表、换算桥、促升批、名册单一真身 |
| `patches/F1-FX-CURRENCIES-20261002.md` | 新建（本文件） |

**生效条件**：以上一律**待审不自动部署**；提交、推送、重启由用户执行或明示授权（AGENTS 常令）。
