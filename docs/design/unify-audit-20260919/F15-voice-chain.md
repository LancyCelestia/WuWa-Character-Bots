# F15 · 语音前端链路审计（voice-chain）

> **快照声明**：本文件由语音前端链路审计代理 F15 生成。
> **取证时间**：`date` = **2026-09-19 16:36 +0800**（工作区墙钟）。
> **快照态**：共享工作树，多会话在飞；所有坐标取自本报告生成时工作树实况，重启/他席落库后可能位移。
> **纪律声明**：本轮 TTS 全域（`domains/media/**`、`config.py`、`echo.py`、`tests/test_tts*`、`settings.py`、`.env`）**一律只读**。除本文件外零新建/零编辑/零删除。零 `--write`、零服务启停、零真实合成/发送、零真实网络。直跑仅 `command_catalog.py --check`（只读，EXIT=0）。定向 pytest 被环境自动模式分类器拦下（判为触 TTS 在飞域），**未绕开**，改以静态读码 + 只读脚本取证。
> **归属背景**：本席与「Wave T（2026-09-19 TTS 专项 10 子席，见 `docs/design/tts-audit-20260919.md` + 记忆 tts-audit-20260919）」重叠但互补——Wave T 主打引擎/合成/后端，本席只取「语音链的**前端可见面**」。Wave T 已证而后端归属的项，本席引用不重复记账，并标注「非前端可改」。

---

## 0. 结论摘要（先给裁决）

- **语音出站是否走统一协议**：**是**。bot.tts 产物经 `CapabilityResult.audio` → 中央 renderer → `{"type":"record"}` mixed 部件 → 统一 SendQueue/onebot sender 出站；生产 matcher `_is_tts_event` 也**先经中央路由决策**（`_cached_route_decision(...).kind is RouteKind.TTS`）。未发现绕过中央出站/直连 `send_record_msg` 的语音旁路。
- **入站语音是否走统一契约**：**是**。ASR 转写结果与图片/视频结果一样并入同一 `composed_query`（`query_text`），带 `[语音转写结果（不可信上下文，仅供参考）]` 标签，无独立旁路契约。
- **「必然播不出/无声」形态**：**4 条**（其中 1 条 Wave T 已证后端、需真机终判；2 条前端可读码定；1 条 by-design）。
- **帮助/路由/catalog 五处闭合**：**已闭合**，09-17 那次语音 help-路由缺口**当前不复存在**（catalog `--check` = current 77 topics，EXIT=0；`test_help_alias_word_actually_routes` 在位锁死别名可路由）。**缺项 0**。
- **`bot_tts_*` 四本账缺口**：三本（config.py / config-catalog / .env.example）**20/20 齐全**；唯 **控制面 SETTABLE/RESTART = 0/20**、WebUI 设置面 0 条 → 「改不到、看不见」全压在这一本账上。
- **WebUI 对 TTS 的可观测性裁决**：**完全不可见**（WebUI `tts|TTS|语音` 零命中；control_plane/api 无 TTS 端点；合成失败被折叠成成功形态 text，不进 error-card/告警）→ 属**中央可观测性缺口**，坐实「一切先经中央」主张在 TTS 这一路**仅在路由/出站层成立，观测/配置层不成立**。
- **前端可改 vs 必须交 TTS 席**：本席发现**无一条属「前端独立可改」**——全部落在 TTS 域（`domains/media/capabilities/tts.py`）、控制面白名单（`settings.py`）、根 `__init__.py`（他席独占写）。本席只出取证与方案，改动权归主会话/TTS 席。

---

## 1. 语音出站形态盘点（任务①）

全树「语音/音频消息」出口形态清点（TTS 相关 + 同通道邻居）：

