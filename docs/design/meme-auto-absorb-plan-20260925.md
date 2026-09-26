# 表情包自动吸收与情绪化发送方案（2026-09-25 核实 + 计划）

> 身份：**方案件，零施工**。本波只核实与规划，未改任何代码/配置/`.env`/人格/测试文件。
> 触发需求（用户原话第 12 条）：
> 「检验表情包生成、表情包发送系统是否可以正常工作。需要开启自动爬取吸收功能，如果表情包的主体里有守岸人，那么就自动吸收，并且根据需要，能在对用户的问答、戳一戳等场景时能根据 bot 的情绪、心理、感情和好感度，发送符合话题、bot 人格设定和用户喜好的表情包，禁止重复发送同一表情包，禁止发送无关话题、不讨用户喜欢的表情包。」
> 追加裁定（2026-09-25）：**自动爬取/抓取执行归她本地跑，agent 只写代码与开关** ⇒ 本件第六节把两侧切开并给出接口约定。
> 计数一律以机器册 `docs/auto-facts.md` 为准（AGENTS 规则 10）；本文件里的「现算值」都标了取值时刻，只作本次核实的证据，不作长期口径。

## 一、现状结论（能力 × 现在能不能用 × 证据 × 缺哪一环）

| 能力 | 现在能不能用 | 证据（path:line，行号随树漂移，以符号名为准） | 缺哪一环 |
|---|---|---|---|
| 表情包**生成**（`bot.meme` → 本地 meme-generator-rs） | 代码与开关都在（`.env` 现值 `BOT_MEME_API_ENABLED=true`），命令面已路由已注册；**但本机 `127.0.0.1:2233` 现算无监听** ⇒ 今天发命令只会收到诚实降级「表情包服务未启动或不可达（…）」 | 能力体 `domains/meme/capabilities/meme.py::build_meme_capability`（`enabled = getattr(config,"bot_meme_api_enabled",False)`）＋降级支 `_service_down_result`；路由 `domains/chat_reply/runtime/base_router.py::meme_match` / `RouteRule(RouteKind.MEME,"bot.meme",20,…)`；在册 `domains/chat_reply/runtime/capability_registry.py`（`matcher_name="meme_match"`）；配置现算 `scripts/load_runtime_config.py` → `bot_meme_api_enabled=True` / `bot_meme_api_base_url='http://127.0.0.1:2233'`；端口 `netstat -ano` 现算 2233 零命中；历史产物 `ChatBot_Runtime/data/memes/`（3 个 `meme_5000choyen_*/meme_nokia_*`，时点值） | 服务常驻与否**在她的机器面上**，bot 侧无可修。要判定「可达」必须真调一次 `GET /meme/version`——本波未调（禁启停进程、不对服务发请求），故**生成链路今天是否可用＝未判定**，只有「历史跑通过＋今天端口无人监听」两条实据 |
| 群图**自动收库**（`absorb_event_images`） | **今天活着**：库与文件都在（现算 7434 行 / 7434 文件，时点值），三重门都通 | `domains/meme/sources/meme_library_listener.py::absorb_event_images`（`bot_meme_library_enabled` ∧ 群会话 ∧ 白/黑名单）→ `_download_once`（SSRF 唯一真身 `domains/files/sources/downloader.py::check_download_url`，入口＋逐跳落点双查）→ `MemeLibraryStore.add`（`md5` 主键去重）；装配 `__init__.py`（`meme_library_store = MemeLibraryStore(...) if bot_meme_library_enabled else None`）＋ `@meme_absorb.handle()` 里的功能门 `bot.plugin.meme_library.auto_absorb`（该 id 在 `domains/ops/features/feature_catalog.py::_SUBFEATURE_ROWS` 在册，现算 `registered=True`） | —— 收库这条腿不缺件 |
| 收库后**自动打标**（VLM：is_meme/情绪/场景/NSFW/persona_hint） | **不成立**：库有 7434 行，但 `persona_hint` 全为 `common`（现算 7434/7434），`description` 非空只有 392 行且多数是离线导入脚本写进去的**文件名主干** | 开关链 `_spawn_vlm_task` 只在 `getattr(config,"bot_meme_library_vlm_enabled",False)` 为真时投；`.env` 现算 `bot_meme_library_vlm_enabled=False`；即便打开也取不到端点——`_resolve_vision_config` 读 `bot_meme_library_vlm_preset`，生产现算值是**空串**，回落 `bot_meme_library_vlm_model/_base_url` 也全空 ⇒ `if not (model and base_url): return` 早退；生产 `BOT_VISION_MODEL_REGISTRY` 唯一预设名是 `myvlm`，而代码缺省写 `deepseek-vision`（现算 `registry.get('')`/`.get('deepseek-vision')` 都是 `None`）；`docs/config-catalog-full.md` E1 段早已把该键的「样例空 ≠ 代码缺省」记为在册差异 | ①开关关；②预设名对不上注册表键 ⇒ **无标签＝无主体判定＝无「按守岸人自动吸收」**。今天唯一在起作用的「守岸人加权」是 `_PRIORITY_HINTS`/`bot_meme_library_prefer` 对**文本**的字面命中（现算权重最高两行 24.0 就是文件名恰含「守岸人」的那两张），属误吸面而非设计内的主体识别 |
| **情绪/心情驱动主动发表情包**（双层表情第二层） | **代码在、今天结构上永不触发** | 编排 `__init__.py::_maybe_send_reaction_meme`（独立 `_REACTION_MEME_GATE` 五门＋`_reaction_meme_daily` 每日上限＋C1 悲伤门，投递走 `_send_parts_through_unified_pipeline`）；选图 `domains/meme/reactions/engine.py::pick_reaction_meme`（意图→`_REACTION_MEME_INTENT_TERMS` 检索词→`weighted_pick`）；调用点门 `switches.enabled("bot.plugin.chat.reactions.meme")`；而 `bot.plugin.chat.reactions.meme` **不在功能册**（`_SUBFEATURE_ROWS` 只有 `reactions.receive/emotion/after_reply`；现算 `registered=False`），且 `domains/ops/features/feature_gate.py::FeatureSwitchSnapshot.enabled` 是 `states.get(feature_id, False)` —— 未登记即 False（同文件 `ProductFeatureGate` docstring 明写 fail-closed 是有意设计） | 登记这枚 sub-feature（**一行**，且必须同笔补一条「根文件里每个 `switches.enabled("bot.plugin.…")` 字面量都在册」的常驻门，否则同型洞会再长回来）。⚠ 与 AGENTS 台账 #35 的口径冲突见第七节 |
| 命令式发送 `/偷表情` | **可用**（现算 `bot_meme_library_enabled=True` ⇒ 能力与库都在） | `domains/meme/capabilities/meme_library.py::build_meme_library_capability`（会话冷却 `bot_meme_library_cooldown_seconds=20`、`nsfw_max=0.2`、`_pick_with_mood` 低落软重抽）；装配 `__init__.py`（`build_meme_library_capability(meme_library_store, config, mood_valence_fn=…)`） | 无话题相关性（只有可选关键词过滤）、无用户喜好、**无「不重复」**（`weighted_pick` 是 `random.choices`，`used_count` 只记账不参与排除） |
| 戳一戳场景发图（poke v2「表情包」形态） | **可用** | `__init__.py::_pick_poke_meme`（`store.weighted_pick(keyword="", nsfw_max=…)`）→ `_send_parts_through_unified_pipeline(…, prefix_parts=@段, image=…, capability_id="bot.poke")` | 同上，且选图**无关键词**＝纯随机加权，跑题面最大 |
| 选择信号：bot 心情 / 好感 / 用户喜好 | 心情只有一处、好感与喜好**零接入** | 心情唯一消费点 `meme_library._pick_with_mood`（阈值 `_MOOD_LOW_VALENCE=-0.25`，与 `domains/chat_reply/character/mood.py` 低落档同源，读失败回中性）；`BotMoodStore.snapshot()/willingness_factor` 与 `DynamicAffinityStore.snapshot(sender_id)`（返回 `affinity/tier/attitude/tags/nickname/profile_notes`）都**没有**任何表情选择消费点；`domains/meme/sources/reaction_store.py` 只有 **emoji 贴纸回应**的聚合统计，无 meme 维度喜好 | 缺「合分口径」整件：现成可借的只有 `weighted_pick(weight)` 这一根乘积杆 |
| 禁止重复发同一表情包 | **不存在** | `MemeLibraryStore` 的 `md5` 只保证**入库**去重（`INSERT OR IGNORE`）；`mark_used` 只 `used_count+1`；没有任何「本会话已发集合」读点 | 缺 per-session 已发窗口（可借先例：`engine.py::ReactionBuffer`（deque＋TTL＋LRU 封顶）与 `ProactiveGate._reacted/_rolled`（一次登记不再二次掷骰）） |
| 出站闸是否在发送路径上 | 表情走的这条路上**没有** `outbound_gate`；安静时间与角色 blocked **有** | `domains/transport/sender/outbound_gate.py` 的生产 import 只有 `domains/emergency_info/service/push.py`（现算）；表情与 poke 走 `pipeline.handle/handle_async` → `SendRequest` → `send_queue`；安静时间在 `domains/chat_reply/runtime/pipeline.py`（`quiet_hours = self.quiet_hours_checker.check(message, capability_id)`，拦截静默留审计），角色门同文件（`role_settings`），功能门同文件（`feature_gate`）；`bot_outbound_gate_enabled` 缺省 False 且生产 `.env` 无该行 | 若把「主动发」升格为**主动投递**（非回复附带），就必须改走唯一出口 `submit_active_push`，那时键形/限流/安静顺延才执法——这是方案里 D-2 的取舍点 |

