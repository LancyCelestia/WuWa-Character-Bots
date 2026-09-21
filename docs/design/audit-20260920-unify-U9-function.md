# 席位 U9-FUNCTION：统一函数/工具层取证审计（2026-09-20）

> **性质**：只读审计席位。零代码/配置改动、零 git 写、零子代理、零真实网络调用、零真实发送、零重启。
> **对象**：函数层统一性——「同一职责只允许一个实现，公共件收进单一层并由中央供给」。量化重复，不泛泛而谈。
> **方法**：自写 AST 指纹扫描器（函数名+参数集+三层归一化体哈希：h_exact 逐字面 / h_norm 常量抹平 / h_shape 标识符抹平）全树实跑 14,456 函数 → 克隆分组 51 组（跨文件、nloc≥6、至少一处在 plugins/）+ 同名多文件族 351 组 + 定向 grep/直读取证 + scoped 测试实跑。脚本与原始输出存 `C:\tmp\u9-fn-audit\`（fingerprints.jsonl / clones.txt / names.txt / top.txt / dead.txt），源码树零残留。
> **快照口径**：行号 = 2026-09-20 本席取证时刻。每条发现附**锚点字符串**，行号漂移时以锚点重定位。禁改面（domains/render/**、output/card_render/**、theme_tokens.py、tests/render_hashes.json、capabilities/echo.py、domains/media/capabilities/tts.py）**全程只读**，涉及时仅登记不判修法。
> **上轮审计关系**：`audit-20260919-unify-wave.md`（渲染+WebUI）与 U1（入站摄取）/U6（配置）各与本席零重叠；本席多处引用其「垫片/在飞」口径但不重复其结论。
> **环境实证基线**：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_datafix_runtime_paths.py tests/test_rendering_contract.py --basetemp="$TEMP/u9-scoped" -p no:cacheprovider -q` → **142 passed in 2.69s**（本席零改动，证树基线未被本席扰动）。

---

## §0 取证计划与进度（滚动更新）

| 项 | 范围 | 状态 |
|---|---|---|
| 1 | 网络取数与重试（retry 份数/客户端混用/超时/UA/SSRF 咽喉覆盖率） | ✅ §1 |
| 2 | 脱敏/消毒族谱（份数+黑名单差异+最弱一份在用者） | ✅ §2 |
| 3 | 时间与时区（now/iso/日界/时间词解析/timesync 消费面） | ✅ §3 |
| 4 | 路径与 IO（runtime_paths 覆盖/原子写/JSON/SQLite 连接与建表） | ✅ §4 |
| 5 | 限额/裁剪/prune | ✅ §5 |
| 6 | 幂等键与去重 | ✅ §6 |
| 7 | CapabilityResult 与话术池 | ✅ §7 |
| 8 | 跨域复制的领域逻辑 | ✅ §8 |
| 9 | 体积债（ponytail 口径） | ✅ §9 |
| 10 | 死函数 | ✅ §10 |
| 11 | 重复实现族谱表 + 收口路线 | ✅ §11/§12 |

**严重度分布（本席全量，逐条见对应小节）**：P0 ×0 ｜ P1 ×4（F-U9-01/04/05/06）｜ P2 ×17（F-U9-02/03/07/08/09 + §8 组九宗 + §10 整模块死三件套 + §1 悬空双胞胎归 §8 计）｜ P3 ×14（§10 函数级死 13 + kb_wiki 盘外绝对路径缺省）。最危险三条：F-U9-01（聊天工具链网页抓取与 meme 媒体下载绕过 SSRF 咽喉且跟随重定向）、F-U9-04（脱敏双引擎，账单 error_summary 与审计 last_error 走弱引擎且 fail-open 保原文）、F-U9-06（75 处裸 connect/28 套建表各自为政，WAL 25 份 busy_timeout 仅 10 份=锁死旧伤复发温床）。

---

## §1 网络取数与重试族

### 事实底座（全为脚本/grep 实跑）

- **HTTP 客户端混用**：`urllib` import 65 处、`httpx` import 19 处（`httpx.AsyncClient(/httpx.Client(` 直构 **15 处**/12 文件：channel_health、providers、search_api×3、web_search×2、tts(禁改面仅登记)、telegram_media、transcribe、sauce_search、meme×2、meme_library_listener、nonebot、disconnect_notice）；`requests/curl_cffi/aiohttp` 在生产插件内 **0 处**（台账 #27 pip-audit 时代口径仍含 curl-cffi 系解析器依赖，代码面已不见直引）。同步/异步两形态无统一门面。
- **退避重试实现份数**：数据层「for attempt + sleep」环 **35 处**（grep `for attempt in`，去 tests）。其中**逐字克隆三份**已成族：`stock_data._network_retry`(90) ≡ `commodities_data._retry_transient`(223) ≡ `market_data._retry_transient`(449)——commodities 的 docstring 自认「语义与 stock_data._network_retry 一致」、market 的 docstring 自认「逐字对齐」（复制粘贴有自觉）。此外 `bond_data`(237)、`fx_data`(417)、weather `_NMC_RETRY_ATTEMPTS`(98)、`http_util`(189，链接解析正统)、search_api(199)、bilibili×2、epic×2、facebook、generic、steam×2、weibo×4、mail_adapter、mail_bridge、onebot `_ONEBOT_SEND_RETRY_DELAYS`、subscription_watcher 各写一套。命名/退避参数/异常白名单三份克隆当前一致，**但无机器锁，下一次只改其中一份即漂移**（东财 kline `end` 参数变更即先例，AGENTS 台账 #11）。
- **超时设置点**：字面量 `timeout=..` 全树 **~190 处**（top: timeout=10×37、5.0×22、15×14、8×13…），带默认超时参数函数定义 113 个；`urlopen(` 10 处中仅 8 处显式带 timeout。**无任何「数据源超时缺省」单一来源**（LLM 面有 BOT_CHAT_* 预算，数据面全靠各模块硬编码）。
- **User-Agent 拼装份数**：UA 相关 44 处，**独立 UA 字面源 ≥12 个**：`http_util.DEFAULT_USER_AGENT`（正统）、`web_search._USER_AGENT`、`eat._IMAGE_UA`、`platform_credentials._DESKTOP_UA`、`community._UA`、`media_share._UA`、`generic._UA`、`weibo._WEIBO_MOBILE_UA`、`facebook._FB_CRAWLER_UA`、`lofter._LOFTER_ANDROID_UA`、discourse/taptap/douban 内联。**「Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0」短串在 4 文件逐字重复**（community:18、media_share:21、discourse:41、taptap:80/91）。
- **`build_request_headers` 双胞胎**：`parsers/context.py:52`（类型化）与 `parsers/http_util.py:47`（getattr 宽容）**逐体几乎全等**，生产零调用点（唯一 import 者=tests/test_parser_v2_boundary.py）——两份拼装实现都悬空，真实头部构造散在各 http_get/http_post 形参。

