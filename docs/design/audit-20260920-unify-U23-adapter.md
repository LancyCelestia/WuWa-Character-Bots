# 席位 U23-ADAPTER —— 多适配器对等性与归属统一（审计日志 + 交付物）

> 术语说明：本文中的 **NapCat** 指 2026-09-18 之前的 QQ 协议端（当时实况记录，保留原文不改写）；现役协议端为 **SnowLuma**，见 [snowluma-setup.md](../snowluma-setup.md)。

> 席位性质：只读审计子代理。工作区 `C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot`。
> 范围：后端 Python 通道侧（OneBot/QQ、Telegram、Mail、Console + SnowLuma 主号 / SnowLuma 学校号双实例）。
> 不查不碰：`webui/`、`domains/render/**` 内部实现、`output/card_render/**`、`theme_tokens.py`、TTS/语音链路。
> 硬禁令：不再派子代理；无 git 写；除本文件外不改任何文件；无 `--write`；无真实网络/LLM/发送；不 kill/启动/重启进程；不碰 8080/3001/3002/8742；不读 `.env` 明文值；`ChatBot_Runtime/` 只读。
> 证据规矩：每条发现七要素 = 严重度｜坐标｜锚点字符串｜根因｜证据｜改法 before→after｜验证命令。禁「可能/大概」。

## 状态板（实时更新）

- [x] 日志骨架落盘
- [ ] 0. 前置阅读（AGENTS 第〇/三部分 + 台账 #19/#20/#26/#33/#34/#35/#36/#42 + U1/U3/U13/U5 结论引用）
- [ ] D1-1 适配器 × 摄取步骤矩阵（每格带坐标 + 锚点）
- [ ] D1-2 能力可达性差异（RouteKind × 通道）与诚实降级判定
- [ ] D1-3 通道专属旁路（mail_adapter / mail_bridge / message_context / scripts/telegram_resilience）
- [ ] D2-1 出站咽喉对等性（回执/UNKNOWN/幂等/part 续发 份数与语义）
- [ ] D2-2 多实例路由 bot_id 传递链完整性
- [ ] D2-3 平台能力差异建模单源性
- [ ] D2-4 失败与降级话术一致性（引用 U12）
- [ ] D3-1 通道件目录归属 + 同概念两处定义
- [ ] D3-2 配置键一致性（含与 U6 os.getenv 交叉点名）
- [ ] D3-3 依赖钉死面现况复核
- [ ] D4 收口清单（按解锁顺序）
- [ ] 未覆盖清单
- [ ] 源码树卫生自查（.pyc/__pycache__/data 计数，备份 %TEMP% 后清零并披露）

## 发现登记表（汇总用，逐条详述见下文各节）

| ID | 严重度 | 一句话 | 坐标 |
|---|---|---|---|
| （待填） | | | |

---

## 0. 前置阅读记录（引用不重证）

本机 `date` 实读 = **2026-09-19 16:51**（任务书/文件名口径 2026-09-20，沿用不改；本席全部坐标/时间戳对应本地钟 09-19 16:4x 起时段，与他席同一口径错位，非本席缺陷）。
开工基线自查（实跑）：`find plugins tests scripts bot.py -name "*.pyc"` → **0**；`find plugins tests scripts -name "__pycache__" -type d` → **0**；`ls -d data` → **不存在**。本席全程用解释器 **`-B`** 标志（吸取 U1 §11 教训：本机 `PYTHONDONTWRITEBYTECODE=1` 拦不住 .pyc）。

### 0.1 同波席位结论引用表（本席不重复取证）

