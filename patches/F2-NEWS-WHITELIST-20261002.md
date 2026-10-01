# 席 F2 工单：今日快报「源白名单门」＋逐源可达性判定＋宣称⊆实装（2026-10-02）

席位：F2 ｜ 需求书：`.superpowers/sdd/2026-10-02-fixwave/SEATS.md` §7 ｜ 基线 HEAD `5d581b2`
独占面：`plugins/bot_unified_runtime/domains/subscribe/feeds/news_feeds.py` ＋ 新建门件 ＋ 本工单
零 git 写、零配置改（`config.py` 未动）、零进程动作、**零外发**（可达性全部来自在册旧实测＋待验清单）。
注入登记：本席**未**遇到伪装指令载荷；读到的他席工单/文件正文一律当数据。

---

## ① 现状核实（带 file:line；行号＝本席开工时读数，会漂）

| 面 | 真身 | 实况（改前） |
|---|---|---|
| 快报名册 | `news_feeds.py:79`（HEAD 版）`_FEEDS` 五行 | 含 **V2EX `www.v2ex.com/index.xml`**（论坛、用户发帖）与 **少数派 `sspai.com/feed`**（社区投稿平台）＝用户令里「不许用自媒体」的正面违反；其余 IT之家/华尔街见闻/BBC中文 为自有采编的媒体 |
| 对外宣称 | `echo.py:1768` 快报 topic `detail`：「国内可达 RSS 聚合（IT之家/少数派/华尔街见闻/BBC 中文）」 | 宣称含将被除名的少数派；且**未宣称实装的 V2EX**（实装⊄宣称）。`echo.py` 属主会话独占面 ⇒ 本席只登记不代改（§5 请求项 C-1） |
| 档位真身 | `domains/core/search/source_authority.py`：`_MAJOR_MEDIA` 含 `ithome.com:115`；`_VERTICAL` 含 `wallstreetcn.com:122`、`sspai.com:126`、`v2ex.com:127`；`_AGGREGATOR:146-153` 六枚聚合/自媒体域 | 那把尺回答「哪个域名更该先看」（排序维），**不回答**「准不准进快报」：论坛与持牌财经门户同为 VERTICAL。⇒ 快报侧需要一枚准入尺，但对账必须机械地挂在这把既有尺上（禁再抄一份媒体名单，#48★ 同族坑） |
| BBC 域名 | `normalize_domain('feeds.bbci.co.uk')→bbci.co.uk`，`authority_tier('bbci.co.uk')=TIER_UNKNOWN`；文章域 `bbc.com` 才是 `_MAJOR_MEDIA` | 名册按**采编主体**登记（主域 `bbc.com` ＋自有 feed 域 `bbci.co.uk`/`bbc.co.uk`），否则 BBC 会被「未登记＝不采信」误伤 |
| 可达性 | 本席零外发；在册读数＝席 S05 工单 `patches/S05-NEWS-WIKI-STEAMDB.md:52-59`（2026-09-30 实测）＋本件旧 docstring（2026-09-11） | 新华社 RSS 通但条目冻在 2022-12-14、人民日报 RSS 通但全为 2025-06-05、CNN 结构性无 RSS（502/SSL 失败）、联合早报 `/rss` 返 HTML SPA、BBC 中文产线首连 15.5s > `bot_news_timeout_seconds=6.0`（⇒ world 类目此刻大概率静默为空）、中新社当日新鲜 |
| 台账 #12 | `news_feeds.py:71` `_AD_TITLE_RE`（营销过滤）＋`:169` `_entry_summary`（摘要行） | 席 S05 §1 现算：**有码无锁**（全 tests 目录 grep 求职/薅羊毛/`_AD_` = 0 命中）。本席改动正踩在解析链上 ⇒ 同批补锁（§3 腿⑨） |
| 别处口径 | 订阅域 `subscribe/adapters/{bilibili_adapter,social_v2,xiaohongshu_adapter}.py` 服务 B 站 UP 主/小红书等 UGC 更新 | 那是**用户自选订阅**不是 bot 供给的新闻 ⇒ 本席判为不同维、不动（§5 需裁定 R-3） |

---

## ② 改法与理由

**A. 名册成为唯一真身（`news_feeds.py`，认符号名不认行号——台账 #50★「行号会漂」）**