### F-U9-01｜聊天网页抓取与 meme 媒体下载绕过 SSRF 咽喉（安全+统一双料）

- **严重度**：P1（可达内网敏感面+回显进模型上下文）。
- **坐标与逐点清单（「哪些外部 URL 取数点没走咽喉」）**：
  1. `domains/core/search/web_search.py:109 _fetch` / `:141 _fetch_async` / `:237 fetch_page_text`——**锚点** `follow_redirects=True`、`def _fetch(`。
  2. `domains/chat_reply/capabilities/chat.py:3216-3236` 网页正文工具调用——**锚点** `fetcher = getattr(active_web_provider, "fetch_page_text"`（top.url 来自搜索结果，第三方页面可 302 到任意内网地址）。
  3. `domains/meme/capabilities/meme.py:103-111 _default_image_fetch_fn`（`client.stream("GET", url)`，url=消息段/结果 URL）——**锚点** `def _default_image_fetch_fn`。
  4. `domains/meme/sources/meme_library_listener.py:80-92 _download_once`（群消息 image/表情段 url 直下）——**锚点** `async def _download_once`。
  5. `domains/meme/sources/meme_search.py:250 _resolve_ddg_redirect` 与 `web_search.py:647 _resolve_ddg_redirect`（克隆对，逐跳解重定向无落点复查）——**锚点** `def _resolve_ddg_redirect`。
- **对照（咽喉面已在册）**：`check_download_url` 定义于 `domains/files/sources/downloader.py:363`（内网/保留段全解析判定，锚点 `raise RejectedUrlError("该地址属于内网/保留网段，已拒绝")`），消费方 10 处：downloader、eat×2（入口+重定向落点复查）、ssrf_guard、media_archive×2（含 `_GuardedRedirectHandler` 逐跳）、notes×2、file_gateway、capability_protocols:728；`ssrf_guard`（guard_user_url/check_fetch_landing）消费方：search_service（锚点 `guard_user_url = _default_guard` 单源复用，做得对）、content_parser、http_util、platforms_generic、capability_protocols。**判定**：链接解析/下载/归档主线有咽喉，搜索服务层已接，但**「网页正文抓取」与「meme 图片抓取」两条侧链完全绕开**——同一威胁模型两套口径。
- **根因**：SSRF 校验是「调用点自律」而非「取数层强制」；web_search/meme 早于/平行于护栏体系长成，无单一 fetch 门面。
- **证据**：上述坐标 grep 实录（本席 §1 事实底座）；`grep -rn "ssrf_guard\|check_download_url" plugins/bot_unified_runtime/domains/core/search/web_search.py plugins/bot_unified_runtime/domains/meme/` 零命中。
- **改法**：把 `http_util` 的「入口 guard_user_url + 逐跳 check_fetch_landing」（锚点 `# 每一跳 30x 落点先过 ssrf_guard 判定`）抽成 `runtime/fetchkit.get(url,...)`，web_search/meme 两处改走该门面；SnowLuma 本机段媒体 URL 需求以**显式受控豁免**表达（单一 `allow_hosts` 参数来自配置，而非无校验直连）。
- **验证**：新增负样本回归（对 `http://127.0.0.1:9/`、`http://169.254.169.254/` 的 fetch_page_text/meme 抓取必须拒）：`… python.exe -m pytest tests/test_ssrf_chokepoint.py -p no:cacheprovider --basetemp="$TEMP/u9-ssrf" -q`（锁测试为收口动作，本席只登记）；棘轮 grep 门：web_search/meme 目录内 `follow_redirects=True` 命中必伴随 ssrf_guard import。

### F-U9-02｜重定向逐跳复查再实现 3 套（双料缺陷的统一侧）

- **严重度**：P2。guard 语义分叉=「哪条链先漏」不可预测。
- **坐标**：`media_archive._GuardedRedirectHandler`（urllib RedirectHandler 覆写，锚点 `class _GuardedRedirectHandler`）、`eat.py:335/345`（手工两次 `check_download_url` 入口+final_url，锚点 `重定向落点复查（安全审计 I-1`）、`notes.py:252/256`（同款第三抄，锚点 `check_download_url(final_url)`）。**差异一句话**：三种「复查重定向落点」的实现与日志留痕方式各不同；downloader 自身仍走 yt-dlp 独立重定向路径（其 docstring 自认残余，锚点 `彻底收敛需在 yt-dlp 侧挂连接级钩子`）。
- **改法**：并入 F-U9-01 的 fetchkit（一处逐跳复查，三家调用）；**验证**：三锚点 grep 归零 + 现eat/notes/media_archive 相关测试族绿（`-k "eat or notes or media_archive"`）。

### F-U9-03｜重试/超时/UA 三无（数据取数层无中央供给）

- **严重度**：P2（维护税+漂移温床；东财 `end` 参数事故同族再现条件已具备）。
- **坐标**：§1 底座全部。**根因**：finance 五文件、music 三源、weather、subscribe 适配器各自长出自己的 `urlopen+UA+timeout+retry`；正统 `http_util`（含退避 `empty_backoff_sleep` 的可注入 sleep）只在 link_parse 域内复用（`empty_backoff_sleep` 锚点 `def empty_backoff_sleep` 甚至被 finance 跨域反向 import——耦合方向已乱：`commodities/stock/market → market_data.empty_backoff_sleep`）。
- **改法**：fetchkit 一次收编（retry 引擎×1、timeout 缺省×1、UA 表×1、per-source override 字典）；**先收 finance `_network_retry` 三克隆**（有自觉 docstring 的复制=最低风险首刀）。
- **验证**：`PYTHONDONTWRITEBYTECODE=1 …python.exe C:/tmp/u9-fn-audit/u9_fp.py out2.jsonl && grep -c "5eeba947f4d8" out2.jsonl` 应归零（三克隆指纹消失）+ 金融六测试族绿。

---

## §2 脱敏/消毒族

**份数**（全部 def 实录）：文本脱敏引擎/包装 **15 份**，其中**独立正则引擎 6 个**、其余为 fail-closed 包装或局部变体：