| 引用件 | 本席据其结论之处 |
|---|---|
| U1-INVEST §1.1 | 中央归一函数 = `__init__.py:1274 _incoming_from_nonebot_event`；12 个生产调用点仅 1 个走 `IngressGateway`；根 `message_context.py`/`runtime/ingress.py` 为 PEP 562 垫片、无第二实现 |
| U1 §1.2 | 四项富化（语音转码/TG file_id→字节/引用链反查/合并转发正文）**全库各 1 个生产调用点、只活在 `@chat.handle()`（:7281-7291/:7529）** |
| U1 §2.3 | 全部 NoneBot matcher 注册集中在根 `__init__.py`，**无任何插件域自建 matcher**（正面结论，本席据此把 D1 的「通路」问题收敛到入口内部） |
| U1 U1-21 | **Console 未注册为 NoneBot 适配器**——`bot.py` 实读 `register_adapter` 恰 3 处（:408 OneBotV11 / :409 ResilientTelegram / :483 ResilientMail）；console 是 `domains/ops/smoke/console_chat.py` 自研 REPL、直构 `IncomingMessage` |
| U1 U1-22 | TG `sender_display_name` 恒 None（`first_name` 全树仅 `message_context.py:253` 一处读） |
| U1 U1-23 | `platform`/`adapter` 字面量三分叉（`qq`/`onebot`/`nonebot`）+ `gateway._adapter_name` 自带弱归一 |
| U1 §5.3 | 三套群会话键并存（`group_<gid>_<uid>` / `group:<gid>` / reactions 自建），群上下文恒空已端到端复现 |
| U1 U1-09 | campus = 读事件→拼文本→落库→直投队列四段全复刻，绕过 gate/Review/脱敏/审计 |
| U3 §一 表 | 出站四类出口；完全旁路 = `delete_msg` / 管理告警 / 掉线通知四渠道 / `/mail send` |
| U3 U3-03 | **`unknown_part_confirmer` 生产零接线**（唯一调用点 `__init__.py:1649` 未传）+ `provider_message_id` 在 UNKNOWN 路径从不写入 → 唯一回退路结构不可达 |
| U3 §4.2 | 逐通道 UNKNOWN 能力：OneBot 有 `get_msg` 未注册；Telegram 无按 id 反查 API；Mail `send_mail_from_account` 返回 `None`、`provider_message_id` 恒缺 |
| U3 U3-14 | Mail 出站**两套实现并存**（队列侧 `nonebot.py:494` 回复语义 / 运维侧 `aiosmtplib` 直投主动语义）；ServerChan/PushPlus 不在 `TransportPlatform` 枚举 |
| U3 §十一 | `TransportRegistry.bind_handler` **全树零生产调用 → 全部 transport 条目 status=placeholder**（U3 只做了 grep 取证、显式让渡不成文，**本席接手把它做成正式发现**，见 D2-3） |
| U6 §6.0 | NoneBot 用 `dotenv_values` 纯读文件、**绝不写 `os.environ`** → `os.getenv("BOT_*")` 对 `.env` **恒不生效**；插件内 23 键/31 处直读（本席只做「通道键里哪些命中」的点名，根因不重证） |
| U13 D1 | `campus_store.py:40` 建库黑户（BH8）；`reaction_events` 表级 `event_id` 幂等 |
| U12 | 五池话术与告警抑制（300s）结论本席按引用处理，不重复取证 |

### 0.2 本席与同波席位的边界裁定

- **不重复 U1**：入站摄取「事件→契约」的构造点/富化点/段册（U1 已成文 24 条）。本席 D1 只做 **通道维度**的对等性矩阵与「通道专属旁路件」（`mail_adapter.py`/`mail_bridge.py`/`message_context.py` 双份/`scripts/telegram_resilience.py`）——U1 未看 scripts 侧。
- **不重复 U3**：出站直连点全枚举、feature_gate 吞文案（U3-01/02）、登记表坐标失效（U3-04）。本席 D2 只做 **通道间实现份数与语义差**、**bot_id 多实例路由链**、**TransportRegistry 单源性正式成文**、`unknown_part_confirmer` 的「哪几个通道根本没有确认路径」补完（U3 §4.2 已给逐通道能力，本席补的是**结构缺件计数**）。
- **不碰**：`webui/`、`domains/render/**` 内部、`output/card_render/**`、`theme_tokens.py`、TTS/语音链路。`domains/transport/**`、`domains/*/ingest/telegram_*`、`sender/`、`adapters`、`campus` 通道面 = 本席主战场。

### 0.3 本席解释器纪律（一次性声明，后文不重述）

```
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe -B …
pytest 一律追加  --basetemp="$TEMP/u23-<用途>" -p no:cacheprovider
```
临时脚本一律写工作区内 `%TEMP%/`（该目录为本波次他席已用的约定 scratch 位，见 U3 §十一）。

---

## 1. D1 入站对等性（完成）

### 1.1 适配器 → 中央管线的通路（实读结论，先立事实再列矩阵）