| # | 出口形态 | 载体坐标 | 引用方式 | 是否走统一出站 | 判定 |
|---|---|---|---|---|---|
| V1 | bot.tts 命令合成语音 | `domains/media/capabilities/tts.py:502` `audio=[{"file": str(path)}]` | 本地绝对路径（wav） | **是**：`CapabilityResult.audio`→renderer→record→SendQueue→onebot | 合规统一 |
| V2 | bot.tts 对话自动配音 | `tts.py:624-629` `result.model_copy({"audio":[...]})` | 同上 | **是**，与 chat 正文并存（record 段前置） | 合规统一 |
| V3 | renderer audio→record 映射 | `domains/render/renderer.py:210-215`（默认 `part_type="record"`，可被 `type` 覆盖为 `voice`） | — | 中央映射 | 合规统一 |
| V4 | onebot record 段构造 | `domains/transport/sender/onebot.py:279-284` `_segment_from_mixed_part` | `file`/`url`，`_resolve_local_file_ref` 归一（315-323） | 中央 sender | 合规统一（**不校验文件存在**，见 §2 C3） |
| V5 | 点歌 voice 输出模式 | `domains/music/capabilities/music.py`（voice=语音部件，`config.py:484/734` 试听下载目录） | 音频文件 | 走同一 renderer/record 通道（能力自带 audio） | 属 music 域，非 TTS，登记不分叉 |
| V6 | CQ 码语音 | grep `CQ:record`/`[CQ:record` **全树零命中** | — | — | 无 CQ 码语音拼装点（语音全走结构化段） |
| V7 | `file://`/base64/data: 引用 | `onebot.py:318` 原样透传，`test_tts_outbound_chain.py:180-188` 锁死 | 三形态透传 | 统一 | 支持但 TTS 实际只用本地绝对路径 |

**直连绕过核查**：`send_private_msg`/`send_group_msg` 直连点集中在 `domains/transport/sender/onebot.py:480-590`（这是队列最终调用的 sender 本体，非旁路）与 `outbound_registry.py` 登记的 `__init__.py:4440-4444 / 5378-5382 / 5730-5740`（摘要/提醒/其它，**均为 text，不含语音**）。**未发现任何语音绕过统一出站网关的直连 `send_*_msg`。** → 「统一协议」在语音出站**成立**。

---

## 2. 「必然播不出 / 点了无声」形态清单（任务②，含依据）

> 「试听 URL 的生成实现」：**bot 侧不存在**。全树无任何为**用户可见**拼装的 GPT-SoVITS `GET /tts?...` 试听地址（grep `9880/tts?`/`urlencode tts`/TTS+试听 **零命中**；命中的「试听」全属 mail preview / music 点歌 / control-plane action preview / divination preview，与 TTS 无关）。技能 §10.4 的 `GET /tts` 试听是**引擎自带的浏览器地址**，仅供管理员/工程师本机核验，产品从不把它发给 QQ 用户。→ 用户侧「试听」概念在 bot 内**不存在**；用户只能收到一条 record 语音消息。

| # | 形态 | 依据（坐标/协议） | 前端可见后果 | 严重度 | 归属 |
|---|---|---|---|---|---|
| C1 | **引擎推理异常返回 `200 + 1 秒静音 wav`**，bot 仅判 `content` 非空 | `tts.py:340-345`（只有 `if not response.content` 空判，无解码/时长/能量校验）；`tts.py:61-64` 注释自承「运行环境没有 soundfile/mutagen，读不了时长」 | 用户收到一条**能点开但只有静音**的语音，且被 `_store_cache` 当成功缓存，**永久命中静音** | **P1**（Wave T 已证；**需真机终判**引擎确返 200 静音） | **TTS 后端/域**（非前端可改） |
| C2 | **`bot_tts_enabled=false`（config 缺省）且引擎人肉启动** | `config.py:296` 缺省 False；`tts.py:430` disabled→`SILENT_AUDIT` 静默；生产 `.env` 据 Wave T 为 true 但 9880 无常驻 | 用户发「说 …」→ 走 `_is_tts_event=False`→ **落回人格 chat**（把「说 今天的潮汐」当聊天回一句），**没有任何「语音未开」提示** | **P1**（常态性「不可能出声」，Wave T 引擎启动项） | 后端/部署（非前端可改）；**前端可见缺口=无告知**，可改点见 §7 |
| C3 | **record 段不校验文件是否存在** | `onebot.py:279-284` 仅取 `file`/`url` 非空；`_resolve_local_file_ref:320-323` 不存在则**原样返回相对路径**；`test_tts_outbound_chain.py:191-193` 明确锁死此行为 | 若 wav 写盘失败被吞/缓存文件外部删除/相对路径跨 CWD → record 段带打不开的路径 → SnowLuma 侧**无声或报错** | **P3**（低概率，`_lookup_cache:258` 命中前查 `is_file`，仅竞态/落盘失败时暴露） | TTS 后端（sender 归 transport 域） |
| C4 | **wav 在 QQ 侧的可播性** | 引擎 `media_type:"wav"`（`tts.py:308`），record 段交 SnowLuma 转 silk；**bot 无任何时长/采样率/大小/格式护栏** | 长文本→长 wav（`bot_tts_max_chars=200` 截断缓解），SnowLuma 对 wav 的解码/时长上限 | **未知·需真机验证**（无据不判「播不出」） | SnowLuma/引擎侧（非前端可改） |

