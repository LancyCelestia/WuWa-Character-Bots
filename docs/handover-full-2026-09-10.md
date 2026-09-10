# 守岸人 Bot 全量交接文档（2026-09-10 全新版，事无巨细）

> 本文件是**从零重写的全新交接文档**，不基于旧文档增补；旧文档
> `docs/handoff-final-2026-09-07.md`（及其 git 历史）保留作过程档案。
> 定位：任何新会话/AI/人只读这一份，即可完整接手系统的**所有**子系统、
> 运维操作、已知坑与设计取舍理由。
> 编写时点：2026-09-10，分支 `v0.0.1-alpha.2`，HEAD 见 `git log -1`。

---

## 0. 三分钟速览

- **是什么**：QQ（NapCat/OneBot V11）为主的多人设聊天机器人，附带 Telegram / Mail / Console 适配器。核心能力：37+ 平台链接解析（Mica 卡图渲染）、多供应商点歌（候选选歌卡+歌曲卡+语音）、模型路由与渠道健康巡检、记忆/人格/好感度/向量知识库、订阅推送、搜索 API、内容安全防线。
- **代码规模**：插件主包 `plugins/bot_unified_runtime/`；`__init__.py` 约 5280 行（handler 装配/能力分发）；`config.py` 973 行 **426 个配置字段**；解析器 34 个文件；测试 111 个文件 **865+ 用例**。
- **验证基线**（2026-09-10 本轮交付时点）：`dev.ps1` 三门禁 = **865 passed / ruff 全过 / mypy 本组分文件零错**（树内常有并行会话在途文件的少量 mypy 残留，见 §19）。
- **一句话架构**：NapCat(WS 服务端 127.0.0.1:3001) ← bot(forward-WS 客户端) → IngressGateway → 路由/风控 → RuntimePipeline → CapabilityResult → 渲染(HTML→PNG 卡图) → SendQueue(SQLite) → 各适配器 sender。
- **最重要的三条纪律**（踩过实坑）：
  1. **密钥永不入库不入聊天**：真实 key 只在 `.env`（gitignored），配置里用 `env:变量名` 间接引用，且对应的 `bot_api_key_*` Config 字段**必须存在**（缺字段=env: 解析失败=整渠道失效，09-09 事故根因）。
  2. **commit 禁用 `git add -A`**：本仓库常有 2~3 个 AI 会话并行工作，`-A` 会裹挟别人未提交的半成品；只 `git add <明确路径>`。同理**共享 index 陷阱**：别的会话可能已把文件 `git add` 进暂存区，`git commit`（不带路径参数）会连他们的暂存一起提交——提交前 `git diff --cached --stat` 检查，或事后在 handoff 存证（f96d1a1 即实例）。
  3. **改动"没生效"先查进程启动时间再查代码**：`Get-Process python | Select Id,StartTime` 对比最后一次提交时间；bot 常驻进程不会热加载。

---

## 1. 运行环境与目录地图

```
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\
├── ChatBot\                     ← 唯一默认工作区（AI 只扫这里）
│   ├── bot.py                   ← 入口：NoneBot 启动 + 崩溃守卫 + TG 过滤器
│   ├── .env / .env.prod         ← 全部配置（.env 在 .gitignore；.env.prod 进库不含密钥）
│   ├── pyproject.toml           ← ruff/mypy/pytest 配置（basetemp 固定在源码树外）
│   ├── scripts/
│   │   ├── dev.ps1              ← 所有开发任务的统一入口（见 §3）
│   │   └── runtime_paths.py     ← BOT_RUNTIME_DATA_DIR 解析规则（data/ → Runtime 根）
│   ├── plugins/bot_unified_runtime/
│   │   ├── __init__.py          ← ~5280 行：plugin 装配、路由分发、各能力构建与接线
│   │   ├── config.py            ← 426 字段 Config + translate_env_keys
│   │   ├── runtime/             ← pipeline / ingress / base_router / aliases / settings /
│   │   │                          alerts / disconnect_notice / result_unknown / runtime_event_log
│   │   ├── capabilities/        ← 27 个能力模块（§8~§12 逐个说明）
│   │   ├── sources/
│   │   │   ├── parsers/         ← 34 个文件：34 文件矩阵见 §7
│   │   │   ├── fetchers/        ← PlaywrightFetchBackend（xhs 等真浏览器抓取）
│   │   │   ├── subscriptions/   ← social_v2 / xiaohongshu_adapter / youtube 适配器
│   │   │   ├── video_understanding.py / transcribe.py / vision_describe.py
│   │   │   ├── steamfree.py / web_search.py / meme_library_listener.py
│   │   │   └── credentials.py / platform_credentials.py
│   │   ├── character/           ← affinity / providers / memory / history / vector_knowledge /
│   │   │                          media_registry / shared_group / temporal
│   │   ├── security/            ← content_safety / memory_sanitize
│   │   ├── output/              ← renderer / plain_text / templates / render_backends /
│   │   │                          card_render/(bridge.py models.py templates/universal_card.html
│   │   │                          templates/song_candidates.html templates/affinity_card.html)
│   │   ├── llm/                 ← model_router / providers / channel_health
│   │   ├── sender/              ← onebot / nonebot / gateway / queue / receipts / worker
│   │   ├── policy/gate.py       ← 群门禁（URL 支持判定走注册表缓存）
│   │   ├── audit/logger.py      ← 脱敏审计
│   │   └── contracts/           ← media.py(ParsedContent 全家桶) / runtime.py / character.py
│   ├── tests/                   ← 111 个测试文件（865+ 用例）
│   └── docs/                    ← 本文档、handoff-final-2026-09-07.md（旧过程档案）、
│                                  affinity-design.md、capability-audit-2026-09-10.md 等
├── ChatBot_Runtime\             ← 运行数据根（默认不扫描不修改！）
│   ├── venv\                    ← 唯一运行虚拟环境（865 测试/playwright/PIL 都在这里）
│   ├── data\                    ← platform_cookies.txt / SQLite 库 / FAISS / cards / music /
│   │                              media_stitch / food_images / 订阅状态 / 记忆库
│   ├── logs\nonebot.out.log     ← dev.ps1 启动重定向日志
│   └── git\                     ← git 元数据外置目录（见 §18 git 陷阱）
├── ChatBot_Archive\             ← 归档区（历史/旧工作树，压缩后移入）
└── C:\Software\NapCat\          ← NapCat 本体 + login-bot.bat（快速登录脚本）
```

