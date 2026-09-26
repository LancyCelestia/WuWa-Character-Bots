"""SAFE-EXEC 第 18 项：会话命令面改参数的**旁路收编**锁（S-THROAT，2026-09-26）。

钉的是什么
----
`S-CONSENT-DISPATCH` §⑨-B 现算出的形态：咽喉（`RuntimeSettingsStore._throat_guard`）
只在 `store.set_override/reset_override` 上执法，而挂着 SQL backend 的部署里
`/bot runtime set|reset` 走的是 `ConfigControlService._write → backend.set_override
→ 裸 SQL`，**一行不沾门**；且 `bot_control_plane_config_db` 缺省非空 ⇒ 生产恒挂
backend ⇒ 这条旁路今天就会被命中（复现探针两腿：经咽喉被拒出票、经控制面当场落库
且同意账不 +1）。本件收在两侧：

- 锁①（行为）：**经会话命令**改一枚 R2 键 ⇒ 无票被拒（值没落、票签出来了、回执带
  工单号/短码/过期/下一步）、超管亲批后同一条命令重试才落库、同意账记到 consumed
  且变更流水出现 applied 终态；R0 键不因为收编多弹一次票，回显与旧旁路形态**逐字节
  同形**（同一句话、同一个版本号）；
- 锁②（结构）：`X.set_override/reset_override` 且 X 是**裸 backend**（绕过咽喉）的
  直写点名册只准含咽喉自身的两个 raw 转发（`_raw_write`/`_raw_reset`）；控制面 HTTP
  腿今天仍在（缺省关、待她裁）⇒ 单列一本**只降不升**的冻结核；裸 SQL 写 config 表的
  语句只准住 `control_plane/config_store.py` 一个文件。接收者含 "backend" 的文本判据
  之外还追**局部别名**（`be = store.config_backend; be.set_override(...)` 也当场点名，
  S-THROAT-2 补强 + 注毒验证）。

S-THROAT-2（续坐席，2026-09-26）在锁①②之外补齐：

- 锁①R1 腿：经会话命令改 R1 键——拒写签出的**卡面带来源会话**
  （`row.source_session_key == 命令传入的 session_key`），换会话 admin 批不动
  （`APPROVER_NOT_AUTHORISED`、工单不烧），本会话 admin（非超管）亲批后同参数
  重试落库、同意账 consumed +1、变更流水 applied；
- 锁③（session_key 传到底）：咽喉把清洗后的会话键**原样**交给门、缺省空串保持
  空串（不伪造「看着像缺省会话」的值）；`runtime_admin` 每一处咽喉写必须转发
  `session_key` 形参（硬写空串注毒必红）；`build_runtime_admin_result` 的
  **未传会话键调用者**单列一本只降不升的欠账（今天：根装配 3 处 + 控制台 1 处，
  根上那 3 处的修法见 S-THROAT §⑦-A 施工单——`message.session_id` 就在手边）。

全离线：设置目录、SQL 配置库、同意账一律落 `tmp_path`；不 import NoneBot、不联网、
不碰 Runtime 真库、不写源码树。
"""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGINS = ROOT / "plugins"

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.chat_reply.policy.roles import (
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN,
    ROLE_USER,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
    build_instance_settings_manager,
)
from plugins.bot_unified_runtime.domains.core.safety_exec import settings_gate
from plugins.bot_unified_runtime.domains.core.safety_exec.consent import (
    CHANGE_APPLIED,
    CHANGE_TABLE,
    CONSENT_TABLE,
    ConsentGrant,
    DenyKind,
    Refusal,
)
from plugins.bot_unified_runtime.domains.ops.admin.runtime_admin import (
    build_runtime_admin_result,
)

#: R2 真字段且在 SETTABLE 白名单里（与 test_safety_exec_throat_wire 同一取法）。
R2_KEY = "BOT_MEMORY_EXTRACT_ENABLED"
R2_VALUE = "false"
#: R0 真字段（超时族）且在白名单里：门开时也直写，不许因此多弹一次票。
R0_KEY = "BOT_TRANSPORT_TIMEOUT_SECONDS"
R0_VALUE = "5.0"
#: R1 真字段（安静时间族，`config_risk` 模式族解出 R1）：要「管理员在**原会话**确认」，
#: 这一档的会话维度吃的就是调用方传进来的 session_key（S-THROAT-2 补的缺口腿）。
R1_KEY = "BOT_QUIET_HOURS_ENABLED"
R1_VALUE = "false"
#: 发起 R1 命令的群会话键；卡面 `source_session_key` 必须逐字节等于它。
R1_GROUP_SESSION = "group_1108838060_1722380002"
REQUESTER = "qq:1722380002"
APPROVER = "3865067623"
SUPER_ROLES = [ROLE_USER, ROLE_ADMIN, ROLE_SUPER_ADMIN]
ADMIN_ONLY_ROLES = [ROLE_USER, ROLE_ADMIN]


