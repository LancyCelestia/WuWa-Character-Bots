"""需求 8 补缺口——对话自动配音「概率门」的数值锁（席位 S-T-TTS-NUM，2026-09-26）。

⚠ 先读这一段（否则本件会被读成「线上正在按 10% 配音」）
    现网生产 ``.env`` 里 ``BOT_TTS_AUTO_REPLY_ENABLED=false``（.env:452），而
    ``should_voice_reply`` 的第二道门（真身 ``tts.py:1481``）在它之前就把整条链
    返回 False ⇒ **概率门今天一次都不会被求值，10% 今天不生效**。
    本件钉的是「这道门一旦开起来，开的是几分」这个数，以及「这个数只允许住在一处」，
    不证明现网在配音。要让概率真生效，她需要动的唯一一枚键是
    ``BOT_TTS_AUTO_REPLY_ENABLED=true``（装配期读，重启生效）；
    ``BOT_TTS_VOICE_HOOK_ENABLED`` 只选腿（现网 .env 已为 true=新链），两条腿
    读的都是同一个概率，开不开它不改变命中率。

缺口从哪来（只读席 S-R-VERIFY5 实跑发现，本席复核两处成立）
    需求 8「TTS 10% 概率 + 原文本+音频」里，「原文本+音频」那半边有真锁
    （``tests/test_tts.py`` 断言 audio dict 全等 + ``body==念出文本``）；
    「10%」这个数在全仓**没有任何数字断言**：
      * ``tests/test_tts.py::test_should_voice_reply_is_deterministic_and_sparse_by_default``
        只锁粗边界 ``0 < voiced < total * 0.25``，且夹具自喂常量 0.05（与生产缺省无关），
        连「缺省是多少」都没说；
      * 数值本身靠四处互证却没有比对门：``config.py:474`` 的 ``Field(default=0.10)``、
        ``.env.example:909``、生产 ``.env:456``、``echo.py:2139`` 的散文「默认有 10%」
        （及其投影 ``docs/command-catalog.md:2382``）——谁把缺省改成 1.0 全套测试照样绿。

本件补的三把锁
    ① **单一事实源在位**：数字只住在 ``config.py`` 那一枚字段的缺省上；声明值与
       ``Config()`` 实装值必须相等；全生产面读这一枚键的 getattr 点恰好一处；字段在
       ``config.py`` 里恰好定义一次（防「同名重复定义静默覆盖」——台账 #53 真咬过）；
       判据链（``_resolve_probability``/``should_voice_reply``）内不许出现等于该缺省的
       数字字面量（= 手抄第二份必红）；**本测试件自身**也不许出现等于该缺省的浮点字面量。
    2️⃣ **数值断言（跟着配置动）**：确定性哈希 ⇒ 语料固定 ⇒ 命中数可复算。命中率与
       「从字段缺省派生出来的期望值」比对（5σ 二项容差，不是把某个百分数抄进测试）；
       再沿两条互补的路各验一次——
         * 派生梯子（缺省的 1/4、1/2、3/4、1）：证明**缺省怎么改，门就怎么跟**；
         * 值域三档 + 中点档（``ge`` 下界 / ``ge``与``le`` 的中点 / 数值源 / ``le`` 上界，
           全部从字段反射派生，今日读数即 0.0 / 0.5 / 缺省 / 1.0）：
           证明门链的三条分支（恒不配音／真走抽签／恒配音）都被走到，且源档严格夹在中间、
           与中点档按配置值同增；四档各自再叠「配音闸关」都必须是 0 命中
           （概率压不过上游闸＝今天现网的实况）。
    3️⃣ **四处口径一致**：字段缺省 ↔ .env.example ↔ 生产 .env（存在才比）↔ echo 散文
       ↔ 生成的命令目录，任一方单方漂移必红（「一处变更处处跟随」）。
    外加**现网实况锁**：用生产同构装载器读出真在跑的 Config，断言「闸关 ⇒ 命中必须为 0；
    闸开 ⇒ 命中率必须落在那枚已配置值的容差带内」——两态都由装载结果派生，她 flip 键之后
    本锁自动换成后一半判据，不需要改这个文件。

牙齿（``test_teeth_*``）逐条自证本件不是恒过：改缺省、改口径、架空抽签三条路各钉一发。
全部离线：零网络、零引擎（127.0.0.1:9880 一次都不碰）、零进程、只读文件。
"""

from __future__ import annotations

import ast
import math
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.domains.media.capabilities import tts as tts_mod
from plugins.bot_unified_runtime.domains.media.capabilities.tts import (
    should_voice_reply,
)

