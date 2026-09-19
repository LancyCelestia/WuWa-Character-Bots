"""守岸人语音合成能力（bot.tts）：文本 → 守岸人音色的语音消息。

对接本机 GPT-SoVITS v2ProPlus 的 ``api_v2.py`` HTTP 接口（默认 9880）。

设计：

- **独立能力，零侵入既有链路**：本模块只读配置、只调 HTTP、只把 wav 落到
  运行时目录；出站复用 renderer 既有的 audio 部件通道
  （``CapabilityResult.audio`` → ``{"type":"record"}`` → ``sender/onebot``），
  不改 chat / pipeline / renderer / sender 任何一行。
- **参考音频**：``BOT_TTS_REF_AUDIOS`` 每项形如 ``路径|参考文本|语种``，
  多项时随机轮换，贴合不同语气；路径可为绝对路径，也可相对
  ``BOT_TTS_GPTSOVITS_DIR``（GPT-SoVITS 程序目录）。
  参考音频硬性要求 3~10 秒干声，超出会被服务端直接拒绝。
- **缓存**：文本 + 引擎地址 + 参考音频（含**内容指纹**）+ 预设身份 → sha256
  命名，命中直接复用已有 wav（``BOT_TTS_CACHE_ENABLED`` 默认开），同一句话
  不重复合成；换引擎地址 / 原地重录参考音频 / 换预设后旧键自动失配（M-11/G-2）。
- **契约层（Wave G G-2）**：合成参数缺省源=中央预设表
  ``domains/media/tts_presets.py``（``BOT_TTS_*`` 数值键保留为管理员覆盖；
  M-43 第二缺省族已删）；``seed`` 不再硬编码 -1，由缓存键派生确定性值
  （M-72/U-25，同句恒同音色）；引擎「200+恰 1s 静音」伪装成功被静音指纹闸
  拒绝（M-07）；文本/产物双硬顶（G2-R3：2000 字 / 8 MiB，超顶拒绝留痕不拆条）；
  产物目录顺接中央磁盘配额（U-04，缺省关）。
- **fail-open**：服务未启动 / 超时 / 非 200 → 返回守岸人口吻的降级文案，
  绝不抛异常、绝不阻断出站管线（与 randpic 同哲学）。但 **fail-open ≠ 发出去**：
  引擎产物先过结构体检（``_inspect_wav_bytes``：RIFF/WAVE 魔数 + 头可解析 + 帧数>0
  + 静音指纹），不可播字节**绝不落盘、绝不入缓存、绝不再交给 QQ**——2026-09-19 起
  QQ 端换件为 SnowLuma，坏 record 段是 fatal（整条消息一字不发），不再是旧实现
  「丢段留文字」。每条运营性失败另挂 ``OperationalIssue``（``_failure_issue``）走中央告警链。
- **对话自动配音**（可选）：``BOT_TTS_AUTO_REPLY_ENABLED`` 开启后，
  ``maybe_attach_voice()`` 把人格回复正文一并合成为语音随消息发出，
  由 ``__init__`` 的 chat 能力包装层调用。是否真的配音由
  ``should_voice_reply()`` 统一裁决：总开关 / 自动配音开关 / 未带音频 /
  出自 ``bot.chat`` / 会话范围（``BOT_TTS_AUTO_REPLY_SCOPE``）/ 概率门
  （``BOT_TTS_AUTO_REPLY_PROBABILITY``，默认 5%，确定性哈希实现，
  同一条消息结果恒定可复现）。
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import random
import re
import threading
import time
import wave
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    IncomingMessage,
    OperationalIssue,
    SendPolicy,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.cache_policy import (
    enforce_quota,
)

# 合成前的内容门与打码：复用中央单一事实源，**绝不在本域抄一份**。
# 抄一份就等于再造一条「文字面拦、语音面放」的红线漂移面（审计 M-02 根因）。
# 分层注记：media → chat_reply/render 属跨域直连，正解是中央 hook（修复波 S13/S14
# 待施工）；在 hook 落地前，直连中央真身比各域自带副本更安全，故如此接线。
from plugins.bot_unified_runtime.domains.chat_reply.runtime.content_route import (
    explicit_allowed_for_session,
)
from plugins.bot_unified_runtime.domains.chat_reply.security.content_safety import (
    assess_public_content,
)
from plugins.bot_unified_runtime.domains.media.tts_presets import (
    DEFAULT_PRESET_ID,
    HARD_MAX_CHARS_FALLBACK,
    IDENTITY_VERSION,
    MAX_AUDIO_BYTES_FALLBACK,
    PRESET_REGISTRY,
    SEED_RULE_VERSION,
    TtsPreset,
)
from plugins.bot_unified_runtime.domains.render.plain_text import redact_local_secrets

logger = logging.getLogger(__name__)

# 触发词（T-Spec 口径）：中文 + 英文 + 拼音全拼/缩写。
# 边界判定沿用 randpic 的保守哲学——整句等于触发词，或触发词后紧跟
# 标点/空白，避免「说话」「念书」「语音消息」这类包含关系词误触发。
# 「语音合成」与 help 主题别名同源：帮助里列出的词，路由面必须真能命中
# （tests/test_trigger_bidirectional_gate.py 的词级双向门锁定这件事）。
DEFAULT_TRIGGER_WORDS: tuple[str, ...] = (
    "语音合成", "朗读", "语音", "念", "说",
    "tts", "say", "shuo", "yuyin", "nian", "langdu",
)
# 触发词与正文之间的分隔字符（取正文时剥掉）。
# ⚠️ 这里**只能放真分隔符**（标点与空白），一个词字符都不能进：曾经收录过
# 「了/的/呢/吗/呀/啊/哈」，于是「说了再见」「说的对」「语音哈喽」这类日常聊天
# 被整句吞进 bot.tts（priority 41 + block=True ⇒ 消息不再进人格对话），并把
# 「再见」「对」「喽」这种残片念出去。实测 312 句日常中文劫持率 68.1%。
# 回归锁见 tests/test_tts_hijack_guard.py（含"边界集合不得出现汉字"的棘轮断言）。
_TEXT_BOUNDARY_CHARS = "，,。！？!?：:、 　\t～~"

# 参考音频时长合规区间（3~10 秒）由服务端硬卡（TTS.py 的 _set_prompt_semantic），
# 本地不做重复预检：ChatBot 运行环境没有 soundfile/mutagen，读不了时长；
# 越界时服务端会在错误体 Exception 里给出可读原因，经 _request_tts 透传到
# _degrade 的「参考音频」分支，用户侧提示已经足够。
# M-43 注记：合成参数的第二缺省常量族（max_chars/speed/temperature/top_k/
# top_p/text_lang/split_method 七项）已整体删除——缺省唯一来源=中央预设表
# （domains/media/tts_presets.py），config 缺省值与其相等（现状收编）。
# 键缺失（鸭子配置）回预设表，不再有第二份代码内真值。
# 单请求超时的函数级缺省保留（库函数工效；生产路径恒由 config 传入）。
_DEFAULT_TIMEOUT_SECONDS = 60.0
# 静音指纹闸域值（M-07，引擎陷阱实测值=T53 §3 verified：16000Hz + 恰 1s +
# 全零 int16，≈32044 字节）。域值出处锁定 T53，禁自造。
_SILENCE_RATE = 16000
_SILENCE_MIN_SECONDS = 0.9
_SILENCE_MAX_SECONDS = 1.1
_SILENCE_PEAK_AMPLITUDE = 2

# 合成结果缓存（进程内 LRU 索引）：key → (落盘路径, 写入时刻)。
# 键数封顶，避免长跑进程按文本无界增长（对齐 runtime/reactions.py 惯例）。
_CACHE_LRU_CAP = 512
_CACHE: OrderedDict[str, tuple[Path, float]] = OrderedDict()

# 参考音频内容指纹缓存（M-11）：路径 → ((size, mtime), sha256 前 16 位)。
# 首次读取做全文件 sha256，之后只 stat 比 (size, mtime)：一致即沿用指纹，
# 避免每次合成全文件哈希；stat 变了（真实现场原地换文件必然更新 mtime）才重算。
# **已知边界**：内容变而 size+mtime 都不变（如 touch 回写旧时间戳）检测不到，
# 按设计接受——规格锁在 tests/test_tts_cache_identity.py。
# 并发口径：GIL 下 dict 单键读写原子；竞态最坏结果是两个线程对同一新 stat
# 重复算一次哈希（幂等同值），故不加锁。
_REF_FINGERPRINTS: dict[str, tuple[tuple[int, float], str]] = {}

# 服务健康退避闸（M-09 接线，U-20 裁定=接线不删净）：真失败（不可达/被拒/
# 空音频/httpx 缺失）进入冷却窗，窗内后续合成**不发 HTTP** 直接快速失败
# （原因以「服务不可达」开头 → 挂 ``tts_service_unreachable`` 可重试 issue），
# 窗满自动放行（非永久拉黑），真成功清零；快速失败不刷新窗口。
# 阈值=模块常量，不加新 config 键。
# 线程安全：能力跑在 offload 线程池，「失败时刻+原因」必须成对读写——GIL 只
# 保证单条赋值原子，保证不了配对一致，故模块级锁包住全部状态读写；临界区只有
# 内存操作，HTTP 绝不持锁（否则全部合成串行化）。已知取舍：「先查闸、后打
# 请求」不是原子语义，窗沿上并发的前几个请求都可能真打引擎——本闸是成本
# 节流不是硬信号量，为此把锁横跨 HTTP 不可接受。
_HEALTH_BACKOFF_SECONDS = 30.0
_last_failure_at: float = 0.0
_last_failure_reason: str = ""
_HEALTH_LOCK = threading.Lock()

# 朗读前清洗用正则：代码围栏 / 行内代码 / markdown 强调符 / 链接 / 颜文字括号。
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_URL_RE = re.compile(r"https?://\S+")
_MARKDOWN_MARKS_RE = re.compile(r"[*_#>~|]+")
_LIST_PREFIX_RE = re.compile(r"^\s*(?:[-+•]|\d+[.)])\s*", re.MULTILINE)
# 中央打码占位符（`plain_text._SECRET_VALUE_PLACEHOLDER`="<已隐藏>" 与
# `_LOCAL_PATH_PLACEHOLDER`="<本机路径已隐藏>"）的残缺形态：清洗会吃掉它们的
# 尖括号，朗读前替换成能念的词（T56 P2-②：两形都要接住）。
_REDACTION_PLACEHOLDER_RE = re.compile(r"<(?:本机路径已隐藏|已隐藏)[^<>]*>?")
_BLANK_LINES_RE = re.compile(r"\n{2,}")
_SPACES_RE = re.compile(r"[ \t]{2,}")
_SENTENCE_END = "。！？…!?；;"


@dataclass(frozen=True)
class RefAudio:
    """一条参考音频及其逐字文本（prompt_text）。

    ``text`` 为空表示走「无参考文本模式」——服务端自行从音频推断内容。
    ``lang`` 缺省 ``"zh"``（与 shorekeeper 预设 text_lang 同值，一致性由
    tests/test_tts_presets.py 锁；引擎空 prompt_lang 会 400，故不能缺省空串）。
    """

    path: str
    text: str = ""
    lang: str = "zh"


@dataclass(frozen=True)
class TtsParams:
    """一次合成的采样参数快照（参与缓存键计算）。"""

    text_lang: str
    speed_factor: float
    temperature: float
    top_k: int
    top_p: float
    text_split_method: str


def is_tts_command(
    text: str, trigger_words: list[str] | tuple[str, ...] | None = None
) -> bool:
    """触发词判定：整句等于触发词，或触发词后紧跟标点/空白边界。"""
    return bool(extract_tts_text(text, trigger_words))


def effective_trigger_words(
    trigger_words: list[str] | tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    """内置词表 ∪ 管理员追加词（去重；追加词在前，内置词在后）。

    旧实码是「传了非空表就整表替换」，而 catalog:809 / `.env.example` / help 条目
    三处文档承诺的是「与内置合并」：管理员加一个词即把内置 11 词全数静默关掉，
    `说 …` 当场落回人格对话（M-15）。合并语义收在这**唯一入口**，路由谓词与取文共用。
    """
    extra = tuple(str(word).strip() for word in (trigger_words or ()) if str(word).strip())
    merged: list[str] = []
    for word in (*extra, *DEFAULT_TRIGGER_WORDS):
        if word not in merged:
            merged.append(word)
    return tuple(merged)


def extract_tts_text(
    text: str, trigger_words: list[str] | tuple[str, ...] | None = None
) -> str:
    """取出触发句里要合成的正文；不命中触发词返回空串。

    最长触发词优先匹配，避免短词截断长词（``tts`` 之于 ``tts`` 前缀词）。
    英文词**大小写不敏感**（``SAY``/``TTS`` 是真命令，M-16），正文一律取原串切片，
    绝不返回折叠后的大小写。
    """
    stripped = (text or "").strip()
    if not stripped:
        return ""
    folded = stripped.casefold()
    # casefold 会改变长度的极端字符（如 ß→ss）会让「折叠串偏移」与「原串偏移」错位，
    # 那种输入退回逐字精确匹配——宁可不触发，也不切错正文或误触发。
    foldable = len(folded) == len(stripped)
    target = folded if foldable else stripped
    for word in sorted(set(effective_trigger_words(trigger_words)), key=len, reverse=True):
        needle = word.casefold() if foldable else word
        if target == needle or stripped == word:
            # 只发了触发词、没带正文：由调用方给引导文案。
            return ""
        if not target.startswith(needle):
            continue
        tail = stripped[len(needle):]
        if not tail or tail[0] not in _TEXT_BOUNDARY_CHARS:
            continue
        return tail.lstrip(_TEXT_BOUNDARY_CHARS).strip()
    return ""


def parse_ref_audios(
    items: list[str] | tuple[str, ...] | None, *, base_dir: str = ""
) -> list[RefAudio]:
    """解析 ``BOT_TTS_REF_AUDIOS``：每项 ``路径|参考文本|语种``（后两段可省）。"""
    parsed: list[RefAudio] = []
    for raw in items or []:
        item = str(raw).strip()
        if not item:
            continue
        parts = item.split("|")
        path = parts[0].strip()
        if not path:
            continue
        text = parts[1].strip() if len(parts) > 1 else ""
        lang = parts[2].strip() if len(parts) > 2 and parts[2].strip() else "zh"
        resolved = _resolve_ref_path(path, base_dir)
        parsed.append(RefAudio(path=str(resolved), text=text, lang=lang))
    return parsed


def _resolve_ref_path(path: str, base_dir: str) -> Path:
    """参考音频路径解析：绝对路径原样用；相对路径挂到 GPT-SoVITS 程序目录下。"""
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    if base_dir.strip():
        return Path(base_dir.strip()) / candidate
    return candidate


def pick_ref_audio(
    items: list[str] | tuple[str, ...] | None,
    *,
    base_dir: str = "",
    rng: random.Random | None = None,
) -> RefAudio | None:
    """随机挑一条**文件确实存在**的参考音频；一条都没有则返回 None。"""
    candidates = [
        ref for ref in parse_ref_audios(items, base_dir=base_dir) if Path(ref.path).is_file()
    ]
    if not candidates:
        return None
    return (rng or random).choice(candidates)


def clean_for_speech(text: str, *, max_chars: int = 0) -> str:
    """把回复正文清洗成适合朗读的纯文本。

    去掉代码块/行内代码/链接/markdown 标记与列表前缀——这些东西念出来只会
    变成一串噪音。``max_chars > 0`` 时在句子边界截断；**0（函数缺省）=不限**
    （不按字数截断）——纯函数不做隐藏截断，限制由调用方按配置显式传入
    （M-35：配置面 0=不限 语义统一，「不限≠无界」由中央硬顶另行把守）。
    """
    value = str(text or "")
    if not value.strip():
        return ""
    value = _FENCE_RE.sub(" ", value)
    value = _INLINE_CODE_RE.sub(" ", value)
    value = _URL_RE.sub(" ", value)
    value = _MARKDOWN_MARKS_RE.sub("", value)
    value = _LIST_PREFIX_RE.sub("", value)
    value = _BLANK_LINES_RE.sub("\n", value)
    value = _SPACES_RE.sub(" ", value)
    value = value.replace("\n", " ").strip()
    if max_chars > 0 and len(value) > max_chars:
        value = _truncate_at_sentence(value, max_chars)
    return value


def _truncate_at_sentence(text: str, limit: int) -> str:
    """在 limit 以内尽量切在句末标点处。"""
    window = text[:limit]
    for index in range(len(window) - 1, max(0, limit - 40), -1):
        if window[index] in _SENTENCE_END:
            return window[: index + 1]
    return window


def _ref_fingerprint(ref_path: str) -> str:
    """参考音频内容指纹（M-11）：stat 快路径 + 首次全文件 sha256。

    读不到的路径返回 ``"missing"``（确定性占位；不同路径另有 ``ref`` 段区分）。
    """
    path = Path(ref_path)
    try:
        stat = path.stat()
    except OSError:
        return "missing"
    stamp = (stat.st_size, stat.st_mtime)
    cached = _REF_FINGERPRINTS.get(ref_path)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except OSError:
        return "missing"
    _REF_FINGERPRINTS[ref_path] = (stamp, digest)
    return digest


def _cache_identity(
    text: str,
    ref: RefAudio,
    params: TtsParams,
    *,
    api_url: str,
    preset_id: str,
    identity_version: int = IDENTITY_VERSION,
) -> tuple[str, int]:
    """缓存键身份唯一算法 + 确定性 seed（G-2 契约，T54 规格 §5）。

    preimage = canonical_json({identity_version, engine, ref, preset, text})：

    - ``engine``：``api_url``（``rstrip('/')`` 归一，尾斜杠不算换引擎，T57 基线）；
    - ``ref``：路径 + **内容指纹**（``_ref_fingerprint``，T57 基线）+ 参考文本 + 语种；
    - ``preset``：预设 id + 生效参数快照（G-2 收编段——换预设=换键空间）；
    - ``identity_version``：键空间代号（tts_presets.IDENTITY_VERSION，换代自增，
      旧键整体变冷）。

    返回 ``(cache_key, seed)``：

    - ``seed = int(sha256(preimage)[:8], 16)``（U-25/G2-R3 裁定：产物=参数的纯函数，
      「同一句话不重复合成」承诺整链兑现；M-72 的 ``seed=-1`` 静默随机就此死亡）；
    - ``cache_key = sha256(preimage + seed 规则版本)[:20]``（保持 20 hex 文件名形态；
      规则版本入键，防跨派生规则键撞）。
    """
    payload = {
        "identity_version": identity_version,
        "engine": {"api_url": str(api_url or "").rstrip("/")},
        "ref": {
            "path": ref.path,
            "fp": _ref_fingerprint(ref.path),
            "text": ref.text,
            "lang": ref.lang,
        },
        "preset": {
            "preset_id": preset_id,
            "params": {
                "text_lang": params.text_lang,
                "speed_factor": params.speed_factor,
                "temperature": params.temperature,
                "top_k": params.top_k,
                "top_p": params.top_p,
                "text_split_method": params.text_split_method,
            },
        },
        "text": text,
    }
    preimage = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    seed = int(hashlib.sha256(preimage.encode("utf-8")).hexdigest()[:8], 16)
    cache_key = hashlib.sha256(
        (preimage + "|" + SEED_RULE_VERSION).encode("utf-8")
    ).hexdigest()[:20]
    return cache_key, seed


def derive_seed(
    text: str,
    ref: RefAudio,
    params: TtsParams,
    *,
    api_url: str,
    preset_id: str,
) -> int:
    """确定性 seed 的唯一派生口（audit_tags 与请求体共用同一函数，恒一致）。"""
    return _cache_identity(
        text, ref, params, api_url=api_url, preset_id=preset_id
    )[1]


def _cache_key(
    text: str,
    ref: RefAudio,
    params: TtsParams,
    *,
    api_url: str,
    preset_id: str,
    identity_version: int = IDENTITY_VERSION,
) -> str:
    """缓存键（键算法见 ``_cache_identity``；便捷口只返回键本身）。"""
    return _cache_identity(
        text, ref, params, api_url=api_url, preset_id=preset_id, identity_version=identity_version
    )[0]


def _lookup_cache(key: str) -> Path | None:
    cached = _CACHE.get(key)
    if cached is None:
        return None
    path, _at = cached
    if not path.is_file():
        _CACHE.pop(key, None)
        return None
    _CACHE.move_to_end(key)
    return path


def _store_cache(key: str, path: Path) -> None:
    _CACHE[key] = (path, time.monotonic())
    _CACHE.move_to_end(key)
    while len(_CACHE) > _CACHE_LRU_CAP:
        _CACHE.popitem(last=False)


def _record_failure(reason: str) -> None:
    """记一次真实失败（进入退避冷却窗）——M-09 退避状态的唯一写入口。"""
    global _last_failure_at, _last_failure_reason
    with _HEALTH_LOCK:
        _last_failure_at = time.monotonic()
        _last_failure_reason = reason


def _clear_failure() -> None:
    """真成功清零退避状态：下一轮失败从零起算（非累积性拉黑）。"""
    global _last_failure_at, _last_failure_reason
    with _HEALTH_LOCK:
        _last_failure_at = 0.0
        _last_failure_reason = ""


def _backoff_reason() -> str:
    """健康退避闸（M-09）：冷却窗内返回快速失败原因，窗满/无失败返回空串。

    原因固定以「服务不可达」开头——走 ``_FAILURE_KINDS`` 既有前缀映射，挂
    ``tts_service_unreachable``（可重试）；窗满即放行，绝不永久拉黑。
    """
    with _HEALTH_LOCK:
        if _last_failure_at <= 0.0:
            return ""
        elapsed = time.monotonic() - _last_failure_at
        if elapsed >= _HEALTH_BACKOFF_SECONDS:
            return ""
        remaining = _HEALTH_BACKOFF_SECONDS - elapsed
        last = _last_failure_reason or "上次合成失败"
    return f"服务不可达：退避冷却中（剩 {remaining:.0f} 秒）｜上次失败：{last}"


def _build_request_payload(
    text: str,
    ref: RefAudio,
    params: TtsParams,
    *,
    engine_params: dict[str, object],
    seed: int,
) -> dict[str, Any]:
    """组 api_v2 ``POST /tts`` 请求体（T53 §1 19 实发键）。

    - 采样六项来自 ``params``（config 覆盖 > 预设缺省，``_build_params``）；
    - 八个原硬编码项（M-76）全部收编自预设表 ``engine_params``，不再有代码内
      真值；``split_bucket`` 显式 False（引擎 speed≠1 时无条件忽略，死意图消除）；
    - ``seed`` 由缓存键派生（M-72/U-25）；``text_lang`` 出门前 casefold
      （POST 入口引擎用原值断言，"ZH" 必 400）。
    """
    return {
        "text": text,
        "text_lang": str(params.text_lang).strip().casefold(),
        "ref_audio_path": ref.path,
        "prompt_text": ref.text,
        "prompt_lang": ref.lang,
        "top_k": params.top_k,
        "top_p": params.top_p,
        "temperature": params.temperature,
        "text_split_method": params.text_split_method,
        "batch_size": engine_params["batch_size"],
        "batch_threshold": engine_params["batch_threshold"],
        "split_bucket": engine_params["split_bucket"],
        "speed_factor": params.speed_factor,
        "fragment_interval": engine_params["fragment_interval"],
        "seed": int(seed),
        "media_type": engine_params["media_type"],
        "streaming_mode": False,
        "parallel_infer": engine_params["parallel_infer"],
        "repetition_penalty": engine_params["repetition_penalty"],
    }


def _request_tts(
    *,
    api_url: str,
    text: str,
    ref: RefAudio,
    params: TtsParams,
    timeout_seconds: float,
    engine_params: dict[str, object],
    seed: int,
) -> bytes | None:
    """调用 api_v2.py 的 ``POST /tts``，返回 wav 字节；失败返回 None。

    异常一律吞掉并记账（fail-open）——调用方据此给降级文案。
    每条真实失败经 ``_record_failure`` 进入健康退避冷却窗（M-09）。
    """
    try:
        import httpx
    except Exception:  # noqa: BLE001 - 缺依赖按服务不可用处理。
        # 与其余失败同口径记账（M-46 指认的「httpx 分支不更新时刻」在此收口）。
        _record_failure("httpx 不可用")
        return None

    endpoint = f"{api_url.rstrip('/')}/tts"
    payload = _build_request_payload(text, ref, params, engine_params=engine_params, seed=seed)
    try:
        with httpx.Client(timeout=max(1.0, float(timeout_seconds))) as client:
            response = client.post(endpoint, json=payload)
    except Exception as exc:  # noqa: BLE001 - 连接/超时统一按失败降级。
        _record_failure(f"服务不可达：{type(exc).__name__}")
        logger.info("tts request failed: %s", exc)
        return None
    if response.status_code != 200:
        _last_failure_at = time.monotonic()
        # 错误体形如 {"message": "tts failed", "Exception": "<真原因>"}
        # （api_v2.py 的兜底包装）：真原因在 Exception 里，message 只是固定摘要，
        # 故必须先取 Exception，否则 3~10 秒越界这类可读原因会被吞成 "tts failed"，
        # 下游 _degrade 的「参考音频」分支永远命不中。
        try:
            error_body: Any = response.json()
        except Exception:  # noqa: BLE001 - 错误体非 JSON 时退回纯文本。
            error_body = None
        if isinstance(error_body, dict):
            detail = str(error_body.get("Exception") or error_body.get("message") or "")
        elif isinstance(error_body, str):
            detail = error_body[:200]
        else:
            detail = (response.text or "")[:200]
        _record_failure(f"服务返回 {response.status_code}：{detail[:160]}")
        logger.info("tts request rejected: %s %s", response.status_code, detail)
        return None
    if not response.content:
        _record_failure("服务返回空音频")
        return None
    _clear_failure()
    return response.content


def _inspect_wav_bytes(data: bytes) -> str:
    """结构体检 + 静音指纹闸：不可播返回原因短语，可播返回空串。

    只判**结构**（RIFF/WAVE 魔数 + 头可解析 + 帧数>0）与**静音陷阱**，
    **不判时长上限**：QQ 语音条的时长红线是未做真机判定的悬案（U-02），拿估
    出来的秒数硬拦会把正常长回复误杀——时长维度由 G2-R3 字节顶另行把守
    （wav/PCM 下字节顶≈时长顶），本闸不重复。

    静音指纹（M-07，域值=T53 §3 verified）：引擎推理期异常会先 yield
    ``16000Hz + 16000 个全零 int16``（恰 1s、≈32044 字节）再 raise，而非流式
    只消费一次 ⇒ 200+1 秒静音伪装成功。三条指纹同时命中才判静音（采样率
    ≠产物标称 32000 + 恰 1s 量级 + 全零/近全零），正常产物零误杀；命中即
    失败——不落盘、不入缓存、不出站。
    """
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return "非 RIFF/WAVE 字节"
    try:
        with wave.open(io.BytesIO(data)) as handle:
            frames = handle.getnframes()
            rate = handle.getframerate()
    except Exception:  # noqa: BLE001 - 头读不出来即不可播，宁不发。
        return "wav 头不可解析"
    if frames <= 0 or rate <= 0:
        return "零帧 wav"
    if (
        rate == _SILENCE_RATE
        and _SILENCE_MIN_SECONDS <= frames / rate <= _SILENCE_MAX_SECONDS
        and _is_near_silent(data, frames)
    ):
        return f"{frames / rate:.1f} 秒静音（引擎推理异常伪装成功）"
    return ""


def _is_near_silent(data: bytes, frames: int) -> bool:
    """近全零判据：样本峰值 ≤ ``_SILENCE_PEAK_AMPLITUDE``（int16）。"""
    with wave.open(io.BytesIO(data)) as handle:
        raw = handle.readframes(frames)
    peak = 0
    for offset in range(0, len(raw) - 1, 2):
        sample = int.from_bytes(raw[offset : offset + 2], "little", signed=True)
        magnitude = -sample if sample < 0 else sample
        if magnitude > peak:
            peak = magnitude
            if peak > _SILENCE_PEAK_AMPLITUDE:
                return False
    return True


def synthesize(
    *,
    api_url: str,
    text: str,
    ref: RefAudio,
    params: TtsParams,
    output_dir: Path,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    cache_enabled: bool = True,
    preset_id: str = DEFAULT_PRESET_ID,
    engine_params: dict[str, object] | None = None,
    seed: int | None = None,
    max_audio_bytes: int = MAX_AUDIO_BYTES_FALLBACK,
    quota_max_bytes: int = 0,
    quota_max_age_days: int = 0,
) -> tuple[Path | None, str]:
    """合成一段语音并落盘，返回 ``(wav 路径, 失败原因)``；成功时原因为空串。

    G-2 契约参数：

    - ``preset_id``/``engine_params``：预设身份进缓存键；八硬编码项随预设出门；
    - ``seed``：None=按缓存键派生（M-72/U-25 确定性）；
    - ``max_audio_bytes``：产物字节硬顶（0=禁配无界，取内置 8 MiB；G2-R3）；
    - ``quota_max_bytes``/``quota_max_age_days``：落盘后顺接中央配额
      （U-04；0/0=不限制，缺省字节级不变）。
    """
    resolved_engine = engine_params if engine_params is not None else dict(
        PRESET_REGISTRY[DEFAULT_PRESET_ID].params
    )
    key, derived_seed = _cache_identity(text, ref, params, api_url=api_url, preset_id=preset_id)
    effective_seed = derived_seed if seed is None else int(seed)
    if cache_enabled:
        hit = _lookup_cache(key)
        if hit is not None:
            return hit, ""
    # 健康退避闸（M-09）：放在唯一 HTTP 入口之前、缓存查找之后——已合成的
    # 音频照常复用，冷却窗内只省掉注定失败的那次真请求（不再白打服务）。
    backoff = _backoff_reason()
    if backoff:
        return None, backoff
    audio = _request_tts(
        api_url=api_url,
        text=text,
        ref=ref,
        params=params,
        timeout_seconds=timeout_seconds,
        engine_params=resolved_engine,
        seed=effective_seed,
    )
    if audio is None:
        return None, _last_failure_reason or "合成失败"
    bad = _inspect_wav_bytes(audio)
    if not bad:
        byte_cap = int(max_audio_bytes or 0) or MAX_AUDIO_BYTES_FALLBACK
        if len(audio) > byte_cap:
            bad = f"产物 {len(audio)} 字节超字节顶 {byte_cap}"
    if bad:
        # 不可播字节**绝不落盘、绝不入缓存**：SnowLuma 换件后坏 record 段是 fatal
        # （整条消息一字不发，见 report-T46.md），毒件入缓存还会在进程存活期复放。
        logger.info("tts audio rejected by sanity gate: %s (%d bytes)", bad, len(audio))
        return None, f"音频体检失败：{bad}（{len(audio)} 字节）"
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / f"{key}.wav"
        target.write_bytes(audio)
    except (OSError, ValueError) as exc:
        # ValueError 同捕（M-50：非法路径形态抛 ValueError 不该炸成未分类异常）。
        logger.info("tts write failed: %s", exc)
        return None, f"音频落盘失败：{type(exc).__name__}"
    if cache_enabled:
        _store_cache(key, target)
    if quota_max_bytes > 0 or quota_max_age_days > 0:
        # U-04：data/tts_output=缓存语义，接中央「最旧先删」配额；缺省关。
        try:
            enforce_quota(
                output_dir, max_bytes=int(quota_max_bytes), max_age_days=int(quota_max_age_days)
            )
        except Exception:  # noqa: BLE001 - 配额清理失败不影响主链路。
            logger.info("tts quota enforcement failed: output_dir=%s", output_dir)
    return target, ""


def _resolve_preset(config: Any) -> TtsPreset:
    """取当前生效预设：config 选择键 > 缺省；未知 id 回缺省（装载期已枚举校验）。"""
    selected = str(getattr(config, "bot_tts_preset", "") or "").strip().casefold()
    if selected in PRESET_REGISTRY:
        return PRESET_REGISTRY[selected]
    return PRESET_REGISTRY[DEFAULT_PRESET_ID]


def _build_params(config: Any) -> TtsParams:
    """采样参数装配（M-43/M-35）：config 单点直读，缺键回预设表，无第二真值。

    ``text_lang`` 出门前 casefold（POST 入口引擎用原值断言，"ZH" 必 400）。
    """
    preset_params = _resolve_preset(config).params

    def _value(field: str, preset_key: str) -> Any:
        raw: Any = getattr(config, field, None)
        return preset_params[preset_key] if raw is None or raw == "" else raw

    return TtsParams(
        text_lang=str(_value("bot_tts_text_lang", "text_lang")).strip().casefold(),
        speed_factor=float(_value("bot_tts_speed_factor", "speed_factor")),
        temperature=float(_value("bot_tts_temperature", "temperature")),
        top_k=int(_value("bot_tts_top_k", "top_k")),
        top_p=float(_value("bot_tts_top_p", "top_p")),
        text_split_method=str(_value("bot_tts_text_split_method", "text_split_method")),
    )


def _output_dir(config: Any) -> Path:
    raw = str(getattr(config, "bot_tts_output_dir", "") or "data/tts_output")
    return Path(raw)


def _degrade(reason: str) -> str:
    """合成失败时的守岸人口吻降级文案（不暴露内部细节，只给可读方向）。"""
    if "不可达" in reason:
        return "嗓子还没接上——语音服务好像没在跑，稍后再叫我一次吧。"
    if "3~10秒" in reason or "参考音频" in reason:
        return "还差一段合适的参考音频：3 到 10 秒的干声，我才能借到自己的音色。"
    return "这次没能发出声音……等一下再试，或者先听听我打字说的话吧。"


def _no_ref_audio_hint(config: Any) -> str:
    items = list(getattr(config, "bot_tts_ref_audios", []) or [])
    if not items:
        return (
            "还没有给我配参考音频。请在 BOT_TTS_REF_AUDIOS 里填一条 "
            "「音频路径|这段音频说的话」，3 到 10 秒的干声最合适。"
        )
    return (
        "配置里的参考音频文件都找不到——检查 BOT_TTS_REF_AUDIOS 的路径"
        "（相对路径以 BOT_TTS_GPTSOVITS_DIR 为基准）。"
    )


_ISSUE_STAGE = "tts"

_ISSUE_SUMMARY_MAX_CHARS = 200

# 失败原因前缀 → (kind, retryable)：`_request_tts`/`synthesize` 的原因串是本域
# 自己拼的固定前缀，故按前缀分类即可，不看引擎原文（原文只进 safe_summary）。
_FAILURE_KINDS: tuple[tuple[str, str, bool], ...] = (
    ("服务不可达", "tts_service_unreachable", True),
    ("httpx", "tts_service_unreachable", True),
    ("服务返回空音频", "tts_empty_audio", True),
    ("音频体检失败", "tts_bad_audio", False),
    ("服务返回", "tts_service_rejected", False),
    ("音频落盘失败", "tts_write_failed", False),
)


def _issue(
    message: IncomingMessage,
    *,
    kind: str,
    retryable: bool,
    detail: str = "",
) -> OperationalIssue:
    """语音失败的结构化证据（审计 M-13）。

    本域 logger 不在 nonebot 日志树上，`logger.info` 在生产直接丢失；只有挂上
    ``operational_issue``，中央回执链才会告警、错误报告卡才会挂——否则引擎整夜
    不跑而管理员毫不知情。

    ``safe_summary`` 必过 ``redact_local_secrets``：issue 会进诊断卡与管理员私聊，
    而引擎错误体常带本机绝对路径（AGENTS 铁律 3：打码不得绕过）。
    """
    raw = f"{kind}: {detail}" if detail else kind
    return OperationalIssue(
        stage=_ISSUE_STAGE,
        kind=kind,
        retryable=retryable,
        debug_id=message.debug_id,
        safe_summary=redact_local_secrets(raw)[:_ISSUE_SUMMARY_MAX_CHARS].strip(),
    )


def _failure_issue(message: IncomingMessage, reason: str) -> OperationalIssue:
    for prefix, kind, retryable in _FAILURE_KINDS:
        if reason.startswith(prefix):
            return _issue(message, kind=kind, retryable=retryable, detail=reason)
    return _issue(message, kind="tts_synthesize_failed", retryable=False, detail=reason)


def _no_ref_audio_issue(message: IncomingMessage, config: Any) -> OperationalIssue:
    configured = list(getattr(config, "bot_tts_ref_audios", []) or [])
    detail = (
        "BOT_TTS_REF_AUDIOS 未配置"
        if not configured
        else "BOT_TTS_REF_AUDIOS 中的音频文件全部读不到（路径或基准目录不对）"
    )
    return _issue(message, kind="tts_no_ref_audio", retryable=False, detail=detail)


def build_tts_capability(config: Any | None = None) -> Any:
    """构建语音合成能力：返回 ``(message, decision) -> CapabilityResult``。

    与 randpic / eat 等能力同构，可在 offload 线程池里同步执行
    （HTTP 调用是阻塞的，绝不能跑在事件循环线程上）。
    """

    def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
        if not bool(getattr(config, "bot_tts_enabled", False)):
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.tts",
                kind="text",
                send_policy=SendPolicy.SILENT_AUDIT,
                audit_tags=["tts", "skip_disabled"],
            )
        triggers = list(getattr(config, "bot_tts_trigger_words", []) or [])
        body = extract_tts_text(message.plain_text or "", triggers or None)
        if not body:
            # 只发了触发词（「说」「语音」）：给用法引导，不做无意义的空合成。
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.tts",
                kind="text",
                title="",
                body="在「说」后面接上想让我念的话就行，比如：说 今天的潮汐很安静。",
                audit_tags=["tts", "missing_text"],
            )

        # 0=不限（不按字数截断）；「不限≠无界」，下方必过中央硬顶（G2-R3）。
        max_chars = int(getattr(config, "bot_tts_max_chars", 0) or 0)
        speech, blocked = resolve_speech_text(
            config, message, body, max_chars=max_chars
        )
        if blocked:
            # P1-1（T56 反审转发）：政策件异常/配置坏（policy_unavailable）≠ 有意
            # 拦截——异常必须挂 issue 走中央 300s 抑制告警（静默=管理员永远不知
            # 道名单库坏了）；有意拦截（政策拒绝）不挂 issue 防刷屏。
            issue = (
                _issue(
                    message,
                    kind="tts_synthesize_failed",
                    retryable=False,
                    detail=f"policy gate unavailable: {blocked}",
                )
                if blocked == "policy_unavailable"
                else None
            )
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.tts",
                kind="text",
                body=_speech_refusal_hint(),
                audit_tags=["tts", "blocked_by_policy"],
                operational_issue=issue,
            )
        if not speech:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.tts",
                kind="text",
                body="这段话里没有能念出来的内容——换一句试试？",
                audit_tags=["tts", "empty_after_clean"],
            )
        # 文本硬顶（G2-R3）：超顶=拒绝合成+留痕，不静默、**不拆条**（拆多条语音=
        # 多个 record 段的新投递语义，H 波 M-63 修好前拆条=翻倍无保护语音）。
        hard_cap = (
            int(getattr(config, "bot_tts_hard_max_chars", 0) or 0) or HARD_MAX_CHARS_FALLBACK
        )
        if len(speech) > hard_cap:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.tts",
                kind="text",
                body=(
                    "这段话太长了，我一口气念不完——拆成几句再说给我听好不好？"
                ),
                audit_tags=["tts", "over_hard_cap", f"len={len(speech)}", f"cap={hard_cap}"],
                operational_issue=_issue(
                    message,
                    kind="tts_service_rejected",
                    retryable=False,
                    detail=f"over_hard_cap：文本 {len(speech)} 字超硬顶 {hard_cap}"
                    "（bot_tts_hard_max_chars，0=取内置常量），拒绝合成不拆条",
                ),
            )

        preset = _resolve_preset(config)
        params = _build_params(config)
        ref = pick_ref_audio(
            getattr(config, "bot_tts_ref_audios", []) or [],
            base_dir=str(getattr(config, "bot_tts_gptsovits_dir", "") or ""),
        )
        if ref is None:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.tts",
                kind="text",
                body=_no_ref_audio_hint(config),
                audit_tags=["tts", "no_ref_audio"],
                operational_issue=_no_ref_audio_issue(message, config),
            )
        speech_seed = derive_seed(
            speech,
            ref,
            params,
            api_url=str(getattr(config, "bot_tts_api_url", "") or ""),
            preset_id=preset.preset_id,
        )
        path, reason = synthesize(
            api_url=str(getattr(config, "bot_tts_api_url", "") or ""),
            text=speech,
            ref=ref,
            params=params,
            output_dir=_output_dir(config),
            timeout_seconds=float(
                getattr(config, "bot_tts_timeout_seconds", _DEFAULT_TIMEOUT_SECONDS)
            ),
            cache_enabled=bool(getattr(config, "bot_tts_cache_enabled", True)),
            preset_id=preset.preset_id,
            engine_params=dict(preset.params),
            seed=speech_seed,
            max_audio_bytes=int(getattr(config, "bot_tts_max_audio_bytes", 0) or 0),
            quota_max_bytes=int(getattr(config, "bot_tts_cache_max_bytes", 0) or 0),
            quota_max_age_days=int(getattr(config, "bot_tts_cache_max_age_days", 0) or 0),
        )
        if path is None:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.tts",
                kind="text",
                body=_degrade(reason),
                audit_tags=["tts", "synthesize_failed"],
                operational_issue=_failure_issue(message, reason),
            )
        # 与 randpic 同口径：title/body 留空，只发媒体本体，
        # 否则 renderer 的 body→summary→title 兜底链会把标题当文案一起发出去。
        # audit_tags 记 preset/seed（G2-R3：确定性可审计，波末向用户报备
        # 「同句恒同音色」语义变更）。
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.tts",
            kind="text",
            title="",
            body="",
            audio=[{"file": str(path), "review_text": speech}],
            audit_tags=[
                "tts",
                "sent",
                f"preset={preset.preset_id}",
                f"seed={speech_seed}",
            ],
        )

    return capability


def _session_kind(message: IncomingMessage) -> str:
    """会话类型取字符串形态（枚举取 ``.value``，缺省按私聊口径）。"""
    kind = getattr(message, "session_type", "")
    return str(getattr(kind, "value", kind) or "")


def speech_block_reason(config: Any, message: IncomingMessage, text: str) -> str:
    """内容政策裁决：这段文字能不能被**念出来**。返回 ""=放行，非空=拒绝理由位。

    与文字面共用同一个 `assess_public_content` 与同一个 `explicit_allowed` 单一
    事实源——文字能说的语音就能说，文字被拦的语音必须一起被拦（M-02 的根修）。
    政策件不可用时 **fail-closed**：拒的是配音、留的是文字，用户侧几乎无损；
    反过来 fail-open 就是把红线音频永久落盘并发出去。
    """
    kind = _session_kind(message) or "private"
    try:
        explicit = explicit_allowed_for_session(
            kind,
            str(getattr(message, "group_id", "") or ""),
            config,
            str(getattr(message, "sender_id", "") or ""),
        )
        verdict = assess_public_content(
            text,
            session_type=kind,
            explicit_allowed=bool(explicit),
        )
    except Exception as exc:  # noqa: BLE001 - 政策件异常按不放行处理。
        logger.warning("tts speech policy unavailable, refusing synthesis: %s", exc)
        return "policy_unavailable"
    if str(getattr(verdict, "action", "allow")) != "allow":
        category = str(getattr(verdict, "category", "") or "policy_refused")
        logger.warning("tts speech refused by content policy: category=%s", category)
        return category
    return ""


def _apply_lexicon(text: str, lexicon: dict[str, str]) -> str:
    """读法词典应用（M-77 机制）：键=原文精确串，值=替换读法。

    应用点=清洗侧末端（占位符替换之后、内容门之前）。v1 预设词典为空表
    （零行为变更）；条目待 U-02 听辨后逐条入册 tts_presets。禁在此为 RP 括号
    另造第二正则（S-07 教训）——括号段处理收 domains/core 共用件。
    """
    for original, reading in lexicon.items():
        if original:
            text = text.replace(original, reading)
    return text


def resolve_speech_text(
    config: Any,
    message: IncomingMessage,
    raw_text: str,
    *,
    max_chars: int | None = None,
) -> tuple[str, str]:
    """合成前**唯一**的取文口：打码 → 清洗 → 占位符 → 词典 → 内容门。

    返回 ``(可朗读正文, 拒绝理由)``。

    打码必须在最前面：`clean_for_speech` 会吃掉 `_` 与 `>`，先把
    ``BOT_SUPER_ADMIN_API_KEY=x`` 洗成 ``BOTSUPERADMINAPIKEY=x`` 之后，
    中央两条打码正则（`_BOT_ENV_ASSIGN_RE` / `_BARE_KEY_VALUE_RE`）双双失配，
    密钥就跟着音频出门了（M-03 的根修）。

    ``max_chars``：调用方按配置显式传入；**0=不限**（不按字数截断，M-35 语义
    统一——本函数不再把 0 悄悄抬回任何缺省值，硬顶由能力层另行把守）。
    """
    value = redact_local_secrets(str(raw_text or ""))
    limit = max_chars
    if limit is None:
        # 未显式给限=读配置（0=不限原样生效，无 or-反转）。
        limit = int(getattr(config, "bot_tts_max_chars", 0) or 0)
    speech = clean_for_speech(value, max_chars=int(limit))
    # 打码占位符（`<已隐藏>` / `<本机路径已隐藏>`）的尖括号会被清洗吃掉，剩个
    # 残缺形态念出来只会变成一串怪音；换成可读出的词（占位符本身仍不外泄原值）。
    speech = _REDACTION_PLACEHOLDER_RE.sub("已隐去", speech)
    speech = _apply_lexicon(speech, _resolve_preset(config).lexicon)
    if not speech:
        return "", ""
    reason = speech_block_reason(config, message, speech)
    if reason:
        return "", reason
    return speech, ""


def _speech_refusal_hint() -> str:
    """被内容门拦下时的守岸人口吻回执（不复述政策类别、不泄露被拦原文）。"""
    return "这段话我不念出声——留在文字里就好。想让我说点什么，换个说法试试？"


def auto_reply_scope_allows(config: Any, message: IncomingMessage) -> bool:
    """对话自动配音的会话范围判定：private / group / all。"""
    scope = str(getattr(config, "bot_tts_auto_reply_scope", "private") or "private").strip().lower()
    if scope == "all":
        return True
    is_group = bool(str(getattr(message, "group_id", "") or "").strip())
    if scope == "group":
        return is_group
    return not is_group


def _resolve_probability(value: Any) -> float:
    """把概率配置解析成 float；失败按 0（不配音）处理。

    与 ``policy/gate.py`` 的 ``_resolve_probability`` 同口径，支持实时
    callable——概率若由心情之类的动态量参与，必须在每次抽签时求值，
    不能在装配期冻成常量。
    """
    if value is None:
        return 0.0
    if callable(value):
        try:
            return float(value())
        except Exception:  # noqa: BLE001 - 求值失败按不配音处理。
            return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def should_voice_reply(
    config: Any,
    message: IncomingMessage,
    result: CapabilityResult,
) -> bool:
    """对话自动配音的完整门链判定（纯谓词，无副作用，可直测）。

    依次判定：总开关 → 自动配音开关 → 结果尚未带音频 → 结果出自 ``bot.chat``
    → 会话范围匹配 → 概率门。

    概率门用**确定性哈希**（与 ``policy/gate.py`` 的
    ``deterministic_group_reply_lottery`` 同款，media 域内自带一份以保持域边界）：
    seed 取 ``f"{session_id}:{message_id or request_id}"``，同一条消息永远得到
    同一结果——可复现、可审计，也避免用 ``random`` 让测试变成按概率 flaky。
    ``bot_tts_auto_reply_always`` 为真时跳过概率门（全量配音，调试/验收用）。
    """
    if not bool(getattr(config, "bot_tts_enabled", False)):
        return False
    if not bool(getattr(config, "bot_tts_auto_reply_enabled", False)):
        return False
    if result.audio:
        return False
    if str(getattr(result, "capability_id", "")) != "bot.chat":
        return False
    if not auto_reply_scope_allows(config, message):
        return False
    if bool(getattr(config, "bot_tts_auto_reply_always", False)):
        return True
    probability = _resolve_probability(
        getattr(config, "bot_tts_auto_reply_probability", 0.0)
    )
    if probability <= 0:
        return False
    if probability >= 1:
        return True
    seed = (
        f"{getattr(message, 'session_id', '') or ''}:"
        f"{getattr(message, 'message_id', '') or getattr(message, 'request_id', '') or ''}"
    )
    bucket = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16) % 10000
    return bucket < probability * 10000


def maybe_attach_voice(
    message: IncomingMessage,
    result: CapabilityResult,
    *,
    config: Any,
) -> CapabilityResult:
    """给 chat 结果附加语音（供 ``__init__`` 的 chat 能力包装层调用）。

    门链见 ``should_voice_reply``：总开关 / 自动配音开关 / 未带音频 /
    出自 bot.chat / 会话范围 / 概率门。任何失败都原样返回 result——
    配音是增益，绝不能影响文字回复。
    """
    if not should_voice_reply(config, message, result):
        return result
    try:
        # 0=不限（M-35 语义统一：不再 or-抬回 120）；「不限≠无界」，下方过硬顶。
        max_chars = int(getattr(config, "bot_tts_auto_reply_max_chars", 0) or 0)
        speech, blocked = resolve_speech_text(
            config, message, result.body or result.summary or "", max_chars=max_chars
        )
        if blocked:
            # 配音是增益：被内容门拦下就只丢增益，文字回复原样出站。
            logger.info("tts auto reply blocked by policy: category=%s", blocked)
            return result
        if not speech:
            return result
        # 文本硬顶（G2-R3）：自动路超顶=静默放弃增益（文字回复原样出站），
        # 同样不拆条；留痕走日志（配音增益面不挂 issue 防刷屏）。
        hard_cap = (
            int(getattr(config, "bot_tts_hard_max_chars", 0) or 0) or HARD_MAX_CHARS_FALLBACK
        )
        if len(speech) > hard_cap:
            logger.info(
                "tts auto reply skipped: over_hard_cap len=%d cap=%d", len(speech), hard_cap
            )
            return result
        preset = _resolve_preset(config)
        params = _build_params(config)
        ref = pick_ref_audio(
            getattr(config, "bot_tts_ref_audios", []) or [],
            base_dir=str(getattr(config, "bot_tts_gptsovits_dir", "") or ""),
        )
        if ref is None:
            return result
        speech_seed = derive_seed(
            speech,
            ref,
            params,
            api_url=str(getattr(config, "bot_tts_api_url", "") or ""),
            preset_id=preset.preset_id,
        )
        path, reason = synthesize(
            api_url=str(getattr(config, "bot_tts_api_url", "") or ""),
            text=speech,
            ref=ref,
            params=params,
            output_dir=_output_dir(config),
            timeout_seconds=float(
                getattr(config, "bot_tts_timeout_seconds", _DEFAULT_TIMEOUT_SECONDS)
            ),
            cache_enabled=bool(getattr(config, "bot_tts_cache_enabled", True)),
            preset_id=preset.preset_id,
            engine_params=dict(preset.params),
            seed=speech_seed,
            max_audio_bytes=int(getattr(config, "bot_tts_max_audio_bytes", 0) or 0),
            quota_max_bytes=int(getattr(config, "bot_tts_cache_max_bytes", 0) or 0),
            quota_max_age_days=int(getattr(config, "bot_tts_cache_max_age_days", 0) or 0),
        )
        if path is None:
            logger.info("tts auto reply skipped: %s", reason)
            return result
        return result.model_copy(
            update={
                "audio": [{"file": str(path), "review_text": speech}],
                "audit_tags": [
                    *result.audit_tags,
                    "tts",
                    "auto_reply",
                    f"preset={preset.preset_id}",
                    f"seed={speech_seed}",
                ],
            }
        )
    except Exception as exc:  # noqa: BLE001 - 配音增益绝不阻断文字回复。
        logger.info("tts auto reply failed: %s", exc)
        return result