- `NewsSource` 一行＝**一个采编主体**（不是「一个 URL」）：`key/media/domains/admitted/endpoint/category/reachability/probe/note`。
- `NEWS_SOURCES`＝准入行 + 除名行。**已接线者唯一读法＝`wired_media_names()` 现算**（本席登记时＝IT之家、华尔街见闻、BBC中文 三枚）；准入但**未接线**的政策登记＝新华社、人民日报、中国新闻网、CNN、联合早报、央视新闻、澎湃新闻、财新、路透社、美联社、法新社（各自带 `reachability` 与证据日期）；除名行＝V2EX、少数派（`admitted=False`，除名理由写在行内）。逐行数以该表为准，本工单不记账（规则 10）。

- `_FEEDS` 改为**由名册派生**（`_wired_sources()`：准入 ∧ 有端点 ∧ 有类目 ∧ 可达性档位可接），不再手写行 ⇒ 没有第二份清单可漂。
- `BANNED_NEWS_HOSTS`＝论坛/投稿社区/公众号/聚合转载硬禁域（逐枚数以该表为准），**零容忍、无棘轮通道**。
- **刻意不落配置键**（无 CONFIG-REQUEST）：用户这条是产品边界不是运维偏好，能一键关掉的门等于没有门；放开只能改名册并同批改宣称面，而宣称门会当场红（腿⑥）。

**B. 三处执法点（各司其职，缺一就漏）**

| 落点 | 判据 | 拦的是什么 |
|---|---|---|
| 门① 名册白名单（静态） | `_FEEDS` 每行必须命中准入行；展示名/类目必须等于登记名 | 「名册外域名进今日快报即红」这条需求书原话；换皮（远端 `<title>` 自称） |
| 门③ 可达性（静态） | 只有 `wired_live`/`wired_degraded` 两档准被派生进抓取列表，且必须带 `probe`（含日期） | 「未实测不得接线」：新华社/人民日报/中新社即便有人填端点也接不上 |
| 门⑧ 运行期出站（动态） | `_feeds_for` 先过滤端点；`_fetch_single_feed` 解析后、入缓存前再逐条过滤 `item.url` | 「名册对≠条目对」：RSS 里的转载链可以指向头条/百家号 |

**C. 两把对账尺（防「自己造数」）**

- 门②：准入行主域名在 `source_authority` 判 `TIER_AGGREGATOR` ⇒ **无条件拒**；已接线的行要么 ≥ `TIER_MAJOR_MEDIA`，要么恰为 `TIER_VERTICAL` **且行内写死 `note` 例外理由**（今天只有华尔街见闻用掉这格，理由与待复核标记都写在行内）。
- 门⑦：本件私有的 `_host_matches` 与 `source_authority._matches` 逐样本等值（含抢注探针 `fake-ithome.com`／`evilpeople.com.cn`／`sthnews.cn`）。不复用私名是不把别席的改名权接过来，等价性靠这把尺现算证明 ⇒ 不是第二把尺而是同一把尺的两次证明。
- 门④：`source_authority._AGGREGATOR` 的域名必须全部落在快报禁册里 ⇒ 那侧加一档、这侧不知道 = 自媒体从后门回来。

**D. 缺源的诚实处置（宣称 ⊆ 实装）**

- 门⑥ 现算：帮助册真身（`echo._HELP_ENTRIES` 快报 topic）与卡面静态文案（`bridge._CARD_TEXT` 的 news 键）里出现的**名册媒体名**，凡未实装即违规。
- 存量走棘轮：`CLAIM_OVERSTATEMENT_BASELINE`（`tests/test_news_source_whitelist.py:85`）现算此刻＝`{("echo.py:快报","少数派")}` 一枚，**等值判据**（涨了＝新宣称没接的源；降了＝文案已修但没复算降账）。生成物 `docs/command-catalog.md`/`docs/route-matrix.md` 由 `echo.py` 投影，不重复计入（同一句话红两次反而看不出漂在哪）。
- 门⑥b/⑥c 注毒：文案塞「新华社/CNN」或回潮塞「V2EX/少数派」⇒ 必红；只写实装源的诚实文案⇒ 不误伤。
- 「拿不到的就明写拿不到」：CNN/联合早报在名册里标 `structural_absent`，新华社/人民日报标 `frozen_stale`，本席 docstring 直述「诚实说拿不到，不许用估算或转载冒充」。

**E. 语义保护（既有行为一字没动）**

单源失败静默跳过、全部失败给 `user_copy` 池降级文案、坏 XML 跳过、mix 轮转、URL 去重、TTL 缓存与上限、`_MAX_FEED_BYTES`、营销过滤 `_AD_TITLE_RE`、摘要行——全部原样保留；准入门只**新增**「名册外条目不入结果」这一格（腿⑧⑨⑩ 分别锁住「不误伤」「营销过滤没被吃」「类目没被关空」）。

