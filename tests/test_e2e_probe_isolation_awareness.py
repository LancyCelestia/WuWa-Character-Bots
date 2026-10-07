"""worker 存活探针必须知道"这本库有没有 worker 会去 drain"（10-07 根修）。

背景（取证，不是猜）：`1eda900` 把 `--execute` 的发送队列改指 **OS 临时库**（在线 bot 的
worker 读不到那本库＝不再误真发），这方向是对的；但 `run_help_matrix` 里那枚
**worker 存活探针**仍然用 `wait_for_delivery(send_queue, ...)` 轮询**验收器自己那本队列对象**。
隔离之后没有任何 worker 会去 drain 它 ⇒ 探针**必然超时** ⇒ 旧代码据此打印
「bot 未重启或未启用发送队列」并以 **rc=3 中止整轮**——诊断错了（bot 在线），代价是一次本可
跑完的形状验收被判离线。

⇒ 判据：探针的结论要随**队列落点**分岔。
- 隔离态（label 含 `isolated`）：拿不到投递确认是**设计使然**，不许当"bot 离线"，也不能静默跳过
  （必须打一行"探针在本态不适用"，否则下次又有人以为它验过了）；
- 真发态（`--live-delivery`，label 含 `live-production-queue`）：超时**仍然**是离线，牙必须留着；
- 探针真拿到投递确认（sent/redirected）：照旧继续。
"""

from __future__ import annotations

import pytest

import scripts.e2e_acceptance as e2e


def test_probe_function_exists_on_the_harness() -> None:
    """探针判定必须是**一处可测真身**，不是埋在 3700 行脚本里的一段 if。"""
    assert callable(getattr(e2e, "classify_probe_outcome", None)), (
        "缺 classify_probe_outcome(queue_desc, state)：探针结论无处执法"
    )


@pytest.mark.parametrize(
    "queue_desc, state, expected",
    [
        # 隔离态超时＝设计使然，不中止、但要说清没验
        ("execute:sqlite:isolated:C:/temp/e2e/wuwa_send_queue.sqlite3", "timeout", "not-verified"),
        ("execute:sqlite:isolated:C:/temp/e2e/wuwa_send_queue.sqlite3", "query_error:TypeError", "not-verified"),
        # 真发态超时＝真离线，保留旧牙（rc=3 那一支）
        ("execute:sqlite:live-production-queue:C:/Runtime/data/wuwa.sqlite3", "timeout", "worker-offline"),
        # 拿到确认：两态都算探针通过
        ("execute:sqlite:live-production-queue:C:/Runtime/data/wuwa.sqlite3", "sent", "alive"),
        ("execute:sqlite:isolated:C:/temp/e2e/wuwa_send_queue.sqlite3", "sent", "alive"),
        # DRY-RUN 态压根没有队列可探
        ("dry-run:in-memory", "timeout", "not-applicable"),
    ],
)
def test_probe_verdict_follows_where_the_queue_lives(
    queue_desc: str, state: str, expected: str
) -> None:
    assert e2e.classify_probe_outcome(queue_desc, state) == expected


def test_isolation_is_the_default_so_the_old_abort_is_a_false_diagnosis(tmp_path) -> None:
    """缺省落点＝隔离：把这条钉住，防"顺手把默认改回真发"把本修定成绕过安全阀。

    🔴 按**行为**锁，不按注释锁——文档串改了不该红，落点真改了必须红。
    """
    from plugins.bot_unified_runtime.config import Config

    production = str(tmp_path / "prod-send-queue.sqlite3")
    runtime = e2e.E2eRuntime(
        config=Config(
            bot_runtime_data_dir=str(tmp_path / "runtime-data"),
            bot_send_queue_enabled=True,
            bot_send_queue_db_path=production,
        ),
        runtime_settings=None,
        render_backend=None,
        execute=True,
        city="北京",
        bot_id="",
        sender_id="10000",
        **{"live_delivery": False}
        if "live_delivery" in getattr(e2e.E2eRuntime, "__dataclass_fields__", {})
        else {},
    )
    _queue, label = e2e.choose_send_queue(
        runtime, _audit(), isolation_root=str(tmp_path / "iso")
    )
    assert label.startswith("execute:sqlite:isolated:"), (
        f"缺省落点不再是隔离库⇒本修的『隔离态探针不适用』分支成了死码：{label}"
    )

    import inspect

    src = inspect.getsource(e2e)
    assert "离线中止：发送队列 worker 无响应" in src, "真发态那支中止不许被删（那是牙）"


