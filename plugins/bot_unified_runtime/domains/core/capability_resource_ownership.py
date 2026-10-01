"""capability_resource_ownership — 「哪一族能力共用哪一格资源」的唯一声明册（S85）.

**要治的病**：mandate 要求能力标签「与路由优先级、内容档分级、主动投递配额、渲染面
正交共存（视觉与语音同开不得互压）」。这句话在
``domains/core/capability_manifest.py`` 的教义段里只以**散文**在场（该件 :24-25），
而 ``tests/test_capability_manifest_gate.py`` 的九条 ``def test_*`` 里**没有一条**
判它（2026-09-24T00:47:59Z 现算）。本件把"谁和谁共用哪一格"变成**机器可读的数据**，
执法腿在 ``tests/test_capability_tag_orthogonality.py``。

## 本件管什么、不管什么（先划界，防第二真身）
- **不管开关值**：`bot_vision_enabled` / `bot_tts_enabled` 的真身是
  ``config.py``，本件只登记"这个键属于哪一族"，绝不复制缺省值、绝不判开关该不该开。
- **不管标签语义**：能力→标签的唯一真身是 ``capability_manifest.py::FACETS``，
  本件按 capability_id 列成员、由门反向核对两侧一致（名册涨了我不知道 ⇒ 门红）。
- **只管两件事**：①各族**专属**的开关/限额/超时/落点键清单（判"两族是否共用同一枚键"）；
  ②**共享资源账**——今天确实共用的那几格、上限真身、谁在用、A 开对 B 是排队还是否决。

## 三条教义（写进代码，也写进门）
1. **族专属键两两不相交**：任何一枚 config 键只能归一族；两族共键＝那条键就是互压通道。
2. **共享必须点名，且点名效应**：`SHARED_RESOURCES` 里凡 `effect` 为 `veto`/`preempt`/
   `queue` 的行＝**已知会互压的地方**；把本表清空不是"没有互压"，而是"门瞎了"（腿⑥拦这一手）。
3. **结构锁证明不了不互压**：本件＋门只能判"不共键/不共闸身份/不共计数器"。
   同 CPU、同 chromium 实例、同 worker 池、同请求预算都能让两族互相拖慢甚至拖死——
   那部分**只能记账（本表）不能宣称已执法**。任何把本门叙述成"共存已验证"的写法都是假绿。

## 语音族为什么把 ASR 也算进来
``capability_manifest`` 给 `media.asr.*` 打的是 `media-read` 不是 `native-audio`
（能力侧尚无票根，见该件 EVIDENCE 段）。但"听音频"在**资源归属**上就是语音侧——
把 ASR 划到族外，恰好会把本席现算抓到的那条真互压（视觉烧掉请求预算 ⇒ ASR 被
`expired()` 一票跳过，`chat.py:3347/3359`）落在册外。故本件按**资源面**分族、
不按标签面分族，并由腿③钉住"带 tts/vision 系标签者必在册"这一单向跟随。
"""

from __future__ import annotations

# 本件只声明数据：零 config 依赖、零网络、零 I/O，且不 import 任何包内模块
# （与 ``channel_capability_tags.py`` / ``board_taxonomy.py`` 同一哲学——
#  常量保持字面量、可 ``ast.literal_eval``，体检脚本不必为读一组常量把 NoneBot 拉起来）。

#: 族 → 该族按 mandate 标签面应当覆盖的 CapabilityTag 字面量。
#: 这里是"门用来反查名册有没有漏收新成员"的词表，**不是**第二份标签真身
#: （标签真身＝``capability_manifest.CapabilityTag``）。
FAMILY_TAGS: dict[str, tuple[str, ...]] = {
    "visual": ("vision", "native-vision", "native-animation", "native-video", "image"),
    "audio": ("tts", "native-audio"),
}

#: 族 → 成员 capability_id（按**资源面**归类，见模块 docstring 第三条）。
#: 一个 id 只准属于一族（跨族成员＝同一份执行体既算视觉又算语音，正交性当场不成立）。
FAMILY_MEMBERS: dict[str, tuple[str, ...]] = {
    "visual": (
        "media.vision.image",
        "media.vision.ocr",
        "media.vision.anime_ip",
        "media.video.recognize",
        "creation.image.generate",
    ),
    "audio": (
        "bot.tts",
        "media.tts.autodub",
        # S91 自动配音第二条腿（中央第三形，tags=tts）：同族登记，否则正交门判它"族外"。
        "media.tts.autodub_transform",
        "creation.tts.synthesize",
        "media.asr.speech",
        "media.asr.audio_file",
    ),
}

