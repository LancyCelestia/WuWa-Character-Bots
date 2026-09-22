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
- **退避清零时机对齐（WP4/E1-1）**：健康退避闸（M-09）的「算成功=清零」判据与
  产物校验严格对齐——只有 ``synthesize`` 通过全部校验（结构 + 静音指纹 + 字节顶）
  且**落盘交付**后才 ``_clear_failure()``；引擎「200+恰 1s 静音」伪装成功不再被
  抢跑清零、而是计入退避窗（窗内快速失败，不再白等 60s、不再占死线程池 worker）。
  清零与进窗都只走 ``_record_failure``/``_clear_failure`` 单一状态机，无第二副本。
- **对话自动配音**（可选）：``BOT_TTS_AUTO_REPLY_ENABLED`` 开启后，
  ``maybe_attach_voice()`` 把人格回复正文一并合成为语音随消息发出，
  由 ``__init__`` 的 chat 能力包装层调用。是否真的配音由
  ``should_voice_reply()`` 统一裁决：总开关 / 自动配音开关 / 未带音频 /
  出自 ``bot.chat`` / 会话范围（``BOT_TTS_AUTO_REPLY_SCOPE``，**礼仪维度**）/
  群面中央名单门（M-17：群聊必须过 ``explicit_allowed_for_session``——
  黑名单永远赢、群白名单空=群面关闭绝不猜群，**安全维度**，与 chat 主链
  同一事实源）/ 概率门（``BOT_TTS_AUTO_REPLY_PROBABILITY``，默认 5%，
  确定性哈希实现，同一条消息结果恒定可复现）。
- **有损变换可观测（M-14）**：``resolve_speech_text`` 的打码/markdown 剥除/
  截断/占位符替换/词典替换每一步都产出机读结论（``audit`` 出参 + audit_tags
  ``truncated=true``/``kept_ratio=0.42`` 等），零文本行为变更——「语音只念了
  42% 字」这类事实（T26-表3）从此可从机读面直接看出来。
- **出站内容摘要（M-64/S2）**：audio 部件随件携带落盘字节 sha256
  （``content_sha256``，中央件 ``domains/media/digest.py`` 单一入口）；
  算不出即部件不带键（诚实降级，与渲染收口缺省退化咬合），零行为变更面。
  观测面（U-107-C/T144）：``audit_tags`` 同步记 ``audio_sha256=<[:16]>``
  （键内截短=U-107-A 已裁；part 随行全长；纯元数据零行为变更）。
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
import uuid
import wave
from collections import OrderedDict
from collections.abc import Callable
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
from plugins.bot_unified_runtime.domains.core.text_boundary import (
    match_trigger,
)
from plugins.bot_unified_runtime.domains.media.digest import (
    media_digest,
    media_digest_file,
)
from plugins.bot_unified_runtime.domains.media.tts_presets import (
    DEFAULT_PRESET_ID,
    IDENTITY_VERSION,
    MAX_AUDIO_BYTES_FALLBACK,
    PRESET_REGISTRY,
    SEED_RULE_VERSION,
    TtsPreset,
    effective_lexicon,
    resolve_hard_max_chars,
    resolve_max_audio_bytes,
)
from plugins.bot_unified_runtime.domains.render.plain_text import redact_local_secrets
from plugins.bot_unified_runtime.domains.render.roleplay import strip_action_brackets

logger = logging.getLogger(__name__)

# 触发词（T-Spec 口径）：中文 + 英文 + 拼音全拼/缩写 + 繁體（M-16 后半，T92）。
# 边界判定沿用 randpic 的保守哲学——整句等于触发词，或触发词后紧跟
# 标点/空白，避免「说话」「念书」「语音消息」这类包含关系词误触发。
# 「语音合成」与 help 主题别名同源：帮助里列出的词，路由面必须真能命中
# （tests/test_trigger_bidirectional_gate.py 的词级双向门锁定这件事）。
# 繁體口径（tts-contract-layer §6 明文）：**词表登记解决，不做 s2t 转换器**——
# 繁體命中只靠下方繁體条目登记，casefold 不做繁→简映射；正文取原串切片，
# 用户的繁體用字原样合成。英文/拼音 6 词（tts/say/shuo/yuyin/nian/langdu）
# 为罗马字，无繁體形态，如实不造。
DEFAULT_TRIGGER_WORDS: tuple[str, ...] = (
    "语音合成", "朗读", "语音", "念", "说",
    "tts", "say", "shuo", "yuyin", "nian", "langdu",
    # 繁體登记（与上方简中词逐词对应；tests/test_text_boundary_central.py
    # 繁體口径节 + tests/test_tts_hijack_guard.py 繁體样本双锁）。
    "語音合成", "朗讀", "語音", "唸", "說",
)
# 触发词与正文之间的分隔字符**不再本地持有**：S-07 六副本收编最后一副本（T83）
# 换线中央件 ``domains/core/text_boundary``，权威取值=
# ``text_boundary.TRIGGER_BOUNDARY_CHARS``（本文件 d3a53ea 收紧集逐字上收，
# T77 值漂移硬锁曾钉两侧逐字一致）。⚠️ 那里**只能放真分隔符**（标点与空白），
# 一个词字符都不能进：曾经收录过「了/的/呢/吗/呀/啊/哈」，于是「说了再见」
# 「说的对」「语音哈喽」这类日常聊天被整句吞进 bot.tts（priority 41 + block=True
# ⇒ 消息不再进人格对话），并把「再见」「对」「喽」这种残片念出去。实测 312 句
# 日常中文劫持率 68.1%。回归锁见 tests/test_tts_hijack_guard.py（含"边界集合
# 不得出现汉字"的棘轮断言，换线后直锁权威值）。

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
# 静音陷阱产物的机读签名（体检拒因的前缀，退避归类与结构类拒因的唯一分界）：
# 引擎「HTTP 200 + 恰 1s 静音」伪装成功=部署类故障，须计退避窗（WP4/E1-1）；
# 非 RIFF/头不可解析/零帧等结构类坏字节则不入窗（分类学既有，禁放宽）。
# 该串只作前缀判据，不参与文案；改判据须同步 _inspect_wav_bytes 与 synthesize。
_SILENCE_TRAP_MARK = "静音陷阱："

