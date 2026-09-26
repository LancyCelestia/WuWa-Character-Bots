"""S-G2-THROAT（2026-09-26，用户裁定「K-1：修」）：控制面/WebUI 写入口接进同意门。

钉的是什么
----
`test_safety_exec_session_throat.py` 收编会话面时**有意留下**的那条旁路（其冻结核注释
「控制面 HTTP 腿今天仍在，随旁路收编那一笔清零」）：`ConfigControlService._write /
reset_all → backend.set_override/reset_override → 裸 SQL` 一行不沾咽喉。本件把它接上
——三条写入口的实际落库动作全部搬进 `settings_gate.guarded_write` 的 `apply=` 闭包，
并与咽喉复用**同一枚门对象**（同意账同库、凭证同表，`bot.consent` 命令面看得见卡）。

- 锁①：R2 键经服务层写 ⇒ 不落库、出工单、同意账 pending +1、原文含批准指令；
  同参数重复请求复用同一张卡（不刷第二张）；HTTP 端点腿走同一裁决（envelope 409）。
- 锁②：同键第二次带已批凭证 ⇒ 落库成功、同意账变 consumed、变更流水 applied；
  换值重试不作数（凭证绑死值且一次性）。
- 锁③：R3 档 ⇒ 直接拒、零落库、不出卡；并现算在册事实「今天可写键与 R3 交集为空」
  （HTTP 面对 R3 结构性不可达，接线腿用注入档证明判据到场，不造第二套判定）。
- 锁④：`bot_safetyexec_enabled=False` ⇒ 与改动前逐字节同形——对照组是
  `runtime_settings=None` 的旧裸形态，同输入同输出同版本戳，且两张账表都不建。
- 锁⑤（关键）：AST 活性锁——`config_service.py` 里每一处裸 backend 写调用点必须住在
  `apply=` 实参的子树里，且 `_write` 与 `reset_all` 两处**都在册**（只测一条路径会漏
  掉 reset_all，本仓「存在性糊过活性判据」的老账）；反例锁证明名字级判据会空跑。
- 锁⑥：服务与 `bot.consent` 命令面（`store.safety_gate` 现读口径）看到的是同一枚门，
  卡可见、可批、重试可消费（没有第二本账、没有死信卡）。
- 锁⑦：`reset_all` 整批按聚合目标 `ALL_RUNTIME_OVERRIDES`（缺省 R2）判一次，
  被拒不偷清、批后一键清空；单键 reset 同样是「改参数」，无票不落。

全离线：设置目录、SQL 配置库、同意账一律落 tmp 目录（pytest tmp_path），
不 import NoneBot、不联网、绝不碰 `ChatBot_Runtime/data/settings/*.json` 与生产库。
"""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.control_plane import create_control_plane_app
from plugins.bot_unified_runtime.control_plane.audit import ControlPlaneAuditStore
from plugins.bot_unified_runtime.control_plane.auth import Principal, hash_token
from plugins.bot_unified_runtime.control_plane.config_service import (
    ConfigControlService,
)
from plugins.bot_unified_runtime.control_plane.config_store import (
    SQLiteConfigStateStore,
)
from plugins.bot_unified_runtime.control_plane.services import ControlServiceError
from plugins.bot_unified_runtime.domains.chat_reply.policy.roles import (
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN,
    ROLE_USER,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
    SETTABLE_KEYS,
    build_instance_settings_manager,
)
from plugins.bot_unified_runtime.domains.core.safety_exec import (
    config_risk,
    settings_gate,
)
from plugins.bot_unified_runtime.domains.core.safety_exec.config_risk import RiskTier
from plugins.bot_unified_runtime.domains.core.safety_exec.consent import (
    CHANGE_APPLIED,
    CHANGE_TABLE,
    CONSENT_TABLE,
    ConsentGrant,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_SERVICE_SOURCE = (
    ROOT / "plugins/bot_unified_runtime/control_plane/config_service.py"
)

#: R2 真字段且在 SETTABLE 白名单里（未登记键的缺省档也是 R2，这里取显式在册的稳妥面）。
R2_KEY = "BOT_CHAT_TEMPERATURE"
R2_VALUE = 0.7
#: R0 两枚（超时族）：reset_all 行为锁先无票地铺两行覆盖。
R0_KEY = "BOT_TRANSPORT_TIMEOUT_SECONDS"
R0_VALUE = 5.0
R0_KEY2 = "BOT_MEMORY_EXTRACT_TIMEOUT_SECONDS"
R0_VALUE2 = 30.0
ADMIN = Principal("bearer-super-admin", ("super_admin", "admin"))
APPROVER = "3865067623"
SUPER_ROLES = [ROLE_USER, ROLE_ADMIN, ROLE_SUPER_ADMIN]


def _config(tmp_path: Path, *, enabled: bool = True) -> SimpleNamespace:
    """生产缺省形态：SQL backend 键非空 ⇒ store 恒挂 backend（K-1 探针的同型前提）。"""
    return SimpleNamespace(
        bot_chat_temperature=0.5,
        bot_transport_timeout_seconds=8.0,
        bot_memory_extract_timeout_seconds=60.0,
        bot_runtime_settings_dir=str(tmp_path / "settings"),
        bot_control_plane_config_db=str(tmp_path / "cp_config.sqlite3"),
        bot_safetyexec_enabled=enabled,
    )


def _wired(tmp_path: Path, *, enabled: bool = True) -> tuple[Any, Any, Any, ConfigControlService]:
    config = _config(tmp_path, enabled=enabled)
    manager = build_instance_settings_manager(config)
    store = manager.get("default")
    backend = store.config_backend
    assert backend is not None, "前提不成立：要的是挂着 SQL backend 的形态"
    service = ConfigControlService(config, backend, runtime_settings=store)
    return config, manager, store, service


def _ledger_states(store: Any, table: str) -> list[str]:
    """直读同意账两张表的 state 列——「表不涨」就是旁路的全部罪证。"""
    if table not in (CONSENT_TABLE, CHANGE_TABLE):
        raise AssertionError(f"未知账本表：{table}")
    with sqlite3.connect(Path(str(store.config_backend.path))) as conn:
        try:
            return [str(row[0]) for row in conn.execute(f"SELECT state FROM {table}").fetchall()]
        except sqlite3.Error:
            return []  # 表没建 = 一笔账都没落


def _approve(store: Any, ticket: Any) -> Any:
    code = settings_gate.short_code_of(ticket.row)
    return store.safety_gate.approve(
        ticket.consent_id,
        code=code,
        message=IncomingMessage(
            platform="qq",
            adapter="onebot",
            bot_id="10000",
            session_id=f"private_{APPROVER}",
            session_type=SessionType.PRIVATE,
            sender_id=APPROVER,
            sender_roles=list(SUPER_ROLES),
            plain_text=f"同意卡 批 {ticket.consent_id} {code}",
        ),
    )


def _tier(key: str) -> RiskTier:
    return config_risk.risk_tier_for_target(key)


# ===========================================================================
# 锁①：R2 经服务层/HTTP 写 ⇒ 不落库、出工单、同意账 +1、原文含批准指令
# ===========================================================================


def test_r2_service_write_is_refused_and_issues_ticket(tmp_path: Path) -> None:
    assert _tier(R2_KEY) is RiskTier.R2, "夹具前提漂移：本键不再是 R2"
    _, _, store, service = _wired(tmp_path)
    assert _ledger_states(store, CONSENT_TABLE) == [], "开局就有同意账：夹具不干净"

    with pytest.raises(ControlServiceError) as exc:
        service.set(R2_KEY, R2_VALUE, principal=ADMIN, expected_version=0,
                    request_id="req-g2-1")
    assert exc.value.code == "consent_required"
    assert exc.value.status_code == 409
    assert backend_overrides_empty(store)
    assert store.config_backend.snapshot().version == 0, "被拒的写把版本戳顶动了"
    assert _ledger_states(store, CONSENT_TABLE).count("pending") == 1, "同意账没 +1（工单是假的？）"
    pending = store.safety_gate.pending_tickets()
    assert len(pending) == 1
    row = pending[0].row
    assert row.target == R2_KEY and row.tier == "R2"
    assert row.source_session_key == "", (
        "控制面没有入站会话，卡面不许伪造来源会话键（R1 同会话判据须对该渠道不启用）"
    )
    # 「别吞成 500、别丢原文」：工单号、短码、批准那句原话、过期都必须在响应消息里。
    assert row.consent_id in exc.value.message
    assert settings_gate.short_code_of(row) in exc.value.message
    assert "同意卡 批" in exc.value.message
    assert "过期" in exc.value.message

    # 同参数重复请求复用同一张卡（调度器式重试不许刷出第二张）。
    with pytest.raises(ControlServiceError) as again:
        service.set(R2_KEY, R2_VALUE, principal=ADMIN, expected_version=0,
                    request_id="req-g2-1-retry")
    assert row.consent_id in again.value.message
    assert len(store.safety_gate.pending_tickets()) == 1


def backend_overrides_empty(store: Any) -> bool:
    return store.config_backend.snapshot().overrides == {}


def test_http_config_endpoint_returns_ticket_in_envelope(tmp_path: Path) -> None:
    """真 HTTP 腿（v1.py set_config → 本服务）：409 + envelope 里带工单原文。"""
    admin_token = "g2-admin-token"
    root_token = "g2-root-token"
    config = SimpleNamespace(
        bot_control_plane_enabled=True,
        bot_control_plane_token_sha256=hash_token(admin_token),
        bot_control_plane_super_admin_token_sha256=hash_token(root_token),
        bot_runtime_settings_dir=str(tmp_path / "settings"),
        bot_control_plane_config_db=str(tmp_path / "config.sqlite3"),
        bot_runtime_settings_file=str(tmp_path / "settings.json"),
        bot_control_plane_features_file=str(tmp_path / "features.json"),
        bot_timezone="UTC",
        bot_safetyexec_enabled=True,
        bot_chat_temperature=0.5,
    )
    app = create_control_plane_app(
        config, audit_store=ControlPlaneAuditStore(str(tmp_path / "audit.sqlite3")),
        channel_health_store=object(),
    )
    with TestClient(app, base_url="http://127.0.0.1:8742") as client:
        refused = client.post(
            f"/api/v1/config/{R2_KEY}/set",
            headers={"Authorization": f"Bearer {root_token}"},
            json={"expected_version": 0, "value": R2_VALUE},
        )
        assert refused.status_code == 409
        err = refused.json()["error"]
        assert err["code"] == "consent_required"
        assert "同意卡 批" in err["message"], "批准指令原文没走到 HTTP 面"
        still = client.get(
            f"/api/v1/config/{R2_KEY}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert still.json()["data"]["value"] == 0.5, "被 409 拒掉的写把值改了"
        # 卡对 `bot.consent` 命令面的现读口径可见（同一枚门、同一本账）。
        store = build_instance_settings_manager(config).get("default")
        pending = store.safety_gate.pending_tickets()
        assert len(pending) == 1
        assert pending[0].consent_id in err["message"]


# ===========================================================================
# 锁②：带已批凭证的第二次重试 ⇒ 落库、同意账变 consumed、换值不作数
# ===========================================================================


def test_approved_retry_lands_and_consent_turns_consumed(tmp_path: Path) -> None:
    _, _, store, service = _wired(tmp_path)
    with pytest.raises(ControlServiceError):
        service.set(R2_KEY, R2_VALUE, principal=ADMIN, expected_version=0,
                    request_id="req-g2-2")
    pending = store.safety_gate.pending_tickets()
    assert isinstance(_approve(store, pending[0]), ConsentGrant)
    assert store.safety_gate.pending_tickets() == [], "批完卡还挂着（凭证没被消费）"

    row = service.set(R2_KEY, R2_VALUE, principal=ADMIN, expected_version=0,
                      request_id="req-g2-2-retry")
    assert row["value"] == R2_VALUE and row["version"] == 1
    assert store.config_backend.snapshot().overrides[R2_KEY] == R2_VALUE
    assert _ledger_states(store, CONSENT_TABLE).count("consumed") == 1
    assert CHANGE_APPLIED in _ledger_states(store, CHANGE_TABLE)

    # 一次性：用完即焚；换值＝另一件事，旧凭证不作数，得再签新卡。
    with pytest.raises(ControlServiceError) as swapped:
        service.set(R2_KEY, 0.9, principal=ADMIN, expected_version=1,
                    request_id="req-g2-2-swapped")
    assert swapped.value.code == "consent_required"
    assert store.config_backend.snapshot().overrides[R2_KEY] == R2_VALUE


# ===========================================================================
# 锁③：R3 档 ⇒ 直接拒、零落库、不出卡（今日不可达性 + 接线腿各一枚）
# ===========================================================================


def test_no_writable_key_is_r3_today(tmp_path: Path) -> None:
    """现算在册事实：可热写键与 R3 交集为空 ⇒ HTTP 面今天到不了 R3 腿。

    这条不许被删：它是锁③接线腿「注入档」定性（模拟明天）的依据；将来任何一枚
    SETTABLE 键被定成 R3，本锁红 ⇒ 逼着有人来把「真 R3 经 HTTP 被拒」补成行为锁。
    """
    offenders = [key for key in SETTABLE_KEYS if _tier(key) is RiskTier.R3]
    assert offenders == [], f"出现了可热写的 R3 键，锁③须补真档行为腿：{offenders}"


def test_r3_tier_is_refused_without_ticket_or_write(tmp_path: Path, monkeypatch) -> None:
    """接线腿：把该键的档注入成 R3（只喂唯一真身的分级口，不造第二套判定），
    证明门判 NEVER_AUTO 时本服务确实走「拒 + 零落库 + 不出卡 + 留 refused 流水」。
    """
    _, _, store, service = _wired(tmp_path)
    monkeypatch.setattr(config_risk, "risk_tier_for_target", lambda _t: RiskTier.R3)
    with pytest.raises(ControlServiceError) as exc:
        service.set(R2_KEY, R2_VALUE, principal=ADMIN, expected_version=0,
                    request_id="req-g2-r3")
    assert exc.value.code == "change_refused"
    assert exc.value.status_code == 403
    assert "R3" in exc.value.message, "拒绝面没带档位代号（防空跑）"
    assert backend_overrides_empty(store)
    assert store.config_backend.snapshot().version == 0
    assert _ledger_states(store, CONSENT_TABLE) == [], "R3 出卡＝给了一张永不可批的死信"
    assert "refused" in _ledger_states(store, CHANGE_TABLE)


# ===========================================================================
# 锁④：关闸 ⇒ 与改动前逐字节同形（对照组＝旧裸形态 runtime_settings=None）
# ===========================================================================


def test_gate_off_is_byte_identical_to_unwired_shape(tmp_path: Path) -> None:
    control_dir = tmp_path / "control"
    control_backend = SQLiteConfigStateStore(control_dir / "cp_config.sqlite3")
    control = ConfigControlService(_config(control_dir, enabled=True), control_backend)
    _, _, store, subject = _wired(tmp_path / "subject", enabled=False)

    c1 = control.set(R2_KEY, R2_VALUE, principal=ADMIN, expected_version=0, request_id="b1")
    s1 = subject.set(R2_KEY, R2_VALUE, principal=ADMIN, expected_version=0, request_id="b1")
    assert s1 == c1, f"同输入不同输出：{s1!r} != {c1!r}"
    c2 = control.set(R0_KEY, R0_VALUE, principal=ADMIN, expected_version=1, request_id="b2")
    s2 = subject.set(R0_KEY, R0_VALUE, principal=ADMIN, expected_version=1, request_id="b2")
    assert s2 == c2
    c3 = control.reset(R2_KEY, principal=ADMIN, expected_version=2, request_id="b3")
    s3 = subject.reset(R2_KEY, principal=ADMIN, expected_version=2, request_id="b3")
    assert s3 == c3
    c4 = control.reset_all(principal=ADMIN, expected_version=3, request_id="b4")
    s4 = subject.reset_all(principal=ADMIN, expected_version=3, request_id="b4")
    assert s4 == c4

    before = control_backend.snapshot()
    after = store.config_backend.snapshot()
    assert (after.version, after.overrides) == (before.version, before.overrides), "版本戳/覆盖漂移"
    # 关闸不建第二本账：门虽挂上（policy.enabled=False），两张账表都不许出现。
    assert _ledger_states(store, CONSENT_TABLE) == []
    assert _ledger_states(store, CHANGE_TABLE) == []


# ===========================================================================
# 锁⑤（关键）：AST 活性——裸 backend 写调用点全部住在 apply= 子树内
# ===========================================================================

_RAW_WRITE_METHODS = frozenset({"set_override", "reset_override"})
_GUARD_CALL_NAMES = frozenset({"_guarded_apply", "guarded_write"})


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    mapping: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            mapping[child] = node
    return mapping


def _enclosing_def(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    cur: ast.AST | None = node
    while cur is not None:
        if isinstance(cur, ast.FunctionDef | ast.AsyncFunctionDef):
            return cur.name
        cur = parents.get(cur)
    return "<module>"


def _inside_apply_argument(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    cur: ast.AST | None = node
    while cur is not None:
        parent = parents.get(cur)
        if (
            isinstance(parent, ast.Call)
            and isinstance(parent.func, ast.Attribute)
            and parent.func.attr in _GUARD_CALL_NAMES
        ):
            for keyword in parent.keywords:
                if keyword.arg == "apply" and any(sub is node for sub in ast.walk(keyword.value)):
                    return True
        cur = parent
    return False


def unprotected_raw_backend_writes(source: str) -> list[str]:
    """判据（纯函数）：`X.set_override/X.reset_override` 且接收者含 backend，
    不在任何 `guarded_write/_guarded_apply` 的 apply= 实参子树里的，全部点名。
    """
    tree = ast.parse(source)
    parents = _parents(tree)
    problems: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _RAW_WRITE_METHODS
            and "backend" in ast.unparse(node.func.value).lower()
            and not _inside_apply_argument(node, parents)
        ):
            problems.append(
                f"{_enclosing_def(node, parents)}::{node.func.attr}"
            )
    return problems


def _raw_backend_write_defs(source: str) -> set[str]:
    tree = ast.parse(source)
    parents = _parents(tree)
    found: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _RAW_WRITE_METHODS
            and "backend" in ast.unparse(node.func.value).lower()
        ):
            found.add(_enclosing_def(node, parents))
    return found


def test_every_raw_backend_write_in_config_service_is_inside_apply_closure() -> None:
    source = CONFIG_SERVICE_SOURCE.read_text(encoding="utf-8")
    hits = _raw_backend_write_defs(source)
    assert {"_write", "reset_all"} <= hits, (
        f"reset_all 或 _write 的裸写腿失踪/改名——本锁的『两条路径都在册』前提塌了：{hits}"
    )
    violations = unprotected_raw_backend_writes(source)
    assert violations == [], f"裸 backend 写点离开了 apply= 闭包：{violations}"


def test_apply_closure_lock_has_teeth_against_name_only_judgment() -> None:
    """反例锁：把一处裸写搬到 apply= 子树**外**——名字级判据（『文件里出现过
    _guarded_apply / apply=』）照样全绿，本锁必须红。这就是『存在性糊过活性判据』
    的解毒剂，也是本席拒收『文件里出现过 guarded_write』那种放宽的凭据。
    """
    source = CONFIG_SERVICE_SOURCE.read_text(encoding="utf-8")
    anchor = "snapshot = self._guarded_apply(\n                target=key,"
    assert anchor in source, "注毒锚点已失效 ⇒ 本毒在空跑（须换锚点，不许放宽判据）"
    poisoned = source.replace(
        anchor,
        "self.backend.set_override(key, converted, expected_version=expected_version,"
        " actor=principal.subject, request_id=request_id)\n            " + anchor,
        1,
    )
    # 名字级判据对毒形态放行（证明它没有杀伤力、不能用它替代子树判据）……
    assert "_guarded_apply(" in poisoned and "apply=" in poisoned
    # ……而子树判据当场点名。
    assert unprotected_raw_backend_writes(poisoned) == ["_write::set_override"] or \
        "_write::set_override" in unprotected_raw_backend_writes(poisoned), \
        unprotected_raw_backend_writes(poisoned)


# ===========================================================================
# 锁⑥：同一枚门（命令面读点=服务用门）——没有第二本账、没有死信卡
# ===========================================================================


def test_service_and_consent_surface_share_one_gate(tmp_path: Path) -> None:
    _, _, store, service = _wired(tmp_path)
    with pytest.raises(ControlServiceError):
        service.set(R2_KEY, R2_VALUE, principal=ADMIN, expected_version=0,
                    request_id="req-g2-6")
    assert store.safety_gate is not None
    assert service._consent_gate() is store.safety_gate, (
        "服务另造了一枚门——凭证表与卡就会分家（两本账形态回潮）"
    )
    pending = store.safety_gate.pending_tickets()  # consent_admin 的现读形状
    assert len(pending) == 1
    assert isinstance(_approve(store, pending[0]), ConsentGrant)
    landed = service.set(R2_KEY, R2_VALUE, principal=ADMIN, expected_version=0,
                         request_id="req-g2-6-retry")
    assert landed["version"] == 1


# ===========================================================================
# 锁⑦：reset_all 走聚合目标（缺省 R2）；单键 reset 无票也不落
# ===========================================================================


def test_reset_all_goes_through_aggregate_target_and_lands_after_consent(
    tmp_path: Path,
) -> None:
    _, _, store, service = _wired(tmp_path)
    assert service.set(R0_KEY, R0_VALUE, principal=ADMIN, expected_version=0,
                       request_id="ra-seed1")["version"] == 1
    assert service.set(R0_KEY2, R0_VALUE2, principal=ADMIN, expected_version=1,
                       request_id="ra-seed2")["version"] == 2

    with pytest.raises(ControlServiceError) as refused:
        service.reset_all(principal=ADMIN, expected_version=2, request_id="ra-1")
    assert refused.value.code == "consent_required"
    assert settings_gate.ALL_OVERRIDES_TARGET in refused.value.message
    snap = store.config_backend.snapshot()
    assert set(snap.overrides) == {R0_KEY, R0_KEY2} and snap.version == 2, "被拒的全撤偷清了"
    ticket = store.safety_gate.pending_tickets()[0]
    assert ticket.row.target == settings_gate.ALL_OVERRIDES_TARGET
    assert ticket.row.tier == "R2", "整批档位口径漂移（聚合目标缺省 R2）"

    assert isinstance(_approve(store, ticket), ConsentGrant)
    done = service.reset_all(principal=ADMIN, expected_version=2, request_id="ra-2")
    assert done == {"version": 3, "reset_count": 2}
    assert store.config_backend.snapshot().overrides == {}


def test_single_key_reset_also_needs_its_ticket(tmp_path: Path) -> None:
    """撤覆盖同样是「改参数」：R2 键的单键 reset 无票不落、版本戳不动。"""
    _, _, store, service = _wired(tmp_path)
    with pytest.raises(ControlServiceError):
        service.set(R2_KEY, R2_VALUE, principal=ADMIN, expected_version=0,
                    request_id="sr-seed")
    ticket = store.safety_gate.pending_tickets()[0]
    assert isinstance(_approve(store, ticket), ConsentGrant)
    assert service.set(R2_KEY, R2_VALUE, principal=ADMIN, expected_version=0,
                       request_id="sr-seed-retry")["version"] == 1

    with pytest.raises(ControlServiceError) as refused:
        service.reset(R2_KEY, principal=ADMIN, expected_version=1, request_id="sr-1")
    assert refused.value.code == "consent_required"
    assert store.config_backend.snapshot().overrides.get(R2_KEY) == R2_VALUE
    assert store.config_backend.snapshot().version == 1
