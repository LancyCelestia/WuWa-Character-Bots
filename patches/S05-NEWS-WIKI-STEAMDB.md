# S05 工单：新闻资讯 + 百科 + 历史上的今天 + Steam/iPad 数据

席位：S05 ｜ 基线：`8ad03e4`（HEAD 实测；**盘上无源码**，全部行号取 `git show HEAD:<路径>`）
本席只写了这一个文件；零 git 写、零配置改动、零进程操作、未跑 pytest。
网络探针＝简报明示「要判可达性，别假设」授权的**只读 GET**（2026-09-30 UTC 08:2x–08:4x，本机，UA 浏览器串）。探针复跑命令见 §8.4。

---

## 摘要（≤200 词）

四个诉求里，两个的账和简报给的口径不同，先纠两处再谈施工。

**一、新华社/人民日报的 RSS 不是「缺」，是「已停更」**：`xinhuanet.com/politics/news_politics.xml` 与 `people.com.cn/rss/*.xml` 本机直连 200、XML 合法，但条目分别冻在 **2022-12-14** 与 **2025-06-05**（今日 2026-09-30）。按现架构接进来＝把旧闻当「今日快报」播。CNN 的 `rss.cnn.com` 经代理 502/SSL 失败，联合早报 `/rss` 返 HTML SPA——两者**结构性无 RSS**。国内权威源唯一实测**新鲜**的是中国新闻网/中新社 `chinanews.com.cn/rss/{china,world,importnews}.xml`（30 Sep 2026，0.1s，直连免代理）。⇒ 五源名册要连「新鲜度门」一起做，否则宁可不加。

**二、台账 #27 的先例是触发词缩写裁定（zb/bz/sz/sm），不是数据源裁定**，且 tests 内 0 文件写「永不启用」＝该裁定无执法门。对百科的直接约束：新能力**不得占 `bz`**。

**三、在线人数不用碰 steamdb**（/charts/ 实测 403 Cloudflare）：官方 `ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid=730` **免 key 实测 200**（694287 人）。热门清单更便宜——`steamfree.py` 已在用的 featuredcategories 同一响应里就带 `top_sellers`/`new_releases`。iPad 免费/热门＝Apple 官方 `rss.marketingtools.apple.com`（实测 200，无 iPad-only 维度）。

**四、百科查询与逐事件展开的数据早已在手里**：`eventsOnHistory` 每条带 `link/desc/type`（现被 `today_history.py` 丢掉只留 year+title）；`BaikeLemmaCardApi` 实测免 key 返 abstract+card+url。展开交互直接抄 `music.py` 的编号会话态。

营销过滤（`_AD_TITLE_RE`）与摘要行**零测试覆盖**——台账 #12 这条契约现在是裸的。

---

## 1. 现状账（HEAD 实测）