| # | 引擎/包装 | 坐标（锚点） | 覆盖形态 | 失败姿态 |
|---|---|---|---|---|
| E1 | **正统** `redact_local_secrets` | `domains/render/plain_text.py:340`（锚点 `_SECRET_VALUE_PLACEHOLDER = "<已隐藏>"`）| BOT_=、sk-、URL userinfo、JWT、Bearer、裸键值、盘符路径（7 形态，F-01 审计批补齐）| 快路径哨兵幂等 |
| E2 | `redact_private_debug` | `domains/ops/audit/logger.py:38`（锚点 `_BEARER_RE = re.compile`）| key=value、Authorization:、Bearer、sk-（4 形态）| 无 try（纯函数）|
| E3 | `_fallback_redact` ×3 逐字克隆 | incident/service.py:74、repair/service.py:110、acceptance/runner.py:575（锚点 `def _fallback_redact`）| BOT_=、Bearer、sk-、盘符（4 形态子集）| 兜底即本职 |
| E4 | `redact_history_text` | `character/history.py:39`（锚点 `_HISTORY_COOKIE_KEY_RE`）| 键值、Bearer、sk-、cookie（4 形态另一子集）| — |
| E5 | reviewer 内联 | `domains/render/reviewer.py:65 _redact_output_match`（锚点 `redacted = re.sub(` 三连）| apikey/token/cookie/authkey、authorization、bearer sk、sk-（4，禁改面**仅登记**）| — |
| E6 | prompt_audit 键名法 | `chat_reply/runtime/prompt_audit.py:152 _redact_value`（锚点 `if _SECRET_KEY_RE.search(key)`）| 键名命中整值 [redacted]+2 值正则 | — |
| 包装 | cp events / actions / event_store / error_report / alerts | 均 E1(+E2) 组合，**fail-closed**（锚点 `# Fail closed: the older DTO helper deliberately falls back to raw text.`——events.py:102 注释自证知旧助手 fail-open）| 全 | 抛错→丢弃整值（好）|
| 漏网 | `control_plane/audit.redact_query/redact_error_for_dto`(44)、`llm_engine/ledger.redact_error_summary`(173)、`smoke._redact_smoke_debug`(1065)、`config_store.redact_public_data`(80，键名法) | 锚点 `except Exception:  # 脱敏模块不可用时保留原文截断。` | 仅 E2 或 bespoke | **fail-open 保原文** |

### F-U9-04｜最弱一份在用：账单 error_summary 与审计 last_error 走 4 形态引擎且 fail-open

- **严重度**：P1（密钥泄露风险面：LLM 异常摘要常自带 `Authorization: Bearer …`/盘符路径，这两处是 WebUI/账本直显面）。
- **坐标**：`domains/chat_reply/llm_engine/ledger.py:173 redact_error_summary`（锚点 `复用 audit 的 redact_private_debug`）；`control_plane/audit.py:44 redact_error_for_dto`（锚点 `脱敏模块不可用时保留原文截断`）。
- **根因**：脱敏引擎双轨（E1 render 域正统 / E2 audit 域旧集），包装点各选其一；「异常时保原文」的旧姿态在 E2 系仍存活。
- **差异一句话**：E2 漏 BOT_XXX=、盘符路径、JWT、URL userinfo、裸键值 5 形态；E1 全覆。E3×3 是 E1 的有损快照，随 E1 演进必然漂移（F-01 扩形态那轮 E3/E4 就未同步）。
- **改法**：E1+键名 deny 合成唯一 `runtime/redact.py::redact_text`；E2 变薄委托；全链 fail-closed（异常→占位符，抄 events.py 既有纪律）；E3×3 删除改调单一引擎（懒加载+失败即返回占位串，非原文）。
- **验证**：`…python.exe -m pytest tests/test_redaction_single_source.py -q`（新增：给 7 形态样串断言各包装点输出一致且 fail-closed）+ 指纹棘轮 `u9_analyze.py clones` 中 `9464e2f23a35`（_fallback_redact×3）组归零。

---

## §3 时间与时区

**事实底座**：
- now/时间戳助手 **29 个定义**（§3 dump 实录）：`_utc_now`×11（其中 hn=e0151b99bb56 **11 份逐字同体** `return datetime.now(timezone.utc)`）、`_now_iso`×5（control_plane 三种形态互不一致：全 hex vs 截断）、`_utc_now_iso`×6、`_now`×4、`_now_utc`×3、`_iso_now`、`_safe_timestamp`；另有**零调用公开件 `utc_now_iso`（schedule/llm_draft.py:477）**（§10）。
- naive `datetime.now()`（无 tz）生产 **41 处 / 23 文件**（含 `model_schedule.py`（时段路由判定！）、`__init__.py`×4 日键、campus/daily/news_feeds/today_history/media_archive/error_report/usage_monitor/time_window/reminders 自身兜底路径、epicfree/steamfree）。`utcnow()` 0 处（已清）。
- **timesync 消费面**：`grep -rln timesync plugins` = config.py、domains/schedule/store/reminders.py、timesync 包自身。**notes 域零 import**（`grep -rn "timesync\|synced" domains/notes/` 空手）——AGENTS 台账 #28「NTP 授时驱动提醒/**笔记**时序」的笔记侧无实据（文档口径>代码现实；提醒侧 7414e87 真接）。重启后绕过者照吃系统钟漂移（13 点报 23 点 bug 族 #29⑤ 的再现条件保留在 41 个绕过点上）。
- **日界口径分裂**（date_key/day 格式化 10+ 处）：本地日 `now().astimezone().date().isoformat()`（`__init__.py:2855/3010/3177/3328` cookie 到期/日报/摘要/daily_assist 的**按日幂等键成分**）vs **UTC 日**（`trend.py:230`、`subscription_watcher.py:164`）vs 无 tz `current.date()`（campus_store prune/forward）。同概念（「今天」）两阈值 → 23:00-24:00 窗口内 digest 日键与 watcher 日键不同日，dedup 跨日界漂移。**克隆对**：`daily_fortune_day_key`(draw_store:257) ≡ `fortune_day_key`(fortune.py:148)（指纹组 aae93fc8b96d 逐字同体）。
- **时间词解析**：提醒域 `_DAY_OFFSETS/_ABS_TIME_RE/_PERIOD_ONLY_RE`（reminders.py:52-58，锚点 `_DAY_OFFSETS = {"今天": 0`）为唯一自然语解析器，**divination 自写 `_DATE_RE/_TIME_RE + _parse_bazi_when`**(118/123/202)、today_history `_TIME_RE`(65)——生辰/时刻解析独立三套（业务上可辩解为语义不同，但「X点Y分/半」词法应共享原语）；`hh:mm` 数字钟解析 **3 份**：model_router:222 `_parse_hhmm`、quiet_hours:184 `_parse_hhmm`、model_schedule:58 `_parse_clock`（指纹组 426dbaa03eb8 近克隆）；**ISO 解析 6+ 份**：`_parse_utc`×4（两组克隆：cp webui stats/memory_graph 逐字同体 cef74c5cff85；affinity/mood 逐字同体 4cd14f4f5b73）+ billing `_parse_iso/_parse_legacy_time` + usage `_parse_instant` + reminders `_parse_stored_moment` + timesync `_parse_http_date`。

### F-U9-05｜时钟无中央供给：29 助手 + 41 naive now + timesync 单消费者

