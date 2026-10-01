# S02 工单 · 金融市场域覆盖面（汇率 11 币 / 多国国债 / 大宗镍铬 / 个股字段 / 基金期权期货）

> 席位：S02（只读对象库 + 只写本文件）。HEAD＝`8ad03e4`（`git --git-dir=.../ChatBot_Runtime/git rev-parse HEAD` 实测）。
> 取证纪律：本席**未做任何网络实探、未跑 pytest、未动 git**；文中行号一律「HEAD 实测」。凡 HEAD 未自陈「实测核验」的数据源，本单一律标 **待验**，不许当成有源写进代码。
> 读码配方（可复跑）：`git --git-dir="C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/git" show HEAD:<相对路径>`

## 0. 摘要（≤200 词）

用户点名的 11 枚币种里 **7 枚已有活源**（USD/EUR/JPY/KRW/CNY/HKD/SGD 走东财 119/120/133），**RUB/CHF/CAD/AUD 四枚整片缺**；国债**只有中美 2/5/10/30Y**，1Y 与日德英印无源；大宗**只有 4 枚**（GC/SI/HG/CL），镍待探、铬预判定结构性无源；股指 18 席已含 MOEX/KOSPI/FTSE/CAC/DAX。**个股「流通股/总股本」不是没取，是被 H-03 裁定「单位未实测 ⇒ 置 None 不上卡」并有两枚测试锁死**；日内开/高/低/昨收在批量面板链**已取到但没展示**（现成套利，零新源）。基金/公募/私募/期权/期货**完全没做**，且「基金」「期货」今天是 market/fx 的**让路词**。故本单主张：①先建**机器可读的「有源必须带实测凭据」证据册**＋五把注毒门（无源被写成有源 ⇒ 门必红），再逐枚补源；②补源只走**已实证的东财 ulist/datacenter 同族**，候选 secid 全部先真机实探，缺者登记进无源名册并在卡面 `delayed_note` 显式缺席；③私募/期权判为**结构性无源、永不接**；④基金只做**场内 ETF 复用同族接口**这一条最小线，场外净值留下一波。非上市红线与北向口径不动。

---

## 1. 现状坐标（HEAD 实测）

