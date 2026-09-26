"""SEAT-S89：绘画协议「八段逐段对账」的常驻机器门（零网络／零真实出图／零发消息）。

为什么要有这一件（mandate 目标 4 的验收面）
------------------------------------------------
前席把八段"补全"成了一句汇总话（"八段补全＋provenance＋mock provider＋fail-closed"），
**从来没有人一段一段对过账**。本波反复踩的坑正是这个：字段声明在契约里、名字也叫对了，
但没有任何一处断言它存在、没有一处判它取值、执行路径根本不读它——即"在册无牙"。把
"字段存在"当成"这一段的契约成立"，就是拿代理指标当结论。

本件把对账变成五把可注毒打死的尺：
① **在册性**：每段载体成员必须解析得到（改名/删字段 ⇒ 红）——治形态③"有字段有读点却
   无一处断言它存在"。
② **覆盖面**：六具载体 DTO 的**每一个**字段都必须被某一段认领，且只认给一段 ⇒ 往契约里
   塞一枚名字对不上的空字段凑数、或把同一枚牙算两次，当场红。
③ **类型**：被认领的字段不得是裸 ``Any``、不得是 ``dict``/``list`` 一把抓（治形态②）。
④ **读点**：逐字段申报证据 ``(文件, 接收者, 属性)``，**接收者限定**——``caps.provider``
   不得替 ``job.provider`` 作证（按名取值是 AST 尺的盲区，本仓踩过：本件第一版就是这样
   把 11 枚无牙字段误判成有牙，被自己的方向锁当场打红）。申报的证据必须在盘上真存在
   （不许凭空写），没证据的字段必须进**无牙账**并写明理由；两本账与现算**集合相等**，
   故只准降不准升。
⑤ **缺位可见**：每段一条"坏形必被拒 + 好形须放行"的配对臂（只有前者会红＝空跑判据）。

另两组行为臂（§2 的账）：``@runtime_checkable`` 的 ``isinstance`` 只查**方法名**，签名与
返回形态一概不管 ⇒ 光"mock 通过"推不出"真 provider 可用"。本件自带一枚名字全对、签名全
错的假适配器，断言它过得了 isinstance、**过不了**同形尺；再自带一枚回鸭子替身的适配器，
断言它在边界被拒收（补牙前它会静默降成 DEGRADED）。

纪律：只读、只构造 DTO 与假适配器，不起线程、不落库、不发网络、不碰配置面。
"""

from __future__ import annotations

import ast
import inspect
import typing
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pydantic
import pytest

from plugins.bot_unified_runtime.domains.creation._common import contracts as common
from plugins.bot_unified_runtime.domains.creation.image import contracts as cimage
from plugins.bot_unified_runtime.domains.creation.image import engine_provider as ep

_CREATION_DIR = (
    Path(__file__).resolve().parent.parent
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "creation"
)
_ENGINE = "image/engine_provider.py"
_STORE = "_common/job_store.py"
#: 判据谓词件：八段的交集判据一律住在契约里（``size_supported`` 一族），执行面只**调用**
#: 已登记件。故"按名取值"的证据点落在契约文件上，不在执行件里——这是家规，不是漏登。
_PRED = "image/contracts.py"
_FILES = (_ENGINE, _STORE, _PRED)
_DIGEST64 = "a" * 64
_AWARE = datetime(2026, 9, 24, tzinfo=timezone.utc)

#: 无证据字段的统一记号（区别于"忘了登记"——忘了登记会被尺②/尺④的集合相等当场打红）。
NO_EVIDENCE: tuple[tuple[str, str, str], ...] = ()


def _cp():
    try:
        from plugins.bot_unified_runtime.runtime import capability_protocols as cp
    except Exception as exc:  # noqa: BLE001 - 只拦他席在飞把中央装配改崩
        pytest.skip(f"中央 capability_protocols 当前不可导入（他席在飞，非本席面）: {exc}")
    return cp


# ---------------------------------------------------------------------------
# 尺的输入 1：载体登记表（六具 DTO＝八段的"户口"，逐字段归属到段）
# ---------------------------------------------------------------------------

CARRIER_MODELS: dict[str, type[common.CreationContractBase]] = {
    "ImageJobRequest": cimage.ImageJobRequest,
    "ImageProviderCapabilities": cimage.ImageProviderCapabilities,
    "ImageAssetRecord": cimage.ImageAssetRecord,
    "CreationJob": common.CreationJob,
    "CreationProvenance": common.CreationProvenance,
    "AssetRef": common.AssetRef,
}

#: 段号 → (段名, 该段认领的 ``模型.字段``)。段序取 mandate 原文八段。
SEGMENT_CLAIMS: dict[int, tuple[str, frozenset[str]]] = {
    1: (
        "请求",
        frozenset(
            {
                "ImageJobRequest.task",
                "ImageJobRequest.prompt",
                "ImageJobRequest.provider",
                "ImageJobRequest.model",
                "ImageJobRequest.workspace_id",
                "ImageJobRequest.version",
                "ImageJobRequest.idempotency_key",
                "CreationJob.idempotency_key",
            }
        ),
    ),
    2: (
        "风格参考（参考图与权重）",
        frozenset(
            {
                "ImageJobRequest.assets",
                "ImageJobRequest.mask",
                "ImageProviderCapabilities.max_reference_images",
                "AssetRef.asset_id",
                "AssetRef.pixel_count",
                "AssetRef.weight",
            }
        ),
    ),
    3: (
        "负面提示",
        frozenset(
            {
                "ImageJobRequest.negative_prompt",
                "ImageProviderCapabilities.supports_negative_prompt",
            }
        ),
    ),
    4: (
        "尺寸·步数·CFG·seed（含件数 count）",
        frozenset(
            {
                "ImageJobRequest.size",
                "ImageJobRequest.steps",
                "ImageJobRequest.guidance",
                "ImageJobRequest.seed",
                "ImageJobRequest.count",
                "ImageProviderCapabilities.provider",
                "ImageProviderCapabilities.max_steps",
                "ImageProviderCapabilities.sizes",
                "ImageProviderCapabilities.resolution_tiers",
                "ImageProviderCapabilities.max_guidance",
                "ImageProviderCapabilities.supported_tasks",
                "ImageAssetRecord.width",
                "ImageAssetRecord.height",
                "ImageAssetRecord.frames",
            }
        ),
    ),
    5: (
        "进度事件",
        frozenset(
            {
                "CreationJob.job_id",
                "CreationJob.state",
                "CreationJob.updated_at",
                "CreationJob.provider_operation",
                "CreationJob.cancel_requested",
                "CreationJob.cancel_requested_at",
            }
        ),
    ),
    6: (
        "结果件（含 AssetRef）",
        frozenset(
            {
                "CreationJob.assets",
                "CreationJob.usage",
                "ImageAssetRecord.asset_id",
                "ImageAssetRecord.real_mime",
                "ImageAssetRecord.bytes_size",
                "ImageAssetRecord.magic_verified",
                "ImageAssetRecord.exif_sanitized",
                "ImageAssetRecord.review_approved",
                "ImageAssetRecord.content_sha256",
                "ImageAssetRecord.usage",
                "ImageAssetRecord.cost",
            }
        ),
    ),
    7: ("失败语义", frozenset({"CreationJob.error_code"})),
    8: (
        "来源与水印元数据",
        frozenset(
            {
                "CreationProvenance.generator_principal",
                "CreationProvenance.provider",
                "CreationProvenance.model",
                "CreationProvenance.prompt_digest",
                "CreationProvenance.generated_at",
                "CreationProvenance.license_statement",
                "CreationProvenance.exif_stripped",
                "CreationProvenance.marking",
                "CreationProvenance.marking_applied",
                "CreationProvenance.marking_actor",
                "ImageAssetRecord.provenance",
            }
        ),
    ),
}