def _config(tmp_path: Path, *, enabled: bool = True) -> SimpleNamespace:
    """生产缺省形态：SQL backend 键**非空**（`config.py` 缺省即非空）⇒ store 恒挂 backend。"""
    return SimpleNamespace(
        bot_runtime_settings_dir=str(tmp_path / "settings"),
        bot_control_plane_config_db=str(tmp_path / "control_plane_config.sqlite3"),
        bot_safetyexec_enabled=enabled,
    )


def _wired(tmp_path: Path, *, enabled: bool = True) -> tuple[Any, Any, SimpleNamespace]:
    config = _config(tmp_path, enabled=enabled)
    manager = build_instance_settings_manager(config)
    store = manager.get("default")
    assert store.config_backend is not None, "前提不成立：本件要的是挂着 SQL backend 的形态"
    assert store.safety_gate is None, "前提不成立：门应当惰性装载（第一次写才建）"
    return manager, store, config


def _session_set(manager: Any, config: Any, key: str, value: str) -> Any:
    """一条真实的会话命令：与根装配面同一形状（超管、私聊、带 request_id）。"""
    return build_runtime_admin_result(
        manager,
        "default",
        config,
        request_id=f"req-set-{key}",
        actor_id=REQUESTER,
        actor_roles=list(SUPER_ROLES),
        command_text=f"set {key} {value}",
        session_key=f"private_{APPROVER}",
    )


def _ledger_states(store: Any, table: str) -> list[str]:
    """直接读同意账本表的 state 列——旁路今天的全部罪证就是这两张表不涨。"""
    if table not in (CONSENT_TABLE, CHANGE_TABLE):
        raise AssertionError(f"未知账本表：{table}")
    with sqlite3.connect(Path(str(store.config_backend.path))) as conn:
        try:
            return [str(row[0]) for row in conn.execute(f"SELECT state FROM {table}").fetchall()]
        except sqlite3.Error:
            return []  # 表没建 = 一笔账都没落（首次写之前就是这个形态）


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


# ===========================================================================
# 锁①：经会话命令改参数——R2 无票被拒 / 批后落库 / 同意账跟随；R0 逐字节同形
# ===========================================================================


def test_session_command_r2_write_refused_then_lands_after_written_consent(
    tmp_path: Path,
) -> None:
    manager, store, config = _wired(tmp_path)
    assert _ledger_states(store, CONSENT_TABLE) == [], "开局就有同意账：夹具不干净"

    refused = _session_set(manager, config, R2_KEY, R2_VALUE)
    assert refused.title == "运行时设置失败", f"无票的 R2 写竟然成功了：{refused.body}"
    assert R2_KEY in refused.body
    assert store.list_overrides() == {}, "被拒的写把值落下去了——拒绝路径泄了"
    pending = store.safety_gate.pending_tickets()
    assert len(pending) == 1, "拒的那次没签出同意卡（无声吞掉）"
    # 回执必须把「凭哪张票、找谁批、到什么时候」交到申请人手里（文案已有，不另写一套）。
    assert pending[0].consent_id in refused.body, "回执里没有工单号：申请人无从批"
    assert settings_gate.short_code_of(pending[0].row) in refused.body, "回执里没有短码"
    assert "同意卡 批" in refused.body, "回执没给下一步那句原话"
    assert "过期" in refused.body, "回执没说到什么时候作废"

    assert isinstance(_approve(store, pending[0]), ConsentGrant)
    assert store.safety_gate.pending_tickets() == [], "批完卡还挂着（凭证没被消费）"

    applied = _session_set(manager, config, R2_KEY, R2_VALUE)
    assert applied.title == "运行时设置", f"批过的同一条命令仍写不进：{applied.body}"
    assert store.list_overrides()[R2_KEY] is False, "批完没真落库（只在内存里演了一下）"
    assert "已保存" in applied.body and "动态消费者下次读取生效" in applied.body
    # 同意账 +1：那张卡从 pending 走到 consumed；变更流水落到 applied 终态。
    assert _ledger_states(store, CONSENT_TABLE).count("consumed") == 1
    assert CHANGE_APPLIED in _ledger_states(store, CHANGE_TABLE)