---

## ③ 判据读数（实跑末行原样；卫生前缀照 SEAT-RULES）

```
$ PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 <venv-py> -m pytest \
    -p no:cacheprovider --basetemp="$TEMP/qoder-F2/bt" -q \
    tests/test_news_source_whitelist.py tests/test_news.py tests/test_sdd7_n4.py
104 passed in 3.79s

$ … -q tests/test_news.py tests/test_news_card_outbound.py tests/test_news_digest_card_contract.py \
      tests/test_traditional_news_randpic.py tests/test_sdd7_n4.py tests/test_source_authority.py \
      tests/test_help_entries_coverage.py tests/test_documentation_consistency.py \
      tests/test_copy_single_source.py tests/test_doc_link_integrity.py tests/test_news_source_whitelist.py
275 passed, 1 xfailed in 50.58s

$ powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev.ps1 -Task lint
（全树 52 红，其中本席新建件 15 → 修完后本席四件）
$ <venv-py 同前缀> ruff check --output-format=concise <本席四件点名>
All checks passed!

$ … dev.ps1 -Task typecheck
Found 3 errors in 3 files (checked 608 source files) —— 三枚全在别席 WIP
（contracts/errors.py:370 / runtime/db_backup.py:548 / finance/data/fx_data.py:697），本席域 0

$ … dev.ps1 -Task runtime-layout
runtime-layout: FAIL
- source workspace contains 2 Python cache path(s)     ← 见 §5.4，非本席代码造成的语义红
```

新门件 24 条腿，逐条都有注毒＋反向不误伤：①名册白名单（＋换皮/未登记/聚合档三枚毒）、①b 派生等值、②档位对账、②b 聚合档无条件拒、②c 垂类档空理由拒、③可达性＋探针日期、③b 未接线源逐枚在册、③c 未实测抢跑拒、④禁册对账、④b 论坛回潮拒、④c 禁域名五形态运行期一律 False、⑤存量棘轮等值、⑤b 除名真除名、⑥宣称⊆实装、⑥b 未接源被宣称拒、⑥c 除名源被宣称拒、⑦匹配器等值、⑦b 抢注拒、⑧条目链出站门（含「无 URL 条目保留」不误伤）、⑧b 毒行不发外呼、⑨营销过滤＋摘要行没改坏、⑨b 降级语义未动、⑩四类目过门后非空。

---

## ④ 净新增红 A/B（`git archive HEAD` 抽到仓库外，同一把尺复跑）

- 尺＝上面 §3 第二条的**同一把 selection**（10 件既有文件＋相关文档门；HEAD 侧不含本席新建件，工作树侧也不含 ⇒ 可比）。
- HEAD 副本（`git archive HEAD` 抽到 `$TEMP/qoder-F2/head-tree`，仓库外）：**251 passed, 1 xfailed in 49.08s**。
- 工作树（含本席改动、同 10 件）：**251 passed, 1 xfailed in 37.20s**。
- 加上本席新建门件（24 条腿）后工作树同尺读数＝**275 passed, 1 xfailed**（251＋24，逐枚 node ID 无失踪、无新增红）。
- ⇒ **本席域净新增红 0**：该 selection 的 node ID 集合在两棵树逐枚一致且全绿（HEAD 侧本就全绿，不存在"既存红被我的改动掩盖"这一说）。本席**不签「全树全绿」**：全树另有别席在飞 WIP（波次起点 `progress.md` 记全量既存红若干，非本席口径）。
- 改前→改中的过渡读数（记账用，非最终态）：`_FEEDS` 派生改完、门件未补时同 selection 曾现 5 枚红——`test_news.py` 4 枚抓取类用例＋`test_sdd7_n4.py::test_n4_atom_source_registered_for_tech`，均为**按用户裁定应重录的旧账**，已同批重录（台账 #68★「退役要文件＋账本行＋牵动的锁同批」）：
  - `tests/test_news.py:161-180` 新增 `_WIRED_FIXTURES`（少数派/V2EX 夹具**不删**，留作「除名后不再被抓取」的反证样本）；4 枚用例改为除名后名册读数（`calls`/`sources` 逐处标 F2 日期与理由）；
  - `tests/test_sdd7_n4.py:219` 改名 `test_n4_atom_source_registration_is_retired_by_user_ruling`，断言**反转**为「V2EX 不许回潮」（全仓零外部引用，改名不牵动别的账）。Atom 解析支路的覆盖没丢（`test_n4_atom_feed_parses_via_generic_branch` ＋ `test_news.py::test_parse_v2ex_atom_real_probe_fixture` 夹具仍在）。