| 面 | 真身 | 实况 |
|---|---|---|
| 快报名册 | `domains/subscribe/feeds/news_feeds.py:79` `_FEEDS`（HEAD 实测） | 5 源：IT之家/少数派/V2EX/华尔街见闻/BBC中文；类目前缀 tech×3、finance×1、world×1 |
| 营销过滤 | 同件 `:71` `_AD_TITLE_RE`，命中点在 `:207`（标题**或摘要**命中即弃） | 有码**无测试**：全 tests 目录 grep `求职\|薅羊毛\|拼团\|_AD_` = 0 命中 |
| 摘要行 | 同件 `:169` `_entry_summary`（截 80 字）→ `:339` `format_news_brief` 缩进一行 | `tests/test_news.py` 的 `_sample_items()`（HEAD 实测 `:409-424`）**不带 summary 字段**，断言只锁 `lines[0..2]`；摘要契约只在 `tests/test_news_card_outbound.py:156,188` 有锁 |
| 能力侧 | `subscribe/capabilities/news.py:293` 调 `fetch_headlines`，键：`bot_news_{enabled,timeout_seconds=6.0,cache_seconds=600,max_items=20}`（`config.py:627-630`） | `_fetch_feed_text`（`news_feeds.py:110`）**不传 proxy** ⇒ 回落 `http_util._build_opener`（`:151`）的 `_DEFAULT_PROXY`；该模块级变量**全树无写入方**（grep 仅 `:49` 定义与 `:151` 读取）⇒ 实际走 urllib 默认 ProxyHandler＝吃 `HTTP(S)_PROXY` 环境变量/注册表系统代理（与台账 #71「`proxy=None`≠直连」同坑） |
| 维基 | `location/capabilities/wiki.py`（87 行）+ `location/data/mediawiki.py`（323 行） | 精确标题 → 列表内条目嵌查（`_lookup_embedded_entry`，候选页 `bot_wiki_entry_pages=["鳴潮角色列表"]`）；`variant=zh-hans`、重定向进 fragment 直接判空、消歧页判空 |
| 萌百 | `location/capabilities/moegirl.py`（672 行）+ `data/moegirl.py`（304 行）+ `link_parse/parsers/platforms_moegirl.py` | 主站+镜像双 base（`config.py:1289-1290`）；刻意不碰 `action=parse`（萌百 ACL 屏蔽，见 data 件 docstring）；2026-09-27 批改为**零 LLM 通路、出站无 URL** |
| 百度百科 | 只作「历史上的今天」的**数据口**：`subscribe/feeds/today_history.py:55`；离线补齐脚本 `scripts/today_history_kb.py:78` | **无独立查询能力**（简报正确）。但脚本已把 `BaikeLemmaCardApi` 的字段与 URL 口径跑通，可直接复用 |
| 历史上的今天 | `subscribe/capabilities/today_history.py`（425 行）+ `feeds/today_history.py`（148 行） | `fetch_today_history` `:59-66` **只保 year/title，丢掉 desc/link/type**；`format_history_text` `:142-148` 清单式列举（简报「约 134-146」＝HEAD 实测 134-148）；能力侧 `arg` 分支只认 状态/取消/设置/推送，**其余任何 arg 一律回「用法」**（`:384-390`）⇒ 现在打「历史上的今天 3」会被当非法参数 |
| Steam/Epic 免费 | `subscribe/feeds/steamfree.py`（55 行，`featuredcategories` specials 里 `discount_percent==100`）+ `epicfree.py` + `capabilities/epic.py:102` | 2026-09-30 实测 `specials` 里 **100% 折扣条目＝0** ⇒ 现能力此刻对 Steam 侧返回空列表（非 bug，是事实；对用户口径要「今日无限免」而非报错） |
| steamdb / 在线人数 | — | **全仓 0 命中**（简报正确，`git grep -i steamdb HEAD` 空） |
| iPad 免费游戏 | — | 已登记在册的**裁定性缺席**：`tests/test_epic_card.py:11`「iPad 免费游戏当前无数据源能力，不在本能力域（见 task-6 报告）」；另 `music/data/music_charts.py:322` 记 iTunes RSS topsongs 已停发条目 |
| 源权威分级（**已存在的资产**） | `domains/core/search/source_authority.py`（202 行） | 六档阶梯：`xinhuanet.com/news.cn/people.com.cn/cctv.com` = TIER_FIRST_PARTY，`bbc.com/bbc.co.uk` = TIER_MAJOR_MEDIA，`baijiahao.baidu.com/mbd.baidu.com/toutiao.com/sohu.com/360kuai.com/ixigua.com` = TIER_AGGREGATOR（＝自媒体档）；`_matches` 末段后缀匹配防抢注（`:173-179`） |

> 简报的两处口径要更正记账：
> ① **台账 #27★ `zb`/`bz`/`sz`/`sm` 是「拼音缩写触发词永不启用」的裁定**（`docs/design/v21r2-command-spec.md:96,188,265`、`v21r2-command-spec-inventory.md:128`），**不是新闻源裁定性缺席**；用它类比「源是裁定性缺席」不成立。真正属于「源侧裁定性缺席」的在册先例是 `today_history` 只接百度百科这一条。
> ② 该「永不启用」裁定**目前没有机器门**（tests 目录 grep `永不启用` = 0 命中；`v21r2-command-spec.md:324` 只把「永不启用词负样本测试」列为**提案**）。⇒ 本单涉及新别名时必须自带避让，别指望门拦你。

---

## 2. 五个新闻源的接入可行性分档（全部实测，非推断）

探针两条链：**直连**（`--noproxy '*'`，等价 `BOT_DOWNLOAD_PROXY` 留空且系统代理关）与**产线路径**（python urllib 默认 opener，吃 `HTTP(S)_PROXY=http://127.0.0.1:7890`，与 `_build_opener("")` 同形）。