**结论**：C1、C2 是「用户点了必然播不出/听到静音」的两大真实形态（均 Wave T 后端归属，需真机终判）；C3 为窄竞态；C4 无据不下「播不出」结论，标「需真机验证」。**四条无一条在纯前端可独立修**。

---

## 3. 入站语音链审计（任务③）

链：语音消息 → 预转码 → ASR → 人格上下文。

- **统一摄取**：`__init__.py:678` `AUDIO_SEGMENT_TYPES = frozenset({"record","voice","audio"})`（注释 676-677：此前只认 `record`，TG 语音入站**完全不识别**，评审需求 3 已修）。`contains_audio_message_segments:695`。
- **预转码**：`__init__.py:1125-1160` `_transcode_record_segments`：SILK 裸流 ffmpeg 解不了 → `bot.call_api("get_record", out_format="mp3")`，写回 `data.transcoded_path`。**带 `asyncio.wait_for(timeout=20.0)`（1149-1151），SnowLuma 偶发挂起不返回时不会永久卡该用户后续消息**（此处超时护栏到位，与 TTS 出站 httpx 逐操作超时形成对照）。失败 `except`→静默跳过、段保原样（1153-1157）。
- **ASR 转写**：`chat.py:2985-3006` `extract_audio_source(raw_segments)` →（`effective_asr_enabled ∧ asr_provider 非空 ∧ 预算未过期`）→ `transcribe_audio(..., timeout_seconds=bot_asr_timeout_seconds 缺省20)` → 成功则 `composed_query += "[语音转写结果（不可信上下文，仅供参考）]\n{transcript}"` → `build_context(query_text=composed_query)`。
- **绕过统一摄取的语音处理点**：控制面 `api/platform.py:410-414` 有**第二条 ASR 消费路径**（admin 调试：`kind=="audio"` → `build_asr_provider`+`transcribe_audio`），属运维工具，非用户消息链，不计为旁路缺陷。
- **转码失败/无 ASR key 的用户可见行为**（任务③-②）：
  - `bot_asr_enabled` **缺省 False**（`config.py:558`）。关闭/无 key/失败时，ASR 段整块跳过，**无任何面向用户的「这条语音我没能转写」告知**。
  - 入站若**纯语音无文字**，占位文本 `"（用户发送了语音消息，未附文字。）"`（`__init__.py:1377`）成为 `plain_text` 进链；ASR 关闭时人格即对着这句占位符回复——**表现为「答非所问」而非「明示未识别」**。这是入站侧「统一可观测/统一告知」的缺口（与 §7 文案相关）。
- **语音识别结果与文本是否同契约**（任务③-③）：**同契约**。转写以**标签内联文本**混入 `composed_query`（与 `[视频识别结果…]` 同构），进 `query_text` 单一字段；**无独立的结构化「转写来源/时间戳/字段名」契约**——来源仅靠 `[语音转写结果…]` 中文标签，非类型化字段。对「统一契约」是**达成但偏弱**：图片/视频/语音三者用同一 composed_query 软拼接，无 per-segment 溯源字段。

---

## 4. 语音帮助/路由闭合性复验（任务④，09-17 缺口）

五处交叉比对（bot.tts / 「语音」）：