小结三句：**生成**这条腿今天不可判定（服务端无监听，端口未调）；**发送**这条腿今天只有「用户主动要」（`/偷表情`、戳一戳）能用，「bot 主动发」那条形**因为一枚没登记的功能门 id 而整条黑**；**自动吸收按主体=守岸人**这条今天完全不存在——不是缺判定件，是判定所依赖的标签根本没被写过。

## 二、判定「主体＝守岸人」该走哪个已有中央件

**不新建模型调用，不新建第二真身。** 现成两件，各有边界：

1. `domains/media/ingest/vision_describe.py::build_vision_provider`（→ `DynamicVisionProvider`，预设表真身 `bot_vision_model_registry`）——媒体归档就是吃它：`domains/media/capabilities/media_archive.py` 以 `_ARCHIVE_PROMPT` 作 system、`provider.generate(messages, temperature=0.1, max_tokens=300)` 出 JSON。**但注意**：它判的是 `ip_source`（作品/画师）与 `character`（角色名），且 `_ARCHIVE_PROMPT` 里这两个字段是**自由文本**（明写「判不出写 未识别」/「判不出写空字符串」），**没有受控词表**。所以「主体＝守岸人」不能靠现 prompt 直接判出来，必须补一层本地受控匹配。
2. `domains/media/digest.py::media_digest`（sha256 全长 64 hex，中央媒体字节摘要唯一真身）——内容身份的唯一口径，用于与媒体归档跨库对账。

