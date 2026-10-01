"""错误/失败话术池的变体下限与泄漏面机器门（席 E1，2026-10-02）。

一句话：**每池 ≥15 变体**从散文升成机器计数；**异常原文**不许进用户可见句；
**第五套选池 API** 不许出现。三件事防的都是「下一个人偷懒或手滑」。

三处真身（本门全部**现读模块属性**，不做 import 期快照——注毒必须被看见，
纪律同 `tests/test_persona_imagery_whitelist.py`）：
- `domains/core/contracts/errors.py`：`ERROR_COPY_POOLS`（失败族壳）+
  `ERROR_COPY_FAMILY`（41 枚码 → 族）。`ErrorSpec.message_template` 是族壳里
  `{detail}` 槽的取材，逐字不动——它是错误目录规范句，也是
  `tests/test_copy_single_source.py` 在册重复簇的 home。
- `domains/chat_reply/capabilities/user_copy.py`：四枚 `*_TEMPLATES` 池。
- `domains/ops/monitor/error_report.py`：`_HUMAN_TEXTS`（人话区）、
  `_COOLDOWN_LINES`（冷却降级句）。

判据分层（红在哪层，报错文案就点名哪层）：
① 计数：在册池必须 `MIN_VARIANTS ≤ 条数 ≤ MAX_VARIANTS`。
② 棘轮：面外（别席独占文件）存量池按**现算录地板**，只准升不准降；涨了没
   重录也算红（防「悄悄养回旧数」）；未登记的新池不足即红。
③ 槽位：在册池的 `{占位符}` 只许 `reason/action/exc/detail`。异常**原文**槽
   （`err`/`error`/`message`/`tb`/`traceback`/`stack`/`path`…）出现即红——
   这条就是「把异常名直发用户」那类腿的机械拦截。`{exc}` 只装**类型名**，
   属 W9 分级门在册的对外保留面（见 `error_report.py` 模块头「留：…异常类型名…」）。
④ 出口形态：全树 `DATASOURCE_FAILURE_TEMPLATES).format(reason=…)` 的实参必须
   是字面量，或只插值在册变量（`status`）；插运行时对象即红。
⑤ 取句原身名册：既有那几套（台账 #41/#42 的在册债）之外的轮换取句函数＝
   第五套，直接红；另锁「投影面只走 `render_error_message`」，不留第二通路。

双向自测：①③ 配注毒腿 + 反向不误伤腿；②④⑤ 各配「空集合/空名册不得恒真」
的防空转腿。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.capabilities import user_copy
from plugins.bot_unified_runtime.domains.core.contracts import errors as errors_mod
from plugins.bot_unified_runtime.domains.ops.monitor import error_report

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PKG = REPO_ROOT / "plugins" / "bot_unified_runtime"

# ---------------------------------------------------------------- 判据常量

#: 每池变体下限（席面要求 15–20：下限是硬门，上限防「灌水凑数」）。
MIN_VARIANTS = 15
MAX_VARIANTS = 20

#: 在册池允许的插值槽。`exc` 只装异常**类型名**（`type(exc).__name__`），
#: `detail` 只装错误目录规范句，`reason`/`action` 是调用方给的短语。
ALLOWED_SLOTS: frozenset[str] = frozenset({"reason", "action", "exc", "detail"})

#: 出现即红的槽名 token——这类形态会把异常原文/栈/路径拽进用户可见句。
#: 只判「整槽名等于 token」或「token 是槽名」，不判子串（否则 `{exc}` 这类
#: 在册槽会被 `{action}` 之类误伤）。
BANNED_SLOT_TOKENS: frozenset[str] = frozenset(
    {
        "err",
        "error",
        "exc_msg",
        "exc_message",
        "exc_text",
        "message",
        "msg",
        "tb",
        "traceback",
        "stack",
        "paths",
        "raw",
        "detail_text",
        "exception",
    }
)

#: 结构形态靶子（与 W9 分级门 `_PUBLIC_FORBIDDEN_MARKERS` 同族，另加栈帧形态）：
#: 错误人话里出现这些＝内部结构上屏。
FORBIDDEN_STRUCTURAL_TOKENS: tuple[str, ...] = (
    ".py:",
    "BOT_",
    "bot_",
    "C:\\",
    "C:/",
    "/home/",
    "/app/",
)

#: 面外存量池的地板（**只准升不准降**；涨到 15 就该从本表摘掉）。
#: 这些文件属别席独占面（`chat.py`/`echo.py` 本波明令禁碰；`daily_assist.py`
#: 属日常助理文案面；`progress_ack.py` 有意保持短池），本席只录数、不改动。
#: 数字来源：2026-10-02 本席 AST 现算扫描，逐条 file::NAME。
DEFICIT_FLOOR: dict[str, int] = {
    "plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py::_PERSONA_FAILURE_MESSAGES": 12,
    "plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py::_INJECTION_GUARD_TEMPLATES": 12,
    "plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py::_KB_GROUNDED_FALLBACK_LEADS": 5,
    "plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py::_DANGER_COMFORT_EXAMPLES": 10,
    "plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py::_IGNORE_GUIDE_LINES": 3,
    "plugins/bot_unified_runtime/domains/assistant/daily/store/daily_assist.py::_MORNING_EMPTY_OPENERS": 6,
    "plugins/bot_unified_runtime/domains/assistant/daily/store/daily_assist.py::_MORNING_OPENERS": 6,
    "plugins/bot_unified_runtime/domains/assistant/daily/store/daily_assist.py::_MORNING_IDEA_NOTES": 6,
    "plugins/bot_unified_runtime/domains/assistant/daily/store/daily_assist.py::_EVENING_OPENERS": 7,
    "plugins/bot_unified_runtime/domains/assistant/daily/store/daily_assist.py::_EVENING_INBOX_EMPTY_LINES": 6,
    "plugins/bot_unified_runtime/domains/assistant/daily/store/daily_assist.py::_EVENING_INBOX_COUNTED_LINES": 6,
    "plugins/bot_unified_runtime/domains/assistant/daily/store/daily_assist.py::_EVENING_IDEA_NUDGES": 6,
}

#: 错误文案三处真身里**允许存在**的取句/渲染入口（既有形态的名单）。
#: 判据⑤盯的是「本席没起第五套、后人也不许在错误面上起」：任何模块级新函数
#: 只要名字像取句器（`pick_*`/`*_pick_*`/`choose_*`/`rotate_*`）或在函数体里
#: 对池做 `% len(...)` 取模轮换，就必须在这张名单里。
#: 名单本体＝2026-10-02 现算扫描，逐条 file::func（既有四套的出处与选择理由见
#: `patches/E1-ERROR-COPY-POOLS-20261002.md` ②段，全仓取句机制盘点在同段）。
PICKER_ALLOWLIST: frozenset[str] = frozenset(
    {
        # 族壳轮换取句的唯一出口（内部只调既有 `random.choice`，非新机制）
        "domains/core/contracts/errors.py::render_error_message",
        "domains/core/contracts/errors.py::_render_message",
        # 会话游标（既有原身，本席只扩池没改机制）
        "domains/ops/monitor/error_report.py::_persona_text",
        "domains/ops/monitor/error_report.py::cooldown_line",
    }
)

#: 判据④：`reason=` 实参里允许插值的变量名（不是异常，是中央调度回的状态串）。
REASON_INTERP_ALLOWLIST: frozenset[str] = frozenset({"status"})

# 守岸人语气底线（AGENTS 规则 8 + 内容政策）。与 `test_copy_redline_gate` 互不
# 替代：那件扫全树文案形态，本件只扫**错误面池**的指责句式与短句。
BLAME_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<!不)是你的问题"),
    re.compile(r"(?<!不)怪你"),
    re.compile(r"你怎么"),
    re.compile(r"你自己"),
    re.compile(r"早就说过"),
)
MACHINE_TONE_TOKENS: tuple[str, ...] = (
    "作为一个",
    "为您",
    "给您带来不便",
    "深表歉意",
)

# ---------------------------------------------------------------- 在册池读取

_SLOT_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _live_pools() -> dict[str, tuple[str, ...]]:
    """现读三处真身的在册池（族壳按族逐条登记，键名带定位信息）。"""
    pools: dict[str, tuple[str, ...]] = {
        "user_copy.ADMIN_GATE_TEMPLATES": tuple(user_copy.ADMIN_GATE_TEMPLATES),
        "user_copy.DATASOURCE_FAILURE_TEMPLATES": tuple(
            user_copy.DATASOURCE_FAILURE_TEMPLATES
        ),
        "user_copy.GROUP_FAILURE_ACK_TEMPLATES": tuple(
            user_copy.GROUP_FAILURE_ACK_TEMPLATES
        ),
        "user_copy.PIPELINE_BUSY_PRIVATE_ACK_TEMPLATES": tuple(
            user_copy.PIPELINE_BUSY_PRIVATE_ACK_TEMPLATES
        ),
        "error_report._HUMAN_TEXTS": tuple(error_report._HUMAN_TEXTS),
        "error_report._COOLDOWN_LINES": tuple(error_report._COOLDOWN_LINES),
    }
    for family, variants in errors_mod.ERROR_COPY_POOLS.items():
        pools[f"ERROR_COPY_POOLS[{family}]"] = tuple(variants)
    return pools


def _slots_of(text: str) -> set[str]:
    return set(_SLOT_RE.findall(text))


def _bare_length(text: str) -> int:
    """剥掉槽位与标点后的正文字数（判「长句不短句」用）。"""
    body = _SLOT_RE.sub("", text)
    return len(re.sub(r"[，。！？；：、…「」『』（）()～〜\s,.!?;:]", "", body))


def _size_offenders(pools: dict[str, tuple[str, ...]]) -> dict[str, int]:
    return {
        name: len(variants)
        for name, variants in pools.items()
        if not MIN_VARIANTS <= len(variants) <= MAX_VARIANTS
    }


def _slot_offenders(pools: dict[str, tuple[str, ...]]) -> list[str]:
    """槽位越界 = 出现 ALLOWED 之外的槽，或槽名命中「异常原文」token。"""
    offenders: list[str] = []
    for name, variants in pools.items():
        for text in variants:
            for slot in sorted(_slots_of(text)):
                if slot in ALLOWED_SLOTS:
                    continue
                offenders.append(f"{name}: 非法槽 {{{slot}}} ← {text[:28]}")
    return offenders


# ---------------------------------------------------------------- 判据①：计数


def test_every_registered_error_copy_pool_meets_the_variant_floor() -> None:
    pools = _live_pools()
    assert pools, "在册池一个都没读到——本门在空转（判据①）"
    # 族壳必须还在（空 dict 会让键集只剩四池，计数门就悄悄少了一半面）。
    assert len(errors_mod.ERROR_COPY_POOLS) >= 8, "失败族壳塌了（判据①）"
    offenders = _size_offenders(pools)
    assert not offenders, (
        f"每池 ≥{MIN_VARIANTS} 变体的下限被破（判据①，越界者=条数）：{offenders}"
    )


def test_pool_floor_gate_has_teeth_on_poisoned_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """注毒腿：在册池削到 14 条必须红；补回 15 条必须绿（不碰真文件）。"""
    poisoned = tuple(user_copy.DATASOURCE_FAILURE_TEMPLATES)[:14]
    assert len(poisoned) == MIN_VARIANTS - 1, "夹具自身不合格，注毒不算证据"
    monkeypatch.setattr(user_copy, "DATASOURCE_FAILURE_TEMPLATES", poisoned, raising=True)
    offenders = _size_offenders(_live_pools())
    assert offenders.get("user_copy.DATASOURCE_FAILURE_TEMPLATES") == 14, (
        "削池未被抓红＝判据①是空转门"
    )
    monkeypatch.setattr(
        user_copy,
        "DATASOURCE_FAILURE_TEMPLATES",
        poisoned + ("{reason}，我在原处接着。",),
        raising=True,
    )
    assert "user_copy.DATASOURCE_FAILURE_TEMPLATES" not in _size_offenders(_live_pools())


def test_family_shells_cover_every_registered_error_code() -> None:
    codes = set(errors_mod.iter_error_codes())
    assert codes, "错误注册表为空（判据①）"
    mapped = set(errors_mod.ERROR_COPY_FAMILY)
    assert codes == mapped, (
        "错误码与失败族名册不是一对一（判据①）："
        f"未入族={sorted(codes - mapped)}，族册里的幽灵码={sorted(mapped - codes)}"
    )
    dangling = sorted(
        family
        for family in errors_mod.ERROR_COPY_FAMILY.values()
        if family not in errors_mod.ERROR_COPY_POOLS
    )
    assert not dangling, f"码指向未注册的族（判据①）：{dangling}"


def test_rendered_message_rotates_within_the_family_shell() -> None:
    """正面行为锁：同一枚码连着取句拿到多种说法，且每条都保住码级语义。"""
    detail = errors_mod.ERROR_REGISTRY["rate_limited"].message_template
    seen = {errors_mod.error_body("rate_limited")["message"] for _ in range(400)}
    assert len(seen) >= MIN_VARIANTS, (
        f"rate_limited 取句 400 次只得 {len(seen)} 种说法——池没在轮换（判据①）"
    )
    assert all(detail in text for text in seen), "换壳把码级语义吃掉了（判据①）"


def test_registry_canonical_sentence_is_untouched() -> None:
    """规范句逐字不动：它是族壳 `{detail}` 的取材，也是文案单一真身门的在册锚。"""
    assert (
        errors_mod.ERROR_REGISTRY["permission_denied"].message_template
        == "这件事超出了你现在的权限，先到这里为止了。"
    )
    assert (
        errors_mod.ERROR_REGISTRY["unauthenticated"].message_template
        == "我还认不出你是谁，请先完成登录再来找我吧。"
    )


# ---------------------------------------------------------------- 判据②：棘轮


def _module_pool_sizes(path: Path) -> dict[str, int]:
    """AST 现算：模块级「≥2 条中文字面量」的元组/列表条数。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    sizes: dict[str, int] = {}
    for node in tree.body:
        names: list[str] = []
        value: ast.expr | None = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names, value = [node.target.id], node.value
        elif isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            value = node.value
        if not names or not isinstance(value, (ast.Tuple, ast.List)):
            continue
        elements = list(value.elts)
        if len(elements) < 2:
            continue
        if not all(
            isinstance(e, ast.Constant) and isinstance(e.value, str) for e in elements
        ):
            continue
        if not any(re.search(r"[\u4e00-\u9fff]", str(e.value)) for e in elements):
            continue
        sizes[names[0]] = len(elements)
    return sizes