def test_session_command_r0_write_lands_without_ticket_and_reply_is_byte_identical(
    tmp_path: Path,
) -> None:
    """R0（不需要同意）不许因为收编而多弹一次票，回显也与旧旁路形态逐字节同形。"""
    manager, store, config = _wired(tmp_path)
    result = _session_set(manager, config, R0_KEY, R0_VALUE)
    assert result.title == "运行时设置", f"R0 键被要票了：{result.body}"
    assert store.list_overrides()[R0_KEY] == 5.0
    # 旧旁路的这句话（同一条 f-string、版本号取写完后的快照）一个字都不许漂。
    assert result.body == (
        f"[实例 {store.instance}] 已保存 {R0_KEY} = 5.0（版本 1）；动态消费者下次读取生效。"
    ), f"R0 回显漂移：{result.body!r}"
    assert _ledger_states(store, CONSENT_TABLE) == [], "R0 写签了同意卡＝多弹一次票"


def test_session_command_reset_all_now_needs_a_ticket(tmp_path: Path) -> None:
    """撤覆盖同样是「改参数」：整表清空走聚合目标（缺省 R2）⇒ 今天起要票。

    这是收编带来的**行为收紧**，如实钉在这里（旧形态：`service.reset_all` 无声清空）。
    """
    manager, store, config = _wired(tmp_path)
    assert _session_set(manager, config, R0_KEY, R0_VALUE).title == "运行时设置"
    refused = build_runtime_admin_result(
        manager, "default", config, request_id="req-reset-all",
        actor_id=REQUESTER, actor_roles=list(SUPER_ROLES), command_text="reset",
        session_key=f"private_{APPROVER}",
    )
    assert refused.title == "运行时设置失败"
    assert store.list_overrides() != {}, "「全撤」绕过了票就把覆盖清了"
    assert settings_gate.ALL_OVERRIDES_TARGET in refused.body


def test_master_off_session_write_is_byte_identical_to_pre_wiring(tmp_path: Path) -> None:
    """总闸关 ⇒ 收编不许改变任何可见形态：写落库、零张票、同一句话。"""
    manager, store, config = _wired(tmp_path, enabled=False)
    result = _session_set(manager, config, R2_KEY, R2_VALUE)
    assert result.title == "运行时设置", f"关闸形态被要票了：{result.body}"
    assert store.list_overrides()[R2_KEY] is False
    assert _ledger_states(store, CONSENT_TABLE) == []
    assert _ledger_states(store, CHANGE_TABLE) == []