| 源 | 端点 | 直连 | 产线（走 Clash） | 分档 | 结论 |
|---|---|---|---|---|---|
| 人民日报 | `http://www.people.com.cn/rss/politics.xml`（另 world/finance/it/society 同形） | **200**，382KB，`text/xml`，100 条 | 200 | **RSS 直取可行，但内容冻结** | 条目 pubDate 全为 `2025-06-05` ⇒ **接了就是旧闻**。只准在「新鲜度门」之后接入，实测不过则**不得入册** |
| 新华社 | `https://www.xinhuanet.com/politics/news_politics.xml` | **200**，174KB，`text/xml; charset=utf-8` | 200 | **RSS 直取可行，但内容冻结 4 年** | 条目 2022-12-14，且**无 `<pubDate>`**（时间戳是裸文本落在元素外）⇒ `_parse_datetime` 拿不到日期。`news.cn/rss.xml`、`news.cn/rss.htm`、`xinhuanet.com/politics/xwhl.xml` 全 404 |
| 中新社（**唯一实测新鲜的国内权威源**） | `https://www.chinanews.com.cn/rss/{china,world,importnews}.xml` | **200**，15KB，`text/xml` | 200，**0.1s** | **RSS 直取，立即可用** | 条目日期 `30 Sep 2026`＝今日；RFC822 pubDate 现解析器直接可吃；国家通讯社（中国新闻社）属一手/主流媒体档 |
| BBC 中文 | `https://feeds.bbci.co.uk/zhongwen/simp/rss.xml` | **超时**（8s 无响应，curl 28） | 200，但**301→`/zhongwen/trad/rss.xml`**，首连 **15.5s** | **需代理，且踩预算** | 15.5s > `bot_news_timeout_seconds=6.0` ⇒ **此刻 world 类目在生产里大概率静默失败**（单源失败静默跳过＝用户只看到条目变少，不报错）。`feeds.bbci.co.uk/news/world/rss.xml` 同链 4.9s 可作国际档替补（待验：单次样本，需复跑中位数） |
| CNN | `rss.cnn.com/rss/cnn_topstories.rss` / `edition.rss` / `cnn.com/services/rss/` | 000 / SSL 失败（curl 35） | **502** / 超时 | **结构性不可达** | 无 RSS 通道，**明写拿不到**。替代：CNN 属境外媒体，本 bot 要「国际要闻」应走已通的 BBC 英文族 + 中新社国际，或走联网检索链路（`web_search` + `source_authority` 已认 `bbc.com`）而非硬塞名册 |
| 联合早报 | `zaobao.com`、`/rss`、`/rss/realtime/china`、`/feeds` | 200 但 **`text/html`**（SPA 壳，无日期串） | **SSL: UNEXPECTED_EOF**（被拦） | **需反代/需解析器，非 RSS** | 要接只能自建 HTML→清单（同 `sources/market_data.py` 那类口径），且要先解决 SSL 截断；成本高于收益，建议列为**候选不排期** |

**待验清单（不许当已完成记账）**：中新社 RSS 的条目量与更新节奏（只测了一刻）、BBC 英文 feed 的稳定性、Apple RSS 的抖动（两次：200/2.2s 与 timeout）。

### 2.1 台账 #12 契约（营销过滤 + 摘要行）——扩为四条硬口径

新增源**必须逐源过同一把尺**，不许「先接进来再说」：

1. **营销过滤**：沿用 `news_feeds.py:71` `_AD_TITLE_RE`（真身唯一，禁在新源侧复刻第二份正则；`parse_feed` 已统一在 `:207` 拦）。
2. **摘要行**：`_entry_summary` 已对 `description|summary|content` 三支通吃，新源无需改解析器；但**缺摘要的条目不得编**（`format_news_brief` 现行为＝无摘要只上标题，保持）。
3. **新鲜度门（本单新增，必做）**：`NewsItem.published_at` 缺失或 `now - published_at > bot_news_max_item_age_hours`（建议缺省 48h，**数值待用户拍**，先跑真实分布再定）⇒ 该条丢；**整源全数超龄 ⇒ 该源记「陈旧」并丢弃全部条目**，同时打 `audit_tags=["news_source_stale:<source>"]`。这一条就是拦住人民日报/新华网的闸门；没有它，第 2 节两个 200 的国内源**一律不许入 `_FEEDS`**。
4. **诚实降级**：陈旧/被拦的源不得静默——现「部分源失败：条目变少，不报错也不声明」（`docs/boards/B05-external-data-services/news/news.md:33` 明文登记的缺陷 1）。本单要求把「类目内零可用源」与「类目源缩水」在 audit_tags 上可判别，**文案面仍保持不吓用户**（守岸人语气，走 `user_copy` 池）。

---

## 3. 「不许用自媒体」怎么机械执法

### 3.1 判据真身复用，不新建词表

`domains/core/search/source_authority.py` 已是「哪个来源更该先看」的**唯一在册表**（docstring 自陈「本件只回答哪个域名更该先看，不参与相关性判定」），且 `TIER_AGGREGATOR` 就是自媒体/转载档。⇒ **快报侧只准问它，禁在 `news_feeds.py` 再抄一份媒体名单**（第二真身＝规则 10 与 #48★「AGENTS 叙述≠真身」的同族坑）。

新增薄函数（放 `source_authority.py` 内，同件同门）：

- `is_authoritative_source(url_or_domain: str) -> bool`：`authority_tier(...) <= TIER_VERTICAL` 者为真；`TIER_UNKNOWN` **判 False**（快报是**点名要权威源**的场景，未登记＝不予采信，与检索侧「不丢弃」的取向刻意相反，需在 docstring 写明差异理由）。
- `SOURCE_AUTHORITY_LABELS: dict[str, str]`：给展示用短名（`xinhuanet.com→新华社`、`people.com.cn→人民日报`、`chinanews.com.cn→中国新闻网`、`bbc.co.uk→BBC`），供快报把 `source` 字段从「站点自报名」升级成「登记名」——远端 `<title>` 自称不可信（防换皮）。