**路径重映射规则**（`scripts/runtime_paths.py` + `config.py` + `cookies.py` 各有一份等价实现）：
`data/...` 相对路径 → `BOT_RUNTIME_DATA_DIR`（.env=`C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/data`）。env 未设置时解析器一律**禁用写文件行为**（如 `image_stitch.py` 直接不拼接），绝不往源码树写。

---

## 2. 消息主链路（逐跳）

```text
QQ 客户端 ⇄ NapCat（OneBot V11 正向 WS 服务端，127.0.0.1:3001，token=ShoreKeeper）
   ↑↓ forward-WS（.env.prod ONEBOT_WS_URLS；NapCat 重启后 bot 自动重连）
bot.py（NoneBot 初始化 + 崩溃守卫：主循环异常自动重启；TG 轮询过滤器在此）
   → plugins/bot_unified_runtime/__init__.py
      ① _incoming_from_nonebot_event() → IngressGateway → IncomingMessage（严格 pydantic 模型）
      ② 路由（runtime/base_router.py）：RouteDecision{capability_id, rest_text, priority}
         - 命令：/bot <模块> <功能> [参数]（runtime/aliases.py 别名表归一）
         - 自然语言触发：chat / poke / 音乐 / 吃什么 / 天气 / wiki …（各 is_xxx_command）
         - URL → 解析管线（_has_supported_url 走注册表缓存单例）
      ③ 门禁/风控（policy/gate.py + __init__ 内联）：
         群黑白名单 → 安静时间（BOT_QUIET_HOURS_*）→ 限流（BOT_RATE_LIMIT_*，SQLite 窗口）
         → 幂等表（BOT_EVENT_IDEMPOTENCY_ENABLED 默认 false，进程内+SQLite 双层）
         → 内容安全（security/content_safety.py 硬/软类别）
      ④ RuntimePipeline.run() → CapabilityResult{kind, title, body, images[], audio[], files[], audit_tags[]}
      ⑤ Review（risk/privacy 评定）→ output/renderer.py → RenderedOutput
         （text / chunks / forward / mixed 四种 content_type；媒体部件透传规则见 renderer.py）
      ⑥ SendQueue（SQLite 持久化）→ UnifiedDeliveryGateway → sender.onebot / sender.nonebot
      ⑦ 发送回执 receipts / result_unknown 账本（重连对账，不盲发）
```

关键设计取舍：
- **发送层丢消息是 P0 事故**（09-09 实锤：LLM 慢烧完 90s 预算后发送层静默丢）。现在请求总预算 150s（`bot_request_budget_seconds`），**预算耗尽不丢已生成回复**，给足传输超时。
- 群聊 LLM 失败**静默**；私聊失败回 `_PERSONA_FAILURE_MESSAGES` 12 条守岸人话术轮换（`capabilities/chat.py`）。
- `bot.content` / `bot.music` 等长任务在 `to_thread` 里跑；playwright 渲染全大锁串行+线程本地常驻浏览器（`output/render_backends.py`）。

---

## 3. 启动、停止、验证（dev.ps1 全量任务）

```powershell
# 统一入口（PowerShell；Git Bash 下写 .ps1 临时脚本执行，防 $_ 被吞）
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task <task>"

# —— 三门禁（每轮交付前必须全绿）——
-Task test        # pytest 全量（当前 865 passed）；basetemp 已固定在源码树外
-Task lint        # ruff check
-Task typecheck   # mypy（205 文件）

# —— 启动前体检 ——
-Task doctor              # 环境体检
-Task backend-base-smoke  # 基础后端冒烟
-Task backend-smoke       # 完整后端冒烟
-Task chat-smoke          # 聊天链路冒烟
-Task search-smoke        # 搜索 API 验收（Tavily/You/TinyFish 真实 key）
-Task runtime-layout      # Runtime 目录布局检查（勿在手动删除缓存后立即跑）
-Task kb-sync             # 知识库同步（--kb-full 全量 / --kb-no-embed）
-Task smoke               # 综合冒烟
-Task run                 # 启动 bot（日志重定向 ChatBot_Runtime/logs/nonebot.out.log）
```

**启动顺序**：
1. NapCat：`C:\Software\NapCat\login-bot.bat`（UAC 确认，快速登录守岸人 3958874605）。
   验证：`netstat -ano | findstr 3001` 出 LISTENING。
2. bot：`ChatBot_Runtime\venv\Scripts\python.exe bot.py`（或 dev.ps1 -Task run）。
   确认**只有一个实例**（先查进程启动时间再查代码！）。bot 起来后自动连 NapCat。

**绕开 dev.ps1 直接跑 python/pytest 的铁律**：必须 `PYTHONDONTWRITEBYTECODE=1` + pytest 加 `--basetemp=<源码树外目录>`，否则源码树会出现 `__pycache__`/.pytest_cache（runtime-layout 会报，且违反工作区规范）。

---

## 4. 配置体系与密钥

### 4.1 Config 加载链

```
.env / .env.prod（NoneBot dotenv）→ driver.config
→ translate_env_keys()（BOT_X → bot_x，幂等小写化，config.py:11）
→ Config.model_validate(...)（pydantic，426 字段，config.py:28 起）
```
字段分域（前缀即域）：`BOT_RUNTIME_*`（实例/管理前缀/别名）、`BOT_PERSONA_*`+`BOT_TONE_*`（人格语气）、`BOT_ADMIN/BLOCKED/TRUSTED_USER_IDS`、`BOT_GROUP_*`（黑白名单/摘要/主动回复）、`BOT_QUIET_HOURS_*`、`BOT_RATE_LIMIT_*`、`BOT_MUSIC_*`、`BOT_PARSE_*`、`BOT_CHANNEL_HEALTH_*`、`BOT_CARD_*`、`BOT_SEARCH_*`、`BOT_MODEL_REGISTRY`（整段 JSON）、`BOT_API_KEY_*`（密钥区，env: 引用的解析目标）等。

### 4.2 密钥规则（不可违反）

- 真实 key 只存在于 `.env`（gitignored）。配置值写 `env:BOT_XXX_KEY` 形式。
- `env:` 解析链 = `os.environ → Config 同名字段回退`。**对应 `bot_api_key_*` 字段不存在 → 解析结果 config_missing → 该模型全渠道失败**（09-09 五连发失败事故根因，当时补了 9 个字段）。
- Cookie 与密钥值永不进日志/审计/消息（`audit/logger.py` 脱敏 + `cookies.py` 只暴露 cookie 名）。

### 4.3 Cookie 文件