**方案（判定归一、词表不新建）**：

- 判定=「VLM 给的 `character` 文本 × 守岸人别名表命中」，别名表**唯一源**＝`personas/shorekeeper/aliases.txt`（现读点 `domains/chat_reply/runtime/aliases.py::_load_persona_alias_file` ＋ 硬编码兜底 `DEFAULT_PERSONA_NICKNAMES`，两侧有 `tests/test_nickname_default_seed.py` 锁同齐），**不再抄一份守岸人名单**；新增键若需要覆盖，只准「追加」不准「替换」（缺省＝派生并集）。
- 收库侧：把打标 prompt 的输出**扩一个字段**（`character`），判定在本地做；打标路径仍唯一走 `meme_library_listener._tag_with_vlm`，禁第二 scanner、禁在导入脚本里判主体。
- 前置修复（S0，见第八节）：先把 `_resolve_vision_config` 的预设名与生产注册表键对上（生产现值键名 `myvlm`），并把 `bot_meme_library_vlm_enabled` 打开的权交给她——否则本节所有判定都是空的。

## 三、入库字段 / 去重 / NSFW 降权（现状 + 目标）

现状表 `memes`：`md5`(PK) / `path` / `ext` / `group_id` / `added_at` / `used_count` / `is_meme` / `description` / `emotion_tags` / `scene_tags` / `persona_hint` / `nsfw_score` / `weight`（`domains/meme/sources/meme_library.py::_SCHEMA`）。
现状权重（`_score_weight`）：`nsfw_score>=0.8` → **0.0（永不再被选中）**；非表情 ×0.25；命中 `_PRIORITY_HINTS`（守岸人/岸宝 8.0、鸣潮/战双/库洛 4.0、ACG 1.5）；命中 `bot_meme_library_prefer` 再 ×2.0；`nsfw_score>=0.2` 再 ×0.3。删除侧：`_tag_with_vlm` 命中 `bot_meme_library_nsfw_delete`（0.8）即 `store.remove`（连文件一起删）。

目标（**只加列、不拆列**，家规＝ALTER-if-missing，先例＝affinity 三列 / memory_store_v21）：

| 新列 | 语义 | 为什么 |
|---|---|---|
| `content_sha256` | 中央 `media_digest` 全长口径 | md5 只做主键兼容；跨库对账与「同一图两处来源」要靠 sha256 |
| `subject_persona` | 0/1＋`subject_basis`（`vlm` / `filename` / `manifest`） | 「主体=守岸人」唯一执法位；`subject_basis` 防文件名冒充（今天 24.0 权重那两张就是 filename 来源） |
| `label_provenance` | `vlm` / `filename` / `manual` / `import_pack` | 区分真标签与文件名主干，让选择面可以只信 `vlm` |
| `last_sent_at` / `sent_count_session` | 发送侧记账（**per-session 窗口另立新表**，不落这行） | 单行只作全局最近值，会话维度必须按 (session, md5) 记 |

新表（**建议** `meme_sends` 与 `meme_feedback`，落同一库 `bot_meme_library_db_path`，登记进 `docs/db-owners.md`）：
- `meme_sends(session_key, md5, sent_at)` — 「禁止重复」的硬依据；进程内 dict 只能当快路径（重启即清＝不能对「禁止」做承诺）。
- `meme_feedback(session_key, md5, sign, at)` — 用户喜好学习：正信号=对方跟着发同类/回戳/贴表情；负信号=被要求「别发这种」或同标签连续无正反馈。

## 四、选择算法（确定性、可测、不用 random）

统一入口**只有一个**：`MemeLibraryStore.pick_for_context(...)` 的新形参，旧 `weighted_pick` 保留为再导出垫片（**禁第二评分真身**；先例＝WP9 占卜 `deck_math` 收编）。