- **严重度**：P1（与台账 #6/#3 同族：安静时间/cron/日键异时区偏移；生产事故先例 #29⑤ 已两次）。
- **改法**：`runtime/clock.py`：`now_aware()`（timesync 补偿钟，缺省回退本地 tz-aware）+ `today_key()`（唯一定义「本地日 isoformat」）+ `parse_iso()/parse_hhmm()`（收编 §3 全部解析器）；datetime.now 直读设棘轮门（白名单=clock 自身），先收 4 个 `__init__` 日键点与 trend/watcher 两个 UTC 日界点（行为变化=日界统一为本地，需登记裁定）。
- **验证**：`grep -rn "datetime.now()" plugins --include="*.py" | grep -v tests | wc -l` 单调下降；新增 `tests/test_clock_single_source.py`；指纹组 aae93fc8b96d、cef74c5cff85、4cd14f4f5b73 归零。

---

## §4 路径与 IO / SQLite

- **runtime_paths 覆盖**：好。裸相对 `open("data/…` / `Path("data/` 生产写盘点 **0**（grep 实跑），29 文件消费 runtime_paths；唯一外溢：`domains/location/knowledge/kb_wiki.py:58` 缺省外机绝对路径 `D:\Coding\Crawl Wiki`（锚点 `or r"D:\Coding\Crawl Wiki"`）——P3 登记（读面默认值，越机即瞎，宜配置键+缺省空）。
- **SQLite 连接/建表**（本席最大宗）：`sqlite3.connect(` **75 处**；连接助手 def `_connect`×28、`_shared_connection`×7（两组克隆 d4b9a8a2b3e0×4 / be827f91e4fe×3）、`_read_only_connect`×2（webui_knowledge/memory_graph 逐字同体）、`_connection`×4、`_get_connection`×4、`_discard_connection`×2 同体、`_transaction`×2 近同体（queue/receipts）。建表：`def _ensure_schema` **28 文件**、`_ensure_schema_once`×6（其中 5 份逐字同体组 hn=57d519578b4e），`_ensure_column`×2 同体。**PRAGMA 口径**：WAL 设置 25 文件各自 `PRAGMA journal_mode=WAL`（含只读 webui 面 query_only+trusted_schema 三处内联）；**busy_timeout 仅 10 文件**——`connect(timeout=…)` 22 处，其余 53 处连接**无锁等待语义**。锁死旧伤（mark_done Critical 死锁先例）在这套「每库自配 PRAGMA」结构下是常态风险。`runtime/database_broker.py`（带 busy_timeout 的正统封装）在盘但生产消费=门控关（WIRE-SVC 缺省 False），**等于没有中央供给**。
- **原子写/JSON**：`os.replace` 13 处/9 套独立小实现（prompt_audit._write_atomic 带 mkstemp+fsync 最完备，锚点 `fd, temporary = tempfile.mkstemp`；trend.py 带 uuid 后缀 tmp，锚点 `.with_name(f"{path.name}.{uuid4().hex[:8]}.tmp")`；其余 7 处裸 replace）；无共享 `write_json_atomic()`（JSON 读写 helper 定义 grep 仅 diagnostics._dump_list 一个近亲）。

### F-U9-06｜SQLite 访问无单一层：75 connect / 28 schema / PRAGMA 三口径

- **严重度**：P1（锁死与半迁移风险；docs/db-owners.md 32 库全部各自裸 connect）。
- **改法**：`runtime/dbkit.connect(path, *, mode)` 统一 WAL+busy_timeout+timeout+URI 只读形态，schema 迁移走各库声明式 DDL 列表 + 共享 `_ensure_schema`/`_ensure_column` 执行器（收编 4 个克隆组）；database_broker 要么按 WIRE-DIRECT 计划收编为 dbkit 的权威实现、要么退役，不留双轨。
- **验证**：`grep -rn "sqlite3.connect(" plugins --include="*.py" | grep -v dbkit | wc -l` → 目标 <10（仅测试夹具）；`grep -rn "journal_mode" plugins | wc -l` 从 25 → 1。

---

## §5 限额/裁剪/prune

- **目录/行 prune**：`_prune(self, connection)` 13 行 SQL 逐字克隆 **×3**（ops/audit/logger:209、ops/smoke/diagnostics:385、transport/sender/receipts:303，锚点 `DELETE FROM … WHERE id NOT IN (SELECT id FROM … ORDER BY … LIMIT ?` 同构）+ queue 自有 23 行版（同语义第三形态）；`_prune_card_dirs(root, keep=120)` **精确逐字克隆 ×2**（divination.py:385 ≡ today_history.py:114，h_exact 同值 `f5a8a0bd9ef0`——连 keep=120 缺省都抄，#26⑨ 补记先例）；域 prune 另有 campus_store.list_day 版、media_registry、reaction_store、event_idempotency、workspaces、recovery、rate_limit×2 —— **同一职责 11 个实现**。
- **截断原语**：`_clip` 家族 **10 def / 6 变体**，其中 `_clip_text` 三文件逐字同体（chat:716/history:681/memory:270）+ memory_extract/reflection 同体对 + transcribe/vision_describe 同体对（组 23d49aa4113 的 33L cx10 `_flatten_asr_entries ≡ _flatten_vision_entries` 亦是整段复制）。
- **环形缓冲**：`deque(maxlen=…)` 7 处 + 手写「while len>512: pop(next(iter()))」游标表裁剪 **2 处同体**（chat.py `_FAILURE_MESSAGE_CURSOR`、error_report.py `_HUMAN_CURSOR`，锚点 `while len(_HUMAN_CURSOR) > 512`）——同一小算法三份。
- **「同一概念两套阈值」实例**：①塔罗日上限 `_TAROT_DAILY_LIMIT=20`(capabilities/divination.py:356) vs `DEFAULT_TAROT_DAILY_LIMIT=20`(store/draw_store.py:47)——同域同名异源，值当前相等、漂移无门；②「当日」日界（§3：本地 vs UTC 双源，直接改变一切按日限额/幂等的实际边界）；③审计环形 1000 缺省在 logger/receipts 双写（值同、来源异）。

### F-U9-07｜prune/clip/limit 原语不收口

- **严重度**：P2。改法：`runtime/bounded.py`（clip/evict_dict/prune_rows_by_limit/prune_dirs(keep)），四处克隆组先并（指纹 6607023871ab、041df72ce542、b41dd96f604b、23d49aa4113 归零为棘轮门）。验证：`u9_analyze.py clones` 复跑对应组消失。

---

## §6 幂等键与去重