- 路径：`ChatBot_Runtime/data/platform_cookies.txt`（Netscape 格式）。
- 管理：管理员指令 `/bot cookie import <平台> <Cookie头>` 热写入；或直接编辑文件追加 Netscape 行。
- 平台域名白名单与关键 cookie 名：`sources/parsers/cookies.py:PLATFORM_COOKIE_DOMAINS`（bilibili/xiaohongshu/douyin/qqmusic/netease/kuwo/kugou/twitter/youtube/kurobbs/weibo/kuaishou/acfun/moegirl/xiaoheihe/skland/miyoushe）。
- **当前实装状态**（2026-09-10）：小红书 ✓（web_session 有效）、微博 ✓（09-10 灌入登录态 SUB/ALF/SUBP）；**B站无登录态**（建议 `/bot cookie import bilibili`，可解锁 AI 字幕+降低 -352 面积）；X 无凭证（订阅推特前必须先 import）。
- 微博解析有无登录态都能用：无登录态自动走 genvisitor 访客兑子（`platforms_weibo.py:_weibo_visitor_cookie`，进程内缓存 6h；genvisitor→incarnate 换 SUB/SUBP/tid）。

---

## 5. 解析器矩阵（sources/parsers/，34 文件全量）

### 5.1 架构

- 注册中心 `parsers/__init__.py`：`_PLATFORM_RULES`（平台→URL 正则→解析函数→优先级），`build_content_parser_registry(enabled_platforms, cookie_provider, proxy, playwright_backend)` 返回 `{registry, parsers}`。
  - **全默认参数调用有进程级单例缓存**（`_DEFAULT_REGISTRY_BUNDLE`）：群门禁每条消息全默认调一次，缓存后零重复构建。
  - 代理绑定 `_PARSER_PROXY_PLATFORM`：youtube/twitter/spotify/pixiv×5/facebook 走 `BOT_DOWNLOAD_PROXY`（127.0.0.1:7890）。
  - playwright 绑定：xiaohongshu、kurobbs。
- 公共设施：`http_util.py`（http_get/text/json/post_json，代理/UA/重试/gzip）、`wbi.py`（B站 WBI 签名，键 30 分钟缓存）、`cookies.py`（§4.3）、`image_stitch.py`（竖切横图拼接，§5.9）。
- 契约：`contracts/media.py` `ParsedContent`（纯嵌套：identity/content/creator/engagement/media/music/provenance）+ `build_parsed_content()` 归一化构造器。解析器产出平台形状字段（stats/detail），构造器负责映射；`detail` 键消费白名单 `_DETAIL_CONSUMED_KEYS`、作者键 `_AUTHOR_CONSUMED_KEYS`。
- **时间契约（重要）**：`_optional_datetime` 对 naive 时间一律按**北京时间**解释（`_CN_TZ=+08:00`）。解析器不得产出 naive 字符串当 UTC；带时区 ISO 或 epoch 最稳。字符串发布时间经此归一，展示层 `astimezone()` 得到正确本地时间。（历史：误标 UTC 曾致微博/推特/专栏时间整体漂 8 小时，09-10 契约层根治。）

### 5.2 B站（platforms_bilibili.py，~2100 行，A组主战场）

分发入口 `parse_bilibili()` 按 URL 形态分流（b23.tv/bili2233.cn 短链先 `resolve_short_link`）：

| 形态 | 函数 | 数据通道（按可靠性排序） |
|---|---|---|
| 视频 BV/av | `_lookup_video_by_id` | `x/web-interface/view` 主数据 + `_author_enrichment`（card 签名/relation 粉丝关注/navnum 视频专栏数/upstat 获赞+总播放，**WBI 签名**）+ AI 总结（view/conclusion/get，WBI）+ 字幕（player/wbi/v2，ai-zh 优先，需登录 cookie）+ 热评（v2/reply ps=3 sort=1） |
| 直播间 | `_parse_live` | **主通道 `room/v1/Room/get_info`**（匿名稳，失败 1s 重试一次）+ `get_status_info_by_uids` 补主播昵称/头像/粉丝（POST，匿名可用）+ getInfoByRoom **降为尽力富集**（人气/在线/大航海 TOP3；对无登录态常态 **-352**，buvid3/4+浏览器 UA 实测无效——这就是主通道切换的原因） |
| 专栏 cv | `_parse_article` | `x/article/view` + `_author_enrichment` 全量注入；**-509/-352/-412/429 短停 1.5s 重试一次**（瞬态 IP 风控，实测隔秒自愈） |
| 直播富集 | guardTopList | 大航海 TOP3，尽力而为 |
| 空间 | `_parse_space`/`_parse_favlist` | card + navnum + relation |
| 动态 opus | `_parse_opus` | polymer web-dynamic/v1/opus/detail |
| 番剧 | `_parse_bangumi` | season view + stat；失败回退 og |
| 课程 | `_parse_cheese` | pugv/view/web/season |
| 漫画 | `_parse_manga_card` | twirp TLS 指纹风控 code=99 **不可破**，诚实降级浅卡 |
| 会员购 show | `parse_bilibili_show` | `show.bilibili.com/api/ticket/project/getV2`，全字段见 §5.8 |
| 合集/搜索/公益/游戏/电竞 | 各 `_parse_*` | 见文件内 docstring |

**实测经验（2026-09-10）**：`web-interface/view`、`popular`、`Room/get_info`、`get_status_info_by_uids`、`finger/spi` 匿名可用；`article/view`、`xlive/getInfoByRoom`、`player/wbi/v2` 受波动 IP 风控（-509/-352），有登录 cookie 面积大幅缩小。`x/space/upstat` 需 WBI 且常需登录（拿不到就静默跳过）。
**时长口径**：`stats["时长"]` 存**整型秒**（字符串会让桥接 duration pill 退化成 0:00）；人类可读"X分Y秒"只在摘要行拼装。

### 5.3 微博（platforms_weibo.py）

- 单条微博三通道：①`m.weibo.cn/statuses/show?id={bid}`（JSON）→ ②`weibo.com/ajax/statuses/show`（PC ajax）→ ③`m.weibo.cn/status/{bid}` 页面 `$render_data`。通道前置 **`_weibo_merge_cookies`**：调用方 cookie 优先，缺失并入 genvisitor 访客兑子（缓存 6h）。
- m.weibo.cn 必须**移动端 UA + XHR 头**（PC UA 一律 302 访客验证 retcode=6102）。
- 头像 `_weibo_avatar`：avatar_hd 优先，`/50/`→`/180/` 升级，http→https。
- 视频帖：`page_info.media_info` 取直链，`page_pic` 作封面（无图集时）。
- 发布时间：`created_at`（英文格式带 +0800）strptime %z → **aware ISO 秒级**。
- 标题剥「xx的微博视频」尾缀。
- 长微博 `/statuses/extend` 补全文；图集 `pic_infos.largest`。
- **图片灰块事故结论**：xhs/sina 图床在 Chromium `<img>` no-cors 下被 **ORB** 拦（ERR_BLOCKED_BY_ORB）——修法见 §6.4 render_backends。sinaimg WAF：**直连+curl 形极简头 200；浏览器 UA 缺完整头 403；python TLS 指纹 403**。

