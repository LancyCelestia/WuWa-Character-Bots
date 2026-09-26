"""评审需求回归：语音消息 + 多媒体（图片/GIF/视频）入站识别。

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_voice_media_routing.py -q

覆盖的实测缺口（评审报告「需求 3/4」）：
  - **纯语音不可达**：plain_text 为空 → base_router 判 IGNORE →
    `_is_plain_chat_event` 因 visual_types 不含 record 而 False → chat handler
    根本不触发 → ASR（链路本身完好）永远跑不到。用户发语音 = 静默无响应。
  - **Telegram 语音不识别**：TG 段是 `voice`/`audio`，取源只认 `record`。
  - **Telegram 动图/贴纸不识别**：不在 `_IMAGE_SEGMENT_TYPES` 内。
  - **Telegram 圆形视频（`video_note`）读不到画面**：2026-09-23 席位 S7 实跑坐实——
    它曾与动图/贴纸一起被归进图片族，但落盘容器恒为 mp4，PIL 打不开 ⇒
    图片支路与视频支路**双双取空、零日志**。现归视频族（见下方端到端活性锁）。
"""
from __future__ import annotations

from plugins.bot_unified_runtime import (
    AUDIO_SEGMENT_TYPES,
    contains_audio_message_segments,
    contains_visual_message_segments,
)
from plugins.bot_unified_runtime.domains.media.ingest.transcribe import (
    extract_audio_source,
)
from plugins.bot_unified_runtime.domains.media.ingest.video_understanding import (
    build_native_video_part,
)
from plugins.bot_unified_runtime.domains.media.ingest.vision_describe import (
    _IMAGE_SEGMENT_TYPES,
    _VIDEO_SEGMENT_TYPES,
    IMAGE_GROUPS,
    extract_image_urls,
    extract_video_source,
    requires_native_animation,
    split_animated_segments,
)
from plugins.bot_unified_runtime.message_context import normalize_message_segments

# ------------------------------------------------------------------ 门禁放行


def test_pure_voice_segment_is_recognized_as_audio() -> None:
    """纯语音必须被识别为音频段，否则门禁会把它当空消息丢掉。"""
    segments = [{"type": "record", "data": {"file": "a.silk", "url": "http://x/a.silk"}}]
    assert contains_audio_message_segments(segments) is True
    # 语音不是"视觉"段——两者语义必须分开，占位文案才能各自命名。
    assert contains_visual_message_segments(segments) is False


def test_telegram_voice_and_audio_segments_recognized() -> None:
    for kind in ("voice", "audio"):
        segments = [{"type": kind, "data": {"file": "file_id_123"}}]
        assert contains_audio_message_segments(segments) is True, kind


def test_non_audio_segments_not_flagged() -> None:
    for segments in ([], None, [{"type": "text", "data": {"text": "hi"}}]):
        assert contains_audio_message_segments(segments) is False


def test_audio_segment_types_cover_both_adapters() -> None:
    assert {"record", "voice", "audio"} <= set(AUDIO_SEGMENT_TYPES)


def test_visual_segments_still_recognized() -> None:
    for kind in ("image", "face", "mface", "marketface", "sticker", "video"):
        assert contains_visual_message_segments([{"type": kind, "data": {}}]) is True, kind


def test_telegram_bare_visual_media_passes_the_admission_gate() -> None:
    """用户 2026-09-24 裁定「彻底修复」（M2）：Telegram 裸发视觉段必须进得了处理器。

    无文案、不 @bot 的 photo/animation/video_note 单段消息，plain_text 归一化后
    只剩占位标签，放行门 `visual_types` 不认这三个 TG 段类型名 ⇒ 路由判 IGNORE ⇒
    chat handler 根本不触发，本波为媒体理解铺的原生/转译腿对裸发形态全是死路
    （席位 S7/S21 实证，形态 A）。修法＝`__init__.py:669` 同行扩集合、零插行。

    段先过**真归一层**再喂门（禁手写被测前提——本波已两次栽在夹具手写段类型上），
    断的是公共谓词的输出、不是集合字面量。反向格钉住"退化成恒真"的假修。
    """
    for kind in ("photo", "animation", "video_note"):
        normalized = normalize_message_segments(
            [{"type": kind, "data": {"file": "tg_file_id_123"}}]
        )
        assert contains_visual_message_segments(normalized.segments) is True, kind

    # 反向格：纯文本与空消息绝不算视觉段（杀掉"恒真放行"这一捷径修法）。
    assert (
        contains_visual_message_segments(
            normalize_message_segments([{"type": "text", "data": {"text": "hi"}}]).segments
        )
        is False
    )
    assert contains_visual_message_segments([]) is False
    assert contains_visual_message_segments(None) is False


