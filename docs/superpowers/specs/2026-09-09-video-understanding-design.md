# 视频理解系统设计（Media Registry + 前置管道 + 人格化守则）

日期：2026-09-09
状态：待用户确认后实施
分支基线：v0.0.1-alpha.2

## 1. 背景与目标

场景：用户发链接 → 机器人解析并发出视频（或用户直接发视频/录屏）→ 用户回复该视频提问
（如"这个视频里面是什么"）→ 机器人综合**画面、声音、CC/SRT 字幕、解析元数据**，
以**自己的人格口吻**回答，而不是机械复读"视频内容总结："。

目标覆盖三类视频来源：

1. 机器人自己发出/解析下载的视频（bot_sent）；
2. 用户直接发出的视频与录屏（user_sent）；
3. 只解析未下载的平台视频（parsed_only，P2 起按需补下载）。

非目标：不做去水印/导出原图等媒体处理；不改动卡片 UI（design-system 规范本次不涉及）；
不做弹幕内容抓取。

## 2. 现状与缺口（证据）

| # | 现状 | 证据 |
|---|---|---|
| 1 | 回复引用只取纯文本，被引用视频内容完全丢失；reply 段仅含 message_id | `plugins/bot_unified_runtime/__init__.py:775-790`（`_incoming_from_nonebot_event`）；`message_context.py::_flatten` 无 reply 分支 |
| 2 | `describe_video` 只处理当前消息自带 video 段：ffmpeg 抽 4 帧 → 单次 VLM 摘要，结果用完即弃 | `sources/vision_describe.py:216-235, 535-595`；调用点 `capabilities/chat.py:1703-1722` |
| 3 | 视频无音轨分析；`transcribe.py` 仅处理 record 语音段 | `sources/transcribe.py:34`（`_RECORD_SEGMENT_TYPES={"record"}`） |
| 4 | YouTube（innertube json3）与 B 站（WBI API，AI 字幕需 cookie）解析时已抓 ≤3000 字字幕存 `content.platform_extra["subtitle"]`，但只在内存，卡片仅消费 600 字摘录 | `sources/parsers/platforms_generic.py:849-892, 1237-1241`；`platforms_bilibili.py:208-266, 455-461`；`capabilities/content_parser.py:784-788` |
| 5 | 发出视频的 message_id 与本地文件无关联记录：receipts DB 默认关闭，audit 只写 `[internal]`；parse_history 无 message_id/URL 索引 | `sender/receipts.py:32,67`；`sources/parse_history.py`；`__init__.py:1575-1576` |
| 6 | 会话历史 `conversation_turns` 仅 role/text/created_at/kind，无媒体引用；识别结果不进历史 → 下一轮追问无从谈起 | `character/history.py:416-459`；`contracts/character.py:50-60`；历史写入的是 `message.plain_text`（`__init__.py:1337`） |
| 7 | 识别结果以 `[视频识别结果（不可信上下文）]` 拼进用户消息后全靠模型自觉，无"以人格口吻讲媒体"的指令 | `capabilities/chat.py:1722`；prompt 组装 `build_chat_prompt_with_diagnostics`（chat.py:657-853） |
| 8 | 源码无"正在读取视频，请稍候"进度提示，链路全串行，视频分析期间用户干等 | 全仓 grep 无此文案；chat.py:1666-1750 串行识别 |
| 9 | `BOT_ASR_ENABLED` 不在 `SETTABLE_KEYS` 白名单，transcribe.py 的运行时热开关永远不生效（顺手修复项） | `runtime/settings.py:284-320`；`sources/transcribe.py:135` |
| 10 | 下载文件留 `data/downloads` 7 天/2GiB 配额清理 → bot 发过的视频文件短期内仍在盘上，可复用做分析 | `sources/downloader.py:549-557`；`runtime/cache_policy.py:17-70`；`config.py:385-386` |

关键推论：**"对视频追问"不是加强识别，而是缺一条 message_id → 文件/字幕/简报 的关联记忆**，
以及**简报缓存与人格化出声规则**。

## 3. 方案选型

- **方案 A（采纳）：媒体档案库 + 前置管道**。保持"消息进来 → LLM 前完成感知 → 注入 prompt →
  人格模型出声"的现有架构；新增 SQLite MediaRegistry 关联 message_id ↔ 文件 ↔ 元数据 ↔ 简报；
  追问按 message_id 反查命中缓存。与现有 vision/ASR 的"未配置零开销跳过、失败不阻断"哲学一致。