### 5.4 小红书（platforms_generic.py 内 parse_xiaohongshu，~370 行起）

- 流程：xhslink 短链解析 → /discovery/item/ 归一 /explore/ → 用户主页（playwright capture_json user_posted → INITIAL_STATE → og）→ 搜索页关键词卡 → **笔记页深解析** → og 兜底。
- **笔记深解析 `_xhs_note_deep_parse`（09-10 修复）**：先 http_get_text（带 cookie）；失败或缺 `INITIAL_STATE` → **playwright fetch_html 兜底**（此前 backend 参数只用于用户主页，笔记页被 xhs 间歇 403/461 拦后就直接落 og 空卡——真实缺陷已修）。
- `xsec_token` 失效（整页 404）：自动剥 token 重试一次；仍失败给明确汇报文案（让用户重新分享）。
- **图片 URL 铁律（实测血泪）**：2026 版 xhscdn 的 `!nd_dft_*` 后缀**在签名路径内，剥掉即 403**（200→403 对照实测）。质量提升唯一合法姿势：优先 `imageList[].info_list` 里 `image_scene=="WB_DFT"` 的变体，否则 urlDefault/url **原样使用**。`_xhs_original_url` 剥！函数已删除（ed0fedb 引入、f96d1a1 撤回）。
- `_strip_js_new_map`：INITIAL_STATE 里 `new Map([...])` 平衡扫描替换为 null（嵌套数组防 JSON 截断）。
- URL 时效：图片地址带时间戳签名（约 10 分钟级），解析→渲染/发送要快；过期 403 属正常。

### 5.5 YouTube（platforms_generic.py parse_youtube，需代理）

三层合并：watch 页正则（标题/描述/时长）+ innertube 端点（作者数据）+ about 页（频道粉丝）。封面 `i.ytimg.com/vi/{id}/maxresdefault.jpg`；模板 onerror 自动回退 hqdefault（universal_card.html 封面 img）。字幕 captionTracks（ASR 滚动重叠去重）→ 摘录+`BOT_PARSE_SUBTITLE_SUMMARY=true` 时主路由出【AI字幕总结】。
边界：频道总获赞官方不提供；长/短视频数与 post 数需逐 Tab 抓取（未做）。

### 5.6 推特/X（platforms_generic.py parse_twitter_x，需代理）

fxtwitter 聚合接口（`api.fxtwitter.com/{user}/status/{id}`，`code==200` 门槛，纯媒体推文也走深分支）→ og 兜底。图片 `_twitter_large_url` 补 `name=large`；**photos 全量进 images**；`created_timestamp` epoch → `_format_epoch` 带时区 ISO。媒体多为 4 图竖切横图 → `try_stitch_strip` 拼接（§5.9）。

### 5.7 其他平台速览

| 文件 | 平台 | 要点 |
|---|---|---|
| platforms_music.py | 网易/QQ/酷狗/酷我/Apple/Spotify | 见 §9 点歌 |
| platforms_zhihu.py 系 | 知乎/豆瓣/TapTap/虎扑/贴吧等 | parser-lite 批次，og+API 混合 |
| platforms_discourse.py/community.py | Discourse 论坛/社区 | JSON API |
| platforms_acfun/kuaishou/lofter/... | 各社媒 | 注意各自 stats["发布时间"] 均产出 naive 本地串 → 契约层已按 +08 解释 |
| platforms_epic.py / steam.py | Epic/Steam 喜加一 | 免费游戏卡（capabilities/epic + steamfree.py） |
| platforms_moegirl.py | 萌娘百科 | moegirlSSOToken cookie |
| platforms_generic.py 其余 | 抖音（_ROUTER_DATA）、汽水/豆包/米画师/画加/BUFF | 抖音反爬拦截时给降级卡 |

### 5.8 会员购全字段（parse_bilibili_show，09-10 重写）

getV2 一发拿全，可见面=summary 行+stats，结构化全量存 `detail["show"]`：
- 档期 `project_label`、起止 `start/end_time`
- 场馆 `venue_info.name`+`place_info.name`（展厅）+城市+`address_detail`
- 票价 `price_low/high`（**分→元**）
- 场次 `screen_list[]`：名称/时间/售票状态 + `ticket_list[]` 票档明细（desc/价格/开售窗/状态）
- 票种 `has_eticket/has_paper_ticket` + 票档 desc 关键词（电子/实体/兑换）
- 退票 `refund_desc`（"支持/不支持7天无理由退票"）
- 嘉宾 `guests[]`：name/description/guest_img/book_num → **独立卡区**（bridge `show_guests` 投影 + universal_card 嘉宾网格）
- 主办 `merchant.company`；博主位 `follow_info.up_name/up_face`（无则主办方撑布局）
- 图文详情 `performance_desc.list[]`：**details 可能是 HTML 串或 [{title,content}] 列表**（`_show_module_text` 双形态适配）+ gallery 图片提取
- 实测样例：88451（苏州OCG，12嘉宾）、96799（惠州镜漫，4嘉宾）全字段上卡。

### 5.9 竖切横图拼接（image_stitch.py）

识别"横图竖切 N 块"发布形式：同尺寸竖图组（±2px 容差、单张 h/w≥1.12、n∈2..10、拼接总宽高比 1.0~4.0）→ PIL 横向拼回 → 落盘 `data/media_stitch/strip_{sha1}.jpg`（q90）。推特/小红书/微博三平台接入；任一图下载失败或条件不满足**原样返回不丢图**。BOT_RUNTIME_DATA_DIR 未设置时整功能自动禁用（防源码树写文件）。

---

## 6. 卡片渲染管线（Mica 规范）

### 6.1 管线

```
CapabilityResult → content_parser.render_card_png(backend, item, config, card_dir, bot_avatar_url)
  → bridge.parse_to_render_payload（ParsedContent→RenderPayload 字段全量投影）
  → bridge.render_universal_card_html（Jinja2，autoescape=True）
  → render_backends（PlaywrightRenderBackend：线程本地常驻 Chromium，
     page.set_content(networkidle) + img.complete 等待 + .card 元素截图 omit_background）
  → PNG 落盘 data/cards/ → CapabilityResult.images=[{"file": path}]
```