# ---------------------------------------------------------------------------
# 尺的输入 2：逐字段读点证据（``NO_EVIDENCE`` ＝诚实的"执行面不按名取值"）
# ---------------------------------------------------------------------------

FIELD_EVIDENCE: dict[str, tuple[tuple[str, str, str], ...]] = {
    # 段 1
    "ImageJobRequest.task": ((_ENGINE, "job", "task"),),
    "ImageJobRequest.prompt": NO_EVIDENCE,
    "ImageJobRequest.negative_prompt": ((_PRED, "request", "negative_prompt"),),
    "ImageJobRequest.provider": NO_EVIDENCE,
    "ImageJobRequest.model": ((_ENGINE, "job", "model"),),
    "ImageJobRequest.workspace_id": NO_EVIDENCE,
    "ImageJobRequest.version": NO_EVIDENCE,
    "ImageJobRequest.idempotency_key": ((_ENGINE, "job", "idempotency_key"),),
    "CreationJob.idempotency_key": ((_STORE, "job", "idempotency_key"),),
    # 段 2
    "ImageJobRequest.assets": ((_ENGINE, "job", "assets"),),
    "ImageJobRequest.mask": NO_EVIDENCE,
    "ImageProviderCapabilities.max_reference_images": ((_PRED, "caps", "max_reference_images"),),
    "AssetRef.asset_id": NO_EVIDENCE,
    "AssetRef.pixel_count": NO_EVIDENCE,
    "AssetRef.weight": NO_EVIDENCE,
    # 段 3
    "ImageProviderCapabilities.supports_negative_prompt": (
        (_PRED, "caps", "supports_negative_prompt"),
    ),
    # 段 4
    "ImageJobRequest.size": ((_ENGINE, "job", "size"),),
    "ImageJobRequest.steps": ((_ENGINE, "job", "steps"),),
    "ImageJobRequest.guidance": ((_ENGINE, "job", "guidance"),),
    "ImageJobRequest.seed": NO_EVIDENCE,
    "ImageJobRequest.count": ((_ENGINE, "job", "count"),),
    "ImageProviderCapabilities.provider": ((_ENGINE, "caps", "provider"),),
    "ImageProviderCapabilities.max_steps": ((_ENGINE, "caps", "max_steps"),),
    "ImageProviderCapabilities.sizes": ((_ENGINE, "caps", "sizes"),),
    "ImageProviderCapabilities.resolution_tiers": NO_EVIDENCE,
    "ImageProviderCapabilities.max_guidance": ((_ENGINE, "caps", "max_guidance"),),
    "ImageProviderCapabilities.supported_tasks": ((_ENGINE, "caps", "supported_tasks"),),
    "ImageAssetRecord.width": NO_EVIDENCE,
    "ImageAssetRecord.height": NO_EVIDENCE,
    "ImageAssetRecord.frames": NO_EVIDENCE,
    # 段 5
    "CreationJob.job_id": ((_STORE, "job", "job_id"),),
    "CreationJob.state": ((_STORE, "job", "state"), (_ENGINE, "outcome", "state")),
    "CreationJob.updated_at": ((_STORE, "job", "updated_at"),),
    "CreationJob.provider_operation": ((_STORE, "job", "provider_operation"),),
    "CreationJob.cancel_requested": ((_STORE, "job", "cancel_requested"),),
    "CreationJob.cancel_requested_at": ((_STORE, "job", "cancel_requested_at"),),
    # 段 6
    "CreationJob.assets": ((_STORE, "job", "assets"), (_ENGINE, "outcome", "assets")),
    "CreationJob.usage": ((_STORE, "job", "usage"),),
    "ImageAssetRecord.asset_id": ((_ENGINE, "asset", "asset_id"),),
    "ImageAssetRecord.real_mime": NO_EVIDENCE,
    "ImageAssetRecord.bytes_size": NO_EVIDENCE,
    "ImageAssetRecord.magic_verified": NO_EVIDENCE,
    "ImageAssetRecord.exif_sanitized": NO_EVIDENCE,
    "ImageAssetRecord.review_approved": NO_EVIDENCE,
    "ImageAssetRecord.content_sha256": NO_EVIDENCE,
    "ImageAssetRecord.usage": NO_EVIDENCE,
    "ImageAssetRecord.cost": NO_EVIDENCE,
    # 段 7
    "CreationJob.error_code": ((_STORE, "job", "error_code"), (_ENGINE, "outcome", "error_code")),
    # 段 8
    "ImageAssetRecord.provenance": ((_ENGINE, "row", "provenance"),),
    "CreationProvenance.generator_principal": NO_EVIDENCE,
    "CreationProvenance.provider": NO_EVIDENCE,
    "CreationProvenance.model": NO_EVIDENCE,
    "CreationProvenance.prompt_digest": NO_EVIDENCE,
    "CreationProvenance.generated_at": NO_EVIDENCE,
    "CreationProvenance.license_statement": NO_EVIDENCE,
    "CreationProvenance.exif_stripped": NO_EVIDENCE,
    "CreationProvenance.marking": NO_EVIDENCE,
    "CreationProvenance.marking_applied": NO_EVIDENCE,
    "CreationProvenance.marking_actor": NO_EVIDENCE,
}