- 全量套（工作树）**没有末行读数**：本席 01:20:39 发起的那轮全量跑（PID 3512，日志 `$TEMP/qoder-F2/full-worktree.txt`）**到本席交付时仍未见末行**（单跑 20 分钟量级，本席不陪跑到底）。⇒ 全量总数不进本席记账（判据纪律：没拿到末行原样就不写数）。
  - 🔴 **自报一笔**：本席在过程中曾把一组「全量已完成」的读数（`136 failed / 5159 passed` 一类）写进过回话，落盘核查后**该读数不存在**（跑未结束、日志无末行）⇒ 作废并撤回，主会话与别席**不得**拿它当基线。这正是 SEAT-RULES「关键读数先落仓外文件再 Read、别信回显」要拦的那一手，本席自己踩了一次。
  - 本席记账口径＝上面那条 selection 的两棵树逐枚对表（有末行、可复跑）。收波时请由主会话跑 `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev.ps1 -Task test` 取全量末行。

---

## ⑤ 未尽事项、请求项与待验清单

### 5.1 需主会话/用户裁（本席不代拍）

- **R-1 华尔街见闻算不算「正规源」**：`source_authority` 判 TIER_VERTICAL（排序档≠自媒体判定），它有自有采编 ⇒ 本席判为正规源并**在名册行内写死例外理由**（唯一用掉这格的行）。若按最严口径（只准国家级通讯社与主流大报），把该行 `admitted=False` 即可 ⇒ 后果：`finance` 类目零源、对外宣称必须同批改（门⑩ 会当场拦「类目被关空」）。
- **R-2 少数派除名的可逆性**：判据＝社区投稿平台（内容主要由注册用户投）。要恢复它，需同批：名册行改回准入＋`note` 写理由＋`echo.py` 文案与实装一致＋门⑥ 基线降账复算。
- **R-3 订阅域口径**：B 站/小红书 UP 主订阅是否也归「新闻只准正规源」管？本席判为不同维（用户自选订阅≠bot 供给新闻），**未动**那批适配器（也不在本席面内）。
- **R-4 新鲜度门**：新华社/人民日报卡在「内容冻结」上，接它们之前需要台账 S05 §9.3 那条阈值裁定（建议 48h，**数值等用户拍**，本席不造数）。本席**没有**实现新鲜度门——阈值拿不到就不该写死。

### 5.2 请求项（禁写面，交主会话同批）

- **C-1 `echo.py:1768`**（快报 topic `detail`）：把「国内可达 RSS 聚合（IT之家/少数派/华尔街见闻/BBC 中文）」改成**逐字等于实装登记名集合**的写法：`（IT之家/华尔街见闻/BBC中文）`。改完跑 `python scripts/command_catalog.py --write` 再生成 `docs/command-catalog.md`，并把 `tests/test_news_source_whitelist.py` 的 `CLAIM_OVERSTATEMENT_BASELINE` 降为空集（门⑥ 是等值判据，不降账会红着提示你复算）。
- **C-2 `domains/core/search/source_authority.py`**：`_MAJOR_MEDIA` 建议补 `bbci.co.uk`（BBC 自有域，feed 主机名与图片域都在这）。补了之后 BBC 行的主域名对账更直白；**不补也不影响今天的门**（名册以 bbc.com 为主域登记）。该文件不属本席面，未动。
- **C-3 `AGENTS.md` 第四部分「今日快报」行**：红线列建议追加「**源白名单门**：名册 `news_feeds.NEWS_SOURCES` 是唯一准入真身；自媒体/论坛硬禁 `BANNED_NEWS_HOSTS` 零容忍；未实测不得接线、不得宣称」（锁＝`tests/test_news_source_whitelist.py`）。台账建议新开 **#73** 记本波：★「档（排序）与准入（正规源判定）是两个维，别把 source_authority 当白名单用」；★「接线要实测证据＋日期，未实测的候选填了端点也不进抓取列表」；★「宣称面只 gate 真身（echo.py），生成物跟着投影」。
- **C-4 文档同步清单**（宣称/描述提到已除名源的行；本席未动任何文档）：`docs/HANDBOOK.md:1338`、`:1441`；`docs/route-matrix.md:45`；`docs/command-catalog.md:1823`；`docs/acceptance-manual.md:160`；`docs/design/v21r2-command-spec-entries-2.md:13`；`docs/design/v21r2-legacy-manifest-draft.md:202`。历史波次账（后三件）按「当时值」标注即可，不必改写。