| 声明面 | 坐标 | 状态 |
|---|---|---|
| RouteKind 枚举 | `base_router.py:129` `TTS = "tts"` | ✅ |
| 路由判定闭包 | `base_router.py:431-438` `tts_match`（`bot_tts_enabled` 门 + `is_tts_command`） | ✅ |
| RouteRule | `base_router.py:577` priority 41 | ✅ |
| InterfaceEntry | `base_router.py:619` help_topic=`"语音"` | ✅ |
| 中央 registry | `capability_registry.py:278-281` RouteCapabilityDecl(command=True,matcher_name=tts_match)、`415-417` InterfaceDecl、`521` HelpTopicDecl(admin_only=False) | ✅ |
| NoneBot 生产 matcher | `__init__.py:6076/6116` `_is_tts_event`+`on_message(priority=41,block=True)` | ✅ |
| echo 帮助四表 | `_PUBLIC_HELP_TOPICS:272`、`_HELP_CATEGORIES:301`、`_HELP_ENTRIES:2258-2281`、`_HELP_ENTRY_META:3074-3104` | ✅ |
| `docs/command-catalog.md` | `## 语音`（2273-2278，别名/自然语言触发齐） | ✅ |
| `docs/route-matrix.md` | 行 47（handler=`_is_tts_event` 真实存在、priority 41、触发词全） | ✅ |

- **只读门实跑**：`command_catalog.py --check` → `command catalog is current (77 topics)`，**EXIT=0**，无语音条目漂移。
- **触发词双向**：路由 `DEFAULT_TRIGGER_WORDS`（`tts.py:54-57`，11 词）与 help（`_HELP_ENTRY_META` aliases+triggers_nl+triggers_nickname，3079-3080）词级互相覆盖，行为锁 `test_help_alias_word_actually_routes`（`test_tts.py:143-151`）+ `test_trigger_bidirectional_gate.py`（LEDGER 双向）在位。
- **裁决**：**09-17「语音 help-路由缺口」当前已闭合，缺项 0**。（诚实：因分类器拦下 pytest，双向门/registry 门**未实跑**，闭合判定基于五处坐标静态全在 + `catalog --check` 通过；如需铁证请主会话放行定向 pytest。）

**唯一闭合隐患（非缺口，是「一旦配置就破口」）**：见 §6-①——`BOT_TTS_TRIGGER_WORDS` 三处文档/帮助写「追加合并」、实码 `extract_tts_text:138` 是「非空即整表替换」。管理员一旦自定义触发词，内置 11 词全失效 → **帮助仍列 说/语音/念… 但路由不再认** → 双向门在「config 空」下测得绿、在生产「config 非空」下实际破口（门用空 config，抓不到）。

---

## 5. 语音在 WebUI 的呈现（任务⑤）

- **WebUI**：`grep -rn "tts|TTS|语音" webui/src` **零命中**（仅 sse.ts/tokens.tsx 泛匹配 `audio/voice` 子串，非 TTS）。WebUI **无任何语音相关端点、页面、设置项、试听入口、TTS 用量/成本、语音失败率**。
- **control_plane/api**：`grep tts/语音` **零命中**，无 TTS 数据端点。
- **stats/cost 是否含语音**：webui `calls.tsx:186` 仅有通用 `by_capability` 调用计数；TTS 合成**不进 LLM 账单**（`llm/ledger.py` 只记 generate 出口，TTS 是本地 HTTP 合成非 LLM）→ 成本无、失败率无。
- **致命观测缺陷**：合成失败在 `tts.py:486-493` 返回 **`kind="text"` 的成功形态 CapabilityResult**（人话降级），**不抛异常** → **error-card（`runtime/error_report.py`）与告警（`runtime/alerts*`）对 TTS 零命中**（grep 证实）→ **TTS 失败率对中央观测面完全隐身**。
- **裁决**：**属中央可观测性缺口**（P1，命中用户「TTS 也要先经中央」命题）。
- **最小可行呈现建议（只出方案，不改码）**：
  1. 中央能力结果**区分「降级成功」与「正常成功」**：`_degrade` 分支给 `audit_tags=["tts","synthesize_failed"]`（已有），但需让 stats 聚合按 `audit_tags` 计「语音失败率」，而非只看 exception。
  2. control_plane 加**只读端点** `GET /api/v1/tts/stats`（成功/失败/降级/平均合成时延/缓存命中率），读 `_last_failure_reason` 与合成计数（需先把 §Wave T 的死退避计数器改成真活指标）。
  3. WebUI 设置面板把 `bot_tts_enabled`/`bot_tts_api_url` 等纳入 **SETTABLE/RESTART_REQUIRED 展示**（见 §6 缺口）。
  4. 可选「试听」入口：仅当引擎在跑时，把 `bot_tts_api_url + /tts?...`（urlencode，技能 §10.4）呈现为**管理员控制面链接**，不进用户消息面。