**算法份数判定**（核心问题：是否同一算法 → **否，三族混用**）：
- 族 A **分隔符键（无哈希）**：`build_event_dedupe_key` = `f"{adapter}|{bot_id}|{message_id}"`（event_idempotency.py:25，锚点 `return f"{adapter}|{bot_id}|{message_id}"`，**无成分校验**——message_id 含 `|` 即键分裂）；`derive_dedupe_key` = `f"{platform}:{entry_kind}:{event_id}"`（outbound_contracts.py:757，锚点 `must not contain ':' or newlines`，**有校验**）。两套元分隔风格并存、校验纪律一有一无。
- 族 B **内联 f-string 命名空间键**（发往 SendQueue 的 dedupe_key，SQLite UNIQUE 收口）：`campus_fwd:{message_id}`、`reminder:{id}`、`cookie-expiry:{admin}:{today}`、`digest_push:{group}:{today}`、`daily_assist:{tag}:{user}:{today}`、`group_failure_notice:{request_id}`、`admin_alert:…:{request_id}`、error_report `{base}:ack`/`{base}:card`、smoke 字面量 ×3——**10+ 处各写各的前缀**，无中央命名空间登记表（前缀冲突=静默吞并，靠人肉不撞）。
- 族 C **内容哈希**：媒体归档 sha256 去重、prompt_audit `sha256(...)[:16]` 文件名、llm_admin `[:12]`、`prov-[:10]`、billing 全长 hex——切片长度 4 种、无共享 `digest()` helper（sha256 直调全树 13+ 处）。
- **request/trace id 生成器 4 份三个格式**：`control_plane/api/protocol.py:17` `req_{uuid4().hex}`(32 位) vs `core/contracts/errors.py:123` `req_{uuid4().hex[:12]}`(12 位，**同前缀不同长度**) vs `envelope.py:36`/`runtime.py:17` `f"{prefix}_{hex[:12]}"` 同体对 + `trace.py:42 dt_`、`search_service:1412 sreq_`、`teaching:214 teach_`、`actions:261 run_` 等 8+ 处内联 uuid4 —— id 形态无契约。
- **重放风险判定**：入队面幂等最终收敛在 queue 的 `dedupe_key UNIQUE`+UNKNOWN 确认（单点，好）；风险在键**生成侧**——族 A/B 混用意味着同一逻辑事件若经两条不同产键路径（如未来某能力改用 derive_dedupe_key 而 campus 仍用内联串），**同事件双键=双发**；`|` vs `:` 无统一转义即埋雷。

### F-U9-08｜dedupe/id 产键三族混用无登记

- **严重度**：P2。改法：`dedupe_key(namespace, *parts)`（= derive_dedupe_key 泛化：校验+转义+前缀注册）与 `new_id(prefix)`（长度单一化 hex[:12]）两枚收编全部产键点。验证：`grep -rn 'dedupe_key=f"' plugins | wc -l` → 0（全走函数）+ `grep -rn 'uuid4().hex' plugins | wc -l` 收敛至 id 模块+随机盐点。

---

## §7 CapabilityResult 与话术池

- **构造面**：`CapabilityResult(` 直构 **204 处 / 25+ 文件**（Top: `__init__` 30、today_history 16、divination 14、music 11、meme 9…），局部壳 helper 各自为政（daily_assist `_result`、group_info `_result`、memory `_memory_result`、echo `build_*_result` 4 枚、pipeline `_pipeline_busy_result`）——**无中央 builder**，status/tags/prefix_parts 语义靠抄邻居。
- **同名双模型**：`domains/core/contracts/runtime.py:226 CapabilityResult(StrictBaseModel)`（能力结果，request_id/kind/title/body…）与 `runtime/capability_protocols.py:151 CapabilityResult(_StrictModel)`（受控调用结果，status/via/elapsed_ms/attempts）**同名不同物**，chat.py 等经 contracts 垫片取前者。命名冲突+契约分叉双料（后者是控制面调用协议件，应名 `InvocationResult`——它 docstring 自己都这么写：锚点 `受控调用结果`）。
- **话术池单源性判定：不合格。**池常量散布 **6 文件**（user_copy 3 池 / chat.py 2 池+2 游标引擎 / error_report 2 池 / echo 1 池 / daily_assist 4 池），选择机制 **5 套**：
  1. 会话游标+锁+512 裁剪（chat.py `persona_failure_message`、`injection_guard_message`；error_report `_persona_text` 同构第三抄）——锚点 `# 修 D9：有会话时纯按游标顺序轮换`；
  2. 全局键游标 `pick_variant`（daily/store/daily_assist.py:333，锚点 `chat.py 五池话术同构的确定性轮换`）；
  3. 全局计数器（echo.py `_ignore_guide_cursor`，锚点 `_ignore_guide_cursor += 1`；禁改面**仅登记**）;
  4. 内容哈希确定性（poke.py:123 `int(digest[:8],16) % len(_POKE_MODES)`）；
  5. **裸 `random.choice`**——user_copy 三池（ADMIN_GATE/GROUP_FAILURE/DATASOURCE）**全部 30+ 消费点**都是 `random.choice(user_copy.XXX_TEMPLATES).format(...)`（锚点 `random.choice(user_copy.ADMIN_GATE_TEMPLATES`）。
  **后果**：台账 #34「五池…游标轮换」仅对 chat 自有两池+冷却池成立；管理门/群失败 ack/数据源失败三类**连发可重复**（「同会话连发不重复」纪律未贯穿）。绕过池子自写失败文案的能力点亦存在（finance「暂无…」类兜底 body 直拼，样本见 stocks/market 局部 return CapabilityResult(body=…)，判定为池语义边界待定，登记）。

### F-U9-09｜池选择机制 5 套、游标纪律半途

- **严重度**：P2（用户可见话术不统一）。改法：`runtime/phrasepool.py`：池常量集中（user_copy 升格为唯一池模块，chat/error_report/daily/echo 池迁入）+ 单一 `pick(pool_key, session_id=None)`（有会话走会话游标、无会话随机、LRU 512 单一实现）；全部 `random.choice(…TEMPLATES)` 机械替换。验证：`grep -rn "random.choice(user_copy" plugins | wc -l` → 0；`test_user_copy_unification_gate.py` 扩「选择机制唯一」AST 断言（该门已是先例基建）。

---

## §8 跨域复制的领域逻辑（前后对照摘录）