`_FEEDS` 的元组建议从 `(url, 展示名, 类目)` 扩成 `(url, 展示名, 类目)`＋**注册期断言**：`展示名` 必须等于 `SOURCE_AUTHORITY_LABELS[normalize_domain(url)]`，不等即门红。这样「名册」只有一处真身。

### 3.2 门放哪（三处，各司其职）

| 门 | 落点 | 判据 | 为什么是它 |
|---|---|---|---|
| ① 名册白名单门 | `tests/test_news.py`（**已有件**，别新开文件） | 遍历 `_FEEDS`：每条 `assert is_authoritative_source(url)`；并 `assert authority_tier(url) != TIER_AGGREGATOR` | 与解析器/类目门同件，改动面最小；`_FEEDS` 是私名但已被 `tests/test_sdd7_n4.py:48` 直接 import ⇒ 先例在册 |
| ② 运行期出站门 | `news_feeds.py`：`parse_feed` 之后、入缓存之前，对每条 `item.url` 再过一次 `is_authoritative_source` | 名册对≠条目对（RSS 里转载链会指向别处）；`_merge_dedup` 前拦 | 单源失败静默跳过的既有语义不变 |
| ③ 注毒自证门 | 与 ① 同件，见 §7 | 夹具塞一条 `toutiao.com`/`baijiahao` 源 ⇒ ① 必红 | 证明门是活的，不是摆设 |

**负样本（必须绿）**：`baijiahao.baidu.com`、`mbd.baidu.com`、`toutiao.com`、`360kuai.com`、`ixigua.com`、`sohu.com` 全部判非权威；
**抢注探针（必须绿）**：`fake-reuters.com`、`evilpeople.com.cn` 不得命中（`_matches` 末段后缀语义已锁，见 `tests/test_source_authority.py` 不变量②，别放宽）。
**易误伤（要显式裁决）**：`ithome.com`/`sspai.com`/`v2ex.com` 现居 `TIER_MAJOR_MEDIA`/`TIER_VERTICAL`——IT之家/少数派算不算用户口中的「自媒体」？**本席不替用户拍**：门按现档放行，把裁定挂到 §9。

---

## 4. 百度百科独立查询能力（最小实现）

### 4.1 接口选择（实测，免 key 免登录）

`https://baike.baidu.com/api/openapi/BaikeLemmaCardApi?scope=103&format=json&appid=379020&bk_key=<词>&bk_length=600`
2026-09-30 实测 200，返回键（HEAD 实测 `scripts/today_history_kb.py:76-94` 已用了其中 4 个）：
`key, title, abstract, url, wapUrl, image, desc, catalog, card[], redirect, hasOther, newLemmaId, subLemmaId, copyrights`
—— `card` 是结构化信息框（`[{key,name,value[],format[]}]`），`catalog` 是章节目录，`redirect` 指向正主词条。**这两个字段现在没人用，是百科式展开的正解来源。**

选型理由与红线：
- 只走 openapi 卡片口，**不抓 `baike.baidu.com/item/<词>` 的 HTML**（页面重 JS + 反爬，且会把百科正文当 HTML 解析＝走 `link_parse` 那条 SSRF/消毒链，成本与风险都高）。
- `appid=379020` 是**公开页面自用值**，非密钥（不违规则 3）；但它属「别人家的配额」⇒ 复用 `mediawiki.py` 的 **TTL 缓存 + 最小请求间隔** 同形护栏（`WIKI_CACHE_TTL_SECONDS=900 / WIKI_MIN_REQUEST_INTERVAL_SECONDS=1.0 / MAX=256`），别裸调。
- 出站域名固定：`baike.baidu.com`；**必须经 `ssrf_guard`/`http_util` 既有咽喉**（`chat.py:1552` 与 `source_authority.py:140` 已各自在册登记该域，说明它在允许面内）。

### 4.2 新件落点（与维基/萌百同域同形）

