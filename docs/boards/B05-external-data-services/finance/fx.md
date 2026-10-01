# 金融行情 · 汇率查询

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B05.finance · 汇率查询

- 层级：一级 B05 → 二级 finance → 三级 `fx`
- 路由席位：`FX`（matcher `fx`，command=True）
- 判定优先级：36
- 能力 id：`bot.fx`
- 实现落点：`plugins/bot_unified_runtime/domains/finance`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

汇率查询：`汇率`（主要货币面板）、`美元兑人民币`、`USD/CNY`、`100日元换多少人民币`、`日元汇率`（单查默认兑人民币）。给方向明确的换算与面板，并显式标注基准货币、中间价/现钞口径与数据时点。**拿不到的币种说拿不到**，不做插值。

## 怎么调用

- 席位 `FX`、能力 id `bot.fx`；闭包 `domains/finance/capabilities/fx.py:build_fx_capability(config, *, render_backend)`，谓词 `is_fx_command`（短文本、无链接、命中汇率意图且不撞股票语境）。
- 意图解析在数据层：`domains/finance/data/fx_data.py:parse_fx_query(text)` → `(base, quote, amount)`；面板意图 `wants_major_rates`；币名识别 `has_currency_term`（中文别名/繁体/ISO 码）；对子方向 `resolve_fx_pair`（反向命中会自动倒过来并标注）。
- 取数：主源东财外汇批量快照 `fetch_fx_rates(pair_keys, *, timeout_seconds, cache_seconds)`（免 key，进程内 60s 缓存）；备选快照链路 `fetch_fx_snapshot(base, targets, ...)`（保持对外签名不变）；交叉价纯函数 `cross_rate_from_usd`（以 USD 为桥，换不出返回 `None`）。
- 出卡：`build_fx_card_payload(rates, missing_note, focus_label=...)`，面板与定向换算在**副标题上语义分离**，落盘文件名把查询语义（面板 / pair:方向）纳入摘要，避免两张不同内容的卡同名互覆盖；文案 `format_fx_brief` / `format_fx_rate_line`（按 `unit_base` 折算，如 100 日元口径）。

## 开关与参数

- `bot_fx_enabled`（缺省 True，已在 `config.py` 声明）。
- 超时/缓存沿用 `bot_market_timeout_seconds` / `bot_market_cache_seconds`，空响应重试共用 `bot_market_retry_on_empty`。
- 优先级见 `domains/chat_reply/runtime/base_router.py` 的 `RouteRule` 行（拆位后最靠前的金融席位之一，因为"兑"这类词最容易和股指撞）——**代码已在、线上未生效**（该文件属 2026-09-21 修复波的未提交改动面）。

## 失败时看到什么

- 面板整体失败：数据源失败人话。
- 某对无源：卡上「暂无数据」并计入 `missing_note`，**绝不补 0、绝不用相近币种顶替**。结构性无源清单（`USD/TWD`、`USD/MOP`、`USD/AED` 在东财实测查无结果）登记在 `FX_UNAVAILABLE_PAIRS`，读点 `fx_pair_availability()`。
- **三态名册（2026-10-02 席位 F1）**：币种按 `fx_currency_availability()` 逐枚表态——`sourced`（宇宙表里真会外呼、且 `_FX_SOURCED_EVIDENCE` 查得到实测凭据）／`pending`（候选 secid 已列、真机未核实）／`unavailable`（实测查无）。用户点名的 **RUB/CHF/CAD/AUD 四枚今天是 `pending`**：问到就明写「尚未接入已核实报价源＋候选腿是谁＋还差真机核实这一步」，既不冒充有源、也不替东财作「查无」的证。缺席清单在卡面与纯文本面板同读 `fx_missing_note()`，不从任一面静默消失。
- 定向换算的回答顺序：实测直盘 → 反向命中（取倒数并标注）→ USD 三角换算（`fx_derived_quote`，只用本轮在盘的两条**现货**腿，标注「非中间价、非可成交价」，缺腿即拒答）→ 三态拒答。因此「英镑汇率／韩元汇率／新加坡元汇率」不再答非所问。面板卡仍只列实测源行，`derived` 不进面板，避免一格数字混两种口径。
- 无历史走势：东财外汇日 K 在相关板块实测全空 ⇒ `FxRate.history` 恒为空，卡上诚实写「暂无历史走势数据」，不画假折线。
- 备选快照端点在当前环境同样不可达：`status=unavailable`，缺币进 `missing_currencies` 显式列出。

## 测试与验收

离线：`tests/test_fx_data.py`（解析方向、无源登记、交叉价 None、快照缺币）、`tests/test_fx_card_semantics.py`（面板/换算副标题与落盘名语义）、`tests/test_fx_currency_coverage.py`（三态封闭、有源必带凭据、缺席可见、名册单一真身、换算不编数，每把门配注毒腿）、`tests/test_route_priority_disambiguation.py`（「美元兑人民币行情」「汇率 美元」类样句归属）。
真机：`汇率`、`美元兑人民币`、`100日元换多少人民币`、`新台币汇率`（应明确"该币种暂无源"）、`卢布汇率`（应点名候选腿待真机核实，且**不出现任何换算数字**）。
