# U19-CORRECT 能力实质正确性抽查日志（2026-09-20）

> 席位：U19-CORRECT（只读审计子代理）。目标：逐个能力查「业务算得对不对、失败时诚不诚实」。
> 红线：绝不编数——凡「无源却出数、单位/时区/币种错算、空响应被洗成 0、失败被伪装成成功」一律 P0/P1。
> 禁令遵守声明：本席未派子代理、未做任何 git 写、未改任何代码/配置/文档（仅本日志）、未 --write、
> 未真实联网、未真实 LLM 调用、未读 .env 明文值、Runtime 只读。
> 范围裁定：只查后端 Python 业务实现；不查 webui/、domains/render/**、output/card_render/**、
> theme_tokens.py、TTS/语音链路。

## 状态看板

- [ ] 0. 前置阅读（AGENTS 第四部分 / 台账相关行 / U9 功能审计谱系）
- [ ] C1 金融（股指/个股/商品债券北向/汇率）
- [ ] C2 天气与地理
- [ ] C3 时间语义（提醒/摘要/每日助理/历史上的今天/多历法）
- [ ] C4 订阅 / 摘要 / 快报
- [ ] C5 点歌 / 链接解析 / 媒体归档业务面
- [ ] C6 好感度 v5 与心情
- [ ] 汇总：无源编数风险点汇总表 + 能力面回归缺口 + 未覆盖清单

## 环境卫生自查

（占位：PYTHONDONTWRITEBYTECODE 失效情况、源码树残留自查结果，完工前回填）

---

# C1 金融三件 + 汇率

## 取证方法

- 通读 `domains/finance/data/{stock_data,market_data,market_crosscheck,fx_data,commodities_data,bond_data,finance_chart}.py` + `capabilities/{stocks,market,fx}.py` 全文 + `domains/core/contracts/finance.py`。
- 离线复算脚本 `C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot/%TEMP%/u19_recheck_finance.py`（零网络：全部外呼出口 monkeypatch，喂构造夹具），实跑 **51 checks / 0 FAIL**，可复跑：
  `cd ChatBot && PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe "%TEMP%/u19_recheck_finance.py"`

## 算对了的部分（实算证据，防止后文被误读为「金融全错」）

| 校验点 | 输入→期望→实际 | 结论 |
|---|---|---|
| KDJ 1/3 平滑手算 | 3 根 period=3（H_n=12,L_n=8,C=12→RSV=100）→ K=66.667/D=55.556/J=88.889 | ✅ `kdj-3bar` |
| KDJ 一字板中性 | 9 根全 H=L=C → K=D=J=50（不放大信号） | ✅ `kdj-yiziban-neutral` |
| type-7 分位（numpy/QUARTILE.INC 口径） | 300 组随机序列 vs `statistics.quantiles(method="inclusive")` | ✅ mismatch=0 |
| 箱形样本门 | 4 值 min_samples=5 → (None,"insufficient_data")；NaN 被剔除 n=5 | ✅ |
| 日收益 | [100,110,99] → (+10.00,−10.00)% | ✅ |
| MACD/RSI/WR/CCI | 常值→全 0；全涨 RSI=100；WR 末窗 (160,145,C=159)→6.667 与手算一致 | ✅ |
| JPY unit_base 换算（正反） | 100日元中间价 4.8852/100 → 「100日元换人民币」=4.8852；「人民币换日元」1 CNY=100/4.8852=20.47 JPY（反向分支 `unit_base/rate` 单位处理正确） | ✅ `fx-jpy-direct/inverse` |
| 国债利差推导 | 10Y=1.6899、2Y=1.2466、直供列 null → 0.4433 + derived_notes「计算」标注；上游直供 0.33 优先 | ✅ `bond-spread-derived/direct` |
| 北向量纲 | DEAL_AMT=142256.09（百万元）→ 1422.56 亿元（/100）；无交易日行→None 不造行 | ✅ `northbound-unit` |
| 停牌/缺字段不造 0 | f2="-" → price=None + UNAVAILABLE（非 0） | ✅ `quote-suspended-not-zero` |
| 交叉核验真比对 | GBK 短/长格式夹具 → 一致 2/2；3900 vs 3842.6（差 1.5%>0.5% 容差）→ 「⚠ 0/1 一致，差异：…腾讯 3842.60」显式差异；通道抛错 → checked=0 且脚注空串（沉默不声明不伪造） | ✅ `crosscheck-*` |
| **空响应重试覆盖面（`bot_market_retry_on_empty` 实证）** | 逐出口喂空响应计调用数：股指快照/指数kline/个股现价/K线/市值/批量面板/历史/东财汇价/商品快照/商品kline/国债/北向（两通道各自 2 次）全部 calls=2；开关关=1；**真异常（ConnectionError）=1 不重试**；er-api 汇率快照异常路径不重试且 missing=10 币诚实 | ✅ 12/12 出口全覆盖 |
| kline `end` 参数（台账 #11 回归） | stock/market/commodities 三处 `_KLINE_URL` 均含 `end=20500101` | ✅ |
| 非上市红线（三层） | ①契约：`NonPublicEquityNote` 无价格字段、`fetch_stock_quote/ohlcv` 对非上市在**任何外呼之前**早退（`_non_public_quote/series` source=""）；②能力：`capability()` NON_PUBLIC 分支先于一切 fetch（stocks.py:683 起），grep 证 `fetch_market_cap` 唯一生产调用点 stocks.py:696 在该早退之后——「估值被当市值」无可达通路；③呈现：brief 只给「最近公开估值 ≈8520 亿美元（2026 年 3 月）+来源 URL」。两条链路（NON_PUBLIC_EQUITIES/_OPENAI_RECORD）同 8520 亿口径无第二套数字 | ✅ 结构性成立 |
| TWD/MOP/AED 无源 | `FX_UNAVAILABLE_PAIRS` → 定向查询 body「暂无数据（东财无该货币对行情）」；面板行「暂无数据」上卡；解析层照常命中但覆盖表标 unavailable | ✅ 真不接 |
| 无源市场登记 | 迪拜/阿联酋/澳门 `INDEX_UNAVAILABLE` 出现在 brief 与卡 `delayed_note`「暂无数据源」注记 | ✅ |

## C1 发现（七要素）

### F-U19-01｜P2｜走势折线宣称「近 30 个交易日」实喂 60 根，且同卡混两种窗口

- **坐标**：`domains/finance/data/market_data.py:431`（锚点 `_TREND_MAX_POINTS = 60`）、`:560`（锚点 `closes = tuple(values[-_TREND_MAX_POINTS:])`）、`domains/finance/capabilities/market.py:790`（锚点 `subtitle = "红涨绿跌 · 折线为近 30 个交易日收盘"`）；`commodities_data.py:82` 同款 + `market.py:376` 锚点 `"subtitle": "红涨绿跌 · 折线为近 30 个交易日收盘"`（商品卡）。
- **根因**：接口窗口从 30 扩到 60（或本来按计划取 60）时，副标题文案没跟着改；MOEX 备选源单独钉 `_MOEX_TREND_POINTS = 30`，形成同卡两种窗口。
- **证据（实算）**：`trend-window-claim` check 实跑输出 `eastmoney trend=60 pts / MOEX=30 pts / 卡副标题宣称『近 30 个交易日收盘』`；`_KLINE_URL` 实参 `lmt={days}` 以 days=60 格式化（`fetch_index_trend` `_get()` 内 `days=_TREND_MAX_POINTS`）。
- **改法**：before `closes = tuple(values[-_TREND_MAX_POINTS:])` → after 出卡侧切片 `trend=list(trends.get(quote.code) or ())[-30:]`（或把 URL lmt 与文案统一为同一常量，单一事实来源）；商品卡同理。
- **验证**：新增断言：卡 payload 每行 `len(row["trend"])<=30`（夹具 60 根输入）；复跑 `…python.exe -m pytest tests/test_market_card.py -p no:cacheprovider --basetemp="$TEMP/u19-trend" -q`。
- **回归缺口**：现无测试锁定「副标题窗口 == 实际点数」；`test_market_card.py` 只测渲染与失败缺席。

### F-U19-02｜P2｜汇率面板 JPY/CNY 行裸值 4.8852 无「每 100 日元」标注，100 倍量纲歧义上卡

- **坐标**：`domains/finance/capabilities/fx.py:101-109`（锚点 `"value": f"{rate.rate:.4f}"` 与 `"sub": type_note`）；数据侧 `fx_data.py:264`（锚点 `("JPY/CNY", "120.JPYCNYC", "parity", 100.0, …)`）。
- **根因**：定向换算/纯文本链路都做对了 unit_base 折算（评审 P0-1 先例+回归锁），但**面板卡行**直接展示上游原始中间价（每 100 日元口径），行 sub 只有「人民币中间价」，无 100 单位字样。
- **证据（实算）**：`fx-jpy-direct`：同一枚币对，行面展示 4.8852，真实「1 日元」价 0.048852——读表人按「JPY/CNY=4.8852」理解为 1:4.89 将错 100 倍；grep 全树 `每100|100日元口径` 仅存在于代码注释与帮助示例，卡面无。
- **改法**：before `"label": f"{rate.base_currency}/{rate.quote_currency}"` → after 当 `unit_base != 1` 时 label 追加口径：`f"{base}/{quote}（每{unit_base:g}{base}）"` 或 value 前缀「×100」。
- **验证**：`tests/test_fx_card_semantics.py` 扩断言：JPY/CNY 行文本含「100」。
- **回归缺口**：unit_base 回归锁（`test_finance_data.py:1079 test_amount_conversion_uses_unit_base`）只锁 body/brief，未覆盖面板行。

### F-U19-03｜P3｜卡面时间戳时区口径三张牌：个股卡标 UTC、面板/商品/国债/北向/汇率卡为无标记本地钟

- **坐标**：`market.py:221`（锚点 `"updated_at": _time.strftime("%Y-%m-%d %H:%M:%S")`）、`market.py:712` 同款、`fx.py:130`（锚点 `"updated_at": rates[0].timestamp if rates else ""`，源头 `fx_data.py:422` 锚点同上行 `timestamp = time.strftime(...)` 本地 naive）、`stock_data.py:1548` 同款；对照 `capabilities/stocks.py` 个股卡 `subtitle = quote.as_of.strftime("%Y-%m-%d %H:%M UTC")`（aware UTC 带标记）。
- **根因**：无中央时钟（U9 F-U9-05 同根，本席只记业务后果）：同一金融卡族内「更新时间」一处 UTC、五处本地裸串。
- **证据**：代码实录 + 本席 20:xx 本地钟复跑时 `StockQuote.timestamp` 样例输出（本地时刻无 tz 后缀）；台账 #6 已记 cron 本地钟偏移族。
- **改法**：before `time.strftime("%Y-%m-%d %H:%M:%S")` → after `datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")`（或统一 UTC + " UTC"），六处一次收口。
- **验证**：断言各卡 `updated_at` 含 tz 标记（正则 `\d{2}:\d{2}:\d{2}( UTC| \w+)$`）。

### F-U19-04｜P3｜个股 K 线失败态对象币种硬编码 USD（CNY/HKD 标的元数据错标，不涉数字）

- **坐标**：`stock_data.py:850`（锚点 `note=f"K 线拉取失败：`，上一行 `currency="USD",`）。
- **根因**：异常分支手抄默认值，未用 `ref.currency`（同函数成功路径与 `_parse_klines` 都正确用 `ref.currency`）。
- **证据**：构造 `_fetch_kline_payload` 抛 ConnectionError + ticker="600519" → 返回 series.currency=="USD"（bars 空，无数字外泄；纯元数据错）。
- **改法**：`currency=ref.currency`。
- **验证**：`tests/test_stock_data.py` 加失败路径币种断言。

### F-U19-05｜P3｜USD/CNY 行实为离岸 CNH 口径，卡面不显「离岸」二字

- **坐标**：`fx_data.py:262`（锚点 `("USD/CNY", "133.USDCNH", "spot", 1.0, "美元兑离岸人民币")`——展示名自己写了「离岸」，面板行 label 却是 `USD/CNY`、sub「现货/参考价」）。
- **证据**：行面与 help 示例「美元兑人民币」指向同一数；在岸/离岸长期点差下用户以卡上数当在岸价属误导（轻）。
- **改法**：该行 sub 追加「离岸CNH」；验证：fx 卡语义测试扩断言。

### F-U19-06｜P3｜MOEX 停牌/延迟语境零标注（数据无错，语境不诚实）

- **坐标**：`market_data.py:210-251`（锚点 `def _fetch_moex_quote`；`as_of=time.time()` 抓取即当下）；全树 grep `制裁` 零命中。
- **证据**：MOEX 休市/停盘时 LASTCHANGEPRC 停在上场值，卡行与其余 17 指数无差别展示；行级机器字段 source=moex_iss 在，人类可读注记无（AGENTS 宣称口径「MOEX 走 ISS 真折线」为真，语境表述为缺口）。北向两通道 trade_date 可不一致而 header 只示 `trade_dates[-1]`（`market_data.py:726` 锚点 `交易日 {trade_dates[-1]}`）——单通道滞后时会被 max 日期掩盖（轻，同族登记）。
- **改法**：MOEX 行 sub/注记「MOEX ISS 官方源·休市期间为上一交易日收」（能力层纯文本字段，零模板改动）；北向注记改逐通道日期。
- **验证**：夹具（两通道不同 TRADE_DATE）断言 brief 各行自带日期。

## 与本席红线对照的「伪装成功」扫描（C1）

- 空响应/异常 → 全部 12 出口走 `[]`/UNAVAILABLE/missing 列表，**无一 laundering 成 0 或旧值**（`no-retry-on-real-error`、`fx-snapshot-fail-honest`、`bond-empty-honest` 实证）。
- 市值非美元诚实门：`mcap-cny-honest-gate` 实证 CNY 标的 `fetch_market_cap` **零外呼**、value=None+DEGRADED+「标注能力未就绪」注记——「不能如实标注的字段不上卡」在码层成立。
- `format_stock_line`/面板 `value` 的 falsy 判（`if quote.close else "暂无"`）理论上会把 0.0 洗成「暂无」——方向是**保守**的（有值不展示），非编数，登记不修。
- 唯一「数字进了错误标签」风险=上文 F-U19-01/02（窗口/量纲标注与数值脱节），均为标注失真非造数。

---

# C2 天气与地理

## 取证方法

- 通读 `domains/weather/data/{nmc_weather,open_meteo}.py` + `domains/weather/capabilities/weather.py` 全文。
- 复算脚本 `%TEMP%/u19_recheck_weather.py`（monkeypatch `http_get_json` 出口，零网络），实跑 **19 OK / 1 预期外**（该 1 条为本席对变体链尾段的过设期望，见 F-U19-11，非代码失败）。
- 复跑命令同 C1 风格。

## 算对了/诚实的部分（实算证据）

| 校验点 | 输入→期望→实际 | 结论 |
|---|---|---|
| qx.json 码表在位 | 2527 行加载 | ✅（铁律 6 资产现存） |
| 「东京」不塌国内码表 | `search_city_code("东京")`→None（码表无该名）→走 OM 人口排序 | ✅ F18 根因链在位 |
| geocoding count=10 + 排序 | 夹具三 Springfield（MA 27万/MO 5000/重名小镇）→ 选 `Springfield，MA，USA`，精确名+人口双键；URL 实带 `count=10` | ✅ |
| NMC 9999 缺数哨兵 | temperature="9999"/rain="9999.0"/speed="9999" → 全落 ❓，不打印 9999 假值 | ✅ |
| 变体链逐级拆分 | 「湘潭 雨湖」→ [原串, 湘潭雨湖, 雨湖]（末段区县优先）；裸「东京」=[东京] | ✅（链行为与实现一致） |
| 陈述句/口语守卫 | 「天气预报说明天下雨」拒、「天气真好」拒、「天气 上海」放行 | ✅ |
| 预警 token 过滤 | 「河北-大城」双 token 同中才命中（跨省同名防御在码） | ✅（代码实录） |
| NMC 主通道重试 | in_db 才重试 2 次（0.5s），码表未中零外呼不空耗 | ✅ `db-empty-zero-egress-silent` 副证 |

## C2 发现（七要素）

### F-U19-07｜P2｜qx.json 缺失=整链静默塌向 Open-Meteo：零外呼 NMC、预警段消失、无任何用户可见/运维可见标注

- **坐标**：`domains/weather/data/nmc_weather.py:23-27`（锚点 `except (OSError, ValueError):` → `return []`）、`capabilities/weather.py:95-96`（锚点 `if not in_db: return None`）、`:384`（锚点 `if source == "nmc":` 预警门）。
- **根因**：码表加载失败被吞成空表，与「海外城市查不到」在能力层不可区分；预警支路以 `source=="nmc"` 为前提，塌向后预警语义整体消失也不声明。
- **证据（实算）**：monkeypatch `_CITY_DATABASE=[]` 复演：`search_city_code("北京")→None`、`nmc_weather_query("北京")→None`、`_nmc_query_with_retry("北京")→None` 且 **NMC 外呼计数=0**；用户所得只有卡作者栏变「Open-Meteo」，正文无「主源不可用/无预警语义」任何字样。AGENTS 铁律 6 明载此坑 2026-09-13 曾实爆（wx7 报告）。
- **改法**：before `except (OSError, ValueError): return []` → after ①装配期 `_CITY_DATABASE` 行数 <2000 时 `logger.error`+告警（复用 runtime/alerts）；②能力层 `in_db` 全链失败且码表行数异常时，报告尾部加「主码表不可用，已降级全球源（无预警）」一行。
- **验证**：`tests/test_weather_nmc_fallback.py`（或同族）加 `_CITY_DATABASE=[]` 夹具断言 body 含降级注记 + 告警计数；复跑 scoped pytest。
- **回归缺口**：现无「码表空 → 用户可见降级」测试（只测了单城查询）。

### F-U19-08｜P3｜预警颜色解析按词表 dict 序取首个命中，「升级」类标题低估警级

- **坐标**：`capabilities/weather.py:176-198 parse_alert_title`（锚点 `for name in _ALARM_COLOR_RANK:` + `if name in text`）。
- **根因**：迭代序=字典插入序（蓝→黄→橙→红），非「文内最后出现」或「最高级」。
- **证据（实算）**：`alert-bluebeats-red`：标题「升从蓝色预警升级为红色预警」→ 解析色=**蓝色**；`alert-dual-color-trap`：「雷电黄色…大雾橙色」→ 黄色。排序权重 `_ALARM_COLOR_RANK` 随之把红警沉底。
- **改法**：before `for name in _ALARM_COLOR_RANK: if name in text` → after 取文中**最右出现**的颜色词（`max(rank_names, key=text.rfind)`），或取最高级（更保守）。
- **验证**：`tests/`（weather 族）加双色列标题用例；scoped pytest。

### F-U19-09｜P3｜Open-Meteo 部分字段 null 直排「None°C / 湿度 None% /风速 Nonekm/h」进行文

- **坐标**：`data/open_meteo.py:136-152`（锚点 `f"{current.get('temperature_2m')}°C"`、`f"今天 {min_t[0]}~{max_t[0]}°C"`）。
- **根因**：包络门只查 `forecast.get("current")` 真值，不查成员键值；daily 数组缺位以 None 填充展示。
- **证据（实算）**：`om-none-leak`：夹具 current 全 None → 行输出 `当前：雷暴，None°C，湿度 None%，风速 Nonekm/h`（未编数，但 None 裸奔=呈现事故；与金融域「缺失→暂无」纪律不对齐）。
- **改法**：`_fmt(v, unit)` 壳：None→「暂无」，缺失项省略整段（对齐 nmc `_format_value`❓语义）。
- **验证**：weather 族夹具断言无字面 "None" 出现在 report。

### F-U19-10｜P3｜OM geocoding 带 proxy、forecast 段丢 proxy——代理环境半通半断

- **坐标**：`data/open_meteo.py:63-68`（geocode `proxy=proxy`）vs `:109-122`（forecast `http_get_json(..., timeout=timeout)` 无 proxy；锚点 `"forecast_days": "2",`）。
- **证据**：`inspect.getsource` 实跑判定 `om-forecast-no-proxy`。生产 `.env` 代理配置时 geocode 通、forecast 断 → 整体 None → 用户见「没有查到」假象（失败被伪装成「城市不存在」）。
- **改法**：forecast 调用补 `proxy=proxy`。验证：source 级 grep 门或夹具（proxy 参数透传断言）。

### F-U19-11｜P3（登记为主，语义裁定）｜时间/来源语义差未在卡面显式：NMC=北京时 publish_time+观测值，OM=目的地时区「今天/明天」+模式化再分析；变体链不重试首段行政区

- **证据**：①`open_meteo.py` 锚点 `timezone=auto` + `今天/明天`（目的地日界）；NMC 报告锚点 `🕒 发布时间`（北京时，无 tz 字样）——同能力两源时间基准不同、卡上零标注（author 栏只标机构不标语义）。②变体链 `for part in reversed(parts[1:])`（锚点同左）不含 parts[0]：「湘潭 雨湖镇」（镇不在码表）NMC 侧永不重试「湘潭」市站，直接落 OM 全球源，同名异地镇由人口排序代选——location_label 有显示（可自查），但对用户是静默代答。docstring 写「各段倒序」与实现「除首段外各段」存在口径差。
- **改法**：①报告尾部追加「数据时点=北京时间」/「当地时间，来源 Open-Meteo」一行（纯文本零模板改动）；②链补首段兜底变体（区县失败后重试市站），或维持现状但把 docstring 改准并加测试钉死链序。
- **验证**：夹具断言 OM 分支 body 含「当地」时间字样；`_query_variants("湘潭 雨湖镇")` 含 "湘潭"。

## C2 无源编数扫描

- 两源均无「失败→造数」通路：NMC 失败→None→OM；OM 失败→None→诚实报错（私聊）/群聊静默（有 audit tag `weather_not_found_silent`）。未发现问题。
- 预警条数 `_ALARM_MAX_SHOWN=5` 截断有「其余 N 条略」注记（`format_city_alerts` 锚点 `（其余` ）——不藏数。

---

# C3 时间语义

（未开始）

---

# C4 订阅 / 摘要 / 快报

（未开始）

---

# C5 点歌 / 链接解析 / 媒体归档业务面

（未开始）

---

# C6 好感度 v5 与心情

（未开始）

---

# 无源编数风险点汇总表

（完工前回填）

# 能力面回归缺口

（完工前回填）

# 未覆盖清单

（完工前回填）
