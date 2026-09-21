# 席位 U1-INVEST：消息摄取统一性取证审计（2026-09-20）

> 术语说明：本文中的 **NapCat** 指 2026-09-18 之前的 QQ 协议端（当时实况记录，保留原文不改写）；现役协议端为 **SnowLuma**，见 [snowluma-setup.md](../snowluma-setup.md)。

> **性质**：只读审计席位。零代码/配置改动、零 git 写、零子代理、零真实发送。
> **对象**：入站侧统一性——「一切消息必须经中央统一摄取与归一后才进入分发管线」。
> **方法**：实读代码 + grep/AST 取证 + scoped 测试实跑。禁推测措辞。
> **快照口径**：行号 = 2026-09-20 本席位取证时刻。每条发现均附**锚点字符串**，行号漂移时以锚点重定位。
> **上轮审计关系**：`docs/design/audit-20260919-unify-wave.md` 对象=渲染收口 + WebUI 前端，**与本席入站侧零重叠**；本席只在 §复核 处引用其结论（见文末）。

---

## §0 取证计划与完成度（自报覆盖面）

| 项 | 范围 | 状态 | 产出 |
|---|---|---|---|
| 1 | `__init__.py` 摄取段：事件类型覆盖 / 段归一 / 引用链反查 / 语音预转码 / TG file_id→字节 | **完成** | §1，发现 U1-01~04 |
| 2 | IncomingMessage 是否唯一入站契约：全树直连原始 Event 清单 | **完成**（AST 117 函数全量扫描） | §2，发现 U1-08 + 7 条旁路登记 |
| 3 | 被动 matcher 旁路逐个判定（campus / meme / reactions / media_archive / auto_send / daily_assist / 群摘要） | **完成**（7/7 逐个判定） | §3，发现 U1-09~12 |
| 4 | 文本提取重复实现清单 + 差异点 | **完成**（4 份纯文本 / 3 份 URL / 6 册段型） | §4，发现 U1-13~18 |
| 5 | session_key 口径单源性 + 群摘要双口径实证 | **完成（已端到端复现）** | §5，发现 U1-05~07 |
| 6 | 入站幂等/去重口径一致性、双计判定 | **完成**（6 个去重位列表） | §6，发现 U1-19~20（结论：当前无双计） |
| 7 | 多适配器对等性（OneBot / Telegram / Mail / Console） | **完成**（注册实况 + 8 维矩阵 + 5 处隐藏假设逐个证伪） | §7，发现 U1-21~23 |
| 8 | 机器门/登记表可信度（席外加发现） | **完成** | §8，发现 U1-24 |
| 9 | 上轮审计复核 | **完成**（相关 3 条） | §9 |
| 10 | 源码树零残留自查 | **完成，已清零** | §11 |

---

## §1 摄取段实际路径（事件 → IncomingMessage）

### 1.1 唯一的归一函数与其真实调用拓扑（实证）

中央归一函数 = `plugins/bot_unified_runtime/__init__.py:1274 _incoming_from_nonebot_event(event, bot_id, adapter_name, segments, reply_chain, feature_enabled) -> IncomingMessage`。
段归一/引用链实体在 `domains/chat_reply/ingest/message_context.py`（467 行，canonical）；根 `message_context.py`(18 行) 与 `runtime/ingress.py`(18 行) 均为 PEP 562 活转发垫片（`_CANONICAL` 指向 chat_reply 域），**无第二实现**。

生产代码调用点全量枚举（`grep -rn "_incoming_from_nonebot_event" --include=*.py plugins/`，排除 tests/）：

| 坐标 | 传的 enrichment 参数 | 归属 |
|---|---|---|
| `__init__.py:2531` | 无（经 `IngressGateway`） | `_run_capability_through_pipeline` 通用管道 |
| `__init__.py:5566` | 无 | image_search |
| `__init__.py:5795` | `adapter_name="Mail"` | mail_notice |
| `__init__.py:7295` | **segments + reply_chain + feature_enabled 全给** | chat（热区） |
| `__init__.py:7745` | 无 | content（链接解析） |
| `__init__.py:7813` | 无 | music |
| `__init__.py:7870` | 无 | today_history |
| `__init__.py:7921` | 无 | `_run_simple_capability`（wiki/moegirl/epic/weather/market/fx… 复用） |
| `__init__.py:7976` | 无 | group_info |
| `__init__.py:8132` | 无 | media_archive |
| `__init__.py:8191` | 无 | meme_library |
| `__init__.py:8505` | 无 | moegirl_question |
| `domains/core/decision/ingress.py:43,68` | 无 | OneBotSource / 决策引擎 Phase-0 位 |

**关键结构事实（实证）**：`IngressGateway`（`domains/chat_reply/runtime/ingress.py:8`）全文 14 行，`from_event` 只是 `self._normalizer(event, bot_id=bot_id)` 一行转发。12 个生产调用点中 **仅 1 个走该网关**，其余 11 个直接调私有函数 `_incoming_from_nonebot_event`。网关不承载任何 enrichment、不承载任何门、不承载任何审计 → 「中央摄取边界」目前是**名义存在**，实质是「一个被 11 处直接引用的模块级函数」。

### 1.2 富化（enrichment）四件套的实际落点：只在 chat 热区 handler 内联

`_incoming_from_nonebot_event` 本体是**同步纯函数**，四项需要 `await` 的富化全部在调用方。全量枚举（`grep -rn "enrich_telegram_file_segments\|_transcode_record_segments\|collect_reply_chain_async\|_forward_message_text" --include=*.py plugins/`，排除 tests/）：

```
__init__.py:7281            await _transcode_record_segments(bot, event_segments)          # 语音预转码
__init__.py:7286            await enrich_telegram_file_segments(bot, event, event_segments) # TG file_id→字节
__init__.py:7290            resolved_chain = await collect_reply_chain_async(...)            # 引用链反查
__init__.py:7529            forward_text = await _forward_message_text(bot, event, ...)      # 合并转发正文
```

**四处全部命中数 = 1**，即**只此一份、只在 `@chat.handle()`（priority=50）里**。其余 11 个摄取入口得到的是「未富化」的 IncomingMessage：

- **U1-01（P1）**｜`__init__.py:7281-7291` vs `8132`｜锚点 `if switches.enabled("bot.ingress.telegram_media"):`
  根因：TG 媒体富化只有 chat 链有。`media_archive`（收藏/归档，本体就是处理图片/动图/视频）、`image_search`（搜图）、`content`（链接解析）三个**媒体强相关**能力全部拿不到 `file_id→字节` 的回写。
  证据：`enrich_telegram_file_segments` 全库仅 1 个生产调用点（上表）；`domains/media/ingest/telegram_media.py:290` 是该函数定义；media_archive 侧自建了 `_enrich_media_archive_message`（`__init__.py:8060-8128`），它做的是 `get_msg`/`get_forward_msg` 反查注入 `reply_media_segments`/`chat_record_text`，**不含 TG file_id 解析**（该函数内 `grep -c enrich_telegram` = 0）。
  后果口径：Telegram 发图 + 「收藏」→ 段里仍是 `file_id`，归档落盘链路读到的是不可消费的路径 → 功能退化。（**未做实机验证**——本席禁止真实发送，此条只主张「不经同一富化」的结构事实，不主张线上具体报错文案。）
  改法 before→after：把四件套抽成 `async def enrich_incoming(bot, event, config, switches) -> tuple[list[dict], list[ReplyChainItem], str]`，chat handler 改为调用它；`media_archive`/`image_search`/`content` 三入口同样调用（各自按需取用返回值）。
  验证：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_telegram_media.py tests/test_media_archive.py tests/test_reply_chain_recursion.py tests/test_forward_message_ingest.py -p no:cacheprovider --basetemp="$TEMP/u1-enrich" -q`

- **U1-02（P2）**｜`__init__.py:8082`｜锚点 `return _forward_message_text_sync(payload)`
  根因：合并转发正文解析在 media_archive 里**第二次实现**了一遍（复用同一同步洗文本函数 `_forward_message_text_sync`，但自己发 `get_forward_msg`、自己拼、自己注 `chat_record_text`），而 chat 链是 `_forward_message_text` 注 `plain_text`。同一份「转发正文」在两条链上**落成两个不同字段、两处独立网络调用**。
  改法：转发正文收进 1.2 的统一富化器，产出 `forwarded_text` 单一字段，由摄取层一次性决定注入点。
  验证：同 U1-01 命令 + `tests/test_f03_notice_redaction.py`。

### 1.3 事件类型覆盖实况表（逐项实证，非文档转述）

| 事件 | 摄取入口 | 是否产 IncomingMessage | 坐标/锚点 |
|---|---|---|---|
| 私聊消息 | `chat`(p50,block) / 各能力 matcher | ✓ | `on_message(rule=_is_plain_chat_event, priority=50, block=True)` @4781 |
| 群消息 | 同上 | ✓ | `_is_plain_chat_event` 内部按 `GroupMessageEvent` 判 |
| 合并转发 | chat 链内联 `_forward_message_text` | ✓（plain_text 追加） | `:7529` |
| 引用（reply） | `collect_reply_chain` / `_async` | ✓（reply_chain 结构化） | `message_context.py:342/278` |
| 语音 record | `_transcode_record_segments` | ✓（data.transcoded_path） | `:1125/7281` |
| 图片/视频 | `normalize_message_segments` 打标签 | ✓ | `message_context.py:57-85` |
| 表情回应 notice | `_normalize_onebot_emoji_like` | **✗ 不产 IncomingMessage** | `:5302-5325`，自产 `ReactionEvent(session_key=…)` |
| 戳一戳 notice | `_poke_dispatcher.build_poke_reaction(event,…)` | **✗ 直读原始 event** | `:5222-5228` |
| 入群 group_increase | `on_notice` | ✓（`_incoming_from_nonebot_event` 空文本降级） | `:5337`，注释见 `:5368` |
| 退群/管理变更 | `on_notice` | 只记事件 | `:5394/5405` |
| **撤回（group_recall / friend_recall）** | **零处理** | ✗ | `grep -rn "GroupRecall\|FriendRecall\|recall" plugins/bot_unified_runtime/__init__.py` → **0 命中** |
| 群文件上传 notice | `group_upload_notice` | 旁路 | `:4953` |

**撤回取证结论**：`grep -rni "recall" --include=*.py plugins/bot_unified_runtime/` 的命中全部落在无关处（`_reload_if_changed` 之类），OneBot `group_recall`/`friend_recall` 无任何 matcher 注册。定性=**功能未实现**，非「绕过统一摄取」；因撤回消息至今无任何下游消费者，按 P3 卫生级登记（若将来做「撤回后清理记忆」，必须落在统一摄取而非新旁路）。

### 1.4 段归一的适配器盲点（实锤）

`message_context._flatten` 认的媒体段全集（`:57-68`）：`image, photo, sticker, animation, video_note, file, record, voice, audio, video` + 表情族 `face, mface, marketface, emoji`。
`__init__.contains_visual_message_segments` 认的集合（`:669`）：`{"image","face","mface","marketface","sticker","video"}`。

**U1-03（P1）**｜`__init__.py:669`｜锚点 `visual_types = {"image", "face", "mface", "marketface", "sticker", "video"}`
根因：两个集合**同源不同册**——归一层已经承认 `photo / animation / video_note` 是媒体并会打出 `[图片]/[动图]/[圆形视频]` 标签，但「是否有视觉内容」的放行判定漏认这三个 TG 专属类型。
证据链（两处代码对读）：`message_context.py:72-83` 的 label 字典含 `"photo":"图片","animation":"动图","video_note":"圆形视频"`；`__init__.py:669` 集合无此三名。语音侧则**三型齐全**（`:678 AUDIO_SEGMENT_TYPES = frozenset({"record","voice","audio"})`，注释明写「此前只认 record，于是 Telegram 语音在入站侧完全不识别（评审需求 3）」——**同一 bug 的语音版当年修了，视觉版没修**）。
后果：Telegram 纯图片/纯动图/纯圆形视频消息 → `text` 空 + `contains_visual_message_segments=False` + `contains_audio=False` → `__init__.py:1374` 的占位文案不触发 → `plain_text` 为空 → 路由判 IGNORE。即 AGENTS.md 宣称「TG 媒体全通」在这一形态下不成立。
改法 before→after：
```python
# before
visual_types = {"image", "face", "mface", "marketface", "sticker", "video"}
# after（与 message_context 的媒体册同源；最好在 message_context.py 导出
# VISUAL_SEGMENT_TYPES / AUDIO_SEGMENT_TYPES / FORWARD_SEGMENT_TYPES 三枚常量，
# __init__ 与 contains_* 全部 import，消灭第二册）
visual_types = {"image","photo","sticker","animation","video_note","video",
                "face","mface","marketface","emoji"}