| 通道 | 注册点 | 驱动方式 | 事件类 | 进入中央管线的唯一门 |
|---|---|---|---|---|
| OneBot V11（SnowLuma 主号 3001） | `bot.py:408 driver.register_adapter(OneBotV11Adapter)` | 正向 WS（`ONEBOT_WS_URLS`） | `nonebot.adapters.onebot.v11.event.*` | `__init__.py:4781 chat = on_message(rule=_is_plain_chat_event, priority=50, block=True)` |
| OneBot V11（SnowLuma 学校号 3002） | **同一行注册**（同一 Adapter 实例，多 bot_id） | 正向 WS 第二条 URL（当前 `.env.prod:10` 为注释态 → 生产只有 3001 一条） | 同上 | 同上（无通道专属入口，campus 是旁路，见 U1 U1-09） |
| Telegram | `bot.py:409 driver.register_adapter(ResilientTelegramAdapter)` | 长轮询 getUpdates（韧性层 `scripts/telegram_resilience.py:118-137`） | `nonebot.adapters.telegram.event.*` | 同 `chat`；`message` 段由适配器 `event.py:147-166 __parse_event` 生成 |
| Mail | `bot.py:483 driver.register_adapter(ResilientMailAdapter)`（481 行导入顶层垫片，真身 `domains/transport/mail/mail_adapter.py:143`） | IMAP 自轮询 3s（`mail_adapter.py:229-231`） | `QuietMailMessageEvent`（`mail_adapter.py:120`，伪装成 `NewMailMessageEvent.__module__`，见 `:128`） | `chat`（`_is_plain_chat_event:4738` 的 mail 分支）+ `mail_notice = on_message(rule=_is_mail_event, priority=9, block=False)`（`:4780`） |
| Console | **未注册**（`bot.py` 实读 `register_adapter` 恰 3 处，锚点 `driver.register_adapter(ResilientMailAdapter)`=483） | `domains/ops/smoke/console_chat.py` 自研 REPL，`_build_runtime` 手装 `InMemorySendQueue`+`RuntimePipeline`（`:217-219`） | 无（不经适配器） | 无：`console_chat.py:488 pipeline.handle(...)` + `:492 print(text)` |

- 「QQ 的 WS 与 webhook 两条入口是否同一入口」= **只有一条**：`bot.py:408` 注册 OneBotV11Adapter，`pyproject.toml`/`bot.py` 无 `ONEBOT_HTTP_*`/webhook 接收配置消费点，正向 WS 为唯一摄取面；8080 属 SnowLuma 侧反向 HTTP（AGENTS 第〇部分口径），本席不再取证（U1 §2.3 同结论）。
- `nonebot.load_from_toml` **不注册适配器**：venv `nonebot/plugin/load.py:135-159` 函数体只取 `nonebot_data.get("plugins")` 与 `plugin_dirs` 交 `load_all_plugins`，`[tool.nonebot.adapters]` 全程未被读取 → `pyproject.toml:61-63` 声明的 `nonebot-adapter-console` 对 `python bot.py` 启动路径零效果（见 U23-03）。

### 1.2 适配器 × 摄取步骤矩阵（空格=该通道缺这步；「可达」列为 U23-01/U23-02 的直接证据）