---

## 6. `bot_tts_*` 配置键的前端可见面 · 四本账（任务⑥）

| 账本 | 权威源 | 登记数 | 缺口 |
|---|---|---|---|
| ① `config.py`（源真值） | `config.py:296-325` | **20/20** | — |
| ② `docs/config-catalog-full.md`（A26） | 805-825 行 | **20/20** | **语义错 1 处**：809 行 `_tts_trigger_words` 写「与内置…**合并**」，实码整表替换（见下 §6-①） |
| ③ `.env.example` | 618-647 行 | **20/20** | 同上 trigger_words 注释口径（627 行示例为空未点破语义） |
| ④ 控制面 SETTABLE/RESTART + WebUI 设置 | `domains/chat_reply/runtime/settings.py:333/454` | **0/20** | **20 键全缺**：无一进 `SETTABLE_KEYS`/`RESTART_REQUIRED_KEYS`；WebUI 无设置项 |

**AGENTS #42 记「catalog 1 失败 = TTS 席 bot_tts_* 未登记」现状核实**：**已不再是整块未登记**——catalog/.env/config 三本账现均 20/20（本读码时点，属他席可能已补齐；以本快照为准）。`command_catalog --check` EXIT=0。**真正未闭合的是第四本账（SETTABLE/RESTART + WebUI）0/20**，与 Wave T「20 键零个进 SETTABLE/RESTART」一致。

**缺口键名（全部 20，第四本账 0 登记）**：
`_tts_enabled, _tts_api_url, _tts_gptsovits_dir, _tts_ref_audios, _tts_trigger_words, _tts_output_dir, _tts_max_chars, _tts_timeout_seconds, _tts_speed_factor, _tts_temperature, _tts_top_k, _tts_top_p, _tts_text_lang, _tts_text_split_method, _tts_cache_enabled, _tts_auto_reply_enabled, _tts_auto_reply_scope, _tts_auto_reply_max_chars, _tts_auto_reply_probability, _tts_auto_reply_always`。

> 「统一变量」在用户面前的直接体现：这 20 个键**改不到（控制面白名单无、WebUI 面板无）、看不见（stats/设置无）**，只能改 `.env` + 重启；而 catalog 已把它们写得「像可管理」→ **写着存在、实际中央管不着**。

---

## 7. 文案与人格一致性 · 前端出口（任务⑦）

用户可见文案定义点（全在 `tts.py`，**inline 硬编码，不入「五池话术」统一池**）：

| 场景 | 坐标 | 文案 | 守岸人语气 | 技术串泄漏 | 锁 |
|---|---|---|---|---|---|
| 只发裸触发词 | `tts.py:447` | 「在「说」后面接上想让我念的话就行…」 | ✅ | 无 | 有（`test_capability_bare_trigger_gives_guidance` 610） |
| 清洗后空 | `tts.py:458` | 「这段话里没有能念出来的内容…」 | ✅ | 无 | 未见 body 级锁 |
| 缺参考音频 | `tts.py:409-419` `_no_ref_audio_hint` | 「请在 **BOT_TTS_REF_AUDIOS** 里填…相对路径以 **BOT_TTS_GPTSOVITS_DIR** 为基准」 | 半（夹配置键名） | **有**（两个 env 键名上屏） | **有**（`test_tts.py:619` 断言 `"BOT_TTS_REF_AUDIOS" in body`，属**有意设计**并被锁） |
| 合成失败降级 | `tts.py:400-406` `_degrade` | 三句守岸人口吻（嗓子没接上/差参考音频/没能发声） | ✅ | 无 | **有**（`test_degrade_copy…:586-590` 锁「含守岸人词 + 不含『服务返回』」） |