| 件 | 内容 |
|---|---|
| `domains/location/data/baike.py`（新） | `baike_card(keyword, *, max_chars, proxy) -> BaikeHit | None`；`BaikeHit(title, abstract, url, image, card: tuple, catalog: tuple, redirect_to)`；解析失败/命中 `hasOther`（多义）/网络失败一律 `None` 或带标记返回，**绝不抛**（对齐 `wiki_summary` 返回 `""` 的口径） |
| `domains/location/capabilities/baike.py`（新） | `build_baike_capability(config)` + `is_baike_command/extract_baike_query`；能力 id `bot.baike` |
| 触发词 | `百度百科/百度/百科/baike/baidu baike/bbk/…`。**红线**：`bz` 撞台账 #27 永不启用清单（帮助域拼首永远缺位），**不得占用**；`bd` 与「报到/绑定」类词的自然语言胶合要先过 `scripts/probe_trigger_hijack.py`（HEAD 实测该探针件在册）。ASCII 别名一律带 `(?![a-z0-9])` 右边界（`wiki.py:29` 先例），斜杠门槛沿用 `today_history.py:60` `_SHORT_RE` 的短别名规则 |
| 配置键（`config.py`，与 wiki 同段） | `bot_baike_enabled: bool = True`、`bot_baike_summary_max_chars: int = 300`、`bot_baike_timeout_seconds: float = 5.0`、`bot_baike_cache_seconds: float = 900.0`。**幽灵字段坑（#68★）**：三件同批＝config 字段 + `runtime/settings.py` 热改态登记 + `.env.example`，只补一面必红另一面 |
| 注册面（一处不能少，见 §8.2） | `capability_protocols.CAPABILITY_DESCRIPTOR`、`capability_registry.ROUTE_CAPABILITY_DECLARATIONS` + `InterfaceEntry` + `HelpTopicDecl`、`aliases.py`、`base_router.py`、`__init__.py` 装配、`native_tools.py`、`echo.py._HELP_ENTRIES`、`board_taxonomy.py` |

### 4.3 卡片契约

- 默认**纯文本**：`标题\n概述\n（信息框 2-4 行）\n链接：<wapUrl>`。链接可给——百度百科是**显式指令能力**，与萌百 2026-09-27「零 LLM 通路、出站无 URL」那条裁定**不同域不同口径**，别顺手把 wiki/moegirl 的输出契约改花。
- 出卡走 `content_parser.render_card_png` + `build_parsed_content(platform="baidu_baike", item_kind="article", canonical_url=<真实词条 URL>)`——`today_history` 已在用这条（`capabilities/today_history.py:164-184`，`platform="today_history"`）。**F10 约定**：有真 URL 就给真 URL，`about:blank` 只留给无来源的卡。
- 多义（`hasOther`/`redirect`）⇒ **不押注**，回编号候选让人选（`_TITLE_SUFFIX_RE`、`music.py` 的候选态同形，见 §5）。这与「点歌同名先问」（台账 #18）是同一族行为，用户已认可过一次。
- 渲染铁律照旧：失败→纯文本兜底、契约零破坏（AGENTS 第三部分）。

---

## 5. 「历史上的今天」逐事件展开

### 5.1 数据源：**不用新增外呼**——现成 JSON 就把展开需要的字段给了

`eventsOnHistory/{MM}.json` 每条实测字段（HEAD 实测 `feeds/today_history.py` 只读 `year/title`）：

```
year  title(带 <a> 标签)  desc(HTML，百科式简介正文)  link(baike.baidu.com/item/<词>)  type(birth|death|event)  festival  cover  recommend
```

⇒ 最小改动＝ `HistoryEvent` 扩 `desc/link/event_type` 三字段（`@dataclass(frozen=True)`，`feeds/today_history.py:25-28`）+ 缓存落盘带上它们 + `format_history_text` 给每条**编号**。**当年那批 `desc` 就够 80% 的追问展开**，deep 层再用 §4 的 `baike_card(keyword=link 里的 /item/ 词)` 补。

**缓存 schema 迁移（必做，别踩）**：生产 `ChatBot_Runtime/data/today_history_cache.json` 此刻（2026-09-30 00:30 写入）是 `{"date","events":[{year,title}]}` 旧形。读侧必须对缺字段容错（`item.get("desc","")`），写侧升 schema 版本号；**禁删该文件**（规则 2 运行数据保护）。旧形条目被追问时 ⇒ 走一次按需外查（`link` 可从 `title` 关键词猜，猜不准就诚实说「这条没带详情」）。

### 5.2 交互设计：编号 + 会话态（抄 `music.py`，不发明第三种）

现状：`_QUERY_RE` 已把尾部任意文本收进 `arg`，但 `arg` 非空时只认 状态/取消/设置/推送，**其它一律回「用法」**（`capabilities/today_history.py:384-390`）⇒ 这是唯一需要动的入口。

- 第一屏：`1. 1147 · 南宋皇帝宋光宗赵惇出生`（编号 + 年份 + 标题），末尾一行「想细看哪条，直接发：历史上的今天 3」。
- 追问：`历史上的今天 <序号>` ／ `/历史 <序号>` ／ 裸序号**只在会话态命中时**接受（防把群里数字当指令）。
- 会话态真身照搬 `music.py:512-530`：`_EVENT_SESSIONS: dict[str, tuple[float, list[HistoryEvent]]]`、`_prune_*`（按过期时刻淘汰，#22★审计口径）、`dict.pop` 原子取用（E2-6）、`isdecimal()` + try/except（P2#6，"①"/"²" 会崩 `int()`）、session key = `f"{session_type}:{session_id}:{sender_id}"` 按人隔离。TTL 与开关建议 `bot_today_history_detail_enabled: bool = True`、`bot_today_history_detail_ttl_seconds: float = 600.0`。
- 展开正文优先级：`desc`（去 HTML）→ 不足则 `baike_card()` → 仍空则回「这条百科没给出简介」。
- **序号越界/无会话态** ⇒ 回一句「今天有 13 条，发『历史上的今天 3』看第三条」，不报错、不静默。
- 推送侧（21:30 那类定时）**保持纯文本清单**，不带编号追问（既有「推送保持纯文本」裁定，见 `capabilities/news.py:24-25` 同款口径）。