# ---------------------------------------------------------------------------
# 坐标（报告 §a 的完整链路，全部现算核对，非照抄简报）
# ---------------------------------------------------------------------------
#   数值源（唯一）      plugins/bot_unified_runtime/config.py:474
#       bot_tts_auto_reply_probability: float = Field(default=0.10, ge=0.0, le=1.0)
#   能力层读点          domains/media/capabilities/tts.py:1495-1497
#       probability = _resolve_probability(getattr(config, "bot_tts_auto_reply_probability", 0.0))
#   0/1 短路            tts.py:1498-1501
#   抽签（seed/bucket）  tts.py:1502-1506（seed = session_id:message_id|request_id，
#                       sha256 前 8 位 hex → int → % 10000）
#   ★ 决定这一条要不要配音的那一行： tts.py:1507  return bucket < probability * 10000
#   三条消费腿（同一个谓词，无第二份抽签）：
#       旧包装腿  根 __init__.py:359 与 tts.py:1651（maybe_attach_voice）
#       hook 腿   domains/media/voice_enricher.py:136（第 0 道 = :131 hook 键）
#       中央三形  domains/media/tts/result_transform.py:264（第 0 道 = :258 hook 键）
#   概率之前的门（tts.py:1479-1494）：总闸 / 自动配音闸 / 已带音频 / 出自 bot.chat /
#       scope（礼仪）/ 群面中央名单（安全，M-17）/ always 旁路。

PROBABILITY_FIELD = "bot_tts_auto_reply_probability"
PROBABILITY_ENV_KEY = "BOT_TTS_AUTO_REPLY_PROBABILITY"
CONFIG_PATH = PROJECT_ROOT / "plugins/bot_unified_runtime/config.py"
TTS_PATH = PROJECT_ROOT / "plugins/bot_unified_runtime/domains/media/capabilities/tts.py"
ENV_EXAMPLE_PATH = PROJECT_ROOT / ".env.example"
ENV_PATH = PROJECT_ROOT / ".env"
ECHO_PATH = PROJECT_ROOT / "plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py"
COMMAND_CATALOG_PATH = PROJECT_ROOT / "docs/command-catalog.md"
PLUGINS_ROOT = PROJECT_ROOT / "plugins"

#: 抽签桶数与容差 σ 倍数——结构性整数，不是概率值（本件任何断言都不抄百分数）。
_BUCKET_SPACE = 10000
_SIGMA = 5


# ---------------------------------------------------------------------------
# 数值源与四处口径
# ---------------------------------------------------------------------------


def declared_default() -> float:
    """唯一事实源：``config.py`` 上那枚字段的缺省（从模型反射，绝不写死）。"""
    field = Config.model_fields[PROBABILITY_FIELD]
    assert field.default is not None, f"{PROBABILITY_FIELD} 没有标量缺省，判据需重新定位"
    return float(field.default)


def domain_bounds() -> tuple[float, float]:
    """该字段的合法值域两端（``Field(ge=…, le=…)`` 反射而得，不是写死的 0 与 1）。

    有了这两枚，「恒不配音 / 恒配音」两条短路档也能按配置派生，本件就一处数字都不抄。
    """
    metadata = Config.model_fields[PROBABILITY_FIELD].metadata
    lower = [float(item.ge) for item in metadata if getattr(item, "ge", None) is not None]
    upper = [float(item.le) for item in metadata if getattr(item, "le", None) is not None]
    assert lower and upper, "该字段的值域约束（ge/le）不见了 ⇒ 判据需重新定位"
    return min(lower), max(upper)


def effective_default() -> float:
    """裸 ``Config()`` 实装值（防「Field 写着 X、校验器另给一套」的二真身）。"""
    return float(Config().bot_tts_auto_reply_probability)


def _basis_points(value: float) -> int:
    """把概率折成整数基点（万分之一）比对，避免浮点等值与 ε 字面量。"""
    return round(float(value) * _BUCKET_SPACE)


def _env_value(path: Path) -> float | None:
    """读一枚 env 文件里的 ``KEY=value``（行内 # 注释不参与解析）；无此行返回 None。"""
    if not path.exists():
        return None
    prefix = f"{PROBABILITY_ENV_KEY}="
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        text = line.strip()
        if not text.startswith(prefix):
            continue
        raw = text[len(prefix) :].split("#")[0].strip()
        if raw:
            return float(raw)
    return None


def _prose_value(path: Path) -> float | None:
    """读散文口径：必须点名这枚环境变量，且句子里带「N%」。

    ``echo.py`` 的 ``_HELP_ENTRIES`` 是唯一真身，``docs/command-catalog.md`` 是它的
    生成投影——两都比，投影漂移也算「一处变更没处处跟随」。
    """
    if not path.exists():
        return None
    pattern = re.compile(r"(\d+(?:\.\d+)?)\s*%")
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if PROBABILITY_ENV_KEY in line and "配音概率" in line:
            match = pattern.search(line)
            if match:
                return float(match.group(1)) / 100.0
    return None