#: 族 → 该族**专属**的 Config 字段名（开关/限额/超时/落点）。
#: 判据＝两族清单不相交；每枚键必须能在 ``config.py`` 现算在场（反虚构腿）。
#: 清单来源＝`capability_protocols._media_descriptors()` 各行的 config_keys
#: ＋ `config.py` 的 `bot_vision_* / bot_video_* / bot_asr_* / bot_tts_*` 段，逐枚抄录不臆造。
FAMILY_CONFIG_KEYS: dict[str, tuple[str, ...]] = {
    "visual": (
        "bot_request_budget_seconds",
        "bot_vision_enabled",
        "bot_vision_mode",
        "bot_vision_model_registry",
        "bot_vision_timeout_seconds",
        "bot_vision_max_images",
        "bot_vision_max_chars",
        "bot_vision_video_frames",
        "bot_vision_reply_probability",
        "bot_saucenao_api_key",
        "bot_video_understanding_enabled",
        "bot_video_max_frames",
        "bot_video_brief_deadline_seconds",
        "bot_video_brief_max_chars",
        "bot_video_asr_max_seconds",
        "bot_video_skip_asr_with_subtitle",
        "bot_video_native_input",
        "bot_video_native_max_mb",
        "bot_video_progress_ack_enabled",
        "bot_video_progress_ack_cooldown_seconds",
        "bot_video_fuzzy_followup",
        "bot_video_deep_enabled",
        "bot_video_deep_cooldown_seconds",
        "bot_video_deep_frames",
        "bot_video_deep_asr_max_seconds",
        "bot_video_deep_deadline_seconds",
        # ⚠ `bot_media_registry_path` / `_ttl_days` **不在任何一族的专属清单里**：
        # 媒体资产库是跨族共用的一枚 SQLite（media_registry.py:410 唯一读点），
        # 把它算作某一族专属＝虚假声明。它在下方 SHARED_RESOURCES 里作为共享存储登记。
    ),
    "audio": (
        "bot_request_budget_seconds",
        "bot_tts_enabled",
        "bot_tts_api_url",
        "bot_tts_gptsovits_dir",
        "bot_tts_ref_audios",
        "bot_tts_trigger_words",
        "bot_tts_output_dir",
        "bot_tts_preset",
        "bot_tts_max_chars",
        "bot_tts_hard_max_chars",
        "bot_tts_max_audio_bytes",
        "bot_tts_timeout_seconds",
        "bot_tts_speed_factor",
        "bot_tts_temperature",
        "bot_tts_top_k",
        "bot_tts_top_p",
        "bot_tts_text_lang",
        "bot_tts_text_split_method",
        "bot_tts_cache_enabled",
        "bot_tts_cache_max_bytes",
        "bot_tts_cache_max_age_days",
        "bot_tts_auto_reply_enabled",
        "bot_tts_auto_reply_scope",
        "bot_tts_auto_reply_max_chars",
        "bot_tts_auto_reply_split_max_chars",
        "bot_tts_auto_reply_probability",
        "bot_tts_auto_reply_always",
        "bot_tts_voice_hook_enabled",
        "bot_asr_enabled",
        "bot_asr_model_registry",
        "bot_asr_timeout_seconds",
        "bot_asr_max_chars",
    ),
}

#: 请求级预算相位（`DeadlineBudget.record_phase("…")` 的第一枚字面量）→ 族归属。
#: 未列出的相位（如 ``llm``）＝不属于两族任何一族，**不参与**"同一条预算串了两族"的判定。
#: 新增一枚相位却不登记归属 ⇒ 门的扫描面计数会涨、归属覆盖率会掉（腿⑤的失明哨兵）。
BUDGET_PHASE_FAMILIES: dict[str, str] = {
    "vision": "visual",
    "video_brief": "visual",
    "vision_video": "visual",
    "asr": "audio",
}

#: 效应词表（本件唯一合法取值；门腿⑥按此校验，未知值 fail-closed 红）。
#:  - ``separate`` 各用各的 ⇒ 结构上不可能互压（本席的判据能证的那一半）
#:  - ``queue``    排队     ⇒ 变慢，不改判定结果
#:  - ``preempt``  抢占     ⇒ 后来者挤掉在途
#:  - ``veto``     直接否决 ⇒ 另一族拿不到结果（最狠，本席现算抓到两枚）
#:  - ``external`` 代码面之外（同机进程/算力竞争，本门不判、只点名）
EFFECTS: tuple[str, ...] = ("separate", "queue", "preempt", "veto", "external")