合分（一次算清，纯函数、可单测）：

```
score = w_topic·topic + w_persona·persona_fit + w_user·user_pref
      + w_mood·mood_fit + w_fresh·novelty  − w_nsfw·nsfw_pen − 硬剔除项
硬剔除（不是降权）：① per-session 窗口内已发过的 md5；② `subject_basis=filename`
且 `label_provenance≠vlm` 且总闸未放开；③ 命中 `meme_disliked` 负词表；
④ `nsfw_score >= bot_meme_library_nsfw_max`；⑤ `weight<=0`（含 0.8 高危）
```

- `topic`：本轮用户文本抽 ≤`bot_meme_topic_terms_max` 个词，命中 `description/emotion_tags/scene_tags` 任一分词 → 1；意图词表**唯一源**沿用 `engine.py::_REACTION_MEME_INTENT_TERMS`（不新建第二份情绪词映射），新增维度只准往这张表里加。
- `persona_fit`：`subject_persona==1` → 1；命中 `bot_meme_library_prefer` 其余条目 → 0.6；纯 ACG → 0.3。
- `user_pref`：`meme_feedback` 同 (会话, 标签) 的净正样本，加**好感档**（`DynamicAffinityStore.snapshot(sender_id)["tier"]`）与**当日心情**（`BotMoodStore.snapshot().valence`）的联合缩放；档低了只是「更少发、更保守发」，**绝不发负面对抗类图**（人格红线：好感任何档位不攻击/不强硬）。
- `mood_fit`：把今天的「低落时吵闹梗软重抽」升成显式负项——吵闹词表仍唯一住 `_NOISY_MEME_TERMS`，阈值仍与 `mood.py` 低落档同源；语义保持**只调倾向、不做硬开关**（与现文档一致，防悄悄升级成硬门）。
- `novelty`：`−(近期发送次数)` 与 `−(used_count 的饱和函数)`，取代今天「`used_count` 算了没人用」的死字段。
- 决定性：**零 `random`**。同分内排序用 `sha256(f"{session_key}:{window_bucket}:{md5}")` 取前 8 hex 当伪随机序（先例＝`select_reaction_emoji` 的确定性哈希兜底、`ProactiveGate` 的确定性概率骰）；`window_bucket` 必带（按日/按小时滚桶），否则同一会话永远第一张。
- 候选扫描上限沿用 `_PICK_SCAN_LIMIT`（有界最坏成本），**不得**改成全表回读。

## 五、反骚扰门（全部缺省关或保守）

序（任一门不过即不发，且**不因门不过而报错**）：

1. 总闸 `bot_meme_auto_send_enabled`（缺省 **False**）。
2. 场景门：**只在已有回复之后**（沿用今天第二层的位置），或用户显式 @/命令；戳一戳沿用 poke v2 既有三选一，不改语义。
3. 名单门：群白名单 `bot_meme_auto_send_group_whitelist`（**空＝群面关闭，绝不猜群**）、群黑名单永远赢；私聊 `bot_meme_auto_send_private_whitelist`（本方案**有意**取「空＝关闭」，与 `bot_content_route_*`/ack 族的「私聊空＝放开」**不同**，理由＝表情包是图片出站、不可撤回，见第八节 D-1 待裁）。
4. 情绪/角色门：blocked 角色与安静时间由管线执法（`pipeline.py` role gate / `quiet_hours_checker`），本域**不建第二份**；悲伤/低落词族 C1 门沿用 `engine.py::is_sad_message` 唯一真身。
5. 每消息去重 + 「本消息已骰一次」：直接复用 `ProactiveGate`（`_reacted`/`_rolled`/LRU 封顶），不新写第二颗门。
6. 概率（确定性哈希）×会话冷却×每小时滑窗×每日上限：沿用今天的四件形态，但**数值全线下调**（概率 0.05、冷却 300s、每小时 2、每日 4；今天 0.15/120s/20/6）。
7. 不重复门：per-session `meme_sends` 窗口（`bot_meme_no_repeat_window_seconds` 缺省 7 天）＋同图全局最近值。
8. 讨嫌门：同会话连续 `bot_meme_dislike_streak` 次零正反馈的标签进 `meme_disliked`，命中即候选剔除（不是降权）。

## 六、她本地抓取 → bot 现读入库：**接口约定**（两侧切开）

### 6.1 分工

| 侧 | 负责 | 说明 |
|---|---|---|
| 她（本地） | 爬取、下载、人工粗筛、**跑导入/落清单** | bot 永不主动联网抓表情库 |
| 我（代码＋开关） | 现读入库、字节校验、去重、打标调度、主体判定、选择与发送、门禁、观测 | 只读她放好的目录，不产生网络流量（除可选 VLM 打标调用） |

### 6.2 第一阶段接口（**已验证的路**，零新代码即可用）