#: **无牙账**：每枚必须带「为什么这样仍算诚实」+「何时该销账」。挂账理由过短即红
#: （见 :func:`test_every_ledgered_no_readpoint_carries_a_reason`——本席自己先写了「同上」，
#: 被这条锁当场打红，故此处逐枚写全，不许再退化成指针）。
NO_READPOINT_LEDGER: dict[str, str] = {
    # 段 1：prompt 随**整个已验请求对象**进 submit()；闸＝契约拒空/超长，另有幂等身份牙
    # （parity 件逐字段锁「改 prompt ⇒ 身份变」）。销账条件：执行面出现按名取值点。
    "ImageJobRequest.prompt": "整包进 submit()；闸=契约拒空白与超 4000＋身份牙；执行面无按名读点",
    "ImageJobRequest.provider": "只随整包进 submit；caps.provider 属能力目录侧，不得替请求侧作证",
    "ImageJobRequest.workspace_id": "装配事实，job_store 走构造 kwargs 侧；执行面不判它",
    "ImageJobRequest.version": "装配事实（工作区版本），执行面今日无任何判据⇒真残余",
    # 段 2：mask 的闸在契约 _task_shape（仅 inpaint 可用且必用），值本体随整包进 submit。
    "ImageJobRequest.mask": "契约 _task_shape 已拦（仅 inpaint 可用、inpaint 必带）；值不出契约",
    "AssetRef.asset_id": "闸=pattern＋显式拒路径/URL/穿越；出口只带 asset_id 字符串本身（Q-1）",
    "AssetRef.pixel_count": "闸=Field 值域 1..20MP；执行面不按名取⇒无 provider 交集，真残余",
    "AssetRef.weight": "进幂等身份（改权重即改请求身份）；执行面不按名取⇒provider 可整条忽略",
    # 段 4b：seed 有值域与身份牙，却**没有任何一处**据它要求可复现（对比 TTS 侧
    # derive_seed＝缓存键派生，同句恒同音）。绘图的「同 seed 同图」无人执法⇒真残余。
    "ImageJobRequest.seed": "有值域(ge=0)与身份牙，无可复现判据；TTS 侧 derive_seed 无对应物",
    "ImageProviderCapabilities.resolution_tiers": "只在册描述能力，执行面不按名取⇒分辨率档不计费不收紧",
    # 段 6/8：结果件的**闸**有牙（三闸不过就构造不出来），出口只带走 asset_id 与
    # provenance 的**有无**；明细（尺寸/MIME/字节/摘要/成本/溯源内层八字段）在域内
    # **无处可去**——creation 无 asset 落盘面、job_store 也只存 AssetRef。⇒ 需裁项 Q-1。
    "ImageAssetRecord.width": "闸内字段；出口只带 asset_id 与 provenance 有无（Q-1）",
    "ImageAssetRecord.height": "闸内字段；出口只带 asset_id 与 provenance 有无（Q-1）",
    "ImageAssetRecord.frames": "闸内字段；动图帧数今天无人判（Q-1）",
    "ImageAssetRecord.real_mime": "闸内字段；MIME 真伪由构造期 magic_verified 背书，出口不读（Q-1）",
    "ImageAssetRecord.bytes_size": "闸内字段；体积无上限已另册登记（test_creation_job_protocol 自证）",
    "ImageAssetRecord.magic_verified": "由 ImageAssetRecord._gates 构造期执法，盘上无外部按名读点",
    "ImageAssetRecord.exif_sanitized": "由 _gates 构造期执法，并与 provenance.exif_stripped 交叉锁",
    "ImageAssetRecord.review_approved": "由 _gates 构造期执法（Review 不过不出 asset）",
    "ImageAssetRecord.content_sha256": "闸内字段；内容身份今天不进 presented job（Q-1）",
    "ImageAssetRecord.usage": "件内用量副本；对外计量取 CreationJob.usage，件侧无人读（Q-1）",
    "ImageAssetRecord.cost": "闸内字段；成本不经结果记录出口（Q-1）",
    "CreationProvenance.generator_principal": "闸=非空＋长度；出口只判「有没有溯源」这一位（Q-1）",
    "CreationProvenance.provider": "闸=非空；出口不点名是谁生成的（Q-1）",
    "CreationProvenance.model": "闸=非空；出口不点名是哪个模型（Q-1）",
    "CreationProvenance.prompt_digest": "闸=64hex＋显式拒原文；出口不回读摘要（Q-1）",
    "CreationProvenance.generated_at": "闸=aware-UTC；出口不比对生成时刻（Q-1）",
    "CreationProvenance.license_statement": "闸=非空（禁「出处全默认」）；出口不展示许可（Q-1）",
    "CreationProvenance.exif_stripped": "与 exif_sanitized 交叉锁（_gates 读 self.provenance）；出口不再判",
    "CreationProvenance.marking": "与 marking_applied 互为条件（本席新锁，说谎形态必拒）；出口不展示（Q-1）",
    "CreationProvenance.marking_applied": "与 marking 互为条件且须有认领人；出口不展示（Q-1）",
    "CreationProvenance.marking_actor": "打了标必须有人认领；出口不展示是谁打的（Q-1）",
}


def _all_claims() -> set[str]:
    return set().union(*(members for _t, members in SEGMENT_CLAIMS.values()))


# ---------------------------------------------------------------------------
# 尺①：在册性
# ---------------------------------------------------------------------------


def test_every_claimed_carrier_member_resolves() -> None:
    """改名/删字段/换模型 ⇒ 当场红（八段的户口不能靠注释维持）。"""
    for dotted in sorted(_all_claims()):
        model_name, field = dotted.split(".", 1)
        assert model_name in CARRIER_MODELS, f"{dotted}：模型不在载体登记表"
        model = CARRIER_MODELS[model_name]
        assert field in model.model_fields, (
            f"{dotted}：段账点名的成员在契约里不存在了（在册：{sorted(model.model_fields)}）"
        )


def test_eight_segments_are_named_one_to_eight_without_gaps() -> None:
    """段号必须恰为 1..8：mandate 的八段不许被"合并计数"糊过去（少一段就少一格账）。"""
    assert set(SEGMENT_CLAIMS) == set(range(1, 9))
    for index, (title, members) in SEGMENT_CLAIMS.items():
        assert title.strip(), f"第 {index} 段无段名"
        assert members, f"第 {index} 段没有认领任何载体成员＝该段根本不在这张表上"


# ---------------------------------------------------------------------------
# 尺②：覆盖面 + 唯一归属
# ---------------------------------------------------------------------------


def test_every_carrier_field_is_claimed_by_a_segment() -> None:
    """六具载体的每个字段都得归到某一段；无主字段＝往契约里塞了没人负责的东西。"""
    claimed = _all_claims()
    orphans = [
        f"{model_name}.{field}"
        for model_name, model in CARRIER_MODELS.items()
        for field in model.model_fields
        if f"{model_name}.{field}" not in claimed
    ]
    assert not orphans, (
        f"以下契约字段不属于任何一段：{orphans}"
        "（要么它是某段的载体⇒登记进去，要么它不该在这六具 DTO 里）"
    )


def test_no_field_is_claimed_by_two_segments() -> None:
    """一枚字段只准记在一个段名下：两处都抵账＝同一枚牙算两次。"""
    seen: dict[str, int] = {}
    for index, (_title, members) in SEGMENT_CLAIMS.items():
        for dotted in sorted(members):
            assert dotted not in seen, (
                f"{dotted} 同时被第 {seen.get(dotted)} 段与第 {index} 段认领"
            )
            seen[dotted] = index


def test_readpoint_evidence_table_covers_exactly_the_claims() -> None:
    """证据表与认领表必须集合相等：漏登记＝有人新加字段没交代它有没有牙。"""
    assert set(FIELD_EVIDENCE) == _all_claims(), (
        f"证据表缺 {sorted(_all_claims() - set(FIELD_EVIDENCE))}、"
        f"多 {sorted(set(FIELD_EVIDENCE) - _all_claims())}"
    )