| 组 | 指纹 | 坐标 | 差异一句话 |
|---|---|---|---|
| epic/steam cookie 加载器 | 127fd7289d4(31L cx15 同体) | platforms_epic.py:95 ≡ platforms_steam.py:109 | 换域名常量的整段复制（RET3 批同对） |
| asr/vision 条目拍平 | 23d49aa4111(33L cx10 同体) | transcribe.py:84 ≡ vision_describe.py:470 | media/ingest 双文件 4 组克隆（另含 is_enabled/clip/_utc 小对） |
| incident/repair 服务对 | f879bd373a9 + 325038008d1 + 9464e2f23a3 | ops/incident/service.py:86/109/74 ≡ ops/repair/service.py:119/142/110 | 红actor 懒加载+脱敏+兜底五连逐字对（两模块整族 fork） |
| ddg 重定向解析 | 1fbcb5afdf81 | core/search/web_search.py:647 ≡ meme/sources/meme_search.py:250 | 搜索域与梗域各养一份同一 DDG 解链器 |
| onebot 结果判读三连 | d6f16547f5e 等 | transport/sender/file_gateway.py:85/108/117 ≡ onebot.py:91/111/281(nonebot) | retcode 提取/成功判定/provider msg id 三连在 gateway 与 sender 双写（公开名+下划线名各一份） |
| 音乐/东财取数壳 | c04fc3e0dc7b 等 | commodities:253 ≡ market:532 `_get`（精确同体）+ `_fetch_payload` 5 份（shape 同、常量异） | 同一「GET→json→解包」壳在 finance+music 至少 9 份 |
| 抽卦存储双模块 | e4718561f27 + DrawError×2 | divination/data/draw_store.py ≡ divination/store/draw_store.py | **同域两个 draw_store.py**：`DrawError` 定义两次、`_compute_deck_revision` 同体两份（V2.1 S12 波与旧存储波未合流的地质断层） |
| 群/私聊判定 | — | memory.py:81 `_is_group_session` ≡ reactions/engine.py:292 同名 + rate_limit.py:168 异签名 + **12 处内联三元** `"group" if group_id else "private"` | 「会话类型」应读 IncomingMessage.session_type 单一事实源，实为三助手+十二抄 |
| 空分区/分区拼装 | — | chat.py `_section_budget`+13 分区（正统，锚点 `# 动态分区：只有确实有内容时才输出`）vs channel_health 巡检报告、校园【校园转发】前缀、daily 简报等 10+ 处各自手拼【标签】块 | 「空则不渲」语义只存在于 chat 一处，其余块无该保证（空【表情回应】等是否出现取决于各能力自觉） |

（严重度：组级均 P2；divination 双 store 与 onebot 三连为改行为必踩双点，列 P2 优先并。）

---

## §9 体积债（ponytail 口径）

**Top 20 文件**（行数｜顶层 def 数｜函数体行和｜Σ 分支复杂度）——脚本 top.txt 实录（前 12）：

```
8675 __init__.py        331 defs(fn) 13437 fnL  Σcx 2425   ← 根枢纽
3921 domains/chat_reply/capabilities/echo.py     35 defs   964 fnL   253
3859 domains/ops/smoke/smoke.py                  61 defs  3572 fnL   492
3595 domains/chat_reply/capabilities/chat.py     76 defs  3814 fnL   900
2341 …/llm_engine/model_router.py                61 defs  1997 fnL   493
2131 …/parsers/platforms_bilibili.py             33 defs  1942 fnL   808
2110 …/character/vector_knowledge.py             79 defs  1938 fnL   490
2083 …/parsers/platforms_generic.py              54 defs  1931 fnL   692
2001 …/render/card_render/bridge.py（禁改面）
1935 …/ops/admin/runtime_admin.py                31 defs  1871 fnL   496
1929 runtime/capability_protocols.py             68 defs  1588 fnL   276
1858 …/transport/sender/queue.py                 66 defs  1644 fnL   191
```

**巨型函数 Top**（nloc/cx）：`__init__.py:3544 _register_nonebot_handlers` **5126L cx704**（NoneBot 注册总枢纽，100 处 handle/on_message 全在此）、`smoke.py:2938 main` **918L cx51**、`chat.py:2713 build_chat_capability` 779L（含 729L 内层 `capability`）、`__init__.py:6487 _handle_status` 725L cx118、`runtime_admin.py:425 _handle_model_command` 588L、`contracts/media.py:401 build_parsed_content` 388L cx170（单函数复杂度全树第一）。

**根 `__init__.py` 与各域 `__init__.py` 职责重叠判定**：20 域的 `__init__.py` 几乎全空壳（transport 6 行、weather/subscribe/… 1 行；唯 core 264 行为装配杂项）——**不存在「域 index 与根 index 双写」**；真实债务反向：域内 `build_*_capability` 工厂制已存在（content/chat/subscribe/divination/reminder 等），但**根文件仍以 331 def + 100 matcher 手写装配**，即「域化收口完成一半」。合并/下沉建议（每条附行数增减预估，净变化≈0 者以可测性计价）：

| 建议 | 动作 | ±行预估 |
|---|---|---|
| `_register_nonebot_handlers` 按域拆 8 段（campus/meme/media/subscribe/ops/chat/transport/misc），根留调用序 | 下沉 | 根 −4200 / 新 8 文件 +4300 ≈ **+100**，可测性质变（cx704 灭） |
| `_handle_status/_handle_chat/_handle_model_command` 迁 echo/runtime_admin 既有域文件 | 下沉 | ±0（搬移） |
| smoke.main(918L) 按 21 个冒烟面拆注册表驱动 | 重构 | −300（样板化省重复） |
| build_parsed_content(cx170) 按段型 5 个纯函数 | 拆分 | +40 |
| 根内 4 处日键点并入 clockkit | 收编 | −40 |
| finance 五文件取数壳并 fetchkit | 收编 | **−400~550** |
| prune/clip/dedupe/id/池 五批原语收编（§5-§7） | 收编 | **−350~450** |
| SQLite 连表并 dbkit（§4） | 收编 | −250（28 schema 壳薄后） |
| divination data/store draw_store 合一对 | 合并 | −150 |
| incident/repair 五连 fork 并 ops/redact 基座 | 合并 | −120 |
| epic/steam、asr/vision 同体对参数化 | 合并 | −130 |

---

## §10 死函数（AST 零引用候选，人工复核后清单）

方法：u9_dead.py（装饰器件/__all__ 件/dunder 豁免；跨文件同名串扰为已知假阴性源）。**候选 24 → 复核后 21 真死 + 3 框架假阳性**（mediawiki `handle_starttag/handle_endtag/handle_data` 为 HTMLParser 回调，排除）。逐条 `grep -rnw` 全树 hits=1（=def 行自身）实证。

**整模块死**（零 import 方，且 git grep HEAD 亦仅自体命中——非工作树漂移）：
1. `domains/ops/integrations/gscore_bridge.py` —— `build_gscore_bridge/build_message_receive/build_message_send/roles_to_user_pm` 四公开件死；**矛盾点**：base_router:603 仍标 `core.gscore status="active"`（锚点 `InterfaceEntry("core.gscore"`），注册表宣称与现实分叉（P2）。
2. `domains/link_parse/support/url_cleaner.py` —— `clean_tracking_url/clean_urls_in_text` 死，且 search_service.py:682 另写了一套 utm 剥离（死正统+活私货，P2）。
3. `domains/subscribe/store/subscription_watcher.py` —— `build_subscription_watcher` 死；类本体仅自体文件被用（订阅轮询现役路径不经此件，P2 登记，待订阅域 owner 判退役）。