def probability_surfaces() -> dict[str, float]:
    """除数值源之外的全部口径（存在才入册，缺席不算漂移但也不能假装看见）。"""
    surfaces: dict[str, float] = {}
    if ENV_EXAMPLE_PATH.exists():
        value = _env_value(ENV_EXAMPLE_PATH)
        if value is not None:
            surfaces[".env.example"] = value
    if ENV_PATH.exists():
        value = _env_value(ENV_PATH)
        if value is not None:
            surfaces[".env（生产）"] = value
    for path, label in ((ECHO_PATH, "echo.py 帮助散文"), (COMMAND_CATALOG_PATH, "command-catalog 投影")):
        value = _prose_value(path)
        if value is not None:
            surfaces[label] = value
    return surfaces


def drift_against(expected: float, surfaces: dict[str, float] | None = None) -> list[str]:
    """返回「与数值源不一致的口径」清单；空表即四处同数。"""
    target = _basis_points(expected)
    chosen = probability_surfaces() if surfaces is None else surfaces
    return [
        f"{name}={value}（基点 {points}）≠ 数值源 {expected}（基点 {target}）"
        for name, value in sorted(chosen.items())
        for points in (_basis_points(value),)
        if points != target
    ]


# ---------------------------------------------------------------------------
# 判据夹具（确定性：门链用 sha256 哈希，无 random ⇒ 语料固定即结果固定）
# ---------------------------------------------------------------------------