| 摄取步骤 | 实现坐标（真身） | OneBot/QQ | Telegram | Mail | Console |
|---|---|---|---|---|---|
| 段提取 | `__init__.py:550 _extract_onebot_raw_segments`，锚点 `get_message = getattr(event, "get_message", None)`；调用点 `:7279` | ✅ `image/record/video/face/at/forward` | ⚠️ 只出 `text/photo/voice/audio/document/animation/sticker/video_note`（探针实跑，见 U23-01 证据） | ❌ 适配器 `Mail` 无 message 段 → `:1352` 兜底造 1 条空 text 段 | ✅ 直接构造 |
| 段归一（跨适配器标签） | `domains/chat_reply/ingest/message_context.py:57-85`，锚点 `"image",\n "photo",` | ✅ | ✅ photo/voice/audio/document 全部有中文标签 | ❌（无段可归） | ✅ |
| 聊天门放行（纯媒体） | `__init__.py:4752-4760`，锚点 `contains_visual_message_segments(raw_segments)`；白名单 `:669` `visual_types = {"image", "face", "mface", "marketface", "sticker", "video"}` | ✅ | ❌ **`photo`/`animation`/`video_note`/`document` 不在表内** → U23-01 | ✅（`:4738` 专用分支按 subject/正文放行） | n/a |
| 语音预转码（SILK→mp3） | `__init__.py:7280-7281`，锚点 `switches.enabled("bot.ingress.audio_transcode")` + `_transcode_record_segments` | ✅ `record` | ❌ TG 段名是 `voice`/`audio`，`_transcode_record_segments` 按 `record` 命中（`:7280` 的 any 判定只认 `record`） | ❌ | ❌ 不在 chat 链 |
| TG file_id→字节富化 | `domains/media/ingest/telegram_media.py:53` 锚点 `{"photo", "sticker", "animation", "video_note", "voice", "audio"}`；调用点 `__init__.py:7285-7286` | n/a | ⚠️ 实现覆盖 6 类，但**只在 `@chat.handle()` 内调用**，而 photo-only 消息已被上游门禁挡掉（U23-01）→ 结构不可达 | ❌ | ❌ |
| 引用链递归反查（5 层 + get_msg） | `__init__.py:7289-7292` 锚点 `resolved_chain = await collect_reply_chain_async(` → `_make_onebot_reply_lookup(bot)`（OneBot 专属 API） | ✅ | ⚠️ 同步链 `message_context.py:366` 读 `reply_to_message` 可解，异步反查用 OneBot `get_msg` → TG 分支不发请求 | ❌ | ❌ |
| 合并转发正文反查 | `__init__.py:1054` 锚点 `call_api("get_forward_msg", message_id=one_id)` | ✅ | ❌ 无对应实现（TG 无 forward 段类型） | ❌ | ❌ |
| 发送者显示名填充 | `__init__.py:1459-1469` 锚点 `sender_card = str(getattr(onebot_sender, "card", None)` | ✅ card/nickname/role/title/level | ❌ 恒 None（U1 U1-22 已证 `first_name` 全树仅 `message_context.py:253` 读） | ❌（`sender.name` 只在 `mail_bridge.py:377` 用于提醒文案，不进契约） | ❌ 写死 `"console-user"` |
| 群标题 | `__init__.py:1468` 锚点 `getattr(event, "group_title", None)` | ✅（NapCat 扩展字段） | ❌ TG 是 `chat.title`，未取 | n/a | n/a |
| session 键生成 | `__init__.py:1317/1328/1341`（mail=`f"email:{sender_id}"`、TG/QQ=`event.get_session_id()`） | ✅ `group_<gid>_<uid>`/`private` | ✅ 与 QQ 同族但形态不同（TG `get_session_id` 产 `group_<id>_<uid>`? 见 U1 §5.3 三套并存） | ✅ 自造 `email:` 前缀 | ✅ 自造 `console:repl` |
| 入站幂等 | 队列层 `dedupe_key`（`queue.py:459` 锚点 `ON CONFLICT(dedupe_key) DO NOTHING`）+ mail 专属 `mail_event_dedupe_id`（`__init__.py:5800` 附近，锚点 `mail_id, mail_id_is_fallback = mail_event_dedupe_id(event)`） | ⚠️ 无入站事件级幂等（靠出站 dedupe_key 兜） | ⚠️ 同 | ✅ 显式 `claim_notification/claim_reply`（`mail_bridge.py:184/196`） | n/a |

**计数**：矩阵 12 步 × 4 通道 = 48 格，其中 ✅ 26、⚠️（部分/条件可达）5、❌ 12、n/a 5。

### 1.3 U23-01｜Critical｜TG 纯图/纯文档消息被聊天门禁判「空消息」丢弃，四段富化结构不可达，且注释反向声称已覆盖

- **坐标**：`plugins/bot_unified_runtime/__init__.py:663-671`（判据函数）、`:4752-4760`（门禁）、`:7285-7286`（受益者）；`domains/chat_reply/runtime/base_router.py:709`（落 IGNORE）。
- **锚点字符串**：`visual_types = {"image", "face", "mface", "marketface", "sticker", "video"}` / `contains_visual_message_segments(raw_segments)` / `return RouteDecision(RouteKind.IGNORE, "bot.ignore", 999, "空消息")`。
- **根因**：段类型词表按 OneBot 字面量硬编码，未收录 Telegram 协议段名。同一概念（「可看的图」）在全树有 **6 份各自维护的集合**，其中 5 份都收了 `photo`，唯独做路由门禁的这份没收：

  | 集合 | 坐标 | 含 `photo` | 含 `animation` | 含 `document` |
  |---|---|---|---|---|
  | 聊天门禁 visual_types | `__init__.py:669` | ❌ | ❌ | ❌ |
  | 段归一 media kinds | `domains/chat_reply/ingest/message_context.py:57-68` | ✅ | ✅ | ✅(`file`) |
  | 视觉识别 `_IMAGE_SEGMENT_TYPES` | `domains/media/ingest/vision_describe.py:59-66` | ✅ | ✅ | ❌ |
  | 媒体归档 `_MEDIA_SEGMENT_TYPES` | `domains/media/capabilities/media_archive.py:68` | ✅ | ✅ | ❌ |
  | TG 富化支持面 | `domains/media/ingest/telegram_media.py:53` | ✅ | ✅ | ❌ |
  | 回复媒体反查 | `__init__.py:8115-8123` | ✅ | ✅ | ❌ |
  | 表情库吸收 | `domains/meme/sources/meme_library_listener.py:61` | ❌ | ❌ | ❌ |

