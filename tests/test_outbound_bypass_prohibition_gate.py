"""Wave 4.2「B 类直 `call_api` 旁路」禁止式门（统一接入波 SEAT-U4，2026-09-21）。

> 2026-09-22 SEAT-S-W42 扩面：新增「A 类裸 `send_queue.submit` 旁路」维度（见文件
> 末 A 类段），与上半部 B 类互补、共用同一扫描面，故扩本件而非另建第二把扫全树的门。
> 分工详见 `.superpowers/sdd/2026-09-21-unify-wave/logs/SEAT-S-W42.md` §2/§3。

用户令：所有内容走中央调度层。规格 `docs/design/capability-orchestration-adoption-spec.md`
§4.2 定的判据原文：「根文件与 `domains/**`（sender 漏斗最底层除外）出现
`call_api("send_*` / `send_group_msg` / `send_private_msg` 即红」。本件就是那句话的
可执行形态。

它取代谁（§7 禁第三套问答）：**纯新增门，无取代对象**（规格 §7 表已把它登记为常驻新增门）。
它与 `domains/core/decision/outbound_registry.py` 的 `DirectSendEntry` 关系 =
**登记表是叙事册（人工维护、含历史注记、行号只做说明用），本件是执法表（AST 实测、
按「路径 + API + 条数」比对）**。二者不合并的理由与合并建议见
`.superpowers/sdd/2026-09-21-unify-wave/logs/SEAT-U4.md` §5。

本批**不改任何投递语义**：现存旁路全部逐条挂名豁免（每条必须是「门关旧直连分支」，
即上方 60 行内存在缺省 False 的 `getattr(config, "<*_via_queue>", False)` 卫哨），
新写的直发没有豁免表条目 ⇒ 当场红。
"""

from __future__ import annotations

import ast
import pathlib
from dataclasses import dataclass

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG_ROOT = REPO_ROOT / "plugins" / "bot_unified_runtime"

#: 判据锁定的三类出站直发（规格 §4.2 原文口径）。
SEND_API_NAMES = frozenset({"send_group_msg", "send_private_msg"})

#: sender 漏斗最底层＝唯一合法的协议通道本体，按规格排除在扫描面之外。
SENDER_FUNNEL_DIRS = ("domains/transport/sender/",)


@dataclass(frozen=True)
class BypassExemption:
    """一条在册旁路的豁免理由（必须可核：路径 + API + 条数 + 门关卫哨键）。"""

    path: str
    api: str
    count: int
    gate_key: str
    reason: str
    registry_ref: str


def _exempt(path: str, api: str) -> bool:
    return any(
        path.startswith(prefix) and f"{prefix}" in path for prefix in SENDER_FUNNEL_DIRS
    )


def scan_send_bypasses(package_root: pathlib.Path) -> dict[tuple[str, str], list[int]]:
    """AST 扫描根 `__init__.py` + `domains/**`，返回 {(相对路径, API): [行号…]}。

    命中形态（只认这三类，避免把注册表里的字符串常量算成旁路）：
    ① `x.call_api("send_…", …)` 首参为字符串字面量且以 `send_` 起头；
    ② 属性直发 `x.send_group_msg` / `x.send_private_msg`（含 `await bot.send_group_msg(...)`）。
    """
    files = [package_root / "__init__.py"]
    files.extend(sorted((package_root / "domains").rglob("*.py")))
    found: dict[tuple[str, str], list[int]] = {}
    for file in files:
        if not file.exists():
            continue
        rel = file.relative_to(package_root).as_posix()
        if any(rel.startswith(prefix) for prefix in SENDER_FUNNEL_DIRS):
            continue
        try:
            tree = ast.parse(file.read_text(encoding="utf-8"))
        except SyntaxError as exc:  # 语法错误由静态门处理，这里如实报错不静默跳过
            raise AssertionError(f"禁止式门无法解析 {rel}: {exc}") from exc
        for node in ast.walk(tree):
            api: str | None = None
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "call_api"
                and node.args
            ):
                first = node.args[0]
                if (
                    isinstance(first, ast.Constant)
                    and isinstance(first.value, str)
                    and first.value.startswith("send_")
                ):
                    api = first.value
            elif isinstance(node, ast.Attribute) and node.attr in SEND_API_NAMES:
                api = node.attr
            if api is None:
                continue
            found.setdefault((rel, api), []).append(int(getattr(node, "lineno", 0)))
    return found