**诚实裁决**：语音链文案**总体守规矩**——`_degrade` 有行为锁保证不吐技术串、保语气；`_no_ref_audio_hint` 的配置键名上屏是**测试主动锁死的有意设计**。但两点未达「统一」：
1. 文案**内联在 tts.py**，未接入项目「五池话术 + `output/plain_text.redact_local_secrets`」统一出口 → 违反「统一函数/统一变量」的文案单一源。
2. `admin_only=False`（`capability_registry.py:521`）+ `_no_ref_audio_hint` → **普通用户**误触发即可看到运维级配置指引（信息可达性面，非崩溃）。建议：no-ref/degrade 类「配置指引」文案下沉为 admin-only 可见或改走统一话术池 + `redact` 剥键名。
3. **入站侧**无「语音未转写」的用户话术（§3）——语音默认不识别时人格对占位符乱答，缺一句守岸人「这条语音我先听着，暂时没转成字」。

---

## 8. 回归锁盘点 + 最小语音链结构锁设计（任务⑧）

**现有锁（读码判定）**：
- `test_tts_outbound_chain.py`（17 例）：**真行为锁**——三段断言 `audio→mixed record→onebot record 段`，覆盖 title/body 必须空、无 file 丢弃、URL/缺失路径透传、e2e。**但未锁「QQ 能否解码 wav」任何一环**（Wave T 结论坐实）。
- `test_tts.py`：触发词命中/边界/最长优先、`parse_ref_audios`/`pick_ref_audio`（仅返回存在的文件）、`clean_for_speech`、`_request_tts` 请求体契约（POST 键名、`media_type=wav`）、错误体解析顺序、`_degrade` 语气、能力四态（disabled/bare/no_ref/成功）。
- `test_trigger_bidirectional_gate.py` + `test_capability_registry.py` + `test_documentation_consistency.py` + `test_config_catalog_covers_config_fields`：闭合一致性门（词/计数/meta 测试路径存在/catalog 覆盖）。

**裸奔项（无锁）**：
1. **合并 vs 替换语义**：`test_custom_trigger_words_extend_defaults`（`test_tts.py:167`）名曰「extend」却**只验自定义词生效、从不验内置词在自定义后是否仍路由** → §4 的破口无门可抓。
2. **200+静音 wav 被当成功**：无「校验解码/时长/非静音」的用例（因实码根本不做此校验）。
3. **`_last_failure_at`/`_HEALTH_BACKOFF_SECONDS` 死代码**：写了不读（`tts.py:85-87` vs `_request_tts` 无前置读），退避从未生效 → 无任何锁能发现「退避是假的」。
4. **record 段文件存在性**：`test_tts_outbound_chain.py:191-193` 反而**锁死了「不存在也原样发」**的行为，即缺失路径出站是 by-design、无更上层护栏。
5. **TTS 失败可观测性**：失败折叠成成功形态 text，无「失败应进 stats/alert」的锁。

**最小语音链结构锁设计（建议新增，pytest 常驻，全离线）**——断言「触发词 ↔ 路由 ↔ 帮助 ↔ catalog ↔ 四本账」五方闭合：
```
test_voice_chain_closure.py（设计，不落码）
 ├─ 路由↔帮助：DEFAULT_TRIGGER_WORDS ⊆ {help 别名∪triggers_nl∪triggers_nickname} 且反向成立
 │   且「BOT_TTS_TRIGGER_WORDS 非空时，内置词仍路由」——把 §8-1 的 extend 语义钉成契约
 │   （或反向钉「替换」并强制 catalog/help/.env 三处文档同步改口径，二选一，禁现状劈叉）
 ├─ 路由↔catalog：从 _HELP_ENTRY_META["语音"].triggers_* 生成的 topic 行 == docs/command-catalog.md「## 语音」（复用 catalog --check 语义）
 ├─ RouteKind↔matrix：RouteKind.TTS 在 route-matrix.md 有且仅一行，handler 符号 _is_tts_event 可导入
 ├─ 四本账：set(config bot_tts_*) == set(catalog _tts_*) == set(.env.example BOT_TTS_*)
 │   且 每条 bot_tts_* 要么在 SETTABLE_KEYS/RESTART_REQUIRED_KEYS、要么显式登记「restart-only」白名单（杜绝 §6 第四本账静默为 0）
 ├─ 出站段契约：synthesized 结果必走 record 段（已有）+ **新增「文件必须存在或降级为文案、绝不发不存在路径」**（反转 §8-4）
 └─ 文案：_degrade/_no_ref 走 redact（若采纳 §7 下沉）
```

---

## 9. 新发现台账（七要素：严重度｜坐标｜锚点｜根因｜建议 before→after｜验证｜回归锁）

