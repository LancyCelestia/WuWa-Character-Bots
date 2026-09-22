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
# 已知局限：①别名裸调 `submit = x.send_queue.submit; submit(req)` —— **2026-09-22 已收编**
# （S-BYPASS 实证该逃逸面真的吞掉了 error_report 两条在跑的投递，判据升级为
# `_submit_alias_names`：按**作用域**把绑到队列 `.submit` 的局部名一并计命中，
# 见 `test_submit_alias_is_caught_within_scope_only`）。登记这条历史不是为了记账，
# 是为了说清"清点账 6→8 那两条一直都在，是门瞎"。
# ②异名接收者（队列实例绑到词表外变量名）同样逃逸；全树唯一真实例
# （smoke.py 裸 `queue`，S-W42 后由 S-FIXB 实测发现）已扩词表收进判据面，
# 残余异名面（self.send_q/self.q/self._q 类）见
# `test_poison_divergently_named_receiver_escapes_by_design` 自证=登记的局限非判据正确。
# 收编施工图见 `.superpowers/sdd/2026-09-21-unify-wave/logs/SEAT-S-W42.md` §5。
# =========================================================================

#: submit 旁路的接收者标识：`send_queue`/`queue`（裸 Name）或链中属性 `.send_queue` / `._queue` / `.queue`。
#: `queue` 为 S-FIXB 账2 新增：smoke.py:1151/1152 用异名 `queue` 绑 SQLiteSendRequestQueue，
#: 系全树唯一真实异名接收者（实测登记），不扩则它静默逃逸。
SUBMIT_QUEUE_ATTRS = frozenset({"send_queue", "_queue", "queue"})


@dataclass(frozen=True)
class SubmitBypassExemption:
    """一条在册裸 submit 旁路（按文件路径计条数封顶 + 改道去向）。"""

    path: str
    count: int
    retire_to: str
    reason: str


def _queue_base_is_receiver(base: ast.expr) -> bool:
    """`<base>` 这条链是不是"队列实例"（裸名或链中属性命中词表即算）。"""
    if isinstance(base, ast.Name) and base.id in SUBMIT_QUEUE_ATTRS:
        return True
    cur: ast.expr = base
    while isinstance(cur, ast.Attribute):
        if cur.attr in SUBMIT_QUEUE_ATTRS:
            return True
        cur = cur.value
    return False


def _submit_receiver_is_queue(node: ast.Call) -> bool:
    """`<base>.submit(...)` 且 base 链含 send_queue / _queue / queue 才判命中。

    命中：send_queue.submit / self.send_queue.submit / pipeline.send_queue.submit /
    self._queue.submit / queue.submit。不命中：`submit(...)`（别名裸调——**2026-09-22 起
    由 `_submit_alias_names` 单独收编**，不再算逃逸面）、
    self.send_q/self.q/self._q（词表外异名，见局限②）、pool.submit、executor.submit、
    review_gate.submit、ledger sink.submit 等非投递队列提交（段名精确匹配，
    task_queue 类前缀近似不连带误伤）。
    """
    func = node.func
    return bool(
        isinstance(func, ast.Attribute)
        and func.attr == "submit"
        and _queue_base_is_receiver(func.value)
    )


def _own_nodes(scope: ast.AST):
    """该作用域**自己**的节点：不下钻进更内层的函数。

    没有这一步，模块作用域会把函数里的 `submit = …send_queue.submit` 当作全局绑定，
    于是另一个同名函数里的 `submit(req)` 被算成投递旁路（假阳性）。
    """
    stack: list[ast.AST] = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue  # 内层函数由它自己那一份统计负责
        yield node
        stack.extend(ast.iter_child_nodes(node))