#: 现存 B 类旁路逐条挂名（2026-09-21 实测：根文件 4 处、`domains/**` 零处）。
#: 四条全是「S0 收编的门关旧直连分支」——门开即走 SendQueue/统一管线，门缺省 False
#: 才落到这里。收编施工图见 SEAT-U4.md §4。
BYPASS_EXEMPTIONS: tuple[BypassExemption, ...] = (
    BypassExemption(
        path="__init__.py",
        api="send_private_msg",
        count=2,
        gate_key="bot_cookie_expiry_reminder_via_queue | bot_cookie_qr_via_queue",
        reason=(
            "cookie 到期提醒 job 门关分支 + cookie 登录二维码图片 else 分支"
            "（S0 收编①③，规格 §4.2 所称「cookie 兜底」即此）"
        ),
        registry_ref="outbound_registry.DirectSendEntry「__init__.py:4440-4444」/「5730-5740」",
    ),
    BypassExemption(
        path="__init__.py",
        api="send_group_msg",
        count=2,
        gate_key="bot_group_welcome_via_queue | bot_cookie_qr_via_queue",
        reason=(
            "入群欢迎 notice handler 门关分支（S0 收编②）+ cookie 登录二维码图片群聊分支"
            "（S0 收编③；规格 §4.2 误标为「随机图主动发」，实测全树零随机图直发，见 O5 账）"
        ),
        registry_ref="outbound_registry.DirectSendEntry「__init__.py:5378-5382」/「5730-5740」",
    ),
)


def _table() -> dict[tuple[str, str], BypassExemption]:
    return {(row.path, row.api): row for row in BYPASS_EXEMPTIONS}


def _unexempted(
    found: dict[tuple[str, str], list[int]], table: dict[tuple[str, str], BypassExemption]
) -> list[str]:
    """把「表外新写」与「条数超册」判成违规，返回人话清单。"""
    problems: list[str] = []
    for (rel, api), lines in sorted(found.items()):
        row = table.get((rel, api))
        if row is None:
            problems.append(
                f"{rel}:{lines[0]} 新写直发 `{api}`（表外旁路）——"
                f"必须改走 SendQueue/outbound_gate 或 `_send_text_through_unified_pipeline`"
            )
        elif len(lines) > row.count:
            problems.append(
                f"{rel} 的 `{api}` 实有 {len(lines)} 处 > 在册 {row.count} 处，"
                f"多出行={lines[row.count:]}（豁免按条数封顶，不给你白涨）"
            )
    return problems


# ---------- ① 执法面 ----------


def test_scan_targets_root_and_domains() -> None:
    """扫描面必须真的含根文件与 domains/**，否则整扇门是空转假绿。"""
    files = [PKG_ROOT / "__init__.py"] + sorted((PKG_ROOT / "domains").rglob("*.py"))
    assert (PKG_ROOT / "__init__.py").is_file()
    assert len(files) > 400, f"扫描面异常收缩，仅 {len(files)} 件——门形同虚设"


def test_no_unexempted_send_bypass() -> None:
    """主判据：表外直发即红（规格 §4.2「禁止式门」原句）。"""
    found = scan_send_bypasses(PKG_ROOT)
    problems = _unexempted(found, _table())
    assert not problems, "发现未登记出站直发旁路：\n" + "\n".join(problems)


def test_exemption_table_covers_actual_bypasses_exactly() -> None:
    """豁免表不许留幽灵行：在册条数必须与实到条数逐 API 相等。

    旁路被收编走却没删条目 ⇒ 本例红，逼着收编席同批改表（防「豁免表只涨不消」）。
    """
    found = scan_send_bypasses(PKG_ROOT)
    table = _table()
    for (rel, api), row in sorted(table.items()):
        actual = len(found.get((rel, api), []))
        assert actual == row.count, (
            f"豁免表漂移：{rel} `{api}` 在册 {row.count} 处、实到 {actual} 处。"
            f"旁路收编后要删行，别留幽灵豁免。"
        )