- **证据**（离线探针，不触网不发送）：`%TEMP%/u23_tg_segment_probe4.py` 用真实适配器路径 `MessageEvent.parse_event(payload)`（锚点 `__parse_event`，venv `nonebot/adapters/telegram/event.py:147-166`）+ 内联复刻 `__init__.py:550-569` 抽取逻辑，实跑输出：
  ```
  --- photo only: GroupMessageEvent
      types  : ['photo']
      plain  : ''
  --- voice only: GroupMessageEvent
      types  : ['voice']
      plain  : ''
  --- document only: GroupMessageEvent
      types  : ['document']
      plain  : ''
  ```
  `plain=''` 且 `photo`/`document` 不在 visual/audio 白名单 → `_is_plain_chat_event` 不特放行 → 路由拿空文本 → `base_router.py:709` 判 IGNORE → `@chat.handle()` 不执行 → `enrich_telegram_file_segments`（`telegram_media.py` 已明确支持 `photo`）与视觉/ASR 分支永不被调用。`voice`/`audio` 因 `AUDIO_SEGMENT_TYPES`（`__init__.py:678`）含该名而放行 → **同一通道内语音可达、图片不可达**，是词表分叉的直接后果而非有意设计。
- **诚实标注缺口**：`__init__.py:4756-4759` 注释写「纯媒体/转发消息走聊天链路：这些消息的 plain_text 往往为空，会被路由判 IGNORE；若不在这里放行，视觉理解、ASR 与合并转发正文反查……都永远跑不到」——该说明声称已解决，实际只覆盖 OneBot 字面量；`vision_describe.py:56-58` 注释更直接记录「此前缺 animation/sticker/photo/video_note，Telegram 侧这些一律只剩占位文本，评审需求 4」——同一缺陷在识别层已修，路由层漏修。全树无一处声明「TG 图片不支持」。
- **改法 before→after**：
  before（`__init__.py:669`，局部字面量）
  `visual_types = {"image", "face", "mface", "marketface", "sticker", "video"}`
  after（单一词表源，路由/识别/归档/富化四处共读）
  在 `domains/core/contracts/` 或 `domains/chat_reply/ingest/message_context.py` 增设 `VISUAL/AUDIO/FORWARD_SEGMENT_TYPES` 一份并集常量（`image|photo|sticker|mface|face|marketface|animation|video|video_note`），`:669/:678/:684`、`vision_describe.py:59`、`media_archive.py:68`、`meme_library_listener.py:61` 全部改 import；本席不实施。
- **验证命令**：
  `PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe -B "%TEMP%/u23_tg_segment_probe4.py"`（词表收口后应显示 `photo` 命中 visual 判定）；
  `PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe -B -m pytest tests/test_media_inputs.py tests/test_vision_describe.py -k telegram --basetemp="$TEMP/r23-u23-01" -p no:cacheprovider`
  （实跑前须补一条「TG photo-only → `_is_plain_chat_event` 为 True」的回归锁，现树内无此锁：`grep -c "photo" tests/test_reply_chain_recursion.py` 见 §1.6）。
- **生产影响边界**：离线判据，未重启 bot；现网 TG 通道本行为与改动前一致。

### 1.4 U23-02｜High｜四项入站富化只挂在 `@chat.handle()` 一处，其余 10 个摄取点零富化

- **坐标**：`__init__.py:7279-7301`（唯一富化点，锚点 `enrich_telegram_file_segments(bot, event, event_segments)`）；对照 10 个裸调用点：`:5566`（image_search）、`:5795`（mail_notice）、`:7745`（content 链接解析）、`:7813`（music）、`:7870`、`:7921`（工厂函数 `_register_command_matcher` 体内，覆盖 wiki/moegirl/epic/weather/market/stocks/fx/commodities/bond/northbound/divination/news/randpic/tts/reminder/daily_assist/eat/affinity）、`:7976`（group_info）、`:8132`（media_archive）、`:8191`（meme_library）、`:8505`（moegirl_question）。
- **锚点字符串**：`message = _incoming_from_nonebot_event(\n            event,\n            bot_id=str(getattr(bot, "self_id", "unknown")),\n            feature_enabled=` （该形态在 10 处逐字相同，无 `segments=`/`reply_chain=` 两个关键字）。
- **根因**：富化以「先算好再传参」的形式做在 chat handler 内（函数本体保持同步纯函数，见 `:1281` 签名 `segments: list[dict[str, Any]] | None = None`），没有把「富化」抽成通道无关的摄取阶段，于是每加一个 matcher 就重抄一遍裸调用。
- **证据**：`grep -c "_incoming_from_nonebot_event(" plugins/bot_unified_runtime/__init__.py` = 11 个调用点 +1 处定义；`grep -n "segments=event_segments" plugins/bot_unified_runtime/__init__.py` 仅 `:7298` 命中 1 处；`grep -n "reply_chain=resolved_chain"` 仅 `:7299` 命中 1 处。U1 §1.2 从「生产调用点」口径给出同数（本席为「富化参数」口径，二者不冲突）。
  后果可静态判定：`media_archive`（`:8132`）拿到的 `raw_segments` 未经 `telegram_media.py` 落字节，TG 侧归档请求拿到的 `photo.data["file"]` 仍是 file_id；`content`（`:7745`）与 `image_search`（`:5566`）同理拿不到深引用链（`collect_reply_chain` 同步版 `message_context.py:366` 只在事件自带 `reply_to_message` 时可解）。
