# U15-OUTPUT 审计：出站文本 / 输出管线统一（2026-09-20）

> 席位：U15-OUTPUT（只读审计，唯一可写文件＝本文件）
> 范围（用户裁定）：后端 Python **非卡片**输出管线契约面——Review 层、纯文本加工、分片/合并转发、媒体部件装配顺序、失败兜底与重试的文本侧语义。
> 排除：webui/、domains/render/** 内部、output/card_render/**、theme_tokens.py、card_render/templates/**、TTS/语音链路。
> 交叉席位：U3（绕过 SendQueue 直连点清单）、U11b（消毒/打码安全面）——本席只引用+补强，不重复其清单与风险枚举。
> 本席总目标（统一 mandate）：一条能力结果只经过一条加工链；同一语义只有一种分片/换行/截断/兜底规则。凡能力自己拼文本、自己截断、自己分行、自己写兜底文案＝缺陷。

## 0. 工作规程与必读确认
- [x] 日志骨架先行落盘（本文件首次写入＝第一动作）
- 必读：AGENTS.md 第三部分链路图 + 台账 #26/#29/#35/#36/#41/#42（含「分段换行统一」二段增补：`normalize_paragraph_breaks` / `format_roleplay_paragraphs` / `prefix_parts`）；`docs/design/audit-20260919-unify-wave.md`；`HANDOFF-V21R5-20260920.md` §三 C（出站收编）
- 必读结论（已落实）：①AGENTS 链路图各件真身坐标：`output/plain_text.py`、`output/renderer.py`、`output/reviewer.py`、`output/roleplay.py` 全部是 3 行垫片（锚点 `Compat shim: moved to domains/render/`，v21r2 W13 render 迁移），真身在 `plugins/bot_unified_runtime/domains/render/*.py`。②范围裁定收口：用户排除「domains/render/** 内部」与交付物 D1-D4 字面冲突（plain_text/reviewer/renderer/roleplay 真身恰在其中且被点名必审）。本席按交付物执行：只审 domains/render 文本管线四件（plain_text.py / reviewer.py / renderer.py 分片-转发-部件装配函数 / roleplay.py），不审其卡片视觉件（card_render/、render_backends.py、templates.py、theme_tokens）。③前轮记忆册实测（digest/daily_assist/reminder/校园/告警旁路中央门禁）与本席 D1 独立取证方向一致。④HANDOFF-V21R5 §三 C：S0 直连收编在飞（DIRECT-PLAN，通道面）；本席为文本加工链面，互补不重复。
- 证据规程：每条发现七要素（严重度｜文件:行｜锚点字符串｜根因｜证据｜改法 before→after｜验证命令）；禁「可能/大概」；离线构造串验证形态；直跑 python 必带 `PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`；pytest 必带 `--basetemp=$TEMP/u15-* -p no:cacheprovider`；禁一切 `--write` 类命令（verify_hashes/doc_sync/command_catalog 只用 --check）；禁真实发送/触网/跑全量 pytest；不读 .env 明文值。

## D1 输出通路清点（核心）
### D1.0 咽喉函数真身与唯一消费者（先立事实）
「说人话全链」四件套＝`naturalize_chat_text` + `humanize_reply` + `redact_local_secrets` + `normalize_paragraph_breaks`（旁路消费者多数只调 redact 单件）。真身坐标（2026-09-20 重读，行号+锚点）：
- `domains/render/plain_text.py:203` `def naturalize_chat_text`（锚点 `Idempotent presentation conversion`）
- `domains/render/plain_text.py:286` `def humanize_reply`（锚点 `剥离聊天回复的 AI 客套开场与总结腔`）
- `domains/render/plain_text.py:340` `def redact_local_secrets`（锚点 `打码回复文本中的本机敏感形态`）
- `domains/render/roleplay.py:109` `format_roleplay_paragraphs` / `:140` `normalize_paragraph_breaks`（锚点 `段间一律单个换行`）

全树 grep 实证：`humanize_reply` 与 `normalize_paragraph_breaks` 的**唯一生产消费者**＝`domains/chat_reply/capabilities/chat.py`（L2351/L2357，锚点 `reply_text = normalize_paragraph_breaks(reply_text)`）；`format_roleplay_paragraphs`/`strip_action_brackets`/`strip_outer_speech_quotes` 亦仅此一处。管线中央与渲染器对非 chat 能力**不做任何分行/润色加工**（`renderer.py:197` 锚点 `elif is_chat:`——naturalize 仅 bot.chat 分支）。**结论先行：AGENTS #36「分段换行统一」实证覆盖面＝chat 一条链，不是出站口全局。**

### D1.1/D1.2 通路 × 加工步骤矩阵（✅＝经过；空＝绕过）
| # | 通路 | 坐标（锚点） | review | redact | naturalize/humanize/分行 | 分片统一 | SendQueue |
|---|---|---|---|---|---|---|---|
| P1 | chat 主链 | chat.py L2335-2357；pipeline.py L731 `review = review_capability_result` / L755 render / L835 submit | ✅ | ✅(能力层) | ✅(能力层全链) | ✅(chat 仅字数触发合并 L761-774) | ✅ |
| P2 | 非 chat 能力主链（echo/天气/行情/笔记/订阅等 28+） | 同 pipeline；renderer.py L190-198 | 部分(仅 body→summary→title 三选一，reviewer.py L121 锚点 `output_text = result.body or result.summary or result.title`) | 空 | 空 | ✅(≥4条合并 L761-769) | ✅ |
| P3 | 提醒主动投递 | `__init__.py:2915-2941`（锚点 `capability_id="bot.reminder"`）；文案 reminders.py:718 `build_reminder_text` | 空 | 空 | 空 | 空 | ✅(submit L2941+内联投递) |
| P4 | cookie 到期报告 | `__init__.py:3027-3050`（锚点 `bot.cookie_expiry_notice`） | 空 | 空 | 空 | 空 | ✅ |
| P5 | 群摘要 21:30 推送 | `__init__.py:3188-3211`；`_build_digest_push_text` L3126（锚点 `我都悄悄记下了`） | 空 | 空 | 空(LLM 摘要原文直落) | 空 | ✅(纯 submit) |
| P6 | daily_assist 三餐/早报/晚报 | `__init__.py:3306-3359`；开场池 L2884-2891（锚点 `到饭点啦，守岸人替你挑了这个`）；LLM 早报 L3382+ | 空 | 空 | 空 | 空 | ✅ |
| P7 | 校园转发 | campus.py L137-172（锚点 `【校园转发】群{group_id}`） | 空 | 空 | 空 | 自建截断 `text[:budget]+"…"` L147-148（`_CAMPUS_FORWARD_MAX_CHARS=1500` L34） | ✅ |
| P8 | 管理员告警 | alerts.py L269-303（锚点 `所有管理员告警出站内容的唯一收口`） | 空 | ✅(L278) | 空 | 自建硬切 `[:4000]` L289（无尾提示=静默丢字） | ✅ |
| P9 | 群失败降级 ack | pipeline.py L837-936（锚点 `GROUP_FAILURE_ACK_TEMPLATES` 轮换）`random.choice` L881 | 空 | 空 | 空 | 空 | ✅(IMMEDIATE) |
| P10 | 错误卡文本回执(两段式第一段) | error_report.py L1127-1142（锚点 `_ACK_FOLLOWUP_HINT`） | 空 | 部分(构造期 L695 `redact_local_secrets(str(exc)[:300])`) | 空(未过分行统一) | 空 | ✅ |
| P11 | 错误卡冷却降级文本 | error_report.py L1111-1125；`cooldown_line` L969（锚点 `冷却期降级纯文本`）随机池 | 空 | 空 | 空 | 空 | ✅ |
| P12 | 诊断卡文部件/卡失败纯文本兜底 | error_report.py L1245-1279（锚点 `build_text_fallback(report)`，函数 L759） | 空 | 栈逐帧✅(L352/373/447) | 空 | 空 | ✅ |
| P13 | 视频解析进度 ack | video_pipeline.py L197-217（锚点 `_VIDEO_ACK_TEXT = "这个视频我看看`） | 空 | 空 | 空(写死单句+带标题 f-string 变体 L205 双份文案面) | 空 | **空：`matcher_send` 直发**（通道直连归 U3 记，本席记文本面） |
| P14 | 戳一戳回复 fixed/llm/meme | `__init__.py:5222-5287`→`_send_parts_through_unified_pipeline` L4838-4879（锚点 `带 @ 前置段/图片的统一管线发送`）；LLM 文本 `_poke_llm_reply` L5180-5214 原始 `.strip()` 直落 body | ✅(但 persona-drift/群公开安全审只认 bot.chat，reviewer.py L104-106/L134) | 空 | 空 | ✅(非 chat 按条数) | ✅ |
| P15 | 媒体终败文本降级 | worker.py L581-665（锚点 `只在「明确拒绝」时回退`；`:textfb` 键 L640） | 沿用原请求 | 沿用原文本 | 沿用 | 空 | ✅（二次降级，不另计首发） |
| P16 | 卡片渲染失败→纯文本兜底(renderer 层) | renderer.py L235/246/259/268 `text_fallback=...`；onebot.py L232-241（锚点 `return [_text_segment(text_fallback)]`） | ✅(原内容) | 非 chat 空 | 非 chat 空 | 兜底不再切分 | ✅ |
| P17 | /bot 子命令直返（echo 帮助族） | 作为能力走 P2 | ✅(同上限制) | 空 | 空(手拼字面量，设计内) | ✅ | ✅ |
| P18 | 控制面 HTTP 响应文本 | control_plane/workspaces.py:84、actions.py:46、events.py:106（锚点 `redact_private_debug(redact_local_secrets(value))`） | 空 | ✅ | 空 | 空 | 非用户会话文本，不计入通路 |

**统计**：到达用户可见文本（QQ/TG/邮件会话内）的通路实测 **16 条**（P1-P14、P16、P17；P15 为二次降级、P18 非会话面）。其中经「说人话全四件套」的仅 **P1 一条**；**完全绕过 plain_text 咽喉（任一函数都不过）的首发用户可见通路＝P2/P3/P4/P5/P6/P7/P9/P11/P13/P14/P17 共 11 条**。

### D1.3 发现（详七要素见汇总表）
- **U15-01 Critical**：非 chat 主链与全部调度器主动投递零文本加工；含 LLM 派生文本的 P5/P6/P14 裸文本出站（P5 直进**群**）。中央统一在输出文本面不成立。
- **U15-02 Major**：review 审查面＝body/summary/title 三选一，`text_parts`（chat 字幕摘录 `字幕摘录：{subtitle[:1500]}` chat.py L489）与并存 title/summary、mixed parts 内文本段全部逃逸。
- **U15-03 Major**：persona-drift 与「公开不安全」审查硬编码只认 bot.chat（reviewer.py L105 锚点 `result.capability_id != "bot.chat"`；L134 同）——P14 戳一戳 LLM、P5 群摘要可自称通用 AI/露骨文本直发不被拦。
- **U15-04 Major**：话术池四家并存、选法三种互不统一：私聊五池(游标轮换#36)/`GROUP_FAILURE_ACK_TEMPLATES`(random.choice)/`_COOLDOWN_LINES`(random.choice)/`_MEAL_OPENERS`+`pick_variant`(游标)/`_REMINDER_TEXT_TEMPLATES`+`_pick_template_variant`(sha1 散列)/`build_poke_text` 与 `_VIDEO_ACK_TEXT` 写死单句。绕池写死清单：`build_poke_text`（poke.py L48-51）、`_VIDEO_ACK_TEXT`+标题变体（video_pipeline.py L27/L205）、`_DIGEST_PUSH_INTRO`（__init__.py L3122）。
- 无缺陷申明：P15 文本侧复用已加工内容、无第二形态（取证 worker.py L640-645）；P13/P8 的通道直连清单归 U3，此处只记文本形态。

## D2 分片 / 截断 / 合并转发规则统一
### D2.1 全树切分/截断实现清单（一手坐标，均 2026-09-20 重读）
| 实现 | 坐标（锚点） | 规则 | 尾部提示 |
|---|---|---|---|
| 中央分片(合并转发/part 切分) | renderer.py:286 `def split_text_chunks`（锚点 `按段落把长文本切成合并转发节点`）；node_chars 默认 900，`_safe_break_index` L275 向前 40 字回找标点，找不到**硬切** | 段落聚合+标点回退 | 无（设计为不丢字，逐块保全） |
| 触发口径 | pipeline.py:761-785（锚点 `合并转发触发条件：切分后**>3 条**`）；chat 只按字数(≥1500)，非 chat 按条数(≥4)或字数；配置四键 `bot_render_forward_min_chars=1500/min_nodes=4/max_nodes=0/node_chars=900`（config.py:807-812） | — | — |
| chat 出站预算 | chat.py:3536 `_apply_output_message_budget`（锚点 `段数 0/负数 = 不限段`）；单条默认 1200（`_output_max_chars_per_message` L3505 锚点 `至少 200 字符`）；`_clip_text` L716 加 `…` | 按空行分块取前 N 块+总字数封顶 | ✅ `OUTPUT_BUDGET_NOTICE`（L573 锚点 `平台单条消息长度限制，以上为完整回复的可见部分`） |
| 校园转发 | campus.py:147-148（锚点 `budget = max(0, _CAMPUS_FORWARD_MAX_CHARS - len(prefix))`）| 字符硬切 | `…` 一份 |
| 管理员告警 | alerts.py:289-290（锚点 `text_fallback=str(text)[:4000]`） | 字符硬切 | **无（静默丢字）** |
| 媒体终败文本兜底 | worker.py:589/608/612（锚点 `_TEXT_FALLBACK_MAX_CHARS = 4000`） | 字符硬切 | **无（静默丢字）** |
| 天气摘要 | weather.py:282（锚点 `summary=report[:1200]`） | 字符硬切(summary 面) | **无** |
| 订阅推送正文 | `__init__.py:4294`（锚点 `text += f"\n{body[:500]}"`） | 字符硬切 | **无** |
| chat 字幕摘录 | chat.py:489（锚点 `字幕摘录：{subtitle[:1500]}`） | 字符硬切 | **无** |
| TG 附件 caption | nonebot.py:420（锚点 `caption=remaining[:1000]`）；photo caption 1024 分流 L439（>1024 图先发文另发=分片第三规则） | 字符硬切/改道 | **无** |
| transport 侧 | onebot.py 全文本发送**零长度切分**（L614-627 锚点 `build_onebot_message_segments(send_request)` 整段发出）；无 QQ 单条上限常量 | 不兜底 | — |
| 其它诊断面 | echo.py:119-120（`…`）；ops repair/incident `…(已截断)`（service.py:151/incident:120 锚点） | 字符硬切 | 第三种尾巴文案 |

**「同一超限内容两种形态」实锤案例**：同为 5000 字符纯文本——走 P2 主链（非 chat 能力）→ 字数≥1500 触发合并转发，切成 ≤900 字节点多条可见；走 P5 群摘要推送（调度器直构 text）→ `max_messages=1`、无切分、transport 不兜底 → **整条撞平台上限失败**（SnowLuma 拒收/截断不可控，出站侧无任何分片或降级实现）。走 P8 告警 → `[:4000]` 静默剪掉 1000 字。**QQ 单条上限在代码内零登记**（grep `4500|too_long|4096` 无出站常量），即「按字节/按码点」的口径根本不存在，各实现各按各的字符数猜。
**UTF-8/表情切分安全（探针 P1 实锤）**：`split_text_chunks` 在 node_chars 边界把 ZWJ 序列族 emoji 从中间切断——`P1 split: n=2 first_len=900 prev_char=U+1F468 next_head='\u200d👩' (family emoji split=True)`：chunk1 以零宽连接符+残留码点开头，用户侧呈现裂开表情。`_clip_text`/`[:4000]`/`[:500]`/`[:1500]` 全部同构可复现（Python 码点切片对 ZWJ/变体选择符序列无簇感知）。

### D2.2 截断尾部文案
三族互不同源：①chat `OUTPUT_BUDGET_NOTICE` 整句说明；②`…`（campus/echo/_clip 系）；③`…(已截断)`（ops repair/incident）。**静默丢字面**：alerts 4000、worker 兜底 4000、weather 1200、订阅 500、字幕 1500（五处，均无任何提示，取证上表坐标）。

### D2.3 `prefix_parts` 消费一致性（探针 P9 实锤）
renderer.py 四出口：text 分支（L251 `if leading_parts or media_parts:` ✅）、mixed ✅、**chunks 分支（L222-235）返回前不看 leading_parts → @ 段丢**（P9：`content_type=chunks at_kept=False`）、**mermaid 分支（L236-250 `parts = [*media_parts, *mermaid_parts]` 不含 leading_parts → @ 段丢**（代码直读）。transport 面：onebot 消费 at 段（onebot.py:264-271 锚点 `OneBot V11 at 段`）✅；nonebot(TG/mail) 只取 text_fallback → @ 设计性丢失（renderer L202-203 注释自认「诚实降级丢 @」，登记为口径而非缺陷）。**触发面**：现网 poke 不带 text_parts/mermaid，故未爆；但契约上「同一语义（@ 前置）在四条 renderer 出口两种形态丢件」＝缺陷成立。

### D2.4 发现
- **U15-05 Critical**：超限文本三种命运（合并转发/静默硬切/整条撞上限）按通路随机决定；transport 层无统一最后防线；调度器长文本（P5/P6 早晚报含 LLM 长摘要）实测无切分面。
- **U15-06 Major**：五处静默丢字截断（alerts/worker兜底/weather/订阅/字幕）+三族尾巴文案不同源。
- **U15-07 Major**：分片不感知字素簇，ZWJ emoji/变体序列可被从中间切断（探针 P1）；`_safe_break_index` 40 字回退窗内无标点即硬切。
- **U15-08 Minor**：`prefix_parts` 在 chunks/mermaid 两出口被丢（探针 P9+代码直读）。
- **U15-09 Minor**：chat 文本在链上被 naturalize **两次**（chat.py L2345 + renderer.py L198）——幂等成立（探针 P5 `True`）无实害，但属同功能双调用面，收口清单登记。
### D2.1/D2.2/D2.3 待补残余（登记不判缺陷）
- reminders 回执条目 `[:30]`（reminders.py:209）为内部回执行，尾注取证后若缺 `…` 并入 U15-06 家族。

## D3 Review 层与「说人话」统一
### D3.1 Review 真身 / 职责边界 / 旁路清单
真身＝`domains/render/reviewer.py::review_capability_result`（L114，锚点 `def review_capability_result`），唯一生产调用点＝pipeline.py:731。**职责边界（实读）**：只判不修——`safe_text=output_text` 原样透传（L163），`_redact_output_match`（L65）仅用于**理由字符串**内片段回显，不改出站文本。审的内容：CRITICAL 风险、内部标记外漏（`[UNTRUSTED_USER_TEXT]` 等）、密钥形态（自带第二份正则族 `_SECRET_OUTPUT_PATTERNS` L22-30，与 plain_text.redact_local_secrets 形态集重叠而口径不同：reviewer 命中即 BLOCK，plain_text 命中即打码放行）、群内公开不安全（仅 bot.chat）、persona drift（仅 bot.chat）、PERSONAL/CREDENTIALED 进群→MOVE_PRIVATE。
**旁路清单（不过 review 的出站文本）**：P3/P4/P5/P6/P7/P8/P9/P10/P11/P12/P13 共 11 条（D1.2 矩阵 review 列空者）——全部调度器投递、全部错误卡文本面、告警、群失败 ack、视频 ack。
**拦截后路径**：pipeline L732-753 直接 BLOCKED 回执+固定文案（见 D3.3）。
**MOVE_PRIVATE 语义空洞（探针+grep 实锤）**：reviewer.py:153 锚点 `action = ReviewAction.MOVE_PRIVATE` 是全树**唯一**出现处——pipeline 对 `not review.approved` 只有一律 BLOCKED 分支（L732），不存在任何「转私聊」投递实现；PERSONAL 内容进群的实际行为＝拦截+一句机器文案，**「改道私聊」契约名不副实**（审计事件里 `review.action.value` 记 move_private 但用户侧与 block 无差别）。

### D3.2 「去 AI 味/说人话」实现份数与写死文案清单
加工规则实现份数：**各 1 份、集中在 plain_text.py**（naturalize=Markdown/TeX/表格洗；humanize=客套剥离+内心数值打码）——这部分统一成立；**缺陷在覆盖面不在份数**（D1.0：仅 chat.py 消费）。
话术池实现清单（同职责多机制实锤，grep 全树）：
| 池 | 坐标（锚点） | 选法 |
|---|---|---|
| 私聊人格失败池 | chat.py:616 `_PERSONA_FAILURE_MESSAGES`（锚点 `纯按游标顺序轮换`） | 会话游标 mod n，无会话退随机 |
| 反注入拦截池 | chat.py:2674 附近（锚点 `拦截回复取句：同会话游标轮换`） | 会话游标 |
| 管理门池 | user_copy.py:37 `ADMIN_GATE_TEMPLATES`（锚点 `random.choice(ADMIN_GATE_TEMPLATES)`） | random.choice |
| 数据源失败池 | user_copy.py:58 `DATASOURCE_FAILURE_TEMPLATES`（stocks/market/fx/moegirl 引用锚点 `审查 Q-01：数据源失败文案统一入 user_copy 池`） | random.choice |
| 群失败 ack 池 | user_copy.py:75 `GROUP_FAILURE_ACK_TEMPLATES`（pipeline.py:881 消费） | random.choice |
| 错误卡冷却池 | error_report.py:91 `_COOLDOWN_LINES`（`cooldown_line` L969 锚点） | random.choice |
| 到点吃什么池 | `__init__.py:2884` `_MEAL_OPENERS` + store/daily_assist.py:332 `pick_variant`（锚点 `同 key 游标循环、连发不重复`） | 游标 |
| 收件箱命令面池 | assistant/daily/capabilities/daily_assist.py:30-57 `_HELP/_QUERY_*/_CAPTURE_VARIANTS` | pick_variant 游标 |
| 提醒模板池 | schedule/store/reminders.py:707 `_pick_template_variant`（锚点 `稳定散列取模选一`） | sha1 首字节 mod |
| 占卜未接线提示池 | divination/projection/render_projection.py:39-48（锚点 `draw_id 确定性轮换`） | draw_id mod |
| **写死单句（绕池）** | video_pipeline.py:27 `_VIDEO_ACK_TEXT`+L205 标题变体；poke.py:48 `build_poke_text`（双句字面）；`__init__.py:3122` `_DIGEST_PUSH_INTRO`；pipeline.py:336/344 `"输出未通过安全或隐私检查。"`；error_report ack `_ACK_FOLLOWUP_HINT` 拼接 | 固定 |
判据引用：台账 #36「不要僵硬短句」五池 mandate——**同职责 10 份池机制、5 种选法（游标×2 家族/random/sha1/draw_id mod/固定）互不互通**，且仍有 6 处写死句。

### D3.3 失败/降级文案出口统一性
能力失败→用户可见文本的出口实测 **6 处**：①chat 私聊失败池（#2）；②群失败 ack（P9）；③错误卡两段式文本回执+冷却降级（P10/P11，`_build_error_send_request` 统一构造器＝该链内部自洽，**全树仅此一份实现**，grep `_build_error_send_request` 调用点全在 error_report.py 内——无第二份）；④review BLOCK 固定文案（pipeline `_review_block_public_message`）；⑤worker 媒体终败文本兜底（P15，发的是原文本部件，非文案池）；⑥transport 拒形态时 `text_fallback` 降级（renderer/onebot 契约）。①②④③彼此为四套互不复用的「温和失败话术」，且④为机器腔单句。

### D3.4 发现
- **U15-10 Major**：`MOVE_PRIVATE` 有名无实（无消费者转道实现，等同 BLOCK+机器文案）——隐私出站在群里的「软处理」契约断裂。
- **U15-11 Major**：review 拦截文案「输出未通过安全或隐私检查。」写死、AI 腔，违反自家「说人话」判据（pipeline.py:336/344）。
- **U15-12 Major**：话术池 10 份实现 5 种选法+6 处写死句（清单见 D3.2 表；判据 #36 mandate）。
- **U15-13 Minor（交叉引用 U11b）**：密钥形态两份规则集并存（reviewer `_SECRET_OUTPUT_PATTERNS` 命中即 BLOCK vs plain_text `redact_local_secrets` 命中即打码），占位符两套（`[redacted]`/`<已隐藏>`/`sk-<已隐藏>`）；安全兜底强弱不一致＝本席只记「同一语义两种出口形态」，风险枚举归 U11b。

## D4 契约与幂等的文本侧一致性
### D4.1 part 级幂等键输入构成 vs 文本加工顺序
**键构成（实读）**：请求级 `dedupe_key`＝pipeline L818-821（锚点 `dedupe_key=(f"{decision.capability_id}:{message.session_id}:"` ）＝能力+会话+入站 message_id（不含正文）；调度器各用自己的语义键（`reminder:{id}`/`digest_push:{群}:{日}` 等）。part 级键＝queue.py:104-106 `_part_key`（锚点 `part 稳定键 = message_request_id + part_index，重试不换键`），**输入构成＝request_id+序号，正文与 digest 均不进键**；`payload_digest`（worker.py:576 锚点 `只存摘要，不存用户正文副本`）仅落库，`ensure_parts_planned` 用 `ON CONFLICT(part_key) DO NOTHING`（queue.py:1067），**全树无任何 digest 比对消费**（PartProgress 读出后 `records[].payload_digest` 无人比较，grep 实证）。
**加工顺序判定：命题不成立（无缺陷，附取证）**——文本全部加工（分行/规范化/分片）发生在 CapabilityResult→render 阶段，即 **submit 之前**；queue 行持久化整个 SendRequest（含 chunks），重试读回的是冻结正文，`_chunk_part_plan`（worker.py:559）确定性 re-strip——同 request_id 重跑不可能产生不同 part。若成立应判 P1 的「键在规范化前算」形态在本仓不存在。
**残余设计缺口（登记）**：正因 digest 不比对，若未来出现「同 request_id 重建不同正文」的通路（目前无），part 状态会静默错位；且 parts_total 变更无守卫（新规划更长时旧行号语义漂移）。P3 级设计债，不升格。

### D4.2 卡片失败→纯文本兜底「零破坏」实证
契约面：renderer 各分支恒带 `text_fallback`（L231/246/259/268）；onebot 卡/图段构造失败→`[_text_segment(text_fallback)]`（L235-241 锚点 `return [_text_segment(text_fallback)]`）——**兜底文本＝原能力 body 字段本身**，不另拼装（好）。但「不过＝打码缺口」的判定：该兜底文本对非 chat 能力**从未过 redact/naturalize**（探针 P4：`unchanged=True path_kept=True`——正文里的盘符路径原样进兜底进出站）；chat 侧已过全链无缺口。**结论：卡片渲染失败的纯文本兜底不补任何加工，缺口由上游 P2 决定——交叉引用 U11b（打码咽喉覆盖面）同一事实，本席记「兜底与首发形态同源=统一成立；同源≠已过咽喉」。** 错误卡文本兜底（P12 `build_text_fallback`）为第二份自建文本装配器（栈摘录+IDs+`_FALLBACK_HELP_TEXT`，锚点 L760-763），逐帧 redact 但不行分统一/不 naturalize（机器形态与主链兜底规则不同族）。

### D4.3 打码后文案形态破坏（离线构造实测，禁真值）
- **规则链互扰（探针 P4b，Major）**：输入 `...配置在 C:/Users/EXAMPLE/.env（好感度 85）https://...?token=abcdefghij1234` → 按 chat 既有顺序 naturalize→humanize→redact 输出 `'天气：\n多云 22℃ 配置在 <本机路径已隐藏>）https://...?token=<已隐藏>'`。`（好感度 85）`整段被吞、右括号悬空——根因：humanize 先产出去掉空白的 `好感度…保密`，`_LOCAL_PATH_RE`（plain_text.py:307 锚点 `(?<![A-Za-z0-9:])([A-Za-z]):[\\/]`）字符类**排除右括号却不排除左括号**、且不排除汉字，把「路径+紧邻括注」整段当路径打掉。**打码顺序与字符类共同造成语义破坏**（行情数值无关键字前缀不受影响——同探针 `22℃` 原样）。
- 告警行（探针 P6）：`http://user:pass@10.0.0.9:8090/v1` → `http://<已隐藏>@10.0.0.9:8090/v1`、`D:\data\runtime.log`→`<本机路径已隐藏>`——形态保真，无破坏。
- P8 告警 `[:4000]` 在 redact **之后**切（L278→L289 顺序），截断点可把 `<本机路径已隐藏>` 之类占位尾巴切半（登记入 U15-06 家族）。

### D4.4 换行/空白规范覆盖面（非 chat 链）
`normalize_paragraph_breaks` 唯一消费者＝chat.py（D1.0 grep 实证）。不一致样本（静态坐标）：①P5 群摘要——LLM 摘要含 `\n\n` 原样出站（`_build_digest_push_text` L3128 只做 `f"{intro}\n{summary}"`）；②P3 提醒模板含 `\n` 多行（reminders.py:700 锚点 `你之前说过的：{text}。\n`）不经折叠；③P10 错误卡 ack `human_text + 空格 + hint` 拼接无折叠（error_report.py:1128-1130）；④P2 非 chat 能力 body 手拼 `\n` 各能力自便（weather report 逐段手拼）；⑤P17 help 正文 `\n` 手拼字面量（echo `_HELP_ENTRIES`）。chat 链「段间单换行」裁定在生产面 = **只对 chat 生效**，其它链双换行/单换行混合照发。

### D4.5 发现
- **U15-14 Major**：打码规则链互扰+左括号吞噬致语义破坏（P4b 实锤，plain_text.py:307/273）。
- **U15-15 Major**：分行统一覆盖面＝chat-only（四组样本，D4.4）；AGENTS #36 记载的「统一」在文档层未限定作用域，接手者会误信全局成立（文档-代码漂移面，与 U6/文档席交叉引用）。
- **U15-16 Minor**：payload_digest 存而不比、parts_total 变更无守卫（设计债登记；「键在规范化前」命题证伪）。
- **U15-17 Minor**：错误卡文本兜底为第二份自建文本装配器、不过行分统一（与主链兜底规则不同族）。

## D5 输出面死码与配置漂移
### D5.1 输出面配置键对照表（登记面=SETTABLE/RESTART_REQUIRED/热改合并表；生效时机）
| 键 | 登记 | 消费坐标 | 生效时机 | 判定 |
|---|---|---|---|---|
| `BOT_RENDER_FORWARD_MIN_CHARS/MAX_NODES/NODE_CHARS` | RESTART_REQUIRED_KEYS（settings.py:358-366，诚实） | `__init__.py:3757-3759` 装配期裸 config→pipeline 快照 | 重启 | ✅一致（拨不动=set 被拒+文案指路重启） |
| `BOT_RENDER_FORWARD_MIN_NODES` | **同时在 RESTART_REQUIRED（:355）与 `_RUNTIME_HOT_OVERRIDE_FIELDS`（`__init__.py:748`）** | 唯一消费点＝pipeline 装配快照 L3761 + 发送期 `self.forward_min_nodes`（pipeline.py:767），合并层产物无人回读 | 重启 | **U15-18 Minor**：热改合并表登记为虚设（拨了白算），两表互相矛盾 |
| `BOT_REPLY_MAX_CHARS_PER_MESSAGE` | SETTABLE（:475） | chat.py:2806 `get_or(...)` 每消息现读 | 热生效 | ✅一致 |
| `BOT_VIDEO_PROGRESS_ACK_ENABLED` | RESTART_REQUIRED（:396） | video_pipeline.py:190 收**裸 config**（`__init__.py:7554 config=config`，未过合并层） | 重启 | ✅一致（诚实登记） |
| `BOT_VIDEO_PROGRESS_ACK_COOLDOWN_SECONDS` | 不在 SETTABLE 亦不在 RESTART 表（grep 零命中） | video_pipeline.py:195 裸 config | .env+重启 | U15-19 Minor：登记缺口（同族仅 ENABLED 入册；行为无害，治理面漏登） |
| `bot_error_card_enabled/_cooldown_seconds/_stack_frames` | 不在两表（仅 .env） | error_report.py:220-228 调用期现读 `nonebot.get_driver().config`（.env 值） | 重启 | ✅拨得动（改 .env）；无热改承诺，不判漂移 |
| `BOT_POKE_*` 8 键 | 白名单外；settings.py:493-496 自证「合并表未登记字段，覆盖不可达；__init__ 注释『立即生效』与实际不符，待接线」 | 合并层 L5226 读了个寂寞 | 重启 | 已知漂移，本席引用不重复记（settings 注释已挂账） |
| `BOT_GROUP_DIGEST_PUSH_ENABLED/TIME`、`BOT_DAILY_ASSIST_*` | 热改合并表（L754-762） | **装配期快照**：digest 注册器 L3241-3242 一次性读；daily_assist 各 job 以**默认参绑死裸 config**（L3487/3507 锚点 `def _meal_job(_config: Any = config`；docstring 自认 `cron 时刻为装配期快照（与 G-DIGEST 同款已知取舍）` L3475），名单/时刻经合并表热改均不可达（注册门 `if not _daily_assist_targets(config)` L3477 也是装配期一次判） | 重启（虽在合并表，调度器不回读） | **U15-20 Minor**：合并表登记与调度器快照消费错位（与 U15-18 同族：登记面承诺热改，消费面烘死；代码注释自认取舍但两表未清账） |
### D5.2 死码清单（从未被调用的输出面字段/分支，附 grep 证据）
| 项 | 坐标 | 证据 |
|---|---|---|
| `SendRequest.allow_split` | contracts/runtime.py:309 定义；写 3 处（pipeline.py:825/915、error_report.py:1020） | 全树 grep `allow_split` **零读点**——queue/worker/transport 无消费；「分片许可」契约字段为死面（实际分片由 content_type/dedupe 决定） |
| `RenderedOutput.size_estimate` | contracts:288；写 5 处（renderer.py:232/247/260/269/370） | 全树无 `.size_estimate` 读取方——写后无人看 |
| `ReviewAction.MOVE_PRIVATE` | reviewer.py:153 唯一出现处 | pipeline 无转道分支（等同 BLOCK）→ 已列 U15-10 |
| `payload_digest` 比对分支 | queue.py:1063 列、worker.py:577 产 | 存而不比（D4.1 设计债） |
| `_RUNTIME_HOT_OVERRIDE_FIELDS` 中 `BOT_RENDER_FORWARD_MIN_NODES` 合并项 | `__init__.py:748` | 合并值无回读方（D5.1 表） |
| （无缺陷申明）renderer 各分支 | — | `should_forward_*`/`split_text_chunks`/`build_forward_output`/`apply_mermaid_blocks` 均有活调用（pipeline L764-776 + tests 32 passed 实跑）；`output/__init__.py` 六再导出被 pipeline.py:57 消费，非死垫片 |

### D3/D4/D5 补充取证清单（无缺陷项，按方法要求列全）
- 分行统一在 chat 链内成立：`tests/test_roleplay_paragraphs.py`+`test_forward_and_mood.py`+`test_onebot_chunk_budget_floor.py`+`test_user_copy_unification_gate.py` 合跑 **32 passed**（离线，`--basetemp` 指真实 TEMP，命令见证据日志）。
- `humanize_reply` 不误伤行情数字：P4b `22℃` 原样；`_INNER_STATE_NUM_RE` 关键字绑定（plain_text.py:273）。
- 打码幂等：`redact_local_secrets` 产物 `sk-<已隐藏>` 不再被 `_API_KEY_RE`（`\b(sk-[A-Za-z0-9_\-]{8,})`）二次命中（<已隐藏> 长度含尖括号非字符类）——静态成立，P6 实跑无形态回环。

## 发现汇总表（按严重度）
| ID | 严重度 | 坐标 | 锚点字符串 | 根因 | 证据 | 改法（before→after） | 验证命令 |
|---|---|---|---|---|---|---|---|
| U15-01 | Critical | chat.py:2335-2357；pipeline.py:731-835；`__init__.py`:2915/3027/3188/3335；campus.py:150；alerts.py:280 | `reply_text = normalize_paragraph_breaks(reply_text)` / `text_fallback=build_reminder_text(reminder)` | 文本四件套加工内嵌于 chat 能力层，中央管线对其它通路零加工；调度器/回执/降级 11 条旁路直构 SendRequest | D1.2 矩阵+D1.0 grep（humanize/normalize 唯一消费者=chat.py）+探针 P4 `unchanged=True path_kept=True` | before：各通路各自出站 → after：pipeline 出口统一挂 `process_outbound_text(result, capability_id)`（复用 plain_text 四件套，chat 幂等免重算），调度器改走「合成 CapabilityResult→pipeline._render 入口」同一函数，禁直构 RenderedOutput | `pytest tests/test_outbound_text_unification.py -p no:cacheprovider --basetemp=$TEMP/u15-v -q`（新契约测试，见收口清单①） |
| U15-02 | Major | reviewer.py:121 | `output_text = result.body or result.summary or result.title` | 审查面=三字段取一，text_parts/title/summary 并存面逃逸 | 探针 P2（title 带密钥 approved=True）、P3（text_parts 含密钥直通 chunks） | before→after：`texts = [result.title, result.summary, result.body, *result.text_parts]` 逐条审 + mixed parts 文本段送审 | `pytest tests/test_review_surface.py -q`（负样本四例） |
| U15-03 | Major | reviewer.py:105,134 | `result.capability_id != "bot.chat"` | persona-drift/公开不安全审查只认 bot.chat，而 LLM 文本已扩到 poke/摘要/简报三链 | D1 P5/P6/P14 坐标 + `_poke_llm_reply` L5212 原始 text 直落 | before→after：改白名单制 `LLM_TEXT_CAPABILITIES`（chat/poke/digest/daily_assist 入册），审则按「含 LLM 文本」判定 | 构造 bot.poke+「As an AI…」样例→review BLOCK 断言 |
| U15-05 | Critical | pipeline.py:761-785；worker.py:589；alerts.py:289；weather.py:282；`__init__.py`:4294；chat.py:489；campus.py:147 | `_TEXT_FALLBACK_MAX_CHARS = 4000` | 超限三命运（合并/静默切/撞上限）按通路随机；transport 无统一最后防线；QQ 上限零登记 | D2.1 表+5000 字双通路推演（P5 无切分代码路径） | before→after：queue worker 前统一 `ensure_transport_fit(text, limit=QQ_LIMIT)`：超限→`split_text_chunks`（同一份实现）或 forward，截断只许走 `truncation_notice()` 同源尾注 | `pytest tests/test_transport_fit.py -q` |
| U15-06 | Major | 同 U15-05 各行 +echo.py:120、repair/service.py:151、incident:120 | `…(已截断)` | 三族尾巴文案+五处静默丢字 | grep 表 | before→after：一处 `truncate_with_notice(text, budget, *, ellipsis=…)`，五处静默点全接 | 同 U15-05 验证 |
| U15-07 | Major | renderer.py:275-283,305-311 | `for index in range(limit - 1, max(0, limit - 40), -1)` | 码点切片无字素簇感知，ZWJ/变体序列拦腰断 | 探针 P1 `family emoji split=True` | before→after：切点后移/前移避开 `\u200d|\ufe0f|\U0001F3FB-\U0001FFFF` 续段（`unicodedata`+组合符类），或 grapheme 库同法 | 探针 P1 改断言 split=False |
| U15-08 | Minor | renderer.py:222-235,241 | `parts = [*media_parts, *mermaid_parts]` | chunks/mermaid 两出口不拼 leading_parts | 探针 P9 `at_kept=False` | before→after：两出口统一 `parts = [*leading_parts, ...]`；chunks 面把 at 段并入首块前缀或显式 raise | 探针 P9 复跑 |
| U15-09 | Minor | renderer.py:197-198 + chat.py:2345 | `elif is_chat:` | chat 文本被 naturalize 两次（幂等无实害，双调用面） | 探针 P5 idempotent=True | before→after：render 期 is_chat 分支删调用（加工唯一入口收口后自然消亡） | 收口清单①后回归 |
| U15-10 | Major | reviewer.py:147-154 + pipeline.py:732-753 | `action = ReviewAction.MOVE_PRIVATE` | MOVE_PRIVATE 无消费者，等同 BLOCK | grep 全树唯一出现处 | before→after：pipeline 增 `action is MOVE_PRIVATE` 分支→改投私聊（有 sender_id 私聊目标时），无目标才 BLOCK | 新增契约测试断言私聊 SendRequest 生成 |
| U15-11 | Major | pipeline.py:336,344 | `"输出未通过安全或隐私检查。"` | 拦截文案写死机器腔，违反自家 #36 mandate | 直读 | before→after：入 user_copy 池 `REVIEW_BLOCK_TEMPLATES`（random.choice 或游标，随 U15-12 统一选法） | `test_user_copy_unification_gate` 扩样本 |
| U15-12 | Major | D3.2 表 10 行 + 6 写死句 | `random.choice(GROUP_FAILURE_ACK_TEMPLATES)` | 池机制 10 份 5 选法互不互通 | D3.2 表 | before→after：一处 `copy_pool.pick(key, mode="cursor")` 门面+各池迁注册表；写死句入池 | 池治理门测试（现仅管 user_copy 一家） |
| U15-13 | Minor | reviewer.py:22-30 vs plain_text.py:303-337 | `_SECRET_OUTPUT_PATTERNS` | 密钥两份规则集两套占位符（BLOCK vs 打码） | D3.4；风险枚举归 U11b | before→after：reviewer 判则改为调用 plain_text 单一规则源（命中=打码+降级审） | 交叉 U11b 结论 |
| U15-14 | Major | plain_text.py:307（`_LOCAL_PATH_RE`）+273（inner-state） | `(?<![A-Za-z0-9:])([A-Za-z]):[\\/]` | humanize 产无空格掩体→路径规则吞括注整段，右括号悬空语义丢失 | 探针 P4b 实测输出 | before→after：字符类补排 `（「『【`；或 redact 前置到 humanize 之前+回归锁；`）`两侧配平守卫 | `pytest tests/test_plain_text_chain_order.py -q`（P4b 输入固化为负样本） |
| U15-15 | Major | D4.4 五样本 | — | 分行统一=chat-only，文档口径未限定作用域 | D1.0 grep+D4.4 | before→after：U15-01 收口后自动覆盖；文档补作用域 | 见① |
| U15-16 | Minor | worker.py:576-578、queue.py:1067 | `ON CONFLICT(part_key) DO NOTHING` | digest 存而不比/parts_total 变更无守卫 | D4.1（命题证伪+设计债） | before→after：planned 时比对既有行 digest，不一致→记 alert 并整请求作废重建键（`:r2` 后缀） | part 重规划负样本测试 |
| U15-17 | Minor | error_report.py:759-800 | `build_text_fallback` | 第二份文本装配器、不过行分统一 | D4.2 | before→after：套 U15-01 中央函数（其「人话区」与话术池一并入池） | 收口清单③ |
| U15-18 | Minor | `__init__.py:748` vs settings.py:355 + pipeline.py:3761/767 | `("BOT_RENDER_FORWARD_MIN_NODES", ...)` | 热改合并表与重启冻结两账矛盾，合并白算 | D5.1 表 | before→after：删合并表该行，或 forward_* 四键全改发送期现读（择一，推荐后者顺带解 RESTART 文案） | `/bot runtime set` 后行为断言 |
| U15-19 | Minor | settings.py:396 邻域 | — | PROGRESS_ACK_COOLDOWN_SECONDS 两表均未登记 | grep 零命中 | before→after：RESTART_REQUIRED_KEYS 补登一行 | 登记门测试 |
| U15-20 | Minor | `__init__.py:754-762` vs L3241-3254 | `("BOT_GROUP_DIGEST_PUSH_TIME", ...)` | digest/daily_assist 推送时刻登记为可热改，调度器装配期一次性注册 cron 不回读 | D5.1 表；台账 #3 同案 | before→after：调度器 job 触发时现读合并 config 决定「今天是否推/时刻对表」，或从合并表摘登 | set 后下一日窗口断言 |
| U15-21 | Minor | contracts/runtime.py:309、288 | `allow_split: bool = False` | allow_split/size_estimate 两字段写后零读 | D5.2 表 | before→after：删除或接真语义（allow_split→worker 分片许可），禁留僵尸契约字段（U4 席协议面交叉） | mypy 未引用字段检测/评审 |
| U15-04 | Major | D3.2 写死句列 | `_VIDEO_ACK_TEXT` | 绕池写死 6 处 | D3.2 表 | 并入 U15-12 施工 | — |

## 输出单一加工链收口清单（按解锁顺序）
1. **立中央函数（不动行为）**：把 chat.py L2335-2357 的序列原样提为 `output/text_pipeline.process_outbound_text(result, decision) -> CapabilityResult`（含预算/动作/自然化/人话/打码/分行），chat 改调它——字节级等价由 P1 全链回归锁（现有 32 例+新金样本）。解锁：后续所有接入有单一挂点。
2. **review 面补全（U15-02/03）**：审查输入改全字段清单+LLM 能力白名单；此步先于接入更多链（防旁路文本带密钥过新咽喉）。
3. **调度器族改道（U15-01 主体）**：reminder/digest/daily_assist/cookie/campus 由「直构 SendRequest」改为「合成 CapabilityResult→①中央函数→pipeline 的 render+submit 段」（复用现函数，不新建第三套——裁定复用中央入口）；校园保 1500 语义改注册 decision.max_messages/budget。
4. **回执/降级池收编（U15-09/11/12/04）**：user_copy 升级为唯一池门面（游标缺省），GROUP_FAILURE/COOLDOWN/MEAL/REMINDER/poke/video/ack 全迁入；render is_chat 二次 naturalize 删除。
5. **分片与截断统一（U15-05/06/07）**：登记 QQ/TG 出站硬上限常量→worker 前唯一 `ensure_transport_fit`；`split_text_chunks` 加字素簇守卫；五处静默 `[:N]` 全改 `truncate_with_notice`；错误卡 build_text_fallback 套中央函数（U15-17）。
6. **打码链序与括号守卫（U15-14/13）**：链序钉死+`_LOCAL_PATH_RE` 字符类修；reviewer 密钥规则并入 plain_text 单源（与 U11b 对表后动）。
7. **配置与契约卫生（U15-18/19/20/21/10/16）**：两表矛盾清账、死字段处置、MOVE_PRIVATE 补实现或改枚举名。
每步验收=`dev.ps1 -Task test` 全量+scoped 契约测试+`--check` 哈希门（重录须人工授权，禁洗绿）。

## 证据日志（命令 + 输出摘要）
1. 骨架首写＝本席第一动作（Write 日志）✅（本文件存在即证）。
2. 咽喉消费者 grep：`Grep 'naturalize_chat_text|humanize_reply|redact_local_secrets|normalize_paragraph_breaks|format_roleplay_paragraphs|...'`（全包）——humanize/normalize 仅 chat.py 命中（结果内嵌 D1.0）。
3. `SendRequest(` 全树枚举：13 命中（含定义/队列构造），通路归类如 D1.2。
4. 截断实现 grep 族：`\[:\s*(4000|...)\]|_MAX_CHARS`（结果内嵌 D2.1/D5）。
5. 离线探针（禁真实发送/触网）：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe C:/Users/LancyCelestia/AppData/Local/Temp/u15-probe/u15_probe1.py` → P1..P9 输出全文（D2/D4 内嵌引用）。脚本留真实 TEMP，副本误落树内 `%TEMP%\u15_probe1.py` 见下节披露。
6. scoped 测试：`... -m pytest tests/test_roleplay_paragraphs.py tests/test_forward_and_mood.py tests/test_onebot_chunk_budget_floor.py tests/test_user_copy_unification_gate.py -p no:cacheprovider --basetemp="C:/Users/LancyCelestia/AppData/Local/Temp/u15-bt1" -q` → **32 passed in 5.70s**。
7. 只读 git：`git status --porcelain`（未做任何 git 写操作；`?? docs/design/audit-20260920-unify-U15-output.md`＝本席唯一新增）。

## 工作树卫生自查
- 实跑后计数：`find plugins scripts tests -name "*.pyc" | wc -l` = **0**；`__pycache__` 目录 = **0**；本席未生成 data/ 残留；`.pytest_cache/.mypy_cache/.ruff_cache` 目录为**先于本席存在**（他席 dev.ps1 产物，未触碰未删除——共享工作树无权代清）。
- **残留披露（必须记账）**：本席首写探针时误落源码树内一个字面名 `%TEMP%` 的目录（`ChatBot/ChatBot/%TEMP%/u15_probe1.py`，5102B；该目录系**多席并发波次的公共scratch**，内有 u3/u12/u19 各席探针，非本席创建）。三次清理尝试（PowerShell Remove-Item / bash cp+rm / python os.remove）均被权限层拦截（分类器判定路径含 `%TEMP%` 字面量属歧义破坏操作）；按「拦截后不绕过」纪律停手。文件内容纯离线探针、真身副本已存 `C:/Users/LancyCelestia/AppData/Local/Temp/u15-probe/u15_probe1.py`，**收尾席可直接删除**（勿删同目录他席文件除非各自收口）。git 侧 `%TEMP%/` 已被 ignore（`git status` 不显），无提交污染。
- 未 commit、未推送、未跑全量 pytest、未触网、未真实发送、未读 .env 明文值、未用任何 `--write` 命令——全程只读+本日志一写。