# --------------------------------------------------------------- 标签归一化


def test_media_labels_normalized_across_adapters() -> None:
    """OneBot 与 Telegram 的媒体段都要产出可读标签。"""
    cases = {
        "image": "[图片]",
        "photo": "[图片]",
        "sticker": "[表情包]",
        "animation": "[动图]",
        "video_note": "[圆形视频]",
        "record": "[语音]",
        "voice": "[语音]",
        "audio": "[音频]",
        "video": "[视频]",
    }
    for kind, expected in cases.items():
        normalized = normalize_message_segments([{"type": kind, "data": {}}])
        assert expected in normalized.plain_text, f"{kind} -> {normalized.plain_text!r}"


def test_voice_only_message_gets_placeholder_text() -> None:
    """纯语音消息经归一化后有文本（占位标签），不再是空串。"""
    normalized = normalize_message_segments(
        [{"type": "record", "data": {"file": "a.silk"}}]
    )
    assert normalized.plain_text.strip()
    assert "[语音]" in normalized.plain_text


# ------------------------------------------------------------------ 取源


def test_extract_audio_source_accepts_telegram_voice() -> None:
    """取源必须认 Telegram 的 voice 段（此前只认 record，直接穿透）。"""
    segments = [{"type": "voice", "data": {"file": "http://example.com/v.ogg"}}]
    assert extract_audio_source(segments) == "http://example.com/v.ogg"


def test_extract_audio_source_accepts_telegram_audio() -> None:
    segments = [{"type": "audio", "data": {"file": "http://example.com/a.mp3"}}]
    assert extract_audio_source(segments) == "http://example.com/a.mp3"


def test_extract_audio_source_accepts_onebot_record() -> None:
    segments = [{"type": "record", "data": {"url": "http://example.com/r.silk"}}]
    assert extract_audio_source(segments) == "http://example.com/r.silk"


def test_extract_audio_source_ignores_non_audio() -> None:
    assert extract_audio_source([{"type": "image", "data": {"url": "http://x/a.png"}}]) is None
    assert extract_audio_source(None) is None


# ------------------------------------------------------------ 视觉段类型集合


def test_image_segment_types_cover_telegram_visuals() -> None:
    assert {"photo", "sticker", "animation"} <= set(_IMAGE_SEGMENT_TYPES)
    # `video_note` 今天归视频族：mp4 容器 PIL 打不开，留在图片族＝两支路皆空。
    # 这条与下面那条活性锁配对，专拦"两边都留"的半修状态。
    assert "video_note" not in _IMAGE_SEGMENT_TYPES


def test_image_segment_types_keep_onebot_originals() -> None:
    assert {"image", "mface"} <= set(_IMAGE_SEGMENT_TYPES)


def test_video_segment_types_cover_telegram_movies() -> None:
    assert {"video", "video_note"} <= set(_VIDEO_SEGMENT_TYPES)


def test_telegram_video_note_reaches_the_video_branch_end_to_end(tmp_path) -> None:
    """**活性锁**：断公共取数口的输出，不断集合字面量。

    反面教材就在这个文件里：改之前 `test_image_segment_types_cover_telegram_visuals`
    与 `test_video_segment_types_unchanged` 两条**全绿**，而 `video_note` 的画面
    一条也读不到——把"存在性"当"活性"（台账 #46 那枚 `nmc:A1` 同型病）。
    所以这里三腿全走公共函数进出，夹具只提供一个磁盘上的真 mp4 头
    （随机字节会让 PIL/ffmpeg 以"文件损坏"为由失败，测到的是夹具不是代码）。

    注毒预期（逐发已实跑，见 HANDBOOK §41.5）：
      ① 从 `_VIDEO_SEGMENT_TYPES` 删回 `{"video"}` → ① 腿红（承重那行）
      ② 把 `video_note` 同时留在图片族 → ② 腿红（重复计）
      ③ 删 `_VIDEO_SUFFIX_MIME` 的 `.mp4` 行 → ③ 腿红（空搬家）
      ④ 把 `extract_video_source` 里的判定写死成 `!= "video"` → ① 腿红
    """
    clip = tmp_path / "note.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 64)
    segments = [{"type": "video_note", "data": {"file": str(clip)}}]

    # ① 视频支路的公共取数口必须拿到这台机器上的真路径。
    assert extract_video_source(segments) == str(clip)
    # ② 同一族不许既算图又算视频（否则开火门双计，图片族还白跑一次 PIL）。
    assert extract_image_urls(segments) == []
    # ③ 下游确实认这个容器——杀掉"只把字符串从一个集合搬到另一个集合"的空搬。
    part = build_native_video_part(str(clip), max_mb=20.0)
    assert part is not None
    assert part["type"] == "video_url"
    assert part["video_url"]["url"].startswith("data:video/mp4;base64,")