def _deficit_readings() -> tuple[list[str], list[str], dict[str, int]]:
    worse: list[str] = []
    unrecorded: list[str] = []
    current: dict[str, int] = {}
    for key, floor in DEFICIT_FLOOR.items():
        rel_file, _, name = key.rpartition("::")
        path = RUNTIME_PKG / rel_file.removeprefix("plugins/bot_unified_runtime/")
        size = _module_pool_sizes(path).get(name)
        assert size is not None, f"棘轮在册的池找不到了（判据②）：{key}"
        current[key] = size
        if size < floor:
            worse.append(f"{key} 现={size} 地板={floor}")
        elif floor < size < MIN_VARIANTS:
            unrecorded.append(f"{key} 现={size} 地板={floor}（请上调地板到现值）")
        elif size >= MIN_VARIANTS:
            unrecorded.append(f"{key} 现={size} 已达下限，应从 DEFICIT_FLOOR 摘掉")
    return worse, unrecorded, current


def test_out_of_scope_copy_pool_sizes_only_ratchet_up() -> None:
    worse, unrecorded, current = _deficit_readings()
    assert current, "棘轮名册是空的（判据②，空集合不得恒真）"
    assert not worse, "面外存量池又变薄了（判据②，只降不升）：" + "；".join(worse)
    assert not unrecorded, "棘轮读数没随现值重录（判据②）：" + "；".join(unrecorded)