- **分支选择**：`use_universal`（有 page_type/badge/detail 或平台在 universal 集合）→ Mica 分支；否则 legacy 分支。点歌成功卡走 **legacy 分支**（实测显示效果好，已验证）。
- **UI 缩放**：`bot_card_ui_scale`（1.25 基准语义），card_width 1440px。

### 6.2 Mica 规范（AGENTS.md 硬规则）

- 底色渐变唯一来源：`PLATFORM_COLORS`（bridge.py:40，bilibili #fb7299 / xhs #ff2442 / weibo #e6162d / youtube #f00 / twitter #1d9bf0 / netease #c20c0c / qqmusic #00c853 / kugou / kuwo / apple_music / spotify / douyin / pixiv / lofter / allcpp / facebook / instagram），经模板 `--pc` 变量 `color-mix(in srgb, var(--pc) N%, #fff)` 掺白派生。**禁止写死品牌色**（含岸宝粉）——历史上大会员徽章写死 #fb7299 曾把全平台染成B站粉（已修为 --pc 派生）。语义状态色（认证金/错误红）不算品牌色。
- 阴影只允许 `--mica-shadow` + `--mica-shadow-soft` 两枚 token；圆角 `--r-shell/--r-panel/--r-tile`；字重≤700；`body` 透明背景+antialiased。
- `song_candidates.html`/`affinity_card.html` 为独立模板（B组/C组产），同样遵守派生规范。

### 6.3 RenderPayload 关键字段（models.py）

身份/内容（name/avatar/title/summary/text/image_urls/cover_url/qrcode）、Header 五行（signature/handle/follower_count/timestamp/official_*）、统计（stats/author_stats/video_stats/stats_bar_items/author_stat_items）、视频（video_duration/video_desc/video_pages）、评论（pinned/hot/comments）、**show_guests**（会员购嘉宾网格）、直播（live_*）、平台主题（platform_color 系列）、bot（bot_name/bot_avatar_url）、card_width/font_scale。

### 6.4 本地图片与 ORB（两个曾致灰块的坑）

1. **本地文件**：playwright 以 about:blank 起页，`file://` 子资源被拒载 → `bridge._inline_local_image` 把本地图转 **data URL** 内联（12MB 上限；吃什么卡菜品图因此修复）。
2. **ORB 拦截**：Chromium 对部分图床（**wx*.sinaimg.cn** 实测）的 `<img>` no-cors 请求直接 `ERR_BLOCKED_BY_ORB`（卡上封面/头像全灰）→ `render_backends` 对 `_ORB_PRONE_HOST_SUFFIXES`（sinaimg.cn/weibocdn.com）安装 `page.route`：**直连+curl 形极简头**（`_ORB_FETCH_HEADERS`）python 侧取回字节 `route.fulfill`。取回头形态实测矩阵：sinaimg WAF 对「浏览器 UA 缺完整头」和「代理出口 IP」都 403，**直连+curl 极简头才 200**。名单外不拦截（避免每图双下载）。
3. 渲染失败语义（并行会话改版）：页面级错误只关页面复用浏览器；浏览器级错误（Target closed 等 `_BROWSER_CRASH_MARKERS`）才重置常驻浏览器。

### 6.5 转义规则（易踩）

bridge 对 `payload.text/summary/forward.text/repost.text` **预 html.escape**；legacy 分支模板用 `| safe`（净一次转义）；**Mica 简介分支**是 `{{ video_desc or summary | safe or text | safe }}`（video_desc 未预转义靠 autoescape，summary/text 已预转义用 safe——新增渲染点务必分清）。CSS 注入由 `_safe_css_color/_css_url_token` 阻断。

---

## 7. 点歌子系统（capabilities/music.py，~795 行）

### 7.1 搜索与候选决策树（完整版）

```
「点歌 X」→ base_router is_music_command（模式词/别名由 B组 P3#23 修复：不再吞消息）
  → capability():
    X 以 # 开头 → 剥 #，强制按歌名搜索
    X 是模式别名（link/卡片/语音…）→ 冲突提示 + 「点歌 #X」转义用法（不搜）
    X.isdecimal()（十进制才安全，"²" 不再崩）:
        会话命中（session+sender 隔离、TTL 内、编号在界）→ detail_fn(候选) → _render_hit
        否则 → 「编号不在候选里，重新点歌」提示（绝不拿数字当歌名搜）[music_candidates_miss]
    候选启用（BOT_MUSIC_CANDIDATES_ENABLED && candidate_providers 非空）且 X 非纯数字:
        list_fn(X, limit=candidates_limit)   ← limit 全平台透传（原先硬编码5截断）
        len(cands)>=2 且非「裸歌名+首条精确同名」→ 存会话 → _render_candidates_card
            （song_candidates.html → PNG；失败逐字回退纯文本编号列表 [music_candidates_card]）
        裸歌名（无空格）且精确命中 → 跳过候选直接播放（点歌 晴天 → 周杰伦）
        带限定词（「晴天 钢琴版」）即使存在字面同名命中也出候选窗
            （网易云模糊搜索几乎总能搜出字面同名翻唱——旧 exact_hits 一票否决
             曾让候选卡几乎不可达，09-10 根治）
    未命中候选 → 逐平台 search_fn 单结果 → _render_hit
```

- 会话存储：`_CANDIDATE_SESSIONS[session_type:session_id:sender_id] = (expires, parser_id, cands)`；`_CANDIDATE_MAX_SESSIONS` 容量上限+最旧逐出。
- 二次选择详情：`candidate_providers[platform][1]`（`.get()` 判空降级）；QQ/酷狗/酷我/网易各有关键 ID 直取详情；酷狗复用 `parse_kugou`（getSongInfo：封面+标题+试听）。

### 7.2 成功卡与发送（_render_hit）

优先级：**Mica 歌曲卡 PNG**（`_render_music_card_png` → render_card_png，失败 warning 日志）> **封面直链** > CQ:music 签名卡（最后——NapCat 缺 musicSignUrl 会拒签并中断整条消息）。语音：`mode` 含 voice 时音频下载（ffmpeg 转 OGG/OPUS，失败降级）。实测真实数据：网易云《晴天》搜索→候选卡→编号选择→成功卡（封面/歌手/专辑/平台色全对）+语音。

### 7.3 供应商现状（实测 2026-09-10）