> 均为**读码推断**（除标「需真机」外），未下「已修复/已生效」措辞。跨 Wave T 的后端项标注归属，不重复裁权。

**F15-1｜P1｜`domains/chat_reply/runtime/settings.py:333,454`（SETTABLE_KEYS/RESTART_REQUIRED_KEYS）**
- 锚点：`grep -in "tts" settings.py` → `NO tts keys in SETTABLE/RESTART_REQUIRED whitelist`
- 根因：20 个 `bot_tts_*` 无一进控制面白名单；无「每能力键须可管」门，故静默为 0。中央「可观测/可管理」在 TTS 配置层不成立。
- 建议：`before` 0/20 登记 → `after` 至少 `bot_tts_enabled`/`bot_tts_api_url`/`bot_tts_auto_reply_*` 进 RESTART_REQUIRED（只读可见）或 SETTABLE（可热改），其余进 restart-only 清单，令 WebUI 设置页可见。
- 验证：`grep -c bot_tts settings.py`（应 >0）+ 新 `test_voice_chain_closure` 四本账子断言。
- 回归锁：**无**（无门要求登记）。→ 归属：控制面/中央配置层（非 TTS 独占，主会话可裁）。

**F15-2｜P2｜`config.py:304` + `docs/config-catalog-full.md:809` + `.env.example` + `echo.py` help**
- 锚点：`BOT_TTS_TRIGGER_WORDS` 文档「（与内置…合并）」（catalog 809）vs `tts.py:138` `triggers = tuple(trigger_words) if trigger_words else DEFAULT_TRIGGER_WORDS`
- 根因：非空即**整表替换**，三处文档写「追加合并」→ 管理员加一词=内置 11 词全灭=帮助/路由劈叉（§4 破口）。
- 建议：`before` 语义劈叉 → `after` 二选一并全仓同步：(A) 代码改真追加（`DEFAULT + custom`）或 (B) 文档/help/.env 三处改口「设置即替换内置，须一并列出内置词」。
- 验证：新锁用例「设 `bot_tts_trigger_words=["来段语音"]` 后 `is_tts_command("说 你好")` 仍 True（A 案）/False 且文档一致（B 案）」。
- 回归锁：**无真锁**（`test_custom_trigger_words_extend_defaults` 名不副实）。→ 归属：**TTS 席**（域代码）+ 文档三处。

**F15-3｜P2（可观测性）｜`tts.py:486-493` + `runtime/error_report.py`/`runtime/alerts*`（零命中）**
- 锚点：合成失败 `CapabilityResult(kind="text", body=_degrade(...))` 成功形态返回
- 根因：失败被折叠成正常文本 → 不进 error-card/告警/stats → TTS 失败率对中央隐身。
- 建议：`before` 隐身 → `after` 失败计数入只读 `tts/stats` 端点（按 `audit_tags` 含 `synthesize_failed`），或降级路径记可聚合指标。
- 验证：`grep tts control_plane/api`（应出现 stats 端点）+ 指标用例。
- 回归锁：**无**。→ 归属：TTS 域（发端）+ 控制面（收端），非前端可改。

**F15-4｜P1（前端可见时延）｜`__init__.py:341-360` `_attach_voice_reply` + `tts.py:475-485`**
- 锚点：`result = await inner(...)` 后 `await asyncio.to_thread(maybe_attach_voice, ...)`，外层**无 `asyncio.wait_for`**；内层 httpx `timeout=bot_tts_timeout_seconds` 缺省 **60.0**（`config.py:307`）
- 根因：自动配音时文字回复同步等整次合成，引擎挂起可拖到 60s（Wave T「时延兜底不成立」坐实；与入站 `_transcode` 的 `wait_for(20s)` 形成不一致）。
- 建议：`before` 无外层超时 → `after` 对 `to_thread` 包 `asyncio.wait_for(<配音预算，如 8-15s>)`，超时原样返回纯文字；或配音彻底后台化不等文字。
- 验证：配音超时用例（假 httpx sleep > 预算 → 断言文字仍按时出）。
- 回归锁：**无**（test_tts 全 mock 立即返回，不测时延）。→ 归属：根 `__init__.py`（他席独占写）+ TTS 域，**非前端可改**。