def test_new_deficient_pool_outside_the_roster_is_red() -> None:
    """判据②注毒腿（合成，不碰真文件）：未登记的新池不足 15 必被抓。"""
    synthetic = {"brand_new_pool": 7, "already_ok": MIN_VARIANTS}
    unregistered = sorted(n for n, s in synthetic.items() if s < MIN_VARIANTS)
    assert unregistered == ["brand_new_pool"], "未在册的不足池没被抓出来＝棘轮空转"
    assert "already_ok" not in unregistered, "够数的池被误算成欠账＝门会乱咬"


# ---------------------------------------------------------------- 判据③④⑤


def test_no_pool_interpolates_raw_exception_text() -> None:
    offenders = _slot_offenders(_live_pools())
    assert not offenders, (
        "用户可见话术里出现了异常原文/栈/路径类插值槽（判据③）：" + "；".join(offenders)
    )


def test_slot_gate_has_teeth_on_poisoned_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """注毒腿：往池里塞一条带 `{err}`（异常原文）的句子，判据③必须抓红。"""
    poison = "{reason}，源头报了 {err}，我照着它回你。"
    original = tuple(user_copy.DATASOURCE_FAILURE_TEMPLATES)
    monkeypatch.setattr(
        user_copy,
        "DATASOURCE_FAILURE_TEMPLATES",
        original + (poison,),
        raising=True,
    )
    offenders = _slot_offenders(_live_pools())
    assert any("DATASOURCE" in line and "{err}" in line for line in offenders), (
        f"异常原文槽未被抓红＝判据③空转：{offenders}"
    )
    # 反向不误伤腿：在册槽（reason/action/exc/detail）一条都不算泄漏。
    monkeypatch.setattr(user_copy, "DATASOURCE_FAILURE_TEMPLATES", original, raising=True)
    assert not _slot_offenders(_live_pools()), "干净池也被判红＝判据③在误伤"


