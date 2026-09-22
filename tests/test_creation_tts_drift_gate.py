"""统一接入波 U3 常驻门：creation TTS 契约漂移收敛 + 预留通道诚实性。

三件事各有一杀行为的判据（注毒即红，非存在性锁）：

1. **漂移门**——creation/tts/contracts.py 的 TTS 数值必须逐组等于中央
   `domains/media/tts_presets.py` 单一来源（改任一侧数字即红）；并锁死「旧值 3000/60s/
   20MiB/0.75..1.25 已作废、不得回归」的游标。
2. **诚实性**——未接线通道恒 unavailable（provider 探测缺省 False、原因串点名未接线）。
3. **DTO-as-data**——创建任务 DTO 以 `InvocationResult.data[PRESENTATION_DATA_KEY]` 的
   dict 形态流转，不新增第三种结果类型；unavailable 态不得携带呈现载荷。
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pydantic
import pytest

from plugins.bot_unified_runtime.domains.creation import reserved_provider as rprov
from plugins.bot_unified_runtime.domains.creation.image import contracts as cimage
from plugins.bot_unified_runtime.domains.creation.tts import contracts as ctts
from plugins.bot_unified_runtime.domains.media import tts_presets as central


def _cp():
    """惰性取中央执行信封模块。

    本席禁碰中央件，故只在用到描述符/信封的用例里惰性 import；当前它**可正常导入**
    （表 119 条装配无异常——U3 首稿写的「会因 bot.moegirl route_kind 冲突抛 ValueError」
    经复跑证伪，已按实况更正）。保留 try/skip 只为防他席在飞把装配改崩时**点名外因**，
    绝不因此放宽任何判据。
    """
    try:
        from plugins.bot_unified_runtime.runtime import capability_protocols as cp
    except Exception as exc:  # noqa: BLE001 - 只拦中央在飞装配崩，转为诚实跳过
        pytest.skip(f"中央 capability_protocols 当前不可导入（他席在飞，非 U3 面）: {exc}")
    return cp

# ---------------------------------------------------------------------------
# 1) 漂移门：creation 值 ≡ 中央单一来源
# ---------------------------------------------------------------------------


def test_tts_text_cap_equals_central_single_source() -> None:
    assert ctts.TTS_MAX_TEXT_CHARS == central.HARD_MAX_CHARS_FALLBACK


def test_tts_asset_bytes_equals_central_single_source() -> None:
    assert ctts.TTS_MAX_ASSET_BYTES == central.MAX_AUDIO_BYTES_FALLBACK


def test_tts_speed_domain_equals_central_single_source() -> None:
    assert (ctts.TTS_SPEED_MIN, ctts.TTS_SPEED_MAX) == central.ENGINE_PARAM_DOMAINS[
        "speed_factor"
    ]


def test_tts_duration_is_derived_from_central_byte_cap() -> None:
    # 中央不持有独立秒级时长顶，只以字节顶（8MiB≈131s）为准；creation 由同一天花板派生。
    assert ctts.TTS_MAX_DURATION_SECONDS == pytest.approx(
        central.MAX_AUDIO_BYTES_FALLBACK / 64000
    )


def test_retired_tts_literals_stayed_dead() -> None:
    """游标：旧值一旦回归（被重新写死）本门即红。"""
    assert ctts.TTS_MAX_TEXT_CHARS != 3000
    assert ctts.TTS_MAX_ASSET_BYTES != 20 * 1024 * 1024


def test_central_descriptor_table_holds_no_second_copy() -> None:
    """漂移的**第二现场**＝中央描述符表自身。

    第一轮收口把表里的写死数值改成引中央常量，评审仍判 Important：**表在装配期建、拿不到
    config**，所以表里那个数永远是「未配口径的兜底值」，而真身按 `config.bot_tts_hard_max_chars`
    现读——实测设 500 就得到「真身 500 / 表 2000」的分叉。故第二轮收口＝**表内不留 TTS 数值**，
    生效顶的唯一家是 `tts_presets.resolve_*`。本锁从此钉死这个方向：谁再往表里抄数值，红。
    """
    cp = _cp()
    row = next(
        d for d in cp._creation_descriptors() if d.capability_id == "creation.tts.synthesize"
    )
    assert row.limits == {}, f"描述符表又开始了持有 TTS 数值的假尺子形态：{row.limits}"
    # 表必须指向**规则**而不是数值：靠 config_keys 声明读哪两把键。
    assert {"bot_tts_hard_max_chars", "bot_tts_max_audio_bytes"} <= set(row.config_keys)
    assert "max_duration_seconds" not in row.limits  # 中央无独立秒级顶，抄进来=凭空造第二真源
    # 游标：旧值回归即红（creation 侧与表侧同判据，才叫单一真源）
    assert ctts.TTS_MAX_TEXT_CHARS != 3000
    assert ctts.TTS_MAX_ASSET_BYTES != 20 * 1024 * 1024
    assert ctts.TTS_MAX_DURATION_SECONDS != 60.0
    assert (ctts.TTS_SPEED_MIN, ctts.TTS_SPEED_MAX) != (0.75, 1.25)


def test_speed_default_still_inside_central_domain() -> None:
    lo, hi = central.ENGINE_PARAM_DOMAINS["speed_factor"]
    assert lo <= ctts.TTS_SPEED_DEFAULT <= hi


# ---------------------------------------------------------------------------
# 1b) 生效硬顶是**规则**、不是常量（R1/I-3：原漂移门结构性看不见 config 面）
# ---------------------------------------------------------------------------

_CAP_KEYS = ("bot_tts_hard_max_chars", "bot_tts_max_audio_bytes")
_PKG_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "bot_unified_runtime"
#: 规则的唯一家：`config 显式值 → 0/未配 ⇒ 内置常量` 这条判定只准写在这里。
_CAP_RULE_HOME = "domains/media/tts_presets.py"


def _is_cap_key_read(node: ast.AST) -> bool:
    if isinstance(node, ast.Attribute):
        return node.attr in _CAP_KEYS
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 2
        and isinstance(node.args[1], ast.Constant)
        and node.args[1].value in _CAP_KEYS
    )


def _cap_key_lines(src: str) -> list[int]:
    """源码里**读**这两个 config 键的行号。

    三种形态一起抓（R-A/C-05：只认前两种等于给后两种留豁免面）：
    ①属性式 `cfg.bot_tts_*`；②字面量 getattr `getattr(cfg, "bot_tts_*")`；
    ③键名藏进模块常量再间接读（`K = "bot_tts_*"` → `getattr(cfg, K)` /
    `cfg.model_dump()[K]` / `vars(cfg)["bot_tts_*"]` 等下标式）。

    刻意走 AST 而非文本匹配：help 元数据里的 `config_vars=("bot_tts_hard_max_chars",)` 只是
    字符串清单、sync_drift 的 `_config_default(config, "…")` 是「文档 vs Config 缺省」权威对照，
    两者都不重算生效顶 ⇒ 不该被这道门误伤。
    """
    tree = ast.parse(src)
    # 别名表：模块级 `名字 = "<键名>"`（含 f-string 以外的常量拼接一律不算，宁可少判误伤）
    aliases = {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant)
        and node.value.value in _CAP_KEYS
    }

    def _reads_key(value: ast.expr) -> bool:
        return (
            (isinstance(value, ast.Constant) and value.value in _CAP_KEYS)
            or (isinstance(value, ast.Name) and value.id in aliases)
        )

    lines: list[int] = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and node.attr in _CAP_KEYS) or (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and _reads_key(node.args[1])
        ):
            # 形态①属性式 / 形态②字面量 getattr（同一动作，合并分支=少一条 elif）。
            lines.append(node.lineno)
        elif isinstance(node, ast.Subscript) and _reads_key(node.slice):
            holder = node.value
            dict_like = (
                (isinstance(holder, ast.Call) and isinstance(holder.func, ast.Attribute)
                 and holder.func.attr in {"model_dump", "dict"})
                or (isinstance(holder, ast.Call) and isinstance(holder.func, ast.Name)
                    and holder.func.id == "vars")
                or (isinstance(holder, ast.Attribute) and holder.attr == "__dict__")
            )
            if dict_like:
                lines.append(node.lineno)
    return lines


def _fallback_constant_sites() -> dict[str, list[int]]:
    """`*_FALLBACK` 两枚兜底常量在**规则家之外**被引用的地方。

    数值的第二具身往往不是字面量 2000（太常见、误伤面大），而是"别处又 import 了一次
    兜底常量并拿它当天花板"——R-A/C-05 实测的那类。定义家与规则家必须同处。
    """
    hits: dict[str, list[int]] = {}
    for path in _PKG_ROOT.rglob("*.py"):
        rel = path.relative_to(_PKG_ROOT).as_posix()
        if rel == _CAP_RULE_HOME:
            continue
        try:
            src = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        found = [
            node.lineno
            for node in ast.walk(ast.parse(src))
            if isinstance(node, ast.Name) and node.id in _FALLBACK_NAMES
        ]
        if found:
            hits[rel] = found
    return hits


_FALLBACK_NAMES = ("HARD_MAX_CHARS_FALLBACK", "MAX_AUDIO_BYTES_FALLBACK")


def _all_cap_key_reads() -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for path in _PKG_ROOT.rglob("*.py"):
        try:
            src = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        try:
            found = _cap_key_lines(src)
        except SyntaxError:  # 在飞的半写文件不归本门判
            continue
        if found:
            out[path.relative_to(_PKG_ROOT).as_posix()] = found
    return out


def test_operative_tts_caps_follow_config_not_the_fallback_constant() -> None:
    """杀伤力证明：改 `BOT_TTS_HARD_MAX_CHARS` 后生效顶必须跟随，只有 0 才落内置常量。

    原门只比 `creation 值 ≡ HARD_MAX_CHARS_FALLBACK`——那是「兜底值」不是「天花板」，
    配置一改就分叉而门全绿。本用例把规则本身纳入判据。
    """
    cfg = SimpleNamespace(bot_tts_hard_max_chars=5000, bot_tts_max_audio_bytes=11 * 1024 * 1024)
    assert central.resolve_hard_max_chars(cfg) == 5000
    assert central.resolve_max_audio_bytes(cfg) == 11 * 1024 * 1024
    zero = SimpleNamespace(bot_tts_hard_max_chars=0, bot_tts_max_audio_bytes=0)
    assert central.resolve_hard_max_chars(zero) == ctts.TTS_MAX_TEXT_CHARS
    assert central.resolve_max_audio_bytes(zero) == ctts.TTS_MAX_ASSET_BYTES
    # 键缺失（Config 未装载）与 0 同义，且绝不抛。
    assert central.resolve_hard_max_chars(SimpleNamespace()) == central.HARD_MAX_CHARS_FALLBACK
    assert central.resolve_hard_max_chars(None) == central.HARD_MAX_CHARS_FALLBACK


def test_hard_cap_config_rule_has_exactly_one_home() -> None:
    """除规则家之外，全树再有人重写这条判定 ⇒ 分叉，当场红。"""
    strays = {rel: ln for rel, ln in _all_cap_key_reads().items() if rel != _CAP_RULE_HOME}
    assert strays == {}, f"生效硬顶规则出现第二处读数点（改 config 只会有一处跟随）：{strays}"


def test_rule_home_scanner_sees_its_own_reads() -> None:
    """自证非空门：扫描器必须看得见规则家自身的命中，否则上一条恒绿。"""
    assert _all_cap_key_reads().get(_CAP_RULE_HOME), "扫描器看不见规则家的 config 读点=假门"


@pytest.mark.parametrize(
    "src",
    [
        "def f(config):\n    return int(getattr(config, 'bot_tts_hard_max_chars', 0) or 0) or 2000\n",
        "def f(config):\n    return config.bot_tts_max_audio_bytes\n",
        # 别名形态与下标形态（R-A/C-05：只认前两种等于给后两种留豁免面）。
        "KEY = 'bot_tts_hard_max_chars'\n\n\ndef f(config):\n    return getattr(config, KEY, 0)\n",
        "def f(config):\n    return config.model_dump()['bot_tts_max_audio_bytes']\n",
        "def f(config):\n    return vars(config)['bot_tts_hard_max_chars']\n",
    ],
)
def test_scanner_detects_every_read_shape(src: str) -> None:
    """注毒：每种读数形态各必须被扫到（漏一种=门有豁免洞）。"""
    assert _cap_key_lines(src), f"读数扫描漏判：{src}"


def test_help_string_lists_are_not_misread_as_rule_sites() -> None:
    """负样本：help 元数据只是字符串清单，不该被判成第二现场（否则本门会被误伤后被人调松）。"""
    assert _cap_key_lines('META = ({"config_vars": ("bot_tts_hard_max_chars",)},)\n') == []
    # 兜底常量名不是 config 键名，不参与这条判据。
    assert _cap_key_lines("cap = HARD_MAX_CHARS_FALLBACK\n") == []


#: 兜底常量在"规则家之外"被引用的**登记面**（双向锁：新增即红，销账也必须删干净）。
#: 这两处不是策略第二真源，而是"函数内二次地板"——所有调用方都显式传值，故不咬；
#: 但它们是数值的第二具身，Wave 4.1 之后应收进 resolve_* 一并销账（清单只准缩不准长）。
FALLBACK_REFERENCE_LEDGER: dict[str, str] = {
    "domains/media/capabilities/tts.py": (
        "`_cap_audio` 的参数默认值 + 函数内 `or MAX_AUDIO_BYTES_FALLBACK` 地板；"
        "调用方（tts.py/voice_enricher.py）已全部改走 resolve_max_audio_bytes(config)"
    ),
}


def test_fallback_constants_have_no_unregistered_second_home() -> None:
    sites = _fallback_constant_sites()
    assert set(sites) == set(FALLBACK_REFERENCE_LEDGER), (
        f"兜底常量的引用面与登记面分叉：多出 {sorted(set(sites) - set(FALLBACK_REFERENCE_LEDGER))}、"
        f"已销未删 {sorted(set(FALLBACK_REFERENCE_LEDGER) - set(sites))}"
    )


# ---------------------------------------------------------------------------
# 2) 诚实性：未接线恒 unavailable
# ---------------------------------------------------------------------------


def test_provider_configured_default_false_without_future_keys() -> None:
    empty = SimpleNamespace()  # 无任何键 → 探测恒 False（绝不猜有 provider）
    assert rprov.provider_configured(empty, "creation.tts") is False
    assert rprov.provider_configured(empty, "creation.image") is False


def test_provider_configured_requires_nonempty_future_key() -> None:
    assert rprov.provider_configured(
        SimpleNamespace(bot_creation_tts_provider="gpt-sovits"), "creation.tts"
    ) is True
    # 空串不算配置。
    assert (
        rprov.provider_configured(SimpleNamespace(bot_creation_tts_provider="   "), "creation.tts")
        is False
    )


def test_reserved_reason_names_unwired_for_unconfigured() -> None:
    reason = rprov.reserved_availability_reason(SimpleNamespace(), "creation.tts")
    assert reason.strip()
    assert "未接线" in reason
    # 诚实性游标：若被改成宣称「已可用」，本行即红。
    assert "可用" not in reason.replace("协议≠可用", "")


# ---------------------------------------------------------------------------
# 3) DTO-as-data：不新增第三种结果类型
# ---------------------------------------------------------------------------


def _tts_dto() -> ctts.TTSJobRequest:
    return ctts.TTSJobRequest(
        text="漂泊者，晚上好。",
        provider="provider_a",
        model="voice-model-1",
        voice="alloy",
        language="zh",
        format="mp3",
        workspace_id="ws_main",
        target="session_1",
        version="rev-1",
    )


def test_tts_dto_flows_as_presentation_data_payload() -> None:
    cp = _cp()
    dto = _tts_dto()
    result = cp.InvocationResult(
        capability_id="creation.tts.synthesize",
        status=cp.InvocationStatus.OK,
        data={cp.PRESENTATION_DATA_KEY: dto.model_dump(mode="json")},
    )
    payload = result.data[cp.PRESENTATION_DATA_KEY]
    assert isinstance(payload, dict)  # 信封只承载 dict，不承载活模型对象
    assert payload["text"] == "漂泊者，晚上好。"


def test_image_dto_flows_as_presentation_data_payload() -> None:
    cp = _cp()
    dto = cimage.ImageJobRequest(
        task="text_to_image",
        prompt="釉瑚风格的云母卡片插画",
        provider="provider_a",
        model="image-model-1",
        size="1024x1024",
        workspace_id="ws_main",
        version="rev-1",
    )
    result = cp.InvocationResult(
        capability_id="creation.image.generate",
        status=cp.InvocationStatus.OK,
        data={cp.PRESENTATION_DATA_KEY: dto.model_dump(mode="json")},
    )
    assert result.data[cp.PRESENTATION_DATA_KEY]["prompt"].startswith("釉瑚")


def test_unavailable_envelope_must_not_smuggle_success_payload() -> None:
    """把 handler 从 unavailable 改成假成功=带呈现载荷的失败态 → 信封不变量当场崩。"""
    cp = _cp()
    with pytest.raises(pydantic.ValidationError):
        cp.InvocationResult(
            capability_id="creation.tts.synthesize",
            status=cp.InvocationStatus.UNAVAILABLE,
            data={cp.PRESENTATION_DATA_KEY: _tts_dto().model_dump(mode="json")},
            detail="假装成功",
        )
    # 诚实 unavailable 的正确形态：带 detail、不带载荷。
    honest = cp.InvocationResult(
        capability_id="creation.tts.synthesize",
        status=cp.InvocationStatus.UNAVAILABLE,
        data={},
        detail=rprov.reserved_availability_reason(SimpleNamespace(), "creation.tts"),
    )
    assert honest.status is cp.InvocationStatus.UNAVAILABLE
    assert cp.PRESENTATION_DATA_KEY not in honest.data