def test_session_command_never_touches_the_bypass_write_legs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """旁路的三条写腿一次都不许被走到（收编的行为级反证）。

    这条同时是**注毒台**：谁把 set/reset 改回 `service.set/reset/reset_all`（旧旁路），
    或谁新增一处经 `ConfigControlService` 的写，本锁当场红——它不看源码形状，
    看的是运行时真的调没调，与上面那把 AST 锁互补。
    """
    from plugins.bot_unified_runtime.control_plane.config_service import (
        ConfigControlService,
    )

    walked: list[str] = []

    def _poison(leg: str) -> Any:
        def _hit(_self: Any, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            walked.append(leg)
            raise AssertionError(f"旁路被走到了：{leg}")

        return _hit

    monkeypatch.setattr(ConfigControlService, "set", _poison("set"))
    monkeypatch.setattr(ConfigControlService, "reset", _poison("reset"))
    monkeypatch.setattr(ConfigControlService, "reset_all", _poison("reset_all"))

    manager, store, config = _wired(tmp_path, enabled=False)  # 关闸：写必然落库，最容易暴露
    assert _session_set(manager, config, R0_KEY, R0_VALUE).title == "运行时设置"
    assert store.list_overrides()[R0_KEY] == 5.0, "写腿没落库：本锁在测别的"
    assert build_runtime_admin_result(
        manager, "default", config, request_id="req-reset", actor_id=REQUESTER,
        actor_roles=list(SUPER_ROLES), command_text=f"reset {R0_KEY}",
        session_key=f"private_{APPROVER}",
    ).title == "运行时设置"
    assert walked == []
    # 反向锁：读面照旧走控制面服务（本波只搬写面）。那句「（版本 N）」只有
    # `ConfigControlService._row` 会印——咽喉侧的 get 分支印的是「（覆盖值）」。
    read_back = build_runtime_admin_result(
        manager, "default", config, request_id="req-get", actor_id=REQUESTER,
        actor_roles=list(SUPER_ROLES), command_text=f"get {R0_KEY}",
        session_key=f"private_{APPROVER}",
    )
    assert "（版本" in read_back.body, f"读面被换掉了：{read_back.body!r}"
    listed = build_runtime_admin_result(
        manager, "default", config, request_id="req-list", actor_id=REQUESTER,
        actor_roles=list(SUPER_ROLES), command_text="list",
        session_key=f"private_{APPROVER}",
    )
    assert R0_KEY in listed.body


# ===========================================================================
# 锁②：直写点名册（咽喉之外的裸 backend 写口）+ 裸 SQL 只准住一个文件
# ===========================================================================

#: 咽喉自身的两个 raw 转发：`_throat_guard` 的 apply 体，门内唯一合法直写口。
_THROAT_INTERNAL_WRITERS = frozenset(
    {
        ("plugins/bot_unified_runtime/domains/chat_reply/runtime/settings.py", "_raw_write"),
        ("plugins/bot_unified_runtime/domains/chat_reply/runtime/settings.py", "_raw_reset"),
    }
)
#: 控制面 HTTP 腿（`bot_control_plane_enabled` 缺省关）：在册残余，**只降不升**，
#: 随旁路收编那一笔（她裁 K-1 第 2 项）清零。单列一本账，免得与「名册外」混成一团。
_FROZEN_HTTP_LEG_WRITERS = frozenset(
    {
        ("plugins/bot_unified_runtime/control_plane/config_service.py", "_write"),
        ("plugins/bot_unified_runtime/control_plane/config_service.py", "reset_all"),
    }
)

_SQL_WRITE_METHODS = frozenset({"set_override", "reset_override"})
_CONFIG_TABLE_WRITE_STATEMENTS = (
    "INSERT INTO config_overrides",
    "UPDATE config_overrides",
    "DELETE FROM config_overrides",
)
CONFIG_STORE_FILE = "plugins/bot_unified_runtime/control_plane/config_store.py"


def _production_sources() -> dict[str, str]:
    sources: dict[str, str] = {}
    for path in sorted(PLUGINS.rglob("*.py")):
        sources[path.relative_to(ROOT).as_posix()] = path.read_text(encoding="utf-8")
    return sources


def _backend_alias_names(scope: ast.AST) -> set[str]:
    """本作用域里被绑定到「文本含 backend 的表达式」的局部名。

    治的是最便宜的绕过形：`be = store.config_backend; be.set_override(...)` ——
    只看接收者文本的话 "be" 不含 "backend"，直写点就从名册缝里溜走了。
    """
    names: set[str] = set()
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign) and "backend" in ast.unparse(node.value).lower():
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def _sql_write_calls(sources: dict[str, str]) -> list[tuple[str, str, str, str, bool]]:
    """全部 `X.set_override(...)` / `X.reset_override(...)` 调用点：
    返回 (文件, 所属函数, 接收者文本, 方法名, 是否裸 backend)。
    「裸 backend」= 接收者文本含 backend **或** 接收者是本作用域里从
    `...backend...` 表达式别名出来的名字（`_backend_alias_names` 治绕行）。
    """
    found: list[tuple[str, str, str, str, bool]] = []

    def visit(node: ast.AST, rel: str, func: str, aliases: set[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                next_func, next_aliases = child.name, _backend_alias_names(child)
            else:
                next_func, next_aliases = func, aliases
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr in _SQL_WRITE_METHODS
            ):
                receiver = ast.unparse(child.func.value)
                backendish = "backend" in receiver.lower() or (
                    isinstance(child.func.value, ast.Name) and child.func.value.id in aliases
                )
                found.append((rel, next_func, receiver, child.func.attr, backendish))
            visit(child, rel, next_func, next_aliases)

    for rel, source in sources.items():
        tree = ast.parse(source)
        visit(tree, rel, "<module>", _backend_alias_names(tree))
    return found


def throat_bypass_violations(sources: dict[str, str]) -> list[str]:
    """纯判据（零落盘）：名册外的裸 backend 直写点、冻结核涨枚、裸 SQL 越狱。"""
    problems: list[str] = []
    hits = {
        (rel, func)
        for rel, func, _receiver, _method, backendish in _sql_write_calls(sources)
        if backendish
    }
    for offender in sorted(hits - _THROAT_INTERNAL_WRITERS - _FROZEN_HTTP_LEG_WRITERS):
        problems.append(f"绕过咽喉的直写点（名册外）：{offender[0]}::{offender[1]}")
    if len(hits & _FROZEN_HTTP_LEG_WRITERS) > len(_FROZEN_HTTP_LEG_WRITERS):  # pragma: no cover
        problems.append(f"控制面 HTTP 腿冻结核涨枚：{sorted(hits & _FROZEN_HTTP_LEG_WRITERS)}")
    for offender in sorted(_FROZEN_HTTP_LEG_WRITERS - hits):
        problems.append(f"冻结核里的直写点已经没了，请降账（只降不升）：{list(offender)}")
    for rel, source in sorted(sources.items()):
        if rel == CONFIG_STORE_FILE:
            continue
        for statement in _CONFIG_TABLE_WRITE_STATEMENTS:
            if statement in source:
                problems.append(f"裸 SQL 写 config 表出现在 {rel}（真身只准住 config_store.py）")
    return problems


def test_direct_write_roster_ast_lock_is_clean_on_real_source() -> None:
    violations = throat_bypass_violations(_production_sources())
    assert violations == [], "\n".join(violations)


def test_session_surface_is_not_a_direct_writer_anymore() -> None:
    """会话命令面必须**只**调咽喉：直调裸 backend 即红（收编的正面判据）。"""
    rel = "plugins/bot_unified_runtime/domains/ops/admin/runtime_admin.py"
    source = (PLUGINS / "bot_unified_runtime/domains/ops/admin/runtime_admin.py").read_text(
        encoding="utf-8"
    )
    calls = _sql_write_calls({rel: source})
    offenders = sorted(
        {(func, receiver) for _rel, func, receiver, _m, backendish in calls if backendish}
    )
    assert offenders == [], f"会话面出现了绕过咽喉的直写点：{offenders}"
    # 反向锁：会话面确实还在调那两个咽喉写面（否则上面的空绿只是因为整段被删了）。
    throat_calls = {
        method for _rel, _f, receiver, method, _b in calls if receiver == "store"
    }
    assert {"set_override", "reset_override"} <= throat_calls, throat_calls


def test_direct_write_roster_ast_lock_has_teeth() -> None:
    """注毒（纯内存，零落盘）：在会话面**再开一个直写点** ⇒ 名册当场点名。"""
    rel = "plugins/bot_unified_runtime/domains/ops/admin/runtime_admin.py"
    sources = _production_sources()
    real = sources[rel]
    anchor = "            changed = service.get(remaining[0])\n"
    poisoned = real.replace(
        anchor,
        "            store.config_backend.set_override(\n"
        '                remaining[0], "x", expected_version=0, actor=actor_id, request_id=request_id,\n'
        "            )\n" + anchor,
        1,
    )
    assert poisoned != real, "注毒锚点已失效 ⇒ 本毒在空跑（须换锚点，不许放宽判据）"
    violations = throat_bypass_violations({**sources, rel: poisoned})
    assert any("runtime_admin.py" in problem for problem in violations), (
        f"新开的直写点没被抓到：{violations}"
    )
    assert not any("冻结核" in problem for problem in violations), (
        f"名册外 offender 被误记成冻结核账：两本账必须分开（{violations}）"
    )
    # 还原形态复绿：同一把尺量真源码仍然干净（红来自毒，不是阈值噪声）。
    assert throat_bypass_violations({**sources, rel: real}) == []


def test_frozen_http_leg_ledger_can_only_shrink() -> None:
    """注毒第二发（纯内存）：把 HTTP 腿那两处直写「假装删掉」⇒ 冻结核必须喊降账，
    不许静默把名册改成小写（那本账是给她裁的，不是给锁偷偷消化的）。"""
    sources = _production_sources()
    rel = "plugins/bot_unified_runtime/control_plane/config_service.py"
    shrunk = sources[rel].replace("self.backend.set_override(", "self.backend.removed_for_poison(")
    shrunk = shrunk.replace("self.backend.reset_override(", "self.backend.removed_for_poison(")
    assert shrunk != sources[rel], "注毒锚点已失效 ⇒ 本毒在空跑"
    violations = throat_bypass_violations({**sources, rel: shrunk})
    assert any("降账" in problem for problem in violations), violations


@pytest.mark.parametrize("statement", _CONFIG_TABLE_WRITE_STATEMENTS)
def test_raw_sql_write_statement_lives_only_in_config_store(statement: str) -> None:
    """裸 SQL 写 config 表只准住一个文件（第二处出现＝第二个写口诞生）。

    三形态里今天只有 INSERT 真在（`_change` 与 `import_legacy` 各一处），
    UPDATE/DELETE 走的是同一行 UPSERT 的 `is_reset` 位——所以判据是
    「除真身之外零命中」，另配一发活性锁证明这条判据不是空跑。
    """
    hits = [rel for rel, source in _production_sources().items() if statement in source]
    assert set(hits) <= {CONFIG_STORE_FILE}, hits


def test_raw_sql_write_statement_lock_is_not_vacuous() -> None:
    """活性：INSERT 那条确实在 config_store.py 里——上面三发不是三条空锁。

    枚数**故意不钉死**（铁律 10 的测试侧同型病：写死「共 N 枚」＝一涨就恒假红）；
    新增写口由上面那把「只准住一个文件」的名册锁抓，同文件内多一处由名册现算兜。
    """
    store_source = (ROOT / CONFIG_STORE_FILE).read_text(encoding="utf-8")
    assert store_source.count("INSERT INTO config_overrides") >= 1, (
        "config_store.py 里的 UPSERT 不见了 ⇒ 写口真身搬家了，本件的判据要跟着搬"
    )


def test_direct_write_roster_catches_local_alias_evasion() -> None:
    """注毒（纯内存，S-THROAT-2 补强）：最便宜的绕行形——把裸 backend 先起个不含
    "backend" 的局部别名再直写 ⇒ 名册必须照样点名（旧版只看接收者文本会放过去）。
    """
    rel = "plugins/bot_unified_runtime/domains/ops/admin/runtime_admin.py"
    sources = _production_sources()
    real = sources[rel]
    anchor = "            changed = service.get(remaining[0])\n"
    poisoned = real.replace(
        anchor,
        "            be = store.config_backend\n"
        "            be.set_override(\n"
        '                remaining[0], "x", expected_version=0, actor=actor_id, request_id=request_id,\n'
        "            )\n" + anchor,
        1,
    )
    assert poisoned != real, "注毒锚点已失效 ⇒ 本毒在空跑（须换锚点，不许放宽判据）"
    violations = throat_bypass_violations({**sources, rel: poisoned})
    assert any(
        "runtime_admin.py" in problem and "_handle_runtime_command" in problem
        for problem in violations
    ), f"别名绕行形没被抓到：{violations}"
    assert throat_bypass_violations({**sources, rel: real}) == []


# ===========================================================================
# 锁③（S-THROAT-2）：session_key 一路传到底——R1 的会话维度不许还是空串
# ===========================================================================


def _approve_message(
    store: Any,
    ticket_row: Any,
    *,
    session_id: str,
    session_type: SessionType,
    roles: list[str],
    sender: str = APPROVER,
) -> Any:
    code = settings_gate.short_code_of(ticket_row)
    return store.safety_gate.approve(
        ticket_row.consent_id,
        code=code,
        message=IncomingMessage(
            platform="qq",
            adapter="onebot",
            bot_id="10000",
            session_id=session_id,
            session_type=session_type,
            sender_id=sender,
            sender_roles=list(roles),
            plain_text=f"同意卡 批 {ticket_row.consent_id} {code}",
        ),
    )


def test_session_command_r1_card_declares_source_session_and_admin_confirms_in_it(
    tmp_path: Path,
) -> None:
    """R1 全程经会话命令面：无票被拒出票（卡面带来源会话）⇒ 换会话批不动 ⇒
    本会话 admin（非超管）亲批 ⇒ 同参数重试落库 ⇒ 同意账 consumed +1、流水 applied。

    这一例同时钉住任务书第 1/4 件的 R1 腿：`session_key` 必须真的从命令面穿到咽喉、
    写进卡面 `source_session_key`——空串会让 consent 的同会话判据整体不启用
    （`consent.py`：`and row.source_session_key`），R1 就退化成「任意私聊 admin+ 可批」。
    """
    manager, store, config = _wired(tmp_path)
    refused = build_runtime_admin_result(
        manager, "default", config, request_id="req-r1-refuse", actor_id=REQUESTER,
        actor_roles=list(SUPER_ROLES), command_text=f"set {R1_KEY} {R1_VALUE}",
        session_key=R1_GROUP_SESSION,
    )
    assert refused.title == "运行时设置失败", f"无票的 R1 写竟然成功了：{refused.body}"
    assert store.list_overrides() == {}, "被拒的 R1 写把值落下去了——拒绝路径泄了"
    pending = store.safety_gate.pending_tickets()
    assert len(pending) == 1, "拒的那次没签出 R1 工单"
    row = pending[0].row
    assert row.tier == "R1"
    assert not row.require_private, "R1 不该要求私聊（那是 R2 的书面档）"
    assert row.source_session_key == R1_GROUP_SESSION, (
        f"卡面来源会话没接上（session_key 没传到底）：{row.source_session_key!r}"
    )

    wrong = _approve_message(
        store, row, session_id="group_631785829_3865067623",
        session_type=SessionType.GROUP, roles=ADMIN_ONLY_ROLES,
    )
    assert isinstance(wrong, Refusal), f"换会话的 admin 批竟然过了：{wrong}"
    assert wrong.kind is DenyKind.APPROVER_NOT_AUTHORISED
    assert len(store.safety_gate.pending_tickets()) == 1, "误批尝试把工单烧掉了"
    assert store.list_overrides() == {}, "被拒的批语路径把值落下去了"

    granted = _approve_message(
        store, row, session_id=R1_GROUP_SESSION,
        session_type=SessionType.GROUP, roles=ADMIN_ONLY_ROLES,
    )
    assert isinstance(granted, ConsentGrant), (
        f"R1 应允许本会话 admin（非超管）确认：{granted}"
    )
    assert store.safety_gate.pending_tickets() == [], "批完卡还挂着（凭证没被消费）"

    applied = build_runtime_admin_result(
        manager, "default", config, request_id="req-r1-apply", actor_id=REQUESTER,
        actor_roles=list(SUPER_ROLES), command_text=f"set {R1_KEY} {R1_VALUE}",
        session_key=R1_GROUP_SESSION,
    )
    assert applied.title == "运行时设置", f"批过的同一条 R1 命令仍写不进：{applied.body}"
    assert store.list_overrides()[R1_KEY] is False, "批完没真落库"
    assert _ledger_states(store, CONSENT_TABLE).count("consumed") == 1, "同意账没跟上 +1"
    assert CHANGE_APPLIED in _ledger_states(store, CHANGE_TABLE), "变更流水没有 applied 终态"


def test_throat_forwards_session_key_verbatim_and_empty_is_explicit(tmp_path: Path) -> None:
    """咽喉侧的会话键契约：交给门的是**清洗后的原值**；缺省空串保持空串。

    空串不许被换成任何「看着像缺省会话」的东西（那会让同会话判据对伪造键生效），
    也不许在命令面被硬写——命令面硬写空串由下面那把 AST 锁抓，这里锁咽喉本体。
    """
    _, store, _ = _wired(tmp_path)

    class _RecordingGate:
        enabled = True

        def __init__(self) -> None:
            self.seen: list[dict[str, Any]] = []

        def guarded_write(self, **kwargs: Any) -> Any:
            self.seen.append({"key": kwargs["key"], "session_key": kwargs["session_key"]})
            return kwargs["apply"]()

    gate = _RecordingGate()
    store.attach_safety_gate(gate)

    store.set_override(R2_KEY, R2_VALUE, actor=REQUESTER, session_key="  private_42  ")
    store.set_override(R0_KEY, R0_VALUE, actor=REQUESTER)  # 无会话上下文调用者：显式缺省
    # 门「放行即执行」的活性：两枚都真落了库（不是只记了形状）。
    assert store.list_overrides()[R2_KEY] is False
    assert store.list_overrides()[R0_KEY] == 5.0
    store.reset_override(R2_KEY, actor=REQUESTER, session_key="group_9_9")
    store.reset_override(None, actor=REQUESTER)  # 全撤：聚合目标 + 空会话串

    assert [entry["session_key"] for entry in gate.seen] == ["private_42", "", "group_9_9", ""]
    assert [entry["key"] for entry in gate.seen] == [
        R2_KEY, R0_KEY, R2_KEY, settings_gate.ALL_OVERRIDES_TARGET,
    ]
    assert store.list_overrides() == {}, "全撤的 apply 体没执行——本锁只看形状不看落地"


def test_runtime_admin_throat_writes_always_carry_session_key() -> None:
    """会话命令面的每一处咽喉写都必须把 `session_key` **形参**交出去。

    判据是形状 + 值名两件事：光有 `session_key=` 不行，还必须是外面传进来的
    `session_key`（硬写 `session_key=""` 或漏参 ⇒ 当场红）。合法的空串只准出现在
    **无会话上下文的调用者**那里（那是调用方的缺省，不是本文件替调用方做的决定）。
    """
    source = (PLUGINS / "bot_unified_runtime/domains/ops/admin/runtime_admin.py").read_text(
        encoding="utf-8"
    )
    offenders = _missing_param_session_key_writes(source)
    assert offenders == [], f"咽喉写点没有转发 session_key 形参：{offenders}"
    # 注毒自证（纯内存）：把一处转发改成硬写空串 ⇒ 同一把尺必须红。
    anchor = 'converted = store.set_override(key, value, actor=actor_id, session_key=session_key)'
    poisoned = source.replace(
        anchor,
        'converted = store.set_override(key, value, actor=actor_id, session_key="")',
        1,
    )
    assert poisoned != source, "注毒锚点已失效 ⇒ 本毒在空跑（须换锚点，不许放宽判据）"
    assert _missing_param_session_key_writes(poisoned) != [], "硬写空串的绕行没被抓到"


def _missing_param_session_key_writes(source: str) -> list[int]:
    """返回「调 store.set_override/reset_override 但没把 session_key 形参传到底」的行号。"""
    offenders: list[int] = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _SQL_WRITE_METHODS
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "store"
        ):
            continue
        forwarded = any(
            kw.arg == "session_key"
            and isinstance(kw.value, ast.Name)
            and kw.value.id == "session_key"
            for kw in node.keywords
        )
        if not forwarded:
            offenders.append(node.lineno)
    return offenders