- **改法 before→after**：before 每个 matcher 体内自调 `_incoming_from_nonebot_event(event, bot_id=..., feature_enabled=...)`；after 单一入口 `await IngressGateway(...).from_event_async(event, bot, enrichers=[audio, tg_media, reply_chain])`，matcher 只消费结果（`IngressGateway` 已在 `:2531` 有一个调用点，属可复用中央入口，不新建第三套）。
- **验证命令**：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe -B -m pytest tests -k "ingest or reply_chain or telegram_media" --basetemp="$TEMP/r23-u23-02" -p no:cacheprovider`；收口门：`grep -c "segments=event_segments" plugins/bot_unified_runtime/__init__.py` 应 ≥ 调用点数，现值 1。

### 1.5 U23-03｜Medium｜Console 通道三处互相矛盾：声明注册但从不注册、事件被归成 QQ、出站有分支却在队列路径必炸

- **坐标 + 锚点**：
  1. `pyproject.toml:61-63` 锚点 `nonebot-adapter-console = [` 声明适配器；venv `nonebot/plugin/load.py:135-159`（`load_from_toml` 函数体只读 `plugins`/`plugin_dirs`）→ 声明不生效；`bot.py` 实读 `driver.register_adapter` 仅 408/409/483 三处，无 Console。
  2. `__init__.py:250` 锚点 `supported_adapters={"~onebot.v11", "~console", "~mail", "~telegram"}` —— 插件自报支持 console，与 (1) 相反；一旦有人补上 `register_adapter`，`:4726-4733 _event_adapter_kind`（锚点 `return "onebot"` 为 else 分支）与 `:1292-1297`（锚点 `normalized_adapter = "onebot v11"`）会把 console 事件**静默归成 QQ**：console 事件 `type(event).__module__` = `nonebot.adapters.console.event`，两条嗅探都不命中 → `platform="qq"`、`adapter="nonebot"` → 出站走 `send_onebot_v11`。
  3. `domains/transport/sender/nonebot.py:351-353` 锚点 `elif adapter_name == "console":` 有 console 出站分支，但队列 worker 路径传 `event=None`（`__init__.py:1647` 锚点 `send_nonebot_message(bot, None, send_request)`）→ 落到 `nonebot.py:485-489` 锚点 `raise RuntimeError("adapter does not expose send_to")`；venv `nonebot/adapters/console/bot.py:70-97` 实读只有 `send`/`send_private_message`/`send_message`，**无 `send_to`** → 队列态 console 请求永久 `FAILED_RETRYABLE` 直到 `queue.py:79 _BOT_UNAVAILABLE_MAX_AGE_SECONDS = 1800.0` 被清理。
- **根因**：console 既被当作「未注册的适配器」被文档记录（U1 U1-21），又被当作「支持的一等通道」写进插件元数据与出站分支；三处各自成立、无一处校验。
- **证据**：`grep -rn "register_adapter" bot.py` = 3 命中（408/409/483），无 console；`grep -c "send_to" ../ChatBot_Runtime/venv/Lib/site-packages/nonebot/adapters/console/bot.py` = 0（mail=1 at `mail/bot.py:124`、telegram=1 at `telegram/bot.py:113`、onebot 走自有 sender）。
- **诚实标注判定**：AGENTS 只记「Console 适配器」存在，未记「出站 console 分支是死分支」；`supported_adapters` 反而给出反向信号 → 属**不诚实降级**。
- **改法 before→after**：before 三处各说各话；after 二选一——(a) 承认 console 非通道：删 `:250` 的 `"~console"` 与 `nonebot.py:351-353` 分支，并把 `console_chat.py` 明确登记为「离线自测 REPL，非第四通道」；(b) 升格为一等通道：`bot.py` 注册 Console adapter + 两条嗅探函数加 console 分支 + 队列路径给 console 补 `send_to` 等价物。本席倾向 (a)（现网零依赖 console 投递），裁决权在用户。
- **验证命令**：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe -B -m pytest tests/test_unified_gateways.py tests/test_console_chat*.py --basetemp="$TEMP/r23-u23-03" -p no:cacheprovider`（现树内 `tests/` 是否有 console_chat 专件见 §1.6 未覆盖清单）。

### 1.6 U23-04｜Medium｜`platform` 字面量在能力层用错值：`meme.py` 的 QQ 兜底分支生产恒不执行，被 30 处测试同义掩盖

- **坐标**：`plugins/bot_unified_runtime/domains/meme/capabilities/meme.py:96`；真值来源 `__init__.py:1342-1343`（锚点 `platform = "qq"` / `adapter = "nonebot"`）；唯一写 `"onebot"` 的生产点 `__init__.py:1836`（锚点 `platform="onebot",`，属「历史上的今天」推送自造 IncomingMessage）。
- **根因**：`IncomingMessage.platform` 是无约束自由串（`domains/core/contracts/runtime.py:123` 锚点 `platform: str`，无枚举/无 validator），能力层按记忆比对字面量。
- **证据**：`grep -rn 'platform="onebot"' plugins/ --include="*.py"` = 1 命中（`:1836`）；`grep -rn 'platform="onebot"' tests/ | wc -l` = 30；`grep -n "== \"onebot\"" plugins/ -r --include="*.py"` 在能力层仅 `meme.py:96` 一处。故 `meme.py:96` 的「无图时用发送者 QQ 头像兜底」在生产 QQ 消息上恒 False（现网表现＝表情包生成拿不到默认头像来源）；测试用 `platform="onebot"` 构造夹具（`tests/test_meme_image_input.py:39` 锚点 `adapter="onebot.v11" if platform == "onebot" else platform`）→ 断言通过而生产失效，是**契约层测试与生产字面量脱钩**的范式性例子。
- **改法 before→after**：before `if not sources and message.platform == "onebot":`；after `if not sources and message.session_type is not SessionType.EMAIL and message.platform in QQ_PLATFORM_ALIASES:`（或直接收口成 `contracts` 里的 `Platform` 枚举 + 迁移 30 处测试夹具到 `"qq"`）。
- **验证命令**：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe -B -m pytest tests/test_meme_image_input.py --basetemp="$TEMP/r23-u23-04" -p no:cacheprovider`；收口门：`grep -rn 'platform="onebot"' tests/ | wc -l` 应为 0。

### 1.7 U23-05｜Medium｜通道名/适配器名六份归一器并存，且各自认得的字面量集合不同（U1 U1-23 的通道维度补强）

- **坐标**（6 份，全部实读）：
  | # | 函数/点 | 认得的字面量 | 归一后的取值 |
  |---|---|---|---|
  | 1 | `__init__.py:1285-1297 _incoming_from_nonebot_event`（锚点 `normalized_adapter = "onebot v11"`） | 模块名嗅探 `.telegram`/`.mail` | 内部 `onebot v11`（带空格），对外 `platform=qq`/`adapter=nonebot` |
  | 2 | `__init__.py:4726-4733 _event_adapter_kind`（锚点 `return "onebot"`） | 模块名嗅探 | `telegram`/`mail`/`onebot` |
  | 3 | `__init__.py:1522-1533 _normalize_adapter_name`（锚点 `if "console" in normalized:`） | `onebot`/`nonebot`/`qq`/`console`/… | `onebot`/`telegram`/`mail`/`console`（唯一认 console 的） |
  | 4 | `__init__.py:7272-7273`（chat handler 内联三元，锚点 `platform=("telegram" if ".telegram" in event_module`） | 模块名嗅探 | adapter 用 `nonebot`、platform 用 `qq`（同一函数返回两个不同口径） |
  | 5 | `domains/transport/sender/gateway.py:23-28 _adapter_name`（锚点 `adapter_name in {"onebot", "onebot v11"}`） | `get_name()` 原样小写 | 只有 `onebot`/`onebot v11` 走 OneBot 发件器 |
  | 6 | `domains/transport/sender/nonebot.py:273-278 _adapter_name` + `domains/transport/mail/mail_bridge.py` 同名 `_adapter_name`（锚点 `if _adapter_name(bot) == "mail" and str(getattr(bot, "self_id"`） | `get_name()` **不归一**（`:277 return str(get_name())`，大小写敏感） | 与 #3 语义不同：`"Mail"` 传入即不等于 `"mail"` |
- **证据**：6 个定义点 `grep -n "def _normalize_adapter_name\|def _adapter_name\|def _event_adapter_kind\|def _bot_adapter_name" -r plugins/` = 5 定义 + `:7272` 内联 = 6 份实现；`__init__.py:5795-5799` 传的是 `adapter_name="Mail"`（大写 M），只有 #1/#3 会 `.lower()`，#6 不会。
- **影响**：新增通道/新增实例时需要同步 6 处，任一处漏改即产生「同一消息在不同层被认成不同平台」的静默漂移（U23-01/U23-04 都是同一模式的受害者）。
- **改法**：`contracts` 增设 `Platform`/`AdapterName` 枚举 + 唯一 `resolve_platform(bot_or_event)`，六处改 import；`__plugin_meta__.supported_adapters` 与注册表由同一份常量派生（治 U23-03 第 2 条）。
- **验证命令**：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe -B -m pytest tests/test_transport_identity*.py tests/test_doc_sync_gates.py --basetemp="$TEMP/r23-u23-05" -p no:cacheprovider`。

### 1.8 D1-3 通道专属旁路件逐条判定

| 件 | 真身坐标 | 判定 | 七要素发现号 |
|---|---|---|---|
| 顶层 `mail_adapter.py`（7 行）/ `mail_bridge.py`（3 行） | 星号 re-export → `domains/transport/mail/{mail_adapter,mail_bridge}.py`；`bot.py:481` 仍从垫片导入 | **不是旁路**（无第二实现），但违反「结论落真身」的迁移收口：星号导出无 `__all__` 约束 | U23-06 |
| `mail_bridge.py:312 send_mail_from_account` / `:351 notify_telegram_admins` | 真身内直取 bot 对象发信/发 TG，不经 SendQueue/Review/plain_text 脱敏 | **旁路**（主动语义出站） | U23-07 |
| `message_context.py`（顶层 18 行） | PEP 562 `__getattr__` 活转发到 `domains/chat_reply/ingest/message_context.py`，锚点 `_CANONICAL = "plugins.bot_unified_runtime.domains.chat_reply.ingest.message_context"` | **无重复定义**（与 U1 §1.1 一致） | — |
| `scripts/telegram_resilience.py` | 被 `bot.py:320-328` import（锚点 `from scripts.telegram_resilience import (`），只在子类里重试只读 `get_updates`（`:136` 锚点 `if api in {"get_updates", "getUpdates"}:`），不发消息、不碰 offset | **正面：不是旁路**。AGENTS「产出 TG 断网话术」口径不准——它产出的是 **logger 行**（`:92/:106/:115`），不是用户话术；真正的用户面在 `domains/ops/monitor/disconnect_notice.py` | U23-08 |
| `domains/ops/smoke/console_chat.py` 751 行自装配 | `:217-219` 手建 `InMemorySendQueue`+`RuntimePipeline`；`:103` 从旧路径 `runtime.pipeline` 导入（真身 `domains/chat_reply/runtime/pipeline.py`） | **第二装配根**（生产 `__init__.py:2512+` 之外的平行组合），漂移风险；属 D3-1 目录归属问题 | U23-09 |

### 1.9 D1 未覆盖清单（诚实登记）

- TG `ChannelPostEvent`（频道帖）与 `chat_type == "channel"` 的摄取分支只在 `:1330` 判 `session_id.startswith("channel_")`，未实跑验证适配器实际 `get_session_id()` 取值形态（需真实 payload，禁触网 → 未取证）。
- `tests/` 内是否有 console 专属测试件、覆盖度多少：未枚举。
- Mail 事件的 `get_plaintext()` 富文本/附件正文抽取质量：未取证（属 `sources/parsers` 面，非通道契约）。
- TG 台账 #2「正文嵌套块级元素早停」：本席不重复取证，亦未验证其在 `photo` caption 路径是否同现。
- SnowLuma 学校号双实例**同时在线**的选路正确性：无第二实例在跑，离线不可证（D2-2 以静态取证给结论，重启后需 `scripts/` live 复跑）。
- 入站幂等：QQ/TG 是否有事件级重复投递防护（如 offset 重放、SnowLuma 重发同 message_id）→ 静态只见出站 `dedupe_key`，入站无表；「无」是否等于缺陷需产品裁定（D4 列出）。