def test_probe_success_reaches_the_send_loop_not_an_unconditional_abort() -> None:
    """AST 控制流锁：探针判「在线」后必须落到"开始逐条发送"那行。

    执法的形态＝`return 3` 被留在 `if != "alive"` **外面**（缩进差一级）。这种坏法 `ast.parse`
    照样过、ruff/mypy 照样绿，而症状是「真发态即使 worker 在线也整轮 rc=3」——等于把本修
    反着生效。所以按缩进层级判，不按文本判。
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(e2e.run_help_matrix))
    fn = tree.body[0]
    assert isinstance(fn, ast.FunctionDef)

    online = [
        n
        for n in ast.walk(fn)
        if isinstance(n, ast.Expr)
        and isinstance(n.value, ast.Call)
        and "worker 在线" in ast.unparse(n.value)
    ]
    assert len(online) == 1, f"『worker 在线』那条提示应恰好一处，实得 {len(online)}"
    announce = online[0]

    calls = [
        n
        for n in ast.walk(fn)
        if isinstance(n, ast.Call) and "classify_probe_outcome" in ast.unparse(n.func)
    ]
    assert calls, "探针结论没走 classify_probe_outcome＝分岔又退回『超时即离线』那一刀"
    alive_guard = [
        n
        for n in ast.walk(fn)
        if isinstance(n, ast.If) and "alive" in ast.unparse(n.test) and n.body
    ]
    assert alive_guard, "找不到按『是否拿到投递确认』分岔的守卫＝隔离态超时会被当成 bot 离线"
    guard = alive_guard[0]

    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Return)
            and getattr(node.value, "value", None) == 3
            and guard.lineno <= node.lineno < announce.lineno
            and node.col_offset <= guard.col_offset
        ):
            raise AssertionError(
                f"第 {node.lineno} 行有无条件 `return 3`（缩进 {node.col_offset} "
                f"≤ 守卫 {guard.col_offset}）＝探针通过也中止整轮"
            )
    assert announce.col_offset == guard.col_offset, (
        "『worker 在线』提示与分岔守卫不同级＝return 被留在了 if 外面"
    )

    aborted = [
        s
        for s in ast.iter_child_nodes(guard)
        if isinstance(s, ast.Return) and getattr(s.value, "value", None) == 3
    ]
    assert aborted, "真发态超时那一支必须还在（rc=3 是牙，不许被删）"
    leaked = [
        s
        for s in ast.iter_child_nodes(guard)
        if isinstance(s, ast.Expr) and "worker 在线" in ast.unparse(s.value)
    ]
    assert not leaked, "在线提示被塞进失败分支＝探针通过时反而说不出话"


def _audit():
    from plugins.bot_unified_runtime.audit import InMemoryAuditLogger

    return InMemoryAuditLogger()


def test_isolated_state_says_out_loud_that_delivery_was_not_verified() -> None:
    """隔离态那一支必须**出声**：静默跳过＝下一个人以为探针验过了（在册形态「门会缩不会红」）。"""
    import ast
    import inspect

    fn = ast.parse(inspect.getsource(e2e.run_help_matrix)).body[0]
    branch = [
        n
        for n in ast.walk(fn)
        if isinstance(n, ast.If) and "not-verified" in ast.unparse(n.test) and n.body
    ]
    assert branch, "找不到隔离态分支＝本态要么被当离线、要么被静默跳过"
    printed = [s for s in branch[0].body if isinstance(s, ast.Expr) and
               isinstance(s.value, ast.Call) and "print" in ast.unparse(s.value.func)]
    assert printed, "隔离态分支没有一行输出＝探针没跑这件事不可见"
    assert any("不可验" in ast.unparse(s.value) for s in printed), (
        "那一行必须点名『worker 存活本态不可验』，含糊措辞会被读成探针通过"
    )


@pytest.mark.parametrize(
    "verdict, elapsed, must_contain, must_not_contain",
    [
        ("alive", 4.25, "4.2s 确认", "未验"),
        ("not-verified", 0.0, "存活未验", "确认"),
        ("not-applicable", 0.0, "存活未验", "确认"),
        ("probe-blocked", 0.0, "存活未验", "确认"),
        ("worker-offline", 30.0, "未确认", "确认 "),
    ],
)
def test_report_wording_only_says_confirmed_when_it_was(
    verdict: str, elapsed: float, must_contain: str, must_not_contain: str
) -> None:
    """报告措辞真身：只有真拿到投递确认才许出现"确认"，其余态一律明写未验。

    执法的形态＝把 `ws_desc` 改回 `{elapsed:.1f}s 确认` 那种无条件句式——隔离态会印出
    「探针 0.0s 确认」＝把零验证说成秒过（与 §76.20 的哨兵洞同族，方向相反）。
    """
    text = e2e.probe_confirmation_text(verdict, elapsed)
    assert must_contain in text, f"{verdict} 态措辞丢了要点：{text!r}"
    assert must_not_contain not in text, f"{verdict} 态措辞越界（含 {must_not_contain!r}）：{text!r}"


def test_run_report_takes_its_probe_wording_from_the_single_source() -> None:
    """`ws_desc` 那一行必须走 `probe_confirmation_text`——第二处手抄措辞＝第二真身。"""
    import ast
    import inspect

    fn = ast.parse(inspect.getsource(e2e.run_help_matrix)).body[0]
    kw = [
        node.value
        for node in ast.walk(fn)
        if isinstance(node, ast.keyword)
        and node.arg == "ws_desc"
        and isinstance(node.value, (ast.JoinedStr, ast.BinOp))
    ]
    assert kw, "找不到报告行的 ws_desc"
    wired = [n for n in kw if "probe_confirmation_text" in ast.unparse(n)]
    assert wired, f"报告行没走措辞真身（手抄文案必漂）：{[ast.unparse(n)[:60] for n in kw]}"