#: `build_runtime_admin_result` 调用者里**没传 session_key** 的账（文件 → 处数）。
#: 今天全部是「收编没接到的根上缺口」（S-THROAT §⑦-A：改根文件须按在册坐标重锚，
#: 不在席位射程）。这本账**只降不升**：每补一根合法调用者就降一格；谁新增一处
#: 不传会话键的调用点，当场红——这是「空串只准出现在无会话上下文的调用者」
#: 在整个生产面上的那半条锁。
_SESSION_KEY_CALLER_DEBT: dict[str, int] = {
    "plugins/bot_unified_runtime/__init__.py": 3,  # :7722 / :7740 / :9488（message.session_id 就在手边）
    "plugins/bot_unified_runtime/domains/ops/smoke/console_chat.py": 1,  # 控制台无入站会话，属合法空串形态
}


def _session_key_caller_debt(sources: dict[str, str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for rel, source in sources.items():
        for node in ast.walk(ast.parse(source)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "build_runtime_admin_result"
                and not any(kw.arg == "session_key" for kw in node.keywords)
            ):
                counts[rel] = counts.get(rel, 0) + 1
    return counts


def _caller_debt_problems(counts: dict[str, int]) -> list[str]:
    """纯判据（冻结核同一哲学：涨枚当场红，降了必须显式降账）。"""
    problems = [
        f"{rel} 有 {counts[rel]} 处调用没传 session_key，超过在册欠账 "
        f"{_SESSION_KEY_CALLER_DEBT.get(rel, 0)}——新增未传会话键的调用点，不许入册"
        for rel in sorted(counts)
        if counts[rel] > _SESSION_KEY_CALLER_DEBT.get(rel, 0)
    ]
    problems += [
        f"{rel} 的欠账已从 {_SESSION_KEY_CALLER_DEBT[rel]} 降到 {counts.get(rel, 0)}"
        "——请降账（只降不升，账不许被静默消化）"
        for rel in sorted(_SESSION_KEY_CALLER_DEBT)
        if counts.get(rel, 0) < _SESSION_KEY_CALLER_DEBT[rel]
    ]
    return problems


def test_build_runtime_admin_result_callers_missing_session_key_only_shrinks() -> None:
    problems = _caller_debt_problems(_session_key_caller_debt(_production_sources()))
    assert problems == [], "\n".join(problems)
    # 注毒一发（纯内存）：console_chat 那处「假装修好了」⇒ 必须喊降账，
    # 不许有人把这本账改小蒙过去（那本账是给她裁的）。
    rel = "plugins/bot_unified_runtime/domains/ops/smoke/console_chat.py"
    sources = _production_sources()
    fixed = sources[rel].replace(
        'request_id="console-admin",',
        'request_id="console-admin", session_key="console_session",',
        1,
    )
    assert fixed != sources[rel], "注毒锚点已失效 ⇒ 本毒在空跑"
    problems = _caller_debt_problems(_session_key_caller_debt({**sources, rel: fixed}))
    assert any("降账" in problem for problem in problems), problems
    # 反向注毒：再开一处不传会话键的调用点 ⇒ 涨账同样当场红。
    grown = sources[rel] + (
        "\n\ndef _poison_extra_caller(manager, default_instance, config):\n"
        "    return build_runtime_admin_result(\n"
        "        manager, default_instance, config, request_id=\"poison\",\n"
        "        actor_roles=[\"super_admin\", \"admin\"], command_text=\"list\",\n"
        "    )\n"
    )
    problems = _caller_debt_problems(_session_key_caller_debt({**sources, rel: grown}))
    assert any("不许入册" in problem for problem in problems), problems
