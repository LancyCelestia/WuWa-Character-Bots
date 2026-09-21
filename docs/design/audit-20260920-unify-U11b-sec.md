# 审计日志 — 席位 U11b-SEC「后端安全咽喉」（2026-09-20）

> 席位性质：只读审计。唯一可写文件 = 本文件。
> 范围裁定：仅后端 Python。前端 `webui/`、`domains/render/**`、`output/card_render/**`、`theme_tokens.py`、`card_render/templates/**`、TTS/语音链路 **一律不查、不报、不碰**。
> 硬禁令：不派子代理；无 git 写操作；不改任何代码/配置/文档；无真实网络请求/LLM 调用/发送/重启/杀进程；**绝不落盘 .env 或任何真实密钥值**（只报键名 + 文件:行）。
> 权威链：本文件是 U11b-SEC 席位的一手证据台账；结论汇入主会话，不替代 `docs/design/audit-20260919-unify-wave.md`。

## §0 取证方法

**工具链（全部一手自跑，非转述）**
1. 正则粗扫 `plugins/` + `scripts/` 全部 `.py`：`requests.` / `httpx.` / `curl_cffi` / `aiohttp.` / `urllib.request` / `urlopen` / `Session().get|post` / `subprocess.run|Popen` / `yt_dlp` / `aria2c|wget|curl|ffmpeg` / `socket.create_connection` → 517 行原始命中（噪声含大量 `.get()` 字典取值）。
   脚本：`C:/tmp/u11b-scan/enum_egress.py`（v1，输出 `egress_raw.txt`）。
2. AST 精扫（同一棵目录树，逐文件 `ast.parse`，解析 import 别名 → 只保留「模块.动词」「client 变量.动词」「with Client() as c」三类真出口，并输出 URL 实参的 AST dump）→ **79 命中 / 42 文件**，逐条带 文件:行 + 完整调用片段。
   脚本：`C:/tmp/u11b-scan/enum_egress2.py`（输出 `egress_ast.txt`）、`show_ast.py`（stdout 呈现）。
3. 咽喉定位 + 调用点反查：`grep -rn "def check_download_url|check_download_url\("` → 真身 1 处 + 包装 2 处 + 调用点 9 处（下表 §1.2）。
4. 取数助手覆盖率矩阵：从 `http_util.py` 导出公开函数名集合（`http_get` / `http_get_text` / `http_get_json` / `http_post_json` / `http_post_form` / `resolve_short_link` / `build_request_headers`），全树反查调用点，逐文件判定「同文件是否出现任一咽喉符号」。
   脚本：`C:/tmp/u11b-scan/helpers_matrix.py` → 结论：引用过咽喉的文件 **14 个**，而调用取数助手的文件 **40+ 个**。
5. 解析器 URL 来源分类（FIXED-HOST / VAR+HOST / VARIABLE）：`C:/tmp/u11b-scan/classify_parsers.py` → `link_parse/parsers/` 内 46 处取数调用，其中 VARIABLE 38 / FIXED-HOST 4 / VAR+HOST 4。