她跑现成脚本：`python scripts/import_meme_packs.py --source <目录> [--dry-run]`。
该件今天已具备：MD5 去重、原子写盘（tmp→`os.replace`）、拷贝后 md5 复验、幂等（库已有 md5 不覆盖标签）、并发安全（短事务＋SQLite timeout 15s）、Bot 在跑也可执行。落点缺省即生产真身（`runtime_path("data/meme_library…")`）。
**已知短板（第二阶段要治）**：`description=文件名主干`、`persona_hint` 恒 `common`、`nsfw_score` 恒 `0.0`、`is_meme` 恒 `True` ⇒ 权重表会把「文件名带守岸人」的普通图顶到 24.0（现算实锤）。故第一阶段只当「搬运」，**不得**把「已导入」叙述为「已按主体吸收」。

### 6.3 第二阶段接口（清单文件，需要主体标注时再上）

- 收件目录：`ChatBot_Runtime/data/meme_inbox/`（配置键 `bot_meme_inbox_dir`，进 `path_fields` 重映射）
  ```
  data/meme_inbox/
    manifest.jsonl
    <pack>/<file>.{gif,webp,png,jpg,jpeg}
  ```
- 清单格式：**JSON Lines**（一行一个 UTF-8 对象，`ensure_ascii` 无关，允许注释行以 `#` 开头即跳过），字段：

  | 字段 | 必填 | 语义 |
  |---|---|---|
  | `path` | 是 | 相对 `meme_inbox/` 根的相对路径；**含 `..`、绝对路径、软链一律拒绝并点名跳过**（目录消毒先例＝media_archive） |
  | `sha256` | 是 | 字节 sha256（中央 `media_digest` 全长 64 hex 小写）；bot 侧**重算并比对**，不信任清单 |
  | `size` | 否 | 字节数，仅作快路径与限额 |
  | `ext` | 否 | 与真实 magic bytes 不符则**以真实为准**，不一致记一行 WARNING |
  | `subject_hint` | 否 | 她的人工标注：`shorekeeper` / `wuthering_waves` / `other` / `unknown`；`shorekeeper` 才可在无 VLM 时置 `subject_persona=1`，`subject_basis=manifest` |
  | `source` | 否 | 来源标识（入库溯源，只进 `description` 之外的旁证列，不参与权重） |
  | `crawled_at` | 否 | ISO8601 带偏移；缺失按收件时刻，**不猜** |
  | `nsfw_hint` | 否 | 0.0–1.0；只作**下限**（清单说高、VLM 说低 ⇒ 取高），绝不因清单说 0 而免检 |

- bot 侧唯一新件：`domains/meme/sources/meme_inbox_scanner.py`（周期任务，装配期由总闸门控，**任一闸空即整链不注册**，先例＝campus/emergency 三重门）。职责严格限定：读清单 → 校验（sha256 复算、magic bytes、大小/每日限额）→ 拷贝进 `bot_meme_library_dir` → `store.add(md5=…)` + 写新列 → 丢进**既有**打标队列（`list_untagged`/`backfill_meme_tags`）→ 标记清单行 `consumed`。
  明确**不做**：不联网、不判主体（判在打标侧）、不删她的原目录（只写自己的 consumed 台账）。
- 活性约定（防「存在≠在用」那类假绿）：`/bot status` 加一行 inbox 现读态（待处理行数 / 本轮消费数 / 被拒原因计数），并有一条装配可达性 AST 锁（先例＝紧急域 R1/R2/R3 三把门、ack 族装配锁）。

## 七、与 AGENTS 台账口径的冲突（照实列，不改台账）

1. **#17「F6 meme 主动调用：有意不上线半吊子版」**——实况更糟也更好：一条半吊子版**已经在码上**（#35 落的双层表情第二层），但它不是「有意不上线」而是**被一枚没登记的功能门 id 关黑**（`bot.plugin.chat.reactions.meme` 不在 `feature_catalog._SUBFEATURE_ROWS`，门 fail-closed）。所以「未上线」结论成立，**归因不成立**：修一行登记就会立刻变成「上线且缺省概率 0.15/每日 6」，那才是她当初拒绝的半吊子版 ⇒ 该洞**不许顺手修**，必须与第五节的名单/去重/讨嫌门同笔落地。
2. **#35「双层表情第二层…独立门+互斥+C1 悲伤门」**被记为「代码+测试完成，重启生效」——`重启生效` 不成立（生效条件是功能册登记，不是重启）。`tests/test_runtime_subfeatures.py` 只测了 `meme_library.auto_absorb` 与 poke 两族，**没有一条**覆盖 `reactions.meme` ⇒ 一条绿套件把一个不可达分支照成了已交付。
3. **第四部分功能表**「表情贴纸回应 | `runtime/reactions.py`」——该文件自 v21r2 起是 605 字节再导出垫片，真身 `domains/meme/reactions/engine.py`（现算）。属命名/路径口径漂移，指向真身即可，本波不改 AGENTS。
4. **#17「生成器已配好（2233 端口 enabled）」**——开关确实 enabled（`.env` 现算 True），但**端口今天无人监听**（`netstat` 现算零命中），故「已配好」不等于「可用」；且历史上真跑通过（`data/memes/` 有产物）。