### 5.3 数据源多样性（可选，需裁定）

用户要「百科式介绍」＝百度百科已够。若要加维基侧交叉：`mediawiki.wiki_summary(query, lang="zh")` 可直接吃 `desc` 抠出的关键词，形成「百科主、维基校验」双口；**但两次外呼串行走各自 TTL**，最坏时延翻倍 ⇒ 只在显式追问时做，别放进清单首屏。

---

## 6. Steam / iPad：在线人数与热门清单

### 6.1 在线人数：**steamdb 拿不到，明写拿不到；官方口免 key 可用**

- `https://steamdb.info/charts/` 2026-09-30 实测 **403 Forbidden**（Cloudflare 盾）；`robots.txt` 可读（`/charts/?compare=*`、`/topsellers/*.png`、`/calculator/`、`/embed/`、`/watching/` 等 Disallow）。⇒ **结论：不接 steamdb**。它的数值本身是从 Steam 派生的，绕一层反爬 + ToS 灰区去拿二手数，负收益。写进 docstring 作为裁定记录，别留「以后接」的暗账。
- **正解（实测）**：`https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid=<id>` ⇒ **200，`{"response":{"player_count":694287,"result":1}}`，无需 key**（该 method 免鉴权，与「Web API 一律要 key」的常见说法不同；此为本席实测，非推断）。
- 逐游戏在线：`appdetails` 已能给 `is_free`（实测 578080 `is_free=True`；252950 `False`）。**热门清单 → 逐个取在线数**这条链全免 key。
- 红线：① **禁并发轰炸**（`appdetails` 有 1s/390 请求量级风控；本仓 `GetNumberOfCurrentPlayers` 单 appid 一次调用）——用 `mediawiki.py` 的 TTL+最小间隔同形护栏；② 全局峰值另有 `https://store.steampowered.com/about/` HTML 内嵌值，属**待验**（本席未测，别写死）；③ 数字口径要显式「当前同时在线玩家（Steam 官方 API）」，**禁**与「历史峰值」混谈。

### 6.2 热门清单 = 现成响应的另一半（最便宜的一格）

`steamfree.py:16` 已在调 `featuredcategories/?l=schinese&cc=cn`。2026-09-30 实测该响应的顶层键（HEAD 实测现只取 `specials`）：

```
specials(10)  coming_soon(10)  top_sellers(10)  new_releases(30)  genres  trailerslideshow  0..5
条目字段：id name type currency discounted discount_percent original_price final_price
          header_image small_capsule_image large_capsule_image windows/mac/linux_available
          controller_support streamingvideo_available
```

⇒ 「Steam 热门清单」＝同一次抓取读 `top_sellers` / `new_releases`，**零新增外呼、零新 key**。注意 `free_with_video_player` 在 `cc=cn` 下**缺席**（实测键不存在），别按某些文档假设它在。

新增 `domains/subscribe/feeds/steamtop.py`（或把 `steamfree.py` 改名为 `steamstore.py` 同件多函数——**改名要连 `docs/design/v21r2-shim-retirement-inventory.md:74,506` 登记的 `sources.steamfree` 静态 re-export 垫片一起动**，退役要文件+账本行同批，#68★）。触发词建议 `steam热门/steamb榜/steam新游`，要过 `probe_trigger_hijack.py`。

### 6.3 iPad 免费/热门（Apple 官方 RSS，实测 200）

- `https://rss.applemarketingtools.com/api/v2/<storefront>/apps/top-free/<limit>/apps.json`（302→`rss.marketingtools.apple.com`）实测 200/2.2s，`feed.title="免费 App 排行"`，`results[].name/id/url/icon`（**注意：该 v2 feed 无 `genres`，我一次解析取 `genres[0]` 抛过 IndexError ⇒ 别假设有分类**）。同族还有 `top-paid/top-grossing`，storefront 可 `cn/us/jp/...`。
- **限制要如实说**：v2 只有「App 榜」，**没有 iPad-only、没有 games-only 维度**；`itunes.apple.com/cn/rss/ipadapplications/.../genre=6014/json` 实测 **400**（旧 RSS 生成器已退役），`itunes.apple.com/search?media=software&country=cn&genreId=6014` 实测 `results` 空。⇒ 「iPad 专属免费游戏」这个口径**给不出精确数据**，只能给「iPhone/iPad 通用免费 App 榜」并按 App Store 分类人工判读，或退化为 `search?media=software` 通用榜。**待验**：`lookup?id=` 逐条取 `genres`/`languageIsSupported` 再筛「Games」，可行但 N+1 次外呼，默认关。
- `tests/test_epic_card.py:11` 的登记要同步改口径（「无数据源」→「有榜无 iPad 维度」），否则机器册与实测背离（规则 10）。