**函数级死**（P3 逐条）：`__init__.py:482 _is_plain_chat_text`、`control_plane/dispatcher.py:96 generate_and_send`、`features.py:228 descendants`、`knowledge_service.py:163 source_names`、`shared_export.py:153 build_shared_conversation_export_provider`（会话导出 provider 无生产者——群摘要旧伤 #33① 同族位）、`credentials.py:224 resolve_credential`（credentials 门面断头）、`divination_service.py:240 interpret_draw`（服务方法死而 control_plane/api/divination.py:189 端点**自写同名逻辑**=双实现一死一活）、`store/draw_store.py:139 _epoch_of`、`ops/admin/debug.py:1232 _format_semicolon_list`、`error_report.py:310 seconds_remaining`、`repair/service.py:739 list_tickets`、`schedule/llm_draft.py:477 utc_now_iso`（公开版死，私有版 12 份活着）、`schedule/timetable.py:74 _valid_hhmm`。

**改法**：退役波照单清（先补 `docs/` 声明面），活双实现（interpret_draw、utm 剥离）并一；验证：`python C:/tmp/u9-fn-audit/u9_dead.py` 复跑行数下降即棘轮。

---

## §11 重复实现族谱表

> 职责｜实现份数｜各份坐标（主代表）｜差异一句话｜建议保留哪份。全部由 §1-§10 实证汇总，无估算值。

| 职责 | 份数 | 各份坐标 | 差异一句话 | 建议保留 |
|---|---|---|---|---|
| 退避重试环（数据层） | 3 克隆 + ~15 内联 | finance/{stock:90,commodities:223,market:449}；bond/fx/weather:98/search_api:199/weibo×4/bilibili×2/steam×2/epic×2/facebook/generic/mail×2/onebot:688/http_util:189 | 三份克隆 docstring 自认「逐字对齐」，无机器锁 | **http_util 重试核** 升格 fetchkit |
| HTTP GET-JSON 壳 | ≥9 | http_util.http_get_json；finance `_fetch_payload`×4+`_get`×2；music_charts×4；social_v2._get_json；web_search._fetch | 同为「GET→json→解包」，超时/UA/重试各配 | **http_util.http_get_json** |
| User-Agent 源 | ≥12 | http_util.DEFAULT_USER_AGENT + web_search/eat/platform_credentials/community/media_share/generic/weibo/facebook/lofter/discourse/taptap/douban | 「Chrome/126.0」短串 4 文件逐字重 | **http_util 缺省 + per-source override 表** |
| SSRF 咽喉 | 1 引擎 3 抄 | downloader.check_download_url(363)；ssrf_guard(正统复用面)；eat/notes/media_archive 各自「入口+落点」双查 | 校验引擎单源✅，但「逐跳复查」三套且 web_search/meme 全旁路 | **check_download_url + fetchkit 强制内置** |
| 直构 httpx 客户端 | 15 | §1 清单 | 每调用点自 new client+timeout，仅 providers/ledger 有 `_shared_http_client` | **provider 级共享客户端**（先例 `_shared_http_client`） |
| 文本脱敏 | 6 引擎+9 包装 | E1 render/plain_text:340；E2 ops/audit/logger:38；E3 fallback×3；E4 history:39；E5 reviewer:65(禁改面登记)；E6 prompt_audit:152 + bespoke(smoke/ledger/audit) | E2 少 5 形态；ledger/audit 用 E2 且 fail-open | **E1 唯一引擎 + fail-closed 薄包装×1** |
| now/时间戳 | 29 def | _utc_now×11 同体、_now_iso×5、_utc_now_iso×6、_now×4、_now_utc×3、_iso_now… | 语义同（取当前时刻），形态异（aware/naive/iso/秒浮点） | **runtime/clock.now()/now_iso()** |
| ISO 时刻解析 | 6+ | _parse_utc×4(两组逐字对)、billing._parse_iso/_parse_legacy_time、usage._parse_instant、reminders._parse_stored_moment、timesync._parse_http_date | 宽容度各异，个别静默吞错 | **clock.parse_iso(±宽容旗标)** |
| 「今天」日键 | 10+（本地/UTC 分裂） | __init__:2855/3010/3177/3328（本地）；trend:230、subscription_watcher:164（UTC）；campus current.date()（naive）；fortune_day_key≡daily_fortune_day_key 克隆对 | 日界不一致=按日幂等/限额在 23-24 点双口径 | **clock.today_key()（本地日，显式注记）** |
| hh:mm 解析 | 3 | model_router._parse_hhmm:222、quiet_hours._parse_hhmm:184、model_schedule._parse_clock:58 | 报错姿态各异 | **clock.parse_hhmm** |
| 自然语时间词 | 1+2 旁支 | reminders._DAY_OFFSETS/_ABS_TIME_RE/_PERIOD_ONLY_RE(52-58)；divination._DATE_RE/_TIME_RE(118/123)；today_history._TIME_RE(65) | 提醒词表是唯一全集，旁支各自缩水 | **clock 词法核 + 域语义层** |
| SQLite connect | ~40 壳/75 直连 | _connect×28、_shared_connection×7(两克隆组)、_read_only_connect×2、_connection×4、_get_connection×4、_transaction×2 | WAL 25 有、busy_timeout 仅 10 | **runtime/dbkit.connect(mode)**（database_broker 收编或退役） |
| 建表/迁移 | 28+6+2 | `_ensure_schema`×28、`_ensure_schema_once`×6(5 同体)、`_ensure_column`×2 同体 | 执行器形态同、DDL 各表 | **dbkit.ensure_schema(ddl_list)+ensure_column** |
| 行/目录 prune | 11 | `_prune(connection)`×3 逐字 + queue 版；`_prune_card_dirs(keep=120)`×2 逐字；campus/media_registry/reaction_store/event_idempotency/workspaces/recovery/rate_limit×2 | keep/retention 各配（§5 三处「同概念双阈值」） | **bounded.prune_rows/prune_dirs** |
| 截断 clip | 10 def/6 变体 | _clip_text×3 同体、_clip×2 同体对、_clip×2 同体对、moegirl/incident/message_context 各异 | 省略号/中间截断/头部截断三种风格 | **bounded.clip(text,n,ellide="…")** |
| 环形/游标表裁剪 | 9 | deque(maxlen)×7 + 手写 512 弹窗×2（chat:646 附近、error_report:343 附近，逐字同式） | 同一 LRU 小算法三份 | **bounded.EvictingDict** |
| dedupe 键 | 3 族 | build_event_dedupe_key(|,无校验)；derive_dedupe_key(:，有校验)；内联 f-string×10+ | 双风格分隔符+一查一漏 | **dedupe.key(ns,*parts)（校验泛化）** |
| id 生成 | 4 正 + 8 散 | protocol.new_request_id(32hex)；errors.new_request_id(12hex 同前缀!)；envelope/runtime.new_id(12hex 同体对)；trace/search/teaching/actions 内联 | 同前缀不同长度=形态无契约 | **envelope.new_id(prefix) 唯一** |
| 话术池选择 | 5 机制 | chat 会话游标×2、error_report 游标、pick_variant、echo 计数、poke 哈希、random.choice×30+ | 「连发不重复」仅部分池成立 | **phrasepool.pick(池键,session)** |
| CapabilityResult | 2 模型 + 204 直构 | contracts/runtime:226(正统) vs capability_protocols:151(同名异物)；局部壳 helper×8 | 双模型同名+零 builder | **contracts 模型改名隔离 + cr.ok/cr.err builder** |
| 群/私聊判定 | 3+12 | memory._is_group_session≡engine._is_group_session、rate_limit.is_group_session、内联三元×12 | 前缀字符串猜 vs 契约字段读 | **IncomingMessage.session_kind()** |
| 抽卦存储 | 双模块 | divination/data/draw_store ≡ divination/store/draw_store（DrawError×2、_compute_deck_revision 同体） | 两波各自建库未合流 | 合并（store 为体、data 为算法层） |
| DDG 解链 | 2 同体 | web_search:647 ≡ meme_search:250 | 逐字对 | search 域单份导出 |
| onebot 结果判读 | 3×2 | file_gateway.{_extract_onebot_retcode,onebot_result_is_success,extract_provider_message_id} ≡ onebot/nonebot 私有版 | 公开/私有两份同物 | onebot 域单份（公开名） |
| 头部构造 | 2 悬空 | context.build_request_headers ≡ http_util.build_request_headers（都无生产调用者，仅测试 import 后者） | 双胞胎皆死码 | 留 context 版接进 http_util 内部 |
| epic/steam cookie、asr/vision flatten、incident/repair 五连 | 各 2 逐字对 | §8 表 | 复制有自觉无机器锁 | 参数化合并 |