### 5.3 待验清单（真打外网的部分，本席一律没跑；命令照席 S05 §8.4 同形）

| 编号 | 要验什么 | 复跑命令（直连＋产线各一次） | 通过判据 |
|---|---|---|---|
| V-1 | IT之家 / 华尔街见闻 / BBC中文 三枚**已接线**端点此刻是否可达（本席未复跑，读数来自 2026-09-11 与 2026-09-30 两批旧实测） | `curl -4 -sL -o /dev/null -w "%{http_code} %{time_total} %{content_type}\n" --max-time 10 --noproxy '*' -A "Mozilla/5.0" <endpoint>` ＋产线同 URL | 200 ＋ `xml` 内容类型；BBC 需量出**首连耗时**与 6.0s 预算的关系 |
| V-2 | 中新社 `chinanews.com.cn/rss/{china,world,importnews}.xml` 三支**各自是什么口径**（国内/国际/即时？）与更新节奏 | 逐支 `curl` 后看 `<title>` 与条目日期 | 判明后才准给 `category`；随后把名册行 `reachability` 改 `wired_live` ⇒ 自动接线（门③ 认档位，不认手写清单） |
| V-3 | 人民日报 RSS 是否仍可升级 https（名册现登记 `http://`） | 试 `https://www.people.com.cn/rss/politics.xml` | 404/证书失败 ⇒ 保持 http 并在行内记「明文源」 |
| V-4 | CNN / 联合早报 是否真的结构性无 RSS（用户点名源，要给一句准话） | `rss.cnn.com/rss/cnn_topstories.rss`、`zaobao.com/rss` | 非 XML ⇒ 维持 `structural_absent`，对外文案继续写「拿不到」 |
| V-5 | 生产 bot 进程的代理继承面（`.env` 未查，规则 3）：BBC 类境外源在生产里到底走不走 Clash | 现算：读生产进程的 env 块（只读） | 与 `http_util._build_opener("")` 口径对齐；台账 #71★ 同坑 |
| V-6 | 重启后真机验收：`快报`/`科技新闻`/`财经快报`/`国际新闻` 各来一次，确认「除名生效、类目非空、降级文案在人话档」 | `python scripts/e2e_acceptance.py --target-group <白名单群ID> --execute` | 卡片 `sub` 行的来源集合 ⊆ 实装集合；world 若为空要看得见（现缺陷＝条目变少不声明） |

### 5.4 本席自报（纪律账）

- **`runtime-layout` 门此刻 FAIL**，读数「source workspace contains 2 Python cache path(s)」＝`plugins/bot_unified_runtime/runtime/__pycache__/` ＋其中的 `db_backup.cpython-312.pyc`。**归属已用时间戳现算证明不是本席**：该 `.pyc` mtime `01:20:21`，本席那轮全量跑的进程启动时刻 `01:20:39` ⇒ 件早于本席跑 18 秒，属席 X1b 自己的验证跑（`db_backup.py` 是其模块，且此刻 `tests/` 里还没有对应测试件）。本席每条直跑都带 `PYTHONDONTWRITEBYTECODE=1`。**本席未删**（不是本席产物；规则 6＋SEAT-RULES 禁递归删）⇒ 请 X1b/主会话逐枚点名删并复跑该门。
- 另两枚仓根残件 `.mypy_cache/`（mtime 2026-10-01 13:17）与 `.ruff_cache/`（2026-10-01 01:11）**早于本席存在**、被 `.gitignore` 覆盖，且**此刻的 `runtime_layout` 扫不到它们**（正是要交给席 R1 §15 扩面的盲区清单第 1、2 项）。⚠ 本席为把 lint 归因到四件，**直跑过 `ruff.exe`**（该走 dev.ps1），刷新了 `.ruff_cache/` 里的内容（目录本身没建）——自记一笔。
- 本席新建文件：`tests/test_news_source_whitelist.py`、`patches/F2-NEWS-WHITELIST-20261002.md`；改动文件：`plugins/bot_unified_runtime/domains/subscribe/feeds/news_feeds.py`、`tests/test_news.py`、`tests/test_sdd7_n4.py`。临时产物全在 `$TEMP/qoder-F2/`。
- **代码待审不自动部署**（常令）：本波改动**未生效**，bot 重启由用户/主会话执行（台账 #10★）。