| 文件 | 关键锚点 | 现状 |
|---|---|---|
| `domains/finance/data/fx_data.py`（591 行） | `:55` `BASE_CURRENCY="USD"`；`:58-70` `SUPPORTED_CURRENCIES`＝11 币；`:261-272` `_FX_PAIR_UNIVERSE`＝10 对（活源真身）；`:282-287` `_FX_PARITY_ALTERNATES`；`:290` `FX_UNAVAILABLE_PAIRS`＝USD/TWD·MOP·AED；`:311-320` `fx_pair_availability()`（有源/无源二分覆盖表）；`:458-486` `_CURRENCY_ALIASES`；`:501-513` `_CURRENCY_DISPLAY`；`:565-568` `has_currency_term` 内**硬抄第二份 11 码**；`:210-231` `cross_rate_from_usd`；`:72/182` er-api 快照链 | 活链＝东财 `ulist.np/get`（`:292-295`）。**`fetch_fx_snapshot` / `cross_rate_from_usd` / `format_fx_snapshot_brief` 全树零生产调用点**（`git grep` 只命中 `tests/`）⇒ `SUPPORTED_CURRENCIES` 今天**不驱动任何用户可见面**，扩它≠扩能力 |
| `domains/finance/data/bond_data.py`（287 行） | `:49-54` 单报表 `RPTA_WEB_TREASURYYIELD`；`:59-64` `_CN_TENORS` 4 列；`:65-70` `_US_TENORS` 4 列；`:71-72` 10Y−2Y 直供利差列；`:141-156` 算术回退并标「计算值」；`:264-287` brief；头注 `:25-28` 自陈 1Y 无源 | 只有中国＋美国，期限 2/5/10/30。列映射锚 akshare 1.18.94（`:11-19`），利差列与期限列逐位自洽（`:21-23`） |
| `domains/finance/data/commodities_data.py`（358 行） | `:51-56` `_COMMODITY_UNIVERSE`＝4 枚；`:58` 分组「贵金属/基本金属/能源」；`:61` `LME_NOTE`；`:207-215` `commodity_availability()`（含 LME铜／Brent原油 两条 `unavailable:`）；`:77-81` `_KLINE_URL` **带 `end=20500101`** | 镍/铬/农产品**零登记**；市场号规律 101=COMEX、102=NYMEX（`:11`） |
| `domains/finance/data/market_data.py`（772 行） | `:86-105` `_INDEX_UNIVERSE` 18 席（含 100.KS11／FTSE／FCHI／GDAXI／IMOEX）；`:50-56+230-272` MOEX ISS 备选源（**本机实证可达**）；`:124-128` `INDEX_UNAVAILABLE`（迪拜/阿联酋/澳门）；`:133-136` `PENDING_INDEX_CANDIDATES`（105.UAE，只登记不上卡）；`:445-449` kline 带 `end`；`:607-641` 北向（`NorthboundFlow` **结构性无 net 字段**） | 无源名册形制的**现役样板**（本单复用它） |
| `domains/finance/data/stock_data.py`（**1697 行**，简报说「约 1820」＝已漂） | `:129-239` 美股 9 家；`:241-436` A 股 9＋港股 8；`:437-445` `_PENDING_STOCK_CANDIDATES`；`:451-495` `NON_PUBLIC_EQUITIES`（3 家，只估值）；`:556-559` `_QUOTE_URL`（f2,f3,f4,f12,f14,f20,f47,f48,f84,f85）；`:635-680` `_parse_quote`，**`:671-674` volume/amount/float_shares/total_shares 全置 None（H-03）**；`:864-945` `fetch_market_cap`，**`:893-905` 非美元市值诚实门**；`:1379-1383` `_QUOTES_URL`（**含 f15,f16,f17,f18,f5,f20**）；`:1503-1524` 批量链已解析 open/high/low/prev_close/volume/market_cap | 流通股＝f85、总股本＝f84 **已在请求字段里但不消费**；日内 OHLC 批量链取了、面板未展示 |
| `domains/finance/capabilities/market.py`（837 行） | `:63-69` `_NON_STOCK_RE` 把 **基金/期货** 列让路；`:158-190` 商品/国债/北向触发族；`:238-289` `_render_finance_sections_card`（三卡共用壳）；`:383-391` 商品 payload（`delayed_note=LME_NOTE`）；`:473-483` 国债 payload（`delayed_note` 写「1 年期暂无稳定免费源」）；`:603-613` 北向 payload；`:725-733` 股指把无源名册**拼进 `delayed_note`** | 「无源怎么在卡面显式标注」＝**现成两条路**：`delayed_note` 文案 / 一行 `value:"暂无"` 的行 |
| `domains/finance/capabilities/fx.py`（300 行） | `:50` `_STOCK_GUARD_RE` 含 **基金** 让路；`:82-133` `build_fx_card_payload(rates, missing_note, focus_label)`，`:111-119` 无源行；`:228-232` `resolve_fx_pair` 未命中 ⇒ 直接说「暂无数据（东财无该货币对行情）」 | 诚实文案通路**已经存在**，只要别名表里有这个币名就会走到；别名表里没有 ⇒ `parse_fx_query` 返回 None ⇒ 掉回面板（**答非所问**，见 §9-3） |
| `domains/finance/capabilities/stocks.py`（794 行） | `:269-419` 个股 payload；`:333-340` 市值行**硬编码「亿/万亿美元」**；`:341-381` 成交量/额/流通股/总股本四行（被 None 门挡住，代码就绪）；`:521-638` 九家面板 | 字段回填后**渲染侧不用改**（行已写好）；非美元市值要改的只有 `:333-340` 一行单位词 |
| `domains/core/contracts/finance.py`（343 行） | `:43-59` 五态 status；`:62-69` provenance 四件套；`:72-91` `EquityQuote`（**volume/amount/float_shares/total_shares 四字段已存在**）；`:149-161` `MarketCap`；`:236-254` `NonPublicEquityNote`（**结构性无价格字段**） | 契约**不需要为流通股/多国国债新增字段**；多国国债需扩 `BondYieldSnapshot`（数据层私有 dataclass） |

**路由/开关（HEAD 实测）**：优先级 fx36 < commodities37 < bond38 < northbound39 < market41 < stocks42（`runtime/base_router.py:394-456`、`capability_registry.py:394-511`）；`bot_{market,stocks,fx,commodities,bond,northbound}_enabled` 六键**config.py:501-510 已声明**、`.env.example:531-539/640-644` 已登记。

---

## 2. 缺口二分表（有源→接入 ／ 无源→诚实缺席）

> 铁律：**「有源」只认两种凭据**——① HEAD 模块头注已自陈「本机实测」，② 本波真机重新实探并落日期＋响应形态。除此之外全部 **待验**，待验者不得进宇宙表，只准进无源名册或候选册。

### 2.1 汇率 · 逐币种（用户点名 11 枚）