| 平台 | 搜索 | 候选 | 备注 |
|---|---|---|---|
| 网易云 | ✅ 匿名 | ✅ limit 透传 | 主力；pic_str 是资源 ID 不是 URL（已剔）；网易云模糊搜索几乎必出字面同名翻唱 |
| QQ | ✅ **musicu.fcg DoSearchForQQMusicDesktop**（POST） | ✅ | **旧 client_search_cp 服务端下线（任意参数恒 500，实测）**；封面 `album.mid` 拼 `y.gtimg.cn/music/photo_new/T002R500x500M000{mid}.jpg`；音频 vkey 需登录 |
| 酷狗 | ✅ msearchcdn（**明文 http**，证书主机名不匹配——已知取舍） | ✅ | 编号详情复用 parse_kugou |
| 酷我 | ⚠️ 单结果走第三方 suyanw 聚合 | ❌ r.s 接口服务端劣化返回非 JSON（实测） | 候选路径静默跳过；登记已知边界 |
| Apple/Spotify | Apple ✅ itunes API；Spotify search 恒 None（占位） | — | Spotify 链接解析可用 |

---

## 8. 模型路由与渠道健康（llm/）

- **注册表**：`.env BOT_MODEL_REGISTRY` 一段 JSON，45 条目，8 供应商（浅夜/恒星纪元/ToolCode/umi（含 Claude 四渠道）/DeepSeek 官方/智谱/StarAPI/hcn 兜底）。条目含 price_in/price_out/priority/think/effort/`env:`key。
- **选择顺序**：手动指定 > 时段组 order（BOT_MODEL_SCHEDULE/PRIORITY_GROUPS）> 基础 priority > 故障转移同序。`/bot model set <模型名>` 聚合同名全渠道。
- **渠道健康巡检**（channel_health.py，SQLite）：连续 2 次失败标 ⛔ 暂不可用移出故障转移队列，30 分钟重探，**永不自动删除**；全挂时放行原队列防全瘫。探针双模式：手动 `/bot model probe` 8 并发 / 后台 3 线程+0.4s 抖动（**已参数化** bot_channel_probe_threads/manual_threads/jitter_seconds）。
- **延迟择优 v2**（B组 d5a9f43）：EWMA 动态测量+慢渠道动态检测+路由排序动态切换+自适应超时与影子并发（无损切换）。双开关 `BOT_CHANNEL_HEALTH_ENABLED`+`BOT_CHANNEL_HEALTH_LATENCY_FIRST`。auto-route 全局队列保持人工策展 priority 不被延迟重排（设计裁决：否则原生 gemini 会被套壳渠道的速度反复顶掉）。
- **已知渠道事实**：浅夜渠道 gemini-3.8 自报 DeepSeek 身份（套壳实锤，介意用 aiprc-gemini/starapi-gemini，已在 .env 提前）；umi 三渠道余额 ✦0 需充值；浅夜主 key 曾 401；ds-official 曾 no_api_key；toolcode-gemini 404 下架。
- **指令族**：`/bot model list|set|add|update|priority|think|effort|price|remove|reset|usage|health|probe|routes`。health 报告含【需要你处理的】行动清单。
- **vision direct**（默认）：图片以 data URL 直传主模型；`supports_vision` 默认全渠道（text-only 标签排除）；relay（VLM 转译）兜底；`/bot model vision mode relay|direct`。
- **请求总预算 150s**；预算耗尽不丢已生成回复。记忆抽取复用主路由（独立超时/冷却）。

---

## 9. 记忆 / 人格 / 好感度 / 知识库（character/）

- **好感度 v3**（affinity.py + docs/affinity-design.md，用户已裁定）：初始 10（内部 0.1）；五行为影响因子+每日有效次数上限；步长幂律非线性（距极值 <10 分按 (d/0.1)^γ 缩小）；因人而异（sha1 派生 ±15% 个人系数）；惰性回归向基数收敛；四档位→语气映射；`好感度 算法` 图文说明卡。库里 WAL 模式；每日上限按本地自然日。
- **查询卡**：`好感度`（私聊双向：守岸人对你/你对他）/`群好感榜`（镜像表，正分绿低分红）；affinity_card.html 独立 Mica 模板。
- **记忆**：chat.py 后台线程抽取（`_schedule_memory_extraction`，独立超时不阻塞回复）；`memory_sanitize.py` 清洗→隔离表。
- **知识库**：`vector_knowledge.py` 向量检索+FTS；`dev.ps1 -Task kb-sync` 同步。
- **人格注入预算**：人设>知识库>短时对话>长时记忆（§5 Prompt 审计脱敏）。

## 10. 安全防线（security/）

- `content_safety.py`：硬类别（NSFW/血腥/政治/骚扰）不可放宽；软类别（强加称谓/宠物化/人格破坏/侮辱外号/excessive_intimacy/insult_nickname）管理员可放宽。
- 输出侧：`output/plain_text.py`（去引号/Markdown/LaTeX 噪声+TeX 命令转中文）+ 说人话层。
- 文件读取视为不可信数据，不执行代码。

## 11. 订阅（sources/subscriptions/ + capabilities/subscribe_v2.py）

- 适配器：Bilibili/Xiaohongshu/YouTube/Twitter/Telegram/Pixiv/Weibo（social_v2.py ADAPTERS）。
- **YT 订阅实测通过**（@handle 解析已修：先解析 handle→真实 UC 频道 id，失败回退不阻塞）；**推特订阅需先 `/bot cookie import x`**（当前无 X 凭证）；QQ 端实际推送外发需指定真实目标再验。
- v2 权限模型：pause/resume/remove 校验创建者/目的地归属；库有界化（outbox 14d 裁剪）。

## 12. 其他能力速查

| 能力 | 文件 | 要点 |
|---|---|---|
| 帮助 | echo.py | `/bot help` 双列网格手册卡；`/bot help <模块>`；分类名直查 |
| 天气 | weather.py | Open-Meteo+全球兜底；天气误捕静默 |
| 吃什么 | eat.py + sources/food_data.py | 随机/三选一/忌口；本地 60 道菜谱库；菜品图 Runtime data/food_images（本地图经 bridge 内联 data URL 后卡片可见） |
| 免费游戏 | epic.py + steamfree.py | Epic+Steam 双源 |
| 搜图 | image_search.py | SauceNAO |
| 萌娘 | moegirl.py + sources/moegirl.py | KB 优先 |
| 历史/回忆 | today_history.py | 本地 365 天库 |
| 戳一戳 | poke.py | NapCat poke/反戳（真实事件验收仍待） |
| 运维 | runtime_admin.py / debug.py / runtime_logs.py | `/bot model` 族、注册表 source=env 语义（.env 实时为准，明文永不落盘） |
| 文件 | file_exchange.py / group_files.py / download.py | 群文件/下载 |
| 表情包 | meme.py / meme_library.py | httpx Client 单例（修过连接池泄漏） |