@pytest.mark.parametrize(
    ("sample", "expected_red"),
    [
        ("{reason}，源头报了 {err}。", True),
        ("{exc} 的栈是 {traceback}。", True),
        ("处理到一半卡住了（{exc}）。诊断都在卡上。", False),
        ("{reason}，我在原处接着。", False),
        ("这一步要 {action}，请管理员来。", False),
        ("壳里只装 {detail}。", False),
    ],
)
def test_slot_rule_judges_leak_and_non_leak_correctly(
    sample: str, expected_red: bool
) -> None:
    """判据③的双向自测：泄漏形态必红、在册槽必不误伤。"""
    offenders = _slot_offenders({"probe": (sample,)})
    assert bool(offenders) is expected_red, f"判定错位：{sample!r} → {offenders}"


def test_family_shell_carries_exactly_one_detail_slot() -> None:
    for family, variants in errors_mod.ERROR_COPY_POOLS.items():
        assert variants, f"族壳为空（判据③）：{family}"
        assert variants[0] == "{detail}", f"族壳首条必须是裸规范句锚（判据③）：{family}"
        for text in variants:
            assert text.count("{detail}") == 1, f"{family} 的壳不止一处 detail：{text}"
            assert _slots_of(text) == {"detail"}, f"{family} 的壳夹带了别的槽：{text}"