def _submit_alias_names(scope: ast.AST) -> set[str]:
    """该作用域内把队列 `.submit` **绑成局部名**的别名（局限①的收编判据）。

    形如 `submit = pipeline.send_queue.submit` 的赋值是 **Store 侧**、不是 Call，
    所以接收者判据结构性看不见它，随后的 `submit(req)` 就成了静默逃逸
    （S-BYPASS 实证：本门只报 `error_report.py:1037`，真正发出去的两条在 :1052/:1054，
    两个集合交集为空）。按**作用域**收别名而不是全文件一把抓：`submit` 这种短名
    在别的函数里可能指完全不同的东西，全局匹配会造出假阳性、进而逼人放宽判据。
    """
    names: set[str] = set()
    for node in _own_nodes(scope):
        if not isinstance(node, ast.Assign):
            continue
        value = node.value
        if isinstance(value, ast.Attribute) and value.attr == "submit" and _queue_base_is_receiver(
            value.value
        ):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def _file_submit_bypass_lines(tree: ast.Module) -> list[int]:
    """一个文件里所有 A 类裸 submit 行号（直调 ∪ 别名裸调），去重升序。"""
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _submit_receiver_is_queue(node):
            lines.add(int(getattr(node, "lineno", 0)))
    scopes: list[ast.AST] = [
        tree,
        *(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)),
    ]
    for scope in scopes:
        aliases = _submit_alias_names(scope)
        if not aliases:
            continue
        for node in _own_nodes(scope):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in aliases
            ):
                lines.add(int(getattr(node, "lineno", 0)))
    return sorted(lines)


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
        lines = _file_submit_bypass_lines(tree)
        if lines:
            found[rel] = lines
    return found