# -------------------------------------------------- 图片族分组 × 动图原生面
# 用户 2026-09-23 矩阵：纯图片任何渠道原生；动图与表情包只在声明了
# `native-animation` 的渠道原生，其余渠道必须转成文字再给模型。


def _real_gif_bytes() -> bytes:
    """四帧真动图。随机字节会令 PIL 以"文件损坏"为由失败，测到的是夹具不是代码。"""
    from io import BytesIO

    from PIL import Image, ImageDraw

    frames = []
    for digit in "1234":
        frame = Image.new("RGB", (120, 120), "white")
        ImageDraw.Draw(frame).text((60, 60), digit, fill=(200, 0, 0), anchor="mm")
        frames.append(frame)
    buffer = BytesIO()
    frames[0].save(
        buffer,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=300,
        loop=0,
    )
    return buffer.getvalue()


def _real_png_bytes() -> bytes:
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (80, 80), (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_image_groups_partition_the_family_exactly() -> None:
    """三组并集必须恰好等于图片族，且两两不相交。

    承重理由：聊天侧现在**只按组取数**，谁都不再读 `_IMAGE_SEGMENT_TYPES`。
    往族里加一个段类型却忘了归组 ⇒ 该段在 LLM 面前整个消失（零日志零告警），
    而族成员断言照样绿；两组相交 ⇒ 同一段既直传又转译，算两遍。
    """
    assert (
        IMAGE_GROUPS["photo"] | IMAGE_GROUPS["sticker"] | IMAGE_GROUPS["animation"]
    ) == _IMAGE_SEGMENT_TYPES
    names = sorted(IMAGE_GROUPS)
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            assert not (IMAGE_GROUPS[left] & IMAGE_GROUPS[right]), (left, right)


def test_animation_gif_goes_native_only_when_the_caller_asks(tmp_path) -> None:
    gif = tmp_path / "m.gif"
    gif.write_bytes(_real_gif_bytes())
    segments = [{"type": "animation", "data": {"file": str(gif)}}]

    flattened = extract_image_urls(segments)
    native = extract_image_urls(segments, keep_animation_raw=True)

    # 缺省=旧行为逐字节不变：PIL 拼成一条静态 JPEG。
    assert flattened and flattened[0].startswith("data:image/jpeg;base64,")
    # 声明原生后：gif 原字节直发，模型才看得见"它在动"。
    assert native and native[0].startswith("data:image/gif;base64,")
    assert flattened != native  # 杀掉"两条分支返回同一个值"的空跑


def test_group_filter_selects_families_independently(tmp_path) -> None:
    gif = tmp_path / "g.gif"
    gif.write_bytes(_real_gif_bytes())
    png = tmp_path / "p.png"
    png.write_bytes(_real_png_bytes())
    segments = [
        {"type": "photo", "data": {"file": str(png)}},
        {"type": "sticker", "data": {"file": str(gif)}},
        {"type": "video", "data": {"file": str(gif)}},
    ]

    photo_only = extract_image_urls(segments, groups=("photo",))
    meme_only = extract_image_urls(segments, groups=("sticker", "animation"))

    assert len(photo_only) == 1 and photo_only[0].startswith("data:image/png")
    assert len(meme_only) == 1 and meme_only[0].startswith("data:image/jpeg")
    # 视频段绝不从图片取数口漏出来（否则同一段既抽帧又当图，两条转译各跑一次）。
    assert all("video" not in url.split(";")[0] for url in meme_only + photo_only)


def test_plain_photo_is_never_reinterpreted_by_the_animation_flag(tmp_path) -> None:
    png = tmp_path / "p.png"
    png.write_bytes(_real_png_bytes())
    segments = [{"type": "photo", "data": {"file": str(png)}}]

    assert extract_image_urls(segments) == extract_image_urls(
        segments, keep_animation_raw=True
    )


def test_qq_sticker_segments_survive_real_normalization(tmp_path) -> None:
    """**走真归一层**，不手写段类型。

    QQ 侧 `face`/`mface`/`marketface` 在 `message_context.py:53-56` 就被改写成
    `{"type":"emoji"}`，而 `raw_segments` 存的是**归一后**的段——所以分组表里只写
    `mface` 时，生产发来的表情包在聊天侧是一列空的。旧测试直接手写 `mface` 段
    反而把它锁成绿（本仓在册的"测夹具不测代码"同型病，席位 S26 实跑揭穿）。
    """
    gif = tmp_path / "meme.gif"
    gif.write_bytes(_real_gif_bytes())

    for raw_type in ("face", "mface", "marketface", "emoji"):
        normalized = normalize_message_segments(
            [{"type": raw_type, "data": {"file": str(gif)}}]
        )
        assert [s["type"] for s in normalized.segments] == ["emoji"], raw_type
        picked = extract_image_urls(normalized.segments, groups=("sticker", "animation"))
        assert len(picked) == 1, f"归一成 emoji 后 {raw_type} 段位被丢弃"

    # 反向格：纯文本表情（无文件）不该被硬当成图片源。
    text_only = normalize_message_segments(
        [{"type": "face", "data": {"text": "[微笑]"}}]
    )
    assert (
        extract_image_urls(text_only.segments, groups=("sticker", "animation")) == []
    )


def test_animation_predicate_splits_by_container_not_by_segment_type(tmp_path) -> None:
    """用户 2026-09-23 晚裁定：非声明渠道上 **gif 动图转译、静图仍原生**。

    判据必须是**容器**而不是段类型——同一个 `sticker` 段可能是 png 也可能是 gif，
    一刀切会把静图贴纸一起降成转译（她明确不要这个）。
    """
    gif = tmp_path / "meme.gif"
    gif.write_bytes(_real_gif_bytes())
    png = tmp_path / "sticker.png"
    png.write_bytes(_real_png_bytes())
    segments = [
        {"type": "sticker", "data": {"file": str(gif)}},
        {"type": "sticker", "data": {"file": str(png)}},
        {"type": "animation", "data": {"file": str(gif)}},
        {"type": "image", "data": {"file": str(png)}},
        {"type": "photo", "data": {"url": "https://example.test/loop.gif"}},
        {"type": "photo", "data": {"url": "https://example.test/pic.png?x=1"}},
    ]

    animated, static = split_animated_segments(segments)
    # 本机与 http 两种引用形态都要按容器判；带 query 的 URL 不能被参数骗成非动画。
    assert len(animated) == 3, [s["data"] for s in animated]
    assert len(static) == 3, [s["data"] for s in static]
    assert all(requires_native_animation(s["data"].get("file") or s["data"].get("url")) for s in animated)
    assert not any(requires_native_animation(s["data"].get("file") or s["data"].get("url")) for s in static)

    # 静图堆取数后仍是静图形态（本机件为 data:image/png|jpeg|webp，http 件原样透传）；
    # 动画堆则只有显式要原生时才以 gif 原字节出现，静态化后绝不再顶著 gif 名。
    static_forms = {u.split(";")[0] for u in extract_image_urls(static)}
    assert static_forms <= {
        "data:image/png",
        "data:image/jpeg",
        "data:image/webp",
        "https://example.test/pic.png?x=1",
    }, static_forms
    native_forms = [str(u) for u in extract_image_urls(animated, keep_animation_raw=True)]
    assert all(
        u.startswith(("data:image/gif", "http")) for u in native_forms
    ), native_forms
    # 取数口按引用去重（sticker 与 animation 同指一个文件时只发一份），
    # 所以条数对齐"去重后的引用数"，不是段数。
    unique_animated_refs = {
        str(s["data"].get("file") or s["data"].get("url")) for s in animated
    }
    assert len(native_forms) == len(unique_animated_refs)
    # 本机 gif 静态化后不再顶著 gif 名（http 件原样透传，形态由对端决定，不在这里改写）
    flat_forms = [str(u) for u in extract_image_urls(animated)]
    assert all(not u.startswith("data:image/gif") for u in flat_forms), flat_forms

    # 反向锁：分堆必须是原段的全覆盖且不重不漏（漏一堆=某型媒体整个消失）。
    assert len(animated) + len(static) == len(segments)


def test_unknown_group_name_selects_nothing_not_everything(tmp_path) -> None:
    """组名打错绝不能退化成"全取"。

    "只发照片"退化成"表情包也发出去"是放宽出站面，方向与本次裁定的收窄相反，
    且这种退化在调用点上看不出来——所以在这里钉死。
    """
    gif = tmp_path / "g.gif"
    gif.write_bytes(_real_gif_bytes())
    segments = [{"type": "animation", "data": {"file": str(gif)}}]

    assert extract_image_urls(segments, groups=("phooto",)) == []
    assert extract_image_urls(segments, groups=()) == []
    assert extract_image_urls(segments) != []  # 上一条不是靠"整个函数哑了"通过的