| 币 | HEAD 现状 | 判定 | 动作 / 缺席标注 |
|---|---|---|---|
| USD | `BASE_CURRENCY`（fx_data:55） | 有源（基准） | 不动 |
| EUR | 119.EURUSD 现货＋120.EURCNYC 中间价 | 有源·已上卡 | 不动 |
| JPY | 119.USDJPY＋120.JPYCNYC（`unit_base=100`） | 有源·已上卡 | 不动（100 日元口径已有 P0-1 锁） |
| KRW | 119.USDKRW | 有源·已上卡 | 不动 |
| CNY | 133.USDCNH 离岸现货 | 有源·已上卡 | 不动 |
| HKD | 119.USDHKD＋120.HKDCNYC | 有源·已上卡 | 不动 |
| SGD | 119.USDSGD | 有源·已上卡 | 不动 |
| **RUB** | 宇宙表/别名/展示名**全无** | **待验** | 候选 `119.USDRUB` 实探；备选＝`iss.moex.com` 货币市场端点（**该主机 HEAD 已实证可达**，端点本身待探）。命中⇒入宇宙表＋别名「卢布/俄罗斯卢布/러」＋展示名；未命中⇒`FX_UNAVAILABLE_CURRENCIES` 登记原因「东财与 MOEX 均无该币对现汇报价」 |
| **CHF** | 全无 | **待验** | 候选 `119.USDCHF`；别名「瑞郎/瑞士法郎」 |
| **CAD** | 全无 | **待验** | 候选 `119.USDCAD`；别名「加元/加拿大元」 |
| **AUD** | 全无 | **待验** | 候选 `119.USDAUD`；别名「澳元/澳大利亚元」 |
| （在册无源）TWD/MOP/AED | `FX_UNAVAILABLE_PAIRS:290` | 无源·已诚实登记 | 保持；新名册要与之**同读点**，不许两份「暂无」文案 |

**缺席必须在三处同时可见**（缺一即门红，见 §7 门 3）：卡面行（fx.py:111-119 形制）、纯文本 `format_fx_brief`、以及「用户直接问该币」时的定向回答（fx.py:228-232 通路）。

### 2.2 国债 · 逐国 × 期限

| 国 | 2Y | 5Y | 10Y | 30Y | 1Y | 判定 |
|---|---|---|---|---|---|---|
| 中国 | EMM00588704 | EMM00166462 | EMM00166466 | EMM00166469 | **无列** | 有源·已上卡；1Y 保持无源登记（bond_data:25-28） |
| 美国 | EMG00001306 | EMG00001308 | EMG00001310 | EMG00001312 | **无列** | 同上 |
| 日本 / 德国 / 英国 / 印度 | — | — | — | — | — | **整片缺**：HEAD 只挂一张报表，其列名册（`:59-70`）无这些国；akshare 同族映射亦只 CN/US |
| 法国 / 意大利 / 加拿大 / 澳洲 | — | — | — | — | — | 同上 |

处置（两步，不许跳第一步）：
1. **探源**：在真机用东财 datacenter 的报表目录/搜索面**找是否存在覆盖日德英印收益率的 reportName**；`reportName` **不得凭印象写死**（HEAD 唯一实证名就是 `RPTA_WEB_TREASURYYIELD`，且 `:203` 已实证过猜列名的代价——`TRADE_DATE` 不存在返回 9501）。找到且列映射可自证（用**利差列＝期限列之差**这类内部一致性交叉验证，照 `:21-23` 的先例）⇒ 才许接入。
2. **无果即登记缺席**：新增 `BOND_UNAVAILABLE: tuple[tuple[str,str],...]`（形制照 `market_data.INDEX_UNAVAILABLE:124-128`）＋ `bond_unavailable_entries()` 读点，卡面按 `market.py:725-733` 的写法拼进 `delayed_note`：「暂无数据源：日本/德国/英国/印度国债」；文本 brief 追加同句。

期限对齐红线：多国接入后，**利差只在同国 2Y/10Y 都有值时才算**（沿用 `_spread_with_fallback:141-156`），跨国拼利差＝造数，禁止。

### 2.3 大宗商品 · 逐品种

| 品种 | HEAD | 判定 | 动作 |
|---|---|---|---|
| 黄金 | 101.GC00Y | 有源·上卡 | 不动 |
| 白银 | 101.SI00Y | 有源·上卡 | 不动 |
| 铜 | 101.HG00Y（COMEX 替代 LME，卡面已声明） | 有源·上卡 | 不动；LME 真源命中前不改口径（`:61`） |
| 原油 WTI | 102.CL00Y | 有源·上卡 | 不动 |
| **镍** | 无 | **待验**（候选两条，均未实探）：① LME 镍——但 HEAD 已实证「LME 铜多候选 secid 全部无行＋官网无免 key 稳定接口」（`:14-16`），同族推定凶多吉少；② 国内沪镍——东财期货板块前缀**未证**，须 `ulist.np/get`＋suggest 双探 | 命中⇒`_COMMODITY_UNIVERSE` 加行＋分组新增「有色金属」＋`_GROUP_ORDER` 同步（`:58`，分组顺序是渲染顺序，不能漏）；未命中⇒`commodity_availability()` 加 `("镍","unavailable: LME 与东财期货板块均无实测有效 secid")` |
| **铬** | 无 | **预判定结构性无源**：无交易所标准合约、行业报价站非免 key 公开接口（S 席未实探 ⇒ 定案须真机复核） | 若实探无果：登记 `unavailable`，文案写「铬无公开标准行情口径，不给数字」，**绝不拿不锈钢指数或化工品价顶替** |
| Brent / 农产品 | 已登记无源（`:213-214`） | 无源·在册 | 不动；新名册与之同读点 |
| 南向资金 002/004 | 数据可得、未接（HANDBOOK §24.8#6） | 候选 | 一行 `_NORTHBOUND_TYPES`（market_data:615-618）即可扩，须同时改能力标题与 brief 措辞（「北向」→「沪深股通／南向」） |