# ---------------------------------------------------------------------------
# 尺③：类型
# ---------------------------------------------------------------------------


def _annotation_text(model: type[common.CreationContractBase], field: str) -> str:
    raw: Any = model.__annotations__.get(field, model.model_fields[field].annotation)
    return raw if isinstance(raw, str) else str(raw)


def test_no_claimed_field_is_bare_any_or_untyped_container() -> None:
    """逐字段查注解：裸 Any 或无类型容器一把抓 ⇒ 该段等于没契约。"""
    offenders: list[str] = []
    for dotted in sorted(_all_claims()):
        model_name, field = dotted.split(".", 1)
        text = _annotation_text(CARRIER_MODELS[model_name], field)
        stripped = text.replace(" | None", "").strip()
        if stripped == "Any" or stripped.endswith(".Any"):
            offenders.append(f"{dotted} = {text!r}（裸 Any）")
        elif stripped.split("[")[0] in ("dict", "list", "Dict", "List", "object"):
            offenders.append(f"{dotted} = {text!r}（无类型容器一把抓）")
    assert not offenders, f"以下段成员等于没有契约：{offenders}"


def test_provider_boundary_return_is_a_typed_object_not_a_dict() -> None:
    """适配器边界的返回值不许是裸 dict：``poll`` 的注解必须是那具在册 outcome 对象。"""
    hints = typing.get_type_hints(ep.ImageProvider.poll)
    assert hints.get("return") is ep.ImageProviderOutcome, (
        f"poll 返回注解漂成 {hints.get('return')!r}⇒ 边界不再有任何形态约束"
    )


def test_outcome_state_is_the_shared_enum_not_any() -> None:
    """``ImageProviderOutcome.state`` 曾是本链最要紧位置上的一枚裸 ``Any``（治形态②）。"""
    text = str(inspect.signature(ep.ImageProviderOutcome.__init__).parameters["state"].annotation)
    assert "CreationJobState" in text and "Any" not in text, f"终态注解漂了：{text!r}"


# ---------------------------------------------------------------------------
# 尺④：读点证据必须在盘上、无证据必须入账（方向锁）
# ---------------------------------------------------------------------------


def _loaded_pairs(rel: str) -> set[tuple[str, str]]:
    """``(接收者名, 被读属性)``——只认 Name 接收者的 Load 位点（写入与关键字不算）。"""
    tree = ast.parse((_CREATION_DIR / rel).read_text(encoding="utf-8"))
    pairs: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.ctx, ast.Load)
            and isinstance(node.value, ast.Name)
        ):
            pairs.add((node.value.id, node.attr))
    return pairs


@pytest.fixture(scope="module")
def loaded_by_file() -> dict[str, set[tuple[str, str]]]:
    return {rel: _loaded_pairs(rel) for rel in _FILES}


def test_every_declared_readpoint_evidence_is_live(loaded_by_file) -> None:
    """证据不许凭空写：申报的 (文件,接收者,属性) 必须真在盘上（防"注释承诺一把锁"）。"""
    fake = [
        triple
        for triples in FIELD_EVIDENCE.values()
        for triple in triples
        if (triple[1], triple[2]) not in loaded_by_file[triple[0]]
    ]
    assert not fake, f"以下读点证据在盘上不存在：{fake}"


def test_no_readpoint_ledger_equals_evidence_void_in_both_directions() -> None:
    """无牙账必须恰等于"证据为空"的字段集合：多一枚＝新长出无牙字段，少一枚＝补了牙没销账。"""
    void = {dotted for dotted, triples in FIELD_EVIDENCE.items() if not triples}
    assert void == set(NO_READPOINT_LEDGER), (
        f"无牙账与现实分叉：无证据却未入账 {sorted(void - set(NO_READPOINT_LEDGER))}；"
        f"账里挂着却已有证据 {sorted(set(NO_READPOINT_LEDGER) - void)}"
    )


def test_every_ledgered_no_readpoint_carries_a_reason() -> None:
    """挂账不是免检：每枚都要写清"为什么仍算诚实"与"何时该销账"。"""
    for dotted, reason in NO_READPOINT_LEDGER.items():
        assert len(reason.strip()) >= 12, f"{dotted} 的挂账理由形同虚设：{reason!r}"


def test_every_segment_has_at_least_one_field_with_live_teeth() -> None:
    """每段至少要有一枚真被执行面按名取值的字段，否则整段只是"读过一眼的名字"。"""
    toothed = {dotted for dotted, triples in FIELD_EVIDENCE.items() if triples}
    for index, (title, members) in SEGMENT_CLAIMS.items():
        assert members & toothed, (
            f"第 {index} 段（{title}）无任何按名读点＝整段在册无牙，必须补或明写挂账"
        )


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------


def _provenance(**overrides: Any) -> common.CreationProvenance:
    payload: dict[str, Any] = {
        "generator_principal": "user:1",
        "provider": "provider_a",
        "model": "image-model-1",
        "prompt_digest": _DIGEST64,
        "generated_at": _AWARE,
        "license_statement": "可商用（示例）",
        "exif_stripped": True,
    }
    payload.update(overrides)
    return common.CreationProvenance(**payload)