def test_every_exempted_bypass_is_gate_closed_legacy_branch() -> None:
    """在册旁路必须个个「门关分支」：调用点上方 60 行内存在缺省 False 的 `*_via_queue` 卫哨。

    这条把「豁免」和「无门直发」区分开——本波只清点、不改投递语义的前提就是
    现存四条全部受开关控制、门开即走中央管线。
    """
    source_lines = (PKG_ROOT / "__init__.py").read_text(encoding="utf-8").splitlines()
    found = scan_send_bypasses(PKG_ROOT)
    for (rel, api), row in _table().items():
        assert rel == "__init__.py", "本例只核根文件的门关性"
        gate_keys = [key.strip() for key in row.gate_key.split("|")]
        for line_no in found[(rel, api)]:
            window = "\n".join(source_lines[max(0, line_no - 61) : line_no - 1])
            assert any(key in window for key in gate_keys), (
                f"{rel}:{line_no} 的 `{api}` 上方 60 行内找不到 {gate_keys} 卫哨——"
                f"它不是门关分支（新无门直发，或卫哨离得太远需单独收编）"
            )


def test_exempted_rows_carry_auditable_reason() -> None:
    """每条豁免必须带理由 + 关键 + 登记册指针，且理由里点名收编出处（防一格一词糊门）。"""
    for row in BYPASS_EXEMPTIONS:
        assert len(row.reason) >= 24, f"{row.path}/{row.api} 理由过短，不可审计"
        assert row.gate_key, f"{row.path}/{row.api} 缺门关卫哨键"
        assert "outbound_registry" in row.registry_ref, "豁免须指回叙事登记册条目"


# ---------- ② 注毒自证：这扇门真的会红 ----------


def test_poison_new_bypass_line_turns_gate_red(tmp_path: pathlib.Path) -> None:
    """注毒：新写一处 `call_api("send_group_msg"` ⇒ 扫描必命中、判据必红。"""
    fake = tmp_path / "plugins_pkg"
    (fake / "domains" / "demo").mkdir(parents=True)
    (fake / "__init__.py").write_text(
        "async def handler(bot):\n"
        '    await bot.call_api("send_group_msg", group_id=1, message=[])\n',
        encoding="utf-8",
    )
    (fake / "domains" / "demo" / "cap.py").write_text(
        "async def other(bot):\n    await bot.send_private_msg(user_id=2)\n",
        encoding="utf-8",
    )
    found = scan_send_bypasses(fake)
    assert {("__init__.py", "send_group_msg"): [2]} == {
        k: v for k, v in found.items() if k[0] == "__init__.py"
    }
    problems = _unexempted(found, {})
    assert len(problems) == 2, f"掏空豁免表后应两条全红，现={problems}"