### 2.4 股指 · 逐市场（用户「全球股票」线）

18 席已覆盖用户点名面（含 MOEX/KOSPI/FTSE/CAC/DAX/SENSEX/STI/TWII/N225/HSI＋中国 5＋美 3）。缺口不在「名字」而在**硬锁**：`test_finance_market_expansion.py:131` 把宇宙**锁成 18**，加一枚必须同批改锁＋补 `_MARKET_FILTERS`（market.py:85-110）＋决定是否进腾讯交叉核验映射（`market_crosscheck._CROSS_CODES:30-38`，**无验证码就保持沉默，不许声明「已交叉核验」**）。无源市场（迪拜/阿联酋/澳门）与待裁 ETF 候选（105.UAE）保持原状，触发词「有源才补」（H-07）。

### 2.5 基金 / 公募 / 私募 / 期权 / 期货 · 现状与最小可行

**现状＝这条线完全没做**，且**今天是让路词**：`market._NON_STOCK_RE:64` 含「基金|期货」，`fx._STOCK_GUARD_RE:50` 含「基金」⇒「基金行情」「期货行情」落 chat 人格回复（`git grep 期权` 只命中两份 HANDOFF 与一份前端规划，零实现）。

最小可行（判清、不画大饼）：

| 线 | 可行性判定 | 建议范围 |
|---|---|---|
| **场内 ETF／指数基金（P0，本波可做）** | 复用**已实证的同一 ulist 族**，零新源族：`105.UAE`（HEAD 实证存在的NASDAQ ETF）与 9 家美股同前缀；A 股场内 ETF（1./0. 前缀与既有 5 只中国指数同族）**待实探** | 只加「成交价＋涨跌幅＋来源＋延迟」三件套；卡面与 brief **显式声明「场内成交价，非基金净值 NAV」**（语义裁决先例＝105.UAE 不得冒充国家股指）；新 RouteKind＋`bot.fund` 或并入 market 过滤面——**并入更省**（`_MARKET_FILTERS` 加词＋宇宙加行，不动路由席位） |
| 场外公募基金净值（P1，本波**不做**） | 需新源族（净值披露），HEAD 无任何实证端点；且境外/境内可达性受 #71 网络链影响 | 留下一波：先实探、先建证据册，再谈接入；本波只在文档登记「候选未接」 |
| **私募（永久不接）** | **结构性无公开净值/价格披露义务** | 只给诚实话术：「私募不公开披露净值，没有可核数」；**禁止**用同类公募或指数代理（＝顶替） |
| **期权（本波不接，先登记无源）** | 全树零源；期权链需页面接口且带反爬，无免 key 实证 | 登记 `OPTION_UNAVAILABLE` 形制的候选册＋诚实话术；真机探到有效 secid 才开线 |
| 期货（国内商品/股指） | 与大宗同一 ulist 族，**前缀未证**；镍即首个用例 | 实探命中⇒`_COMMODITY_UNIVERSE` 加行（0 新代码路径）；未命中⇒无源名册 |

---

## 3. 个股字段账（流通股数 / 股价 / 总市值 / 每日开·收·高·低）

| 用户要 | 字段在不在 | 展示在不在 | 卡点 |
|---|---|---|---|
| 股价 | ✅ f2（`_parse_quote:642`） | ✅ 卡＋文本 | — |
| 总市值 | ✅ f20（`fetch_market_cap:924`） | ⚠ 仅美元上卡 | **`:893-905` 非美元市值诚实门**＋`stocks.py:333-340` 硬编码「亿/万亿美元」；A 股/港股市值因此**今天一律显示「暂缺」** |
| 每日 开/收/高/低 | ✅ 日 K `f51,f52,f53,f54,f55,f56`＝**日期,开,收,高,低,量**（列序已实测，注意不是 OHLC） | ⚠ 卡与 brief 只写最新一日的「开/高/低」（`stocks.py:295-300`、`stock_data:1318-1324`），**收**只体现在现价、**昨收**不出现 | 逐日开收高低**已在 `OHLCVSeries.bars` 里**，只是没上版面 ⇒ 属展示层小改，零新源 |
| 日内 开/高/低/昨收（批量面板） | ✅ **已取已解析**：`_QUOTES_URL:1382` 请求 f15/f16/f17/f18，`_parse_quotes:1516-1521` 落进 `StockQuote.open/high/low/previous_close` | ❌ 面板行只用了 close/pct/market（`format_stock_line:1664-1688`、`_panel_capability:583-605`） | **现成套利**：渲染侧取用即可，不涉新字段、不涉新源 |
| **流通股数** | ❌ f85 已请求、**被置 None**（`_parse_quote:673`） | ❌（渲染行已写好 `stocks.py:368-374`） | H-03 裁定：f47/f48/f84/f85「单位口径可能差 100 倍（手↔股）」从未真机实测 ⇒ 不上卡；并被 `test_finance_market_expansion.py:265-290` **两枚锁**钉死（「上游给了也不消费」） |
| 总股本 / 成交量 / 成交额 | 同上（`:671-674`） | 同上 | 同上 |