## 八、待裁点（她点头才做）

- **D-1** 私聊主动发：本方案取「私聊白名单空＝关闭」（比 ack/亲密族更保守）。若她要求沿用旧口径（空＝放开），需明确改哪一行判据。
- **D-2** 「主动发」是否升格为**主动投递**：保持今天「回复后附带」形态 ⇒ 不受 `outbound_gate` 管辖（该闸本身缺省关、键形线上不执法）；升格走 `submit_active_push` ⇒ 得到顺延/限流/键形执法，代价是多一条 SQLite 队列与幂等键治理。推荐**保持现形态＋本域自建名单/窗口门**，等出站闸开闸再谈。
- **D-3** `bot_meme_library_vlm_*` 三件套是否**整体退役**、改吃中央 `build_vision_provider` + `bot_vision_model_registry`（推荐：退役旧三键的读点、只留 `_vlm_enabled`/`_timeout`，预设名统一到 `myvlm` 一类注册表键）。属第二真身清零，改生产面，需授权。
- **D-4** 群库图他人隐私：`0.2 ≤ nsfw_score < 0.8` 区间今天「降权 ×0.3 后仍可发」，是否改成**永不外发**（只可自己看）。
- **D-5** 中央调度收编：`bot.meme`/`bot.meme_library` 描述符现算 `execution=None`（在册表总行数时点值 121），属 AGENTS #49「prepared 余批六枚含 meme_library」那笔，要改生产根文件 ⇒ 排队，不在本方案内顺手做。

## 九、配置键清单（全部缺省关或保守；四处同生）

「四处同生」＝①`config.py` 字段（含必要的 `path_fields` / id-list 校验器）②`docs/config-catalog-full.md` 行（键名可省 `BOT_` 前缀，由 `tests/test_doc_sync_gates.py::_normalize_catalog_key` 还原，白名单 `KNOWN_MISSING` 现为空集，**新键必进册**）③`.env.example` 注记 ④`domains/chat_reply/runtime/settings.py` 的 SETTABLE / `RESTART_REQUIRED_KEYS` 判定（装配期快照一律进 RESTART，禁做「看起来能热改」的假键）。

| 键 | 缺省 | 备注 |
|---|---|---|
| `bot_meme_inbox_scan_enabled` | `False` | 总闸；关＝扫描器不注册 |
| `bot_meme_inbox_dir` | `data/meme_inbox` | 进 `path_fields` 重映射 |
| `bot_meme_inbox_scan_interval_seconds` | `300` | >0 |
| `bot_meme_inbox_batch_limit` | `20` | 每轮上限，防打爆 |
| `bot_meme_inbox_daily_limit` | `200` | 每日消费件数上限（media_archive 限额同型） |
| `bot_meme_subject_absorb_enabled` | `False` | 「主体=守岸人 → 自动吸收并标注」总闸 |
| `bot_meme_subject_extra_aliases` | `[]` | **只追加**到 `personas/<profile>/aliases.txt` 派生并集，禁替换 |
| `bot_meme_selection_v2_enabled` | `False` | 关＝旧 `weighted_pick` 逐字节行为 |
| `bot_meme_score_weights` | `""`（内置保守档） | 只接受结构化 JSON；解不出即退回内置档并 WARNING，不静默 |
| `bot_meme_topic_terms_max` | `4` | |
| `bot_meme_no_repeat_window_seconds` | `604800` | 7 天同会话同图不重发 |
| `bot_meme_dislike_streak` | `2` | 进负词表的连续零正反馈次数 |
| `bot_meme_auto_send_enabled` | `False` | 主动发总闸（第五节第 1 门） |
| `bot_meme_auto_send_probability` | `0.05` | 确定性哈希掷骰 |
| `bot_meme_auto_send_cooldown_seconds` | `300` | |
| `bot_meme_auto_send_max_per_hour` | `2` | |
| `bot_meme_auto_send_daily_max` | `4` | |
| `bot_meme_auto_send_group_whitelist` | `[]`（空＝群面关闭） | id-list 宽容装载（int→str 先例，`793e647`） |
| `bot_meme_auto_send_group_blacklist` | `[]` | 黑名单永远赢 |
| `bot_meme_auto_send_private_whitelist` | `[]`（空＝关闭，见 D-1） | |

**本波不动任何生产配置**：上表只写在文里，不写进 `config.py`/`.env`/`.env.example`。

## 十、验收判据（可机检）与实施顺序