- 方案 B（否决）：把"看视频"暴露为 LLM 工具调用。现有 tool loop 仅在联网意图 + MCP 可用时开启
  （chat.py:1985-1990），视频分析 30s+ 会撞 deadline，模型也可能不调用。
- 方案 C（降为 P3 可选）：视频原文件直传原生多模态模型（Gemini/GLM-4V-Plus 等）。按模型 tags
  定向开启，不做主路径。

## 4. 详细设计

### 4.1 MediaRegistry（新文件 `character/media_registry.py`）

仿 `character/history.py` 的 SQLite 模式，库文件 `data/media_registry.sqlite3`
（经 `scripts/runtime_paths.py` 的 runtime_path 映射到外置运行时数据目录）。

```python
class MediaAssetRecord(StrictBaseModel):
    media_id: str            # uuid4
    chat_message_id: str     # 锚点：bot_sent=发送回执 provider_message_id；user_sent=IncomingMessage.message_id
    session_id: str
    source_kind: str         # bot_sent | user_sent | parsed_only
    platform: str = ""
    item_id: str = ""
    canonical_url: str = ""
    title: str = ""
    creator_name: str = ""
    duration_ms: int | None = None
    local_path: str = ""     # data/downloads 文件；user_sent 为 NapCat 落盘路径；parsed_only 为空
    subtitle_text: str = ""  # 平台 CC 字幕全文（≤3000 字）
    brief_text: str = ""     # 感知简报，生成后回写
    brief_signals: str = ""  # JSON {"frames":bool,"asr":bool,"subtitle":bool,"metadata":bool}
    created_at: int
    last_accessed_at: int

class SQLiteMediaRegistry:
    register(record) -> str                       # 同 chat_message_id+session 重复时复用并更新
    lookup_by_message_id(message_id) -> MediaAssetRecord | None
    lookup_recent_in_session(session_id, within_seconds) -> MediaAssetRecord | None   # P2 模糊追问
    update_brief(media_id, brief_text, brief_signals)
    touch(media_id)                               # 刷新 last_accessed_at
    prune(now, ttl_seconds, max_rows)             # TTL + FIFO，写入时顺带触发
```

容量：TTL 7 天（与 `bot_download_cache_max_age_days` 对齐）+ 5000 行 FIFO。
`prune` 在写入时顺带执行（无后台任务），与 `cache_policy.enforce_quota` 同风格。

### 4.2 三类来源的捕获点

1. **bot_sent**：`CapabilityResult` 的 video part 增加 `meta` 字典
   （platform/item_id/canonical_url/title/creator/duration_ms/subtitle_text —— content_parser 与
   download 能力在解析时手里就有 ParsedContent，`subtitle` 取自 `content.platform_extra`）。
   在 `__init__.py::_deliver_transport_send_request` 成功回执处（`transport_receipt` 事件附近），
   video part 带本地路径且 `receipt.provider_message_id` 存在 → `registry.register(source_kind="bot_sent")`。
   不需要开启 receipts DB。
2. **user_sent**：chat 能力检测到当前消息 video 段并执行分析时，用 `IncomingMessage.message_id`
   写档案（`local_path` = `extract_video_source` 解析出的本机路径）。
3. **parsed_only（P2）**：解析成功即写档案（无文件、有字幕与元数据）；回复卡片追问时走
   `/bot download` 同款下载流程补文件再分析。

### 4.3 追问触发解析（`capabilities/chat.py`，组装 composed_query 之前）

优先级从高到低：

1. `reply_to_message_id` 在 Registry 命中：
   - 简报新鲜（`created_at` 起 7 天内）→ 直接注入缓存简报并 `touch`；
   - 有档案无简报且 `local_path` 存在 → 现场生成简报并回写；
   - 命中但无文件（parsed_only，P1）→ 仅注入字幕+元数据文本简报。
2. 当前消息自带 video 段 → 编排器分析（现有行为升级），同时写 user_sent 档案。
3. （P2）reply 未命中（回复别人发的视频）→ 调 NapCat `get_msg` / `get_video` 按 message_id
   取视频文件 → 存入下载缓存目录 → 分析；失败静默降级为无媒体上下文。