#: 现存 A 类裸 submit 旁路逐条挂名（2026-09-22 实测+S-FIXB 扩词表收编：原 10 处 / 5 文件；
#: Wave 4.2/4.3 逐批改道 ⇒ root 四条主动投递已全部接中央出口、整行删净；
#: 同日 S-BYPASS 把**别名裸调**收编进判据 ⇒ 现役 **8 处 / 4 文件**，比旧清点多出 error_report 两条
#: ——那两条一直都在，是门瞎，不是代码变坏。计数上升一次是"补视力量"，不是新欠债）。
#: 前 4 处登记为「待改道 submit_active_push」——改道当笔删行，幽灵豁免会当场红；
#: smoke 两条为「自测器演练 submit API 本体」（临时库+fake transport 永不外发），无改道义务，
#: 但实例数一变本行照样红，逼着重估——不许借「自测」名义给门留暗门。
SUBMIT_BYPASS_EXEMPTIONS: tuple[SubmitBypassExemption, ...] = (
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
        count=3,
        retire_to="裁定=不迁移（S-BYPASS 判定：回合内诊断面，非主动投递族）；"
                  "真要收编须先解决两件事：丢 caller 侧 deliver_after≥3s 的 A-plus 次序、"
                  "邮件键 `email:…@…` 过不了键规范（实测 False）",
        reason=(
            "错误卡两段式投递：:1037 文本回执直调、:1052/:1054 卡片补发经别名 "
            "`submit = pipeline.send_queue.submit`——**别名面 2026-09-22 已由 "
            "`_submit_alias_names` 收编进判据**（此前只登记 1 处、真发两条静默逃逸）。"
            "自带 ErrorCardGate 冷却闸但不经 outbound_gate(A 类)，且已在件内打 "
            "_GATE_BYPASS_TAG='gate:bypass_by_design'"
        ),
    ),
    SubmitBypassExemption(
        path="domains/schedule/delivery.py",
        count=1,
        retire_to="接线(生产零装配)前必须先改 submit_active_push，禁止直 submit",
        reason="S11 occurrence 投递门面 self._queue.submit(:233)——干跑件、消费者仅两测试件，非现行生产旁路",
    ),
    SubmitBypassExemption(
        path="domains/ops/smoke/smoke.py",
        count=2,
        retire_to="无改道义务：run_queue_smoke 演练队列 submit API 本体（:1133 临时库实例+fake transport 永不外发），改名或迁出扫描面前本行常驻",
        reason=(
            "异名接收者裸 `queue.submit`(:1151/:1152)——S-FIXB 账2 实测全树唯一真实例，"
            "扩 SUBMIT_QUEUE_ATTRS 收进判据面后按条数登记，量变即红"
        ),
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
    """清点账自检：现存裸 submit **恰 8 处**。

    轨迹与口径（2026-09-22 更正本 docstring——它一直写着"6 处"而断言是 8，
    典型的注释比代码先腐烂）：原 10 处 → Wave 4.2/4.3 把 root 四条改走中央出口 = 6 处 →
    别名入口收编时把扫描面按作用域修正，**又照出两条一直都在的**（门瞎，不是码坏）= 8 处。
    "只准降"由**逐文件豁免表**执法（多一处红、少一处也红＝幽灵豁免锁），
    本条总数断言只作自检：改站点数必须同时改表，逼人来核。
    """
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
    """注毒：四种接收者形态各造一处 ⇒ 全命中且掏空表后全红（含 S-FIXB 扩的裸 `queue` 异名）。"""
    fake = tmp_path / "plugins_pkg"
    (fake / "domains" / "demo").mkdir(parents=True)
    (fake / "__init__.py").write_text(
        "def a(send_queue, req):\n    send_queue.submit(req)\n",  # 裸 Name send_queue
        encoding="utf-8",
    )
    (fake / "domains" / "demo" / "cap.py").write_text(
        "class C:\n"
        "    def b(self, req):\n        self.send_queue.submit(req)\n"  # self.send_queue
        "    def c(self, req):\n        self._queue.submit(req)\n",  # self._queue
        encoding="utf-8",
    )
    (fake / "domains" / "demo" / "renamed.py").write_text(
        "def d(queue, req):\n    queue.submit(req)\n",  # 异名裸 Name（smoke 同款，已收编判据面）
        encoding="utf-8",
    )
    found = scan_submit_bypasses(fake)
    assert found == {
        "__init__.py": [2], "domains/demo/cap.py": [3, 5], "domains/demo/renamed.py": [2],
    }, found
    assert len(_unexempted_submit(found, {})) == 3  # 三个文件各一组问题


def test_submit_alias_is_caught_within_scope_only(tmp_path: pathlib.Path) -> None:
    """别名裸调判据的两面：作用域内必须抓到，作用域外不得假阳性。

    收编前这里是一条"如实登记的逃逸面"自证（S-BYPASS 用它证明门瞎——error_report 真发的
    两条一直落在逃逸面里）；收编后同一形态必须命中。反向半边同样重要：`submit` 这种短名
    在别的函数里可能指线程池或别的东西，全局匹配会造出假阳性，而假阳性的下场是逼人放宽
    判据——那比漏报更常发生。
    """
    fake = tmp_path / "plugins_pkg"
    (fake / "domains").mkdir(parents=True)
    (fake / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    (fake / "domains" / "alias.py").write_text(
        "def f(pipeline, req):\n"
        "    submit = pipeline.send_queue.submit\n"  # 队列 .submit 绑成局部名
        "    submit(req)\n",  # 别名裸调：现在必须命中
        encoding="utf-8",
    )
    (fake / "domains" / "unrelated.py").write_text(
        "def g(pool, req):\n"
        "    submit = pool.submit\n"  # 线程池，不是投递队列
        "    submit(req)\n",
        encoding="utf-8",
    )
    (fake / "domains" / "otherscope.py").write_text(
        "def h(req):\n"
        "    submit(req)\n"  # 本作用域内没有队列绑定 ⇒ 不算命中
        "\n"
        "\n"
        "def k(pipeline, req):\n"
        "    submit = pipeline.send_queue.submit\n"
        "    submit(req)\n",  # 这个作用域里有绑定 ⇒ 命中
        encoding="utf-8",
    )
    found = scan_submit_bypasses(fake)
    assert found == {
        "domains/alias.py": [3],
        "domains/otherscope.py": [7],
    }, found


def test_poison_divergently_named_receiver_escapes_by_design(tmp_path: pathlib.Path) -> None:
    """自证已知局限②：词表外异名接收者（self.send_q/self.q/self._q）判据扫不到=ESCAPED。

    这是登记的局限、不是判据正确——2026-09-22 实测全树该形态零真实例（唯一异名
    接收者 smoke 裸 `queue` 已扩词表收编）；将来新队列变量起异名时不许默认本门能挡，
    要么扩段名表（登记式，幽灵行照样红）要么改道 central 出口让旁路本体消失。
    """
    fake = tmp_path / "plugins_pkg"
    (fake / "domains").mkdir(parents=True)
    (fake / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    (fake / "domains" / "altname.py").write_text(
        "class C:\n"
        "    def a(self, req):\n        self.send_q.submit(req)\n"
        "    def b(self, req):\n        self.q.submit(req)\n"
        "    def c(self, req):\n        self._q.submit(req)\n",
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