**运行约束（实守）**：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0` + 解释器 `../ChatBot_Runtime/venv/Scripts/python.exe`；零网络（`check_download_url` 内的 `socket.getaddrinfo` 未触发——本席只做静态取证，DNS-rebind 结论以代码语义给出并标注）；零 git 写；除本日志外零写入。

**范围排除（用户裁定，本席一律不查不报）**：`webui/`、`domains/render/**`、`output/card_render/**`、`theme_tokens.py`、`card_render/templates/**`、TTS/语音链路。
- 落在排除面、**因此本席不判定**的两处出口，仅登记坐标供对应席位处理：`domains/media/ingest/transcribe.py:225`（ASR `httpx.post(f"{base_url}/audio/transcriptions")`）、`:319`（`client.stream("GET", source)`）、`domains/media/capabilities/tts.py:314-315`（`client.post(endpoint)`）。
- `domains/creation/tts/contracts.py:127`、`domains/creation/_common/contracts.py:298` 属路径消毒同族，TTS 半句不报，`_common/contracts.py` 一句在 §1.4 只作对照。

**本席自查的既有已核项（不重复报）**：`audit-20260919-unify-wave.md` §3.6 已核 Host 白名单/Bearer 禁入 query/SSE/mock 隔离；§3.5 已核知识库集合白名单 + q≤200 + 分页钳制。以上均在本席范围外或已闭合，未复测。

## §1 D1 外部取数点 → SSRF 咽喉覆盖率差集

**一句话结论**：咽喉本体只有 1 份且质量高（协议白名单 + 主机黑名单 + 全部 DNS 结果判私网），但**它是「按需自取」而非「强制经过」**——全树 40+ 个取数文件中只有 14 个引用过咽喉符号；`probe()` 与 `download()` 同属一个类、一个有一个没有；重定向逐跳校验只在 `resolve_short_link` 落地，`http_get*` 系列仍是首查即放。**D1 共 10 条：P0 0 / P1 6 / P2 3 / P3 1。**

### 1.1 网络出口枚举（AST 精扫后的真出口，按域归类）

| 出口 | 坐标 | URL 实参（来源变量） |
|---|---|---|
| 链接解析共享层 | `domains/link_parse/parsers/http_util.py:106 / :309 / :412` | `url`（形参，调用方传入） |
| 解析器 46 处取数 | `platforms_*.py`（VARIABLE 38 处，典型：`platforms_acfun.py:76`、`platforms_epic.py:155`、`platforms_lofter.py:313-321`、`platforms_steam.py:184`、`platforms_telegram.py:65`、`platforms_weibo.py:206`） | `url` = 用户贴入并经入口护栏的 candidate |
| 拼图取图 | `domains/link_parse/parsers/image_stitch.py:129` | `url` ← `images` 列表（第三方响应内字段） |
| 媒体分析 | `domains/files/sources/downloader.py:548`（`yt_dlp.YoutubeDL(opts)`，入口在 `:595 probe` / `:743 download`） | `url` |
| 下载 CLI 委托 | `domains/files/sources/downloader.py:472 aria2c`、`:581 external_downloader` | opts 内 URL |
| 视觉取图 | `domains/media/ingest/vision_describe.py:257-260` | `url` ← `prepare_vision_image_urls(urls)` |
| 视频抽帧 | `domains/media/ingest/video_understanding.py:121`（`subprocess.run([ffmpeg, "-i", source])`） | `source` |
| 表情库收图 | `domains/meme/sources/meme_library_listener.py:91` | `url` ← 消息段 `data["url"]` |
| 表情库 VLM | `domains/meme/sources/meme_library_listener.py:157` | `base_url`（配置） |
| 表情搜索 | `domains/meme/sources/meme_search.py:158-169` | `url` ← 搜索引擎响应 |
| 表情生成 | `domains/meme/capabilities/meme.py:111`（`client.stream("GET", url)`）、`:188`（`client.request(method.upper(), path)`） | `url` / `base_url=key[0]` |
| 点歌取流 | `domains/music/capabilities/music.py:373` | `url` + `cookie_header` |
| 笔记配图 | `domains/notes/capabilities/notes.py:253-254` | `url`（已双查） |
| 媒体归档 | `domains/media/capabilities/media_archive.py:230-232` | `url`（已逐跳查） |
| 菜谱配图 | `domains/food/capabilities/eat.py:339-343 / :377-385` | `image_url`（已双查）/ `search_url`（固定必应域） |
| 凭据探测 | `domains/core/credentials/credential_health.py:122-132` | `url = self.probe_urls.get(ref_id)` + **`Cookie: credential_value`** |
| 平台扫码 | `domains/core/credentials/platform_credentials.py:366` | `_QR_POLL_API + urlencode(...)`（固定域） |
| 搜索 | `domains/core/search/search_api.py:174/315/373`、`web_search.py:91/101` | 固定引擎域 + `follow_redirects=True` |
| LLM/嵌入 | `domains/chat_reply/llm_engine/providers.py:187/543/579`、`channel_health.py:560`、`character/vector_knowledge.py:236` | `base_url`/`endpoint_url`（注册表，配置态） |
| 出站发送 | `domains/transport/sender/nonebot.py:198`（语音，范围外）、`domains/transport/sender/file_gateway.py:281`（已查） | `url` |
| 运维告警 | `domains/ops/monitor/disconnect_notice.py:91/106` | 固定 Server酱/PushPlus 域 |
| 冒烟/脚本 | `domains/ops/smoke/smoke.py:1611/2786`、`scripts/probe_llm_providers.py:157`、`scripts/measure_latency_chains.py:143/177`、`scripts/fetch_mermaid_js.py:51`、`scripts/today_history_kb.py:48-49`、`scripts/pre_restart_check.py:159/174`、`scripts/e2e_acceptance.py:1592` | 配置端点 / 固定域 |
| 子进程下载 | `subprocess` 13 处：`domains/core/supervisor/acl_windows.py:391`、`windows_sandbox.py:639`、`domains/files/capabilities/file_exchange.py:100`、`domains/ops/repair/service.py:485`、`domains/ops/monitor/error_report.py:482/490`、`domains/ops/smoke/smoke.py:2279`、`domains/transport/sender/nonebot.py:148`、`domains/media/ingest/vision_describe.py:410/458` | 命令数组（多为固定可执行文件 + 本地路径） |

### 1.2 咽喉真身与全部调用点（份数实证）

- **真身唯一**：`domains/files/sources/downloader.py:363 def check_download_url(url: str) -> None`。协议白名单 `_ALLOWED_SCHEMES = frozenset({"http", "https"})`（`:335`）、`_BLOCKED_NETWORKS` 24 段（`:308-334`，含 100.64/10 CGNAT、169.254/16、::ffff:0:0/96）、主机黑名单含 `metadata.google.internal` 等（`:300-306`）、**全部** DNS 结果逐个判私（`:409-411`）、IPv4-mapped 归一（`:346-347`）。→ 咽喉本体无缺陷。
- **兼容垫片**：`plugins/bot_unified_runtime/sources/downloader.py`（`from ...domains.files.sources.downloader import *`）——同一函数的两个导入路径，`ssrf_guard.py:129` 走的是垫片旧路径。**不算两份实现**，但属 #42 退役面。
- **包装两份**：① `domains/link_parse/parsers/ssrf_guard.py`（`guard_user_url:159` / `check_fetch_landing:169`，额外做 inet_aton 整型 IP 归一 `:48-114`、F-04「解析失败=拒绝」`:136-148`）；② `runtime/capability_protocols.py:718 _guard_http_url`（**只做 `startswith(("http://","https://"))` + 裸调 `check_download_url`**，无整型 IP 归一、无端口畸形预处理）。语义差异见 §1.4。
- **调用点全集（9 处）**：`file_gateway.py:281`、`ssrf_guard.py:142`、`capability_protocols.py:728`（由 `:758-761`、`:795-798` 两处 handler 逐 URL 前置）、`eat.py:335 / :345`、`downloader.py:749`、`notes.py:252 / :256`、`media_archive.py:200 / :220`。
- **重定向逐跳校验两份**：`media_archive.py:194-214 _GuardedRedirectHandler`（`redirect_request` 内复查 + `_OPENER`）与 `http_util.py:330-361 _GuardedShortLinkRedirectHandler`（`max_redirections = 5`）。两者互不复用，`http_util` 的那份只在 `resolve_short_link` 挂上。

### 1.3 差集：未过咽喉的取数点（逐条判定）

> 判定口径（用户指令）：可控且未校验 = P0；半可控（配置里的 URL，管理员可改）= P1；固定常量域 = P3。
> 本席对「可控」取严：只有**取值能由普通消息内容或消息段字段直接决定**的才算完全可控；由第三方响应决定 = 半可控（上游可替换响应/可 302）。

**D1-F1｜P1｜媒体分析口绕过咽喉（同族两份语义，弱那份有人用）**
- 坐标：`plugins/bot_unified_runtime/domains/files/sources/downloader.py:595`（`def probe(self, url: str) -> MediaAnalysis:` → `:602 info = ydl.extract_info(url, download=False)`）
- 对照：同文件 `:743 def download(...)` 的 `:749 check_download_url(url)`。
- 根因：咽喉挂在 `download()` 上，`probe()` 从未挂；`probe` 直接把 URL 交给 yt-dlp，而 `check_download_url` 的 docstring 自认「yt-dlp 自己会跟随…本函数只在入口校验一次」（`:370-372`），这里连那一次都没有。
- 证据（两个真实调用点，URL 均非入口 candidate 全等）：`domains/link_parse/capabilities/content_parser.py:738-739` `probe_url = audio_url or candidate` → `analysis = downloader.probe(probe_url)`，其中 `audio_url = music_audio_url(item)`（`:727`，取自解析结果，源头是第三方响应体）；`:758-759` `probe_url = canonical_url if "/video/" in canonical_url else candidate`，`canonical_url = identity.canonical_url`（`:722`，由解析器赋值，`platforms_generic.py:114/:859` 处即 `final_url`）。
- 影响：内网/元数据地址可被发进请求（`http://127.0.0.1:8742/`、`http://169.254.169.254/`），并把 yt-dlp 返回的 title/duration/formats 元数据渲染成卡（`:760-790`）= 半回声面。
- 改法 before→after：`def probe(self, url): if not self.available(): ...` → 首行插入与 `download()` 同源的 `check_download_url(url)`（并沿用 `RejectedUrlError` → 既有 `RuntimeError("媒体分析失败…")` 降级，不改契约）；进一步：把咽喉从两个方法上提到 `_youtube_dl` / `_base_opts` 之前统一收口（一处校验，两处继承）。
- 验证：`../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_media_archive.py tests/test_auditfix_parsers.py -k "probe or ssrf" --basetemp="$TEMP/u11b-d1x" -p no:cacheprovider`；并补一条负样本用例断言 `probe("http://127.0.0.1:8742/x")` 抛错且不触网。

**D1-F2｜P1｜拼图链零咽喉（还把 Cookie 带上）**
- 坐标：`domains/link_parse/parsers/image_stitch.py:129`，锚点 `_, payload = http_get(`。
- 根因：`try_stitch_strip(urls)`（`:99`）对传入 URL 无任何校验，也不做落点复查；而 `urls` 来自**上游响应体字段**，与入口 candidate 不同源，入口护栏（`content_parser.py:697 guard_user_url(candidate)`）覆盖不到它。
- 证据：三个调用点 —— `platforms_generic.py:481 try_stitch_strip(images)`（`images` 于 `:428 images.append(raw_url)` 从 `note.get("imageList")` 的 `urlDefault`/`info_list` 字段取出）、`platforms_generic.py:1648 try_stitch_strip(photo_urls, proxy=proxy, referer="https://x.com/")`、`platforms_weibo.py:392 try_stitch_strip(pics, cookie_header=cookie_header, proxy=proxy, ...)`。最后一条把**微博登录 Cookie** 交给 `http_get`（`http_util.py:102-103 headers["Cookie"] = cookie`），而 `http_get` 用的 `_build_opener`（`:63-81`）**没有**逐跳护栏 → 30x 即可把 Cookie 带到任意主机。
- 影响：上游响应被替换（或被 302）时，内网请求 + 平台 Cookie 外送双通道；PIL 解码失败即静默返回，属盲打（无回显）。
- 改法：`try_stitch_strip` 循环体内 `for url in candidates[:...]` 之后立即 `if guard_user_url(url): return list(urls), ""`（与 `content_parser.py:697` 同语义、复用同一函数，不新建判定）；`cookie_header` 只随「与 referer 同源主机」的请求下发。
- 验证：`pytest tests/test_parser_multipage_quote.py tests/test_auditfix_parsers.py --basetemp=... -p no:cacheprovider`（`test_parser_multipage_quote.py:87` 现有 `monkeypatch.setattr(G, "try_stitch_strip", ...)` 打桩，可作为挂载点）；**无 image_stitch 专属测试件**（`tests/` 全树 grep `try_stitch_strip` 仅命中上述一个文件），需新增负样本：stub 图片列表含 `http://127.0.0.1:9/` → 断言 `http_get` 未被调用。

**D1-F3｜P1｜`http_get*`/`http_post_*` 跟随重定向不复查（F-05 只补了短链一支）**
- 坐标：`domains/link_parse/parsers/http_util.py:169 http_get` / `:224 http_get_text` / `:255 http_get_json` / `:287 http_post_json` / `:389 http_post_form`，五者 opener 一律 `_build_opener(proxy)`（如 `:312`、`:415`），**不含** `_GuardedShortLinkRedirectHandler`；对照 `:375-377 resolve_short_link` 显式 `extra_handlers=[_GuardedShortLinkRedirectHandler()]` 并在 `:355-361` 逐跳 `check_fetch_landing`。
- 根因：urllib 默认 opener 自带 `HTTPRedirectHandler`（`max_redirections=10`），入口一次性 `guard_user_url` 之后，公网主机 302 → 内网即穿透；审查 F-05 已认定这是 Critical 形态，但收口只覆盖了短链函数。
- 证据（跟随用户 URL 且文件内零咽喉符号，取自 helpers_matrix 输出）：`platforms_acfun.py:76`、`platforms_allcpp.py:61`、`platforms_epic.py:155 / :494`、`platforms_facebook.py:88`、`platforms_kuaishou.py:140 / :214`、`platforms_lofter.py:313 / :318 / :321`、`platforms_moegirl.py:145`、`platforms_media_share.py:153`、`platforms_steam.py:184`、`platforms_telegram.py:65`、`platforms_weibo.py:206`。`platforms_generic.py` 的 `:72/:131/:277/:816/:1161` 属**事后复查**型（`http_get_text` 之后 `:77/:143/:154/:285/:787/:827 check_fetch_landing(...)`）——请求已发出、只拦回显。
- 影响：P1「护栏可绕过」。`ssrf_guard.py:26-27` 已把这层残余写明为「登记不堵」，但登记面只覆盖 og 兜底链，未覆盖上表 13 个解析器。
- 改法：把 `_GuardedShortLinkRedirectHandler` 提为 `_build_opener` 的**缺省 handler**（`handlers.append(_GuardedShortLinkRedirectHandler())` 无条件），`resolve_short_link` 不再单独传 `extra_handlers`；跳数上限 5 全局生效。
- 验证：`pytest tests/test_parser_ssrf_guard.py tests/test_auditfix_parsers.py --basetemp=... -p no:cacheprovider`；现有 `tests/test_auditfix_parsers.py:269` 的 `monkeypatch.setattr(ssrf_guard_mod, "check_fetch_landing", lambda target, src: None)` 说明该形状已被测试打桩，改后需确认桩仍生效。

**D1-F4｜P1｜视觉取图 helper 无咽喉，三个调用方只有一个查（三份语义不一致）**
- 坐标：`domains/media/ingest/vision_describe.py:252 def _download_image_bytes(url, ...)`，锚点 `:257 request = urllib.request.Request(url, headers={"User-Agent": _DESKTOP_UA})` 与 `:260 with urllib.request.urlopen(request, timeout=_REMOTE_DOWNLOAD_TIMEOUT)`；上游门只有 `:304 if not url.startswith("http")`。
- 证据（同一 helper 的三入口，护栏覆盖不一致）：
  ① `runtime/capability_protocols.py:758-761` / `:795-798` 有 `blocked = _guard_http_url(url)`；
  ② `domains/chat_reply/capabilities/chat.py:156 urls = prepare_vision_image_urls(...)`（`:2899 image_urls = extract_image_urls(getattr(message, "raw_segments", None))` → `:2921 describe_images(image_urls=image_urls ...)`），`chat.py` 全文咽喉符号命中数 **0**；
  ③ `control_plane/api/platform.py:395-399` 直接 `describe_images(...)`。
- 根因：咽喉挂在**调用方**而不是取数口，新增调用方默认不带；且 `urlopen` 自动跟随重定向 → 即使 ① 的入口查过，30x 后落点无人查。
- 影响：`②` 的 URL 取自消息段 `data["url"|"file"|"path"]`（`vision_describe.py:339-341`）。这些值由 SnowLuma/TG 适配器给出，普通群成员不能直接指定 → 记 P1 而非 P0；但**取回字节转 data URL 送 VLM、VLM 文本再进对话**（`:667` → `:678` → `:684`），是全树最接近「内网响应回显」的一条通道：任一上游能塞图片 URL 进 raw_segments，就是把内网 HTTP 响应交给模型复述。
- 改法：咽喉下沉——`_download_image_bytes` 首行 `check_download_url(url)`（拒绝即 `logger.warning` + `return None`，与 `media_archive.py:217-229` 同型）；同文件另建 `_GuardedRedirectHandler`（复用 `media_archive.py:194` 的形状）替代裸 `urlopen`。
- 验证：`pytest tests/test_vision_remote_data_url.py tests/test_vision_and_failover.py tests/test_vision_local_media.py --basetemp=... -p no:cacheprovider`；注意 `test_vision_remote_data_url.py:42` 打桩的是 `_download_image_bytes` 本体，下沉后桩仍能绕开网络，但需补一条「未打桩 + 内网 URL → 不发起」用例。

**D1-F5｜P1｜表情库收图：段 URL 直下 + `follow_redirects=True`**
- 坐标：`domains/meme/sources/meme_library_listener.py:80 async def _download_once(url, ...)`，锚点 `:85 "follow_redirects": True` 与 `:91-93 async with httpx.AsyncClient(**client_kwargs) as client, client.stream("GET", url)`。
- 证据：`url` 于 `:74 url = str(data.get("url") or "").strip()` 取自 `accepted_types = {"image", "mface", "sticker"}`（`:61`）段；入口为 `plugins/bot_unified_runtime/__init__.py:223 / :4021 absorb_event_images`。该文件与 `meme_library_listener.py` 全文零咽喉符号（helpers_matrix 判 `----- NO GUARD IN FILE`）。
- 影响：httpx 逐跳自动跟随且无任何校验，异常一律 `:107 except Exception: return None` 静默——连日志痕迹都没有，属「绕过 + 不可观测」双重欠账。
- 改法：`_download_once` 开头 `check_download_url(url)`（`RejectedUrlError` → debug 级留痕后返回 None），并 `"follow_redirects": False` + 手动逐跳复查（或复用 `media_archive.py` 的 handler 形状）。
- 验证：`pytest tests/test_meme_domain_fixes.py tests/test_meme_image_input.py tests/test_meme_conflict_fix.py --basetemp=... -p no:cacheprovider`；**无 listener 下载链专属用例**（`tests/` grep `absorb_event_images` 命中 `test_meme_domain_fixes.py`），需补「内网段 URL → 不发起」负样本。

**D1-F6｜P1（半可控：配置态 URL + 凭据同请求）｜凭据探测口**
- 坐标：`domains/core/credentials/credential_health.py:111`，锚点 `url = self.probe_urls.get(ref_id) or self.probe_urls.get("*")`；`:122-131` 组请求并 `:129 "Cookie": credential_value`；`:132 urllib.request.urlopen(request, timeout=...)`。
- 证据：`probe_urls` 源自 `config.py:348 bot_credential_probe_urls: dict[str, str] = {}`（`:1386-1388` 有专用装载器），属「管理员可改的配置 URL」→ 按用户口径判 P1；零咽喉调用（本文件不在 §1.2 的 14 个引用文件之内）。
- 影响：配置里填一条内网/外部 URL，即让 bot 带着**真实平台 Cookie** 去访问，且 `urlopen` 自动跟随 30x → Cookie 可被重定向拐带走；响应体不读（`:133` 只取 status），故不属回显面。
- 改法：`:111` 取得 `url` 后 `check_download_url(url)`；`build_opener` 挂逐跳 handler；`Cookie` 头仅在落点主机与配置主机同域时下发。
- 验证：`tests/` 全树 grep `CredentialHealth` **零命中 → 无现存用例件**，本条需先建 `tests/test_credential_health_probe_guard.py`（离线：注入假 opener，断言内网 probe_url 不产生请求、Cookie 头不随重定向外借）；配套可跑面 `pytest tests/test_doc_sync_gates.py -k config_catalog --basetemp="$TEMP/u11b-d6" -p no:cacheprovider`。

**D1-F7｜P2｜表情搜索 / 点歌两处「上游响应 URL」直下**
- 坐标：`domains/meme/sources/meme_search.py:158 urllib.request.Request(url, headers=...)` + `:169 urlopen(request, ...)`；`domains/music/capabilities/music.py:368-373 kwargs = {... "follow_redirects": True ...}` → `httpx.get(url, **kwargs)`（`:359-366` 可带 `cookie_header`）。
- 根因：两处 URL 均来自第三方检索/供应商响应，与入口 candidate 不同源、无落点复查。
- 改法：与 F2 同一处收口即可（在 `http_get`/helper 层强制逐跳 + 取数口 `check_download_url`），不必各自加一份判定。
- 验证：`pytest tests/test_meme_domain_fixes.py "tests/test_music_provider_projection_v2.py" "tests/test_music_capability_analytics_v2.py" --basetemp=... -p no:cacheprovider`（`meme_search` 无专属件，`tests/` grep `meme_search` 仅命中 `test_meme_domain_fixes.py`）。

**D1-F8｜P2｜TLS 校验被关闭的第二实现（同族护栏出现「弱的那一份」）**
- 坐标：`domains/weather/capabilities/weather.py:215` `_NMC_FIND_ALARM_URL, proxy=proxy, timeout=timeout, verify_ssl=False`；`domains/weather/data/nmc_weather.py:119 http_get_json(url, proxy=proxy, timeout=timeout, verify_ssl=False)`。
- 落点：`http_util.py:75-78 if not verify_ssl: handlers.append(urlrequest.HTTPSHandler(context=ssl._create_unverified_context()))`。
- 根因/影响：全树唯一关闭证书校验的地方，且是**私有 API 调用**（天气预警）；证书被替换即可向预警卡注入伪造内容（`weather` 卡的「预警 ≤5 条」直进用户会话）。属固定域，故 P2 不升 P1。
- 改法：删两处 `verify_ssl=False`（若确因企业代理证书，改为可配置的 `ssl.create_default_context(cafile=...)` 显式信任链，而不是关校验）。
- 验证：`pytest tests/test_weather*.py --basetemp=... -p no:cacheprovider` + `grep -rn "verify_ssl=False" plugins/` 期望零命中。

**D1-F9｜P2｜包装语义分裂**：`ssrf_guard._rejection_reason`（F-04：畸形端口/无 host/DNS 失败一律拒；整型 IP 先归一）vs `capability_protocols._guard_http_url`（`:725-726` 先 `startswith("http://","https://")` 过滤，其余形态**直接返回 "" 视为放行**，畸形端口抛 `ValueError` 不进拒绝分支）。同一 URL 形态在两条链上判定不同。改法：`_guard_http_url` 改为薄壳转调 `ssrf_guard.guard_user_url`，不再自己 `startswith`。验证：`pytest tests/test_parser_ssrf_guard.py tests/test_v21_s10_protocols.py -p no:cacheprovider`（`_guard_http_url` 现存用例挂在 `test_v21_s10_protocols.py`，`tests/` grep `capability_protocols` 仅此件与 `conftest.py`/`test_render_pool_hygiene.py` 命中）。

**D1-F10｜P3｜固定常量域（登记不堵）**：`platforms_weibo.py:101/:119`、`platforms_kurobbs.py:65`、`platform_credentials.py:366`、`disconnect_notice.py:91/:106`、`sauce_search.py:53`、`eat.py:377`、`platforms_music.py:370/:532/:685/:857`、`platforms_generic.py:1050/:1119`。全部为写死主机 + 参数拼接，无用户可控主机位。

### 1.4 同族护栏横查（重定向 / 落点消毒）

- **重定向校验份数 = 2**，且都只挂在自己那条链：`media_archive.py:194-214`（下载链，逐跳 + WARNING 脱敏留痕，最佳实践）、`http_util.py:330-361`（短链，逐跳 + `max_redirections=5`）。**未被任何 httpx 使用方复用**：`meme_library_listener.py:85`、`music.py:370`、`nonebot.py:193`、`web_search.py:94/104`、`search_api.py:176/317/375` 全部 `follow_redirects=True` 零复查 → F3/F4/F5/F7 的共同根因是「没有中央层，各链自带 opener」。
- **落点/目录名消毒份数 = 3（后端在范围内）**：`domains/media/archive/media_archive.py:66 sanitize_dirname`（非法字符正则 + `..` 替换 + 保留名前缀 + 长度截断，最强）、`domains/ops/repair/service.py:889 _sanitize_dir_component`（`:758 if not parts or any(p == ".." for p in parts)` 拒绝式）、`domains/creation/_common/contracts.py:298`（拒绝式，非 TTS 面）。全树 **零** `is_relative_to` / 写前缀包含校验（`grep "is_relative_to"` 后端零命中）——即所有落点防护都是「名字消毒」而非「根目录包含」，任何新增写盘点若忘调消毒器即裸奔。建议：统一一份 `sanitize_dirname` 并在写盘口加 `resolved.is_relative_to(root)` 双保险（P2）。
- **咽喉本体残余（代码自证，非本席新发现）**：DNS rebind TOCTOU（`ssrf_guard.py:28-30` 已登记）、`check_download_url` 只在入口判定而 yt-dlp 另有解析路径（`downloader.py:370-372`）——后者正是 F1 应当收进 `probe()` 的理由。

## §2 D2 角色门 / 越权可达面矩阵

**一句话结论**：角色判定真身唯一（`RoleSettings.resolve_roles`，只认 sender_id 集合成员），/bot 全 31 条子命令**逐条**都过角色门，控制面写端点全部挂 `write_dependency=super_admin`，主动出站五通路收件人**全部**取配置或事件身份（零收件人注入）。缺陷集中在**旁路 matcher 自带一套更窄也更要命的角色判定**：`__init__.py:4943` 只查 `bot_admin_user_ids`，既不叠超管（超管被误拒），也**不看 blocked**（被封禁的管理员照旧能灌 Cookie / 改昵称 / 导文件 / 读群文件清单），且这 4 条链完全绕开 `policy/gate` 的黑白名单、安静时间、限流与审计标签。
**D2 共 6 条：P0 0 / P1 1 / P2 4 / P3 1。**

### 2.1 角色判定真身与「实现份数」实证

- **真身唯一**：`domains/chat_reply/policy/roles.py:19` `class RoleSettings` + `:25 resolve_roles()`（纯 sender_id ∈ 五个名单集合；`:34-36` 超管自动叠加 `admin`；`:65 role_audit_tags`）；装配 `:53 build_role_settings(config)`（`bot_admin_user_ids` 与 `bot_telegram_admin_user_ids` 并集）。垫片：`plugins/bot_unified_runtime/policy/roles.py`（PEP 562 活重导出，v21r4-B RWC6-b）。
- **角色注入唯一可信源**：`domains/chat_reply/runtime/pipeline.py:524` `update={"sender_roles": self.role_settings.resolve_roles(message)}`；契约默认 `domains/core/contracts/runtime.py:167 sender_roles: list[str] = Field(default_factory=lambda: ["user"])`、`:196/:215 actor_roles` 同样缺省 `["user"]` → **缺省即最低权限（fail-closed）**，无「未赋值=放行」形态。✅
- **判定谓词实现份数 = 7 类共 13 处**（同族护栏的多份实现，逐份列）：
  1. `domains/chat_reply/capabilities/echo.py:53 _is_admin_actor`（`"admin" in {strip()}`，None→False）
  2. `domains/ops/admin/debug.py:1671 _is_admin`（14 处调用，`:86/:128/:171/:207/:231/:255/:288/:343/:400/:499/:531/:572/:608/:895`）
  3. `domains/ops/admin/runtime_logs.py:18 _is_admin`
  4. `domains/ops/admin/runtime_admin.py:1878` 与 `:1727` 与 `:1799` 与 `:1911` 内联 `set(actor_roles) & {"admin","super_admin"}` / `"admin" not in actor_roles`
  5. `domains/media/capabilities/media_archive.py:138 _role_at_least`（`_ROLE_RANK`，未知档 `-1`、未知需求档 `4`）与 `domains/chat_reply/capabilities/group_info.py:119 _role_at_least`（**函数内又抄了一份 rank 字典** `:121-127`，语义与 media_archive 同但表体独立）
  6. `domains/subscribe/capabilities/subscribe.py:169` 与 `subscribe_v2.py:62 _is_admin`（各自从 `message.sender_roles` 取集合）
  7. `plugins/bot_unified_runtime/__init__.py:4938 _is_admin_origin(event)`（**完全不走 roles 真身**：`return user_id in {str(item).strip() for item in config.bot_admin_user_ids}`）
  旁路 matcher 谓词另 3 个：`__init__.py:4945 _is_admin_file_notice`、`:5459 _is_admin_file_export`、`:5555 _is_admin_cookie_command`，全部叠加在 `_is_admin_origin` 之上。
- **控制面独立一套授权轴**：`control_plane/auth.py:28 Principal(subject, roles=("admin",))`（Bearer token 固定 admin 角色，`:183 _super_admin_dependency` 用第二枚 `super_admin_token_sha256`，`:299-306` 两枚摘要相同即**主动废掉写权限**）。服务层再判一次：`control_plane/services.py:123 if "super_admin" not in principal.roles: raise ControlServiceError("forbidden", ..., 403)` → `/bot feature enable|disable|reset` 虽由 admin 触发（`domains/ops/features/feature_control.py:26`），实际改态仍需超管，**双层成立**（正面记录）。

### 2.2 有副作用入口清单 × 角色门（逐条核验）

`/bot` 子命令共 31 条分支（脚本 `C:/tmp/u11b-scan/bot_cmd_matrix.py` 从 `__init__.py` 的 `command_text ==` 分支穷举，L6505-7040），**每条都带 `actor_roles=_decision.actor_roles` 或内联 `"admin" not in`**。逐条判定：

| 入口 | 坐标 | 角色门 | 分级 | 群内普通用户可触发 | 幂等/审计 |
|---|---|---|---|---|---|
| `/bot status` | `echo.py:57`→`:66` | ✅ `_is_admin_actor` | admin | 否（拒绝走 user_copy 池 `:73`） | `audit_tags=["runtime_admin","permission_denied"]` 型 |
| `/bot decision` | `echo.py:160`→`:172` | ✅ | admin | 否 | `:183 "decision_denied"` |
| `/bot receipt\|audit\|recent\|queue\|roles\|persona\|context\|config\|readiness\|dialogue\|llm\|setup llm\|pause\|history` | `domains/ops/admin/debug.py:78/:120/:162/:200/:225/:249/:387/:493/:522/:564/:601/:887/:280/:332` | ✅ 14 处 `if not _is_admin(actor_roles)` | admin | 否 | `history` 清空类副作用另有 `:343` 门 |
| `/bot runtime\|model`（读写运行时/模型注册表） | `runtime_admin.py:1864`→`:1878` | ✅ | **admin 读、super_admin 写**（`:1885` 对 `set/reset/persona switch·probability·reset/model 非只读子命令/nickname add·remove` 强制超管） | 否 | `_admin_only_result` `:46-57` |
| `/bot identity`（会话昵称/标签） | `runtime_admin.py:1694`→`:1727` | ✅ | admin | 否 | `set_by="admin"` `:1758/:1768` |
| `/bot identity set-name\|set-gender`（用户自助） | `echo.py:3685 build_identity_preference_result` + `_IDENTITY_PREFERENCE_SUBCOMMANDS:3655` | 仅本人（无 admin 门，符合设计） | self-only | 是（仅改自己） | 群聊「漂泊者」保留字回退 |
| `/bot quirk approve\|retire\|add` | `runtime_admin.py:1787`→`:1799` | ✅ | admin | 否 | `store.approve/retire/add_direct(source="admin")` |
| `/bot alert` | `runtime_admin.py:1904`→`:1911` | ✅ | admin | 否 | — |
| `/bot route\|routes\|search\|parse\|download\|reply\|subscribe\|logs\|group` | `__init__.py:6791/:6820/:6839(门 `:6844`)/:6891(`:6900`)/:6914/:6929(`:6940`)/:6993/:7019/:7040(`:7045` `actor_names`) | ✅ 全部内联 admin 判定 | admin | 否 | `search_denied`/`parse_history denied`/`reply_detail denied`/`group_policy denied` |
| `/bot feature enable\|disable\|reset` | `feature_control.py:17`→`:26` + `services.py:123` | ✅ 双层 | 触发 admin、**改态 super_admin** | 否 | 返回 `audit_id`（`:35`）+ 乐观并发 `expected_version/expected_graph_revision` |
| 媒体归档 `收藏/归档` | `media_archive.py:372` | ✅ `_role_at_least(config.bot_media_archive_min_role)`（缺省 `super_admin`） | 配置档 | 视配置（缺省否） | sha256 去重 + JSON 旁车 |
| 归档 `子路径=` | `media_archive.py:133`→`:519 if args.get("subpath") and is_admin` → `:520 sanitize_dirname` | ✅ **admin 位与 min_role 分离判定** | admin | 否 | 消毒后 `archive/media_archive.py:219-222` 拼接 |
| 控制面 config/features 写 | `_app.py:518-527`（`write_dependency`）+ `api/v1.py:126-138/:167-173` | ✅ | super_admin token | 否（非消息面） | `audit_middleware` `:720` |
| 控制面 actions execute/cancel/preview | `api/actions.py:42/:50/:55` 全部 `Depends(write_dependency)` | ✅ | super_admin | 否 | `runs` 落库 + `_sanitize_action_details` |
| 工作区 CRUD vs 真实发送 | `control_plane/workspaces.py:39 mode: Literal["sandbox","real_session"]="sandbox"`；`:186-187` real 且无 `real_adapter` → `503 real_session_unavailable`；`:327-328` `not_wired` 「本次未发送、确认仍有效」 | ✅ **缺省 sandbox + 未装配即 503** | super_admin | 否 | 与 #42「真实发送端口未装配」口径一致 |
| `/bot cookie`、`/bot 昵称 set`、`/bot 群文件`、群文件上传通知 | `__init__.py:5641/:5648/:5674/:5031` | ⚠️ 走 `_is_admin_origin`（见 D2-F1/F2） | **只认 admin 名单，无超管叠加、无 blocked 判定** | 否 | ❗旁路 matcher：`block=True` 且 priority 8 抢在 `/bot`（11）之前 → 不入 `policy/gate`、不入 base_router 审计（`__init__.py:5556` 注释自证「旁路 matcher 不入 base_router 审计」） |
| `/bot download`（文件出站） | `file_gateway.py:281 check_download_url` + 工单/确认 | ✅ | admin | 否 | 工单幂等 |
| 哈希重录 | `scripts/` + `tests/verify_hashes.py --write` | 非消息面（开发机手工，进程内无门） | n/a | 否 | 属运行纪律不属代码门 |

### 2.3 未过（中央）角色门即达副作用的条目

**D2-F1｜P1｜被封禁的管理员在四条旁路链上仍然全权（blocked 判定被绕过）**
- 坐标：`plugins/bot_unified_runtime/__init__.py:4938-4943`，锚点 `return user_id in {str(item).strip() for item in config.bot_admin_user_ids}`。
- 根因：该谓词直接读 config 名单，不复用 `RoleSettings.resolve_roles`，因此永远看不到 `ROLE_BLOCKED`；而中央门 `domains/chat_reply/policy/gate.py:225 if ROLE_BLOCKED in actor_roles: → allowed=False, reason="sender_blocked"` 只在走 pipeline 时生效。
- 证据：命中面 4 条 `block=True` 旁路 matcher —— `:5031 file_notice`（群/私文件入库）、`:5464 file_export`（生成并上传文档 `:5464` 起）、`:5641 cookie_admin`（**写入平台 Cookie / 发起扫码登录**，处理器 `:5657` 起）、`:5648 nickname_set`（改任意用户小名 `:5666 store.set_nickname(target_user, nickname)`）、`:5674 group_file_stats`（导出全群上传者与文件清单，`:5678` 二次判定同一谓词）。且 `__init__.py:5556` 注释明示该族「旁路 matcher 不入 base_router 审计」。
- 影响：把某管理员加进 `BOT_BLOCKED_USER_IDS` 后，普通命令确实不理他，但 `/bot cookie import`、`/bot 昵称 set`、`/bot 群文件`、文件导出**照旧成功**；这四条恰恰是全项目副作用最重的管理面。属「护栏可绕过」= P1。
- 改法 before→after：`return user_id in {str(item).strip() for item in config.bot_admin_user_ids}` → 复用真身判定：`roles = role_settings.resolve_roles_for_sender(user_id)`（若嫌 `resolve_roles` 只收 message，就在 `roles.py` 增 `roles_for_id(sender_id) -> set[str]` 单点，`resolve_roles` 转调它），再 `return ROLE_ADMIN in roles and ROLE_BLOCKED not in roles`。
- 验证：`pytest tests/test_admin_roster_and_roles.py tests/test_datafix_runtime_paths.py --basetemp="$TEMP/u11b-d2" -p no:cacheprovider`；新增负样本：`bot_blocked_user_ids=[A]` 且 `bot_admin_user_ids=[A]` → 四条 matcher 谓词全部 False。

**D2-F2｜P2｜同一谓词丢掉超管（越权的镜像面：门禁误拒 + 双实现漂移）**
- 坐标同 `__init__.py:4943`。
- 证据：`domains/chat_reply/policy/roles.py:34-36` 明文「超管自动叠加 admin 角色：既有 admin 判定点无需逐一感知超管」，但 `_is_admin_origin` 不是「既有 admin 判定点」而是自造判定，只读 `config.bot_admin_user_ids`（`config.py:79` 与 `:82 bot_super_admin_user_ids` 是两条互不包含的列表，装载器 `config.py:1170-1171` 并列，无任何合并）。
- 影响：仅列入超管名单者用不了 `/bot cookie`、`/bot 昵称 set`、文件导出、`/bot 群文件`；而 /bot 主链同一个人却全权 → 同一身份两套权限，行为不可预期（会错）。
- 改法：同 F1 的单点化即自动修复（超管叠加由真身负责）。
- 验证：新增 `test_super_admin_can_use_bypass_admin_matchers`；`grep -rn "config.bot_admin_user_ids" plugins/bot_unified_runtime/__init__.py` 期望仅剩「收件人=管理员名单」类用途（`:3031/:4421`），判定用途零命中。

**D2-F3｜P2｜秩表两份实现（`_role_at_least`）**：`domains/media/capabilities/media_archive.py:138`（用模块级 `_ROLE_RANK`）与 `domains/chat_reply/capabilities/group_info.py:119`（函数内 `:121-127` 手抄 rank）。当前两份数值一致（user0/trusted1/enterprise2/admin3/super_admin4），**没有任何门保证它继续一致**；未知角色 `-1`、未知需求档默认 `4`（两份同型，fail-closed ✅）。改法：提到 `policy/roles.py` 出 `role_at_least(roles, min_role)` 单一实现，两处转调；门：在 `tests/test_rendering_contract.py` 同族位置加一条 rank 表快照断言。

**D2-F4｜P2｜控制面 divination POST 面挂在读权限下**
- 坐标：`control_plane/api/divination.py:141 @router.post("/draws")`、`:152 /fortune/daily`、`:161 /tarot/draw`、`:188 /draws/{draw_id}/interpretation`、`:212 /bazi/preview`，处理器一律 `principal: Principal = Depends(read_dependency)`（`:145/:156/:165/:176/:192/:216`）；对照同项目 `api/actions.py:42/:50/:55` 与 `api/platform.py:99/:146/:173/:179/:185/:266/:287/:309` 全部 `write_dependency`。
- 装配处即缺料：`_app.py:539-544 build_divination_router(facade=..., read_dependency=...)` 根本没传 `write_dependency`。
- 影响：只该拿「只读 token」的主体可触发占卜生成与 **`/interpretation` LLM 解读**（真金白银的 token 消耗 + 写库 draws 记录），与全站「写=超管」的分级不一致。缓解事实：控制面仅环回 + 显式拒 0.0.0.0（AGENTS 台账 #27 已核）。判 P2 不判 P1。
- 改法：`_app.py:542` 补 `write_dependency=_super_admin_dependency(...)`，`divination.py` 的 5 个 POST 改 `Depends(write_dependency)`（GET 保持 read）。
- 验证：`pytest tests/test_control_plane_*.py --basetemp="$TEMP/u11b-d2" -p no:cacheprovider`；OpenAPI 断言 `operationId` 对应 security scope 分级。

**D2-F5｜P2｜`/bot feature` 的文案承诺与门禁不同源**（已核双层成立，仅登记文案风险）
- `domains/ops/features/feature_control.py:27` 拒绝话术 = 「功能管理需要管理员权限，修改仅限超管。」；本地门 `:26` 只挡到 admin，真正超管判定在 `control_plane/services.py:123`。语义正确，但**话术与门分处两文件**，日后有人只改话术或只改本层门即静默破口。改法：本层判定改为 `if "super_admin" not in actor_roles: raise ...`（与服务层同源同档），或把话术改成「以服务层判定为准」。
- 验证：`pytest tests/test_runtime_feature_gate.py tests/test_feature_store_integrity.py tests/test_feature_cards.py -p no:cacheprovider`（无 `test_feature_control*` 同名件，已按实存名改写），补 admin 触发 enable → 期望 403 审计行。

**D2-F6｜P3｜`_is_admin_actor(None)` / 内联判定形状共 7 类**：无功能缺陷（全部 fail-closed），但「同一件事 13 种写法」正是本波 mandate 要收的口。统一收编到 `policy/roles.py` 的 `role_at_least` + `is_admin_actor` 两个出口即可，属欠账。

### 2.4 主动出站通路收件人注入核验（逐条查证，**零发现**）

| 通路 | 收件人来源坐标 | 判定 |
|---|---|---|
| 提醒督促 | `domains/schedule/capabilities/reminder.py:666 target_id=str(message.group_id or message.sender_id)`；投递 `store/reminders.py:267-269` 原样携带 `target_id/bot_id` | ✅ 只认「谁建的提醒」，消息文本无收件人位 |
| 校园自动转发 | `domains/assistant/campus/campus.py:152-154 session_id=f"private:{self.source.notify_qq}"` / `target_id=self.source.notify_qq`；三重门 `:72-78`（enabled ∧ self_ids ∧ whitelist，`*` 需显式）；冷却键 `:167` | ✅ 收件人 = `bot_campus_notify_qq`（config），群消息正文绝不参与目标 |
| 订阅推送 | `domains/subscribe/capabilities/subscribe.py:268/:273/:403/:407` 目标 = 当前 `group_id` 或 `message.sender_id`；`:361` 还显式校验 `destination.target_id == str(message.sender_id)` | ✅ 订阅者只能订到自己/自己所在群 |
| 群摘要 / 每日通讯总结 | `__init__.py` 调度器读 config 群白名单；`_is_private_admin`（`content_parser.py:255-258`）另把媒体参数限定私聊+管理员 | ✅ 群号来自配置，正文来自历史 |
| 运维告警 | `domains/ops/monitor/alerts.py:132/:139/:148 target_id=str(target_id)`（`:83` 归一），上游为 config 管理员名单（`__init__.py:3031 target_id=str(int(admin_id))`、`:4421`） | ✅ |
| 回戳 / 表情回应 | `__init__.py:5060-5083 _build_poke_back_intent`：`user_id`/`group_id` 取自事件对象（`event.get_user_id()`），非消息正文 | ✅ |
| 每日助理推送 | 台账 #32：`BOT_DAILY_ASSIST_PUSH_USER_IDS` 为空则整链不注册（「绝不猜人」） | ✅（配置面，与代码判定一致） |

## §3 D3 打码 / 消毒多份实现差异表

**一句话结论**：文字消毒有 **两个「中央」函数**（`redact_local_secrets` 与 `redact_private_debug`），**黑名单互不覆盖**（前者认盘符/BOT_/JWT/userinfo，后者认 cookie/session_id/Authorization）；而**「出站前一律打码」这条铁律并没有实现成出站咽喉**——`redact_local_secrets` 在渲染链（`domains/render/renderer.py`）与发送队列（`domains/transport/sender/queue.py`）里 **零调用**，它唯一的对话面调用点在 `chat.py:2354`（bot.chat 能力自己的尾巴）。因此 32 条路由里除 `bot.chat` 之外的能力正文、以及 13 处直接构造 `SendRequest` 的通路，全部不经任何脱敏出站。
**D3 共 6 条：P0 0 / P1 2 / P2 3 / P3 1。**

### 3.1 全树消毒实现盘点（份数 / 覆盖 / fail-open vs fail-closed / 挂在哪一层）

| # | 实现 | 坐标 | BOT_x= | 盘符路径 | sk- | JWT | URL userinfo | Bearer | cookie/session_id | 失败语义 | 挂载层 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `redact_local_secrets`（**文本咽喉**） | `domains/render/plain_text.py:340`（垫片 `output/plain_text.py`）；规则 `:303-336` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌（词干表 `:330` 无 cookie/session） | 幂等、不抛 | **仅 `chat.py:2354` 与 12 处自律调用** |
| 2 | `redact_private_debug`（**审计/调试咽喉**） | `domains/ops/audit/logger.py:38`；规则 `:20-27` | 间接（键名含 key/token/secret 才中） | ❌ | ✅ | ❌ | ❌ | ✅ | ✅ | 不抛 | 审计 / 日志 / DTO |
| 3 | `events._redact` | `control_plane/events.py:103` = ①+② | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **fail-closed**（`:107` 异常→返回 ""） | SSE 事件 / 日志摘要 |
| 4 | `actions._redact` + `_ACTION_KEY_DENY` | `control_plane/actions.py:43` + `:38-41` 键名正则含 `cookie\|authorization\|credential` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅（键名整丢弃） | **fail-closed**（`:47` 异常→""） | 动作详情 |
| 5 | `events._safe_details` | `control_plane/events.py:111`，`DETAIL_KEYS` 白名单（`:97-100`）+ 未知/凭证键整支丢弃 | 继承③ | 继承③ | | | | | ✅ | fail-closed（白名单 + 预算 128） | 事件详情 |
| 6 | `actions._sanitize_action_details` | `control_plane/actions.py:51`（预算 256、深度 4、数值域 `0<=v<=10**15`） | 继承④ | 继承④ | | | | | ✅ | fail-closed | 动作详情 |
| 7 | `audit.redact_query` | `control_plane/audit.py:29`，规则 `:24` = `(token\|secret\|key\|password\|authorization\|credential)=` + ② | ❌ | ❌ | ✅ | ❌ | ❌ | ✅ | ✅ | **fail-open**（`:40-42` ②不可用时「保留正则结果」返回原文） | 审计 URL query |
| 8 | `audit.redact_error_for_dto` | `control_plane/audit.py:44` **只过 ②** | ❌ | ❌ | ✅ | ❌ | ❌ | ✅ | ✅ | **fail-open**（`:53-56` ②异常时 `logger.debug` 后**原样截断输出**） | health/status/models DTO `last_error` |
| 9 | `config_store.redact_public_data` | `control_plane/config_store.py:80`，`:77 _ABSOLUTE_PATH_RE` + `:78 _ASSIGNMENT_RE` + `is_sensitive`（`:55-58` 后缀表含 `_COOKIE/_CREDENTIAL/_AUTHORIZATION`） | 整段隐 | ✅（命中即整段 `[redacted]`） | | | | | ✅ 按字段名 | **fail-closed**（深度 20 → `[redacted]`） | 配置 DTO / 审计 |
| 10 | `workspaces._safe` | `control_plane/workspaces.py:81-92` = ②∘① + 16 键白名单 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | fail-closed（非 JSON 直接 `raise ValueError`） | 工作区产物 |
| 11 | `event_store._redact` | `domains/ops/monitor/event_store.py:147-152` 只过 ①，`:167/:176/:284` 三重预算 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | **fail-closed**（`:152` 异常→None → 回落 `DEFAULT_MESSAGES[category]`） | 运行事件库 |
| 12 | `debug._safe_message` / `_safe_token` | `domains/ops/admin/debug.py:1679` **只过 ②** + 四个字段名替换 | ❌ | ❌ | ✅ | ❌ | ❌ | ✅ | ✅ | 不抛（② 幂等） | **`/bot` 管理查询正文（出站）** |
| 13 | `error_report`（错误卡脱敏） | `domains/ops/monitor/error_report.py:352/:373/:447/:695` 逐段过 ① | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | fail-open（渲染失败→纯文本兜底，兜底亦过 ①） | 诊断卡/回执 |
| 14 | `alerts` | `domains/ops/monitor/alerts.py:278/:356` 过 ① | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | 不抛 | 告警出站 |
| 15 | `acceptance.runner.redact_text/redact_mapping` | `domains/ops/acceptance/runner.py:582/:596` | 部分（自用） | | | | | | | | 验收报告 |
| 16 | `ledger.redact_error_summary` | `domains/chat_reply/llm_engine/ledger.py:173` | 记账侧 | | | | | | | | 计费账本 |
| 17 | `history.redact_history_text` | `domains/chat_reply/character/history.py:39` | 记忆侧 | | | | | | | | 会话历史 |
| 18 | `chat.py:745 _sanitize_untrusted_context_text` | 反注入包裹（非秘密脱敏，另一族） | n/a | | | | | | | | 引用/转发正文 |
| 19 | `credentials._masked_preview` | `domains/core/credentials/credentials.py:71` | 值预览 | | | | | | ✅ | | 凭据列表 |
| 20 | `llm_admin._safe_base_url` | `control_plane/llm_admin.py:45` | URL 去 userinfo | | | | | | | | 模型管理 DTO |

**份数结论**：同族「自由文本脱敏」实现 = **2 个真身 + 11 个各自裁剪的包装**（#3-#14 + #15-#20），裁剪方向不一致：有的只过 ①（#11 #13 #14），有的只过 ②（#8 #12），两个都过的（#3 #4 #10）各自又写了一份 try/except 白名单。

### 3.2 「同一敏感形态 A 面被遮、B 面裸奔」具体案例（只写形态与坐标，无真值）

**案例 A（盘符绝对路径）** —— 形态：`<字母>:\<反斜杠路径>`。
- 遮：`redact_local_secrets` `_LOCAL_PATH_RE`（`plain_text.py:310`）→ 走 ① 的面（chat 回复 `chat.py:2354`、事件库 `event_store.py:150`、错误卡 `error_report.py:352`、告警 `alerts.py:278`、SSE `events.py:106`、动作 `actions.py:46`）。
- **裸奔**：`domains/ops/admin/debug.py:1679 _safe_message` 只过 `redact_private_debug`（`logger.py:20-27` 无盘符规则），其产物**直接拼进出站 body**：`debug.py:107 body=f"未找到发送回执：{_safe_token(normalized_query)}"`、`:149 未找到审计事件：…`、`:1086-1130 readiness/context/llm 状态行`。`normalized_query` 是调用者原样输入的回显 → 管理员在群里发 `/bot receipt C:\Users\<用户名>\...`，回信里盘符与用户名原样出站到 QQ/群聊。
- 同形态另一裸奔点：`control_plane/audit.py:44 redact_error_for_dto`（只过 ②，`:53-56` 异常时**原文截断返回**）→ health/status/models DTO 的 `last_error` 可带盘符与 `BOT_` 赋值残段。

**案例 B（平台 Cookie 原文）** —— 形态：`NAME=值; NAME2=值2`（键名不含 token/secret/key 词干，如 `SESSDATA=`、`bili_jct=`）。
- 遮：只有 `config_store.is_sensitive` 的**字段名**后缀表（`config_store.py:55-58` 含 `_COOKIE/_COOKIES`）与 `actions._ACTION_KEY_DENY`（`:38-41` 含 `cookie`）——**都是按键名丢整支**，不看值形态。
- **裸奔**：两个真身都拦不住自由文本里的 cookie 串：① 词干表 `plain_text.py:330` = `sendkey|api_?key|secret|passw(?:or)?d|token|key`（无 cookie/session）；② `logger.py:21-22` 词干含 `cookie`，但要求键名本身命中（`SESSDATA`/`bili_jct` 不命中）。→ 任何把 Cookie 值写进 `CapabilityResult.body` 或日志 message 的路径（如解析器 `context.py:24 sanitized_headers` 之外的回显、`/bot cookie import` 回执）在**全部 20 个实现**上都不遮。

**案例 C（`sendkey` / PushPlus `token` 裸键值）** —— 形态：`sendkey=值`、`token=值`。
- 遮：①（`plain_text.py:330` 词干含 sendkey/token）。
- **裸奔**：`event_store._sanitize_details`（`event_store.py:176`）走 ①，但 `logger` 系私有 ②-only 路径（`debug._safe_message`、`audit.redact_error_for_dto`）同样命中案例 A 的缺口——同一 token 形态在事件面被遮、在 `/bot` 查询面裸奔。

**案例 D（QQ 号 / user_id）** —— 形态：5-11 位数字 ID。
- 全部实现**都不遮**（设计如此）：`events.py:97 _ID_KEYS` 白名单反而**专门保留** ID 键；`debug._safe_message:1682-1687` 只把 `target_id/session_id/provider_message_id/private_debug` 四个**字段名**换成 `[redacted_field]`，值本身已在别处出现时不拦。→ 不是缺陷，是口径；登记以免被误判为漏项。

### 3.3 绕过文本咽喉直接出站的文案路径（清单）

咽喉在 `renderer` / `queue` / `sender` 三层**均无调用**（实证：`grep -n "redact" domains/render/renderer.py` 零命中；`renderer.py:198/:225` 只调 `naturalize_chat_text`；`transport/sender/queue.py` 全文无 `redact_local_secrets`；`nonebot.py:547` 仅用于**发送失败原因**一处）。因此下列路径的正文不经任何脱敏：

1. **全部非 chat 能力的 `CapabilityResult.body`**：`echo.py`（help/commands/identity preference）、`domains/ops/admin/debug.py` 14 个查询、`runtime_admin.py`（`/bot runtime|model|persona|nickname|quirk|alert`）、`runtime_logs.py:22 build_logs_query_result`（日志摘要正文，②-only）、`finance/*`、`weather`、`market`、`stocks`、`fx`、`divination`、`notes`、`media_archive` 回执、`content_parser` 卡片正文（网页标题/正文摘录 → 全树唯一 ① 覆盖缺口最大的正文面）。
2. **直建 `SendRequest` 的 13 处**：`domains/assistant/campus/campus.py:150`（群消息原文 1500 字截断直转主人私聊，**零脱敏**）、`domains/chat_reply/runtime/pipeline.py:807/:885`、`domains/ops/monitor/alerts.py:280`（① 已覆盖 ✅）、`domains/ops/monitor/error_report.py:990`（① 已覆盖 ✅）、`domains/ops/smoke/smoke.py:1103/:1229`、`__init__.py:2915/:3027/:3188/:3335`（主动出站族）、`domains/core/contracts/runtime.py:294`（模型定义）。
3. **群摘要 / 每日通讯总结 / 每日助理推送**：正文由 LLM 生成后走 SQLite 队列直投，不经 `chat.py:2354`（该处只在 bot.chat 能力内）→ 模型被诱导复述路径/key 时，**摘要类出站无确定性打码兜底**。

**D3-F1｜P1｜「出站前一律打码」没有出站咽喉**
- 坐标/锚点：`domains/render/renderer.py:186 def render_reviewed_output(` + `:198 text = naturalize_chat_text(text)`（该行前后无 `redact_*`）；`domains/transport/sender/queue.py` 全文无 `redact_local_secrets`。
- 根因：铁律 3 承诺的「出站前 `output/plain_text.py` 会打码」实际只装在 `chat.py:2354`；能力层靠各自自律（12 处调用点），新能力默认不遮。
- 改法 before→after：把 ①∘② 合成一个 `redact_outbound_text(text)`（放 `plain_text.py`），在 `render_reviewed_output` 入口对 `body/title/detail` 与合并转发每条调用一次；`chat.py:2354` 保留（幂等，重复无害）；`SendRequest` 构造侧改为经由同一函数。
- 验证：`pytest tests/test_secret_redaction_hardening.py tests/test_f03_notice_redaction.py tests/test_rendering_contract.py --basetemp="$TEMP/u11b-d3" -p no:cacheprovider`（现存咽喉件 = `test_secret_redaction_hardening.py`，`tests/` 无 `test_output_plain_text.py`，已按实存名改写）；新增断言「renderer 出站文本含 `C:\\` 盘符 / `BOT_XX=yy` / `eyJ` 三者之一 → 必被替换」，并对 20 个实现做「② 面必须同时过 ①」的一致性门（同 #26 的 config-catalog 门式写法）。

**D3-F2｜P1｜`_safe_message` / `redact_error_for_dto` 两个 ②-only 出口**：见案例 A。改法：`debug.py:1679` → `redact_local_secrets(redact_private_debug(value))...`（与 `events.py:106` 同口径）；`audit.py:44` 同步并补 fail-closed。验证：`pytest tests/test_control_plane_v1.py tests/test_control_plane_actions_api.py tests/test_secret_redaction_hardening.py -p no:cacheprovider`（`tests/` 无 `test_control_plane_api*` 同名件，已按实存名改写），负样本 = 含盘符的 `last_error` 与含盘符的 `/bot receipt <输入>`。

**D3-F3｜P2｜`audit.redact_query:40-42` 与 `redact_error_for_dto:53-56` 的 fail-open**：`except Exception: 保留原文` 与全站「宁缺毋泄」（`events.py:107`、`actions.py:47`、`event_store.py:152`）相反向。改法：异常→返回 `""` 或 `"<redaction unavailable>"`。

**D3-F4｜P2｜两真身词干表互不覆盖**（①无 cookie/session_id、②无盘符/BOT_/JWT/userinfo）：合并为 `redact_outbound_text` 后自然消失；过渡期至少给 `plain_text.py:330` 词干补 `cookie|session[_-]?id|authkey|credential`，给 `logger.py:20` 补盘符与 JWT 规则。验证：`pytest tests/test_secret_redaction_hardening.py tests/test_audit_fixes_b.py -p no:cacheprovider`（`tests/` 无 `test_auditfix_security.py`，已按实存名改写）。

**D3-F5｜P2｜20 个包装无一致性门**：全树对「脱敏实现份数/覆盖并集」零断言（对照 #26 已建的 config-catalog/route-matrix 门式做法）。改法：加一条常驻门，静态枚举 `redact_private_debug`/`redact_local_secrets` 的调用点集合，任何**新增**裸调 ②（不经 ①）且结果进入 `body=`/`text=` 的文件即红。

**D3-F6｜P3｜垫片双路径**：`output/plain_text.py` 与 `domains/render/plain_text.py` 同一函数两个导入名（`nonebot.py:33` 用旧名 `output.plain_text`，`chat.py:2347` 亦旧名；`events.py`/`actions.py` 用新名）。属 #42 退役面，不计缺陷。

## §9 未发现缺陷清单（诚实登记「查过但没发现」）

以下均已**动手核验**且**不构成缺陷**，供后续席位免重查：

1. **SSRF 咽喉本体无短路**：`domains/files/sources/downloader.py:308-334` 私网段表覆盖 0/8、10/8、100.64/10(CGNAT)、127/8、169.254/16、172.16/12、192.168/16、198.18/15、组播/保留、`::1`、`fc00::/7`、`fe80::/10`、`::ffff:0:0/96`，并叠加 `is_private/is_loopback/is_link_local/is_reserved/is_multicast/is_unspecified`（`:353-360`）；解析结果**全部**判定而非只取第一条（`:409-411`）；IPv4-mapped 先归一（`:346-347`）；`ipaddress` 解析失败按拒绝（`:343-344`）。本机全部敏感服务（SnowLuma 3001 / webhook 8080 / axonhub 8090 / 控制面 8742 / TTS 9880 / ollama 11434 / meme 2233）均在 127.0.0.1 → 咽喉命中即拒。**无绕过位。**
2. **无第二份 SSRF 判定逻辑**：全树 `ip_address|ip_network|is_private|is_loopback` 判定仅存在于 `downloader.py`（真身）与 `ssrf_guard.py`（归一化前置）+ `control_plane/__init__.py:152 is_loopback_host`（监听面绑定，另一族）。**咽喉唯一成立。**
3. **角色真身唯一且缺省 fail-closed**：`contracts/runtime.py:167/:196/:215` 三处角色字段缺省 `["user"]`；`media_archive.py:140` 与 `group_info.py:129` 未知角色秩 `-1`、未知需求档 `4`（升不降）。未发现「未赋值=管理员」形态。
4. **控制面写面分级完整**：`_app.py:299-306` 读写两枚 token 摘要相同即**主动废掉写权限**并 ERROR 留痕；`api/v1.py`、`api/actions.py`、`api/platform.py` 全部 mutating 路由挂 `write_dependency`；`services.py:123` 服务层二次判 super_admin。除 D2-F4 的 divination 一族外未发现例外。
5. **真实发送隔离位成立**：`control_plane/workspaces.py:39` 缺省 `mode="sandbox"`，`:186-187` `real_session` 无适配器 → 503，`:327-328` `not_wired` 明确「本次未发送、确认仍有效」，与台账 #42「factory 未注入 real_adapter」口径一致。消息面无法触达生产发送。
6. **主动出站零收件人注入**：见 §2.4 七通路逐条坐标。补充核验：`campus.py:72-78` 三重门任一空即整链关闭、`*` 需显式；`subscribe.py:361` 还额外断言目标等于本人。
7. **媒体归档/笔记/菜谱三链是脱敏与咽喉的正例**：`media_archive.py:194-239`（入口+逐跳+大小上限+`RejectedUrlError` 补进 except 元组防整批拖垮）、`notes.py:252/256`（入口+`geturl` 双查）、`eat.py:335/345`（公网候选 302→内网拒绝）。F4/F5 的修法即照此形。
8. **落点目录消毒未见穿越**：`media/archive/media_archive.py:66-74 sanitize_dirname`（非法字符正则 + `..`→`_` + 保留名加前缀 + 长度截断），`media_archive.py:519` 的 `子路径=` 既过 admin 位又过该消毒；`ops/repair/service.py:758` 拒绝式。未发现可穿越到根目录之外的写点。（残余 = §1.4「零 `is_relative_to`」= 纵深不足，非当下可利用。）
9. **控制面认证实现无明文 token 落地**：`auth.py:29-47` 只存 SHA-256 摘要 + `hmac.compare_digest`；`:63 mask_source`；`:71-79` 空摘要=未装配即 503。与 `audit-20260919` §3.6 结论一致（本席复述不另计）。
10. **`check_download_url` 未见协议放行**：`_ALLOWED_SCHEMES` 只 http/https，`file://`/`ftp://`/`gopher://` 一律拒（`:381-382`）；空串/无 host 拒。
11. **本席未复现的既有项**（不重复报）：`audit-20260919-unify-wave.md` §3.5/§3.6 已核的 Host 白名单、Bearer 禁入 query、SSE 410、mock 隔离、知识库集合白名单 + q≤200 + 分页钳制。

### 覆盖面自报（本席实际读到 / 未读到）

- 逐行读过：`downloader.py:289-418`（咽喉全函数）、`ssrf_guard.py` 全文、`http_util.py:60-180 / 280-429`、`roles.py` 全文、`gate.py:212-261`、`auth.py:1-80`、`feature_control.py` 全文、`runtime_admin.py:1864-1902`、`plain_text.py:300-400`、`media_archive.py(cap)&(archive):55-90/185-250`、`content_parser.py:660-740`、`image_stitch.py:99-158`、`meme_library_listener.py:60-120`、`credential_health.py:95-135`、`__init__.py:4930-4960 / 5052-5090 / 5455-5470 / 5550-5570 / 5641-5706 / 6619-6748`。
- 只跑脚本未逐行读：`domains/finance/*`、`domains/subscribe/adapters/*`、`domains/ops/smoke/*`、`scripts/*`（判定依据 = helpers_matrix 的「同文件有无咽喉符号」+ 实参形态）。
- 未跑任何 pytest（本席纯静态取证：所有 scoped 命令作为**修复后的验收建议**给出，本席无代码改动故无需跑；零「测试通过」宣称）。

## §10 断点续跑 / 收尾状态

- **三个交付物全部完成并落盘**：D1（10 条：P0 0/P1 6/P2 3/P3 1）、D2（6 条：P0 0/P1 1/P2 4/P3 1）、D3（6 条：P0 0/P1 2/P2 3/P3 1）。合计 22 条 = **P0 0 / P1 9 / P2 10 / P3 3**。
- **对「外部可控输入直达未校验 sink」的裁定：否。** 最接近的两条（D1-F1 `probe()`、D1-F2 拼图链）其 URL 取值需由**第三方响应体**或**上游 302** 决定，普通消息内容无法直接指定主机；入口用户 URL 一支由 `content_parser.py:697` 覆盖。判 P1（护栏可绕过）而非 P0。
- 临时件（全部在源码树之外）：`C:/tmp/u11b-scan/{enum_egress.py, enum_egress2.py, show_ast.py, show_strong.py, classify_parsers.py, helpers_matrix.py, bot_cmd_matrix.py, builder_gates.py, recipients.py, egress_raw.txt, egress_raw.json, egress_strong.txt, egress_ast.txt}`。
- **源码树卫生自查（实跑）**：`find plugins scripts tests -name __pycache__ -o -name "*.pyc"` → **0 / 0**（`PYTHONDONTWRITEBYTECODE=1` 本次有效，与「拦不住」的先例不同，已核对计数）；根目录 `.mypy_cache/.pytest_cache/.ruff_cache` mtime 为 12:30-12:47，**本席未跑 pytest/ruff/mypy，非本席产物**（台账 #1 既记项）；根目录 `%TEMP%/` 内 8 个 `u3_/u12_/u15_/u19_*.py` 属**并行席位脚本**，本席未写入未删除。本席新增文件 = **仅本日志一件**。
- 披露：本席未 commit、未改任何代码/配置/文档（除本日志）；未发起任何网络/DNS 请求（`check_download_url` 的 `getaddrinfo` 未被触发，DNS-rebind 结论以代码语义给出）；未读取 `.env`，日志内零密钥值（仅键名 + 文件:行）。