def _lottery_config(probability: Any = None, **overrides: Any) -> SimpleNamespace:
    """喂给 ``should_voice_reply`` 的最小配置对象（能力层只走 getattr）。

    ``probability`` 为 None 时**取数值源本身**——本件的每一条数值断言因此都跟着缺省走。
    """
    base: dict[str, Any] = {
        "bot_tts_enabled": True,
        "bot_tts_auto_reply_enabled": True,
        "bot_tts_auto_reply_scope": "private",
        "bot_tts_auto_reply_probability": declared_default() if probability is None else probability,
        "bot_tts_auto_reply_always": False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _chat_result() -> CapabilityResult:
    return CapabilityResult(request_id="req-lock", capability_id="bot.chat", kind="text", body="潮汐很安静。")


def _corpus(size: int) -> list[IncomingMessage]:
    """确定性语料：会话号与消息号都按序号派生，跨 7 个会话轮换防单会话偏置。

    种子刻意只是「计数 + 取模」，没有任何一枚按命中率调过的值——本件不许挑样本。
    """
    messages: list[IncomingMessage] = []
    for index in range(size):
        sender = str(1000 + (index % 7))
        messages.append(
            IncomingMessage(
                platform="qq",
                adapter="onebot11",
                bot_id="10000",
                session_id=f"private:{sender}",
                session_type=SessionType.PRIVATE,
                sender_id=sender,
                plain_text="在吗",
                message_id=f"m{index}",
            )
        )
    return messages


@pytest.fixture(scope="module")
def corpus() -> list[IncomingMessage]:
    return _corpus(20000)


def _hits(config: Any, messages: list[IncomingMessage]) -> int:
    return sum(1 for message in messages if should_voice_reply(config, message, _chat_result()))


def _tolerance_points(probability: float, size: int) -> int:
    """5σ 二项容差（整数基点）：样本越大带越窄，容差本身由配置值派生。"""
    p = min(max(probability, 0.0), 1.0)
    sigma = math.sqrt(p * (1.0 - p) / size) * _BUCKET_SPACE
    return math.ceil(_SIGMA * sigma) + 1


# ---------------------------------------------------------------------------
# ① 单一事实源在位
# ---------------------------------------------------------------------------


def _single_source_agreement(declared: float, effective: float) -> list[str]:
    """「数值源」与「实装值」是否同一个数；空表即一致。"""
    declared_points = _basis_points(declared)
    effective_points = _basis_points(effective)
    if declared_points == effective_points:
        return []
    return [
        f"字段缺省 {declared}（基点 {declared_points}）≠ 裸 Config() 实装值 {effective}（基点 {effective_points}）"
    ]


def test_probability_has_a_single_numeric_source() -> None:
    """声明值 == ``Config()`` 实装值 == 门链取值，三者必须同一个数（无第二真身）。"""
    declared = declared_default()
    report = _single_source_agreement(declared, effective_default())
    assert not report, (
        "；".join(report) + "⇒ 有校验器/别名层在背后改这个数，判据得重新定位"
    )
    # 门链从配置对象取的数，与数值源同值 ⇒ 「读的就是这一枚」。
    config = _lottery_config()
    assert _basis_points(
        float(getattr(config, PROBABILITY_FIELD))
    ) == _basis_points(declared)


def test_probability_is_a_real_lottery_not_a_constant() -> None:
    """产品裁定是一「概率」而非全开/全关：0 < 缺省 < 1。

    这一条不写死任何百分数，却正好把「谁改成 0 或 1 都不红」那个洞堵上——
    注毒缺省=0 或 1 时它必红（见 test_teeth_default_drift_is_red）。
    """
    declared = declared_default()
    assert 0 < declared < 1, (
        f"配音概率缺省被改成 {declared}：概率门退化成恒不配音/恒配音，"
        "需求 8 的「按概率抽签」语义已丢失"
    )


def test_probability_field_is_defined_exactly_once_in_config() -> None:
    """``config.py`` 里这枚字段恰好定义一次（同名重复定义会被 pydantic 静默覆盖）。"""
    source = CONFIG_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    counts: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            counts.append(
                sum(
                    1
                    for stmt in node.body
                    if isinstance(stmt, ast.AnnAssign)
                    and isinstance(stmt.target, ast.Name)
                    and stmt.target.id == PROBABILITY_FIELD
                )
            )
    total = sum(counts)
    assert total == 1, f"{PROBABILITY_FIELD} 在 config.py 的类体里出现 {total} 次（应为 1）⇒ 有第二份定义"
    assert "class Config" in source, "config.py 里找不到 Config 类，判据定位方式需更新"


def test_probability_is_read_at_exactly_one_production_site() -> None:
    """全生产面（plugins/）只有能力层那一处 getattr 读这枚键，且**总共只读一次**。

    在册表（``domains/core/capability_resource_ownership.py``）里出现键名是**归属声明**、
    不是取值，正则只认 ``getattr(config, "…")`` 这一形态故不会误计；除此之外任何第二读点
    都意味着第二通路。这里同时数**次数**而不只数**文件**——只比文件集合会漏掉
    「同一个文件里再抄一处 getattr」这种最省事的分叉写法。
    """
    reader_re = re.compile(
        r"getattr\(\s*config\s*,\s*[\"']" + re.escape(PROBABILITY_FIELD) + r"[\"']"
    )
    readers: list[str] = []
    occurrences = 0
    for path in PLUGINS_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        hits = reader_re.findall(path.read_text(encoding="utf-8", errors="replace"))
        if hits:
            readers.append(str(path.relative_to(PROJECT_ROOT)))
            occurrences += len(hits)
    assert readers == [
        str(TTS_PATH.relative_to(PROJECT_ROOT))
    ], f"概率读点不唯一（{readers}）⇒ 出现第二处取值，缺省改了不会处处跟随"
    assert occurrences == 1, (
        f"概率读点虽在同一文件（tts.py）内出现 {occurrences} 次（应为 1）"
        "⇒ 同一枚键被读了两遍，两处判据会各自漂移"
    )


def _is_a_copy_of(literal: object, declared: float) -> bool:
    """字面量是否等于数值源（排除 bool 与 0/1 两枚短路边界）。

    ``should_voice_reply`` 里的 ``0`` 与 ``1`` 是门链自身的"恒不配音/恒配音"短路值，
    不是概率的抄本；缺省一旦真的退化到它们，点名的是
    ``test_probability_is_a_real_lottery_not_a_constant``，不由本判据混报。
    """
    if not isinstance(literal, (int, float)) or isinstance(literal, bool):
        return False
    value = float(literal)
    if value in (0.0, 1.0):
        return False
    return _basis_points(value) == _basis_points(declared)


def test_probability_gate_carries_no_second_numeric_copy() -> None:
    """判据函数体内不许出现「等于数值源」的数字字面量（手抄第二份必红）。"""
    declared = declared_default()
    tree = ast.parse(TTS_PATH.read_text(encoding="utf-8"))
    wanted = {"should_voice_reply", "_resolve_probability"}
    offenders: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name not in wanted:
            continue
        for literal in ast.walk(node):
            if isinstance(literal, ast.Constant) and _is_a_copy_of(literal.value, declared):
                offenders.append(literal.lineno)
    assert not offenders, (
        f"tts.py 概率判据函数内出现与数值源同值的字面量（行 {offenders}）"
        "⇒ 数字被抄了第二份，改 config.py 缺省将只改一半"
    )


def test_this_lock_does_not_hardcode_the_probability() -> None:
    """自证：本测试件里没有等于数值源的浮点字面量（判据全走反射与派生）。

    期望值只从 ``declared_default()`` 与整数倍除（``/ 2``、``/ 4``、``* 3 / 4``）派生，
    所以「把某百分数抄进测试」这种写法一旦出现在本文件里就会被这条打死。
    """
    declared = declared_default()
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and _is_a_copy_of(node.value, declared):
            offenders.append(f"行 {node.lineno}: {node.value!r}")
    assert not offenders, f"本件把概率数字抄成了字面量（{offenders}）——违背「跟着配置动」"


# ---------------------------------------------------------------------------
# ② 数值断言（命中率跟着配置值走）
# ---------------------------------------------------------------------------


def test_probability_hit_rate_matches_the_configured_value(corpus: list[IncomingMessage]) -> None:
    """按数值源喂进配置，实测命中数必须落在 5σ 带内（钉住「这个数」，而非粗边界）。"""
    probability = declared_default()
    size = len(corpus)
    observed = _hits(_lottery_config(), corpus)
    expected_points = round(probability * _BUCKET_SPACE) * size // _BUCKET_SPACE
    band = _tolerance_points(probability, size)
    deviation = observed - expected_points
    assert abs(deviation) <= band, (
        f"概率命中率偏离配置值：实测 {observed}/{size}，期望 {expected_points}"
        f"（{probability}，容差 ±{band}）⇒ 概率值或抽签实现与数值源脱钩了"
    )
    assert 0 < observed < size, "概率门退化成恒不配音/恒配音（见 test_probability_is_a_real_lottery_not_a_constant）"


def test_probability_verdict_is_deterministic_per_message(
    corpus: list[IncomingMessage],
) -> None:
    """同一条消息两次判定必须同结论（确定性哈希，不许换成 random）。"""
    config = _lottery_config()
    chat = _chat_result()
    for message in corpus[:2000]:
        first = should_voice_reply(config, message, chat)
        assert should_voice_reply(config, message, chat) is first, "同一消息结论翻转 ⇒ 抽签不再是确定性的"


def test_probability_scales_linearly_with_configured_value(
    corpus: list[IncomingMessage],
) -> None:
    """沿「缺省的 1/4、1/2、3/4、1」派生梯子逐点复算：单调 + 每点都在 5σ 带内。

    这证明门真的按配置取值（不是把某个百分数烘进实现），且梯子由缺省派生，
    缺省怎么改梯子就跟着改——本件因此没有第二处数字。
    """
    base = declared_default()
    size = len(corpus)
    ladder = [base / 4, base / 2, base * 3 / 4, base]
    previous_hits = -1
    for probability in ladder:
        assert 0 < probability < 1, f"派生梯子越界（{probability}）——缺省值本身已不合法"
        observed = _hits(_lottery_config(probability), corpus)
        expected = round(probability * _BUCKET_SPACE) * size // _BUCKET_SPACE
        band = _tolerance_points(probability, size)
        assert abs(observed - expected) <= band, (
            f"配置概率 {probability} 时命中 {observed}/{size}，期望 {expected}±{band}"
        )
        assert observed >= previous_hits, "命中率随配置值不增 ⇒ 概率与门链不相关"
        previous_hits = observed


def test_probability_domain_bounds_and_source_value_are_three_distinct_tiers(
    corpus: list[IncomingMessage],
) -> None:
    """②的另一半：值域下界档 / 数值源档 / 值域上界档 ⇒ 三种不同结论。

    与上面那条「派生梯子」互补而不重复：梯子证「缺省怎么改门就怎么跟」（防烘进实现），
    本条把 ``should_voice_reply`` 的**三条分支**各走一遍——

      * 下界档（``ge`` 反射而来）⇒ 恒不配音（``tts.py:1498-1499`` 的 ``<= 0`` 短路）；
      * 上界档（``le`` 反射而来）⇒ 条条配音（``tts.py:1500-1501`` 的 ``>= 1`` 短路）；
      * 值域中点档（``(ge+le)/2``，今天即 0.5）⇒ 按中点比例走抽签（5σ 带内）；
      * 数值源档 ⇒ **真走抽签**（``tts.py:1502-1507``），且必须**严格夹在**两条短路之间，
        与中点档按配置值同增（不单调即红）。

    三档全是**灌进配置对象**的派生值（从字段值域与缺省反射），本件没有写死任何概率；
    上一版这里出现过绝对字面量（0.5/0.0/1.0），代价是：缺省一旦等于其中任一枚，本件的
    自我硬抄锁会误红，而「源档必须小于 0.5 档」会把缺省偷偷钉死在 0.5 以下——两处都
    是「把数字烘进判据」的同一个病，故改成按值域派生（中点档因此也走 ``ge``/``le`` 反射，
    今日读数正是简报要的 0.0 / 0.5 / 1.0 三档，只是算出来的、不是抄进来的）。

    另配两半对照，缺一条本条就成了半锁：
      * 三档各自再叠「自动配音闸关」（``bot_tts_auto_reply_enabled=False``，**就是今天
        现网的实况**，见模块头）⇒ 全部 0 命中 ⇒ 概率压不过上游闸；
      * 抽签档必须**既非 0 也非全开**（否则「夹在中间」是句空话）。
    """
    size = len(corpus)
    lower, upper = domain_bounds()
    assert _basis_points(lower) == 0 and _basis_points(upper) == _BUCKET_SPACE, (
        f"该字段的值域已不是「概率」形状（{lower}~{upper}）⇒ 本条的三档语义要重写"
    )
    #: 值域中点档：今天 = 0.5，但**由 ``ge``/``le`` 反射派生**，本件仍一处概率字面量都不抄。
    #: 简报要的「三档 0.5 / 0.0 / 1.0」在这里齐了——0.0=下界档、1.0=上界档、0.5=中点档，
    #: 差别只在中点是算出来的而不是写出来的（缺省哪天改成 0.5 时，本条只会少一档对照，
    #: 不会像写死 0.5 那样撞自我硬抄锁、也不会把缺省偷偷钉死在 0.5 以下）。
    midpoint = (lower + upper) / 2
    hits_floor = _hits(_lottery_config(lower), corpus)
    hits_ceil = _hits(_lottery_config(upper), corpus)
    hits_mid = _hits(_lottery_config(midpoint), corpus)
    hits_source = _hits(_lottery_config(), corpus)  # 不传值 ⇒ 取数值源本身

    assert hits_floor == 0, f"下界档却命中 {hits_floor}/{size} ⇒ 概率下界没能关掉配音"
    assert hits_ceil == size, f"上界档却只命中 {hits_ceil}/{size} ⇒ 概率上界没能放开配音"
    assert 0 < hits_source < size, "数值源档退化成恒开/恒关 ⇒ 抽签分支这一支没有被走到"
    assert hits_floor < hits_source < hits_ceil, (
        f"数值源档 {hits_source} 没有严格夹在下界档（{hits_floor}）与上界档（{hits_ceil}）之间"
        "⇒ 缺省值与门链取值的关系已经不是线性受控"
    )

    #: 中点档走的是抽签分支（既非 0 也非 1）⇒ 命中数必须按中点比例落带，且与源档**按值序同增**。
    band_mid = _tolerance_points(midpoint, size)
    expected_mid = round(midpoint * _BUCKET_SPACE) * size // _BUCKET_SPACE
    assert abs(hits_mid - expected_mid) <= band_mid, (
        f"值域中点档 {midpoint} 命中 {hits_mid}/{size}，期望 {expected_mid}±{band_mid}"
        "⇒ 抽签没有按配置值取比例"
    )
    assert hits_floor < hits_mid < hits_ceil, f"中点档 {hits_mid} 没有落在两条短路之间"
    if _basis_points(midpoint) != _basis_points(declared_default()):
        low_pair, high_pair = sorted(
            ((declared_default(), hits_source), (midpoint, hits_mid)), key=lambda item: item[0]
        )
        assert low_pair[1] < high_pair[1], (
            f"配置值 {low_pair[0]}→命中 {low_pair[1]} 却不少于 {high_pair[0]}→命中 {high_pair[1]}"
            "⇒ 命中率与配置值不单调，门链读的不是这枚配置"
        )

    for tier in (lower, midpoint, declared_default(), upper):
        gated_off = _lottery_config(tier, bot_tts_auto_reply_enabled=False)
        blocked = _hits(gated_off, corpus)
        assert blocked == 0, (
            f"配音闸关（现网实况）而概率档 {tier} 仍命中 {blocked}/{size}"
            "⇒ 上游闸被概率绕过，『今天 10% 不生效』这个判据也就不可信"
        )


def test_always_bypass_outweighs_the_lottery(corpus: list[IncomingMessage]) -> None:
    """``bot_tts_auto_reply_always`` 压过概率门（真机验收旁路）；旁路只在缺省概率上全开。

    对比项：同一批语料在缺省概率下**没有**全开（否则旁路这条锁就成了恒过）。
    """
    size = len(corpus)
    bypassed = _hits(_lottery_config(bot_tts_auto_reply_always=True), corpus)
    lottery = _hits(_lottery_config(), corpus)
    assert bypassed == size, f"always 旁路没生效：{bypassed}/{size}"
    assert lottery < size, "概率门本身已全开 ⇒ 上一条断言是恒过的假锁"


# ---------------------------------------------------------------------------
# ③ 门与闸关掉时命中必须为 0（含现网实况）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("veto", ["tts_master", "auto_reply", "already_audio", "not_chat", "scope"])
def test_veto_gates_never_voice_even_at_certainty(corpus: list[IncomingMessage], veto: str) -> None:
    """把概率拉到 1（抽签必中）再逐道关前面的门：任何一关没过就必须 0 命中。

    ``auto_reply`` 这一枚就是**今天现网的实况**（生产 .env 里为 false）⇒
    10% 今天一次都不被求值。
    """
    messages = corpus[:2000]
    chat = _chat_result()
    if veto == "tts_master":
        config = _lottery_config(1.0, bot_tts_enabled=False)
        hit = sum(1 for m in messages if should_voice_reply(config, m, chat))
    elif veto == "auto_reply":
        config = _lottery_config(1.0, bot_tts_auto_reply_enabled=False)
        hit = sum(1 for m in messages if should_voice_reply(config, m, chat))
    elif veto == "already_audio":
        config = _lottery_config(1.0)
        voiced = chat.model_copy(update={"audio": [{"file": "already.wav"}]})
        hit = sum(1 for m in messages if should_voice_reply(config, m, voiced))
    elif veto == "not_chat":
        config = _lottery_config(1.0)
        other = chat.model_copy(update={"capability_id": "bot.market"})
        hit = sum(1 for m in messages if should_voice_reply(config, m, other))
    else:  # scope：群消息撞 private 范围门
        config = _lottery_config(1.0, bot_tts_auto_reply_scope="private")
        group_messages = [
            m.model_copy(update={"group_id": "600600", "session_id": f"group:600600:{m.sender_id}"})
            for m in messages
        ]
        hit = sum(1 for m in group_messages if should_voice_reply(config, m, chat))
    assert hit == 0, f"门 {veto} 已关却仍命中 {hit} 次 ⇒ 概率绕过了门链"


def test_group_face_needs_the_central_safety_gate(corpus: list[IncomingMessage]) -> None:
    """群面：scope=all 但中央白名单为空 ⇒ 命中 0（安全门压过概率，绝不猜群）。

    反向对照：名单里点名该群后，同一批群消息按概率抽签（缺省概率下不必全中）。
    """
    size = 2000
    messages = corpus[:size]
    group_messages = [
        m.model_copy(update={"group_id": "600600", "session_id": f"group:600600:{m.sender_id}"})
        for m in messages
    ]
    chat = _chat_result()
    closed = _lottery_config(1.0, bot_tts_auto_reply_scope="all")
    assert should_voice_reply(closed, group_messages[0], chat) is False, "群面白名单空却放行"

    opened = _lottery_config(
        1.0,
        bot_tts_auto_reply_scope="all",
        bot_content_route_group_whitelist=["600600"],
        bot_content_route_group_blacklist=[],
    )
    assert all(should_voice_reply(opened, m, chat) for m in group_messages[:50]), "点名群应全过（概率=1）"

    banned = _lottery_config(
        1.0,
        bot_tts_auto_reply_scope="all",
        bot_content_route_group_whitelist=["600600"],
        bot_content_route_group_blacklist=["600600"],
    )
    assert should_voice_reply(banned, group_messages[0], chat) is False, "黑名单必须永远赢"


def test_production_effective_config_matches_its_own_configured_number() -> None:
    """现网实况锁（两态自适配）：用生产同构装载器读出真在跑的 Config，判其行为。

    闸关（今天：``BOT_TTS_AUTO_REPLY_ENABLED=false``）⇒ 整批语料必须 0 命中，
    这就是「10% 今天不生效」的可复跑证据；
    闸开 ⇒ 命中率必须落在那枚已配置值的 5σ 带内。
    她 flip 键之后本条自动换成后一半判据，不需要改这个文件。
    """
    if not ENV_PATH.exists():
        pytest.skip("本机无 .env（生产装载判据只在本部署有意义）")
    from scripts.load_runtime_config import load_runtime_config

    config = load_runtime_config(required=False)
    messages = _corpus(20000)
    chat = _chat_result()
    enabled = bool(config.bot_tts_enabled) and bool(config.bot_tts_auto_reply_enabled)
    if not enabled:
        hits = sum(1 for m in messages if should_voice_reply(config, m, chat))
        assert hits == 0, (
            f"现网配音闸关（bot_tts_enabled={config.bot_tts_enabled}, "
            f"bot_tts_auto_reply_enabled={config.bot_tts_auto_reply_enabled}）却命中 {hits} 次"
        )
        return
    if bool(config.bot_tts_auto_reply_always):
        assert all(should_voice_reply(config, m, chat) for m in messages), "always=true 应条条配音"
        return
    probability = float(config.bot_tts_auto_reply_probability)
    hits = sum(1 for m in messages if should_voice_reply(config, m, chat))
    expected = round(probability * _BUCKET_SPACE) * len(messages) // _BUCKET_SPACE
    band = _tolerance_points(probability, len(messages))
    assert abs(hits - expected) <= band, (
        f"现网配置概率 {probability} 下命中 {hits}/{len(messages)}，期望 {expected}±{band}"
    )


# ---------------------------------------------------------------------------
# ③' 四处口径一致
# ---------------------------------------------------------------------------


def test_all_probabilities_surfaces_agree_with_the_single_source() -> None:
    """字段缺省 ↔ .env.example ↔ .env ↔ echo 散文 ↔ 命令目录投影，必须同一个数。

    这条就是「谁把缺省改成一都不红」的正解：缺省单方漂移 ⇒ 各口径仍在报旧数 ⇒ 红。
    生产 ``.env`` 是**本机 gitignored** 文件，缺席不入册；在位则一并比（config.py 的
    ⚠ 注释自己就承认「那一行不改则线上仍是旧值」——那正是本条要拦的事）。
    """
    declared = declared_default()
    surfaces = probability_surfaces()
    assert surfaces, "一处口径都没找到 ⇒ 判据定位失效，别让这条变成恒过"
    report = drift_against(declared, surfaces)
    assert not report, "配音概率口径漂移（数值源=" + str(declared) + "）：\n  " + "\n  ".join(report)


# ---------------------------------------------------------------------------
# ④ 牙齿：注毒自证（本件不许是恒过）
# ---------------------------------------------------------------------------


def test_teeth_default_drift_is_red() -> None:
    """注毒 1（源侧）：改数值源必须落到判据取数的那一枚上；比对判据认得出两数不同。

    毒值从缺省派生（缺省的一半 / 归零）；FieldInfo 只改内存、不落盘（禁写件一根手指
    都没碰），逐发 finally 还原。比对判据的杀伤力用「差整整一枚单位」验，因此
    **外层世界已被改成 0 或 1 时本条也不会误报成恒过**。
    """
    field = Config.model_fields[PROBABILITY_FIELD]
    original = field.default
    for poison in (declared_default() / 2, 0.0):
        field.default = poison
        try:
            assert declared_default() == poison, "注毒没落到数值源上 ⇒ 本发是空跑"
        finally:
            field.default = original
    assert declared_default() == original, "注毒未还原"
    unit = float(_BUCKET_SPACE) / _BUCKET_SPACE  # 一整枚单位差，绝不等于任何合法概率缺省
    anchor = effective_default()
    assert _single_source_agreement(anchor + unit, anchor), "「声明=实装」那条锁是恒过的假锁"
    assert _single_source_agreement(anchor - unit, anchor), "同上（换一侧还是恒过）"
    assert drift_against(anchor, {"甲": anchor + unit, "乙": anchor}), "口径比对认不出单枚漂移"


def test_teeth_surface_drift_is_red() -> None:
    """注毒 2（口径侧）：只改一枚口径 ⇒ 一致性比对必须**恰好点名那一枚**。

    合成表比（不读盘上现值），偏移量取「一整枚单位差」，所以外层世界被改成任何值
    （含 0 与 1）时这一发都仍然有杀伤力，也不会误报。
    """
    declared = declared_default()
    unit = float(_BUCKET_SPACE) / _BUCKET_SPACE
    base = {"口径甲": declared, "口径乙": declared}
    assert drift_against(declared, base) == [], "全一致却报漂移 ⇒ 比对在乱报"
    flipped = {"口径甲": declared + unit, "口径乙": declared}
    report = drift_against(declared, flipped)
    assert len(report) == 1 and "口径甲" in report[0], f"改了一枚却没被恰好点名：{report}"
    zeroed = {"口径甲": 0.0, "口径乙": declared + unit}
    report = drift_against(declared + unit, zeroed)
    assert len(report) == 1 and "口径甲" in report[0], f"口径归零没被点名 ⇒ 比对恒过：{report}"


def test_teeth_lottery_bypass_is_red(corpus: list[IncomingMessage]) -> None:
    """注毒 3：把抽签判据架空（恒 0）⇒ 数值锁必红。

    这一发证明「命中率 vs 配置值」那条断言真的在看门链的输出，而不是恒等式。
    """
    original = tts_mod._resolve_probability
    messages = corpus
    probability = declared_default()
    if not probability > 0:
        pytest.skip("数值源已退化为 0，本发无从判起（由结构性那条点名退化本身）")
    try:
        tts_mod._resolve_probability = lambda _value: 0.0  # type: ignore[assignment]
        assert _hits(_lottery_config(), messages) == 0, "注毒没生效 ⇒ 本发是空跑"
        expected = round(probability * _BUCKET_SPACE) * len(messages) // _BUCKET_SPACE
        band = _tolerance_points(probability, len(messages))
        assert abs(0 - expected) > band, (
            "概率被架空成 0 而数值判据仍判「一致」⇒ 那条锁是恒过的假锁"
            f"（语料 {len(messages)} 条太短：期望 {expected} 落进容差 ±{band}）"
        )
    finally:
        tts_mod._resolve_probability = original  # type: ignore[assignment]
    assert tts_mod._resolve_probability is original, "注毒未还原"
    assert _hits(_lottery_config(), messages) > 0, "还原后仍 0 命中 ⇒ 门链被本席弄坏了"