## 13. 多适配器

- **Telegram**（sender/nonebot.py）：图文（本地 PNG 可作 photo）、语音 ffmpeg→OGG/OPUS（失败降级 sendAudio，缓存 %TEMP%/bot_tg_voice）、空文本+有媒体不再 SKIPPED、TELEGRAM_PROXY=http://127.0.0.1:7890。
- **Mail**：mail_adapter.py 韧性适配器+mail_bridge.py。
- **Console**：本地调试。
- **掉线通知**：runtime/disconnect_notice.py（TG/邮件/Server酱/PushPlus，默认关）。

## 14. 运维告警与可观测

- alerts.py：按 (stage,kind,adapter,bot,target) 300s 窗口抑制；`llm deadline_exceeded` 豁免（常态降级）。
- result_unknown 账本：发送结果未知时记账，重连对账不盲发。
- 审计：audit/logger.py 脱敏消息与上下文摘要；人格 Prompt 审计文件。
- 渲染失败日志：歌曲卡/候选卡 warning；`build_render_backend` 未知名字/不可用 warning（曾经静默降级导致卡片功能整体消失且无诊断线索——P0-1 收尾）。

## 15. 测试

- 入口只走 `dev.ps1 -Task test`（basetemp 源码树外）。111 文件 865+ 用例。
- 约定：测试桩的 `list_fn` 等签名要跟实现 kwarg 演进（如 limit）；共享缓存类（`_KB_PROVIDER_CACHE`）测试间要 `.clear()`；`_CANDIDATE_SESSIONS` 有 `clear_music_candidate_sessions()`。
- 各组测试文件独立命名（test_music_candidates_v2 / test_auditfix_runtime_policy / test_affinity_* …），互不碰。

## 16. 排障手册（症状→诊断→处置，全实战沉淀）

| 症状 | 第一步诊断 | 处置 |
|---|---|---|
| 改动"没生效" | 进程启动时间 vs 最后提交时间（Get-Process python） | 重启 bot；确认无第二实例 |
| NapCat 3001 不监听/重复登录 | `Get-Process QQ \| Select Id,StartTime` 查多代际并存 | 提权清场（先杀看门狗父进程再杀 QQ/QQEX/NapCatWinBootMain）→ login-bot.bat；bot 自动重连 |
| NapCat 二维码不刷新 | 日志「未找到对应版本的偏移数据」 | QQ 构建号超出 NapCat 支持表——上游问题；启动后 2 分钟内扫首码 |
| 点歌没有候选卡 | 1) 配置开关 2) 裸歌名精确命中（设计如此）3) 渲染失败日志 | 带限定词查询必出；查 `music candidates card render failed` 日志 |
| 点歌候选/歌曲卡全灰 | 图床 WAF/ORB | 见 §6.4；sinaimg 已兜，新图床照方抓药（直连+curl 极简头） |
| 发布时间差 8 小时 | 该解析器是否产 naive 串 | 契约层已按 +08 解释（media.py _CN_TZ）；新解析器直接给 epoch 或带时区 ISO 最稳 |
| xhs 图片 403 | 签名过期（分钟级）属正常 | 解析→渲染要快；**永远不要剥 URL 的 !后缀/参数** |
| B站 -352/-509 | 波动 IP 风控 | 专栏自动重试；直播已切匿名稳通道；根治=灌 bilibili 登录 cookie |
| QQ 音乐全平台搜不到 | client_search_cp 已死 | 已迁移 musicu.fcg；若再挂先 probe 接口 |
| 卡图无机器人头像 | config.bot_persona_avatar_url | render_card_png 有 config 兜底 |
| pytest 会话收尾崩溃 | 共享 %TEMP% pytest-of-* 循环 symlink | 走 dev.ps1（basetemp 已固定） |
| git push 408/断 | 代理掐大包 | 分片推送；**分支标签同名必须完整 refspec** `refs/heads/v0.0.1-alpha.2:refs/heads/v0.0.1-alpha.2` |
| fetch 报 reference broken | gitdir 外置于 ChatBot_Runtime/git，remote ref 文件损坏 | `git ls-remote` 取正确哈希直写该文件 |
| bash 里 PowerShell `$_` 报错 | Git Bash 吞 $ | 写 .ps1 文件执行；Windows 路径 cygpath -w |
| 源码树出现缓存 | 绕开了 dev.ps1 | PYTHONDONTWRITEBYTECODE=1 + basetemp 外置 |
| mypy/lint 树级残留报错 | 并行会话在途文件 | 先确认归属（git status + 文件域），别人的 WIP 不动、只保证自己文件零错 |

## 17. 硬约束（不可违反）

1. 人格源文件、世界观源文件只读。
2. Runtime 数据（SQLite/FAISS/记忆/Cookie/订阅/媒体缓存/日志/venv）不得删除；清理先归档验证。
3. 密钥永不入库不入聊天（§4.2）。
4. 推送 origin 按用户明确指示执行（本轮 A/B/C 组交接文档约定包含交付后推送）。
5. commit 禁 `git add -A`；共享 index 陷阱自查 `git diff --cached --stat`。
6. 源码树零缓存（§3）。
7. 工作区边界：ChatBot_Runtime / ChatBot_Archive / 上层目录默认不扫描不修改。
8. 人格：说话语气=理性、天然呆、活泼感不过量；失败话术 12 条轮换、无表演腔、不做虚假承诺。

## 18. 并行会话协作规范（本仓库常态）