**补流通股/总股本的正道**（禁止直接删门）：
1. 真机取同一家公司的 f84/f85，与**该公司官方披露的股本数**（交易所/SEC 文件）逐位对量纲；f47 与日 K `f56` 成交量、f5 交叉对「手↔股」；证据（日期＋公司＋两边数字）写进模块头注。
2. 定案后**同批**动四处：`_parse_quote:671-674` 恢复映射、`test_finance_market_expansion.py:265-290` 两枚锁改为「有值且单位正确」、`stock_data` 头注 H-03 段改口径、HANDBOOK §24.8 该条划账。**只动一边必红另一边**（台账 #68 的「成批」教训）。
3. 若实探证明单位仍不可证 ⇒ 保持 None，并在 brief 里从「静默省略」升级为「流通股暂无可核口径」（当前是整行消失，用户不知道是门还是缺）。
4. 非美元市值：把 `stocks.py:333-340` 的单位词改走既有纯函数 `_cap_unit()`（`stock_data:962`，brief 侧已在用）⇒ 再删 `fetch_market_cap:893-905` 分支（注释里已写明「能力层支持后删除本分支即恢复」），并改 `test_finance_market_expansion.py:299-312` 的断言（`value is None` → `value==3.7e12 且 cap 行标「港元」`）。

---

## 4. 逐文件施工批次（建议按 A→E 顺序，每批独立可绿可回滚）

> 每批完工判据都走 `scripts/dev.ps1 -Task test|lint|typecheck|runtime-layout`；绕开它直跑必须带规则 6 卫生前缀（`PYTHONDONTWRITEBYTECODE=1`、`-p no:cacheprovider`、`--basetemp=<仓库外>`）。

**批 A（先立尺，别急着补源）·覆盖凭据机制**
- `fx_data.py` / `bond_data.py` / `commodities_data.py` / `market_data.py` 各新增机器可读证据册：`_SOURCE_EVIDENCE: dict[str, tuple[str, str]]`（键＝secid 或 pair 或报表列名；值＝(实测日期, 实测方式)）。
- 各模块的覆盖表统一成同一契约形态：有源＝`"<provider>:<secid> <语义>"`，无源＝`"unavailable: <非空原因>"`（现形制已存在：`fx_pair_availability:311-320`、`commodity_availability:207-215`、`index_unavailable_entries:139-141`——本批只是**把「有源必须能在证据册里查到」变成门**）。
- 同步把 `has_currency_term:565-568` 的硬抄 11 码改为从单一真值派生（第二真身，见 §9-2）。

**批 B ·汇率 4 币（依赖批 A）**
- 真机实探 `119.USDRUB / 119.USDCHF / 119.USDCAD / 119.USDAUD`（`ulist.np/get` 单批＋suggest 双验）；命中者：`_FX_PAIR_UNIVERSE`（`:261-272`）加行、`_CURRENCY_ALIASES`（`:458-486`，含繁体与「瑞郎/加元/澳元」惯用简称）、`_CURRENCY_DISPLAY`（`:501-513`）三处同批；未命中者进新名册 `FX_UNAVAILABLE_CURRENCIES` ＋ `fx_currency_availability()`。
- 能力层 `fx.py:82-133` 的 `missing_note` 改为「`FX_UNAVAILABLE_PAIRS` ＋新名册」并集；**别名表一加，「美元兑卢布」就自动走 fx.py:228-232 的诚实回答**（现通路已验证存在）。
- 测试要同批改：`test_fx_data.py:294`（无源对精确相等）、`:297-311`（覆盖表键集＝宇宙∪无源）、`:268/274`（`len(...)==10` 硬数）。**注意 `:268` 那个 10 是「活宇宙数」，加一枚就得改，别让它变成软锁**。
- `test_finance_data.py:534-538` 是 `>=` 断言（扩币不会红）；但 `:586` `cross_rate_from_usd(table,"CHF","CNY") is None` 用的是 CHF——**若 CHF 进了 USD 表就会红**，改测试前先确认那是测试夹具而非生产语义（建议把该负例换成仍未接入的第三币，如 SEK，并注明理由）。