4. （P2，开关默认关）无回复但文本含"这视频/刚才那个视频/上面的视频"且会话 10 分钟内有档案 →
   `lookup_recent_in_session` 取最近档案。

policy gate 触发规则**不变**：white2 仍需硬 @/命令（NoneBot 对"回复机器人的消息"通常置
`to_me`，实施时以 `test_white2_strict_mention` 回归验证，不放松门槛）。

### 4.4 编排器（新文件 `sources/video_understanding.py`）

```python
@dataclass
class VideoBrief:
    text: str          # 材料式简报
    signals: dict[str, bool]

def build_video_brief(config, *, vision_provider, asr_provider,
                      video_source, subtitle_text="", metadata_text="",
                      question="", deadline_seconds=45.0) -> VideoBrief: ...
```

- **P1（串行，零新ffmpeg工作）**：
  复用 `_extract_video_frames`（帧数 4 → `bot_video_max_frames`=8）→ 帧图 + CC 字幕 + 元数据
  （标题/UP主/时长/链接）+ 用户问题 合并为**一次** VLM 调用；VLM prompt 在现有三行格式
  （内容/文字/细节）基础上增加"声音"行（占位"未分析"）。VLM 失败 → 简报退化为字幕+元数据纯文本。
  CC 字幕是解析时免费拿到的信号，P1 就带上。
- **P2（并行 + 音轨）**：线程池并行跑 ffmpeg 抽音轨（`-vn -ac 1 -ar 16000` mp3，截前
  `bot_video_asr_max_seconds`=180s，超 20MB 放弃，复用 transcribe 的 ASR provider）与抽帧；
  ASR 与 VLM 并发请求；`deadline_seconds` 硬预算到点用已完成信号合成简报。ASR 返回空 →
  `signals["asr"]=False`，简报注明"没有听清人声"。
- **P2 附加**：本地文件含内嵌字幕轨（mov_text/srt）时 `ffmpeg -map 0:s:0 -f srt` 抽出，
  覆盖无平台 CC 的自录视频场景。
- 简报格式（材料，不是答案）：

  ```
  [视频档案]《标题》UP主·时长·平台
  画面：<VLM 输出：主体与发生的事>
  画面文字：<逐字转写>
  声音：<ASR 要点 / 未分析 / 无人声>
  字幕要点：<CC 前 N 字>
  覆盖说明：<如"音频仅分析前 3 分钟">
  ```

- **简报与问题解耦**：首次生成不针对具体问题（question 仅作 VLM 提示），追问复用缓存简报，
  一个视频只分析一次，追问零增量成本。

### 4.5 人格化机制

感知层输出客观材料，**出声永远由人格模型完成**。在 `build_chat_prompt_with_diagnostics`
的运行时注入区（人设原文模式的"——— 运行时注入的实时上下文 ———"之后，两种人设模式都生效）
追加**媒体应对守则**：

> 当消息附有视频/图片档案时：先用你自己的口吻回应用户真正问的事；需要介绍内容时像亲眼看过
> 一样自然讲出来，禁止输出"视频内容总结："式的档案复读或分点罗列；可以引用时间点；用户提出
> 做不到的事（如去水印、导出原图）以你的性格直说做不到并给出替代建议。

注入文本仍保留"（不可信上下文，仅供参考）"标记与 `bot_video_brief_max_chars`=1200 截断。
分析失败/超时 → 复用 `persona_failure_message(session_id)` 话术池（私聊直发、群聊
`SILENT_AUDIT` 静默审计 + `OperationalIssue`，机制现成：chat.py:135-167, 1333-1417）。

### 4.6 进度提示

`build_chat_capability` 新增可选参数 `progress_notifier: Callable[[str], Awaitable[None]] | None`，
由 `__init__.py::_handle_chat` 接线到即时发送。仅当编排器**确认要干重活**（无缓存简报、
总开关开、provider 就绪）时回调，默认文案与人格话术一致风格（如"视频我看一下，稍等…"），
每会话 60 秒节流防刷屏（`bot_video_progress_ack_enabled` 可关）。

### 4.7 配置项（`config.py` + `runtime/settings.py`）