```
验证：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_nonebot_event_adapters.py tests/test_meme_image_input.py -p no:cacheprovider --basetemp="$TEMP/u1-vis" -q`；补一条负锁：构造 `type="photo"` 段断言 `contains_visual_message_segments(...) is True`。

**U1-04（P3）**｜`message_context.py:53-56` vs `__init__.py:669`｜锚点 `"emoji"`
归一层认 `emoji` 为表情族，`contains_visual_message_segments` 不认 `emoji`；同族不同册的第二例（与 U1-03 同根，合并处置）。

### 1.5 `at` / `reply` 段在归一中的处理（口径核对，未见缺陷）

取证 4 项：①`_flatten` 无 `at`/`reply` 分支 → 落 `elif kind:` 透传分支（`message_context.py:86-87`），段保留在 `segments` 但**不进 plain_text**；②@ 语义改由 `_detect_onebot_direct_mention(raw_segments, bot_id)`（`:1109`）在结构化段上判定；③reply 正文由 `collect_reply_chain` 独立采集并 `format_reply_chain` 拼接（`:1404`）；④点名检测保持在引用拼接**之前**（`:1401-1402` `own_text = text`，注释明写评审 L1 根因）。四项口径自洽，**未见缺陷**。

---

## §5 会话标识口径单源性（实证：三套并存，已复现零行缺陷）

### 5.1 权威事实：NoneBot OneBot V11 的 `get_session_id()` 实测输出

命令与实跑输出（venv 解释器，`PYTHONDONTWRITEBYTECODE=1`）：

```
GROUP   get_session_id() -> 'group_123456_777'
PRIVATE get_session_id() -> '777'
```

即：群会话键 = `group_<群号>_<发送者>`（**含发送者**），私聊键 = **裸 user_id（无 `private:` 前缀）**。
`_incoming_from_nonebot_event:1288` 直接 `session_id = event.get_session_id()` 并原样落进 `IncomingMessage.session_id:1478`，除 mail 分支（`:1321` 覆写为 `f"email:{sender_id}"`）外无任何归一。

### 5.2 三套并存的群键（同一「群」在库里有三种身份证）

| 形态 | 语义 | 生产者/消费者坐标 |
|---|---|---|
| `group_<gid>_<uid>` | NoneBot 原生、含发送者 | **写入方**：`__init__.py:1288` → `conversation_turns.session_id`（经 `_record_chat_history_turn:2102`）、audit、限流、好感等一切以 `message.session_id` 为键的面 |
| `group:<gid>` | 冒号族、群维度 | `__init__.py:1825`（今日推送）、`:3190`（群摘要推送 SendRequest）、`domains/ops/smoke/smoke.py:602`、`control_plane/webui_memory_graph.py:381,439`、**读取方** `domains/chat_reply/character/shared_group.py:34 _group_session_id` |
| `group_<gid>_<user>` | 下划线族、反应域自建 | `domains/meme/reactions/engine.py:329 session_key_from_ids` → `:334 return f"group_{group}_{user or 'unknown'}"` |

取证命令与命中数：
- `grep -rn 'f"group:' --include=*.py plugins/` → 5 命中（上表冒号族）
- `grep -rn 'f"group_{group' --include=*.py plugins/` → 1 命中（reactions）
- **无单一 session-key 构造模块**：`def build_scope_key`（`character/memory.py:256`）只做二次加工，不做规范化唯一入口。

### 5.3 U1-05（P1，已端到端复现）群摘要读取键与写入键永不相交 = 群上下文恒空 + 21:30 推送恒静默空转

- **坐标**：写 `plugins/bot_unified_runtime/__init__.py:1288` + `:2102`；读 `domains/chat_reply/character/shared_group.py:34 / :242-252`；推送侧 `__init__.py:3185`。
- **锚点**：读侧 `_GROUP_SESSION_PREFIX = "group:"` + `WHERE session_id = ?`；写侧 `session_id = event.get_session_id()`。
- **根因**：写方落 `group_123456_777`（含发送者），读方查 `group:123456`（群维度），两个字符串**永不相等** → `_fetch_group_rows` 恒 0 行 → `load()` 返回 `enabled=False`。
- **证据（本席实跑复现，非引用他文）**：
  ```
  NoneBot group get_session_id() = 'group_123456_777'
  digest query key               = 'group:123456'
  rows read by digest            = 0 []
  stored rows                    = [('group_123456_777', 'user', '群聊双口径复现文本')]
  SharedGroupContext.enabled     = False | summary = ''
  ```
  （脚本：用生产 `SQLiteConversationHistoryRepository.append_turn` 以 `message.session_id` 口径写入，再用生产 `SQLiteGroupDigestProvider._fetch_group_rows` 读取，基座目录 `tempfile.mkdtemp(prefix="u1-dblkey-")`，零源码树残留。）
- **双重后果**：①对话侧【群共享上下文】分区永不注入（人格在群里看不到最近群聊）；②推送侧 `__init__.py:3185` `if not getattr(context,"enabled",False) or not summary: continue` → **21:30 每日群摘要一条也不发、日志无告警**。即 AGENTS.md #33 记为「调研发现存量缺陷两处（未修，建议立项）」的那一条，**截至 2026-09-20 仍未修**。
- **改法 before→after**（最小正确修法，落在摄取侧而非读取侧，符合中央统一 mandate）：
  ```python
  # 新增单一事实源（建议 domains/core/contracts/session.py，或并入 message_context.py）
  def normalize_session_id(raw: str) -> str:
      """'group_123456_777' -> 'group:123456'；'777' -> 'private:777'；'email:x' 原样。"""
      if raw.startswith("group_"):
          parts = raw.split("_")
          return f"group:{parts[1]}" if len(parts) >= 2 else raw
      if raw.isdigit():
          return f"private:{raw}"
      return raw
  # __init__.py:1288  before: session_id = event.get_session_id()
  #                   after : session_id = normalize_session_id(event.get_session_id())
  # shared_group.py:34 保持 f"group:{group_id}"（成为规范形态唯一读者，不再改）
  ```
  ⚠️ **迁移风险必须同时处置**（否则本改法引入新 P0）：`session_id` 是**存量 SQLite 主键的组成部分**——`conversation_turns` / `user_affinity` / 限流表 / `session_identity` / audit 全按旧键索引。配套清单：①`session_type` 判定不得再靠 `"group" in session_id` 猜（`__init__.py:1345` 现状），改由适配器分支显式赋值；②per-sender 语义不能抹平——群历史如需按发送者查，改走 `conversation_turns.sender_id` 列（`_record_chat_history_turn` 已传该列），**不再靠往键里塞 sender**；③一次性迁移脚本 + `%TEMP%` 备份（铁律 2）；④双写过渡期（新旧键同写，读先新后旧）。
  若不承担迁移面，**替代最小修** = 仅修读侧：`_fetch_group_rows` 改 `WHERE session_id LIKE 'group_' || ? || '_%' OR session_id = ?`（参数=群号、群号），一行、零迁移，但把三套键的债永久留在代码里（届时本条降级为 P2 欠账并须留 TODO 锚）。
- **验证命令**：
  `PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_group_context_b03.py tests/test_time_window_summary.py -p no:cacheprovider --basetemp="$TEMP/u1-sess" -q`
- **回归锁（必修时同建）**：新建 `tests/test_group_digest_session_key_single_source.py`——用真 `GroupMessageEvent.get_session_id()` 写、用生产 provider 读、断言 `enabled is True`。**取证缺口实证**：`grep -rn "get_session_id" tests/ | grep -i digest` → 0 命中；两侧各自单测自洽故全绿，这是 8500+ 用例套不住该 bug 的根本原因，不补锁则同类漂移必再犯。

### 5.4 群维度 vs 发送者维度语义冲突（同一根因的第二面）