### 6.4 「限免此刻为空」

实测 `specials` 中 `discount_percent==100` 条目 **0 条**。⇒ `epic`/`steam免费` 能力在 Steam 侧应输出「今日没有进行中的限免」这类**诚实空态**，而不是空列表或降级报错。核实现行为：`epic.py:102` `games.extend(fetch_steam_free_games(...))`，Steam 空时仅靠 Epic 侧撑——用户看不到「Steam 今天没有」这句 ⇒ 需要一格空态文案（走 `user_copy` 池）。

---

## 7. 注毒自证（本单三条，每条必须「注毒必红」）

放哪、怎么红，全部离线、monkeypatch 单点出口（`_fetch_feed_text` 是**唯一网络出口**，`news_feeds.py:110` docstring 自陈「测试打桩它即可拦截全部外呼」）。

1. **非白名单源混进快报 ⇒ 门必红**
   在 `tests/test_news.py` 加 `test_non_authoritative_feed_poison_fails_gate`：`monkeypatch.setattr(news_feeds, "_FEEDS", _FEEDS + (("https://www.toutiao.com/rss/index.xml","头条","tech"),))`，再跑 §3.2① 的名册断言 ⇒ 断言**必抛**（用 `pytest.raises`/反向 `assert not`，写成「若名册含 TIER_AGGREGATOR 域则 fail」的形态，保证绿的时候是真的没毒）。
   并加运行期腿：`monkeypatch.setattr(_fetch_feed_text)` 返回一条链向 `baijiahao.baidu.com` 的合法 RSS ⇒ `fetch_headlines` 结果里**不得出现该条**（§3.2②）。
2. **陈旧源 ⇒ 门必红**（台账 #12 的新鲜度腿）
   夹具塞一条 `pubDate` 为 2022 年的条目 ⇒ `fetch_headlines` 结果里不得出现；整源全旧 ⇒ 该源条目为 0 且 `audit_tags` 含 `news_source_stale:<source>`。**这条就是人民日报/新华网的守门弹**：谁把它们加进 `_FEEDS` 而没有新鲜度门，本用例红。
3. **营销条目 / 摘要行 ⇒ 门必红**（销掉现状「有码无测试」）
   夹具塞标题「【推广】某厂招聘 Java 工程师」⇒ 必须被丢（现在**没有任何测试拦得住把它摘掉**，这是台账 #12 的裸账）；夹具塞有 `description` 的条目 ⇒ `format_news_brief` 输出必含缩进摘要行。

> 消毒纪律（规则 11）：以上夹具是**本席自造的中性的假数据**，不含任何指令形态文本；落地者不得把真实站点正文当夹具原文粘进来。

---

## 8. 落地清单（分批、可独立验收）

### 8.1 批次切分（按文件域互斥，规则 7）

| 批 | 内容 | 文件域 | 依赖 |
|---|---|---|---|
| S05-A | 新鲜度门 + `_FEEDS` 名册白名单门 + 注毒三条（**先把裸账 #12 补上锁**） | `subscribe/feeds/news_feeds.py`、`tests/test_news.py` | 无 |
| S05-B | 中新社入册（实测唯一新鲜国内权威源）；BBC 超时口径修正（代理/预算） | 同上 + `config.py`（`bot_news_timeout_seconds` 是否分类目） | A |
| S05-C | 百度百科能力 `bot.baike`（data+capability+注册面+卡） | `location/data/baike.py`(新)、`location/capabilities/baike.py`(新)、注册 8 面 | 无 |
| S05-D | 历史上的今天：`HistoryEvent` 扩字段 + 编号 + 会话态追问 | `subscribe/feeds/today_history.py`、`subscribe/capabilities/today_history.py`、`config.py` | C（deep 展开走 baike） |
| S05-E | Steam `top_sellers/new_releases` + 在线人数（免 key 官方口）+ 限免空态 | `subscribe/feeds/steamfree.py`(或 `steamstore.py`)、`subscribe/capabilities/epic.py` | 无 |
| S05-F | iPad/App Store 榜（诚实标「无 iPad 维度」） | `subscribe/feeds/appstorefree.py`(新)、`epic.py` | E |
| 不做 | CNN / 联合早报 RSS / steamdb 抓取 | — | 结论=结构性不可达，写进 docstring 作裁定记录 |

### 8.2 新增一个能力必须同批动的面（HEAD 实测，以 `bot.wiki` 为样板逐件点名）

