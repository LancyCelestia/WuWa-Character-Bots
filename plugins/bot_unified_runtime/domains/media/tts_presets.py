"""中央语音预设表（bot.tts，Wave G G-2 契约层，T54 规格 §2）。

**地位**：合成参数的**唯一缺省源**（M-43/M-75/M-76 的共同载体）。
``BOT_TTS_*`` 数值族保留为管理员覆盖（覆盖优先级：env 显式值 > preset）；
config 缺省值与 v1 预设值相等（现状收编），故 v1 零行为变更。

- v1 ``shorekeeper`` 预设 = 2026-09-20 时点（T57 施工基线 d6801ab）生产出门值收编；
- 引擎域值逐字抄 ``.superpowers/sdd/2026-09-19-unify-audit/report-T53.md``
  §2 WebUI 滑杆全表（引擎 API 面零校验 ⇒ 域闸责任全在 bot 侧；**禁自造域值**）；
- ``split_bucket=False``：M-76 死意图显式化——引擎在 ``speed_factor≠1.0`` 时
  无条件自动关闭并打日志（引擎 TTS.py:1097-1099，转引 T53），生产恒 0.85，
  旧硬编码 ``True`` 每次都被否决；预设显式 False 与实况对齐（出门行为字节级不变）；
- ``seed`` 不直配：由 ``seed_policy`` 列派生（G2-R3/U-25 裁定=cache_key 派生）；
- ``lexicon``：读法词典（M-77，T104 转正=常见符号/单位最小集，条级可关断；
  应用点=清洗侧管线内打码后截断前；人名/专名读法挂 U-02 另波）；
- ``rationale``：参数出处链载体（M-75——谁定/凭什么/何时听过，落盘可考）。

纯数据模块：只依赖标准库，不 import 包内任何模块（config.py 的枚举白名单
``TTS_PRESET_IDS`` 与本表键集的一致性由 tests/test_tts_presets.py 导入门锁死，
避免引入 config → domains 的反向依赖）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# 引擎域值（report-T53.md §2 机器可读 JSON 直抄；G2-R3 解禁后为定稿值）
# ---------------------------------------------------------------------------

# 键 → (min, max)。batch_threshold 引擎/WebUI 均无滑杆（T53: no_ui_slider），
# 不入域值表、只做类型闸；streaming_mode/parallel_infer 是协议开关非数值域。
ENGINE_PARAM_DOMAINS: dict[str, tuple[float, float]] = {
    "top_k": (1, 100),  # api_v2.py:161; inference_webui_fast.py:388
    "top_p": (0.0, 1.0),  # api_v2.py:162; inference_webui_fast.py:389
    "temperature": (0.0, 1.0),  # api_v2.py:163; inference_webui_fast.py:391
    "speed_factor": (0.6, 1.65),  # api_v2.py:168; inference_webui_fast.py:384
    "repetition_penalty": (0.0, 2.0),  # api_v2.py:174; inference_webui_fast.py:394
    "fragment_interval": (0.01, 1.0),  # api_v2.py:169; inference_webui_fast.py:381
    "batch_size": (1, 200),  # api_v2.py:165; inference_webui_fast.py:374
}

# text_lang 合法域（引擎 v2ProPlus 实集，TTS.py:275-277 转引 T53 §6）；
# bot 出门前一律 casefold（POST 入口引擎用原值断言，"ZH" 必 400）。
TEXT_LANG_VALUES: frozenset[str] = frozenset(
    {"auto", "auto_yue", "en", "zh", "ja", "yue", "ko", "all_zh", "all_ja", "all_yue", "all_ko"}
)

# text_split_method 合法域（引擎注册实集共 6 个，T53 §6）。
TEXT_SPLIT_METHODS: frozenset[str] = frozenset(
    {"cut0", "cut1", "cut2", "cut3", "cut4", "cut5"}
)

# ---------------------------------------------------------------------------
# 中央硬顶常量（G2-R3：0=禁配无界时取内置常量；与 config 缺省同值，
# 双处数字由 tests/test_tts_presets.py::test_fallback_constants_match_config_defaults 锁死）
# ---------------------------------------------------------------------------

HARD_MAX_CHARS_FALLBACK = 2000
"""文本硬顶内置常量：正常流量 4~10 倍余量的安全顶（T54 §3.2 判据）。"""

MAX_AUDIO_BYTES_FALLBACK = 8 * 1024 * 1024
"""产物字节顶内置常量：8 MiB≈131s（v2ProPlus 32000Hz/16bit/单声道=64,000 B/s 恒定，
T53 §4.5），覆盖现行 200 字档（≈82s≈5.3MB）留 50% 余量——G2-R3 裁定值。"""


# ---------------------------------------------------------------------------
# 预设表
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TtsPreset:
    """一条语音预设：引擎参数 + seed 策略 + 读法词典 + 参数出处。"""

    preset_id: str
    """预设标识（config ``bot_tts_preset`` 的合法取值，进缓存键）。"""

    params: dict[str, object]
    """引擎请求参数（19 键请求体中随预设走的部分；text/ref/seed 逐请求另拼）。"""

    seed_policy: str = "derived"
    """``derived``=cache_key 派生确定性 seed（v1 唯一入册值，G2-R3/U-25）。"""

    lexicon: dict[str, str] = field(default_factory=dict)
    """读法词典（键=原文精确串，值=替换读法；应用点=清洗侧末端，不入引擎）。"""

    rationale: dict[str, str] = field(default_factory=dict)
    """每参数的出处/依据（M-75：参数决策的落盘载体）。"""


_SHOREKEEPER_RATIONALE: dict[str, str] = {
    "text_lang": "中文人格主体（T25 §1#6）；混读行为零约定（M-77，待 U-02 听辨）",
    "text_split_method": "抄引擎缺省 cut5，「有意跟随缺省」自此显式化（T25 §1#5）",
    "media_type": "NapCat/SnowLuma 链按 wav 契约；换格式=字节顶换算失效须重裁（T54 §2.2）",
    "top_k": "引擎缺省+WebUI value=15，全表唯二 A 类出处（T25 §1#3）",
    "top_p": "引擎缺省+WebUI value=1（T25 §1#4）",
    "temperature": "现状收编；原注释指向不存在的「守岸人预设卡」（C 类）⇒ 本列即唯一交代，待 U-02 听辨改判",
    "speed_factor": "现状收编；比引擎缺省慢 15%，听辨依据不存在 ⇒ 待 U-02 听辨（T25 §1#1）",
    "batch_size": "有意跟随引擎缺省 1（显式化，M-76；v2ProPlus 逐段合成语义）",
    "batch_threshold": "有意跟随引擎缺省 0.75（显式化，M-76）",
    "split_bucket": "死意图消除：引擎 speed≠1 时无条件自动关闭（TTS.py:1097-1099 转引 T53）⇒ 显式 False",
    "fragment_interval": "现状收编 0.3；每段尾补静音含末段直接进时长账，动它=时长账重算（挂 U-02）",
    "repetition_penalty": "有意跟随引擎缺省 1.35（显式化，M-76）",
    "parallel_infer": "维持 True：与引擎 workers=1 排队语义组合后=HTTP 层串行（T54 §1.1）",
}


# ---------------------------------------------------------------------------
# 读法词典（M-77 转正，T104）：常见符号/单位最小集
# ---------------------------------------------------------------------------

# 最小集口径：只收**替换后语序天然正确**的高频符号/单位（键=原文精确串，
# 值=替换读法）；不做全量读音规范——人名/专名/多音字读法挂 U-02 听辨另波。
# 每条读法都按「数字+符号」典型形态推敲过语序（25℃→25摄氏度、3×4→3乘4、
# 6÷2→6除以2、±5→正负5、45°→45度、A＆B→A和B）。
SHOREKEEPER_LEXICON: dict[str, str] = {
    "℃": "摄氏度",
    "℉": "华氏度",
    "＆": "和",
    "&": "和",
    "±": "正负",
    "×": "乘",
    "÷": "除以",
    "°": "度",
    # —— 以下两条**在表内但默认关断**（LEXICON_DISABLED）——
    # 「%」：汉语语序「百分之」前置（50%→百分之五十），精确串替换只能后缀
    # （→「50百分之」乱语序），反成回归 ⇒ 关断待正则级规则（应用机制不动）。
    "%": "百分之",
    # 「～」：双语义（「3～5天」范围 vs「好呀～」语气尾），精确串替换分不了
    # 语境 ⇒ 关断（引擎当前怎么念挂 U-02 听辨）。
    "～": "到",
}

# 条级关断表（M-77 逐条可关断）：键=词典条目原文，命中即不进生效词典。
# 收录于此 = 该条目的读法暂不启用，但读法本身留在 SHOREKEEPER_LEXICON 备查，
# 取消关断只需从本集合移除键（不动词典本体）。
LEXICON_DISABLED: frozenset[str] = frozenset({"%", "～"})


def effective_lexicon(lexicon: dict[str, str] | None) -> dict[str, str]:
    """应用条级关断后的**生效词典**（语音侧应用点只消费本函数出参）。"""
    return {key: reading for key, reading in (lexicon or {}).items() if key not in LEXICON_DISABLED}


SHOREKEEPER_PRESET = TtsPreset(
    preset_id="shorekeeper",
    params={
        "text_lang": "zh",
        "text_split_method": "cut5",
        "media_type": "wav",
        "top_k": 15,
        "top_p": 1.0,
        "temperature": 0.9,
        "speed_factor": 0.85,
        # —— M-76 八硬编码收编（T25 口径 8 键；seed 经 seed_policy 另派生）——
        "batch_size": 1,
        "batch_threshold": 0.75,
        "split_bucket": False,
        "fragment_interval": 0.3,
        "repetition_penalty": 1.35,
        "parallel_infer": True,
    },
    seed_policy="derived",
    lexicon=SHOREKEEPER_LEXICON,
    rationale=_SHOREKEEPER_RATIONALE,
)

PRESET_REGISTRY: dict[str, TtsPreset] = {
    "shorekeeper": SHOREKEEPER_PRESET,
}

DEFAULT_PRESET_ID = "shorekeeper"

# 缓存键空间代号（T54 §5）：换代自增，旧键整体变冷。
# v1 = T57 现状键（api_url+ref_fp+参数快照）；v2 = 收编 preset 身份 + identity_version 段。
IDENTITY_VERSION = 2

# seed 派生规则版本（进缓存键 preimage：规则变更=换键，防跨规则键撞）。
SEED_RULE_VERSION = "seed-derived-v1"


def resolve_preset(preset_id: str) -> TtsPreset:
    """按 id 取预设；未知 id 抛 KeyError（config 装载期已枚举校验，此处为纵深）。"""
    return PRESET_REGISTRY[preset_id]