`shared_group.py` 设计意图是「群公共投影：忽略发送者」（模块 docstring `:4-8` 明写），而摄取层的键**天生含发送者**。这不是哪一侧写错，而是**摄取契约缺一等公民**：`IncomingMessage` 只有 `session_id` 一个字段承载「会话」，没有群维度/个人维度的分层。

**U1-06（P2）**｜`domains/core/contracts/runtime.py:121`｜锚点 `class IncomingMessage(StrictBaseModel)`
改法：契约加两个派生只读属性（`group_scope_key` / `personal_scope_key`），消费者按键类型选取，禁止再手拼字符串。
验证：`grep -rn 'f"group:\|f"private:\|session_key_from_ids' plugins/ --include=*.py` 的非契约命中数应为 0。

### 5.5 `_is_group_session` 两处独立实现（口径漂移实锤）

- `domains/chat_reply/capabilities/memory.py:81 def _is_group_session(session_id)`
- `domains/meme/reactions/engine.py:292 def _is_group_session(session_key)`

**U1-07（P3）**｜锚点 `def _is_group_session`（全树 2 命中）。同名同义判据两份实现，输入还不同源（一个是 `IncomingMessage.session_id`，一个是 reactions 自建键）。改法=并入 §5.3 规范模块，导出 `is_group_session(key)` 单函数。
证据：`grep -rn "def _is_group_session" --include=*.py plugins/` → 2 命中（上列两文件）。

---

## §2 IncomingMessage 是否唯一入站契约（全树直连原始 Event 清单）

### 2.1 结论先给

**归一层是单源的**（唯一函数 `_incoming_from_nonebot_event`，无第二实现；`IngressGateway`/`AdapterSource` 两个"边界抽象"都不承载逻辑）。
**但契约不是单源的**：117 个吃 `event` 的函数里，**65 个从不构造 `IncomingMessage`**（AST 扫描实跑输出，见 2.2），其中含 4 个真正会改状态/落库/出站 handler。所以「一切消息经中央归一后才进分发管线」目前**不成立**。

### 2.2 取证方法（AST，非 grep 计数）

命令：venv 解释器 + `PYTHONDONTWRITEBYTECODE=1`，`ast.parse(__init__.py)` 遍历所有形参含 `event` 的函数，判定其体内是否出现 `_incoming_from_nonebot_event/_run_capability_through_pipeline/_send_text_through_unified_pipeline/_send_parts_through_unified_pipeline/_run_simple_capability` 调用。实跑输出首两行：

```
total funcs taking `event`: 117
--- funcs that read raw event attrs AND never build IncomingMessage ---   （65 条）
```

（同一次扫描还统计了每个函数对 `event` 的属性读取集合与把 `event` 作参数外传的次数，用于区分「规则谓词」与「真旁路」。）

### 2.3 matcher 注册点的物理位置（先立的正结论）

`grep -rn "on_message(\|on_notice(\|on_request(" --include=*.py plugins/` 排除根 `__init__.py` → **0 命中**（唯一命中是 `gscore_bridge.py:267` 的自有同名方法 `self.on_message(payload)`，与 NoneBot 无关，`domains/chat_reply/runtime/base_router.py:392` 等是函数调用非注册）。
**判定：全部 NoneBot matcher 注册集中在根 `__init__.py`，没有任何插件域自建 matcher。** 这是本席最重要的正面结论——「统一入口的物理位置」是成立的，缺的是入口内部的单源性。

### 2.4 真旁路清单（读原始 event 且改状态/落库/出站，不经契约）

| # | 坐标 | 它自己做了什么归一 | 严重度 |
|---|---|---|---|
| B1 | `_handle_campus_record` `__init__.py:5002-5030` | 自己 `event.get_plaintext()`、自己 `getattr(sender,"card") or getattr(sender,"nickname")`（复刻 `:1469` 的 `sender_display_name` 逻辑）、自己取 `message_id`、自己 `send_queue.submit(request)` | **P1**（详见 §3.1） |
| B2 | `_handle_meme_absorb` `__init__.py:5940-5950` → `domains/meme/sources/meme_library_listener.py:247` | 自己 `event.get_session_id()`+`"group" not in session_id` 判群、自己 `event.get_message()` 取段、自己 `_segment_urls`（第三份段→URL）、自己 `httpx` 下载、自己入库 | **P1**（SSRF 缺口，见 §4.3） |
| B3 | `_handle_dirty_guard` `__init__.py:4976-4992` | `event.get_plaintext()` + `getattr(event,"message_id")` + **`bot.call_api("delete_msg")` 直连平台 API** | P2 |
| B4 | `_handle_group_upload` `__init__.py:4955-4967` | 直读 `event.file` dict/对象双形态、`group_file_store.record(...)` 直接落库 | P2 |
| B5 | `_handle_msg_emoji_like_notice` `__init__.py:5302-5325` → `reactions/engine.py:354 normalize_onebot_emoji_like` | 自建 `ReactionEvent` 契约与自建 `session_key_from_ids`（不产 IncomingMessage） | P2（键语义错位见 §6.3） |
| B6 | `_handle_poke_notice` `__init__.py:5222-5228` → `domains/chat_reply/capabilities/poke.py:30 accept(event,…)` | 把**原始 event** 交给 poke 域自行判定（冷却键、群/私聊形态自解析） | P3 |
| B7 | `domains/core/decision/ingress.py:74 DEFAULT_SOURCES` |  Designed 的 `AdapterSource` 插件点（can_handle/normalize/kind）+ `OneBotSource`/`TelegramSource` | **P2（死代码）** |