新常驻门（负样本必红）：
1. `tests/test_runtime_subfeatures.py` 追加：**根文件里出现的每个 `switches.enabled("bot.plugin.…")` 字面量都必须在功能册**（AST 抽字面量 × `build_product_descriptors()` 的 id 集）。这一条今天就会红于 `reactions.meme`——先注毒自证（把新登记的 id 从册里删掉必红），再随 S2 转绿。
2. `tests/test_meme_subject_absorb.py`：别名表派生并集（含繁简/兜底名单同齐）、`subject_basis` 三态、清单校验四态（sha256 不符/穿越/magic bytes 不一致/`nsfw_hint` 只作下限）、端到端「清单行 → 库行 → 消费标记」。
3. `tests/test_meme_selection_v2.py`：合分纯函数（同输入同输出、双跑字节一致）、五条硬剔除各一红、`window_bucket` 轮换（反向锁：去掉 bucket 必出现同会话恒第一张）、旧开关关闭时与 `weighted_pick` 逐字节同形。
4. `tests/test_meme_inbox_interface.py`：扫描器装配门（任一键空＝不注册）、限额、异常单行点名不带走整轮、`/bot status` 现读行。
5. 复跑基线（本波实跑，见末节）：meme/reaction/poke 族 **97 passed**；`tests/test_descriptor_wiredness_ledger.py` **20 passed**。任何后续波次不得让这两组变红。
6. 生成物三件 `--check` 归零（`command_catalog` / `doc_sync` / `board_doc_sync`）＋ `verify_hashes --write` 后 `--check` EXIT 0——若他波在飞漂移被一并写入，如实报备不代修。

「一处变更处处跟随」清单（新增能力/开关必跟）：`echo.py::_HELP_ENTRIES` + `_HELP_ENTRY_META`、`docs/route-matrix.md`、`docs/db-owners.md`（两张新表）、`docs/config-catalog-full.md`、`.env.example`、`docs/acceptance-manual.md`（真机条目）、三件生成物。

实施顺序（每步可独立回滚，**全部缺省关**）：
- **S0 修标签链**：把 `_resolve_vision_config` 的预设名与生产注册表键对上（并在 `/bot status` 或重启前体检里显式报「VLM 打标：未配置/已配置但预设名不在注册表」三态，别再静默早退）。零行为变更（仍关）。
- **S1 记账不判主体**：加四个新列（ALTER-if-missing）＋ `meme_sends`/`meme_feedback` 两表＋db-owners；把现有 392 行的来源标成 `label_provenance=filename`。
- **S2 名单与门登记**：登记 `bot.plugin.chat.reactions.meme`（连同 D-5 的缺省值下调与名单门）**同一笔**，加第 1 条常驻门；此步之后「主动发」才算真上线。
- **S3 选择 v2**：`pick_for_context` 新入口＋合分＋硬剔除；开关关时逐字节旧形为。
- **S4 inbox 接口**：扫描器＋清单（她侧只需按 6.3 落文件）。
- **S5 主体判定收口**：VLM 扩字段 `character` ＋ 别名表命中 → `subject_persona`；D-3/D-4 按她裁定落。

## 十一、明确不做

- 不删 `md5` 主键、不改既有表列语义（只加列）；不动存量 7434 行库与磁盘文件（Runtime 数据不可删）。
- 不自建第二份 SSRF 咽喉（唯一真身 `domains/files/sources/downloader.py::check_download_url`）、不自建第二下载器、不自建第二打标通路、不自建第二情绪词表/吵闹词表/会话键判据（分别唯一住 `_REACTION_MEME_INTENT_TERMS`、`_NOISY_MEME_TERMS`、`domains/core/session_keys.py`）。
- 不在本方案里联网抓取任何图库站点（爬取归她），不装包，不启停进程，不改 `.env`。
- 不做动图/视频形态的表情发送（发送面 image only，与 `import_meme_packs.py` 「只导图片」的既有约束同口径）。
- 不做 Telegram 主动贴/主动发表情（`engine.py` 模块 docstring 已诚实记：适配器 0.1.0b20 不投递 `message_reaction`，TG 主动贴本仓库**不接线**任何触发点）。
- 不顺手修中央调度 `execution=None` 那笔（属 #49 的账，需改生产根文件）。
- 不降任何棘轮基线、不代修他波在册红（见下）。

## 十二、本波证据（全部实跑，可复跑）

环境（每次裸跑都带）：`PYTHONDONTWRITEBYTECODE=1`、`PYTHONPYCACHEPREFIX=C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/cache/pycache-memeverify`、`BOT_AUTOSYNC=0`、`PYTHONIOENCODING=utf-8`、pytest 另加 `-p no:cacheprovider --basetemp=<repo 外目录>`。

1. `PYTHONDONTWRITEBYTECODE=1 … python.exe -m pytest tests/test_meme_conflict_fix.py tests/test_meme_domain_fixes.py tests/test_meme_image_input.py tests/test_reaction_store.py tests/test_reactions.py tests/test_poke_v2.py tests/test_poke_notice_ingest.py tests/test_poke_unified_reaction_b10.py -p no:cacheprovider --basetemp=/tmp/memeverify-parent/run1 -q`
   ⇒ **`97 passed in 5.98s`**（这八件里**没有**任何 `xfail`/`skip` 标记，现算 grep 只在函数名里命中「skip」字样；即：绿是真绿，但**没有任何一条测到第二层可达性**——第七节第 2 条的成因）。