**批 C ·国债多国（依赖探源结论）**
- 探到源⇒`_CN_TENORS/_US_TENORS` 之外新增 `_XX_TENORS`＋`BondYieldSnapshot` 扩字段（`cn/us` 现为具名 tuple，`:96-99`）＋brief/卡面分节；探不到⇒只加 `BOND_UNAVAILABLE`＋`bond_unavailable_entries()`＋卡面 `delayed_note`（`market.py:481` 那行文案改为拼接名册）。
- 测试：`test_bond_data.py:73-87` 断言的是**逐位精确**的 (label, value) 列表——扩国/扩期限必须同批改；`:202-204` 锁 URL 形态。

**批 D ·大宗镍/铬（与 B/C 并行无冲突：文件域互斥）**
- 命中⇒`_COMMODITY_UNIVERSE:51-56` 加行＋`_GROUP_ORDER:58` 加「有色金属」；未命中⇒`commodity_availability():213-215` 加两条。
- 测试：`test_commodities_data.py:114-117`（覆盖表三条断言）、`:135`（**精确 secid 串相等**：`"101.GC00Y,101.SI00Y,101.HG00Y,102.CL00Y"`——加一枚必改）、`:138`（`len==4`）。
- 走势侧：`_KLINE_URL:77-81` **已带 `end`**，新品种复用 `fetch_commodity_trend`，禁另开 kline 出口（红线：东财 kline 必带 `end`，回归锁在 `test_commodities_data.py:233-234`／`test_finance_data.py:1253`／`test_market_card.py:397`）。

**批 E ·个股字段回填 ＋ 面板日内 OHLC（§3 步骤）**
- 只动 `stock_data.py:671-674`、`stocks.py:333-340` 与面板行取用（`:583-605`）＋ `test_finance_market_expansion.py:199/265-290/299-312`。
- 新日 K 展示走既有 `sub` 槽，**不动模板**（§5）。

**批 F ·基金/期权/期货**：本波只做「场内 ETF 并入 market 面」＋其余全部登记无源/候选；新 RouteKind 不建（要建就得同批动 `RouteKind` 枚举、`base_router` 两条、`capability_registry`、`echo._HELP_ENTRIES` topic、route-matrix、boards、`test_documentation_consistency`/`test_trigger_bidirectional_gate` 的台账棘轮——成本与风险都在文档链上，不在代码上）。

---

## 5. 三卡走 `finance_card` 契约的硬约束

- 真身：`domains/render/card_render/bridge.py:1786-1851` ＋ `templates/finance_card.html`；共用壳 `capabilities/market.py:238-289`；商品/国债/北向三卡＋fx＋stocks 全用它（**股指卡另走 `render_market_card_html`，别混**）。
- **白名单式取键**：payload 只认 `title/subtitle/badge/sections[{name,rows[{label,value,delta,cls,sub,trend_svg,trend_note}]}]/source_note/updated_at/delayed_note/bot_name/bot_avatar_url/feature_label/platform_color`；**未知键静默丢弃**（代码里 `stocks.py:416` 的 `logo_url` 就是「休眠契约」先例，模板无槽位）。⇒ 「新增一个『无源』字段」**属渲染契约改动，本域无权自作**；无源只有两条合法表达路：① 写进 `delayed_note` 文案（股指/国债/北向现役做法）② 塞一行 `label:"暂无数据", value:<名册串>`（fx.py:111-119 做法）。
- `cls` 只许 `up|down|flat`，非法值被折成 `flat`（`bridge:1813-1819`）；`trend_svg` 必须匹配 `^<svg…</svg>$` 否则丢弃并回退 `trend_note`（`:1810-1824`）⇒ **只有 `domains/finance/data/finance_chart.py` 产出的 SVG 能进卡**，别手拼。
- 空 rows 的 section 整节被删（`:1827-1830`）⇒ 「无源所以整节消失」是**默认行为**，正因如此才必须显式留一行/一句，否则缺席变静默。
- 出图失败→纯文本兜底，契约零破坏（`_render_finance_sections_card:288-289`）；落盘名 digest 由 `prefix + 各行 value` 组成（`:268-282`），**加行会换文件名**（正常，`prune keep=120`）。
- 模板哈希在册：`tests/render_hashes.json:12`；动模板必牵 `test_rendering_contract.py` / `test_template_visual_audit.py` / `test_e03_typography.py` / `test_token_supply_chain.py` / `test_brand_capsule_contract.py` / `test_phase_determinism*.py` 六族——**本单所有批次都标着「零模板改动」，若要改模板请先回主会话裁决**。

---

## 6. 验收判据（含注毒自证）

**通用判据（规则 5）**：每批交付必须附 ①提交哈希 或 ②可复跑命令＋实跑输出；③真机验收＝bot 在线后 `python scripts/e2e_acceptance.py --target-group <白名单群ID> --execute`（默认 DRY-RUN），并逐条口头点名「哪个币/哪国债/哪个品种是缺席的、缺席话术长什么样」。