**B7 展开（U1-08，P2）**：`DEFAULT_SOURCES`/`AdapterSource` 在**生产零消费者**——实跑 `grep -rn "DEFAULT_SOURCES\|AdapterSource\|OneBotSource" --include=*.py plugins/ tests/`：除定义文件与 `decision/__init__.py` 的惰性导出表外，唯一消费者是 `tests/test_decision_engine_shadow.py:402,412`。且 `MailSource` 缺席（`DEFAULT_SOURCES` 只 2 项，而 mail 在生产是注册适配器）。
根因：B2 阶段 0 只搭骨架（该文件 docstring `:3-7` 自己写明「事件入口仍由旧 matcher 驱动……迁移阶段 2/3 落地」），但**没有任何机器门锁「骨架不得长期悬空」**，于是它成了第二套摄取契约的名义入口却零流量。
改法：①`_incoming_from_nonebot_event` 的实现体迁进 `domains/core/decision/ingress.py::normalize_event`，根 `__init__.py` 只留 re-export；②`DEFAULT_SOURCES` 补 `MailSource`（把 `:1317-1326` 的 mail 分支搬进去）；③加一条常驻门：`pipeline`/`handler` 不得直接 import `_incoming_from_nonebot_event`（AST 门：该符号在 `plugins/**` 的引用点必须 ⊆ {ingress.py 自身, 兼容 re-export 行}）。
验证：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_decision_engine_shadow.py tests/test_v21_s0_collect.py -p no:cacheprovider --basetemp="$TEMP/u1-ingress" -q`

### 2.5 40 个路由谓词各自读原始 event（结构性、非缺陷，但锁定了双解析）

`_is_music_event`/`_is_weather_event`/…共 40 个 `async def _is_*_event(state, event)` 全部经 `_cached_route_decision(state, event, …)` → `event.get_plaintext()`（`:832`）。这是 NoneBot 匹配阶段的必然（构造契约前就要决定谁来构造），**不计为旁路**；但它带来 §4.2 的双文本口径问题与 §4.4 的重复段解析开销。

---

## §3 被动 matcher 旁路逐个判定（任务书点名的 7 个）

| 席位点名项 | 坐标 | 绕开中央摄取？ | 复制了文本提取？ | 复制了出站？ | 判定 |
|---|---|---|---|---|---|
| campus（p8, block=False） | 注册 `:4997`，体 `:5002-5030`，域件 `domains/assistant/campus/campus.py:94 record()` + `campus_store.py` | **是（全绕）** | **是**（`get_plaintext` + sender card/nickname 双份） | **是**（`send_queue.submit` 直投，不经 pipeline/gate/review/audit） | **U1-09 P1** |
| meme_library_listener | `:5940` → `meme_library_listener.py:247` | **是（全绕）** | 是（`_segment_urls:56`） | 否（不发） | **U1-10 P1** |
| reactions（emoji_like + 主动贴） | 收 `:5302`；发 `:7330`（chat 链内） | 收=是；**发=否**（走 `message.*`，仅 `message_id` 回读 event） | 是（`session_key_from_ids`） | 否 | U1-11 P2 + §6.3 |
| media_archive get_msg 反查注入 | `:8060-8128 _enrich_media_archive_message` | **否**（先 `_incoming_from_nonebot_event`，后 enrich 注入契约字段 `reply_media_segments`/`chat_record_text`） | 是（`_forward_message_text_sync` 二次实现，见 U1-02） | 否 | **形态正确，实现重复** |
| auto_send（p13, block=True） | `:4772` 谓词 + `:7215 command_text = event.get_plaintext()` → `_run_capability_through_pipeline` | 否（走通用管道→契约） | 是（先洗一次，再交 ingestion 洗一次；且能力拿到的 `command_text` 与 `message.plain_text` 是两个字符串） | 否 | U1-12 P3 |
| daily_assist（p42, block=True） | `:6118` + `:8479 → _run_simple_capability` | 否 | 否 | 否 | **未见缺陷** |
| 群摘要（digest） | 注册：无（`_register_digest_push_scheduler:3215` 定时器驱动） | 不适用（非入站） | — | 走 `SendRequest`+`send_queue`，出站统一 | **未见入站旁路**；其真实缺陷是 §5.3 键口径 |

### 3.1 U1-09（P1）campus = 任务书定义的「第二套读事件→拼文本→落库→出站」全四段复刻

- **坐标**：`__init__.py:5002-5030`（handler）+ `domains/assistant/campus/campus.py:94-135`（record/决策）+ `campus_store.py:17 message_id TEXT PRIMARY KEY`。
- **锚点**：`plain_text = event.get_plaintext().strip()` 与 `request = await asyncio.to_thread(campus_service.record,`。
- **四段复刻证据**：
  1. **读事件**：`isinstance(event, GroupMessageEvent)` + `getattr(event,"group_id")` + `event.get_user_id()`，无契约。
  2. **拼文本**：`event.get_plaintext().strip()`（`:5016`，`try/except` 自兜底）；`sender_name = getattr(sender,"card") or getattr(sender,"nickname")`（`:5008-5014`）与摄取层 `:1469 sender_display_name = sender_card or sender_nickname or None` 是同义两份。
  3. **落库**：自建 `campus_messages` 表（`campus_store.py:17`），幂等键自定（`campus.py:115`）。
  4. **出站**：`send_queue.submit(request)`（`:5030`）**直投队列**，绕过 `RuntimePipeline` → 不过 `policy/gate`（黑白名单/安静时间/限流）、不过 Review、不过 `plain_text` 出站脱敏链、不落 `AuditRecord`/`ReceiptRepository`。
- **为什么这条最危险**：它是唯一「四段全复刻且自带出站直投」的旁路，且 `priority=8 + block=False + 每条群消息都跑`（`:4997-5001` 谓词只判 `isinstance`，门在 handler 内 `matches()`）。任何将来加进 pipeline 的入站治理（幂等 §6、注入防护、限流、审计）对它**自动无效**。
- **改法 before→after**：
  ```python
  # before（:5002-5030 摘要）
  plain_text = event.get_plaintext().strip()
  request = await asyncio.to_thread(campus_service.record, bot_id=…, group_id=…,
                                    sender_id=…, sender_name=…, text=plain_text, message_id=…)
  if request is not None: send_queue.submit(request)
  # after（两步，风险递增可分批）
  # 步1（低风险）：文本/发送者一律取自契约，消除复刻
  message = _incoming_from_nonebot_event(event, bot_id=bot_id, feature_enabled=switches.enabled)
  request = await asyncio.to_thread(campus_service.record, …, text=message.plain_text,
                                    sender_name=message.sender_display_name or "", …)
  # 步2（根治）：把 campus_service.record 包成 capability 走 pipeline.handle_async，
  #              返回 CapabilityResult(kind="none") + 由 pipeline 统一 submit，
  #               campus 从此受 gate/审计/幂等管辖
  ```
  注：步2 会改变「三重来源门任一空即整链不装配」的现有短路语义（`:4994 if campus_service is not None`），须在门控等价性上先出评审；**步1 零行为变化，建议先落**。
- **验证**：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_campus_digest.py -p no:cacheprovider --basetemp="$TEMP/u1-campus" -q`

### 3.2 U1-10（P1）meme 图库监听 = 第二套「读事件→洗段→下载→落库」，且**是本席发现的 SSRF 单点缺口**

见 §4.3（安全面为主条目，此处登记旁路事实）。坐标 `:5940`，锚点 `await absorb_event_images(bot, event, config, meme_library_store)`。

---

## §4 文本/段提取的同义实现清单（差异点逐列）

### 4.1 段→纯文本：4 份实现

| 实现 | 坐标 | at | reply | image/voice/video | 卡片(json/xml/app) | 转发 |
|---|---|---|---|---|---|---|
| N1 `normalize_message_segments`（权威） | `message_context.py:90` | 丢（透传段不进文本） | 丢（由 chain 负责） | **打标签** `[图片]/[语音]/[视频]/[动图]/[圆形视频]/[文件]` | 透传无名 | **`[转发/聊天记录]` 包裹 + 递归 5 层** |
| N2 `event.get_plaintext()`（NoneBot 原生） | `:832/:799/:4744/:4972/:4978/:5016/:5460/:5560/:5669/:6144/:6407/:7215/:8238` | 视适配器 | 视适配器 | **全丢（空串）** | 丢 | 丢 |
| N3 `_segments_to_text`（引用链专用） | `message_context.py:187` | 丢 | 丢 | 打标签但**分离返回** `media_labels` | — | 递归 N1 |
| N4 `_plain_of`（跨适配器兜底） | `message_context.py:209` | — | — | 依赖 N3/N1 | — | — |

**U1-13（P2，与 U1-03 同根，独立成条）**｜`__init__.py:832`｜锚点 `text = _effective_route_text(event) if effective_text else event.get_plaintext()`
根因：**路由用的文本 ≠ 能力看到的文本**。路由用 N2（媒体全丢，纯图/纯 TG 照片 → `""`），摄取用 N1（`"[图片]"`）。实跑取证：

```
classify(''      ) -> kind=RouteKind.IGNORE
classify('[图片]' ) -> kind=RouteKind.CHAT
```

即同一语义内容，走路由那套文本得 IGNORE、走摄取那套文本得 CHAT。U1-03 的四个媒体类型漏判之所以致命，正是因为路由落在 N2 上。
改法 before→after：`_cached_route_decision` 的 `text` 改取 `normalize_message_segments(_extract_onebot_raw_segments(event)).plain_text`（N1），并与摄取共用同一次段解析（见 4.4）；`_effective_route_text:799` 同理（它已经自己再解一次段拿 URL，见 4.2）。
验证：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_route_order_semantics.py tests/test_white2_strict_mention.py tests/test_nonebot_event_adapters.py -p no:cacheprovider --basetemp="$TEMP/u1-routetext" -q` + 新增锁：photo-only 事件 → `_is_plain_chat_event` 为 True。

### 4.2 段→URL：**3 份**实现（同一覆盖集手抄三遍）

| 实现 | 坐标 | 段型集合 | 键元组 | 差异 |
|---|---|---|---|---|
| V1 `_urls_from_message_segments` | `__init__.py:707` | `{"json","xml","share","app","card","markdown"}`（**未 lower()**） | `("data","content","url","meta","text")` | 无 `isinstance(segment, dict)` 守卫 |
| V2 `_urls_from_segments` | `domains/core/decision/engine.py:372` | `_URL_SEGMENT_TYPES`（`:359` 同 6 名） | `_URL_SEGMENT_KEYS`（`:360` 同 5 名） | 多 dict 守卫 + `type.lower()`；docstring 自称「对齐 `__init__._urls_from_message_segments`」 |
| V3 `_segment_urls` | `domains/meme/sources/meme_library_listener.py:56` | `{"image","mface","sticker"}`（**完全不同的语义：取媒体段的 url，不是卡片里的链接**） | 只读 `data["url"]` | 接受 MessageSegment 对象或 dict 双形态 |

取证命令：`grep -rn "def _segment_urls\|def _urls_from_message_segments\|def _urls_from_segments" --include=*.py plugins/` → 3 命中（即上表）。
**U1-14（P2）**：V1/V2 是**纯复制**（V2 docstring 以"对齐"两字代替复用），一旦卡片段型新增（如 `nodejson`）必漂移；V3 名字与 V1 同义但语义不同，是「同义实现清单」里最容易误用的一份。
改法：V1 提为 `domains/chat_reply/ingest/message_context.py::urls_from_segments(raw_segments, *, card_types=..., keys=...)`（段型/键作参数并导出为模块常量），V1/V2 全部改为 import 它；V3 更名 `media_segment_urls` 以消除同名歧义。
验证：`grep -rn '"json", "xml", "share", "app", "card", "markdown"' plugins/ --include=*.py` 命中数应为 0（字面量收进常量）。

### 4.3 U1-15（P1，安全）meme 图库下载链**未过 SSRF 咽喉**，与自家三处同类实现全部不一致

- **坐标**：`domains/meme/sources/meme_library_listener.py:76-100 _download_once`（调用点 `:279`）。
- **锚点**：`async def _download_once(url: str, *, max_bytes: int, proxy: str)` 与 `"follow_redirects": True`。
- **根因**：项目把 `check_download_url` 定为 SSRF 唯一咽喉，且明文要求「入口 + 落点双查」（台账 #31：`efe7b79 SSRF 咽喉双点`）。实证比对：

| 下载实现 | 入口查 `check_download_url` | 重定向落点复查 |
|---|---|---|
| `media_archive.py:200,220` | ✓ | ✓（`:200` 对 `newurl`） |
| `notes.py:252,256` | ✓ | ✓（`final_url`） |
| `eat.py:335,345` | ✓ | ✓（`final_url`） |
| `file_gateway.py:277,281` | ✓ | — |
| **`meme_library_listener.py:76`** | **✗ 零命中** | **✗（`follow_redirects=True` 直放）** |

  取证命令与输出：`grep -n "ssrf\|SSRF\|check_download\|127\.\|localhost\|192\.168" plugins/bot_unified_runtime/domains/meme/sources/meme_library_listener.py` → **exit 1 / 0 命中**（该文件不 import 护栏）。
- **可达面**：URL 来自群消息 `image/mface/sticker` 段的 `data.url`（`:69`），**任意群成员可诱发**，服务端直接 GET，且跟随重定向、无协议白名单、无内网判定。缓解事实（如实记录）：`bot_meme_library_enabled` 缺省 `False`（`config.py:523`，`.env.example:411` 亦 `false`），且 `absorb_event_images` 有 allow/deny 群名单门（`:256-261`）；**但本席禁读 `.env`，无法确认生产是否已开启**（AGENTS.md 功能表把「表情包·群图收库」列为在运功能，倾向已开）。
- **改法 before→after**：
  ```python
  # before（:278-283 摘要）
  for url in urls[:4]:
      result = await _download_once(url, max_bytes=max_bytes, proxy=proxy)
  # after（复用既有咽喉，零新逻辑）
  from plugins.bot_unified_runtime.domains.files.sources.downloader import check_download_url
  for url in urls[:4]:
      try:
          check_download_url(url)                      # 入口查
      except Exception:
          continue
      result = await _download_once(url, max_bytes=max_bytes, proxy=proxy)
      # 并把 _download_once 的 follow_redirects 改为 False，读 3xx 的 Location 后再查一次（与 notes:256 同构）
  ```
  更彻底：整条 `absorb_event_images` 的下载改走 `sources/downloader`（§3.2 的摄取统一一并处置），则护栏自动继承。
- **验证**：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_parser_ssrf_guard.py tests/test_meme_domain_fixes.py -p no:cacheprovider --basetemp="$TEMP/u1-ssrf" -q`；补一条负锁：`_download_once("http://127.0.0.1:8742/x")` 必须被拒。

### 4.4 一条聊天消息里的重复段解析（性能/一致性卫生）

`_is_plain_chat_event`（`:4740` `_extract_onebot_raw_segments(event)`）+ `_handle_chat`（`:7279` 同一调用）+ `_effective_route_text`（`:800` 若 CONTENT 谓词命中则第三次）。同一段列表被解析 2–3 次、每次新建 dict。
**U1-16（P3）**｜锚点 `event_segments = _extract_onebot_raw_segments(event)`。
改法：段解析一次、结果挂 `state["_bot_unified_segments"]`（与 `_ROUTE_DECISION_STATE_KEY:810` 同款事件级缓存），三处共读。
验证：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_perf_regression.py -p no:cacheprovider --basetemp="$TEMP/u1-perf" -q`（该文件即吞吐棘轮）。

### 4.5 `_extract_onebot_raw_segments` vs `_onebot_segments_from_message_payload`（同函数双写）

`__init__.py:550` 与 `:490` 逐行同构（仅"源是 event 还是 get_msg payload"不同）。**U1-17（P3）**，改法=后者以前者实现（`payload→message` 取值后调同一函数）。
锚点：`segments.append(` + `"data": dict(seg_data) if isinstance(seg_data, dict) else {},`（两处字面量相同）。

### 4.6 段类型白名单：一册 vs 六册（本席最常见的缺陷形态）

权威册 `message_context.py:57-68`（10 媒体 + 4 表情）。其余手抄册（`grep -rn '{"image"' --include=*.py plugins/` 取证）：

| 册 | 坐标 | 成员 | 与权威册的差 |
|---|---|---|---|
| S1 `visual_types` | `__init__.py:669` | image,face,mface,marketface,sticker,video | **缺 photo/animation/video_note/emoji**（U1-03 实锤） |
| S2 `AUDIO_SEGMENT_TYPES` | `__init__.py:678` | record,voice,audio | 与权威一致 ✓ |
| S3 `FORWARD_SEGMENT_TYPES` | `__init__.py:684` | forward,chat_history,messages | 与权威一致 ✓ |
| S4 `_MEDIA_SEGMENT_TYPES` | `domains/core/decision/engine.py:358` | image,record,video,forward | **缺 photo/sticker/animation/video_note/mface/emoji + 缺 chat_history/messages** |
| S5 `_MEDIA_SEGMENT_TYPES` | `media_archive.py:68` | image,photo,sticker,mface,animation | 另有 `_VIDEO_SEGMENT_TYPES:69` 补 video/video_note → **合计覆盖完整 ✓**（不计缺陷，但仍是第三册） |
| S6 `_IMAGE_SEGMENT_TYPES` | `notes.py:204` | image,animation | 笔记语义收窄，判 **可接受**（只收可存图片） |

**U1-18（P2）**：S4（决策引擎影子判定）与权威册差 6 个类型，**且该类差异正是它 docstring 自称要对齐的 `_is_plain_chat_event` 特例**（`engine.py:352` 注释 `"纯媒体/转发消息放行聊天链路（_is_plain_chat_event 特例）"`）。影子对照因此系统性低估媒体消息，接管阶段（Phase 2）会带着这个偏差去"证明分歧很小"。
改法：`message_context.py` 导出 `VISUAL_SEGMENT_TYPES / AUDIO_SEGMENT_TYPES / FORWARD_SEGMENT_TYPES` 三枚 frozenset 为唯一册，S1/S4/S5 全部改 import（S6 若有意收窄须显式注释 + 单测钉死语义）。
验证：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_decision_engine_shadow.py tests/test_media_archive.py -p no:cacheprovider --basetemp="$TEMP/u1-sets" -q`（已核 `ls tests | grep -i shadow` → 唯一实存文件即 `test_decision_engine_shadow.py`）。

### 4.7 实跑矩阵（一证盖 S1 全条，U1-03/04 的机器证据）

命令：venv + `PYTHONDONTWRITEBYTECODE=1`，对 13 种段型同时跑 N1 归一与 S1/S2 判定，实跑输出：

```
image        normalized_label='[图片]'       visual=True   audio=False
photo        normalized_label='[图片]'       visual=False  audio=False
sticker      normalized_label='[表情包]'      visual=True   audio=False
animation    normalized_label='[动图]'       visual=False  audio=False
video_note   normalized_label='[圆形视频]'     visual=False  audio=False
video        normalized_label='[视频]'       visual=True   audio=False
record       normalized_label='[语音]'       visual=False  audio=True
voice        normalized_label='[语音]'       visual=False  audio=True
audio        normalized_label='[音频]'       visual=False  audio=True
face         normalized_label='[Emoji:表情]' visual=True   audio=False
mface        normalized_label='[Emoji:表情]' visual=True   audio=False
marketface   normalized_label='[Emoji:表情]' visual=True   audio=False
emoji        normalized_label='[Emoji:表情]' visual=False  audio=False
```

读法：**同一类型在 N1 里已被承认是媒体并产出标签，在 S1 里却不被承认为视觉内容** → `photo / animation / video_note / emoji` 四型双册不一致，实锤、非推断。

---

## §6 入站幂等/去重口径

### 6.1 中央幂等位：存在、已接线、**缺省关、且只覆盖 pipeline**

- 实现：`domains/chat_reply/runtime/event_idempotency.py`（`EventIdempotencyTable` 进程内 TTL / `SqliteEventIdempotencyTable` 跨重启），构造器 `build_event_idempotency_table:201`。
- 键：`build_event_dedupe_key:25` → `f"{adapter}|{bot_id}|{message_id}"`，**`message_id` 缺失即返回空串并跳过去重**（`:29-31`）。
- 接线：`__init__.py:3806` 装配进 pipeline。
- 消费点：`pipeline.py:1053 _claim_event`（**全库唯一调用侧**），键入参来自 `IncomingMessage`。
- 缺省：`config.py:38 bot_event_idempotency_enabled: bool = False` → 生产**默认不启用**（AGENTS.md 第三部分写作「幂等(可选)」，与实况一致，不计虚报）。

**U1-19（P2）**｜`pipeline.py:1053-1064`｜锚点 `def _claim_event(self, message: IncomingMessage, capability_id: str)`
根因：幂等位被放在 **pipeline 内部**，而 §2/§3 的 6 条旁路（campus / meme_absorb / dirty_guard / group_upload / emoji_like / poke）**没有一个进 pipeline**，故中央幂等对它们结构性无效；同时 NoneBot 在适配器重连时会重投同一 `message_id`（`_transcode_record_segments:1150` 注释自认「NapCat 偶发挂起」，`campus.py:8` 注释自认「NapCat 断线重连重发不会双推」=该现象已被当作常态处理）。
改法：把「一次事件 claim」上移到摄取层出口——`_incoming_from_nonebot_event` 之后、任何 handler 分支之前统一 `claim`，键取 `(adapter, bot_id, message_id, matcher_name)`；旁路要么并入 pipeline（§3.1 步2），要么显式声明自带去重并纳入同一登记表。
验证：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_event_idempotency.py tests/test_a18_gate_idempotency_rollback.py -p no:cacheprovider --basetemp="$TEMP/u1-idem" -q`

### 6.2 各旁路自建去重表：四套键，三种语义（无统一口径）

| 去重位 | 坐标 | 键 | 存储 | TTL/裁剪 | 与中央键关系 |
|---|---|---|---|---|---|
| 中央 | `event_idempotency.py:25` | `adapter\|bot_id\|message_id` | InMemory 或 SQLite | TTL 3600s / max 4096 | — |
| campus | `campus_store.py:17` | `message_id`（**裸 id，无 adapter/bot 前缀**；缺失时退 `f"{bot_id}:{group_id}:{timestamp:.0f}"`，`campus.py:115-117`） | SQLite `campus_messages.message_id PRIMARY KEY` | 90 天 `prune`（`:101`） | **不兼容**：同一条 QQ 消息在中央是 `nonebot\|1\|99`、在 campus 是 `99` |
| reactions | `engine.py:606` `message_dedupe=(key, msg_key)` | (会话键, 消息键) 二元组 | 进程内 `OrderedDict` `_reacted`/`_rolled` | LRU | 不兼容（无 bot_id 维度） |
| poke | `poke.py:30 accept(event, bot_id, enabled, cooldown, group_cooldown, probability)` | 发送者维度最小间隔（台账 #22 R3 记 45s） | InMemory + SQLite 双实现 | 时间窗 | **不是消息级幂等**，与 message_id 无关 |
| mail | `mail_bridge.py:263 mail_event_dedupe_id` → `claim_notification(mail_id, account)` | `mail_id`（带 fallback 布尔，`:381`） | `mail_bridge_state` | — | 独立命名空间（合理：邮件无 message_id） |
| 出站侧 | `SendRequest.dedupe_key`（`campus.py:166 f"campus_fwd:{message_id}"`、`:3190 f"digest_push:{group_id}:{today}"`） | 业务前缀 + 标识 | SQLite 发送队列 part 级 | — | 出站幂等，与入站不重叠（设计正确） |

**U1-20（P2）**｜`campus.py:115-117`｜锚点 `safe_id = str(message_id).strip() or (`
根因：campus 的**空 id 兜底键含秒级时间戳** → 同一条重投消息两次得到两个不同主键 → **该场景下 campus 自身也不幂等**，SnowLuma 跨秒重投即双推双落。这与 `campus.py:8` docstring 的承诺（「message_id 去重，NapCat 断线重连重发不会双推」）**直接矛盾**。
改法：兜底键改内容哈希 `f"fallback:{hashlib.sha1(f'{bot_id}|{group_id}|{sender_id}|{text}'.encode()).hexdigest()[:16]}"`（同内容同键），并在 `record_message` 返回值上区分「重复」与「空 id」（现 `campus_store.py:56` 注释「message_id 重复（或为空）返回 False」把两态合并，掩盖了缺陷）。
验证：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_campus_digest.py -p no:cacheprovider --basetemp="$TEMP/u1-campus2" -q`
**双计判定**：因 §6.1 中央位缺省关且旁路不进 pipeline，当前**不存在双计**（各表互不相交）；一旦中央幂等上移（U1-19 改法），必须同时把 campus/reaction 的自建键改为**派生自中央键**，否则从「无双计」翻成「双拒」。这条顺序约束是本席对接手者的硬提醒。

### 6.3 U1-11（P2）表情回应的写入键与读取键语义错位（谁贴的 vs 谁在说话）

- 写：`__init__.py:5308 _REACTION_BUFFER.record(reaction_event)`，其 `session_key = session_key_from_ids(group_id, event.user_id)`（`engine.py:380`）——OneBot `group_msg_emoji_like.user_id` 是**贴表情的人**。
- 读：`__init__.py:2672 _describe_chat_reactions(message.session_id)`（经 `_build_reactions_describe:2666` ← `providers.py:412`），`message.session_id` 是**当前发言人的会话键**。
- 结论：张三给李四的消息贴表情 → 记在 `group_G_张三` 桶；李四下一轮说话读 `group_G_李四` → **读不到**；张三自己下一轮说话才读到，且此时注入的是「张三给了别人消息贴表情」，与他正说的话无关。`describe()` 渲染含 `who`/`message_id`（`engine.py:546-555`）故不错报内容，但**该分区在群聊里系统性错位/丢失**。
- 锚点：`session_key = session_key_from_ids(group_id, user_id)`（写）与 `reactions_describe(session_id)`（读）。
- 严重度定级理由：不炸、不错数据，只是语境注入丢失 → P2 而非 P1。诚实附注：`engine.py:366` 自己标了「**生产实机待验证**」，本席禁真实发送，故只主张键语义错位的代码事实，不主张线上观测样本。
- 改法：`ReactionEvent` 加 `target_session_key`（被贴消息所在会话 = 群维度键），写入按 `target_session_key`、读取按 `session_id` 的群维度投影（依赖 §5.3 的键规范化先落地）。
- 验证：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_reaction_store.py tests/test_reactions.py tests/test_poke_unified_reaction_b10.py -p no:cacheprovider --basetemp="$TEMP/u1-react" -q`（三文件均已 `ls tests | grep -iE "shadow|reaction|send_queue|transport"` 核实存）。

---

## §7 多适配器对等性（OneBot / Telegram / Mail / Console）

### 7.1 注册实况（先纠一处文档口径）

`grep -n "register_adapter" bot.py` → **3 处**：`:408 OneBotV11Adapter`、`:409 ResilientTelegramAdapter`、`:483 ResilientMailAdapter`。
**U1-21（P3，文档）**：AGENTS.md「附带 Telegram / Mail / **Console** 适配器」与实况不符——**Console 未注册 NoneBot 适配器**。所谓 console 是 `domains/ops/smoke/console_chat.py`（`scripts/dev.ps1:652` 以 `-m …console_chat` 拉起的自研 REPL），它 **直接构造 `IncomingMessage`（`:472`，`platform="console" adapter="console-repl" session_id="console:repl"`）**，是一条合法的离线/工具用第二入站面，但**不是适配器**，也不经摄取层。同类直构还有 `pipeline/backend_unit.py:209`、`runtime/prompt_preview.py:53`、`admin/debug.py:410`、`monitor/alerts.py:536`、`smoke/route_demo.py:138,183`、`smoke/smoke.py:307,606,787`。
判定：**这些是「合成入站」，用于预览/诊断/烟测，非生产消息路径，不计为旁路缺陷**；但应在契约层显式登记（见改法），否则新读者无法区分「合法合成」与「违规自建」。
改法：新建工厂 `make_synthetic_incoming(*, source: Literal["console-repl","prompt-preview","smoke","alert","debug","backend-unit"], text, …)`，内部仍调 `_incoming_from_nonebot_event` 之外的受控构造点，并让 AST 门把 `IncomingMessage(` 的生产命中收敛到「ingress + 工厂 + 测试」三处。
验证：`grep -rn "IncomingMessage(" --include=*.py plugins/ | grep -v tmp-test | wc -l`（现 **17** 命中，目标 ≤4）。

### 7.2 入站对等性矩阵（代码事实）

| 维度 | OneBot | Telegram | Mail | 判定 |
|---|---|---|---|---|
| 适配器名推断 | `:1297 else "onebot v11"` | `:1292 ".telegram" in module_name` | `:1294 ".mail"` | 靠**模块名字符串**猜，非 `bot.adapter.get_name()`（后者已有 `_bot_adapter_name:1535` 正解却未用于摄取） | 
| `session_type` 判定 | `:1344 "group" in session_id` 子串猜 | `:1330 startswith("channel_")` / `"group" in` | `:1320` 显式 `SessionType.EMAIL` | OneBot 侧最弱（见 §5.3 改法①） |
| `sender_display_name` | `:1459-1469` card→nickname | **恒 None** | 恒 None | **U1-22（P2）** |
| 媒体段 | image/record/video | photo/sticker/animation/video_note/voice/audio | 附件走 subject 拼接 `:1326` | 归一层已覆盖，判定层漏（U1-03） |
| file_id→字节 | `get_record` 转码 `:1125` | `enrich_telegram_file_segments` | 无 | 均只在 chat 链（U1-01） |
| `mentions_bot` 硬点名 | `is_tome()` + at 段 `:1416-1419` | 只 `is_tome()`（at 段被 `normalized_adapter not in {"telegram","mail"}` 显式跳过） | 恒 `:1489` PRIVATE/EMAIL→True | 设计有意，**未见缺陷** |
| 引用链 | `event.reply` + get_msg 反查 | `event.reply_to_message` 原生递归 | 无 | 两路在 `collect_reply_chain:366` 合一，**未见缺陷** |
| 出站 sender 分叉 | `gateway.py:37 adapter in {"onebot","onebot v11"}` | `nonebot.py:345/373/433` 三处 `== "telegram"` | nonebot_sender | 见 U1-23 |

**U1-22（P2）**｜`__init__.py:1459-1461`｜锚点 `onebot_sender = getattr(event, "sender", None)`
根因：摄取只读 `sender.card / sender.nickname`。Telegram 的 `sender` 是 `User`，名字在 `first_name`（少数 `username`）。全树 `grep -rn "first_name" --include=*.py plugins/` → **仅 1 命中**：`message_context.py:253`（引用链的 `_sender_of` 里 `card or nickname or first_name`）。
即：**同一份 TG 用户名，引用链取得到、当前发言人取不到** → TG 群聊里人格上下文与称谓层拿不到说话人显示名，而 `:1458` 注释「TG/Mail 事件无 sender.card/nickname 形态，自然落 None（**各有独立摄取路径，不在此扩**）」里的"独立摄取路径"**在代码中不存在**（取证：无第二处 TG 摄取，`grep -rn "first_name"` 仅 1 命中）。注释本身是错误陈述。
改法：`:1461` 后补 `or str(getattr(onebot_sender,"first_name","") or "").strip()`，并把变量名 `onebot_sender` 改为 `event_sender`（消除"仅 OneBot"的误导）。
验证：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_b07_sender_level_ingest.py tests/test_nonebot_event_adapters.py -p no:cacheprovider --basetemp="$TEMP/u1-tgname" -q` + 新增 TG 形态事件断言 `sender_display_name == "..."`。

**U1-23（P3）**｜`domains/transport/sender/gateway.py:24-28 + :37`｜锚点 `if not adapter_name or adapter_name in {"onebot", "onebot v11"}:`
根因：gateway 自带一份内联 `_adapter_name`（原样 lower），**不复用**已有的中央映射 `_normalize_adapter_name:1522`（该函数会把 `nonebot`/`qq` 也归到 `onebot`）。今天靠 `get_name()=="OneBot V11"` 恰好命中；一旦某处传入 `adapter="nonebot"`（正是 `IncomingMessage.adapter:1343` 写的字面量），gateway 会落到 `else` 分支。
同时 `platform/adapter` 字面量在三个构造点分叉（取证）：`:1342 platform="qq" adapter="nonebot"`、`:1836 platform="onebot" adapter="onebot.v11"`、`:4323 platform="nonebot" adapter=destination.transport`。**同一 QQ 渠道在 `conversation_turns.platform` 里最多可出现 `qq / onebot / nonebot` 三个值**（`_record_chat_history_turn:2115` 原样透传 `message.platform`）。当前无代码按 platform 过滤（`grep -rn 'platform == "qq"' plugins/` → 0 命中），故**今天不致错**，但任何按 platform 分组统计/审计/WebUI 面板都会把一条渠道切成三条 → P3 现降 P2 视消费者而定，本席按 P3 记账并标注升级条件。
改法：①platform/adapter 取值全部经 `domains/core/contracts` 导出的枚举常量，禁止字面量；②`gateway._adapter_name` 改调 `_normalize_adapter_name`；③`:1343` 的 `adapter="nonebot"` 与 `:1342` 的 `platform="qq"` 统一为枚举。
验证：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_unified_delivery_routes.py tests/test_auditfix_sender_queue.py -p no:cacheprovider --basetemp="$TEMP/u1-adapter" -q`（两文件均已核实存；`ls tests | grep -iE "queue|gateway"` 另得 `test_unified_gateways.py` 可一并跑）。

### 7.4 隐藏假设「仅 OneBot 才走 X」全清单（任务书点名项）

| 假设 | 坐标 | 是否成立 |
|---|---|---|
| `_transcode_record_segments` 用 `bot.call_api("get_record")` | `:1149` | **安全**：外层按段型 `record` 过滤（`:1137`），TG 的 voice 段型不匹配 |
| `_make_onebot_reply_lookup` 用 `bot.get_msg(message_id=int(...))` | `:517-523` | **部分**：`int(message_id)` 对 TG 的大整数 id 成立，但 `except ValueError` 已兜；仅 chat 链调用 |
| dirty_guard `bot.call_api("delete_msg")` | `:4986` | **OneBot-only**，但谓词要求 `getattr(event,"group_id")`，TG 也有 group_id → 理论可命中，`call_api` 在 TG bot 上必抛，被 `except` 静默（`:4987`）→ 静默失效，无实害，记 P3 |
| `_is_*_event` 谓词用 `_extract_onebot_raw_segments(event)` | `:4740` | 名不符实但实现通用（getattr type/data），**对 TG 有效** |
| `_handle_chat` 里 `".mail" not in event_module` 才贴表情 | `:7329` | 显式 mail 豁免，注释缺位（为何 TG 可贴但 mail 不可未说明），P3 |

**未见缺陷项（正面记录）**：取证 5 处「仅 OneBot」嫌疑点，其中 4 处经代码路径证伪或已被兜住，1 处（`delete_msg`）为静默降级；**摄取层对四路适配器的分支收敛度总体好于出站层**。

---

## §8 机器门与登记表的可信度（本席最重要的元发现）

### 8.1 U1-24（P2）`outbound_registry` 50 条 matcher 坐标**全部失效**，且自有测试只查格式不查真伪

- **坐标**：`domains/core/decision/outbound_registry.py:421-470`（`MatcherEntry` 表）；`tests/test_outbound_v21.py:646-653 test_matcher_locations_unique_and_wellformed`。
- **锚点**：`MatcherEntry("chat", "__init__.py:4407", "on_message", 50, "chat")` 与 `assert file_part and line_part.isdigit()`。
- **实跑取证**（AST + 登记表联查，venv 解释器）：
  ```
  registry entries: 50 | resolvable via '<name> = on_*(' : 49 | unresolved names: 1
  offset distribution (actual_line - registered_line): [(568,18),(374,9),(569,6),(489,4),(536,4),(416,3)]
  min/max offset: 374 607
  0/50 条登记坐标所在行含其登记名
  ```
  即 49/50 条可解析的坐标全部偏 374–607 行（多个离散偏移 = 历史多波次插码所致），1 条（`campus_record_matcher`）连名字都对不上源码。
- **附带事实错误 1 条**：`MatcherEntry("campus_record_matcher", …, priority=None)`，而源码 `__init__.py:4999` 实为 `priority=8`。
- **为什么测试还绿**：`test_outbound_v21.py:646` 只断言坐标字符串**格式良好且互不相同**，从不比对源码实际行。HANDOFF-V21R5 §C3 宣称「测试坐标钉死 + 陈旧坐标负锁（棘轮）」——**钉的是 4 条 BYPASS_SUSPECT 的字符串，不是 50 条 matcher 的真伪**。
- **与本席 mandate 的关系**：这张表是「哪些入站/出站面尚未统一」的机器可读清单。清单坐标全失效 = 后续任何按表施工（收编、验收、回归）都要先人肉重新定位，且**漂移不可见**。
- **改法 before→after**：
  ```python
  # 测试补一条真伪门（tests/test_outbound_v21.py 内新增）
  def test_matcher_locations_point_at_real_source(tmp_registry) -> None:
      """登记表 location 必须指向源码中真实的 matcher 注册行。"""
      root = Path("plugins/bot_unified_runtime")
      src = (root / "__init__.py").read_text(encoding="utf-8").splitlines()
      decl = {}
      for i, line in enumerate(src, 1):
          m = re.match(r"\s{4}([A-Za-z_]\w*) = on_(?:message|notice|command)\(", line)
          if m:
              decl[m.group(1)] = i
      for entry in tmp_registry.matchers:
          name = entry.name.removesuffix("_matcher")
          assert name in decl, f"登记表名 {entry.name} 在源码中无对应 matcher"
          assert decl[name] == int(entry.location.rpartition(":")[2]), (
              f"{entry.name} 坐标陈旧：登记 {entry.location} 实为 __init__.py:{decl[name]}")
  ```
  更稳的形态=登记表改存**符号名 + 锚点字符串**（与 AGENTS.md 铁律「行号漂移用锚点重定位」一致），坐标由该门在运行时推导，不再手写行号。
- **验证**：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_outbound_v21.py -p no:cacheprovider --basetemp="$TEMP/u1-reg" -q`（加门后首轮必红，据此一次性刷新坐标）。

---

## §9 上轮审计（audit-20260919）与本席的复核

本席范围与上轮（渲染/WebUI）**零重叠**，但复核了两条与本席相关者：

| 上轮条 | 复核结论 | 证据 |
|---|---|---|
| P0-2 `sources/web_search.py` 垫片缺失 → `capability_protocols.py:1273` 运行期 ImportError | **已消解**：HANDOFF-V21R5 §D 主代理席记「`sources.web_search` 垫片退役、消费方改指 canonical，连带修 `capability_protocols.py:1425 _SEARCH_REF` 改指 `domains/core/search`」；本席实跑 `grep -rn "sources import web_search\|sources\.web_search" plugins/` → **仅剩 1 处无关命中（`domains/core/search/web_search.py` 自身 docstring），`capability_protocols.py` 零命中** → 上轮该条不再成立 | grep 输出（本席 §8 后跑） |
| P0-1 `test_webui_http` 日历炸弹 | **不在本席范围，未复核**（前端在飞禁改面邻接） | — |
| 上轮 §3.7「qx.json 链路核验通过」 | **仍成立**：`plugins/bot_unified_runtime/domains/weather/assets/qx.json` 在位，362774 字节（本席清缓存后复核，见 §10） | `ls -la` 输出 |

---

## §10 中央统一摄取改造建议清单（按解锁顺序）

> 排序原则：先拆「会静默丢消息/静默空转」的（1-3），再拆「安全单点」（4），再落「单源化结构性改造」（5-8），最后是卫生与文档（9-11）。每条给解锁依赖。

| 序 | 动作 | 解锁它才能做 | 风险面 | 关联台账 |
|---|---|---|---|---|
| **1** | **修段型双册**：`message_context` 导出三枚 frozenset，`contains_visual_message_segments` / `decision/engine._MEDIA_SEGMENT_TYPES` 改 import；补 photo-only 事件的 `_is_plain_chat_event` 正例锁 | 后续所有摄取改造的前提（否则 TG 消息根本进不来，改了也看不到） | 低（纯扩集合，OneBot 侧零变化） | U1-03 U1-04 U1-18 |
| **2** | **修群摘要键口径**（先读侧 LIKE 一行止血，再评估 §5.3 规范迁移） | 让【群共享上下文】与 21:30 推送从「恒空」变「有数据」，之后才能谈注入治理 | 止血=零；根治=**高**（存量 SQLite 键迁移，须 %TEMP% 备份 + 双写过渡） | U1-05 U1-06 U1-07 |
| **3** | **抽 `enrich_incoming()` 统一富化器**（音频转码 / TG 媒体 / 引用反查 / 转发正文四件套），chat 与 media_archive / image_search / content 四入口共用 | 消除「热区独享富化」这一最实质的第二套；也是 campus/meme 收编的模板 | 中（chat 链行为须逐字节对照，建议配 feature 门，沿用 S0-ROOT 的「门关=旧路径等价」范式） | U1-01 U1-02 |
| **4** | **补 meme 图库下载 SSRF 咽喉**（`check_download_url` 入口查 + 关 `follow_redirects` 后落点复查） | 与摄取改造解耦，**可立即单独落**（安全优先） | 低；但会拒掉历史可下的内网 URL（预期行为） | U1-10 U1-15 |
| **5** | **路由文本改取归一文本**（`_cached_route_decision` / `_effective_route_text` 用 N1 而非 `get_plaintext()`），并与摄取共用一次段解析 | 消除「路由看到的」≠「能力看到的」这一类静默 IGNORE 的根因 | **中高**：影响 40 个谓词的判据 → 可能新增命中（媒体消息进 chat 之外的 matcher），须过 route-matrix 覆盖门 + 触发棘轮 | U1-13 U1-16 |
| **6** | **campus 两步收编**（步1 取契约文本；步2 进 pipeline 受 gate/审计/幂等管辖） | 兑现「一切消息经中央摄取后进分发」，并让校园转发受安静时间/限流管辖 | 步1 零；步2 中（改变三重门短路语义，需先评审） | U1-09 |
| **7** | **ingress 实体化**：`_incoming_from_nonebot_event` 实现体迁 `domains/core/decision/ingress.py`，补 `MailSource`，加 AST 门锁「除 ingress 与合成工厂外不得 import 该符号」；根 `__init__.py` 只留 re-export | 让 `IngressGateway`/`AdapterSource` 从名义边界变成真边界，杜绝第 12 个直连调用点 | 中（根 `__init__.py` 是垫片枢纽，动它须与退役波协调，见 HANDOFF §D/§F） | U1-08 §1.1 |
| **8** | **幂等位上移到摄取出口**（键含 matcher 名），旁路去重表改为派生自中央键 | 消除四套键三语义；为「重投不双推」提供统一保证 | **顺序敏感**：必须与 §6 同波，否则从「无双计」翻成「双拒」 | U1-19 U1-20 U1-11 |
| **9** | **建真伪门**：`outbound_registry` 坐标改「符号名 + 锚点串」+ §8.1 的源码比对门 | 让统一化进度表本身可信、可长期维护（否则每波都要人肉重定位） | 低（测试与数据文件） | U1-24 |
| **10** | **合成入站工厂 + AST 计数门**（`IncomingMessage(` 生产命中 ≤4） | 区分「合法合成」与「违规自建」，防新面板再开第二入站面 | 低 | U1-21 |
| **11** | **文档/注释核销**：AGENTS.md 删「Console 适配器」口径或改述为"自研 REPL 入口"；`:1458` 错误注释随 U1-22 一并改；`campus.py:8` 幂等承诺随 U1-20 落地后回写 | 防下一个接手 AI 按错口径施工 | 低 | U1-21 U1-22 U1-20 |

**建议施工节奏**：4（安全，立即）→ 1（集合，一日）→ 2 止血（一行，一日）→ 3（富化统一）→ 9（真伪门，与 3 并行）→ 5（路由文本，需路由回归窗口）→ 6 → 7 → 8（同波）→ 10 → 11。
**全波共同前置**（本席硬提醒，来自 AGENTS.md 铁律 7 与上轮 §5 决策点 1）：**树单写者**。本席取证期间该文件即被并发写（`__init__.py` mtime 13:09→15:37，多份 HANDOFF/docs 15:31-15:45 变动），任何全绿宣称只维持到下一次写盘。

---

## §11 树卫生自查与席位事故披露（诚实底线）

- **自查命令与结果**：
  ```
  find plugins tests scripts -name "*.pyc"                          → 366（会话前为 0）
  find plugins tests scripts -name "__pycache__" -type d             → 93
  find ... -name "*.pyc" -newermt "-30 minutes" -printf "%TH:%TM\n"  → 16:05×7, 16:06×359
  ```
  时间戳与本席两次解释器调用（heredoc 复现脚本 + scoped pytest）完全吻合 → **归认为本席造成**。
- **处置**（依 AGENTS.md 铁律 6 + 台账#1 规程 + 上轮 §6.3 先例）：
  1. `mkdir -p "$TEMP/u1-hygiene-backup-20260919"` → `tar -cf pyc-session.tar`（366 条目，**先 `-tf` 验证条目数=366 且总数=366 再删**）→ 备份 **5,427,200 字节**在位。
  2. `find plugins tests scripts -name "*.pyc" -delete` → `find ... -depth -type d -name __pycache__ -empty -delete`。
  3. 复核：`*.pyc` = **0**、`__pycache__` = **0**、`data/` 目录 = **不存在**（本席未触发源码树写入）、`.pytest_cache/` mtime 12:37（**先前既有，非本席产物，未动**）。
  4. 铁律 6 随包资产复核：`plugins/bot_unified_runtime/domains/weather/assets/qx.json` **362,774 字节、mtime 2026-09-13 12:18，完好未被误删**。
- **教训（供下一个席位）**：本机 `PYTHONDONTWRITEBYTECODE=1` 前缀**未能阻止**字节码落盘（两次调用均已带该变量仍生成 366 个 .pyc）。下次席位改用解释器 **`-B` 命令行标志**（`python -B -c …` / `python -B -m pytest …`）并保留 `PYTHONDONTWRITEBYTECODE=1` 双保险；`rm` 本机不可用（Git Bash 无 coreutils-rm），清理走 `find -delete`。
- **系统时钟口径披露**：本机 `date` 读作 **2026-09-19 16:08**，而任务书与本文件名口径为 **2026-09-20**。本席所有行号/mtime 快照对应本地钟 2026-09-19 15:4x–16:1x 时段；文档名沿用任务书指定的 `audit-20260920-unify-U1-invest.md` 不改。
- **本席未做**（零越界）：未改任何代码/配置/文档（除本文件）、未 git 写、未派子代理、未真实发送、未重启/杀进程、未读 `.env`、未写 `ChatBot_Runtime/`。唯一解释器执行=只读复现脚本（SQLite 落在 `tempfile.mkdtemp`）与 1 次 scoped pytest（`--basetemp="$TEMP/u1-scoped-1"`，57 passed）。
- **并发写实况（本席收稿前最后一刻取证）**：`find plugins scripts tests bot.py pyproject.toml -type f -newermt "-60 minutes"` → 6 个源文件被**其他席位**改写：`domains/media/capabilities/tts.py`、`domains/render/templates.py`、`__init__.py`、`tests/render_hashes.json`、`tests/test_tts.py`、`tests/test_webui_http.py`（前三个正是任务书列出的在飞禁改面邻接件）。**本席只读，未触碰其中任何一个**（`git status --porcelain` 自证本席唯一新增 = 本文件，状态 `??`）。
- **收稿前坐标复验**（因并发写实时发生，落盘后再核一次五个要害锚点，venv 解释器 `grep -n`）：
  ```
  669:    visual_types = {"image", "face", "mface", "marketface", "sticker", "video"}
  1288:    session_id = event.get_session_id()
  5016:                plain_text = event.get_plaintext().strip()
  7286:            await enrich_telegram_file_segments(bot, event, event_segments)
  1274:def _incoming_from_nonebot_event(
  __init__.py 行数 = 8675（与取证时一致）
  ```
  即 §1/§4/§5 的要害坐标在本席收稿时**仍未漂移**。
- **scoped 测试实跑（唯一一次全跑，证「现有锁套不住本席发现」）**：
  `…python.exe -m pytest tests/test_nonebot_event_adapters.py tests/test_media_archive.py tests/test_group_context_b03.py tests/test_v21_s0_collect.py -p no:cacheprovider --basetemp="$TEMP/u1-scoped-1" -q`
  → `57 passed in 2.04s`。**在 U1-03（photo 双册）与 U1-05（群摘要零行）均为实况的情况下全绿**——锁缺位实证，非推断。

---

## §12 发现汇总

| 编号 | 严重度 | 一句话 | 坐标 |
|---|---|---|---|
| U1-01 | P1 | 四项入站富化只在 chat 热区内联，media_archive/image_search/content 拿不到 TG 媒体与深层引用 | `__init__.py:7281-7291` |
| U1-02 | P2 | 合并转发正文二次实现、落两个不同字段 | `__init__.py:8082` |
| U1-03 | P1 | `contains_visual_message_segments` 漏认 photo/animation/video_note（TG 纯媒体被路由 IGNORE，已实跑证） | `__init__.py:669` |
| U1-04 | P3 | 同族第二例：`emoji` 双册不一致 | `:669` vs `message_context.py:53` |
| U1-05 | **P1（已复现）** | 群摘要写键 `group_<gid>_<uid>` 与读键 `group:<gid>` 永不相交 → 群上下文恒空 + 21:30 推送恒静默空转 | `:1288` vs `shared_group.py:34` |
| U1-06 | P2 | 摄取契约缺群/人分层会话键 | `contracts/runtime.py:121` |
| U1-07 | P3 | `_is_group_session` 两份实现 | `memory.py:81` / `engine.py:292` |
| U1-08 | P2 | `AdapterSource/DEFAULT_SOURCES` 生产零消费、缺 MailSource | `decision/ingress.py:74` |
| U1-09 | **P1** | campus = 读事件→拼文本→落库→直投队列 四段全复刻，绕过 gate/审计/幂等 | `__init__.py:5002-5030` |
| U1-10 | P1 | meme 图库监听第二套洗段+自下载+自落库 | `:5940` → `meme_library_listener.py:247` |
| U1-11 | P2 | 表情回应写键=贴的人、读键=说话的人 → 分区系统性错位 | `:5308` / `:2672` |
| U1-12 | P3 | auto_send/music_mode 先 `get_plaintext` 再摄取，两串文本 | `:7215` / `:6407` |
| U1-13 | P2 | 路由文本（N2）≠ 能力文本（N1），实跑 `classify('')→IGNORE`、`classify('[图片]')→CHAT` | `__init__.py:832` |
| U1-14 | P2 | 段→URL 三份实现，V2 docstring 以"对齐"代替复用 | `:707` / `engine.py:372` / `:56` |
| U1-15 | **P1（安全）** | meme 图库下载零 SSRF 护栏（自家 4 处同类均有） | `meme_library_listener.py:76` |
| U1-16 | P3 | 一条消息段列表解析 2–3 次 | `:4740`/`:7279`/`:800` |
| U1-17 | P3 | `_extract_onebot_raw_segments` 与 payload 版逐行同构双写 | `:550`/`:490` |
| U1-18 | P2 | 决策引擎影子媒体段册与权威册差 6 型，自称对齐实未对齐 | `decision/engine.py:358` |
| U1-19 | P2 | 中央幂等位在 pipeline 内部，6 条旁路结构性不受管辖（且缺省关） | `pipeline.py:1053` |
| U1-20 | P2 | campus 空 message_id 兜底键含秒级时间戳 → 与自家 docstring 重投不双推的承诺矛盾 | `campus.py:115` |
| U1-21 | P3 | Console 非适配器；17 处生产 `IncomingMessage(` 直构无合法性分级 | `bot.py:408-483` 等 |
| U1-22 | P2 | TG `sender_display_name` 恒 None（`first_name` 全树仅引用链读）+ 注释错误陈述 | `__init__.py:1459` |
| U1-23 | P3 | platform/adapter 字面量三分叉（qq/onebot/nonebot）+ gateway 自带弱归一 | `:1342`/`:1836`/`:4323`/`gateway.py:37` |
| U1-24 | P2 | `outbound_registry` 50 条 matcher 坐标 0/50 命中真行，自有测试只查格式 | `outbound_registry.py:421` |

**分布（24 条）**：**P0 = 0**｜**P1 = 6**（U1-01 / 03 / 05 / 09 / 10 / 15）｜**P2 = 11**（U1-02 / 06 / 08 / 11 / 13 / 14 / 18 / 19 / 20 / 22 / 24）｜**P3 = 7**（U1-04 / 07 / 12 / 16 / 17 / 21 / 23）。
施工合并建议（不改变条数）：U1-04 随 U1-03、U1-06/U1-07 随 U1-05、U1-12/U1-16/U1-17 随 U1-13、U1-10 与 U1-15 同一条处置。

### 未见缺陷清单（正面记录，接手者勿重复怀疑）

1. **归一函数单源**：全树仅 1 个 `_incoming_from_nonebot_event` 实现，根 `message_context.py`/`runtime/ingress.py` 为 PEP 562 垫片，无第二实现。
2. **matcher 注册单点**：`grep` 证明全部 NoneBot matcher 注册集中在根 `__init__.py`，**无任何插件域自建 matcher**（0 例外）。
3. **引用链跨适配器合一**：OneBot `reply.reply`(extra=allow) / reply 段反查 / Telegram 原生递归 `reply_to_message` 三路在 `collect_reply_chain:366` 收敛为单一 `ReplyChainItem` 结构，含 per-level 与 total 双预算 + 内部标记全角消毒（`_neutralize_markers:148`），**未见缺陷**。
4. **`at`/`reply` 段处理口径自洽**（§1.5 四项取证）。
5. **语音/音频/转发三枚段册与权威册一致**（`AUDIO_SEGMENT_TYPES`、`FORWARD_SEGMENT_TYPES`）。
6. **daily_assist / affinity / 群摘要（入站侧）/ 订阅推送装配** 均经 `_incoming_from_nonebot_event` → pipeline，**未见入站旁路**。
7. **出站侧已统一**：poke / 入群欢迎 / 二维码 / 文档导出四处直连经 S0-ROOT 收编（HANDOFF §C2），本席复核 `emoji_like`/`reaction` 出站同样走 `dedupe_key`+`part_id`（`engine.py:685,721`）——**本席未发现新的出站直连回归**。
8. **事件级路由缓存**设计正确（`_ROUTE_DECISION_STATE_KEY:810` 借 NoneBot per-event state 自动回收，把 40 谓词收敛为 1–2 次分类）。
9. **`_transcode_record_segments` 超时与幂等**（`:1150` 20s `wait_for` + `data.transcoded_path` 短路）实现完好。
10. **撤回事件**：0 处理属"功能未实现"而非"绕过统一"，无消费者，按 §1.3 记账不升级为缺陷。

---