# 合成结果缓存（进程内 LRU 索引）：key → (落盘路径, 写入时刻)。
# 键数封顶，避免长跑进程按文本无界增长（对齐 runtime/reactions.py 惯例）。
_CACHE_LRU_CAP = 512
_CACHE: OrderedDict[str, tuple[Path, float]] = OrderedDict()

# 参考音频内容指纹（M-11 + T62 P2-2）：**每次全量 sha256，取前 16 hex**。
# 曾经是「首次哈希、之后 stat 比 (size,mtime)」快路径——T62 变异实测 stat-only
# 全绿（指纹语义零正向钉死），且「touch 回写旧时间戳 / 备份还原」这类真实场景
# 会永久命中旧音色。改常哈希的代价≈每次合成多算一次几百 KB 的 sha256（<1ms），
# 相对秒级 HTTP 合成可忽略；正确性收益=指纹恒为内容的纯函数。

# 服务健康退避闸（M-09 接线，U-20 裁定=接线不删净）：真失败（不可达/被拒/
# 空音频/httpx 缺失，以及 WP4 新增的「引擎 200+恰 1s 静音」伪装成功陷阱）进入
# 冷却窗，窗内后续合成**不发 HTTP** 直接快速失败（原因以「服务不可达」开头 →
# 挂 ``tts_service_unreachable`` 可重试 issue），窗满自动放行（非永久拉黑）；
# 「真成功清零」的时机=产物过全部校验（结构+静音指纹+字节顶）且落盘交付之后
# （synthesize 唯一成功提交点，WP4/E1-1：此前抢跑在 _request_tts 的 200 分支清零
# 会让静音陷阱永不进窗）；快速失败不刷新窗口。结构类坏字节/字节顶超限不入窗。
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

    追加词与内置词表**合并生效**（M-15，b13913d 落地）：对齐 catalog /
    `.env.example` / help 条目三处「与内置合并」的既有承诺——管理员追加词
    只增不减，内置词永不因追加而失配。合并语义收在这**唯一入口**，
    路由谓词与取文共用。
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

    判定体已收编中央件 ``domains/core/text_boundary.match_trigger``（S-07
    六副本收编最后一副本，T83 换线）：最长触发词优先匹配（``语音合成`` 之于
    ``语音``）、英文大小写不敏感（``SAY``/``TTS`` 是真命令，M-16）、正文一律
    取原串切片绝不返回折叠后的大小写、casefold 改变长度的极端字符（ß→ss）
    回退逐字精确匹配、权威边界集（d3a53ea 收紧集）——语义与字符集均自本文件
    逐字上收（T59 建件蓝本）。本函数保留为**取文入口薄别名**（L-C04：词表
    提取器 harvest 依赖 ``extract_tts_text``/``DEFAULT_TRIGGER_WORDS`` 名与
    词表留在本模块 globals，提取器递归委托追踪已支持转发形态）。
    """
    return match_trigger(text, effective_trigger_words(trigger_words))


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


def _clean_for_speech_tracked(
    text: str, *, max_chars: int = 0, lexicon: dict[str, str] | None = None
) -> tuple[str, dict[str, Any]]:
    """``clean_for_speech`` 的带审计内里（M-14）：同一次变换顺带产出机读事实。

    返回 ``(清洗结果, 审计 dict)``。清洗操作与顺序和公开 pure 函数**逐字一致**
    （``clean_for_speech`` 就是本函数的取首元薄壳；词典只随 ``lexicon`` 出参
    进入，pure 形态不收词典）——审计只读不写。审计键：``raw_len``/``kept_len``/
    ``stripped``（剥除族是否真删了东西）/``truncated``（是否按 ``max_chars``
    截断）/``actions_removed``（M-73：括号动作段是否真摘除了）/``lexicon_replaced``
    （M-77：词典替换命中数，仅随 ``lexicon`` 出参出现）。
    """
    value = str(text or "")
    audit: dict[str, Any] = {"raw_len": len(value), "stripped": False, "truncated": False}
    if not value.strip():
        return "", audit
    pre_strip = value
    value = _FENCE_RE.sub(" ", value)
    value = _INLINE_CODE_RE.sub(" ", value)
    value = _URL_RE.sub(" ", value)
    # M-73（T104）：括号动作段不进语音——**消费**文字侧同一识别真相源
    # ``domains/render/roleplay.strip_action_brackets``（括号内含汉字或嵌套
    # 括号=动作段：独立行整段摘除、行内 span 剥除；括号内无汉字=颜文字保留；
    # 未闭合括号按普通文字安全忽略；半角全角同语义）。语音侧**零第二括号
    # 正则**（S-07 概率门四副本的教训、T25-Q3 明文禁令）。摆位：在围栏/行内
    # 代码/链接之后——代码体内的全角括号不误判成动作；在 markdown 记号剥除
    # 之前——动作段连同段内记号一起消失。
    if "（" in value or "(" in value:
        pre_bracket = value
        value = strip_action_brackets(value)
        audit["actions_removed"] = value != pre_bracket
    value = _MARKDOWN_MARKS_RE.sub("", value)
    value = _LIST_PREFIX_RE.sub("", value)
    audit["stripped"] = value != pre_strip
    value = _BLANK_LINES_RE.sub("\n", value)
    value = _SPACES_RE.sub(" ", value)
    value = value.replace("\n", " ").strip()
    # M-77（T104）：读法词典应用点=打码后、截断前——替换读法计入截断账，
    # 出门文本不会因词典替换顶破 max_chars。条级关断由
    # ``tts_presets.effective_lexicon`` 在上游裁决，本函数收到什么替换什么。
    if lexicon:
        value, lexicon_hits = _apply_lexicon(value, lexicon)
        audit["lexicon_replaced"] = lexicon_hits
    if max_chars > 0 and len(value) > max_chars:
        value = _truncate_at_sentence(value, max_chars)
        audit["truncated"] = True
    audit["kept_len"] = len(value)
    return value, audit


def clean_for_speech(text: str, *, max_chars: int = 0) -> str:
    """把回复正文清洗成适合朗读的纯文本。

    去掉代码块/行内代码/链接/markdown 标记与列表前缀——这些东西念出来只会
    变成一串噪音。**括号动作段整段/行内剥除（M-73，T104）**：识别规则消费
    文字侧同一真相源 ``domains/render/roleplay.strip_action_brackets``——
    括号内含汉字或嵌套括号=动作描写（独立行整段摘除、行内 span 剥除，半角
    全角同语义）；括号内无汉字（``(≧▽≦)`` 类颜文字）保留；未闭合括号按
    普通文字安全忽略。**行为变更披露**：动作描写不再被念出——修复前
    ``（微微一笑）`` 会被整段合成进人声（T25-P1-3/T26-S-3 双实跑，11/11
    括号样本 100% 入声；本 docstring 曾宣称删「颜文字括号」实无该规则，
    T25-P3-2，自 T104 起宣称与实现一致）。``max_chars > 0`` 时在句子边界
    截断；**0（函数缺省）=不限**（不按字数截断）——纯函数不做隐藏截断，
    限制由调用方按配置显式传入（M-35：配置面 0=不限 语义统一，「不限≠无界」
    由中央硬顶另行把守）。本 pure 形态不做读法词典替换（词典随
    ``resolve_speech_text`` 按预设配置进入管线，M-77）。

    本函数是 ``_clean_for_speech_tracked`` 的取首元薄壳：行为零差异；
    需要有损变换机读结论的调用方走 ``resolve_speech_text(…, audit=…)``。
    """
    return _clean_for_speech_tracked(text, max_chars=max_chars)[0]


def _truncate_at_sentence(text: str, limit: int) -> str:
    """在 limit 以内尽量切在句末标点处。"""
    window = text[:limit]
    for index in range(len(window) - 1, max(0, limit - 40), -1):
        if window[index] in _SENTENCE_END:
            return window[: index + 1]
    return window


def _ref_fingerprint(ref_path: str) -> str:
    """参考音频内容指纹（M-11 + T62 P2-2）：内容 sha256 前 16 hex。

    指纹是**内容的纯函数**（每次全量哈希）：「内容变而 size+mtime 被还原」
    （touch 回写/备份还原）不再永久命中旧音色。原 stat 快路径已删——T62 变异
    实测 stat-only 全绿（零正向钉死），且哈希成本相对秒级合成可忽略（注释见
    模块头）。读不到的路径返回 ``"missing"``（确定性占位；不同路径另有 ``ref``
    段区分）。

    T127 起哈希收编中央件 ``media_digest_file``（S-08 单一入口；1MB chunk
    流式，O(1) 内存）：ref 音频可达 MB 级，全量 ``read_bytes`` 入内存不再
    必要。成功路径逐字节等价（同 sha256，``[:16]`` 截短=消费侧决定）；
    OSError→None→``"missing"`` 与旧 OSError 分支同义（U-107-B 缺即缺）。
    """
    digest = media_digest_file(ref_path)
    if digest is None:
        return "missing"
    return digest[:16]


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
    - ``cache_key = sha256(preimage + seed 规则版本)[:20]``（20 hex 形态不变；
      规则版本入键，防跨派生规则键撞）。**注意（M-39，T101）**：键只作内存
      缓存身份，不再是落盘文件名——盘上名已随机化（见 ``synthesize``），键与
      文件名的确定映射已切断。
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
    # 键派生再哈希收编中央件 media_digest（T127，T121 移交项）：表达式恒等
    # （即 sha256().hexdigest()），键空间零变化，温缓存不失效。
    seed = int(media_digest(preimage.encode("utf-8"))[:8], 16)
    cache_key = media_digest(
        (preimage + "|" + SEED_RULE_VERSION).encode("utf-8")
    )[:20]
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
) -> tuple[bytes | None, str]:
    """调用 api_v2.py 的 ``POST /tts``，返回 ``(wav 字节, 失败原因)``。

    成功时原因为空串；失败返回 ``(None, 原因)``——**原因随请求返回**（T62
    P1-1）：旧实现把原因放模块全局再由 ``synthesize`` 回读，并发下会读到
    别的请求的原因，``_FAILURE_KINDS`` 错挂 kind 污染 M-13 告警分类。

    异常一律吞掉（fail-open）——调用方据此给降级文案。**失败分类学**
    （T62 P2-1 + WP4/E1-1）：只有部署类失败进 30s 健康退避窗（``_record_failure``）——
    不可达/超时、5xx、空音频、httpx 缺失；确定性请求类拒绝（4xx，如参考
    音频 3~10s 越界、参数错）**不进窗**：坏 ref 是持续性的，进窗只会让全员
    周期性吃「服务没在跑」的失真文案。

    **本函数不再清零退避状态**（WP4 根修）：旧实现在 HTTP 200 + 非空体分支抢跑
    ``_clear_failure()``，而静音指纹闸在调用方 ``synthesize`` 的**更后面**才判 ⇒
    引擎以「200 + 恰 1s 静音」伪装成功时每条请求都把上一轮失败清零、退避保护
    永不启动，白等 60s 并占死一个线程池 worker。清零时机与「算成功」判据对齐：
    唯一成功提交点在 ``synthesize``——产物过全部校验（结构 + 静音指纹 + 字节顶）
    且落盘交付之后才 ``_clear_failure()``；静音陷阱产物由 ``synthesize`` 计入退避窗。
    结构类坏字节（非 RIFF/头不可解析/零帧）与字节顶超限仍**不入窗**（既有分类学，
    禁放宽——坏字节多是单次/瞬时，进窗只会周期性误伤全员）。
    """
    try:
        import httpx
    except Exception:  # noqa: BLE001 - 缺依赖按服务不可用处理。
        # 与其余失败同口径记账（M-46 指认的「httpx 分支不更新时刻」在此收口）。
        _record_failure("httpx 不可用")
        return None, "httpx 不可用"

    endpoint = f"{api_url.rstrip('/')}/tts"
    payload = _build_request_payload(text, ref, params, engine_params=engine_params, seed=seed)
    try:
        with httpx.Client(timeout=max(1.0, float(timeout_seconds))) as client:
            response = client.post(endpoint, json=payload)
    except Exception as exc:  # noqa: BLE001 - 连接/超时统一按失败降级。
        reason = f"服务不可达：{type(exc).__name__}"
        _record_failure(reason)
        logger.info("tts request failed: %s", exc)
        return None, reason
    if response.status_code != 200:
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
        reason = f"服务返回 {response.status_code}：{detail[:160]}"
        if response.status_code >= 500:
            # 部署类失败（网关/引擎内部故障）→ 进退避窗；4xx=确定性请求类拒绝
            # → 只随请求返回原因，不进窗（T62 P2-1，分类学见 docstring）。
            _record_failure(reason)
        logger.info("tts request rejected: %s %s", response.status_code, detail)
        return None, reason
    if not response.content:
        _record_failure("服务返回空音频")
        return None, "服务返回空音频"
    # WP4/E1-1：此处**不清零**——200 + 非空体不代表「产物可用」，静音陷阱正长这样。
    # 退避清零推迟到 synthesize 的产物校验 + 落盘交付之后（唯一成功提交点）。
    return response.content, ""


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
    失败——不落盘、不入缓存、不出站，且**计入退避窗**（引擎以 200 伪装成功=
    部署类故障，见 ``_SILENCE_TRAP_MARK`` 与 ``synthesize``；WP4/E1-1）。
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
    trap_seconds = _silence_trap_seconds(rate, frames, data)
    if trap_seconds > 0:
        return f"{_SILENCE_TRAP_MARK}{trap_seconds:.1f} 秒静音（引擎推理异常伪装成功）"
    return ""


def _silence_trap_seconds(rate: int, frames: int, data: bytes) -> float:
    """静音陷阱三指纹同中的**唯一判据**：命中返回时长（秒），否则 0.0。

    单一事实源——结构体检（``_inspect_wav_bytes``）与退避归类（``synthesize``）
    都据此，禁第二份副本。「非 RIFF/头不可解析/零帧」等结构类坏字节不走此路，
    因而**不计退避窗**（分类学边界，禁放宽）。
    """
    if (
        rate == _SILENCE_RATE
        and _SILENCE_MIN_SECONDS <= frames / rate <= _SILENCE_MAX_SECONDS
        and _is_near_silent(data, frames)
    ):
        return frames / rate
    return 0.0


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
    audio, fail_reason = _request_tts(
        api_url=api_url,
        text=text,
        ref=ref,
        params=params,
        timeout_seconds=timeout_seconds,
        engine_params=resolved_engine,
        seed=effective_seed,
    )
    if audio is None:
        # 原因随请求返回（T62 P1-1）：不回读全局——并发下那是别的请求的原因。
        return None, fail_reason or "合成失败"
    bad = _inspect_wav_bytes(audio)
    if not bad:
        byte_cap = int(max_audio_bytes or 0) or MAX_AUDIO_BYTES_FALLBACK
        if len(audio) > byte_cap:
            bad = f"产物 {len(audio)} 字节超字节顶 {byte_cap}"
    if bad:
        # 不可播字节**绝不落盘、绝不入缓存**：SnowLuma 换件后坏 record 段是 fatal
        # （整条消息一字不发，见 report-T46.md），毒件入缓存还会在进程存活期复放。
        # WP4/E1-1：引擎「200 + 恰 1s 静音」伪装成功=部署类故障，计入退避窗——
        # 窗内后续合成快速失败，不再白等 60s、不再占死线程池 worker（此前
        # _request_tts 的 200 分支抢跑 _clear_failure ⇒ 该故障永不进窗）。
        # 结构类坏字节（非 RIFF/头不可解析/零帧）与字节顶超限**不入窗**（分类学，
        # 禁放宽）：它们不是「引擎活着却持续生产垃圾」的形态，进窗只会误伤全员。
        if bad.startswith(_SILENCE_TRAP_MARK):
            _record_failure(f"服务不可达：引擎以 200 返回静音伪装产物（{bad}）")
        logger.info("tts audio rejected by sanity gate: %s (%d bytes)", bad, len(audio))
        return None, f"音频体检失败：{bad}（{len(audio)} 字节）"
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        # M-39（Wave H T101）：落盘名随机化——文件名不再是内容指纹。历史形态
        # ``f"{key}.wav"``（key=sha256(preimage+规则版本)[:20]，preimage 明文含
        # text 全文+ref.text）让「哪句话被合成过」可离线字典反推。缓存身份
        # **零改动**：内存键仍内容寻址（同键命中同一路径=单文件语义）；随机名
        # 后每键一文件、缓存未命中即换名，孤儿文件由中央配额回收（M-27/T61，
        # ``enforce_quota``）。uuid4 冲突概率可忽略，不做重试。
        target = output_dir / f"tts-{uuid.uuid4().hex}.wav"
        target.write_bytes(audio)
    except (OSError, ValueError) as exc:
        # ValueError 同捕（M-50：非法路径形态抛 ValueError 不该炸成未分类异常）。
        logger.info("tts write failed: %s", exc)
        return None, f"音频落盘失败：{type(exc).__name__}"
    # WP4/E1-1：唯一「成功提交点」——产物过全部校验（结构体检 + 静音指纹 + 字节顶）
    # 且已落盘可交付，此刻才清零退避状态。落盘失败走上面 except 分支，绝不清零。
    _clear_failure()
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
    """语音产物落盘目录（M-52 第二半，T127 收口）。

    三态语义与 config path_fields（T125 已入 ``bot_tts_output_dir``）对齐：
    绝对/已解析配置值原样透传；空串（含纯空白）缺省兜底 ``data/tts_output``
    经 ``scripts.runtime_paths.runtime_path`` 落 Runtime 数据根——兜底不再按
    CWD 解析，源码树 ``data/`` 污染面就此断根（台账 #1 同族）。
    """
    # 惰性 import（chat.py:195 先例）：scripts/ 非包依赖，模块期引入拖加载面。
    from scripts.runtime_paths import runtime_path

    raw = str(getattr(config, "bot_tts_output_dir", "") or "").strip()
    if raw:
        return Path(raw)
    return runtime_path("data/tts_output")


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


def _failure_kind_tag(reason: str) -> str:
    """失败原因 → kind 标签（``_FAILURE_KINDS`` 前缀表的唯一分类口）。"""
    for prefix, kind, _retryable in _FAILURE_KINDS:
        if reason.startswith(prefix):
            return kind
    return "tts_synthesize_failed"


def _failure_issue(message: IncomingMessage, reason: str) -> OperationalIssue:
    return _issue(
        message,
        kind=_failure_kind_tag(reason),
        retryable=_failure_retryable(reason),
        detail=reason,
    )


def _failure_retryable(reason: str) -> bool:
    for prefix, _kind, retryable in _FAILURE_KINDS:
        if reason.startswith(prefix):
            return retryable
    return False


def _no_ref_audio_issue(message: IncomingMessage, config: Any) -> OperationalIssue:
    configured = list(getattr(config, "bot_tts_ref_audios", []) or [])
    detail = (
        "BOT_TTS_REF_AUDIOS 未配置"
        if not configured
        else "BOT_TTS_REF_AUDIOS 中的音频文件全部读不到（路径或基准目录不对）"
    )
    return _issue(message, kind="tts_no_ref_audio", retryable=False, detail=detail)


def _content_digest_for(path: Any) -> str | None:
    """出站 audio 部件的内容摘要（M-64/S2，蓝图 ``docs/design/media-digest-layer.md`` §3.3）。

    摘要=**落盘字节真值**（sha256 全长 64 hex 小写，经中央件 ``media_digest_file``，
    单一入口禁手抄）——缓存命中路（bytes 不在内存）与新鲜合成路同一语义，答案
    恒为「发出去的字节是什么」（蓝图 §4 出站侧职责）。读不到/形态异常 →
    ``None``：部件不带键（诚实降级，与渲染收口 ``canonicalize_audio_parts``
    缺省退化咬合），禁静默造假值；digest 是增益件，任何失败绝不阻断出站。
    """
    if not isinstance(path, (str, Path)):
        return None
    try:
        return media_digest_file(path)
    except Exception:  # noqa: BLE001 - digest 增益件 fail-open（同 synth fail-open 哲学）。
        logger.info("tts content digest unavailable: path=%r", path)
        return None


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
        lossy_audit: dict[str, Any] = {}
        speech, blocked = resolve_speech_text(
            config, message, body, max_chars=max_chars, audit=lossy_audit
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
            # 空结果也带上有损变换事实（M-14）：「为什么没的念」从机读面可查。
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.tts",
                kind="text",
                body="这段话里没有能念出来的内容——换一句试试？",
                audit_tags=[
                    "tts",
                    "empty_after_clean",
                    *lossy_transform_tags(lossy_audit),
                ],
            )
        # 文本硬顶（G2-R3）：超顶=拒绝合成+留痕，不静默、**不拆条**（拆多条语音=
        # 多个 record 段的新投递语义，H 波 M-63 修好前拆条=翻倍无保护语音）。
        hard_cap = resolve_hard_max_chars(config)
        if len(speech) > hard_cap:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.tts",
                kind="text",
                body=(
                    "这段话太长了，我一口气念不完——拆成几句再说给我听好不好？"
                ),
                audit_tags=[
                    "tts",
                    "over_hard_cap",
                    f"len={len(speech)}",
                    f"cap={hard_cap}",
                    *lossy_transform_tags(lossy_audit),
                ],
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
            max_audio_bytes=resolve_max_audio_bytes(config),
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
        # 「同句恒同音色」语义变更）与有损变换事实（M-14）。
        # M-64/S2（蓝图 §3.3）：出站部件随件携带落盘字节摘要（content_sha256），
        # 渲染收口第三冻结键随段级键自动下行；算不出即缺省（诚实降级）。
        # U-107-C/T144 观测面：audit_tags 同步记 ``audio_sha256=<[:16]>``
        # （键内截短=U-107-A 已裁口径；part 随行全长，纯元数据零行为变更）。
        audio_part: dict[str, Any] = {"file": str(path), "review_text": speech}
        content_digest = _content_digest_for(path)
        if content_digest is not None:
            audio_part["content_sha256"] = content_digest
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.tts",
            kind="text",
            title="",
            body="",
            audio=[audio_part],
            audit_tags=[
                "tts",
                "sent",
                f"preset={preset.preset_id}",
                f"seed={speech_seed}",
                *(
                    [f"audio_sha256={content_digest[:16]}"]
                    if content_digest is not None
                    else []
                ),
                *lossy_transform_tags(lossy_audit),
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


def _apply_lexicon(text: str, lexicon: dict[str, str]) -> tuple[str, int]:
    """读法词典应用（M-77）：键=原文精确串，值=替换读法。

    应用点=清洗管线内（打码后、截断前，T104）：替换读法计入截断账，出门
    文本不因替换顶破 ``max_chars``。传入的词典应是 ``tts_presets.effective_lexicon``
    的出参（条级关断已在上游裁决）。禁在此为 RP 括号另造第二正则（S-07
    教训）——括号段处理消费 ``domains/render/roleplay`` 共用件。不做全量读音
    规范：人名/专名/多音字读法挂 U-02 听辨另波。

    返回 ``(替换后文本, 替换命中次数)``（M-14：命中数进机读审计；替换语义
    与顺序零变化）。
    """
    hits = 0
    for original, reading in lexicon.items():
        if original:
            hits += text.count(original)
            text = text.replace(original, reading)
    return text, hits


def resolve_speech_text(
    config: Any,
    message: IncomingMessage,
    raw_text: str,
    *,
    max_chars: int | None = None,
    audit: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """合成前**唯一**的取文口：打码 → 清洗（括号动作摘除/记号剥除/词典替换/
    截断）→ 占位符 → 内容门。

    返回 ``(可朗读正文, 拒绝理由)``。

    打码必须在最前面：`clean_for_speech` 会吃掉 `_` 与 `>`，先把
    ``BOT_SUPER_ADMIN_API_KEY=x`` 洗成 ``BOTSUPERADMINAPIKEY=x`` 之后，
    中央两条打码正则（`_BOT_ENV_ASSIGN_RE` / `_BARE_KEY_VALUE_RE`）双双失配，
    密钥就跟着音频出门了（M-03 的根修）。

    ``max_chars``：调用方按配置显式传入；**0=不限**（不按字数截断，M-35 语义
    统一——本函数不再把 0 悄悄抬回任何缺省值，硬顶由能力层另行把守）。

    ``audit``（M-14）：可选出参 dict——有损变换的机读事实写回这里
    （``redacted``/``stripped``/``truncated``/``placeholders_replaced``/
    ``lexicon_replaced``/``actions_removed``/``raw_len``/``kept_len``/
    ``kept_ratio``），文本处理结果零变化；渲染成 audit_tags 用
    ``lossy_transform_tags``。
    """
    raw = str(raw_text or "")
    value = redact_local_secrets(raw)
    limit = max_chars
    if limit is None:
        # 未显式给限=读配置（0=不限原样生效，无 or-反转）。
        limit = int(getattr(config, "bot_tts_max_chars", 0) or 0)
    speech, clean_audit = _clean_for_speech_tracked(
        value,
        max_chars=int(limit),
        lexicon=effective_lexicon(_resolve_preset(config).lexicon),
    )
    # 打码占位符（`<已隐藏>` / `<本机路径已隐藏>`）的尖括号会被清洗吃掉，剩个
    # 残缺形态念出来只会变成一串怪音；换成可读出的词（占位符本身仍不外泄原值）。
    speech, placeholder_hits = _REDACTION_PLACEHOLDER_RE.subn("已隐去", speech)
    if audit is not None:
        kept_ratio = round(len(speech) / len(raw), 2) if raw else 1.0
        audit.update(
            {
                "raw_len": len(raw),
                "kept_len": len(speech),
                "kept_ratio": kept_ratio,
                "redacted": value != raw,
                "stripped": bool(clean_audit.get("stripped")),
                "truncated": bool(clean_audit.get("truncated")),
                "placeholders_replaced": int(placeholder_hits),
                "lexicon_replaced": int(clean_audit.get("lexicon_replaced", 0)),
                "actions_removed": bool(clean_audit.get("actions_removed")),
            }
        )
    if not speech:
        return "", ""
    reason = speech_block_reason(config, message, speech)
    if reason:
        return "", reason
    return speech, ""


def lossy_transform_tags(audit: dict[str, Any] | None) -> list[str]:
    """M-14：把 ``resolve_speech_text`` 的审计 dict 渲染成机读 audit_tags。

    稀疏-真值口径（与 ``over_hard_cap``/``skip_disabled`` 同惯例）：事实为真
    才出现，键值形如 ``truncated=true``/``kept_ratio=0.42``。硬顶触发的机读
    结论由能力层既有 ``over_hard_cap``+``len=``+``cap=`` 承担，此处不重复。
    """
    if not audit:
        return []
    tags: list[str] = []
    if audit.get("redacted"):
        tags.append("redacted=true")
    if audit.get("stripped"):
        tags.append("stripped=true")
    if audit.get("truncated"):
        tags.append("truncated=true")
    ratio = audit.get("kept_ratio")
    if isinstance(ratio, (int, float)) and ratio < 1.0:
        tags.append(f"kept_ratio={ratio}")
    placeholders = audit.get("placeholders_replaced")
    if placeholders:
        tags.append(f"placeholders_replaced={placeholders}")
    if audit.get("actions_removed"):
        # M-73（T104）：括号动作段摘除的机读事实——「念出的和文字看到的不一样」
        # 从此可从 audit_tags 直接看出来。
        tags.append("actions_removed=true")
    lexicon_hits = audit.get("lexicon_replaced")
    if lexicon_hits:
        tags.append(f"lexicon_replaced={lexicon_hits}")
    return tags


def _speech_refusal_hint() -> str:
    """被内容门拦下时的守岸人口吻回执（不复述政策类别、不泄露被拦原文）。"""
    return "这段话我不念出声——留在文字里就好。想让我说点什么，换个说法试试？"


def auto_reply_scope_allows(config: Any, message: IncomingMessage) -> bool:
    """对话自动配音的会话范围判定：private / group / all（**礼仪维度**）。

    本谓词只答「用户想在哪些会话面听配音」；「哪里允许说」的安全维度由
    ``should_voice_reply`` 里的中央名单门（``explicit_allowed_for_session``，
    M-17）承担——两门串联，互不取代。
    """
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
    → 会话范围匹配（**礼仪维度**，``BOT_TTS_AUTO_REPLY_SCOPE``）→ 群面中央
    名单门（**安全维度**，M-17）→ 概率门。

    M-17 中央同源：scope 放行的**群聊**必须再过
    ``explicit_allowed_for_session("group", …)``——与 chat 主链/被动好感共用
    的单一事实源，v21r5 四名单语义（黑名单永远赢；群白名单空=群面关闭，
    绝不猜群）。分层保持：scope 仍是礼仪开关（private/group/all 决定「想不
    想在哪说」），名单是安全门（决定「哪里允许说」），两门串联、互不取代；
    ``bot_tts_auto_reply_always``（跳概率门）压不过安全门。私聊面不吃群名单
    （M-17 只收群面）。

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
    # M-17 安全维度：群面接入中央四名单（黑名单永远赢；白名单空=群面关闭）。
    group_id = str(getattr(message, "group_id", "") or "").strip()
    if group_id and not explicit_allowed_for_session("group", group_id, config):
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


def _skip_voice_with_tags(result: CapabilityResult, *extra: str) -> CapabilityResult:
    """配音增益放弃时的机读留痕（M-14）：文字回复零变化，只追加 audit_tags。

    本域 logger 不在生产日志树上（``_issue`` docstring 同因），放弃原因只写
    logger.info 等于丢失；挂到 audit_tags 后中央审计面可直接查「为什么这句
    没配音」。
    """
    return result.model_copy(
        update={"audit_tags": [*result.audit_tags, "tts", "auto_reply_skipped", *extra]}
    )


def synthesize_autodub(
    config: Any, speech: str, *, synth: Callable[..., tuple[Any, str]] | None = None
) -> tuple[str, dict[str, Any] | str]:
    """自动配音「合成这一步」的单一真身（VOICE-V12，收编中央调度层第二出站腿）。

    入参=**已过内容门与硬顶的干净文本**（取文/政策/硬顶是层 1 的「该不该配」判定，
    留在 hook；本函数只做「一句话→一段可交付音频」这个产出步，被中央 handler 调用）。

    与命令路（``build_tts_capability`` 合成段）和旧包装（``maybe_attach_voice`` 合成段）
    **逐字节同构**：preset→params→选 ref→确定性 seed→合成→落盘字节摘要。

    ``synth``：合成原语注入缝，缺省=本模块 ``synthesize``（现网逐字节等价）。调用方
    （层 1 hook 经中央 context）交来的合成原语与缺省同一真身；注入缝的存在只为让
    「合成这一步」的可测试性落在**产出步的 seam 上**（离线单测注入确定性替身），
    不改变生产取数、不新增第二路引擎。字节顶/落盘配额仍全在 ``synthesize`` 真身。

    返回 ``(code, payload)``：

    - ``"ok"``     → payload=``{audio_file, review_text, content_sha256?, preset_id, seed}``
      （``content_sha256`` 算不出即缺省，诚实降级，与出站收口 canonicalize 咬合）；
    - ``"no_ref"`` → payload=""（确定性失败：无可用参考音频，对应 tts_no_ref_audio 码族）；
    - ``"failed"`` → payload=失败原因串（供 ``_failure_issue`` 前缀表精确分类）。

    失败原因不在这里造 kind——只把合成原语的原样原因串交回，层 2 分类与层 1
    挂 issue 各在其位（T58 §2：失败原因可见处才谈得上分类）。
    """
    synth_fn = synth if synth is not None else synthesize
    preset = _resolve_preset(config)
    params = _build_params(config)
    ref = pick_ref_audio(
        getattr(config, "bot_tts_ref_audios", []) or [],
        base_dir=str(getattr(config, "bot_tts_gptsovits_dir", "") or ""),
    )
    if ref is None:
        return "no_ref", ""
    speech_seed = derive_seed(
        speech,
        ref,
        params,
        api_url=str(getattr(config, "bot_tts_api_url", "") or ""),
        preset_id=preset.preset_id,
    )
    path, reason = synth_fn(
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
        max_audio_bytes=resolve_max_audio_bytes(config),
        quota_max_bytes=int(getattr(config, "bot_tts_cache_max_bytes", 0) or 0),
        quota_max_age_days=int(getattr(config, "bot_tts_cache_max_age_days", 0) or 0),
    )
    if path is None:
        return "failed", reason or "合成失败"
    data: dict[str, Any] = {
        "audio_file": str(path),
        "review_text": speech,
        "preset_id": preset.preset_id,
        "seed": speech_seed,
    }
    content_digest = _content_digest_for(path)
    if content_digest is not None:
        data["content_sha256"] = content_digest
    return "ok", data


def maybe_attach_voice(
    message: IncomingMessage,
    result: CapabilityResult,
    *,
    config: Any,
) -> CapabilityResult:
    """给 chat 结果附加语音（供 ``__init__`` 的 chat 能力包装层调用）。

    门链见 ``should_voice_reply``：总开关 / 自动配音开关 / 未带音频 /
    出自 bot.chat / 会话范围（礼仪维度）/ 群面中央名单（安全维度，M-17）/
    概率门。任何失败都原样放弃配音——配音是增益，绝不能影响文字回复；
    放弃路径一律挂机读留痕（``auto_reply_skipped`` + 原因标签，M-14）。
    """
    if not should_voice_reply(config, message, result):
        return result
    try:
        # 0=不限（M-35 语义统一：不再 or-抬回 120）；「不限≠无界」，下方过硬顶。
        max_chars = int(getattr(config, "bot_tts_auto_reply_max_chars", 0) or 0)
        lossy_audit: dict[str, Any] = {}
        speech, blocked = resolve_speech_text(
            config, message, result.body or result.summary or "", max_chars=max_chars,
            audit=lossy_audit,
        )
        if blocked:
            # 配音是增益：被内容门拦下就只丢增益，文字回复原样出站。
            logger.info("tts auto reply blocked by policy: category=%s", blocked)
            return _skip_voice_with_tags(result, "blocked_by_policy")
        if not speech:
            return _skip_voice_with_tags(
                result, "empty_after_clean", *lossy_transform_tags(lossy_audit)
            )
        # 文本硬顶（G2-R3）：自动路超顶=静默放弃增益（文字回复原样出站），
        # 同样不拆条；留痕挂 audit_tags（配音增益面不挂 issue 防刷屏）。
        hard_cap = resolve_hard_max_chars(config)
        if len(speech) > hard_cap:
            logger.info(
                "tts auto reply skipped: over_hard_cap len=%d cap=%d", len(speech), hard_cap
            )
            return _skip_voice_with_tags(
                result,
                "over_hard_cap",
                f"len={len(speech)}",
                f"cap={hard_cap}",
                *lossy_transform_tags(lossy_audit),
            )
        preset = _resolve_preset(config)
        params = _build_params(config)
        ref = pick_ref_audio(
            getattr(config, "bot_tts_ref_audios", []) or [],
            base_dir=str(getattr(config, "bot_tts_gptsovits_dir", "") or ""),
        )
        if ref is None:
            return _skip_voice_with_tags(result, "no_ref_audio")
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
            max_audio_bytes=resolve_max_audio_bytes(config),
            quota_max_bytes=int(getattr(config, "bot_tts_cache_max_bytes", 0) or 0),
            quota_max_age_days=int(getattr(config, "bot_tts_cache_max_age_days", 0) or 0),
        )
        if path is None:
            logger.info("tts auto reply skipped: %s", reason)
            return _skip_voice_with_tags(result, _failure_kind_tag(reason))
        # M-64/S2：与命令路同一摘要语义（落盘字节真值；算不出即缺省）。
        # U-107-C/T144：audit_tags 同步记 audio_sha256=<[:16]>（观测面，与
        # 命令路同位——seed= 锚后；算不出即不带 tag，诚实降级同口径）。
        audio_part: dict[str, Any] = {"file": str(path), "review_text": speech}
        content_digest = _content_digest_for(path)
        if content_digest is not None:
            audio_part["content_sha256"] = content_digest
        return result.model_copy(
            update={
                "audio": [audio_part],
                "audit_tags": [
                    *result.audit_tags,
                    "tts",
                    "auto_reply",
                    f"preset={preset.preset_id}",
                    f"seed={speech_seed}",
                    *(
                        [f"audio_sha256={content_digest[:16]}"]
                        if content_digest is not None
                        else []
                    ),
                    *lossy_transform_tags(lossy_audit),
                ],
            }
        )
    except Exception as exc:  # noqa: BLE001 - 配音增益绝不阻断文字回复。
        logger.info("tts auto reply failed: %s", exc)
        return result