#: 共享资源账：一行＝一枚可能把两族绑在一起的资源。
#: 字段：resource（人读名）/ kind（budget|pool|quota|counter|path|engine）/
#:       cap_key（上限真身的 Config 字段名，无则空串）/
#:       evidence（文件:行号，读码坐标）/ consumers（用它的族或 ``all``）/
#:       effect（A 开对 B 的效应，取 EFFECTS）/ note（诚实边界）。
SHARED_RESOURCES: tuple[dict[str, str | tuple[str, ...]], ...] = (
    {
        "resource": "chat 请求级 DeadlineBudget（识图→视频→转写→LLM 同一条预算）",
        "kind": "budget",
        "cap_key": "bot_request_budget_seconds",
        "evidence": (
            "domains/chat_reply/capabilities/chat.py:build_chat_capability 内 "
            "record_phase(\"vision\"|\"video_brief\"|\"vision_video\"|\"asr\") 同一枚 request_budget；"
            "预留真身＝同文件 `_LLM_HANDOVER_RESERVE_SECONDS`/`_asr_reserve_seconds`/"
            "`_asr_deadline_seconds`/`_vision_stage_timeout_seconds`/`_video_deadline_seconds`"
        ),
        "consumers": ("visual", "audio"),
        "effect": "veto",
        "note": (
            "S134·A（裁定 3 项 A，2026-09-24）已落**最小预算预留**：视频/旧抽帧两支"
            "视觉相位的超时都按「剩余 − LLM 交接保留 − 语音预留」夹住，语音段自身也"
            "按「剩余 − LLM 交接保留」夹住；且「预算低到给不满预留」一律记 "
            "`asr_budget_starved` 审计标签（旧形态＝`expired()` 整段跳过且无痕）。"
            "**残余仍是否决级，故本行 effect 不降**：①图片转译 `describe_images` 自身"
            "没有超时形参（vision_describe.py 签名），视觉洪峰里图片那一段仍可越预留；"
            "②保留位只保证「不被饿到零」，不保证跑完。裁定项 S85-R1 的结构性 B 案"
            "（每族子预算）仍未做。"
        ),
    },
    {
        "resource": "管线 worker 池与在途闸（通用层共用 + 每族独立保留层）",
        "kind": "pool",
        "cap_key": "bot_pipeline_max_workers",
        "evidence": (
            "domains/chat_reply/runtime/pipeline.py:_BoundedSubmissionGate（两层计数器）"
            ":inflight_scope_of/_reserved_scopes（族籍取本册 FAMILY_MEMBERS，不复制第二份）"
            ":offload_capability（取/还同 scope）:_pipeline_busy_result（超限=静默否决）"
        ),
        "consumers": ("visual", "audio", "all"),
        "effect": "veto",
        "note": (
            "S134·B（裁定 3 项 B，2026-09-24）：在途闸不再「全族共一枚计数器」——"
            "通用层 2N 语义不变，另给**每一在册族一格各自的保留计数器**，别的族拿不走"
            "（前值实测 permits=16 时视觉取满后语音成功数 0，后值＝语音仍可取到保留层）。"
            "**残余仍是否决级，故本行 effect 不降**：①保留位只 N/2 格，超出部分仍与"
            "通用层共命运；②族外能力（含承载两族相位的 `bot.chat`）不进保留层；"
            "③被保留层放行的请求最终仍挤同一个 N worker 池（排队级压制不变）。"
        ),
    },
    {
        "resource": "事件循环默认线程池（asyncio.to_thread）",
        "kind": "pool",
        "cap_key": "",
        "evidence": (
            "__init__.py:4655（识图下放）"
            "domains/chat_reply/runtime/pipeline.py:1311（配音完成路径下放，最坏 3x60s）"
        ),
        "consumers": ("visual", "audio"),
        "effect": "queue",
        "note": "无上限真身在代码内（取 Python 默认 min(32, cpu+4)）⇒ 只排队不否决。裁定项 S85-R3。",
    },
    {
        "resource": "playwright 渲染并发池与单卡等待预算",
        "kind": "pool",
        "cap_key": "bot_render_max_concurrency",
        "evidence": (
            "domains/render/render_backends.py:451（BoundedSemaphore）"
            ":758/:787（共享后端单例）"
        ),
        "consumers": ("visual",),
        "effect": "separate",
        "note": (
            "对语音族 separate 的依据＝tts 侧零 render_card 调用（现算）⇒ 语音不进此池；"
            "出图能力彼此仍是 queue→超时降纯文本。"
        ),
    },
    {
        "resource": "LLM 故障转移总预算",
        "kind": "budget",
        "cap_key": "bot_chat_failover_max_seconds",
        "evidence": "domains/chat_reply/llm_engine/model_router.py:2719（唯一读点）",
        "consumers": ("none",),
        "effect": "separate",
        "note": "VLM/ASR 各用自己的 *_timeout_seconds、不经此预算 ⇒ 简报点名的这处嫌疑不成立。",
    },
    {
        "resource": "出站闸每目标投递配额",
        "kind": "quota",
        "cap_key": "bot_outbound_gate_max_per_target_per_minute",
        "evidence": "config.py:310-311（键）＋domains/transport/sender/outbound_gate.py（执法）",
        "consumers": ("audio",),
        "effect": "separate",
        "note": (
            "视觉族不主动投递、自动配音走层 1 hook 不经此口 ⇒ 对 A↔B separate；"
            "该闸本身缺省关（在册未执法，见 AGENTS #49），本行不宣称其在执法。"
        ),
    },
    {
        "resource": "入站限流计数器（群节奏/间隔/分钟/令牌四 scope）",
        "kind": "counter",
        "cap_key": "bot_rate_limit_group_vision_min_interval_seconds",
        "evidence": (
            "domains/chat_reply/policy/rate_limit.py:860/:871/:910/:933"
            "（四 scope 全走 _bucket_key(capability_id, scope, group)）"
        ),
        "consumers": ("visual", "audio"),
        "effect": "separate",
        "note": (
            "按能力分桶 ⇒ 视觉涨不动语音的桶，且视觉另有独立 120s 间隔。"
            "这一枚是**判据可执法**的：桶键一旦丢掉 capability_id 就变成共用计数器（腿④拦）。"
        ),
    },
    {
        "resource": "媒体资产库（跨族共用的一枚 SQLite）",
        "kind": "store",
        "cap_key": "bot_media_registry_path",
        "evidence": (
            "domains/media/registry/media_registry.py:410（唯一路径读点）"
            "＋__init__.py:4974（TTL 装配）"
        ),
        "consumers": ("visual", "audio"),
        "effect": "queue",
        "note": (
            "两族都往同一份库写资产行 ⇒ 写序列化（queue），无否决通道；"
            "正因它是跨族件，本席**不**把它列进任何一族的专属键清单（见 FAMILY_CONFIG_KEYS 注）。"
        ),
    },
    {
        "resource": "引擎侧算力（GPT-SoVITS 单进程 9880 / ffmpeg 子进程 / CPU）",
        "kind": "engine",
        "cap_key": "",
        "evidence": "domains/media/capabilities/tts.py（HTTP 9880）＋抽帧/转码 ffmpeg 调用面",
        "consumers": ("visual", "audio"),
        "effect": "external",
        "note": "代码内零共享闸（现算：vision 与 media 两域无 Semaphore/acquire），竞争在进程外，本门不判。",
    },
)