**F15-5｜P3（文案单一源）｜`tts.py:400-419,447,458`**
- 锚点：`_degrade`/`_no_ref_audio_hint`/引导文案 inline
- 根因：语音文案未入「五池话术 + plain_text redact」统一出口；`_no_ref_audio_hint` 把 env 键名上屏（虽 admin_only=False 仍可达普通用户）。
- 建议：`before` 内联 → `after` 收进统一话术池 + `redact_local_secrets` 剥键名，或配置类指引改 admin-only。
- 验证：文案池成员断言 + `assert "BOT_TTS_" not in 用户可见 body`（若下沉）。
- 回归锁：**部分**（`_degrade` 有 586 锁、`_no_ref` 有 619 锁死「须含键名」——即当前锁**锁的是反方向**）。→ 归属：TTS 域 + 文案池，前端可提议但改在域内。

**F15-6｜P3（入站无告知）｜`__init__.py:1374-1379` + `chat.py:2986`**
- 锚点：`text = "（用户发送了语音消息，未附文字。）"`；ASR 关闭/无 key 整段跳过
- 根因：`bot_asr_enabled` 缺省 False 时，用户语音被占位符顶替、人格乱答且无「未转写」明示。
- 建议：`before` 静默乱答 → `after` ASR 关闭/失败且入站为纯语音时，给一句守岸人「这条语音我还没能转成字」的可控告知（受会话/概率门约束，避免刷屏）。
- 验证：纯语音 + asr_disabled 用例断言人格收到可辨识信号（非占位符直答）。
- 回归锁：**无**。→ 归属：入站 `__init__.py`/chat 域，前端可提议改在域内。

**引用 Wave T（后端，非本席新账，仅登记前端可见后果）**：200+静音 wav 当成功（C1）、引擎人肉启动+enabled（C2）、缓存键缺声音身份维度换权重仍命中旧音色、`data/tts_output` 磁盘无界未接 `enforce_quota`——均属 TTS 后端域，本席不重复记账。

---

## 10. 前端可改 vs 必须交 TTS 席 / 其它席（任务边界收口）

| 发现 | 能否纯前端改 | 归属 |
|---|---|---|
| F15-1 SETTABLE/WebUI 0/20 | ✗（改 `settings.py` 控制面 + webui） | 控制面/中央配置层（主会话裁） |
| F15-2 触发词合并/替换劈叉 | ✗（代码在 `tts.py`） | **TTS 席**（域码）+ 文档三处 |
| F15-3 失败可观测隐身 | ✗（域码 + api） | TTS 席 + 控制面 |
| F15-4 配音拖慢文字 | ✗（`__init__` 他席独占 + 域 timeout） | TTS 席/根装配 |
| F15-5 文案 inline 未入池 | 部分（提议前端出，改在 `tts.py`/文案池） | TTS 席 + 文案池 owner |
| F15-6 入站无「未转写」告知 | 部分（提议前端出，改在 `__init__`/chat） | 入站域 |
| 「试听 URL」用户侧不存在 | 属产品事实，非缺陷 | — |
| 五处闭合缺口 0 / catalog --check 绿 | — | 现状即达标 |

**净结论**：本席**没有一条能纯前端独立落改**；产出的是取证 + 方案，执行权在主会话/TTS 席/控制面。前端能「提议」的是文案池化（F15-5）与入站告知（F15-6），但落点仍在域内。

---

## 11. 诚实与证据边界

- 已实跑的只读证据仅一项：`command_catalog.py --check`（EXIT=0，77 topics，无语音漂移）。
- 定向 pytest（test_tts / outbound_chain / trigger_gate / capability_registry / documentation_consistency）被环境自动模式分类器**拦下**（判为触 TTS 在飞域），**未绕开分类器**；相关「闭合/锁」判定为**读码推断**，非实跑绿证。若需铁证请主会话放行语音定向小集（basetemp 置于仓库外 `$TEMP`，`BOT_AUTOSYNC=0`）。
- 未读 `.env` 明文（纪律）；「生产 `bot_tts_enabled=true`」引自 Wave T 记忆，标「非本席实证」。
- 「播不出」类结论：C1/C2 需真机终判、C4 无据不下结论、C3 有码据（sender 不校验存在）。
- 全程零服务启停、零真实合成/发送、零端口占用、零 kill；除本文件外零写入。