def test_poison_sender_funnel_stays_out_of_scope(tmp_path: pathlib.Path) -> None:
    """注毒：漏斗最底层（sender/）按规格不扫——它写了也不能被当旁路，但别指望能借道藏。"""
    fake = tmp_path / "plugins_pkg"
    (fake / "domains" / "transport" / "sender").mkdir(parents=True)
    (fake / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    (fake / "domains" / "transport" / "sender" / "onebot.py").write_text(
        'async def f(bot):\n    await bot.call_api("send_group_msg")\n', encoding="utf-8"
    )
    assert scan_send_bypasses(fake) == {}


def test_empty_exemption_table_would_flag_all_live_bypasses() -> None:
    """注毒：把豁免表掏空 ⇒ 现存旁路全数现形（证明豁免是白、不是门本身松）。"""
    found = scan_send_bypasses(PKG_ROOT)
    live_total = sum(len(lines) for lines in found.values())
    assert live_total == 4, f"现存根文件直发条数与清点账不符，现={live_total}"
    assert len(_unexempted(found, {})) == len(found) == 2


def test_random_picture_domain_has_no_direct_send_bypass() -> None:
    """O5 实证锁：`domains/meme/**`（随机图/表情）零直发 ⇒ 规格 §4.2「随机图主动发
    :5959/:5965」不是随机图，那两行实为 cookie 登录二维码分支；本波不擅自收编、
    也不为不存在的旁路立豁免。"""
    found = scan_send_bypasses(PKG_ROOT)
    meme_hits = {key: lines for key, lines in found.items() if key[0].startswith("domains/meme/")}
    assert meme_hits == {}, f"meme 域出现新的直发旁路，需按 §4.2 收编：{meme_hits}"


@pytest.mark.parametrize("api", sorted(SEND_API_NAMES))
def test_gate_scope_excludes_only_sender_funnel(api: str) -> None:
    """口径自检：豁免前缀只有 sender 一条，防后来人偷偷加目录把门开大。"""
    assert SENDER_FUNNEL_DIRS == ("domains/transport/sender/",)
    assert api in {"send_group_msg", "send_private_msg"}


# =========================================================================
# Wave 4.2「A 类裸 send_queue.submit 旁路」维度（SEAT-S-W42，2026-09-22 扩面）
#
# 分工（§7 禁第三套自查）：上半部（U4 建）扫 B 类 `call_api("send_*` /
# `send_group_msg` / `send_private_msg`（绕过队列的直发）；本半部扫 A 类
# 「有队列、但绕过 outbound_gate 静默窗/限流/审计的裸 `send_queue.submit`」。
# 同一扫描面（根 + domains/**，sender 漏斗除外）⇒ 合并在同一件，不建第二把
# 扫全树的门。二者互补：B 类=不排队直发，A 类=排队但不走中央闸。
# 中央投递出口 `submit_active_push` 本体在 `domains/transport/sender/`，天然豁免。
#
# 已知局限（如实登记不粉饰）：别名裸调 `submit = x.send_queue.submit; submit(req)`
# （如 error_report.py:1052/1054）AST 接收者判据扫不到——见
# `test_poison_submit_alias_escapes_by_design` 自证。收编施工图见
# `.superpowers/sdd/2026-09-21-unify-wave/logs/SEAT-S-W42.md` §5。
# =========================================================================

#: submit 旁路的接收者标识：`send_queue`（裸 Name）或链中属性 `.send_queue` / `._queue`。
SUBMIT_QUEUE_ATTRS = frozenset({"send_queue", "_queue"})


@dataclass(frozen=True)
class SubmitBypassExemption:
    """一条在册裸 submit 旁路（按文件路径计条数封顶 + 改道去向）。"""

    path: str
    count: int
    retire_to: str
    reason: str


def _submit_receiver_is_queue(node: ast.Call) -> bool:
    """`<base>.submit(...)` 且 base 链含 send_queue / _queue 才判命中。

    命中：send_queue.submit / self.send_queue.submit / pipeline.send_queue.submit /
    self._queue.submit。不命中：submit(...)（别名裸调，见上）、pool.submit、
    executor.submit、review_gate.submit、ledger sink.submit 等非投递队列提交。
    """
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr == "submit"):
        return False
    cur: ast.expr = func.value
    if isinstance(cur, ast.Name) and cur.id in SUBMIT_QUEUE_ATTRS:
        return True
    while isinstance(cur, ast.Attribute):
        if cur.attr in SUBMIT_QUEUE_ATTRS:
            return True
        cur = cur.value
    return False


