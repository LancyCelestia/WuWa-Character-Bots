"""A-8 常驻断言「生产配置值 ∈ 允许根」（S-A8-IMPL-b，2026-09-27）。

对账依据 = 只读审计 ``SEAT-A8-OUTROOT`` §3-④：与其逐个改落点，不如把
「所有登记在册的路径配置值，其落域必须在允许根内」钉成**常驻断言**——以后再有人
把生产落点改到根外，CI 当场打红，而不是等 SEAT 审计现算。

刻度来源全部是**真身**，零抄写：

* 配置值 = ``scripts.load_runtime_config.load_runtime_config``（生产同构装载，
  ``required=False`` 容忍别的机器没有 .env/.env.prod，落回模型缺省值）；
* 名册 = ``config.PATH_REMAPPED_FIELDS`` / ``PATH_LIST_REMAPPED_FIELDS``
  （A-8 裁定时从 validator 局部提到模块级的同一张表，validator 与本断言共用，
  禁第二副本）+ 逐字段点名的**消费时解析**字段（``bot_daily_assist_dir``：
  不在重映射名册里，由 ``daily_assist`` 装配时过 ``build_runtime_data_path`` +
  ``check_sendable`` 把关，本断言补登记域的账）；
* 判定 = ``safety_exec.paths.check_registered_domain``——**登记域尺**（只问在不在
  允许根里），不是出站许可。两把尺混淆不得（红线）：本件拿它验配置**登记**，
  出站仍走 ``check_sendable``；把本尺当放行依据＝放宽守卫，正是所有者明令禁止
  的「靠放宽守卫变绿」形态。口径差本身由 ③ 节用 ``bot_runtime_settings_file``
  锁死（同一值：登记尺 allowed、出站闸 denied ⇒ 两尺各自有牙）。

相对值口径（诚实声明，非抄守卫）：绝对值原样；``data/`` 前缀交给判定件自己的
锚（与 ``paths._anchor`` 同语义）；其余相对写法按仓库根（生产 bot 进程 CWD）
join——这正是 ``tts._resolve_ref_path`` 一类消费方的真实落点。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.config import (
    PATH_LIST_REMAPPED_FIELDS,
    PATH_REMAPPED_FIELDS,
    Config,
)
from plugins.bot_unified_runtime.domains.core.safety_exec import paths
from scripts.load_runtime_config import load_runtime_config
from scripts.runtime_paths import (
    RUNTIME_DATA_DIR_ENV,
    TEST_PROCESS_ENV,
    production_runtime_data_dirs,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

#: 消费时解析（不在重映射名册、由能力自己装配时过守卫）而**必须**被登记域
#: 断言覆盖的字段。缺一条，这类字段就游离在账外。
USE_TIME_RESOLVED_FIELDS: frozenset[str] = frozenset({"bot_daily_assist_dir"})

#: 有正当理由落在允许根之外的字段 ⇒ 必须逐字段写明缘由（禁整族豁免）。
#: 口径：A-8 裁定咬的是**生成物落点**（写/发目的地）；本表全部是**只读引用件**
#: （外部安装件/外部语料），落域外不属"改落点"命题。其中逐值外根的项已写入
#: 席位报告**待裁**——所有者若选择并入根/注册 corpus 根（corpus:daily_assist
#: 有先例），②节反向锁会因豁免变死账而打红，提醒删豁免。
EXTERNAL_REFERENCE_FIELDS: dict[str, str] = {
    # GPT-SoVITS 引擎**程序目录**：只读引用外部安装件，不是本 bot 的生成物
    # 落点（OUTROOT §2 备注/铁律 6 语义：落点必须在根内，引用件不在此列）。
    "bot_tts_gptsovits_dir": "引擎程序目录（外部安装件只读引用，非生成物落点）",
    # 外部知识语料 .md（.env.prod 逐值在册）：读侧材料，写面不落到这里。
    "bot_knowledge_files": "外部知识语料文件（只读引用；是否入根待裁，见席位报告）",
}


@pytest.fixture(scope="module", autouse=True)
def _audit_reads_declared_production_layout():
    """本件审的是**盘上声明**那一套落点 ⇒ Runtime 根隔离缝（L1）在本模块内要让路。

    2026-09-30 L1 落地时现算：conftest 的装配把进程 env 的 ``BOT_RUNTIME_DATA_DIR`` 挤成
    临时隔离根，于是 ``load_runtime_config`` 造的在册值被重映射进隔离根，``safety_exec.paths``
    的允许根尺亦按隔离根解析 ⇒ ①节整片被判 ``outside_allowed_roots``（只摘标记不还原 env 也红，
    因为 ``Config`` 的路径名册按 env 优先读数；实测两半都要动）。修法＝把本模块临时还原成
    「非测试进程」视图：标记摘掉（``_effective_data_root_text`` 的 seam-footprint 回退腿，与在册锁
    ``test_guard_is_inert_for_non_test_processes`` 同一形态）＋数据根回到
    ``production_runtime_data_dirs()``（全仓唯一"什么叫生产根"读数器，禁第二副本）。
    作用域必须是 **module** 且 autouse：``production_config`` 同为 module 级，函数级还原晚一步。
    零放宽判据、零写盘：本件只问 ``check_registered_domain`` 那把登记域尺，不建库不开文件；
    生产值真落在生产根外照样打红（②节反向锁在册）。
    """
    declared = production_runtime_data_dirs()
    patch = pytest.MonkeyPatch()
    patch.delenv(TEST_PROCESS_ENV, raising=False)
    if declared:
        patch.setenv(RUNTIME_DATA_DIR_ENV, str(declared[0]))
    paths.set_default_policy(None)
    try:
        yield
    finally:
        paths.set_default_policy(None)
        patch.undo()


@pytest.fixture(autouse=True)
def _fresh_default_policy():
    """本件全程用**缺省**（真实机器）策略：前后各复位一次，防他件注入泄漏。"""
    paths.set_default_policy(None)
    yield
    paths.set_default_policy(None)


@pytest.fixture(scope="module")
def production_config() -> Config:
    return load_runtime_config((".env", ".env.prod"), required=False)


def _covered_field_names() -> list[str]:
    return [*PATH_REMAPPED_FIELDS, *PATH_LIST_REMAPPED_FIELDS, *sorted(USE_TIME_RESOLVED_FIELDS)]


def _normalize(value: str, policy: paths.PathDomainPolicy) -> str:
    """把配置值换算成登记域尺能直读的形状（见模块 docstring 的口径声明）。"""
    v = value.strip()
    p = Path(v)
    if p.is_absolute():
        return v
    unified = v.replace("\\", "/")
    while unified.startswith("./"):
        unified = unified[2:]
    lowered = unified.lower()
    if lowered == "data" or lowered.startswith("data/"):
        # 判定件自己的 _anchor 认这个前缀（锚在 runtime_data_root），原样递尺。
        return unified
    # 其余相对写法：生产进程 CWD＝仓库根，按真实落点 join 后再问尺。
    return str(REPO_ROOT / unified)


def _values_of(cfg: Config, name: str) -> list[str]:
    raw: Any = getattr(cfg, name)
    if raw is None or raw == "":
        return []
    if isinstance(raw, (list, tuple)):
        return [str(x) for x in raw if str(x).strip()]
    return [str(raw)]


# ---------------------------------------------------------------------------
# ① 主断言：每一个在册路径值 ⇒ 登记域尺不得判 denied
# ---------------------------------------------------------------------------


def test_all_registered_config_values_inside_allowed_roots(
    production_config: Config,
) -> None:
    policy = paths.default_policy()
    offenders: list[tuple[str, str, str, str]] = []
    checked = 0
    for name in _covered_field_names():
        assert name in Config.model_fields, f"名册字段 {name} 已不在 Config 中（名册烂掉）"
        exempt = name in EXTERNAL_REFERENCE_FIELDS
        for value in _values_of(production_config, name):
            checked += 1
            decision = policy.check_registered_domain(_normalize(value, policy))
            if not decision.denied:
                continue
            # 豁免字段也**不豁免形态面**：逃逸/设备名/歧义写法照样打红，
            # 只放行 outside_allowed_roots 这一种（"引用件在根外"的合法形态）。
            if exempt and decision.reason_code == paths.DenyReason.OUTSIDE_ALLOWED_ROOTS:
                continue
            offenders.append((name, value, decision.verdict, decision.reason_code))
    assert checked > 40, f"扫描面塌了（只查了 {checked} 个值）"
    assert not offenders, "生产配置值落在允许根外（改落点，不许扩根）：" + "; ".join(
        f"{n}={v}({rc})" for n, v, _verdict, rc in offenders
    )


# ---------------------------------------------------------------------------
# ② 豁免反向锁：豁免表不许多、不许烂（值回到根内就该删豁免）
# ---------------------------------------------------------------------------


def test_external_reference_exclusions_are_exactly_needed(production_config: Config) -> None:
    policy = paths.default_policy()
    for name in EXTERNAL_REFERENCE_FIELDS:
        assert name in set(PATH_REMAPPED_FIELDS) | set(PATH_LIST_REMAPPED_FIELDS) | set(
            USE_TIME_RESOLVED_FIELDS
        ), f"豁免字段 {name} 根本不在册（豁免表越界）"
        values = _values_of(production_config, name)
        assert values, f"豁免字段 {name} 当前为空 ⇒ 豁免是死账，删掉"
        outside = [
            v for v in values
            if policy.check_registered_domain(_normalize(v, policy)).reason_code
            == paths.DenyReason.OUTSIDE_ALLOWED_ROOTS
        ]
        assert outside, (
            f"{name} 的值已全部回到允许根内 ⇒ 豁免变死账，删掉这条：{values}"
        )


# ---------------------------------------------------------------------------
# ③ 两把尺不混锁：同一值 登记尺放行、出站闸拒（禁拿登记尺当出站许可）
# ---------------------------------------------------------------------------


def test_registered_domain_ruler_is_not_outbound_license(production_config: Config) -> None:
    value = production_config.bot_runtime_settings_file
    registered = paths.check_registered_domain(_normalize(value, paths.default_policy()))
    assert registered.allowed, f"登记尺口径走样：{registered.audit_line()}"
    outbound = paths.check_sendable(_normalize(value, paths.default_policy()))
    assert outbound.denied, (
        "出站闸对该值放行 ⇒ 要么名册变了要么闸松了：两把尺的口径差是本锁的本体"
    )
    assert outbound.reason_code == paths.DenyReason.FORBIDDEN_FILE_CLASS


# ---------------------------------------------------------------------------
# ④ 外根值反向锁：登记尺对根外绝对路径必须拒（不是"看不见"）
# ---------------------------------------------------------------------------


def test_registered_domain_denies_outside_root() -> None:
    decision = paths.check_registered_domain("C:/Windows/win.ini")
    assert decision.denied
    assert decision.reason_code == paths.DenyReason.OUTSIDE_ALLOWED_ROOTS
    # 形态面同样有牙：设备命名空间不许从登记尺溜过去。
    device = paths.check_registered_domain("\\\\?\\C:\\Windows\\win.ini")
    assert device.denied and device.reason_code in {
        paths.DenyReason.UNC_OR_DEVICE_PATH,
        paths.DenyReason.OUTSIDE_ALLOWED_ROOTS,
    }


# ---------------------------------------------------------------------------
# ⑤ 防漂移锁：凡是 data/ 缺省值的 Config 字段都必须被名册∪点名表覆盖
# ---------------------------------------------------------------------------


def test_no_data_default_config_field_escapes_registration() -> None:
    covered = set(_covered_field_names()) | {"bot_runtime_data_dir"}
    drift: list[str] = []
    for name, field in Config.model_fields.items():
        default = field.default
        candidates: list[Any]
        if isinstance(default, str):
            candidates = [default]
        elif isinstance(default, (list, tuple)):
            candidates = list(default)
        else:
            continue
        for cand in candidates:
            if isinstance(cand, str) and cand.replace("\\", "/").startswith("data/"):
                if name not in covered:
                    drift.append(name)
                break
    assert not drift, (
        "新增 data/ 落点字段未入 PATH_REMAPPED_FIELDS/PATH_LIST_REMAPPED_FIELDS "
        f"也未点名：{drift}（增字段只改名册，见 config.py 注释；漏了=账外落点）"
    )