def family_of(capability_id: str) -> str:
    """某个 capability_id 在本册里归哪一族（跨族或不在册 ⇒ 空串，由门判红）。"""
    hits = tuple(name for name, members in FAMILY_MEMBERS.items() if capability_id in members)
    return hits[0] if len(hits) == 1 else ""


def family_conflicts(config_keys: dict[str, tuple[str, ...]] | None = None) -> list[str]:
    """纯谓词：返回「同一枚 config 键被两族同时声明」的冲突描述（缺省读本册数据）。

    形参只是**注毒注入缝**（活账永远走缺省）：让"两族共用一枚预算键"这一手
    能被离线证明判据有牙，而不是靠注释承诺。
    """
    rows = FAMILY_CONFIG_KEYS if config_keys is None else config_keys
    owner: dict[str, list[str]] = {}
    for family, keys in rows.items():
        for key in keys:
            owner.setdefault(str(key), []).append(str(family))
    return sorted(
        f"{key} ← {'/'.join(sorted(set(fams)))}" for key, fams in owner.items() if len(set(fams)) > 1
    )


def member_conflicts() -> list[str]:
    """纯谓词：一个 capability_id 被塞进两族 ⇒ 成员归属冲突（正交性的定义级前提）。"""
    seen: dict[str, list[str]] = {}
    for family, members in FAMILY_MEMBERS.items():
        for cid in members:
            seen.setdefault(cid, []).append(family)
    return sorted(f"{cid} ← {'/'.join(sorted(v))}" for cid, v in seen.items() if len(v) > 1)