```python
bot_video_understanding_enabled: bool = False   # 总开关；False=完全回退现有 describe_video 行为
bot_video_max_frames: int = 8
bot_video_brief_deadline_seconds: float = 45.0
bot_video_brief_max_chars: int = 1200
bot_video_asr_max_seconds: int = 180            # P2
bot_video_progress_ack_enabled: bool = True
bot_video_fuzzy_followup: bool = False          # P2
```

全部加入 `SETTABLE_KEYS` 支持运行时热改；同时补入 `BOT_ASR_ENABLED`（修复缺口 #9）。
过渡期保留旧 `describe_video` 直调路径在开关之后，稳定一个版本后移除。

## 5. 分阶段实施计划（TDD）

### P1 —— 追问闭环（不碰音频，风险最低）

| 步骤 | 内容 | 产出测试 |
|---|---|---|
| 1 | `character/media_registry.py`：Record/SQLiteMediaRegistry（CRUD/反查/TTL/FIFO） | `tests/test_media_registry.py`：注册-反查、同 id 复用、TTL 剪枝、行数上限、会话隔离 |
| 2 | video part `meta` 透传：`content_parser.py`、`download.py`、`output/renderer.py`（mixed parts 不破坏现有结构） | 现有渲染回归 + meta 字段断言 |
| 3 | `__init__.py` 发送点注册 bot_sent；chat.py 注册 user_sent | `tests/test_video_reply_flow.py`：假网关回执 → 档案含 provider_message_id 与 local_path |
| 4 | `sources/video_understanding.py` P1 串行实现（帧+CC+元数据 → 单次 VLM；VLM 挂 → 纯文本简报） | `tests/test_video_understanding.py`：假 provider 退化矩阵（仅帧/仅字幕/仅元数据/全挂/超预算） |
| 5 | chat.py 媒体解析步骤（reply 反查命中缓存 → 注入；自带 video → 分析+建档） | 同上 flow 测试：二次提问零 VLM 调用；开关关闭零额外调用 |
| 6 | 媒体应对守则注入 system prompt 运行时区 | flow 测试断言 messages 含守则文本且随简报出现 |
| 7 | config/settings 新键 + progress_notifier 接线与节流 | 配置默认值与热改断言 |

P1 验收：① 回复机器人发的视频提问 → 人格口吻回答，二次提问不重新分析；
② 用户自发视频提问 → 同上并建档；③ 总开关关 → 行为与现状一致；④ 全信号失败 → 失败话术不炸链路。

### P2 —— 声音与覆盖面

音轨抽取 + ASR 并行编排（线程池、45s 硬预算）；内嵌字幕轨提取；NapCat `get_msg`/`get_video`
反查陌生视频（失败静默）；parsed_only 档案按需补下载；模糊追问（默认关）；
`BOT_VIDEO_*`/`BOT_ASR_ENABLED` 热改键全量接线。
验收：无 CC 的口播视频能答出讲了什么；45s 到点必出简报；white2 触发规则回归通过。

### P3 —— 可选增强

原生视频输入按模型 tags 定向直传（方案 C）；`/bot video 深看` 主动重分析命令；
解析卡片"可追问"提示（届时按 Mica 规范动卡片，颜色仍走 `PLATFORM_COLORS` 派生 token）。

## 6. 测试与回归底线

- 新增：`test_media_registry.py`、`test_video_understanding.py`、`test_video_reply_flow.py`。
- 必须保持绿：`test_youtube_subtitle_regression.py`、`test_asr_transcribe.py`、
  `test_vision_local_media.py`、`test_white2_strict_mention.py` 及既有全量。
- 入口统一 `scripts/dev.ps1 -Task test / lint`；不直接在源码树跑 pytest。

## 7. 风险与回滚

| 风险 | 缓解 |
|---|---|
| 下载+ASR+VLM 串行延迟 60s+ | P2 并行化 + 45s 硬预算 + 进度提示 |
| NapCat `get_video` 对非自家消息可用性未实测（置信度 unknown） | 放 P2，失败静默降级；实施首日先做可用性探针 |
| VLM 成本上升（4→8 帧） | 简报缓存（一视频一次）+ `bot_video_max_frames` 可调 + `bot_video_understanding_enabled` 一键关 |
| Registry 与下载缓存生命周期漂移（文件被清、简报还在） | 简报注入前校验 `local_path` 存在性；纯文本简报仍可注入；TTL 对齐 7 天 |
| 隐私范围 | 仅同会话内反查；不主动跨群共享媒体档案 |