---

## §12 单一函数层收口路线（先收哪 5 族性价比最高）

> 排序准则：安全/正确性影响 × 份数 × 合并风险（低=机械并、中=需回归族、高=涉行为变化需裁定）。全部动作沿「成文→收编→棘轮门（AST 克隆组归零清单入 tests/test_unify_U9_ratchet.py，先例基建=test_user_copy_unification_gate/test_rendering_contract 的机器门写法）」。

1. **fetchkit（网络取数门面）**【风险低→中，收益最大】：http_util 升格 `runtime/fetchkit`（唯一 retry 核/timeout 缺省/UA 表/SSRF 入口+逐跳强制/共享 client）。首刀=finance `_network_retry` 三克隆并一 + web_search/meme 两链路过护栏（**灭 F-U9-01/02/03 三条 P1/P2**，其中 SSRF 缺口=安全双料）。净 −400~550 行。
2. **redaction 单源**【低】：E1 引擎+fail-closed 包装唯一化，ledger/audit fail-open 点改丢弃（**灭 F-U9-04 P1**）；E3×3/E4 并壳。净 −80 行。回归面：tests -k "audit or ledger or events or incident"。
3. **clockkit（时钟/日历）**【中：日界统一属行为变化，随重启验收窗口做】：now/today_key/parse_iso/parse_hhmm 四合一，timesync 提为进程级时钟源（notes/digest/schedule/路由时段全部吃它），本地/UTC 日界分裂收口为本地日（登记裁定点，台账 #3/#6 同根）。**灭 F-U9-05**，顺带消灭 29 个 now 助手与 4 组解析克隆。净 −150 行。
4. **dbkit（SQLite 层）**【中】：connect(WAL+busy_timeout 统一)/ensure_schema/ensure_column/prune_rows/readonly-URI 五件套；database_broker 收编进同一实现或裁决退役（不留「正统在盘、生产零用」双轨）。**灭 F-U9-06**，锁死旧伤面系统性收窄。净 −250 行。
5. **bounded+dedupe+phrasepool（小原语三包）**【低】：clip/evict/prune_dirs、dedupe.key/new_id、池 pick 各一；random.choice×30+ 机械替换；CapabilityResult 双模型改名隔离（protocols 版→InvocationResult）+ 中央 builder 可选后置。灭 F-U9-07/08/09。净 −350~450 行。

**明确后置**：根 `__init__.py` 拆分（§9 路线，属装配波非函数波）；divination 双 store 合并（随 L60 好感/占卜域裁决波）；gscore/url_cleaner/subscription_watcher 死三件套（随垫片退役终波，附「registry active 声明同步核销」）。

---

## §13 附录：方法与可复跑证据

- **脚本**（全 stdlib，零依赖，只读）：`C:\tmp\u9-fn-audit\{u9_fp.py, u9_analyze.py, u9_dump.py, u9_dead.py}`；原始输出 `fingerprints.jsonl`(14,456 函数)、`clones.txt`(51 组)、`names.txt`(351 组)、`top.txt`、`dead.txt`(24 候选)。
- **复跑**：
  ```bash
  cd C:/tmp/u9-fn-audit
  PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 \
    "/c/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe" u9_fp.py fingerprints.jsonl
  … u9_analyze.py clones|names|top ; … u9_dead.py
  ```
- **指纹学口径**：h_exact=去 docstring 的 ast.dump 哈希；h_norm=常量抹平（str/bytes→S、数→N）；h_shape=unparse 重解析后标识符全改名。克隆判据=h_norm 等值 ∧ nloc≥6 ∧ ≥2 文件 ∧ ≥1 在 plugins/（tests 镜像不计）。同名族=h_exact 不管、纯 name+files 计数。**已知盲区**：装饰器动态注册/反射/字符串路由（dead 候选逐条人工 grep -w 复核）；类体跨方法克隆（本波未见显著案例）；docstring 差异不参与判重。
- **本席树卫生自查**：全程 PYTHONDONTWRITEBYTECODE=1 + 输出仅本文件；脚本/产物零入源码树。**既有污染（非本席造成，如实登记不处置）**：取证时刻树内存在 `__pycache__` 多处（plugins/ 各旧目录）、`.mypy_cache/.pytest_cache/.ruff_cache/.tmp-test`（HANDOFF-V21R5 §五 在案遗留）——处置归并发写会话按台账#1 规程（先备份 %TEMP% 再清），本席只读故未动。
- **与在册事实对账**：`redact_local_secrets` 正统位在 `domains/render/plain_text.py`（`output/plain_text.py`=149B Compat shim，`import *` 形态）；`empty_backoff_sleep` 住 market_data 被兄弟文件跨引（§1）；五池纪律出处台账 #34、错误卡冷却池 #41——本席全部按**当前树实码**复核，未采信文档口径。

*U9-FUNCTION 席位取证完毕。全部结论可复跑；「已取证」≠「已修复」——本席零改动。*
