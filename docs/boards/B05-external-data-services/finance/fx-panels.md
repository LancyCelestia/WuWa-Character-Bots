# 金融行情 · 汇率面板与定向换算

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B05.finance · 汇率面板与定向换算

- 层级：一级 B05 → 二级 finance → 三级 `fx-panels`
- 实现落点：`plugins/bot_unified_runtime/domains/finance`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

汇率域的数据层真身（不注册路由）：哪些货币对**有源**、是什么口径（现汇/现钞/中间价/100 单位）、缺币怎么登记、交叉价怎么算。`fx` 入口只消费这一层，"能不能报这个数"由这里的覆盖表说了算。

## 怎么调用

- 真身：`domains/finance/data/fx_data.py`。覆盖表读点 `fx_pair_availability()`（2026-10-02 起四态：`eastmoney:<secid> <rate_type>` / `cross: <腿1>+<腿2>` / `unavailable: <原因>` / `pending: <候选 secid>`），币种级读点 `fx_currency_availability()`（`sourced`/`pending`/`unavailable` 逐枚一票），缺席说明 `fx_missing_note()`、拒答理由 `fx_no_quote_reason()`。条数以该文件自身为准、文档不手写。
- **凭据册（2026-10-02 席位 F1）**：`_FX_SOURCED_EVIDENCE`（secid → 实测日期＋实测方式）与 `_FX_ABSENT_EVIDENCE`（货币对 → 查无凭据）。「有源」只认模块头注已自陈的 curl 实测或后续波次的真机重探；**宇宙表 `_FX_PAIR_UNIVERSE` 里出现无凭据的 secid 就是编源**，由 `tests/test_fx_currency_coverage.py` 门① 拦。
- 主源：东财 `push2 ulist.np/get?fltt=2`，字段 f2=汇率 / f3=涨跌% / f4=涨跌额 / f12=代码 / f13=市场号 / f14=名称 / f18=昨收；已实测 secid 与市场号规律（直盘、人民币中间价、离岸人民币各成一族）写在该文件头注。
- 单位口径：`unit_base`（如 100 日元一档的中间价），展示与换算都经它折算，避免"1 日元 ≈ 4.36 人民币"这种量级事故。
- 换算桥：`fx_usd_bridge()`＋`fx_per_usd()`＋`fx_derived_quote()` 只吃 `rate_type=="spot"` 且与 USD 直接成交的行（中间价行不参与，防一格数字混两种口径），产出 `derived` 行并附「用了哪两条腿＋非中间价＋非可成交价」的说明句；缺任一腿给 `None`。底层纯函数仍是 `cross_rate_from_usd(usd_table, base, quote)`（USD 三角，换不出 `None`）。
- 待验候选：`FX_PENDING_CANDIDATE_SECIDS`（币种 → 候选 secid：直盘两个报价方向加 `120.<币>CNYC` 中间价一族）＋ `FX_PENDING_FALLBACK_LEGS`（第二兜底腿；没有就明写没有）。核实入口 `probe_fx_candidates()`——**生产链路不调用它**（AST 锁执法），命中后由人工把行同批写进宇宙表＋凭据册并摘掉 pending 票。
- 备选源：`open.er-api.com/v6/latest/{base}`（快照链路，函数 `fetch_fx_snapshot`）；**诚实边界**：该端点在本机环境实测同样不可达，因此它只作为已实现但常态失败的兜底，不是"另一个一定能用的源"。
- 单点网络出口：`_fetch_payload`（东财）、`_fetch_fx_payload`（快照）；缓存清理 `reset_fx_cache()`。

## 开关与参数

无独立键（沿用 `bot_fx_enabled` 与 `bot_market_*` 族）。基准货币、目标集合是 `fetch_fx_snapshot(base, targets)` 的参数，由调用方显式给；解析层的"面板 vs 换算"语义在 `parse_fx_query` / `wants_major_rates`。**币种名册只有一份**：`_CURRENCY_ALIASES`（含简繁）→ `_VALID_CODES` → `_ISO_CODE_RE`，`_CURRENCY_DISPLAY` 键集必须与值集相等；加一枚币＝别名＋展示名两处同批，触发面自动跟随（旧写法在 `has_currency_term` 里硬抄过第二份码清单，已收口，门④ 拦回潮）。「澳币／加币／法郎」这类有歧义的口语简称**故意不收**——顶替币种＝报错数。

## 失败时看到什么

这一层不产生用户可见文案，只交状态：缺行或 f2 非数的货币对**直接跳过**（绝不造数）、`missing_currencies` 显式列出缺哪些、整体失败 `status=unavailable`、`updated_at` 解析不出来就留 `None`（不硬造"更新时间"）。日 K 实测全空 ⇒ `history` 恒空，上层写"暂无历史走势数据"。`fx_unquoted_currencies()` 把「结构性无源／候选待验」与「有实测源但本轮上游没回该行」分列，两类都不许静默缺席。

## 测试与验收

离线：`tests/test_fx_data.py`（覆盖表四态封闭、无源对、单位口径、交叉价 None、快照缺币）、`tests/test_fx_card_semantics.py`、`tests/test_fx_currency_coverage.py`（凭据／三态／缺席可见／名册单一真身／换算不编数五把门，每把配注毒腿；含促升演练——模拟候选核实后「加一行」端到端接通）。回归锁包含"新增无源币种必须进登记表"的形态断言。
真机：`汇率 美元 兑 韩元`（直盘）、`英镑汇率`（应给带交叉换算口径的数）、`新台币`（应点名无源）、`卢布汇率`（应点名候选腿待真机核实、且不出任何数字）、`AED 汇率`（同上）。