**五把新门（建议落 `tests/test_finance_coverage_roster.py`，全离线 monkeypatch 网络出口单点）**

- **门 1 ·有源必带凭据**：遍历 `_FX_PAIR_UNIVERSE / _COMMODITY_UNIVERSE / _INDEX_UNIVERSE / bond _*_TENORS` 每枚键，断言其在同模块 `_SOURCE_EVIDENCE` 里有条目（值＝(日期,方式)）且日期格式合法。
  *注毒自证*：删掉任一枚证据条目 ⇒ 门 1 必红（照 `tests/test_prompt_injection_order.py` 的「注毒自证」腿写法，用 `tmp_path` 副本或对模块 dict 做 `pop` 后重跑判据函数）。
- **门 2 ·覆盖表二分封闭**：每枚「用户点名对象」（11 币 / 6 国国债 / 5 品种）必须**恰好**落在「有源覆盖表」或「无源名册」之一，且无源原因串非空；不得两边都不在（＝静默消失）。
  *注毒自证*：把 `RUB` 从两边都摘掉 ⇒ 门 2 红；把 `RUB` 写成 `eastmoney:119.USDRUB` 而证据册没这枚 ⇒ **门 1 红**（这就是「无源币种被编成有源 ⇒ 门必红」的主锁）。
- **门 3 ·缺席必须可见**：能力层出卡 payload 的 `delayed_note` 或 rows 里必须含无源名册的每一枚名字（断言 `all(name in html)`），文本 brief 同理；
  *注毒自证*：把名册从 payload 拼接处摘掉 ⇒ 红（现成样板＝`test_market_fin_phase1.py:269` 那句 `assert "1 年期暂无稳定免费源" in html`）。
- **门 4 ·单位未证即 None**：`float_shares/total_shares/volume/amount` 只要 `_SHARE_UNIT_EVIDENCE` 未登记该字段 ⇒ 解析结果必须为 None 且卡面不得出现该行；
  *注毒自证*：夹具里塞 `f85=9.4e9` 且不给证据 ⇒ 断言 None 必须仍成立；给了证据条目后必须能出数（防门退化成永真的「永远 None」）。现有 `test_finance_market_expansion.py:265-290` 归并进这枚。
- **门 5 ·红线不松动（存量跟随锁）**：① 非上市契约结构性无价格字段——沿用 `test_finance_data.py:305-315` 的 `hasattr` 逐名禁用（`price/open/high/low/close/volume/ohlc`）；② 北向无 net 字段——扩 `NorthboundFlow` 字段名册时禁 `net`；③ 单一估值口径——`test_stock_data.py:525-529` 禁止第二套数字；④ kline 必带 `end`——三处锁（`test_commodities_data.py:233-234`／`test_finance_data.py:1253`／`test_market_card.py:397`）新增取数口后须**逐一枚举覆盖**（照 `test_finance_market_expansion.py:128-132` 的「宇宙数硬锁」形制，把 kline URL 常量集合纳入遍历，别再加一条单点断言）。

**回归面**：`test_finance_data / test_fx_data / test_fx_card_semantics / test_bond_data / test_commodities_data / test_market_fin_phase1 / test_finance_market_expansion / test_finance_routing / test_finance_route_wiring / test_market_exclusion_guard / test_stocks_hijack_guard / test_market_crosscheck_tencent_gbk / test_stock_data / test_stock_technical_indicators / test_finance_charts / test_market_card / test_market_backoff / test_market_github` 全绿；加触发词后补 `test_trigger_bidirectional_gate`、`test_pinyin_triggers*`、`test_traditional_help_aliases`；改文档后补 `test_doc_sync_gates`＋`scripts/doc_sync.py --check`＋`scripts/board_doc_sync.py --check`。

---

## 7. 风险与回滚

