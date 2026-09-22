"""统一波 S-CREATE 常驻门：creation 域内「AI 绘画 ↔ TTS」两腿必须同一套契约。

立门理由（不是存在性锁，每格都可注毒打死）：本波要抓的病正是**两域各抄一份**——
TTS 腿的数值漂移由 ``tests/test_creation_tts_drift_gate.py`` 管（creation ≡ 中央
``tts_presets``），而**绘画腿从来没有一道门**回答「绘画和语音用的是同一套协议吗」。
本门只管这一件事：两侧都有的口径（请求身份 / 产物身份 / 限额 / 错误码 / 状态机 /
REST 形状 / 诚实终态 / 结果信封）必须同源，分叉当场红。

覆盖 ``docs/design/capability-orchestration-adoption-spec.md`` §1 七维里与 creation
有关的可判部分：
- D-c 出入参唯一契约：域内禁第二结果信封、禁第二状态机、禁手抄中央 data 保留键；
- D-d/D-f 限额与健康：中央表里的每个数字都必须在契约侧有同值的家且被真执法；
- D-e 归因：诚实 detail 必须从**两种在册 id 写法**都取得到（装配层传哪个都不说错话）。

纪律：行号不写死；中央件只在用到的用例里惰性 import（本席禁改中央件，他席在飞装配
崩时点名外因、绝不放宽判据——先例 ``test_creation_tts_drift_gate._cp``）。
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

import pydantic
import pytest

from plugins.bot_unified_runtime.domains.creation import reserved_provider as rprov
from plugins.bot_unified_runtime.domains.creation._common import contracts as common
from plugins.bot_unified_runtime.domains.creation.image import contracts as cimage
from plugins.bot_unified_runtime.domains.creation.tts import contracts as ctts

_PKG_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "bot_unified_runtime"
_CREATION_DIR = _PKG_ROOT / "domains" / "creation"


def _cp():
    """惰性取中央执行信封模块（本席禁碰中央件，只在用到时 import）。"""
    try:
        from plugins.bot_unified_runtime.runtime import capability_protocols as cp
    except Exception as exc:  # noqa: BLE001 - 只拦他席在飞把装配改崩，转为诚实跳过
        pytest.skip(f"中央 capability_protocols 当前不可导入（他席在飞，非 S-CREATE 面）: {exc}")
    return cp


def _sources(scope: Path) -> dict[str, str]:
    """creation 域全部 .py 源码（相对主包路径），供 AST 形态判据使用。"""
    return {
        path.relative_to(_PKG_ROOT).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(scope.rglob("*.py"))
    }


# ---------------------------------------------------------------------------
# 两端形状（绘画与语音走同一套判据）
# ---------------------------------------------------------------------------


def _tts_request(**overrides: object) -> ctts.TTSJobRequest:
    payload: dict[str, object] = {
        "text": "漂泊者，晚上好。",
        "provider": "provider_a",
        "model": "voice-model-1",
        "voice": "alloy",
        "language": "zh",
        "format": "mp3",
        "workspace_id": "ws_main",
        "target": "session_1",
        "version": "rev-1",
    }
    payload.update(overrides)
    return ctts.TTSJobRequest(**payload)  # type: ignore[arg-type]


def _image_request(**overrides: object) -> cimage.ImageJobRequest:
    payload: dict[str, object] = {
        "task": "text_to_image",
        "prompt": "釉瑚风格的云母卡片插画",
        "provider": "provider_a",
        "model": "image-model-1",
        "size": "1024x1024",
        "workspace_id": "ws_main",
        "version": "rev-1",
    }
    payload.update(overrides)
    return cimage.ImageJobRequest(**payload)  # type: ignore[arg-type]


def _tts_asset(**overrides: object) -> ctts.TTSAssetRecord:
    payload: dict[str, object] = {
        "asset_id": {"asset_id": "asset-1"},
        "duration_seconds": 3.5,
        "bytes_size": 4096,
        "mime": "audio/wav",
        "provider_operation": "op-1",
        "review_approved": True,
    }
    payload.update(overrides)
    return ctts.TTSAssetRecord(**payload)  # type: ignore[arg-type]


def _image_asset(**overrides: object) -> cimage.ImageAssetRecord:
    payload: dict[str, object] = {
        "asset_id": {"asset_id": "asset-2"},
        "width": 1024,
        "height": 1024,
        "real_mime": "image/png",
        "bytes_size": 20480,
        "magic_verified": True,
        "exif_sanitized": True,
        "review_approved": True,
    }
    payload.update(overrides)
    return cimage.ImageAssetRecord(**payload)  # type: ignore[arg-type]


#: (腿名, 构造器, 通道 id)——两腿共用判据时按此表展开。
LEGS: tuple[tuple[str, object, str], ...] = (
    ("tts", _tts_request, "creation.tts"),
    ("image", _image_request, "creation.image"),
)
ASSET_LEGS: tuple[tuple[str, object, str], ...] = (
    ("tts", _tts_asset, "creation.tts"),
    ("image", _image_asset, "creation.image"),
)

REQUEST_SHAPES = pytest.mark.parametrize(
    "build,channel", [(b, c) for _n, b, c in LEGS], ids=["tts-request", "image-request"]
)
ASSET_SHAPES = pytest.mark.parametrize(
    "build,channel", [(b, c) for _n, b, c in ASSET_LEGS], ids=["tts-asset", "image-asset"]
)

DIGEST_OK = "a" * 64
#: 一律必须被拒的坏摘要形态（长度/大小写/字符集/空白四个方向各一刀）。
BAD_DIGESTS = ["", "abc", "A" * 64, "g" * 64, "a" * 63, "a" * 65, f" {DIGEST_OK}"]


# ===========================================================================
# 1) 请求身份（幂等键）——两腿同一字段、同一形态、同一条规范化规则
# ===========================================================================


@REQUEST_SHAPES
def test_idempotency_field_is_mandatory_on_both_legs(build, channel: str) -> None:
    """两侧都必须**有**这个身份字段，缺省 None＝诚实「没有身份」（不去重、不猜同一条）。"""
    assert channel in rprov.RESERVED_REASON
    model = build()
    assert common.IDEMPOTENCY_SELF_FIELD in type(model).model_fields
    assert getattr(model, common.IDEMPOTENCY_SELF_FIELD) is None
    keyed = build(**{common.IDEMPOTENCY_SELF_FIELD: DIGEST_OK})
    assert getattr(keyed, common.IDEMPOTENCY_SELF_FIELD) == DIGEST_OK


#: 幂等键字段名的**源码级**锁：漏一侧即分叉（含"改名后运行时恰好仍绿"的暗道——
#: 那种改法会让 `idempotency_preimage` 的自排除失效，键算不进身份）。
_IDENTITY_FIELD_SOURCE_LOCKS: dict[str, str] = {
    "domains/creation/tts/contracts.py": "idempotency_key",
    "domains/creation/image/contracts.py": "idempotency_key",
}


def test_idempotency_field_name_is_declared_on_both_legs() -> None:
    sources = _sources(_CREATION_DIR)
    assert common.IDEMPOTENCY_SELF_FIELD not in {"", "idempotency"}  # 自证：钉的是实名
    for rel, name in _IDENTITY_FIELD_SOURCE_LOCKS.items():
        assert name in sources[rel], f"{rel} 不再声明幂等键字段 {name!r}：该腿失去请求身份"
    assert len({*(_IDENTITY_FIELD_SOURCE_LOCKS.values()), common.IDEMPOTENCY_SELF_FIELD}) == 1, (
        f"源码锁与 `_common.IDEMPOTENCY_SELF_FIELD`={common.IDEMPOTENCY_SELF_FIELD!r} 不同名"
    )


@REQUEST_SHAPES
@pytest.mark.parametrize("bad", BAD_DIGESTS)
def test_idempotency_key_shape_is_identical_on_both_legs(build, channel: str, bad: str) -> None:
    """形态口径同源：同一串坏摘要在两侧必须**一起**被拒（只松一侧＝分叉，当场红）。"""
    with pytest.raises(pydantic.ValidationError):
        build(**{common.IDEMPOTENCY_SELF_FIELD: bad})


@REQUEST_SHAPES
def test_preimage_excludes_its_own_key(build, channel: str) -> None:
    """键不能把自己的值算进身份：否则「先算后填」与「先填后算」是两个身份＝不可复现。"""
    bare = build()
    before = common.idempotency_preimage(bare)
    after = common.idempotency_preimage(
        bare.model_copy(update={common.IDEMPOTENCY_SELF_FIELD: DIGEST_OK})
    )
    assert before == after


@REQUEST_SHAPES
def test_preimage_carries_rule_version_and_dto_type(build, channel: str) -> None:
    """版本头 + 类名：改口径必须升版；两腿同形载荷不得互撞身份。"""
    model = build()
    preimage = common.idempotency_preimage(model)
    assert preimage.startswith(f"{common.IDEMPOTENCY_RULE_VERSION}|{type(model).__name__}|")
    assert common.idempotency_preimage(_tts_request(text="同一句")) != common.idempotency_preimage(
        _image_request(prompt="同一句")
    )


#: 身份覆盖用例：(字段, 基线覆盖, 变更覆盖)。两侧各一套，逐字段一刀。
IDENTITY_CASES: dict[str, tuple[tuple[str, dict[str, object], dict[str, object]], ...]] = {
    "tts": (
        ("text", {}, {"text": "换一句"}),
        (
            "approved_reply_id",
            {"text": None, "approved_reply_id": "reply-1"},
            {"approved_reply_id": "reply-2"},
        ),
        ("provider", {}, {"provider": "provider_b"}),
        ("model", {}, {"model": "voice-model-2"}),
        ("voice", {}, {"voice": "echo"}),
        ("language", {}, {"language": "en"}),
        ("format", {}, {"format": "wav"}),
        ("speed", {}, {"speed": 1.2}),
        ("workspace_id", {}, {"workspace_id": "ws_other"}),
        ("target", {}, {"target": "session_2"}),
        ("version", {}, {"version": "rev-2"}),
    ),
    "image": (
        ("task", {}, {"task": "image_to_image", "assets": ({"asset_id": "in-1"},)}),
        (
            "assets",
            {"task": "image_to_image", "assets": ({"asset_id": "in-1"},)},
            {"task": "image_to_image", "assets": ({"asset_id": "in-1"}, {"asset_id": "in-2"})},
        ),
        (
            "mask",
            {
                "task": "inpaint",
                "assets": ({"asset_id": "in-1"},),
                "mask": {"asset_id": "mask-1"},
            },
            {
                "task": "inpaint",
                "assets": ({"asset_id": "in-1"},),
                "mask": {"asset_id": "mask-2"},
            },
        ),
        ("prompt", {}, {"prompt": "换一个画面"}),
        ("negative_prompt", {}, {"negative_prompt": "模糊"}),
        ("provider", {}, {"provider": "provider_b"}),
        ("model", {}, {"model": "image-model-2"}),
        ("size", {}, {"size": "512x512"}),
        ("count", {}, {"count": 2}),
        ("seed", {}, {"seed": 7}),
        ("steps", {}, {"steps": 20}),
        ("guidance", {}, {"guidance": 4.5}),
        ("workspace_id", {}, {"workspace_id": "ws_other"}),
        ("version", {}, {"version": "rev-2"}),
    ),
}


@pytest.mark.parametrize("leg,build", [("tts", _tts_request), ("image", _image_request)])
def test_every_material_field_enters_the_identity(leg: str, build) -> None:
    """逐字段证明「改这个字段 ⇒ 身份变」，并锁死覆盖面＝全字段（新增字段漏判即红）。"""
    cases = IDENTITY_CASES[leg]
    covered = {name for name, _base, _mutated in cases}
    all_fields = set(type(build()).model_fields) - {common.IDEMPOTENCY_SELF_FIELD}
    assert covered == all_fields, (
        f"{leg} 侧幂等身份判据未覆盖全部字段：缺 {sorted(all_fields - covered)}、"
        f"多 {sorted(covered - all_fields)}（新字段进 DTO 就必须进身份，否则它永远不去重）"
    )
    for name, base_over, mutated_over in cases:
        base = build(**base_over)
        merged = {**base_over, **mutated_over}
        mutated = build(**merged)
        assert common.idempotency_preimage(mutated) != common.idempotency_preimage(base), (
            f"字段 {name} 变更不改变幂等身份＝该维度永远判不出「这是同一条请求」"
        )


def test_rule_version_is_load_bearing(monkeypatch: pytest.MonkeyPatch) -> None:
    """自证：规范化函数不是恒等摆设——规则版本一升，全部历史身份必变（改口径必升版）。"""
    before = common.idempotency_preimage(_tts_request())
    monkeypatch.setattr(
        common, "IDEMPOTENCY_RULE_VERSION", common.IDEMPOTENCY_RULE_VERSION + "-next"
    )
    assert common.idempotency_preimage(_tts_request()) != before


def test_creation_domain_does_not_rehash_locally() -> None:
    """幂等键与产物摘要的**算法家只有一个**（中央 ``domains/media/digest.py``）。

    creation 域只声明「哪些字段构成身份」与「值长什么样」。域内出现 ``hashlib``
    或 ``sha256(`` 手抄＝第二套摘要算法家，正是 Wave G 之后各常驻门在抓的病。
    """
    for rel, src in _sources(_CREATION_DIR).items():
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Import):
                assert all(
                    alias.name.split(".")[0] != "hashlib" for alias in node.names
                ), f"{rel}:{node.lineno} 在域内重算哈希（第二套摘要算法家）"
            elif isinstance(node, ast.ImportFrom):
                origin = (node.module or "").split(".")[0]
                assert origin != "hashlib", f"{rel}:{node.lineno} 从 hashlib 导入＝重算哈希"
            elif isinstance(node, ast.Attribute) and node.attr == "sha256":
                raise AssertionError(f"{rel}:{node.lineno} 出现 sha256 手抄调用")


def test_creation_domain_never_reads_the_central_digest_helper() -> None:
    """反向半边：域内也不准 import 中央 digest 件（契约模块受隔离探针约束，
    真包父级装配会拉起 nonebot）。取值发生在装配层，不在协议层。"""
    for rel, src in _sources(_CREATION_DIR).items():
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("media.digest"):
                raise AssertionError(
                    f"{rel}:{node.lineno} 协议层直连中央 digest 件——"
                    "算摘要属装配层职责（本域 contracts 受零重 import 隔离探针约束）"
                )


def test_digest_pattern_has_no_second_literal_home() -> None:
    """叶子契约必须引 ``_common`` 的形态常量，不得再手抄一遍正则。"""
    strays: dict[str, list[int]] = {}
    for rel, src in _sources(_CREATION_DIR).items():
        if rel.endswith("_common/contracts.py"):
            continue
        lines = [
            node.lineno
            for node in ast.walk(ast.parse(src))
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and "0-9a-f" in node.value
        ]
        if lines:
            strays[rel] = lines
    assert strays == {}, f"摘要形态正则出现第二处手抄（改一处必漏一处）：{strays}"


# ===========================================================================
# 2) 产物身份——两腿同一个键名、同一形态、都可诚实缺值
# ===========================================================================


@ASSET_SHAPES
def test_content_digest_field_present_and_optional_on_both_legs(build, channel: str) -> None:
    asset = build()
    assert common.CONTENT_DIGEST_KEY in type(asset).model_fields
    assert getattr(asset, common.CONTENT_DIGEST_KEY) is None  # 缺即缺，禁补算造假值
    keyed = build(**{common.CONTENT_DIGEST_KEY: DIGEST_OK})
    assert getattr(keyed, common.CONTENT_DIGEST_KEY) == DIGEST_OK


@ASSET_SHAPES
@pytest.mark.parametrize("bad", BAD_DIGESTS)
def test_content_digest_shape_identical_on_both_legs(build, channel: str, bad: str) -> None:
    with pytest.raises(pydantic.ValidationError):
        build(**{common.CONTENT_DIGEST_KEY: bad})


def test_digest_key_name_equals_the_production_and_render_key() -> None:
    """协议键名必须等于生产侧真在用的那个键（否则「同一套契约」只是话术）。

    生产两处读点：TTS 出站部件键、渲染收口的音频摘要键。本判据扫源码不 import
    （生产件重，且会把 nonebot 拉进本门）。
    """
    needle = f'"{common.CONTENT_DIGEST_KEY}"'
    for rel in ("domains/media/capabilities/tts.py", "domains/render/renderer.py"):
        src = (_PKG_ROOT / rel).read_text(encoding="utf-8")
        assert needle in src, f"{rel} 不再使用 {common.CONTENT_DIGEST_KEY} 键：协议与生产已分叉"


# ===========================================================================
# 3) 限额与枚举口径——中央表里的每个数字都得有同值的家，且契约真执法
# ===========================================================================


def _image_owned_limits() -> dict[str, int]:
    """契约侧（真身）的绘画限额：中央表里同名键必须与此逐项相等。"""
    return {
        "max_prompt_chars": cimage.IMAGE_MAX_PROMPT_CHARS,
        "max_negative_chars": cimage.IMAGE_MAX_NEGATIVE_CHARS,
        "max_count": cimage.IMAGE_MAX_COUNT,
        "max_input_pixels": common.IMAGE_MAX_INPUT_PIXELS,
        "max_steps": cimage.IMAGE_MAX_STEPS,
    }


def _limits_fork(
    central: Mapping[str, int], owned: Mapping[str, int]
) -> dict[str, tuple[int, int]]:
    """纯函数：逐项对照，返回 {键: (表值, 契约值)} 的分叉清单。"""
    return {
        key: (central[key], owned[key])
        for key in sorted(central)
        if key in owned and central[key] != owned[key]
    }


def test_limits_lock_has_teeth_on_both_directions() -> None:
    """自证：对照函数不是恒绿的摆设——任一侧改动都必须报出分叉。"""
    owned = _image_owned_limits()
    assert _limits_fork(owned, owned) == {}
    assert _limits_fork({**owned, "max_count": 8}, owned) == {"max_count": (8, 2)}
    assert _limits_fork(owned, {**owned, "max_steps": 99}) == {"max_steps": (50, 99)}
    assert _limits_fork({"max_new_thing": 3}, owned) == {}  # 无家可归的新键由下一格判


def test_creation_descriptor_limits_match_contract_single_source() -> None:
    """中央表与契约两侧同值（今天相等 ⇒ 绿；谁只改一边 ⇒ 红）。

    这正是 TTS 腿已被抓过的病（审计 E3-4）在绘画腿上的等价形态：数值同时躺在
    ``_creation_descriptors()`` 与 ``image/contracts.py`` 两处。"""
    cp = _cp()
    row = next(
        d for d in cp._creation_descriptors() if d.capability_id == "creation.image.generate"
    )
    fork = _limits_fork(row.limits, _image_owned_limits())
    assert fork == {}, f"绘画限额中央表与契约分叉（表值/契约值）：{fork}"
    homeless = sorted(set(row.limits) - set(_image_owned_limits()))
    assert homeless == [], f"中央表出现契约侧无家的限额键：{homeless}"


#: 中央 creation 族描述符里**仍自持数值**的登记面（双向锁：新增即红，销账须同批删干净）。
#: 方向与 TTS 腿一致——TTS 第二轮收口（R1/I-3）清空了表内数值、唯一家改指
#: ``tts_presets.resolve_*``；绘画侧的契约常量就是真身（无 config 键、无运行期现读），
#: 表里那份属「装饰性副本」：``limits`` 只有配了 ``limit_fields`` 才被 invoker 执法，
#: 而绘画 descriptor 的 ``limit_fields`` 为空 ⇒ 表里的数字今天不量任何东西。
#: 收口方案交主会话裁（见席位日志 C-2），本登记面负责让它不再长。
CENTRAL_TABLE_NUMERIC_HOME_LEDGER: dict[str, tuple[str, ...]] = {
    "creation.image.generate": (
        "max_count",
        "max_input_pixels",
        "max_negative_chars",
        "max_prompt_chars",
        "max_steps",
    ),
}


def test_central_table_holds_no_unregistered_creation_numbers() -> None:
    cp = _cp()
    live = {
        row.capability_id: tuple(sorted(row.limits))
        for row in cp._creation_descriptors()
        if row.limits
    }
    assert live == CENTRAL_TABLE_NUMERIC_HOME_LEDGER, (
        f"中央 creation 表的数值持有面与登记面分叉：实况 {live} ≠ 登记 "
        f"{CENTRAL_TABLE_NUMERIC_HOME_LEDGER}（新增数值先收口到契约单一家，"
        "或在本登记面点名并说明为何不能收）"
    )


def test_image_descriptor_limits_are_backed_by_real_dto_enforcement() -> None:
    """表里写了数字，契约侧就必须真拦（否则「有上限」是话术）。逐键一刀。"""
    caps = _image_owned_limits()
    with pytest.raises(pydantic.ValidationError):
        _image_request(prompt="字" * (caps["max_prompt_chars"] + 1))
    with pytest.raises(pydantic.ValidationError):
        _image_request(negative_prompt="字" * (caps["max_negative_chars"] + 1))
    with pytest.raises(pydantic.ValidationError):
        _image_request(count=caps["max_count"] + 1)
    with pytest.raises(pydantic.ValidationError):
        _image_request(steps=caps["max_steps"] + 1)
    with pytest.raises(pydantic.ValidationError):
        common.AssetRef(asset_id="asset-1", pixel_count=caps["max_input_pixels"] + 1)


def test_tts_descriptor_keeps_its_config_rule_not_numbers() -> None:
    """两腿对照的**方向**锁：语音侧表内不持数（规则家在 ``tts_presets``）——
    与漂移门同向，钉死「语音不得回退成在表里抄数值」。"""
    cp = _cp()
    row = next(
        d for d in cp._creation_descriptors() if d.capability_id == "creation.tts.synthesize"
    )
    assert row.limits == {}
    assert {"bot_tts_hard_max_chars", "bot_tts_max_audio_bytes"} <= set(row.config_keys)


# ===========================================================================
# 4) 同一套契约的「禁第三套」面（§7）
# ===========================================================================


def test_no_second_job_state_machine_in_creation_domain() -> None:
    """任务状态机只有 ``_common`` 一份真身；两腿只准起别名。"""
    defs: dict[str, list[int]] = {}
    aliases: set[str] = set()
    for rel, src in _sources(_CREATION_DIR).items():
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.ClassDef) and node.name.endswith("JobState"):
                defs.setdefault(rel, []).append(node.lineno)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if (
                        isinstance(target, ast.Name)
                        and target.id.endswith("JobState")
                        and isinstance(node.value, ast.Name)
                        and node.value.id == "CreationJobState"
                    ):
                        aliases.add(f"{rel}#{target.id}")
    total = sum(len(v) for v in defs.values())
    assert total == 1, f"状态机出现第二具身：{defs}"
    assert next(iter(defs)).endswith("_common/contracts.py"), f"状态机真身不在 _common：{defs}"
    assert {
        "domains/creation/tts/contracts.py#TTSJobState",
        "domains/creation/image/contracts.py#ImageJobState",
    } <= aliases, f"某腿不再别名共用中央状态机（=自立第二状态机）：{sorted(aliases)}"


def test_no_second_result_envelope_or_presentation_key_in_creation_domain() -> None:
    """域内禁第二结果信封类、禁手抄中央 data 保留键（§7 禁第三套的机器形态）。"""
    cp = _cp()
    reserved_data_keys = {cp.PRESENTATION_DATA_KEY, cp.INVOKER_ERROR_DATA_KEY}
    for rel, src in _sources(_CREATION_DIR).items():
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.ClassDef) and node.name in {
                "CapabilityResult",
                "InvocationResult",
            }:
                raise AssertionError(f"{rel}:{node.lineno} 在域内复制了中央信封类 {node.name}")
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value not in reserved_data_keys, (
                    f"{rel}:{getattr(node, 'lineno', 0)} 手抄了中央 data 保留键 "
                    f"{node.value!r}（键名的家在中央，域内只准 import）"
                )


def test_error_codes_derive_from_single_catalog_not_hand_copied() -> None:
    """两腿错误目录必须等值于 ``_common`` 单一注册源，且叶子内不得手抄 HTTP 码。"""
    assert ctts.TTS_ERROR_CATALOG == common.CREATION_ERROR_CATALOG
    assert cimage.IMAGE_ERROR_CATALOG == common.CREATION_ERROR_CATALOG
    assert common.CREATION_ERROR_CATALOG["dependency_unavailable"] == 503
    for rel, src in _sources(_CREATION_DIR).items():
        if rel.endswith("_common/contracts.py"):
            continue
        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values, strict=False):
                if (
                    isinstance(key, ast.Constant)
                    and isinstance(key.value, str)
                    and key.value in common.CREATION_ERROR_CATALOG
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, int)
                ):
                    raise AssertionError(
                        f"{rel}:{node.lineno} 手抄错误码 HTTP 值 {value.value}"
                        "（唯一家=_common.CREATION_ERROR_CATALOG，改一处必漏一处）"
                    )


def test_usage_metric_subsets_stay_inside_common_vocabulary() -> None:
    """两腿计量都是 ``_common`` 词表的子集；Token 面两侧一致地不得伪造。"""
    assert ctts.TTS_USAGE_METRICS <= common.CREATION_METRICS
    assert cimage.IMAGE_USAGE_METRICS <= common.CREATION_METRICS
    assert ctts.TTS_USAGE_METRICS & common.TOKEN_METRIC_NAMES == frozenset()
    assert cimage.IMAGE_USAGE_METRICS & common.TOKEN_METRIC_NAMES == frozenset()
    for metric in sorted(common.CREATION_METRICS - cimage.IMAGE_USAGE_METRICS):
        with pytest.raises(pydantic.ValidationError):
            cimage.ImageUsage(
                quantities=[
                    common.UsageLine(
                        metric=metric,
                        value="1",
                        unit=common.CREATION_METRIC_UNITS[metric],
                        status="measured",
                    )
                ]
            )


# ===========================================================================
# 5) REST 协议形状——两腿同一套端子（少一端＝分叉）
# ===========================================================================


def _route_shape(routes: tuple[tuple[str, str], ...], domain_vocab: str) -> list[tuple[str, str]]:
    """(verb, path) → (verb, 端子槽)：命名空间折掉，域词汇折成同一个槽。"""
    shape: list[tuple[str, str]] = []
    for verb, path in routes:
        segments = [seg for seg in path.split("/") if seg]
        assert len(segments) >= 2, f"路由 {path!r} 至少要有命名空间 + 端子"
        tail = list(segments[1:])
        tail[0] = "<vocab>" if tail[0] == domain_vocab else tail[0]
        shape.append((verb, "/".join("<param>" if seg.startswith("{") else seg for seg in tail)))
    return shape


def test_rest_surface_has_the_same_slots_on_both_legs() -> None:
    """providers / 能力目录 / preview / jobs / jobs/{id} / cancel 六端两腿齐备。

    缺 cancel 或缺 preview，都会让「预览→确认」「未知不重发」两条既有教义在某一腿
    无处落地——那是真分叉，不是措辞差异。
    """
    tts = _route_shape(ctts.TTS_REST_ROUTES, domain_vocab="voices")
    img = _route_shape(cimage.IMAGE_REST_ROUTES, domain_vocab="models")
    assert tts == img, f"REST 端子分叉：TTS {tts} ≠ 绘图 {img}"
    assert [verb for verb, _ in tts] == ["GET", "GET", "GET", "POST", "POST", "GET", "POST"]


def test_static_routes_precede_parameterised_on_both_legs() -> None:
    for leg, routes in (("tts", ctts.TTS_REST_ROUTES), ("image", cimage.IMAGE_REST_ROUTES)):
        seen_param = False
        for _verb, path in routes:
            if "{" in path:
                seen_param = True
            elif seen_param:
                raise AssertionError(f"{leg} 侧静态路由排在参数路由之后（指南 §6 L176 顺序约束）")


# ===========================================================================
# 6) 诚实终态——两种在册 id 写法都要说对话
# ===========================================================================


def _central_creation_ids() -> list[str]:
    cp = _cp()
    return sorted(
        d.capability_id
        for d in cp._creation_descriptors()
        if d.family is cp.CapabilityFamily.CREATION
    )


#: 域内有通道、中央尚无描述符的登记面（双向锁，只准缩不准长）。
CHANNELS_WITHOUT_CENTRAL_DESCRIPTOR: frozenset[str] = frozenset()


def test_channel_and_descriptor_registries_agree() -> None:
    """中央每条 creation 描述符都被域表认得；域内每条通道也都必须在中央在册。"""
    ids = _central_creation_ids()
    assert ids, "中央 creation 族描述符为空：本判据失去对象，先确认装配面是否被拆"
    unmapped = [cid for cid in ids if rprov.reserved_channel_for(cid) is None]
    assert unmapped == [], f"这些中央 id 在 creation 域查不到诚实原因（会说错话）：{unmapped}"
    covered = {rprov.reserved_channel_for(cid) for cid in ids}
    stranded = {channel for channel in rprov.CHANNEL_IDS if channel not in covered}
    assert stranded == CHANNELS_WITHOUT_CENTRAL_DESCRIPTOR, (
        f"域内通道与中央描述符面分叉：实况无描述符 {sorted(stranded)} ≠ 登记 "
        f"{sorted(CHANNELS_WITHOUT_CENTRAL_DESCRIPTOR)}"
    )


@pytest.mark.parametrize("channel", rprov.CHANNEL_IDS)
def test_honest_reason_reachable_from_both_id_spellings(channel: str) -> None:
    """域内 stable_id 与中央调用面 id 两种写法 ⇒ 同一条诚实原因（归一口只此一处）。"""
    empty = SimpleNamespace()
    plain = rprov.reserved_availability_reason(empty, channel)
    dotted = rprov.reserved_availability_reason(empty, f"{channel}.whatever")
    assert plain == dotted
    assert "未接线" in plain
    assert "可用" not in plain.replace("协议≠可用", "")  # 游标：改口宣称可用即红


def test_honest_reason_for_configured_but_unwired_factory() -> None:
    """provider 配了但实现没接：仍必须诚实 unavailable，绝不含「已经能用」。"""
    cfg = SimpleNamespace(bot_creation_tts_provider="gpt-sovits", bot_creation_image_provider="sd")
    for channel in rprov.CHANNEL_IDS:
        reason = rprov.reserved_availability_reason(cfg, f"{channel}.x")
        assert "provider 已配置但实现工厂未接入" in reason
        assert "诚实 unavailable" in reason
        # 已配 provider 不得被写成「可用」——只有「协议≠可用」这一处例外。
        assert reason.replace("协议≠可用", "").count("可用") == 0


def test_unknown_capability_id_is_not_guessed() -> None:
    """非预留面 id 不猜：既不给原因串也不谎报已配置。"""
    assert rprov.reserved_channel_for("bot.tts") is None
    assert (
        rprov.provider_configured(SimpleNamespace(bot_creation_image_provider="sd"), "bot.tts")
        is False
    )
    assert "非 creation 预留面" in rprov.reserved_availability_reason(SimpleNamespace(), "bot.tts")


def test_channel_tables_are_the_same_single_source() -> None:
    """三张表同一键集（少一张＝那条通道只会说半句话）。"""
    assert set(rprov.CHANNEL_IDS) == set(rprov.RESERVED_REASON) == set(rprov.PROVIDER_PRESENCE_KEYS)


@ASSET_SHAPES
def test_unavailable_envelope_shape_is_identical_for_both_legs(build, channel: str) -> None:
    """两腿的诚实终态在中央信封里同形：带 detail、不带呈现载荷；夹带必崩。"""
    cp = _cp()
    honest = cp.InvocationResult(
        capability_id=f"{channel}.op",
        status=cp.InvocationStatus.UNAVAILABLE,
        data={},
        detail=rprov.reserved_availability_reason(SimpleNamespace(), channel),
    )
    assert honest.status is cp.InvocationStatus.UNAVAILABLE
    assert cp.PRESENTATION_DATA_KEY not in honest.data
    with pytest.raises(pydantic.ValidationError):
        cp.InvocationResult(
            capability_id=f"{channel}.op",
            status=cp.InvocationStatus.UNAVAILABLE,
            data={cp.PRESENTATION_DATA_KEY: build().model_dump(mode="json")},
            detail="假装成功",
        )
