"""统一波 S-DRAW 常驻门：AI 绘画协议必须「出入两侧都有真身」，散文不算落点。

立门理由（每格都可注毒打死，不是存在性锁）：中央 creation 两行描述符把
``output_protocol`` 写成 ``creation.v1 CreationJob{job_id,state,asset_id?,usage?}``
（``runtime/capability_protocols.py:1815/1838``），但**全仓没有 CreationJob 这具契约**
——请求侧 DTO 齐备，结果侧只有一句散文。散文不能执法，于是三条既有教义今天都是
空头支票：

1. ``UNKNOWN_NEVER_AUTO_REDISPATCH``（未知不重发）：没有承载 ``state`` 与请求身份的
   记录，就判不出「要重发的这条是不是同一条」——幂等键（S-CREATE 补）只挂在请求侧，
   结果侧无人接收；
2. 「取消在途不假成功」（§9.1.2）：没有记录，就没有「不得把无产物写成成功」的闸；
3. 激活期任何人照散文手搓一个 dict，就成了第二真身（AGENTS 铁律：禁第二真身）。

本门把「**声明 ↔ 落点**」钉成双向锁：形态在 ``_common`` 声明一次（唯一家），中央
散文必须与之等值，只改一边即红。与 ``test_creation_protocol_parity.py`` 的分工：
那套管「两腿之间对不对等」，本套管「声明的东西有没有家」。

纪律：行号不写死；中央件只在用到的用例里惰性 import（本席禁改中央件，他席在飞装配
崩时点名外因、绝不放宽判据）；零网络、零线程、零生产配置读取。
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

import pydantic
import pytest

from plugins.bot_unified_runtime.domains.creation._common import contracts as common
from plugins.bot_unified_runtime.domains.creation.image import contracts as cimage
from plugins.bot_unified_runtime.domains.creation.tts import contracts as ctts

_PKG_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "bot_unified_runtime"
_CREATION_DIR = _PKG_ROOT / "domains" / "creation"
_DIGEST_OK = "a" * 64
_NOW = datetime(2026, 9, 22, 12, 0, 0, tzinfo=timezone.utc)


def _cp():
    """惰性取中央执行信封模块（本席禁碰中央件，只在用到时 import）。"""
    try:
        from plugins.bot_unified_runtime.runtime import capability_protocols as cp
    except Exception as exc:  # noqa: BLE001 - 只拦他席在飞把装配改崩，转为诚实跳过
        pytest.skip(f"中央 capability_protocols 当前不可导入（他席在飞，非 S-DRAW 面）: {exc}")
    return cp


def _sources(scope: Path) -> dict[str, str]:
    return {
        path.relative_to(_PKG_ROOT).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(scope.rglob("*.py"))
    }


def _descriptor(cid: str):
    return next(d for d in _cp()._creation_descriptors() if d.capability_id == cid)


def _job(**overrides: object):
    payload: dict[str, object] = {
        "job_id": "job-1",
        "state": common.CreationJobState.SUCCEEDED,
        "updated_at": _NOW,
        "assets": (common.AssetRef(asset_id="asset-1"),),
        "idempotency_key": _DIGEST_OK,
    }
    payload.update(overrides)
    return common.CreationJob(**payload)  # type: ignore[arg-type]


def _parse_output_protocol(text: str) -> tuple[str, str, tuple[str, ...]]:
    """``creation.v1 CreationJob{job_id,state,asset_id?,usage?}`` → (版本, 类型名, 字段名)。

    纯函数、可单独注毒：``?``（可选）与 ``[]``（重复）都是 wire 记号，不是字段名的一部分。
    """
    version, _, rest = text.partition(" ")
    type_name, _, tail = rest.partition("{")
    fields = tuple(
        token.strip().rstrip("?").rstrip("[]")
        for token in tail.rstrip("}").split(",")
        if token.strip()
    )
    return version.strip(), type_name.strip(), fields


def _output_protocol_drift(central_text: str) -> tuple[str, ...]:
    """纯函数：中央散文声明 ↔ 域内声明的分叉清单（空=一致）。"""
    version, type_name, fields = _parse_output_protocol(central_text)
    drift: list[str] = []
    if version != common.DECLARED_OUTPUT_PROTOCOL_VERSION:
        drift.append(f"版本 {version!r} != 域内 {common.DECLARED_OUTPUT_PROTOCOL_VERSION!r}")
    if type_name != common.DECLARED_OUTPUT_PROTOCOL_TYPE:
        drift.append(f"类型名 {type_name!r} != 域内 {common.DECLARED_OUTPUT_PROTOCOL_TYPE!r}")
    if fields != common.DECLARED_OUTPUT_PROTOCOL_FIELDS:
        drift.append(f"字段集 {fields} != 域内 {common.DECLARED_OUTPUT_PROTOCOL_FIELDS}")
    return tuple(drift)


def test_declaration_drift_detector_has_teeth() -> None:
    """自证：三型分叉（换类型名/加字段/改版本）都必须被这把尺子量出来。"""
    aligned = "creation.v1 CreationJob{job_id,state,asset_id?,usage?}"
    assert _output_protocol_drift(aligned) == ()
    assert _output_protocol_drift(aligned.replace("CreationJob", "CreationTicket")) != ()
    assert _output_protocol_drift(aligned.replace("usage?", "usage?,refund?")) != ()
    assert _output_protocol_drift(aligned.replace("creation.v1", "creation.v2")) != ()


# ===========================================================================
# 1) 落点唯一：结果记录在 _common 一具，两腿只准起别名
# ===========================================================================


def test_job_record_is_declared_once_in_common() -> None:
    """``CreationJob`` 恰有一具 ClassDef 且住在 ``_common``（第二具身即红）。"""
    homes: dict[str, list[int]] = {}
    for rel, src in _sources(_CREATION_DIR).items():
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.ClassDef) and node.name == common.DECLARED_OUTPUT_PROTOCOL_TYPE:
                homes.setdefault(rel, []).append(node.lineno)
    assert list(homes) == ["domains/creation/_common/contracts.py"], (
        f"结果记录出现第二真身或无家：{homes}"
    )
    assert all(len(v) == 1 for v in homes.values()), f"同文件内重复定义：{homes}"


def test_both_legs_alias_the_single_job_record() -> None:
    """两腿各自 ``TTSJob``/``ImageJob`` 必须是同一对象的别名（与 JobState 别名同法）。"""
    assert ctts.TTSJob is common.CreationJob
    assert cimage.ImageJob is common.CreationJob


def test_no_second_result_envelope_name_in_domain() -> None:
    """结果记录不得借用中央两个信封类名（parity 门已禁定义，本格禁别名冒名）。"""
    names = {
        name
        for name in (ctts.__all__ + cimage.__all__ + common.__all__)
    }
    assert "CapabilityResult" not in names and "InvocationResult" not in names, (
        "域内导出面出现中央信封名 = 冒名第二结果类型（§7 禁第三套）"
    )


# ===========================================================================
# 2) 声明 ↔ 落点双向锁
# ===========================================================================


def test_declared_output_protocol_matches_central_prose_on_both_legs() -> None:
    """中央两行散文的版本/类型名/字段集必须等值于域内声明（改一边即红）。"""
    for cid in ("creation.tts.synthesize", "creation.image.generate"):
        drift = _output_protocol_drift(_descriptor(cid).output_protocol)
        assert drift == (), f"{cid} 的输出协议散文与域内声明分叉：{drift}"


def test_declared_output_fields_all_have_a_home() -> None:
    """每个声明字段都要落到 DTO 的真实字段上（无家可归的声明=空头协议）。"""
    fields = set(common.CreationJob.model_fields)
    for declared in common.DECLARED_OUTPUT_PROTOCOL_FIELDS:
        target = common.DECLARED_OUTPUT_PROTOCOL_DTO_FIELDS[declared]
        assert target in fields, f"声明字段 {declared!r} 映射到不存在的字段 {target!r}"


def test_projection_map_is_the_single_mapping_and_covers_every_field() -> None:
    """映射表既不多也不少：键集合 == 声明字段集合，且值全在 DTO 里。"""
    assert set(common.DECLARED_OUTPUT_PROTOCOL_DTO_FIELDS) == set(
        common.DECLARED_OUTPUT_PROTOCOL_FIELDS
    )
    assert set(common.DECLARED_OUTPUT_PROTOCOL_DTO_FIELDS.values()) <= set(
        common.CreationJob.model_fields
    )


def test_parser_has_teeth_on_three_drift_shapes() -> None:
    """自证：解析器不是摆设——类型名漂移/字段增减/记号未剥，都要被读出来。"""
    assert _parse_output_protocol("creation.v1 CreationJob{job_id,state}") == (
        "creation.v1",
        "CreationJob",
        ("job_id", "state"),
    )
    assert _parse_output_protocol("creation.v2 CreationX{a?,b[]}")[0] == "creation.v2"
    assert _parse_output_protocol("creation.v2 CreationX{a?,b[]}")[1] == "CreationX"
    assert _parse_output_protocol("creation.v1 CreationJob{a?,b[]}") == (
        "creation.v1",
        "CreationJob",
        ("a", "b"),
    )


# ===========================================================================
# 3) 结果侧教义：三条今天才可用的不变量
# ===========================================================================


def test_success_without_asset_is_rejected() -> None:
    """「取消在途不假成功」的机器形态：SUCCEEDED 必须带产物。"""
    with pytest.raises(pydantic.ValidationError, match="产物"):
        _job(assets=())


@pytest.mark.parametrize(
    "state",
    [
        common.CreationJobState.PENDING,
        common.CreationJobState.ADMITTED,
        common.CreationJobState.RUNNING,
    ],
    ids=["pending", "admitted", "running"],
)
def test_non_terminal_state_carries_no_asset(state: common.CreationJobState) -> None:
    """未终态不得宣布产物（半程产物不对外，防「部分成功」被当成可发送）。"""
    with pytest.raises(pydantic.ValidationError, match="未终态"):
        _job(state=state)


def test_error_code_never_coexists_with_success_or_cancellation() -> None:
    """错误码只在 failed/unknown 两态成立（其余态带错误=自相矛盾的记录）。"""
    with pytest.raises(pydantic.ValidationError, match="错误码"):
        _job(error_code="price_unavailable")
    assert _job(state=common.CreationJobState.FAILED, assets=(), error_code="price_unavailable")
    assert _job(state=common.CreationJobState.UNKNOWN, assets=(), error_code="dependency_unavailable")


def test_unknown_state_requires_the_request_identity() -> None:
    """核心格：unknown 不重发只有在「带请求身份」时才判得出——无身份即拒。"""
    assert common.UNKNOWN_NEVER_AUTO_REDISPATCH is True
    with pytest.raises(pydantic.ValidationError, match="幂等"):
        _job(state=common.CreationJobState.UNKNOWN, assets=(), idempotency_key=None)
    with pytest.raises(pydantic.ValidationError):
        _job(state=common.CreationJobState.UNKNOWN, assets=(), idempotency_key="not-a-digest")


def test_cancel_timestamp_requires_the_flag_and_naive_time_is_rejected() -> None:
    """取消语义两条：时间戳必须配标记；时钟必须带时区（aware UTC 归一）。"""
    with pytest.raises(pydantic.ValidationError, match="cancel_requested"):
        _job(cancel_requested_at=_NOW)
    assert _job(cancel_requested=True, cancel_requested_at=_NOW).cancel_requested_at
    with pytest.raises(pydantic.ValidationError, match="时区"):
        # 故意造 naive 时钟：本域教义是「任务记录时间必须带时区」，此格验它真拦。
        _job(updated_at=datetime(2026, 9, 22, 12, 0, 0))  # noqa: DTZ001


def test_job_record_is_strict_and_rejects_unknown_fields() -> None:
    """wire 形态严格：未登记字段 422 不静默丢弃（extra=forbid）。"""
    with pytest.raises(pydantic.ValidationError):
        _job(some_future_field="x")
    with pytest.raises(pydantic.ValidationError):
        _job(http_status=503)


def test_state_uses_the_shared_machine_and_transitions_are_reused() -> None:
    """状态字段是共用枚举；迁移判定不另立一套，直引 ``can_transition``。"""
    assert common.CreationJob.model_fields["state"].annotation is common.CreationJobState
    succeeded = _job()
    assert succeeded.is_terminal is True
    assert succeeded.may_move_to(common.CreationJobState.RUNNING) is False
    running = _job(state=common.CreationJobState.RUNNING, assets=())
    assert running.is_terminal is False
    assert running.may_move_to(common.CreationJobState.UNKNOWN) is True
    with pytest.raises(pydantic.ValidationError):
        _job(state="teleported")


def test_usage_lines_go_through_the_common_vocabulary() -> None:
    """用量走 _common 单一词表；Token 面在结果侧同样不得伪造。"""
    line = common.UsageLine(metric="images", value="2", unit="images", status="measured")
    assert [item.metric for item in _job(usage=(line,)).usage] == ["images"]
    with pytest.raises(pydantic.ValidationError):
        common.UsageLine(metric="output_tokens", value="2", unit="tokens", status="measured")


# ===========================================================================
# 4) 已知洞的登记面（只准缩不准长：销账须同批删干净）
# ===========================================================================

#: 出站体积上限实况：语音腿有中央 8MiB 顶，绘画腿**没有**——数值待用户给出处
#: （PENDING-RULINGS §一.3 推荐 A）。本登记面负责让「这条腿无顶」不被遗忘。
OUTBOUND_BYTE_CAP_LEDGER: Mapping[str, int | None] = {
    "creation.tts.synthesize": ctts.TTS_MAX_ASSET_BYTES,
    "creation.image.generate": None,
}


def test_outbound_byte_caps_match_the_ledger() -> None:
    caps = {
        "creation.tts.synthesize": getattr(ctts, "TTS_MAX_ASSET_BYTES", None),
        "creation.image.generate": getattr(cimage, "IMAGE_MAX_ASSET_BYTES", None),
    }
    assert caps == OUTBOUND_BYTE_CAP_LEDGER, (
        f"出站体积上限与登记面分叉：实况 {caps}（绘画侧真接上限时须同步：引中央单一来源、"
        "不抄副本，并把本登记面的 None 换掉）"
    )


def test_image_asset_record_still_has_no_upper_bound() -> None:
    """诚实自证：今天确实无顶（给一个荒谬大小也照收），所以洞要登记而非假装存在。"""
    record = cimage.ImageAssetRecord(
        asset_id=common.AssetRef(asset_id="asset-9"),
        width=1024,
        height=1024,
        real_mime="image/png",
        bytes_size=10**15,
        magic_verified=True,
        exif_sanitized=True,
        review_approved=True,
    )
    assert record.bytes_size == 10**15


# ===========================================================================
# 4) 散文只准点名真存在的东西（防"契约话术写着不存在的类/字段"再犯）
# ===========================================================================

#: 声明类型名 → 它应当住在哪个已导入模块。取不到家＝散文点名了一个不存在的契约类。
_PROTOCOL_HOMES: dict[str, object] = {
    "CreationJob": common,
    "TTSJobRequest": ctts,
    "ImageJobRequest": cimage,
}


def _prose_tokens(fields: tuple[str, ...]) -> tuple[str, ...]:
    """`text|approved_reply_id` 这类"二选一"记号拆开；wire 标记 `?`/`[]` 由解析器剥掉。"""
    return tuple(
        piece.strip()
        for token in fields
        for piece in token.split("|")
        if piece.strip()
    )


def _prose_ghosts(declared: str) -> tuple[str, str, tuple[str, ...]]:
    """返回 (类型名, 该类型在册的家, 散文里点名了但真身没有的字段)。"""
    _version, type_name, fields = _parse_output_protocol(declared)
    home = _PROTOCOL_HOMES.get(type_name)
    if home is None:
        return type_name, "", tuple(_prose_tokens(fields))
    model = getattr(home, type_name, None)
    if model is None:
        return type_name, "", tuple(_prose_tokens(fields))
    real = set(getattr(model, "model_fields", {}))
    if not real:
        return type_name, "", tuple(_prose_tokens(fields))
    if type_name == common.DECLARED_OUTPUT_PROTOCOL_TYPE:
        # 结果记录只声明"对接要用的那几枚 wire 名"，wire→DTO 的映射唯一处＝域内常量。
        allowed = set(common.DECLARED_OUTPUT_PROTOCOL_DTO_FIELDS)
        missing_on_model = [
            dto
            for wire, dto in common.DECLARED_OUTPUT_PROTOCOL_DTO_FIELDS.items()
            if dto not in real
        ]
        ghosts = tuple(name for name in _prose_tokens(fields) if name not in allowed)
        return type_name, home.__name__, ghosts + tuple(missing_on_model)
    return (
        type_name,
        home.__name__,
        tuple(name for name in _prose_tokens(fields) if name not in real),
    )


@pytest.mark.parametrize(
    ("capability_id", "field_name"),
    [
        ("creation.tts.synthesize", "input_protocol"),
        ("creation.tts.synthesize", "output_protocol"),
        ("creation.image.generate", "input_protocol"),
        ("creation.image.generate", "output_protocol"),
    ],
)
def test_protocol_prose_names_only_existing_types_and_fields(
    capability_id: str, field_name: str
) -> None:
    """契约散文里**每一枚**类型名与字段名都必须在域内真身存在。

    立门前因（S-DRAW）：中央两行描述符曾写 `TtsJobRequest`（真名 `TTSJobRequest`）、
    `negative`（真名 `negative_prompt`），而结果类型 `CreationJob` 曾整型不存在。
    `_output_protocol_drift` 只锁 output 一侧的**等值**，拦不住 input 侧写错名——
    而"协议预留"的全部价值就是这句话能被下游照着写代码。
    本门刻意不要求"列全字段"（契约只声明对接用的那几枚），要求的是
    "写出来的每一枚都得是真的"：这是双向锁里此前缺失的另一半。
    """
    declared = getattr(_descriptor(capability_id), field_name)
    type_name, home_name, ghosts = _prose_ghosts(declared)
    assert home_name, (
        f"{capability_id}.{field_name} 声明的类型 {type_name!r} 在 creation 域里无家"
        "＝散文点名了一个不存在的契约类"
    )
    assert not ghosts, (
        f"{capability_id}.{field_name} 点名了 {type_name} 真身没有的字段 {list(ghosts)}"
    )


def test_protocol_prose_lock_has_teeth() -> None:
    """注毒：换掉类名 / 换掉字段名两种腐化都必须被抓住（否则上面的门是空转）。"""
    good = _descriptor("creation.image.generate").input_protocol
    assert _prose_ghosts(good)[2] == ()

    renamed_type = _prose_ghosts(good.replace("ImageJobRequest", "ImageRequest"))
    assert renamed_type[1] == "", f"类名写错没被抓：{renamed_type}"

    renamed_field = _prose_ghosts(good.replace("negative_prompt", "negative"))
    assert "negative" in renamed_field[2], f"字段名写错没被抓：{renamed_field}"