- 常态 2~3 个 AI 会话并行（当前活跃域：解析+卡片=A、模型渠道+点歌=B、好感度+审计=C、另有视频理解会话）。
- 文件域切分（9.9 版约定）：A=sources/parsers/** + universal_card.html + 卡片管线；B=llm/* + music.py + song_candidates.html + subscribe*；C=character/* + tests。实际已多次互相"顺手"共享文件（bridge.py 被 A/C 先后提交、music.py A/B 先后提交）——**内容一致即无害，提交信息如实描述**。
- 动共享文件前 `git pull`；Edit 工具的 file-modified 检查是最后防线。
- 别人在途的 WIP（未提交的语法错误/mypy 报错）不修、不裹挟、等其自愈（chat.py 曾语法半成品约 20 分钟后自愈）。
- 树级 lint 门禁被别人 WIP 卡住时：机械性可 auto-fix 的顺手修并注明；语义性的留给归属会话。

## 19. 当前已知边界与非缺陷清单

- **mypy 树级残留**：视频理解会话（chat.py:248 MediaAssetRecord、__init__ queue 联合类型）与 B组在途（worker/disconnect_notice/settings）共 7~12 个报错流动中——归属会话收尾，A 组文件零错。
- **平台边界（非缺陷）**：YouTube 无频道总获赞/Tab 数未抓；小红书依赖登录态+风控（图片签名分钟级过期属正常）；B站 AI 总结仅部分视频有；AI 字幕需登录 cookie；NapCat 二维码刷新受 QQ 版本漂移影响（等上游）；浅夜渠道 gemini 套壳嫌疑（实锤，.env 已降权）；酷我搜索接口劣化（候选不可用，单结果走第三方 suyanw）；Spotify 搜索恒 None 占位；B站漫画 twirp TLS 风控不可破；Spotify/Apple 边界见 platforms_music docstring。
- **架构级尾巴（P0/P1）**：FileTransferGateway 统一（仍有 handler 直连 call_api）；订阅/文档导出出站收敛；PersonaContract/WorldEntity/Claim/EvidenceLedger/AnswerPlan 结构化知识架构；claim-based RAG；记忆写入 propose→approve；群聊公共状态；TrustLevel 反注入；ToolCatalog。
- **验收级（P2）**：真实 NapCat poke/反戳；TG 评论树与文件出站；Mail 真机；LangSearch 验收；视觉模型命令全对齐；LLMCallRecord 可观测；生成文件安全扫描；老 Office 转换链。
- **低优先改进点（audit 存量）**：kugou 明文 http 搜索端点；kuwo suyanw 第三方依赖；`点歌模式` 词与路由的边界 UX；universal_card 内少量语义状态色写死（认证金/错误红——语义色不属品牌色违规）。

## 20. 修复史全索引（2026-09-07 → 09-10）

| 日期 | 主题 | 要点 |
|---|---|---|
| 09-07 | alpha.1 收尾 | 统一管线/文件读写/输出整理/安全基线/Wiki 修复/poke；352 tests |
| 09-08 | 测试基建 | basetemp 修复、mail_bridge 竞态 |
| 09-08 | 12 插件硬对比 | 吸收 htmlrender 常驻浏览器/memes 守门；其余 10 项原生胜出 |
| 09-08 | 搜索验收 | Tavily/You 真实 key smoke；TinyFish 端点修正；search-smoke |
| 09-08 | 幂等/恢复 | 事件幂等表、result_unknown 账本 |
| 09-08 | 音乐多候选 | 网易云编号选歌、TTL 会话 |
| 09-08 | parser-lite A | 知乎/豆瓣/TapTap/社区/虎扑 + B站 AI 总结 + UP 获赞 + /bot cookie |
| 09-08 | 防御强化 | 软硬类别/记忆清洗/命令统一 |
| 09-08 | 并行大交付 | 全平台覆盖/搜图/小名/复读检测/说人话/天气兜底/启动闪退修 |
| 09-08 | 实卡修复一 | 点歌三件套/B站作者栏/发布时间到秒/Help 图/TG 图文 |
| 09-08 | 类型修复 | B站 fans/likes int 化 |
| 09-09 | TG 媒体链路 | 本地卡作 photo/语音 OGG/OPUS/help 空文本 |
| 09-09 | 呈现层四断点 | 时间到秒+时区/热评块/专栏标签/候选选歌启用 |
| 09-09 | 三平台解析 | 推特媒体推文/油管 innertube 三层合并/xhs 空 title 兜底 |
| 09-09 | Help 重设计 | 双列网格/分类直查/免费游戏卡/天气卡 |
| 09-09 | key 批次+渠道扩容 | 45 条目 registry/探针 key 修复/health 行动清单/model list 价格列 |
| 09-09 | 渠道+卡 UI+话术 | StarAPI 渠道/视频卡 UI/话术 v2/探针双模式 |
| 09-09 | 路由救急+视觉直传 | 9 个 bot_api_key 字段/vision direct/internal_error 可观测/预算 150s |
| 09-09 | 字幕+LLM 总结 | B站 AI 字幕/油管 captionTracks |
| 09-09 | 私聊无回复+预算 | 发送层丢消息根因/预算耗尽不丢 |
| 09-09 | 渠道化 | 健康巡检/价格选渠道 |
| 09-09 | 实卡反馈二轮 | 作者数据行归位/alpha 裁剪/Help 视口 |
| 09-10 | B组交付 | 延迟择优+巡检参数化+qian-night 重排+候选 Mica 卡+话术 v4+YT @handle 修复 |
| 09-10 | C组交付 | 好感度数值化+审计报告 36 项+浸泡测试+帮助文本 |
| 09-10 | 好感度查询卡 | bot.affinity 能力+affinity_card.html |
| 09-10 | A组解析专项(8dc7ed4) | 封面原图/时区根治/微博修复+访客兑子/专栏直播会员购补齐/竖切横图拼接 image_stitch/ORB 兜子/data URL 内联 |
| 09-10 | 嘉宾卡区+点歌批(ed0fedb) | 嘉宾独立卡区/候选卡不可达根治/QQ musicu.fcg 迁移/pic_str/{size}/渲染告警/VIP 色/双转义 |
| 09-10 | 直播风控规避+死模板清理(db84aae) | 直播主通道切换/专栏重试/Compact 死块删除 |
| 09-10 | naive 契约+点歌二轮(22d561e) | _CN_TZ/limit 透传/酷狗详情富化/render_backend 告警 |
| 09-10 | xhs playwright 兜底+撤剥!回归+时长秒数化(f96d1a1) | 见 §5.4/§5.2；共享 index 裹挟存证 |
| 09-10 | B组 EWMA v2(d5a9f43) | 渠道延迟择优算法 v2 |

## 21. 完成判定（说"完成"前逐条核对）

AC 达成 ∧ 实测通过（真跑，禁编造输出）∧ 无回归（全量 pytest）∧ 影响已控制（只动本域文件）∧ 交付记录同步（handoff/提交信息）。

## 22. 建议下一步（按价值排序）

1. `/bot cookie import bilibili` + `x`（登录态解锁 AI 字幕/订阅推特，缩小 -352 面积）。
2. mypy 树级残留清零（等视频会话收尾后统一清）。
3. xhs/微博图床 ORB 名单按需扩展（新图床灰图→照 §6.4 方针加后缀+实测取回头形态）。
4. FileTransferGateway 统一出站（架构尾巴里价值最高的一个）。
5. 酷我搜索找新的匿名通道（当前候选不可用，静默跳过不影响主链路）。