def _datasource_reason_findings() -> tuple[int, list[str]]:
    """全树扫 `DATASOURCE_FAILURE_TEMPLATES).format(reason=…)` 的实参形态。"""
    offenders: list[str] = []
    calls = 0
    for path in RUNTIME_PKG.rglob("*.py"):
        if "__pycache__" in str(path) or path.name == "user_copy.py":
            continue
        source = path.read_text(encoding="utf-8")
        if "DATASOURCE_FAILURE_TEMPLATES" not in source:
            continue
        tree = ast.parse(source)
        rel = path.relative_to(REPO_ROOT).as_posix()
        for node in ast.walk(tree):
            if (
                not isinstance(node, ast.Call)
                or not isinstance(node.func, ast.Attribute)
                or node.func.attr != "format"
            ):
                continue
            if "DATASOURCE_FAILURE_TEMPLATES" not in ast.unparse(node.func.value):
                continue
            calls += 1
            for keyword in node.keywords or []:
                if keyword.arg != "reason":
                    continue
                value = keyword.value
                if isinstance(value, ast.Constant):
                    continue
                if isinstance(value, ast.JoinedStr):
                    leaked = sorted(
                        name.id
                        for part in value.values
                        if isinstance(part, ast.FormattedValue)
                        for name in ast.walk(part)
                        if isinstance(name, ast.Name)
                        and name.id not in REASON_INTERP_ALLOWLIST
                    )
                    if leaked:
                        offenders.append(f"{rel}:{node.lineno} reason 插值了 {leaked}")
                    continue
                offenders.append(
                    f"{rel}:{node.lineno} reason 非字面量：{ast.unparse(value)[:40]}"
                )
    return calls, offenders


def test_datasource_reason_argument_is_a_literal_not_a_runtime_object() -> None:
    calls, offenders = _datasource_reason_findings()
    assert calls >= 10, f"只扫到 {calls} 处池调用——扫描面塌了（判据④）"
    assert not offenders, "数据源失败句把运行时对象直发用户（判据④）：" + "；".join(offenders)