1. **「为了齐全而编源」是本域最贵事故**（北向净买入、LME 铜、1Y 国债、MOEX 无东财 kline 四次先例都在 HEAD 留了痕）。对策＝门 1＋门 2 的凭据册，机制先落地再补源（批 A 必须先合）。
2. **精确数硬锁成串**：`_INDEX_UNIVERSE==18`、`_STOCK_UNIVERSE==9`、`len(list_listed_companies())==26`、`FX_UNAVAILABLE_PAIRS==(...)`、商品 `calls==[单条 secid 串]`、`len==10/4`。加一枚改一处即可，但**必须同批**，否则「代码加了、门还锁着旧数」＝当场红。
3. **可达性风险受 #71 网络链牵动**：`er-api.com`（HEAD 自陈不可达）与任何境外新增源要走实探复测；`http_util._build_opener:145-171` 空代理＝回落环境/系统代理，改源时**不许顺手关 trust_env 回落**。若新增 MOEX 货币端点，用 `iss.moex.com`（HEAD 实证可达）而非新域名，风险最小。
4. **限流退避面**：新增批量行会让单次 `ulist` 响应变大，保持「一次批量外呼」纪律（`test_fx_data.py:237` 锁 `len(calls)==1`）；别改成逐币循环。
5. **渲染配额**：卡面行数增加会撑 1160×1400 视口（商品债北三卡），必要时把无源名册收进**一行 `delayed_note`** 而不是逐行 tiles。
6. **文档链成本 > 代码成本**：新增 enabled/timeout 类配置键要走「config 字段＋`.env.example`＋catalog＋热改名单表态」四面（`test_config_hotchange_consistency_gate.py` 腿 A 明确：**新字段既不进名单又不进 `DELIBERATELY_UNLISTED`＝红**）。本波尽量**复用既有六键**，不新增开关。
7. **回滚**：每批一提交；名册类改动是纯常量＋文案，`git revert <批哈希>` 即回到上一批形态；批 E 若上线后判定单位仍不可证，恢复路径＝把 `_parse_quote:671-674` 四行改回 None **并同批恢复两枚锁**（只改一边必红另一边）。
8. **生效面**：全部改动**待用户提权重启 bot 才生效**（规则 3 铁律＋台账 #10 先例）；当前生产进程跑的是重启前码，且主树被清空、`AGENTS.md`/源码盘上无件——**施工前必须先恢复工作树**，否则门连读文件都读不到（`test_doc_link_integrity.py:807` 直读 `ROOT/AGENTS.md`）。

---

## 8. 待用户裁定（大白话版）

- **A. 只补有把握的**：先立凭据册（批 A）＋把 RUB/CHF/CAD/AUD、镍、多国国债全部**实探一遍**，命中的上卡、没命中的老老实实写「暂无数据源」。**推荐这一条**——一次把「齐不齐」和「真不真」同时管住，代价是要她/真机跑一轮探测。
- **B. 先补个股字段**：只做 §3 的流通股/总股本/非美元市值/日内 OHLC 展示（零新源、纯取用与量纲实测），覆盖面缺口留下一波。见效最快、风险最低。
- **C. 一次全都要**：A＋B＋场内 ETF 并入股指面。改动面横跨 6 个数据文件＋3 个能力文件＋约 15 个测试文件，**并发席冲突概率高**，不建议本波一口吃。
- 顺带请她拍：非美元市值上卡后单位词用「亿港元/亿人民币」还是统一折成美元（折美元要引入汇率源＝跨域耦合，建议**不折、如实标币种**）。

---

## 9. 本席顺手抓到的域外缺账（不属金融域，提请主会话）

1. **`docs/HANDBOOK.md` 在 HEAD 只到 §50.13**（4887 行实测），而 `AGENTS.md` 台账行 #63–#69 引用 §52/§53/§54/§55（含 §53.6–§53.9、§54.9），`HANDOFF` 线还引用 §57——**指向的节整片不在册**（末笔＝`5c8ab460`「知识库换代波落账」，`git --git-dir=… log --oneline -- docs/HANDBOOK.md` 实测）。金融增量的落账点因此悬空：本单建议落 **§58 新节**，但要先确认 §51–§57 是不是 09-29 还原事故的另一批未捞回件。
2. **体积顶机器门不存在**：`AGENTS.md:5` 与台账 #62 都宣称由 `test_entry_docs_within_size_ceiling` 执法，但 `git grep -n "size_ceiling|32768|体积硬顶" HEAD -- tests scripts` **零命中**；`HANDOFF-RESCUE-20260930.md:58` 反把它列为「批⑮ 的前置」。同时 HEAD:AGENTS.md＝**31,742 字节**，距 32,768 只剩 1,026 字节 ⇒ 任何人往第四部分加行都无人拦（本域若要加金融行，先补这枚门）。
3. **`AGENTS.md` 金融两行载体已指垫片/旧路径**：`:115`「全球股指」与 `:118`「大宗商品/债券/北向」写 `capabilities/market.py + sources/market_data.py + sources/commodities_data.py + sources/bond_data.py`，而真身在 `domains/finance/**`；`plugins/bot_unified_runtime/capabilities/market.py` 只有 7 行＝Compat 垫片（HEAD 实测）。按 `test_doc_link_integrity.py:835-896` 的口径它们落 `shim`/`moved`（走棘轮不硬红），所以**门不会拦**——建议改指真身，顺手降误导面。
4. **`has_currency_term` 里硬抄第二份 11 币码**（fx_data.py:565-568）；扩币时若只改 `SUPPORTED_CURRENCIES` 就会「面板有、触发词没有」的分裂态（批 A 第 3 条处理）。
5. **boards 文档已 stale 一处**：`docs/boards/B05-.../finance/bond.md:28` 与 `commodities.md:25` 说 `bot_bond_enabled`/`bot_commodities_enabled` **config.py 未声明＝关不掉**，但 HEAD `config.py:508-510` **三枚都已声明**（`.env.example:537-539` 同步在册）。属生成标记外手写正文的漂移（规则 10 的又一例）。