def scan_submit_bypasses(package_root: pathlib.Path) -> dict[str, list[int]]:
    """扫描根 + `domains/**`（sender 漏斗除外），返回 {相对路径: [submit 行号…]}。"""
    files = [package_root / "__init__.py"]
    files.extend(sorted((package_root / "domains").rglob("*.py")))
    found: dict[str, list[int]] = {}
    for file in files:
        if not file.exists():
            continue
        rel = file.relative_to(package_root).as_posix()
        if any(rel.startswith(prefix) for prefix in SENDER_FUNNEL_DIRS):
            continue
        try:
            tree = ast.parse(file.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            raise AssertionError(f"submit 旁路门无法解析 {rel}: {exc}") from exc
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _submit_receiver_is_queue(node):
                found.setdefault(rel, []).append(int(getattr(node, "lineno", 0)))
    return found


#: 现存 A 类裸 submit 旁路逐条挂名（2026-09-22 实测：共 8 处 / 4 文件）。
#: 全部登记为「待改道 submit_active_push」——改道当笔删行，幽灵豁免会当场红。
SUBMIT_BYPASS_EXEMPTIONS: tuple[SubmitBypassExemption, ...] = (
    SubmitBypassExemption(
        path="__init__.py",
        count=4,
        retire_to="submit_active_push（提醒/摘要/早晚报/cookie到期各带 dedupe_family）",
        reason=(
            "root 四条主动投递裸 submit：:2954 提醒(带 :2964 内联绕 worker)、"
            ":3065 cookie到期门开分支、:3223 每日群摘要、:3372 日常助理私聊推"
        ),
    ),
    SubmitBypassExemption(
        path="domains/chat_reply/runtime/pipeline.py",
        count=2,
        retire_to="主输出步:896=层1正当出口常驻在册；ack:945 若挂入站事件改走 _send_text_through_unified_pipeline",
        reason=(
            ":896 中央 pipeline 主输出提交步(非旁路，上游已过 gate/review/render，登记以免误判新增)；"
            ":945 群失败 ack 自带滑窗节流但绕 outbound_gate(A 类)"
        ),
    ),
    SubmitBypassExemption(
        path="domains/ops/monitor/error_report.py",
        count=1,
        retire_to="评估纳入 outbound_gate 冷却/静默窗(已有 ErrorCardGate，改道须单独回归 deliver_after≥3s)",
        reason=(
            "错误卡文本回执段 :1037 自带 ErrorCardGate 冷却闸但不经 outbound_gate(A 类)；"
            ":1052/1054 为别名裸调，AST 判据逃逸(见 §6 局限)"
        ),
    ),
    SubmitBypassExemption(
        path="domains/schedule/delivery.py",
        count=1,
        retire_to="接线(生产零装配)前必须先改 submit_active_push，禁止直 submit",
        reason="S11 occurrence 投递门面 self._queue.submit(:233)——干跑件、消费者仅两测试件，非现行生产旁路",
    ),
)


def _submit_table() -> dict[str, SubmitBypassExemption]:
    return {row.path: row for row in SUBMIT_BYPASS_EXEMPTIONS}


def _unexempted_submit(
    found: dict[str, list[int]], table: dict[str, SubmitBypassExemption]
) -> list[str]:
    problems: list[str] = []
    for rel, lines in sorted(found.items()):
        row = table.get(rel)
        if row is None:
            problems.append(
                f"{rel}:{lines[0]} 新写裸 `send_queue.submit`/`._queue.submit`（表外旁路）"
                f"——改走 submit_active_push 或 _send_*_through_unified_pipeline"
            )
        elif len(lines) > row.count:
            problems.append(
                f"{rel} 裸 submit 实有 {len(lines)} 处 > 在册 {row.count} 处，多出行={lines[row.count:]}"
            )
    return problems


# ---------- A 类 submit 执法面 ----------


def test_live_submit_bypass_total_matches_ledger() -> None:
    """清点账自检：现存裸 submit 恰 8 处（防空转假绿 + 防无声涨账）。"""
    found = scan_submit_bypasses(PKG_ROOT)
    assert sum(len(v) for v in found.values()) == 8, found


def test_no_unexempted_submit_bypass() -> None:
    """主判据：表外新写、或同文件条数超册 ⇒ 红。"""
    found = scan_submit_bypasses(PKG_ROOT)
    problems = _unexempted_submit(found, _submit_table())
    assert not problems, "发现未登记裸 submit 旁路：\n" + "\n".join(problems)


def test_submit_exemption_table_covers_actual_exactly() -> None:
    """幽灵豁免锁：改道后没删行 ⇒ 实到 < 在册 ⇒ 红（机器替代「记得改回来」）。"""
    found = scan_submit_bypasses(PKG_ROOT)
    for rel, row in _submit_table().items():
        actual = len(found.get(rel, []))
        assert actual == row.count, (
            f"submit 豁免表漂移：{rel} 在册 {row.count} 处、实到 {actual} 处——改道后删行，别留幽灵豁免"
        )


def test_submit_exempted_rows_carry_retire_plan() -> None:
    """每条 submit 豁免必须给「改道去向 + 可审计理由」（防一格一词糊门）。"""
    for row in SUBMIT_BYPASS_EXEMPTIONS:
        assert row.retire_to and len(row.retire_to) >= 12, f"{row.path} 缺改道去向"
        assert len(row.reason) >= 24, f"{row.path} 理由过短，不可审计"


# ---------- A 类 submit 注毒自证 ----------


def test_poison_new_submit_bypass_forms_turn_red(tmp_path: pathlib.Path) -> None:
    """注毒：三种接收者形态各造一处 ⇒ 全命中且掏空表后全红。"""
    fake = tmp_path / "plugins_pkg"
    (fake / "domains" / "demo").mkdir(parents=True)
    (fake / "__init__.py").write_text(
        "def a(send_queue, req):\n    send_queue.submit(req)\n",  # 裸 Name
        encoding="utf-8",
    )
    (fake / "domains" / "demo" / "cap.py").write_text(
        "class C:\n"
        "    def b(self, req):\n        self.send_queue.submit(req)\n"  # self.send_queue
        "    def c(self, req):\n        self._queue.submit(req)\n",  # self._queue
        encoding="utf-8",
    )
    found = scan_submit_bypasses(fake)
    assert found == {"__init__.py": [2], "domains/demo/cap.py": [3, 5]}, found
    assert len(_unexempted_submit(found, {})) == 2  # 两个文件各一组问题


def test_poison_submit_alias_escapes_by_design(tmp_path: pathlib.Path) -> None:
    """自证已知局限：别名裸调 `submit = x.send_queue.submit; submit(req)` 扫不到。

    这不是把门做窄，而是如实钉住「AST 接收者判据的边界」——万一将来有人误以为
    本门能挡所有 submit，此例以红→改判据的方式逼他重新评估；当前 error_report
    :1052/:1054 就落在此逃逸面内（已在豁免理由点名）。
    """
    fake = tmp_path / "plugins_pkg"
    (fake / "domains").mkdir(parents=True)
    (fake / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    (fake / "domains" / "alias.py").write_text(
        "def f(pipeline, req):\n"
        "    submit = pipeline.send_queue.submit\n"  # Store，非 Call：不命中
        "    submit(req)\n",  # 裸 Name call：接收者判据不命中
        encoding="utf-8",
    )
    assert scan_submit_bypasses(fake) == {}


def test_non_queue_submit_is_not_flagged(tmp_path: pathlib.Path) -> None:
    """反向锁：线程池/审核门/账本 sink 的 .submit 不得被当旁路（防豁免表被误报淹没）。"""
    fake = tmp_path / "plugins_pkg"
    (fake / "domains").mkdir(parents=True)
    (fake / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    (fake / "domains" / "noise.py").write_text(
        "def f(pool, gate, sink, ex, req):\n"
        "    pool.submit(req)\n    gate.review_gate.submit(req)\n"
        "    sink._ledger_sink.submit(req)\n    ex.executor.submit(req)\n",
        encoding="utf-8",
    )
    assert scan_submit_bypasses(fake) == {}


def test_sender_funnel_submit_stays_out_of_scope(tmp_path: pathlib.Path) -> None:
    """中央投递出口 `submit_active_push` 本体（sender 漏斗）天然豁免，不误伤。"""
    fake = tmp_path / "plugins_pkg"
    (fake / "domains" / "transport" / "sender").mkdir(parents=True)
    (fake / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    (fake / "domains" / "transport" / "sender" / "outbound_gate.py").write_text(
        "def submit_active_push(send_queue, req):\n    return send_queue.submit(req)\n",
        encoding="utf-8",
    )
    assert scan_submit_bypasses(fake) == {}