`runtime/capability_protocols.py:CAPABILITY_DESCRIPTOR`（唯一在册表，`test_capability_single_registration.py` D-a 执法）→ `domains/chat_reply/runtime/capability_registry.py`（`ROUTE_CAPABILITY_DECLARATIONS` + `InterfaceEntry` + `HelpTopicDecl`）→ `runtime/aliases.py` → `runtime/base_router.py`（matcher + `InterfaceEntry`）→ `runtime/natural_language.py`（若要 NL 入口）→ `domains/core/decision/shadow.py`（影子映射）→ `domains/core/board_taxonomy.py`（板块归属）→ `domains/core/search/native_tools.py`（若给 LLM 当工具）→ `domains/chat_reply/capabilities/echo.py:_HELP_ENTRIES` → `config.py` + `runtime/settings.py` + `.env.example`（#68★三面齐）→ `__init__.py` 装配 → 生成物 `docs/command-catalog.md`/`docs/config-catalog-full.md`/`docs/route-matrix.md`/`docs/boards/**`。
相关常驻门（本席未跑，逐条为在册件）：`test_capability_declaration_parity.py`（D-g 三处声明齐 + admin_only 活性 + 一 id 一入口）、`test_capability_single_registration.py`、`test_help_entries_coverage.py`、`test_copy_single_source.py`（同案文案重复聚类，`"百度百科公开接口 + 每日推送"` 已在册 `:97`）、`test_doc_link_integrity.py`（子门③ 逐条判「载体列是否字面真身」）、`test_documentation_consistency.py`（规则 10 计数）、`test_capability_manifest_gate.py`。

### 8.3 验收命令（四道门一律走 dev.ps1，规则 6）

```
powershell -File scripts/dev.ps1 -Task test
powershell -File scripts/dev.ps1 -Task lint
powershell -File scripts/dev.ps1 -Task typecheck
powershell -File scripts/dev.ps1 -Task runtime-layout
```
绕开它直跑必须带卫生前缀：`PYTHONDONTWRITEBYTECODE=1 pytest -p no:cacheprovider --basetemp=<仓库外> tests/test_news.py tests/test_today_history_robustness.py`。
真机（bot 在线、用户执行重启后）：`python scripts/e2e_acceptance.py --target-group <白名单群ID> --execute`；新增触发词必过 `python scripts/probe_trigger_hijack.py`，别名/主题同步 `python scripts/command_catalog.py --write` + `python scripts/board_doc_sync.py`。
**代码补丁待审不自动部署**（常令）：提交/推送/重启由用户执行。

### 8.4 本席可达性探针的可复跑命令（离线树无关，纯网络）

```
# 直连（模拟 BOT_DOWNLOAD_PROXY 空 + 系统代理关）
curl -4 -sL -o /dev/null -w "%%{http_code} %%{time_total} %%{content_type}\n" \
  --max-time 10 --noproxy '*' -A "Mozilla/5.0" <url>
# 产线路径（与 http_util._build_opener("") 同形：urllib 默认吃 HTTP(S)_PROXY）
PYTHONDONTWRITEBYTECODE=1 python -c "import urllib.request as u;print(u.build_opener().open(
  u.Request('<url>',headers={'User-Agent':'Mozilla/5.0'}),timeout=12).status)"
```
> 记账注意：本席在 **Git Bash 会话**测得 `HTTP_PROXY/HTTPS_PROXY=http://127.0.0.1:7890`、`NO_PROXY=localhost,127.0.0.1`。生产 bot 进程的代理继承面**未查**（不读 `.env`，规则 3；且 `.env` 此刻不在源码树，见 2026-09-30 清空事故）⇒ BBC/steam 类境外源「生产到底走不走代理」标**待验**，落地前先现算一次。

---

## 9. 需用户裁定（本席不代拍）

1. **人民日报/新华网**：实测可达但内容冻结 16 个月/4 年。是「接了但被新鲜度门全拦＝等于没接」，还是**放弃官方 RSS、改走 `web_search`+`source_authority` 的时政检索轨**（该轨已认这些域名为一手源）？
2. **IT之家/少数派/V2EX 算不算「自媒体」**？它们在 `source_authority` 是 MAJOR_MEDIA/VERTICAL，不是 AGGREGATOR；若按用户口径判为自媒体 ⇒ `_FEEDS` 现在 5 源里要掉 3 源，`tech` 类目直接见底。
3. **新鲜度阈值**（建议 48h）与**陈旧时是否对用户说一句**（现缺陷 1 是「不报错也不声明」）。
4. **百科是否默认出卡**、是否给 LLM 当 `native_tools` 工具（给＝正文入 prompt，注意反注入包裹与 `guard_secondhand_text`）。
5. **iPad 口径**：接受「免费 App 榜（无 iPad/游戏维度）」还是维持现状「诚实说没有该数据源」（`test_epic_card.py:11` 现登记）。
6. **联合早报**要不要为它自建 HTML→清单解析器（境外 SPA + SSL 截断），或列入 `docs/feature-backlog-20260930.md` 不排期。