def _asset(**overrides: Any) -> cimage.ImageAssetRecord:
    payload: dict[str, Any] = {
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
    return cimage.ImageAssetRecord(**payload)


def _job(**overrides: Any) -> cimage.ImageJobRequest:
    payload: dict[str, Any] = {
        "task": "text_to_image",
        "prompt": "釉瑚风格的云母卡片插画",
        "provider": "mock-image",
        "model": "image-model-1",
        "size": "1024x1024",
        "workspace_id": "ws_main",
        "version": "rev-1",
    }
    payload.update(overrides)
    return cimage.ImageJobRequest(**payload)


def _handle_with(provider: Any, **job_over: Any) -> Any:
    cp = _cp()
    return ep.handle(
        cp.CapabilityRequest(
            capability_id="creation.image.generate",
            payload={"job": _job(**job_over)},
            context={"config": SimpleNamespace(), "image_provider": provider},
        )
    )


# ---------------------------------------------------------------------------
# 尺⑤：缺位可见——逐段"坏形必拒 + 好形放行"配对臂
# ---------------------------------------------------------------------------


def test_segment1_request_rejects_unsupported_and_blank() -> None:
    with pytest.raises(pydantic.ValidationError):
        _job(workflow="arbitrary")  # extra=forbid：未支持参数不静默丢弃
    with pytest.raises(pydantic.ValidationError):
        _job(prompt="   ")
    assert _job().prompt.strip()  # 配对臂：好形必须放行，否则判据可写成恒拒


def test_segment2_reference_weight_bounds_and_task_pairing() -> None:
    assert common.AssetRef(asset_id="in-1").weight is None  # 不猜强度
    assert common.AssetRef(asset_id="in-1", weight=0.5).weight == 0.5
    with pytest.raises(pydantic.ValidationError):
        common.AssetRef(asset_id="in-1", weight=1.5)
    with pytest.raises(pydantic.ValidationError):
        _job(task="image_to_image")  # 参考图缺失＝任务不成立
    assert _job(task="image_to_image", assets=({"asset_id": "in-1"},)).assets


def test_segment3_negative_prompt_cap_is_real() -> None:
    assert _job(negative_prompt="模糊").negative_prompt == "模糊"
    with pytest.raises(pydantic.ValidationError):
        _job(negative_prompt="x" * (cimage.IMAGE_MAX_NEGATIVE_CHARS + 1))
    with pytest.raises(pydantic.ValidationError):
        _job(negative_prompt="   ")


@pytest.mark.parametrize(
    "bad",
    [
        {"guidance": 0},
        {"guidance": cimage.IMAGE_MAX_GUIDANCE + 1},
        {"count": 0},
        {"count": cimage.IMAGE_MAX_COUNT + 1},
        {"seed": -1},
        {"steps": cimage.IMAGE_MAX_STEPS + 1},
        {"size": "1024X1024"},
    ],
    ids=["CFG零", "CFG超上界", "件数零", "件数超上限", "负seed", "步数超上限", "大写X"],
)
def test_segment4_parameter_domain_rejects_each_boundary(bad: dict[str, Any]) -> None:
    with pytest.raises(pydantic.ValidationError):
        _job(**bad)  # type: ignore[arg-type]
    assert _job().size == "1024x1024"  # 配对臂（同一夹具，好形照收）


def test_segment4_provider_intersection_rejects_and_admits() -> None:
    caps = cimage.ImageProviderCapabilities(
        provider="p",
        max_steps=20,
        sizes=("1024x1024",),
        supported_tasks=("text_to_image",),
        max_guidance=8.0,
    )
    assert cimage.steps_supported(20, caps) and not cimage.steps_supported(21, caps)
    assert cimage.size_supported("1024x1024", caps) and not cimage.size_supported("512x512", caps)
    assert cimage.task_supported("text_to_image", caps) and not cimage.task_supported("inpaint", caps)
    assert cimage.guidance_supported(8.0, caps) and not cimage.guidance_supported(8.5, caps)
    # provider 不声明 ⇒ 不额外收紧（缺省语义，不是放行越界：全局域仍在 DTO 拦过一遍）。
    assert cimage.guidance_supported(50.0, caps.model_copy(update={"max_guidance": None}))


def test_segment5_progress_is_poll_only_and_rejects_raw_state_string() -> None:
    assert cimage.IMAGE_PROGRESS_TRANSPORT == "poll"
    assert cimage.IMAGE_PROGRESS_SSE_WIRED is False
    assert cimage.ImageProgressMode.POLL.value == "poll"
    with pytest.raises((TypeError, ValueError)):
        ep.ImageProviderOutcome("succeeded")  # 裸字符串终态（此前它是 Any）
    with pytest.raises((TypeError, ValueError)):
        ep.ImageProviderOutcome(None)
    assert (
        ep.ImageProviderOutcome(common.CreationJobState.RUNNING).state
        is common.CreationJobState.RUNNING
    )


@pytest.mark.parametrize(
    "bad", [{"magic_verified": False}, {"exif_sanitized": False}, {"review_approved": False}]
)
def test_segment6_result_gate_rejects_each_unverified_shape(bad: dict[str, Any]) -> None:
    with pytest.raises(pydantic.ValidationError):
        _asset(**bad)  # type: ignore[arg-type]
    assert _asset().magic_verified is True  # 配对臂


def test_segment6_non_terminal_may_not_announce_artifacts() -> None:
    ref = common.AssetRef(asset_id="a-1")
    with pytest.raises(pydantic.ValidationError):
        common.CreationJob(
            job_id="j", state=common.CreationJobState.RUNNING,
            updated_at=_AWARE, assets=(ref,),
        )
    with pytest.raises(pydantic.ValidationError):
        common.CreationJob(job_id="j", state=common.CreationJobState.SUCCEEDED, updated_at=_AWARE)
    assert common.CreationJob(
        job_id="j", state=common.CreationJobState.SUCCEEDED, updated_at=_AWARE, assets=(ref,)
    ).is_terminal


def test_segment7_error_code_is_in_catalog_and_pairs_terminal_state() -> None:
    ok = ep.ImageProviderOutcome(
        common.CreationJobState.FAILED, error_code="dependency_unavailable"
    )
    assert ok.error_code == "dependency_unavailable"
    with pytest.raises((TypeError, ValueError)):
        ep.ImageProviderOutcome(common.CreationJobState.FAILED, error_code="oops_not_a_code")
    base: dict[str, Any] = {"job_id": "j1", "updated_at": _AWARE}
    with pytest.raises(pydantic.ValidationError):
        common.CreationJob(
            **base, state=common.CreationJobState.SUCCEEDED, error_code="budget_exceeded"
        )
    with pytest.raises(pydantic.ValidationError):
        common.CreationJob(**base, state=common.CreationJobState.UNKNOWN)  # 无身份⇒教义悬空


def test_segment7_http_mapping_is_one_home_for_the_catalog() -> None:
    assert common.CREATION_ERROR_CATALOG["dependency_unavailable"] == 503
    assert cimage.IMAGE_ERROR_CATALOG == dict(common.CREATION_ERROR_CATALOG)
    assert len(common.CREATION_ERROR_CATALOG) == 4


def test_segment8_provenance_rejects_raw_prompt_and_naive_time() -> None:
    assert _provenance().marking == "none"  # 配对臂：默认诚实"未打标"可构造
    with pytest.raises(pydantic.ValidationError):
        _provenance(prompt_digest="这张图里有一只猫")
    with pytest.raises(pydantic.ValidationError):
        _provenance(generated_at=datetime(2026, 9, 24))  # noqa: DTZ001 - 故意造 naive 时刻
    with pytest.raises(pydantic.ValidationError):
        _provenance(license_statement="")  # 许可不得为空⇒不许"出处全默认"


# ---------------------------------------------------------------------------
# 段 8 的另一半：水印/标识（SEAT-S04 把第 8 段整段读成"溯源"，漏了这半腿）
# ---------------------------------------------------------------------------


def test_watermark_half_of_segment8_exists_and_is_a_closed_set() -> None:
    assert {"marking", "marking_applied", "marking_actor"} <= set(
        common.CreationProvenance.model_fields
    )
    # 封闭集：不许 "wm"/"已加水印" 各写一家。清单派生自 Literal，不手抄第二份。
    assert common.MARKING_KINDS == frozenset(typing.get_args(common.MarkingKind))
    assert "none" in common.MARKING_KINDS
    with pytest.raises(pydantic.ValidationError):
        _provenance(marking="visible_wm")  # 近似名不放行


@pytest.mark.parametrize(
    "payload",
    [
        {"marking": "none", "marking_applied": True, "marking_actor": "a"},
        {"marking": "visible_watermark", "marking_applied": False},
        {"marking": "c2pa_manifest", "marking_applied": True, "marking_actor": "   "},
    ],
    ids=["声称应用却没种类", "声称种类却没应用", "打了标却无人认领"],
)
def test_watermark_claim_and_fact_must_agree(payload: dict[str, Any]) -> None:
    """三枚"说谎形态"逐个打死：种类与事实分叉、无人认领的标识声明都不可入册。"""
    with pytest.raises(pydantic.ValidationError):
        _provenance(**payload)


def test_watermark_both_honest_states_are_representable() -> None:
    assert _provenance().marking_applied is False
    marked = _provenance(
        marking="visible_watermark", marking_applied=True, marking_actor="provider_a"
    )
    assert marked.marking_applied is True and marked.marking_actor == "provider_a"


def test_watermark_survives_the_asset_gate_and_is_not_folded_into_exif() -> None:
    """标识声明与"EXIF 已剥净"必须同读：嵌入清干净了，标识事实才更有必要在册。"""
    marked = _provenance(
        marking="implicit_metadata", marking_applied=True, marking_actor="provider_a"
    )
    assert _asset(provenance=marked).provenance is not None
    with pytest.raises(pydantic.ValidationError):
        _asset(
            provenance=_provenance(
                marking="implicit_metadata",
                marking_applied=True,
                marking_actor="provider_a",
                exif_stripped=False,
            )
        )


# ---------------------------------------------------------------------------
# §2 配套件：适配器协议是不是真契约 + mock 是否同形
# ---------------------------------------------------------------------------

_PROTOCOL_MEMBERS = ("offline_mock", "capabilities", "submit", "poll", "cancel")


def _param_shape(func: Any) -> tuple[str, ...]:
    sig = inspect.signature(func)
    return tuple(
        f"{p.name}:{p.kind.name}"
        + ("" if p.default is inspect.Parameter.empty else f"={p.default!r}")
        for p in sig.parameters.values()
    )


def _member_shape(owner: Any, name: str) -> tuple[Any, ...]:
    """成员形状（参数名＋种类＋缺省）；不比较返回值文本，返回值另有专条锁。"""
    member = inspect.getattr_static(owner, name, None)
    if member is None:
        return ("MISSING",)
    if isinstance(member, property):
        return ("property", _param_shape(member.fget) if member.fget else ("NO_GETTER",))
    if callable(member):
        return ("method", _param_shape(member))
    return ("PLAIN_ATTR", type(member).__name__)


def test_protocol_is_an_implementable_closed_member_set() -> None:
    """协议必须是**可实现的最小封闭面**：四方法＋一枚判别位，多一桩少一桩都算改协议。"""
    members = set(ep.ImageProvider.__protocol_attrs__)
    assert members == set(_PROTOCOL_MEMBERS), f"适配器协议面漂移：{sorted(members)}"


@pytest.mark.parametrize("name", _PROTOCOL_MEMBERS)
def test_mock_shape_is_identical_to_what_the_protocol_demands(name: str) -> None:
    """mock 每个成员的形状必须与协议声明逐字同形（参数名与种类都算）。"""
    assert _member_shape(ep.ImageProvider, name) == _member_shape(ep.MockImageProvider, name), (
        f"mock.{name} 与协议声明不同形⇒「mock 跑通」不能推断「真适配器可用」"
    )


class _LooksRightButIsWrong:
    """名字全对、签名全错的假适配器：专治"拿 isinstance 当合面证明"。"""

    offline_mock = False

    def capabilities(self) -> Any:
        return None

    def submit(self, job: Any, extra: int = 0) -> str:  # 多一个参数
        return "op"

    def poll(self, operation: Any) -> Any:
        return ep.ImageProviderOutcome(common.CreationJobState.RUNNING)

    def cancel(self) -> bool:  # 少一个参数
        return True


def test_runtime_checkable_is_name_only_so_the_parity_ruler_is_the_real_teeth() -> None:
    """自证同形尺有牙：这枚假适配器必须过得了 isinstance、过不了同形尺。

    若有人把同形尺放宽成"名字一致即可"，本条当场红。反过来若哪天 isinstance 真会查签名了，
    第一条断言也会红——两臂都在，不许单方面把这条判据说成已足够。
    """
    assert isinstance(_LooksRightButIsWrong(), ep.ImageProvider), (
        "前提不成立：isinstance 竟然查了签名 ⇒ 同形尺成了重复劳动，判据要重想"
    )
    diverging = [
        name
        for name in _PROTOCOL_MEMBERS
        if _member_shape(ep.ImageProvider, name) != _member_shape(_LooksRightButIsWrong, name)
    ]
    assert {"submit", "cancel"} <= set(diverging), f"同形尺看不见签名分叉：{diverging}"


def test_adapter_terminal_vocabulary_has_one_home() -> None:
    """终态词表只有一个家：适配器不许自造状态词（"done"/"ok" 一类）。"""
    with pytest.raises((TypeError, ValueError)):
        ep.ImageProviderOutcome("done")
    for state in common.CreationJobState:
        assert ep.ImageProviderOutcome(state).state is state


def test_duck_typed_outcome_is_refused_at_the_boundary_not_downgraded_quietly() -> None:
    """补牙前最大的病灶：适配器返回**鸭子替身**时 handle 直接读属性，于是
    ``state="succeeded"``（字符串）被 ``is`` 判成未成功 ⇒ **静默**降成 DEGRADED。mock 回
    枚举、真适配器可能回字符串，两者形状不同却只有 mock 那条路被跑过——"mock 通过"于是
    被当成"真 provider 可用"。

    补牙后在边界拒收：异常上抛 ⇒ 经 ``INVOKER_ERROR_DATA_KEY`` 那条已落地通道交回层 1 出
    诊断卡。刻意不就地兜成 FAILED：把接线错误洗成一条普通业务失败，是本仓在主动投递面上
    付过两次账的老病。
    """
    cp = _cp()

    class _Quacks:
        offline_mock = False

        def capabilities(self) -> Any:
            return ep.MockImageProvider().capabilities()

        def submit(self, job: Any) -> str:
            return "op-1"

        def poll(self, operation: str) -> Any:
            return SimpleNamespace(state="succeeded", assets=(), error_code=None)

        def cancel(self, operation: str) -> bool:
            return False

    assert isinstance(_Quacks(), ep.ImageProvider)  # 名字面"合协议"
    with pytest.raises(TypeError):
        _handle_with(_Quacks())
    # 反向臂：合规形态照跑（否则"凡返回必抛"也是恒真判据）。
    assert _handle_with(ep.MockImageProvider()).status is cp.InvocationStatus.DEGRADED


def test_dict_shaped_artifact_is_refused_at_the_boundary_too() -> None:
    """产物不许是裸 dict：那样 magic/EXIF/Review 三闸根本没跑过，闸形同被绕过。"""

    class _DictAsset:
        offline_mock = False

        def capabilities(self) -> Any:
            return ep.MockImageProvider().capabilities()

        def submit(self, job: Any) -> str:
            return "op-1"

        def poll(self, operation: str) -> Any:
            return SimpleNamespace(
                state=common.CreationJobState.SUCCEEDED,
                assets=({"asset_id": "a"},),
                error_code=None,
            )

        def cancel(self, operation: str) -> bool:
            return False

    with pytest.raises(TypeError):
        _handle_with(_DictAsset())


# ---------------------------------------------------------------------------
# 补牙后的新读点：逐条正/反两臂（证明不是恒真判据）
# ---------------------------------------------------------------------------


class _TwoImageProvider(ep.MockImageProvider):
    """真适配器形状（offline_mock=False），一次交付 ``pieces`` 件。"""

    pieces = 2

    @property
    def offline_mock(self) -> bool:
        return False

    def poll(self, operation: str) -> ep.ImageProviderOutcome:
        base = super().poll(operation)
        if not base.assets:
            return base
        extra = tuple(
            base.assets[0].model_copy(update={"asset_id": common.AssetRef(asset_id=f"a-{i}")})
            for i in range(1, self.pieces)
        )
        return ep.ImageProviderOutcome(base.state, assets=base.assets + extra)


class _OneImageProvider(_TwoImageProvider):
    pieces = 1


class _NarrowGuidanceProvider(ep.MockImageProvider):
    """真实适配器形状：明确声明一个 CFG 上界（据此该拦下越界的 guidance）。"""

    ceiling = 6.0

    @property
    def offline_mock(self) -> bool:
        return False

    def capabilities(self) -> cimage.ImageProviderCapabilities:
        return super().capabilities().model_copy(update={"max_guidance": self.ceiling})


def test_usage_settles_by_delivered_pieces_not_a_hardcoded_one() -> None:
    """多图按实结算：交付 2 件 ⇒ 计量 2（此前恒写 1，两图一单与一图一单在账上长一样）。"""
    cp = _cp()
    result = _handle_with(_TwoImageProvider(), count=2)
    assert result.status is cp.InvocationStatus.OK
    body = result.data[cp.PRESENTATION_DATA_KEY]
    images = [line for line in body["usage"] if line["metric"] == "images"]
    assert len(images) == 1 and str(images[0]["value"]) == "2"
    assert len(body["assets"]) == 2


def test_single_piece_request_still_bills_exactly_one() -> None:
    """配对臂：只给 1 件时计量是 1（证明上一条不是"凡交付皆记 2"）。"""
    cp = _cp()
    body = _handle_with(_OneImageProvider(), count=1).data[cp.PRESENTATION_DATA_KEY]
    images = [line for line in body["usage"] if line["metric"] == "images"]
    assert str(images[0]["value"]) == "1"


def test_over_delivery_is_refused_and_not_billed() -> None:
    """要 1 件却给 2 件：不记账、不对外——这是 count 的第一个行为读点。"""
    cp = _cp()
    result = _handle_with(_TwoImageProvider(), count=1)
    assert result.status is cp.InvocationStatus.LIMIT_EXCEEDED
    assert result.via == "creation_image_overdelivery"
    assert cp.PRESENTATION_DATA_KEY not in result.data


def test_result_record_carries_the_reconcile_handle() -> None:
    """provider_operation 不再是装饰：结果记录里必须真带着它（对账唯一抓手）。"""
    cp = _cp()
    body = _handle_with(_OneImageProvider(), count=1).data[cp.PRESENTATION_DATA_KEY]
    assert body["provider_operation"]
    assert body["provider_operation"] == body["job_id"]  # mock 侧同源，真实适配器可不同


def test_provider_error_code_reaches_the_result_record_and_the_detail() -> None:
    """四码目录在绘画执行路径上第一次真被喂到：failed + 在册码 ⇒ 原因串点名码。"""
    cp = _cp()

    class _Failing(ep.MockImageProvider):
        @property
        def offline_mock(self) -> bool:
            return False

        def poll(self, operation: str) -> ep.ImageProviderOutcome:
            return ep.ImageProviderOutcome(
                common.CreationJobState.FAILED, error_code="price_unavailable"
            )

    result = _handle_with(_Failing())
    assert result.status is cp.InvocationStatus.FAILED
    assert "price_unavailable" in result.detail


def test_failure_without_a_code_says_so_instead_of_looking_attributed() -> None:
    """诚实两态：provider 没给码时原因串必须明写"未给码"，不许留空装出可归因的样子。"""

    class _SilentFailure(ep.MockImageProvider):
        @property
        def offline_mock(self) -> bool:
            return False

        def poll(self, operation: str) -> ep.ImageProviderOutcome:
            return ep.ImageProviderOutcome(common.CreationJobState.FAILED)

    detail = _handle_with(_SilentFailure()).detail
    assert "未给码" in detail


def test_guidance_ceiling_bites_in_the_execution_path_and_invents_nothing() -> None:
    """三条臂：声明了上界就拦、不声明就不替 provider 猜、越界一次都不提交。"""
    cp = _cp()
    narrow = _NarrowGuidanceProvider()
    assert narrow.capabilities().max_guidance == 6.0
    before = narrow._seq
    result = _handle_with(narrow, guidance=9.0)
    assert result.status is cp.InvocationStatus.LIMIT_EXCEEDED
    assert result.via == "creation_image_caps"
    assert before == 0, "能力交集不过却仍提交了＝LIMIT_EXCEEDED 只是事后追认"
    # 反向臂：同一枚 guidance，在不声明上界的 mock 那里不是越界（mock ⇒ 诚实降级）。
    assert (
        _handle_with(ep.MockImageProvider(), guidance=9.0).status
        is cp.InvocationStatus.DEGRADED
    )


# ---------------------------------------------------------------------------
# 家规自查：本席补的东西不得变成第二真身
# ---------------------------------------------------------------------------


def test_guidance_ceiling_has_one_home_in_contracts() -> None:
    """CFG 上界的字面量只能有一处（注释里提到旧写法不算，故按 AST 判代码位点）。"""
    tree = ast.parse((_CREATION_DIR / "image" / "contracts.py").read_text(encoding="utf-8"))
    leaks: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Field":
            for kw in node.keywords:
                if kw.arg == "le" and isinstance(kw.value, ast.Constant) and kw.value.value == 100:
                    leaks.append(f"contracts.py:{node.lineno} le=100 字面量")
    assert not leaks, f"guidance 上界又写成字面量＝第二真身：{leaks}"
    src = (_CREATION_DIR / "image" / "contracts.py").read_text(encoding="utf-8")
    assert src.count("IMAGE_MAX_GUIDANCE = 100.0") == 1
    assert "le=IMAGE_MAX_GUIDANCE" in src


def test_watermark_kind_list_is_derived_not_copied() -> None:
    src = (_CREATION_DIR / "_common" / "contracts.py").read_text(encoding="utf-8")
    assert "frozenset(get_args(MarkingKind))" in src


def test_mock_capabilities_take_their_ceiling_from_the_contract() -> None:
    """mock 不许自带一份 50：抄数字＝第二真身，改契约上限时它只会安静地不对。"""
    src = (_CREATION_DIR / "image" / "engine_provider.py").read_text(encoding="utf-8")
    body = src[src.index("class MockImageProvider") : src.index("def resolve_job_request")]
    assert "max_steps=50" not in body and "IMAGE_MAX_STEPS" in body


def test_no_second_doctrine_copy_in_provider_outcome() -> None:
    """``ImageProviderOutcome`` 只判形态，不许复制 CreationJob 的配对教义。"""
    src = (_CREATION_DIR / "image" / "engine_provider.py").read_text(encoding="utf-8")
    body = src[src.index("class ImageProviderOutcome") : src.index("class MockImageProvider")]
    assert "必须携带产物" not in body and "不得携带产物" not in body, (
        "把 CreationJob._doctrines 抄进适配器边界＝第二真身，两条腿会各自漂移"
    )


def test_ledger_file_itself_does_not_import_forbidden_modules() -> None:
    """本件是常驻门：自己也不许破 creation 域的 import 纪律（threading/asyncio/os 等）。"""
    src = Path(__file__).read_text(encoding="utf-8")
    banned = {"threading", "asyncio", "os", "sqlite3", "subprocess", "socket", "httpx"}
    roots: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            roots.add((node.module or "").split(".")[0])
    assert not (roots & banned), f"本件 import 了域纪律禁用的模块：{sorted(roots & banned)}"


# ---------------------------------------------------------------------------
# 八段第 2/3/8 段的新执行面读点：每处都要正/反两臂（否则判据可以写成恒放行或恒拒）
# ---------------------------------------------------------------------------


class _SingleRefProvider(ep.MockImageProvider):
    """真实适配器形状：只吃一张参考图。"""

    @property
    def offline_mock(self) -> bool:
        return False

    def capabilities(self) -> cimage.ImageProviderCapabilities:
        return super().capabilities().model_copy(update={"max_reference_images": 1})


class _NoNegativeProvider(ep.MockImageProvider):
    """真实适配器形状：**明确**声明不支持负面提示（不是"没答"）。"""

    @property
    def offline_mock(self) -> bool:
        return False

    def capabilities(self) -> cimage.ImageProviderCapabilities:
        return super().capabilities().model_copy(update={"supports_negative_prompt": False})


def test_reference_image_ceiling_bites_and_undeclared_provider_is_not_invented_down() -> None:
    """参考图张数：声明 1 张就拦 2 张；不声明的 provider 不替它猜（只吃契约硬顶）。"""
    cp = _cp()
    two_refs = ({"asset_id": "in-1"}, {"asset_id": "in-2"})
    tight = _SingleRefProvider()
    before = tight._seq
    result = _handle_with(
        tight, task="image_to_image", assets=two_refs  # type: ignore[arg-type]
    )
    assert result.status is cp.InvocationStatus.LIMIT_EXCEEDED
    assert result.via == "creation_image_refs"
    assert before == 0, "越界还提交了＝这道闸只是事后追认"
    # 反向臂：同一份请求给不声明张数上限的 provider ⇒ 不是越界（mock ⇒ 诚实降级）。
    assert (
        _handle_with(ep.MockImageProvider(), task="image_to_image", assets=two_refs).status
        is cp.InvocationStatus.DEGRADED
    )


def test_reference_image_contract_hard_ceiling_rejects_before_any_provider_runs() -> None:
    """契约硬顶（``max_length``）：连请求对象都构造不出来，不等到 provider 才拦。"""
    refs = tuple({"asset_id": f"in-{i}"} for i in range(cimage.IMAGE_MAX_REFERENCE_IMAGES + 1))
    with pytest.raises(pydantic.ValidationError):
        _job(task="image_to_image", assets=refs)  # type: ignore[arg-type]
    # 配对臂：硬顶之内照收。
    ok = tuple({"asset_id": f"in-{i}"} for i in range(cimage.IMAGE_MAX_REFERENCE_IMAGES))
    assert len(_job(task="image_to_image", assets=ok).assets) == (  # type: ignore[arg-type]
        cimage.IMAGE_MAX_REFERENCE_IMAGES
    )


def test_explicitly_unsupported_negative_prompt_is_refused_not_quietly_ignored() -> None:
    """段 3 的牙：provider **明确**不支持却收到负面提示 ⇒ 当场拒，不静默忽略。"""
    cp = _cp()
    strict = _NoNegativeProvider()
    before = strict._seq
    result = _handle_with(strict, negative_prompt="模糊")
    assert result.status is cp.InvocationStatus.LIMIT_EXCEEDED
    assert result.via == "creation_image_negative_prompt"
    assert "不支持负面提示" in result.detail
    assert before == 0
    # 反向臂一：同一 provider，不带负面提示 ⇒ 照跑（证明不是"凡来单必拒"）。
    assert _handle_with(strict).status is cp.InvocationStatus.OK
    # 反向臂二：不声明支持性的 provider，带负面提示也放行（绝不替它编"不支持"）。
    assert (
        _handle_with(ep.MockImageProvider(), negative_prompt="模糊").status
        is cp.InvocationStatus.DEGRADED
    )


def test_artifact_without_provenance_cannot_be_presented_as_success() -> None:
    """段 8 的牙：产物不带溯源 ⇒ 出处全盲，降级并点名，不假 OK、不静默外发。"""

    class _BlindProvider(ep.MockImageProvider):
        @property
        def offline_mock(self) -> bool:
            return False

        def poll(self, operation: str) -> ep.ImageProviderOutcome:
            base = super().poll(operation)
            blind = tuple(
                row.model_copy(update={"provenance": None}) for row in base.assets
            )
            return ep.ImageProviderOutcome(base.state, assets=blind)

    cp = _cp()
    result = _handle_with(_BlindProvider())
    assert result.status is cp.InvocationStatus.DEGRADED
    assert result.via == "creation_image_provenance_gate"
    assert "出处不可报" in result.detail
    assert cp.PRESENTATION_DATA_KEY not in result.data
    # 配对臂：带溯源的真实 provider 走 OK（证明上一条不是"凡成功必降级"）。
    assert _handle_with(_OneImageProvider()).status is cp.InvocationStatus.OK


def test_negative_prompt_predicate_never_claims_support_it_does_not_have() -> None:
    """谓词三态不许滑成两态：None（没答）与 True（支持）在放行上同形，**语义**必须可分辨。"""
    caps = cimage.ImageProviderCapabilities(
        provider="p", max_steps=20, sizes=("512x512",), supported_tasks=("text_to_image",)
    )
    assert caps.supports_negative_prompt is None, "缺省必须是『不声明』，不是替 provider 答 True"
    assert caps.max_reference_images is None, "缺省必须是『不声明』，不是替 provider 答一个数"
    assert caps.max_guidance is None, "缺省必须是『不声明』，不是替 provider 答一个数"
    # 三态的可达性：不声明时带负面提示照放行，但谓词不宣称"支持"。
    accepted, reason = cimage.negative_prompt_accepted(_job(negative_prompt="糊"), caps)
    assert accepted and reason == ""