回滚：`BOT_VIDEO_UNDERSTANDING_ENABLED=0` 即回退旧行为；Registry 为增量表，停用即弃，删文件即清。

## 8. 未决事项

1. NapCat `get_video`/`get_msg` 返回 video 段落盘路径的实际字段（P2 首日探针验证）。
2. yt-dlp 补进 `pyproject.toml` 依赖声明（downloader 已依赖，实施时顺手补一行）。
3. P1 验收需在 white2 类群实测"回复机器人视频消息"时 NoneBot `to_me` 是否为真（决定是否需要
   放宽该场景的 gate——若需要，单独提请用户确认，不默认放松）。

## 9. 决策记录与实施结果（2026-09-10）

**用户决策**：P1 + P2 + 方案 A + 方案 C 一起实施；yt-dlp 补依赖声明；要求降低 token/算力/本机开销。

**成本收敛（相对原设计的下调）**：
- 抽帧默认 8 → 6（`bot_video_max_frames`），单次 VLM 调用内消化，帧+CC 字幕+元数据+提问合并为一次请求；
- 已有平台 CC 字幕时默认跳过 ASR（`bot_video_skip_asr_with_subtitle=true`）——字幕已含语言信息，音频转写是纯增量成本；
- 音轨分析默认只取前 120 秒（`bot_video_asr_max_seconds=120`）；
- 简报缓存于档案库：一个视频只分析一次，同视频追问零增量 token；
- 方案 C（原生 video_url 直传）默认关闭（`bot_video_native_input=false`），且仅对小文件（≤20MB）尝试，失败自动回退抽帧；
- 本机开销：无后台任务、无常驻进程，ffmpeg 抽帧/抽音轨按需单次执行，SQLite 档案库写时顺带 TTL+FIFO 剪枝（7 天/5000 行）。

**实施落点**（全部实跑验证）：
- 新增：`character/media_registry.py`、`sources/video_understanding.py`（子代理 TDD，9+10 用例绿）；
- 契约扩展：`IncomingMessage.reply_video_path`、`ContextBundle.media_directive`（均带默认值，向后兼容）；
- `capabilities/chat.py`：`_resolve_media_context`（回复命中缓存 → 自带视频分析建档 → 模糊追问）、`_VIDEO_BRIEF_TAG` 注入、`_MEDIA_DIRECTIVE` 守则进 system prompt、工厂新参 `media_registry/video_understanding_enabled/media_config`；
- `__init__.py`：发送点 `_register_bot_sent_video_assets`（回执 message_id ↔ 文件 ↔ meta ↔ CC 字幕入档）、`_prepare_video_understanding_message`（handler 异步上下文里做 NapCat `get_msg` 反查 + 进度提示节流发送）、档案库构建；
- 设计修正：模糊追问等零成本信号不再依赖 vision 开关（工厂显式 `media_config` 句柄，不从 provider 借配置）；
- 集成测试 `tests/test_video_reply_flow.py` 6 用例锁定：缓存命中零编排调用、现场分析回写、user_sent 建档、开关关闭零触达、未知回复零动作、模糊追问。

**验证**：dev.ps1 test 660 passed（0 failed）；本次改动涉及的全部 14 个文件 ruff 全绿；分支上另有 7 个 lint 错误为既有未提交工作遗留（music.py/bridge.py/templates.py/platforms_generic/platforms_weibo/test_moegirl_search/test_operational_failures），未动。

**未决事项答复与后续**：
1. NapCat 探针：反查逻辑已按"`get_msg` → message 数组 → video 段 `file`/`path`（本机路径直用），否则 `url` 下载到 `data/downloads/fetched/`"实现，任何一步失败静默降级——生产首条"回复他人视频"消息即为实测探针，无需单独动作。
2. yt-dlp：已声明进 pyproject.toml。
3. white2 `to_me`：未改任何触发门槛。NoneBot OneBot 适配器对"回复机器人的消息"通常置 `to_me=true`（即硬 @ 同等），若生产实测发现 white2 里回复视频不触发，需要单独决策是否放宽 gate，代码未预设。
4. 启用方式：`.env` 设 `BOT_VIDEO_UNDERSTANDING_ENABLED=true`（或运行时 `/bot set BOT_VIDEO_UNDERSTANDING_ENABLED true` 热改），vision/ASR 注册表沿用现有配置。