def test_projection_uses_the_single_family_shell_outlet() -> None:
    """判据⑤：REST 投影只准走 `render_error_message`，代码里不许直读规范句。

    认的是 **AST 属性访问**（`spec.message_template` 这种取法），不是文件正文的
    字符串——注释/文档里提到这个名字是必要的说明，不该被抓红。
    """
    path = RUNTIME_PKG / "domains/divination/api/errors.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    direct_reads = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr == "message_template"
    ]
    assert not direct_reads, (
        f"占卜投影直读了注册表规范句（判据⑤，第二通路）：行 {direct_reads}"
    )
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "render_error_message" in imported, (
        "占卜投影没走族壳出口（判据⑤）：仍是单句第二通路"
    )


#: 判据⑤的扫描面：错误文案三处真身（相对 RUNTIME_PKG）。
TRUTH_SOURCE_FILES: tuple[str, ...] = (
    "domains/core/contracts/errors.py",
    "domains/chat_reply/capabilities/user_copy.py",
    "domains/ops/monitor/error_report.py",
)

_PICKER_NAME_RE = re.compile(r"^(pick_|choose_|rotate_)|(_pick_|_choose_)")


def _picker_functions(path: Path, rel: str) -> set[str]:
    """一个文件里「像在取句」的模块级函数：名字像取句器，**或**函数体里对池取模。

    命中条件（宽松侧留给人审，网眼如实登记）：函数体里出现
    ``% len(...)``/``% count`` 取模，或 ``random.randrange``/``random.choice``
    取句，且函数名/体里带池引用。已知网眼（偏松）：不带取模也不带 random 的
    新机制（例如自己造哈希环）抓不到——那类属人审面，本门只钉「再抄一套
    游标/随机」这个最可能发生形态。

    `rel` 由调用方给：真面传 RUNTIME_PKG 相对路径，注毒腿传同一串假相对路径，
    这样合成件与真面吃**同一把尺**（比对的是名单，不是文件系统位置）。
    """
    found: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        dumped = ast.dump(node)
        by_name = bool(_PICKER_NAME_RE.search(node.name))
        by_modulo = "Mod" in dumped and "Call(func=Name(id='len'" in dumped
        if by_name or by_modulo:
            found.add(f"{rel}::{node.name}")
    return found


def _real_picker_findings() -> set[str]:
    """真面（错误文案三处真身）的取句形态命中集。"""
    found: set[str] = set()
    for rel in TRUTH_SOURCE_FILES:
        found |= _picker_functions(RUNTIME_PKG / rel, rel)
    return found


def test_no_fifth_pick_variant_api_on_the_error_face() -> None:
    """判据⑤：错误文案面上只准用既有取句形态，新增一个 picker 就红。

    本席的选择：`errors.py` 族壳走 `random.choice`（既有四套里那套随机，
    且 `errors.py` 有「只依赖标准库」的契约，键控游标那份请不进来）；
    `error_report.py` 的人话区继续吃它自己的会话游标 `_persona_text`；
    `user_copy.py` 的 20 余处消费点表达式一字未动。**零新增选池机制**。
    """
    found = _real_picker_findings()
    assert found, "错误面上一个取句形态都没扫到＝判据⑤在空转"
    extra = sorted(found - PICKER_ALLOWLIST)
    assert not extra, (
        f"错误文案面上出现了名单之外的取句函数（判据⑤，第五套）：{extra}；"
        "既有几套的出处与选择理由见 outbound-template-unification-spec.md §一.2"
    )
    # 空名单不得恒真：比对集清空时，在册的形态必须条条被抓出来。
    assert sorted(found - frozenset()) == sorted(found)


def test_picker_gate_has_teeth_on_a_synthetic_fifth_api(tmp_path: Path) -> None:
    """注毒腿（合成件写进 tmp_path，绝不落进工作树）：新起一套取模选句必红。

    与正向吃**同一把尺**：同一个 `_picker_functions`，同一串相对路径，
    只是文件在 temp 里。真面上的在册形态必须零「名单外」。
    """
    poison_file = tmp_path / "errors_poison.py"
    poison_file.write_text(
        "POOL = ('甲', '乙')\n"
        "_CURSOR = 0\n\n\n"
        "def pick_error_line():\n"
        "    global _CURSOR\n"
        "    line = POOL[_CURSOR % len(POOL)]\n"
        "    _CURSOR += 1\n"
        "    return line\n",
        encoding="utf-8",
    )
    found = _picker_functions(poison_file, "domains/core/contracts/errors.py")
    assert found == {"domains/core/contracts/errors.py::pick_error_line"}, (
        f"合成第五套没被扫出来＝尺子失灵：{found}"
    )
    assert sorted(found - PICKER_ALLOWLIST) == sorted(found), (
        "合成第五套没被抓出来＝判据⑤是摆设"
    )
    # 反向不误伤腿：真面上的在册形态一条都不该出现在「名单外」里。
    assert not sorted(_real_picker_findings() - PICKER_ALLOWLIST)