2. `… -m pytest tests/test_descriptor_wiredness_ledger.py …` ⇒ **`20 passed in 21.13s`**。
3. 配置现算（`scripts/load_runtime_config.py::load_runtime_config()`，即与生产 dotenv→`translate_env_keys`→`Config` 同构的那一真身，**不是**只读 `.env` 文本）：
   `bot_meme_api_enabled=True`、`bot_meme_api_base_url='http://127.0.0.1:2233'`、`bot_meme_command_enabled=True`、`bot_meme_library_enabled=True`、`bot_meme_library_vlm_enabled=False`、`bot_meme_library_vlm_preset=''`、`bot_meme_library_vlm_model=''`、`bot_meme_library_vlm_base_url=''`、`bot_meme_library_prefer=['守岸人','岸宝','鸣潮','战双帕弥什','库洛']`、`bot_meme_library_group_allowlist=[]`、`bot_meme_library_nsfw_max=0.2`、`bot_meme_library_nsfw_delete=0.8`、`bot_reactions_enabled=True`、`bot_reactions_meme_enabled=True`、`bot_reactions_meme_probability=0.15`、`bot_reactions_meme_cooldown_seconds=120`、`bot_reactions_meme_daily_max=6`、`bot_reactions_max_per_hour=20`、`bot_vision_enabled=True`、`bot_vision_mode='direct'`、`bot_vision_model_registry` 键集 `['myvlm']`。
   运行时设置覆盖面（`ChatBot_Runtime/data/settings/runtime_settings_shorekeeper.json` → `overrides`）现算**零枚** meme/reaction/vision 键 ⇒ 上述读数以 `.env`＋代码缺省为准；注册表类另有 `model_registry`/`vision_registry` 两个顶层覆盖位（本域无键）。
4. 功能门现算（`build_product_descriptors()`，节点总数时点值 102）：`bot.plugin.chat.reactions.after_reply=True`、`bot.plugin.chat.reactions.meme=**False**`、`bot.plugin.chat.reactions.emotion=True`、`bot.plugin.meme_library.auto_absorb=True`、`bot.plugin.meme=True`、`bot.plugin.meme_library=True`、`bot.plugin.poke.reply=True`。
5. 库实况只读（`sqlite3` `file:…?mode=ro`）：`memes` 总行 7434、`description` 非空 392、`weight>0` 7434、`persona_hint` 分组只有 `common`（7434）、权重最高 24.0 的两行 `description` 是含「守岸人」的**文件名主干**、磁盘 `meme_library/` 文件数 7434。
6. 端口只读枚举：`netstat -ano | grep 2233` ⇒ 零命中（grep 退出码 1）；对照 127.0.0.1 监听清单里 3001/8080 等在列，说明枚举本身有效。
7. 他波在册红（**本波不修、不降基线**，只点名）：`… -m pytest tests/test_doc_sync_gates.py::test_config_catalog_covers_config_fields …` ⇒ **1 failed**，12 枚未登记键全属 HOT 面在飞件（`bot_chat_message_coalescing_*` ×5、`bot_chat_progress_ack_*` ×3、`bot_chat_rate_limit_redrive_*` ×4）。`bot_meme_*`/`bot_reactions_*` **不在缺键名单里**（catalog 以省 `BOT_` 前缀形态登记，见 `docs/config-catalog-full.md` 的 `_reactions_meme_*` 行）⇒ 本域登记面无红。

## 十三、文档跟随与门禁（本波自身）

本件按「架构规格（design/，先成文后实现）」表登记在 `docs/README.md`（一行，与 B2–B5/`tts-contract-layer.md`/`media-digest-layer.md` 同款）。本波**只新增这一份 md 加一行索引**，未动任何代码/配置/测试。

门禁实跑（2026-09-25，同上述环境）：
`… -m pytest tests/test_doc_link_integrity.py tests/test_documentation_consistency.py -p no:cacheprovider --basetemp=/tmp/memeverify-parent/run7 -q`
⇒ **`1 failed, 43 passed in 27.44s`**。唯一红＝`test_documentation_consistency.py::test_catalog_document_matches_registry`（`docs/command-catalog.md` ≠ `_HELP_ENTRIES` 投影，差异内容是**语音 help 条目**），`git status --porcelain` 现算两枚输入件 `docs/command-catalog.md` 与 `domains/chat_reply/capabilities/echo.py` 均为**他波在飞改动**，本波只碰 `docs/README.md`（M）与本件（??）⇒ 该红与本波无关，按纪律不代修、不降基线。
另证一次可复现的**瞬时红**：同一命令的首跑（`run4`）曾报 `test_coordinate_line_capacity_ratchet` 与 `test_inflight_wave_docs_do_not_explode`（118>113）两枚，两枚单独重跑（`run6`）与整文件重跑（`run7`）均绿 ⇒ 归因＝首跑撞上了并发写入文档面的窗口，非本波引入。