## 10. white2 触发补强与缓存答疑（2026-09-10 追加）

**用户决策**：① white2 群引用/回复机器人消息即使无真 @ 也应触发；② 纯文本里复制/手打的
"@昵称"（非平台 at 段）也要能识别；③ 质疑"终身只分析一次"的完整性与缓存增长。

**实施**（TDD，`tests/test_text_at_mention.py` 10 用例，全量 684 绿）：
- `_detect_text_at_mention()`：`@` 后紧跟人格昵称/好感度小名（停用词除外）→ 硬点名；
  只在用户自己的消息文本上检测（引用拼接之前），防止引用内容里的 @ 误判。
- 回复的消息在媒体档案中为 `bot_sent`（机器人发过的视频）→ 硬点名；回复别人的视频不算。
- 两者并入既有 `hard_mention` 通道，white2 gate 规则本身未改动，软点名校准逻辑不受影响。
- 新增 `bot_media_registry_ttl_days=7`：档案与简报按天过期自动剪枝，过期后追问自动重新分析。

**缓存与完整性口径**：简报是有损摘要（6帧+前120秒音频+CC字幕），日常追问够用，不承诺
"完整信息"；档案 7 天寿命（可配），文本量硬上限 5000 行 FIFO（约 10MB），视频文件由既有
下载缓存配额（2GiB/7天）独立清理——不存在无限增长。更深的按问题重分析（更多帧/全音频）
归入 P3 的 `/bot video 深看` 命令。

**反查下载的封禁风险口径**：bot_sent/user_sent 两类视频零新增网络请求（本地文件复用）；
唯一新增网络行为是回复他人视频时的 NapCat `get_msg`（走本人已登录 QQ 协议，等同本人点开
消息，非网页爬虫）+ NTQQ 签名短期链接下载（绑定会话，等同客户端缓存）。触发以"有人回复
提问"为单位、7 天内同文件复用、失败静默不重试——无批量爬取面。平台 web API（B站/YouTube
解析）风险面未扩大，Cookie/代理机制沿用既有链路。

## 11. 自查修复与参数上调（2026-09-10 第二轮，全量 692 绿）

**用户决策**：人格名纠正（守岸人；小名：小岸同学/岸宝/我的蒙娜丽莎，测试里的臆造名"小维"
已全部替换）；音频分析上限 120→600 秒。

**自查发现并修复的缺陷**（TDD，`tests/test_video_progress_ack.py` 7 用例）：
1. **空承诺 ack**：vision/ASR 都未配置时用户发视频仍会先收到"稍等"，随后对视频只字不提
   → ack 增加"有信号来源"把关（provider 或既有档案，缺一不发）。
2. **white2 应了不答**：受限群里无点名的视频消息会被 gate 拒绝，但 ack 已先行发出
   → ack 增加 `mentions_bot` 把关，本轮不会回复就不打扰。
3. **纯元数据档案被误判"没活可干"**：档案只有字幕/标题、文件已被缓存清理时，
   `will_analyze` 误判导致该答不答 → 档案含任何材料即视为可分析。
4. **600 秒音频被默认值绞杀**：ASR 超时沿用语音消息的 20s（长音频必超时）、总预算 45s
   会砍掉慢转写 → ASR 超时随时长上限缩放（上限×25%，封顶 150s），总预算 45→75s。
   `bot_video_asr_max_seconds=600`、`bot_video_brief_deadline_seconds=75`。

**审计过、判定无虞的点**：档案库单例空值守卫；简报/字幕以"不可信上下文"标记注入；
600s 16kHz 单声道 mp3 约 3.6MB（远低于 20MB 上传上限）；原生直传失败回退抽帧；
节流表 512 会话封顶；ffmpeg 抽音轨自带 300s 硬超时；并行工作线程 shutdown(wait=False)
不阻塞主链路。

**已知边界（明示不修）**：简报是有损摘要，按问题深挖归 P3 `/bot video 深看`；模糊追问
默认关；NapCat `get_msg` 返回字段以生产首条消息实测为准（失败静默降级）。