# ---------------------------------------------------------------- 语气与结构面


#: 「长句不短句」按**渲染后**的观感判：槽位用真实取值填满再数。
#: （拿模板裸串数长度会误伤 `{reason}，稍后再试。` 这类历史锚——
#: 用户看到的整句其实是「汇率数据暂时拉不到，稍后再试。」，够长。）
_SLOT_FILLERS: dict[str, str] = {
    "reason": "汇率数据暂时拉不到",
    "action": "看运行时排障记录",
    "exc": "ValueError",
    "detail": "这件事超出了你现在的权限，先到这里为止了。",
}
MIN_RENDERED_LENGTH = 12


def _rendered_probe(text: str) -> str:
    filled = text
    for slot, filler in _SLOT_FILLERS.items():
        filled = filled.replace("{" + slot + "}", filler)
    return filled


def test_error_copy_tone_bottom_line() -> None:
    for name, variants in _live_pools().items():
        for text in variants:
            stripped = text.strip()
            assert not stripped.endswith(("～", "〜")), f"{name} 拖尾语气符：{stripped}"
            for token in MACHINE_TONE_TOKENS:
                assert token not in text, f"{name} 机器腔 {token!r}：{text[:24]}"
            for pattern in BLAME_PATTERNS:
                assert not pattern.search(text), f"{name} 指责提问者：{text[:24]}"
            # 长句不短句（AGENTS 规则 8）：按填满槽位后的整句数正文字数。
            rendered = _rendered_probe(text)
            assert _bare_length(rendered) >= MIN_RENDERED_LENGTH, (
                f"{name} 短句破音（渲染后 {_bare_length(rendered)} 字）：{rendered[:28]}"
            )


def test_error_registry_message_carries_no_structural_token() -> None:
    """错误人话里不许出现内部结构形态（键名/盘符/栈帧），逐码现算。"""
    for code in errors_mod.iter_error_codes():
        text = errors_mod.error_body(code)["message"]
        hit = [token for token in FORBIDDEN_STRUCTURAL_TOKENS if token in text]
        assert not hit, f"{code} 的错误人话带了内部结构形态 {hit}（判据③）"


def test_cooldown_lines_still_point_at_the_card() -> None:
    """扩容不许吃掉既有语义红线：每句冷却话都指回「刚才那张卡」，都带类型名槽。"""
    for text in error_report._COOLDOWN_LINES:
        assert "卡" in text, f"冷却句没了指向：{text[:24]}"
        assert "{exc}" in text, f"冷却句丢了读数：{text[:24]}"
    for text in error_report._HUMAN_TEXTS:
        assert "{exc}" in text, f"人话区丢了类型名读数：{text[:24]}"


def test_exception_raw_text_never_reaches_the_human_line() -> None:
    """行为锁：卡面上的人话区只会出现异常**类型名**，绝不出现异常原文/路径/键名。

    W9 分级门在册口径「对外档留：人话区、触发回显、异常类型名、能力名、中文归类」
    ——本锁钉的就是这条边界没被扩容冲掉。
    """
    message = SimpleNamespace(
        request_id="r-e1",
        session_id="s-e1",
        session_type="group",
        group_id="20002",
        sender_id="10001",
        bot_id="",
        message_id="m-e1",
        platform="qq",
        adapter="onebot",
        plain_text="/bot market",
        timestamp=None,
        debug_id="",
        sender_roles=(),
    )

    def boom() -> None:
        raise RuntimeError("connect failed for C:/secret/dir BOT_SUPER_ADMIN_USER_IDS")

    try:
        boom()
    except RuntimeError as exc:
        report = error_report.build_error_report(message, "bot.market", exc)
    human = str(report["human_text"])
    assert "RuntimeError" in human, "人话区按 W9 保留类型名，没保留＝口径漂移了"
    for token in ("C:/secret", "BOT_SUPER_ADMIN_USER_IDS", "connect failed for"):
        assert token not in human, f"异常原文进了用户可见句（判据③）：{token}"
    assert report["exc_message"] == "", "对外档还带着异常原文（W9 分级门失效）"
