"""Wave 1 常驻门（另一半盲区）：**被注入 provider 的消费点必须登记在册**（S-PROV 席）。

v1 门 ``test_orchestration_callsite_single.py`` 管「**谁造真身**」（直呼 ``build_web_search_provider``
/ ``read_supported_file`` …）。它按符号名扫，看不到「谁把造好的 provider 对象拿去**执行**」——
S-W1B 已实证：``backend_unit.py:91`` 整枚 provider 泼进 dict 注入给 chat，真正 ``.search()``
的是 ``chat.py``。同一类病也出现在根泛型工厂（能力被谁执行 ≠ 谁调了造真身的函数）。

本门即那另一半：凡「接收 ``*provider`` 型注入并**调用其方法**」的地点都要登记，且登记表
**最终目标是清空**（消费点迁进 invoker 后归零），不是永久白名单。

三层执法（与 v1 同哲学，判据**只 import 复用不复制第二套**）：
- **双向活性判据**：真树扫到的消费点 ⇔ 登记 ledger，两向缺一即红（新未登记红 / 登记已失效红）。
- **棘轮**：``to_be_wired`` 总数只准降不准升——把「清零是终点」写进执法，防清单被偷偷养肥。
- **注毒自证**：合成树逐条证明每条不变量真的会红，且点名红在**哪条不变量**（不认「抛异常即过」）。

全离线、零副作用：只读源码 AST，不 import 业务包、不发网络、不发消息。方法名集合**从真身
provider 类 AST 派生**（不手抄），真身源文件缺失/派生空 → 当场红（防「门变哑」式假绿）。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

# 同目录顶层导入：pytest 默认 prepend 模式把 tests/ 放上 sys.path（先例见 wave_media 席）。
# 复用 v1 门的路径/包根常量，禁在本件复制第二份判据（§7 禁第三套真身）。
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_orchestration_callsite_single as _v1gate  # 复用 v1 门常量（同目录顶层导入）

_PKG_ROOT = _v1gate._PKG_ROOT  # …/plugins/bot_unified_runtime
_SHELL_REL = _v1gate._SHELL_REL  # 受控适配器 handler：provider 消费 = 正解，不算旁路
_REL = _v1gate._rel


# ---------------------------------------------------------------------------
# provider 真身源文件（=消费方法词的派生处）。取「消费方面对的 provider 表面」——
# 即 build_*_provider 返回、被调用方拿去执行的那批类（web_search.py 的 Provider 族），
# **不含** TavilyWebSearchProvider 这类「链后端的引擎实现」（search_api.py）：它们的私有方法
# （如 image_urls）不是本能力的对位成员，纳入只会把「自建自用的引擎实例」误记成消费旁路。
# ---------------------------------------------------------------------------
_PROVIDER_SOURCES: dict[str, tuple[str, ...]] = {
    "search.web": ("domains/core/search/web_search.py",),
    "media.vision": ("domains/media/ingest/vision_describe.py",),
    "media.asr": ("domains/media/ingest/transcribe.py",),
}

# 通用 housekeeping 名：任何对象都可能有，进词表必误伤全树，从派生结果剔除。
_HOUSEKEEPING = frozenset({"close", "name", "is_enabled", "get", "set", "reset"})


def _provider_public_methods(tree: ast.AST) -> set[str]:
    """某 module 内 ``*Provider`` 类的公开实例方法名并集（不含 dunder/_ 前缀/housekeeping）。"""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name.endswith("Provider"):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and not sub.name.startswith("_"):
                    found.add(sub.name)
    return found - _HOUSEKEEPING


def derive_family_vocab(index: dict[str, str]) -> dict[str, set[str]]:
    """族 → 该族 provider 的方法词表（从真身类派生；真身缺失或词表为空即抛，防门变哑）。"""
    vocab: dict[str, set[str]] = {}
    for family, sources in _PROVIDER_SOURCES.items():
        acc: set[str] = set()
        for rel in sources:
            src = index.get(rel)
            if src is None:  # 真身坐标漂走：宁可当场炸，也不要静默把该族变瞎
                raise AssertionError(f"provider 真身源缺失，该族消费扫描将失明：{family} -> {rel}")
            acc |= _provider_public_methods(ast.parse(src))
        if not acc:
            raise AssertionError(f"provider 方法词表派生为空（真身类改名/结构漂走？）：{family}")
        vocab[family] = acc
    return vocab


# ---------------------------------------------------------------------------
# 接收者判据：消费点 = 对「provider 型变量」调用 provider 方法。方法名有歧义（``search``
# 也见于正则、``generate`` 见于 LLM），故必须叠加接收者 token 消歧——判据宁可严不可宽，
# 但也绝不因一个通用方法名把无关调用误记成消费（那会把 ledger 灌成噪声、反而糊住真旁路）。
# ---------------------------------------------------------------------------
def _receiver_leaf(node: ast.AST) -> str:
    """取接收者表达式的尾名：``a.b.c`` → ``c``；``x`` → ``x``；其它复杂表达式给空串不匹配。"""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _receiver_matches(family: str, leaf: str) -> bool:
    low = leaf.lower()
    if family == "search.web":
        # web provider 变量：裸 ``provider``（helper 形参）或含 web 的 *provider（active_web_provider…）；
        # 明确排除 meme 的 ``active_search``/``search_provider``、llm/vision/asr 的 ``*_provider``。
        return low == "provider" or ("web" in low and "provider" in low)
    if family == "media.vision":
        return "vision" in low and "provider" in low
    if family == "media.asr":
        return "asr" in low and "provider" in low
    return False


def _consumption_pairs(index: dict[str, str], vocab: dict[str, set[str]]) -> set[tuple[str, str, int]]:
    """扫出 (族, 相对文件, 行号) 消费点。豁免真身/壳：provider 实现自己组合子 provider、
    壳 handler 是 wired 正解，均非「注入 provider 在别处被执行」的旁路。"""
    # 豁免集（三哲学，全部 **import 复用** v1 的登记表，不复制第二份）：
    #  ① 壳 handler：受控适配器内 provider 消费 = wired 正解（_SHELL_REL）。
    #  ② 能力真身自己 module 内组合：provider 被该能力的实现消费 = 实现细节，非第二执行入口
    #     —— 与 v1 ``_DEF_FILES``「真身在自己 module 内组合不算直呼」同一把尺子（如
    #     video_understanding.py 用注入的 vision/asr provider 实现 build_video_brief）。
    #  ③ search_smoke：本文件自造自持 provider 做只读连通性自检，非注入旁路（若日后被注入
    #     需撤下）。provider 真身源文件本身 ⊆ _DEF_FILES，不重复列。
    exempt = {_SHELL_REL, "domains/core/search/search_smoke.py"}
    for files in _v1gate._DEF_FILES.values():
        exempt.update(files)

    pairs: set[tuple[str, str, int]] = set()
    for rel, src in index.items():
        if rel in exempt:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            # 形态 A：``recv.method(...)``
            if isinstance(fn, ast.Attribute) and isinstance(fn.value, (ast.Name, ast.Attribute)):
                leaf = _receiver_leaf(fn.value)
                for family, methods in vocab.items():
                    if fn.attr in methods and _receiver_matches(family, leaf):
                        pairs.add((family, rel, node.lineno))
            # 形态 B：``getattr(recv, "method", ...)``（chat.py 的 fetch_page_text 走这条，
            # 普通 ``.fetch_page_text(`` AST 看不见——不补这臂，最硬的那个消费点会漏检）。
            if isinstance(fn, ast.Name) and fn.id == "getattr" and len(node.args) >= 2:
                recv, meth = node.args[0], node.args[1]
                if isinstance(meth, ast.Constant) and isinstance(meth.value, str):
                    leaf = _receiver_leaf(recv)
                    for family, methods in vocab.items():
                        if meth.value in methods and _receiver_matches(family, leaf):
                            pairs.add((family, rel, node.lineno))
    return pairs


def _load_consumption_index() -> dict[str, str]:
    """预筛：只载入含 ``provider`` 的源文件（消费点接收者必含 provider 子串，故完备）+
    provider 真身文件（derive 需要，它们自身也含 provider 但被豁免，仍要进 index 供派生）。"""
    sources = {s for srcs in _PROVIDER_SOURCES.values() for s in srcs}
    index: dict[str, str] = {}
    for path in _PKG_ROOT.rglob("*.py"):
        rel = _REL(path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "provider" in text.lower() or rel in sources:
            index[rel] = text
    return index


# ---------------------------------------------------------------------------
# ledger（交付物 A2）：(族, 文件) → 收编状态。目标是清空——迁进 invoker 后删条目。
# 每条必带族 + 状态；状态只有两值，棘轮只数 to_be_wired。
# ---------------------------------------------------------------------------
_TO_BE_WIRED = "to_be_wired"
_WIRED = "wired_via_invoker"
_VALID_STATUS = frozenset({_TO_BE_WIRED, _WIRED})

CONSUMPTION_LEDGER: dict[tuple[str, str], str] = {
    # S-W1B 实证：backend_unit 泼 web provider 进 dict 注入给 chat，chat.py 才是执行者
    # （:277 provider.search 多 query 并发 / :3301 getattr(active_web_provider,"fetch_page_text")）。
    # 不等值不可硬翻（TTL 缓存变冷=重复计费、fetch_page_text 中央无对位件、审计标签丢），故 to_be_wired。
    ("search.web", "domains/chat_reply/capabilities/chat.py"): _TO_BE_WIRED,
    # media.vision / media.asr 当前无「注入 provider 在别处被执行」消费点（唯一 .generate 在真身
    # 组合模块内，属豁免），故无条目；门仍派生其词表以盯未来新增旁路。
}
#: to_be_wired 棘轮基线（RF2-1 根修）：**手写提交整数常量，绝不从 CONSUMPTION_LEDGER 现算**。
#: 旧写法 `= sum(... CONSUMPTION_LEDGER ...)` 与被检对象同一表达式 ⇒ 真门里 `to_be_wired > baseline`
#: 恒 False（评审席注毒 P1：ledger 从 1 条灌到 3 条欠债仍 violations=[]），"只准降不准升"沦为死代码宣称。
#: 现值 = 2026-09-22 真树实测 to_be_wired 条数（=1）。三锁成链，缺一即哑：
#:  - 真门 `test_real_tree_provider_consumption_matches_ledger`：ledger 欠债 > 本常量 ⇒ 棘轮臂红；
#:  - 方向锁 `test_never_wired_forever_documented_invariant`：本常量必须 == ledger 现算欠债（改账即改常量）；
#:  - 结构锁 `test_baseline_ratchet_is_handwritten_literal_not_derived`：本行必须是整数字面量，非 `sum()`。
#: ⇒ 新增欠债须**同时**手改本常量（+1=一次故意留痕、须评审才准涨）；迁走欠债须把本常量下调（只准降）。
TO_BE_WIRED_BASELINE = 1


# ---------------------------------------------------------------------------
# 判据函数（可喂真树或合成树，保证「真会红」而非自证快照）
# ---------------------------------------------------------------------------
def check_consumption(
    found: set[tuple[str, str]],
    ledger: dict[tuple[str, str], str],
    *,
    baseline: int,
) -> list[str]:
    """双向活性 + 状态合法 + 棘轮。返回违规清单（空 = 满足），每条点名红在哪条不变量。"""
    v: list[str] = []
    unregistered = found - set(ledger)
    if unregistered:
        v.append(f"[未登记消费点] 新出现的 provider 消费点须先评审入 ledger 或迁进 invoker：{sorted(unregistered)}")
    stale = set(ledger) - found
    if stale:
        v.append(f"[登记已失效] ledger 登记了但真树扫不到（消费点已消失/改名却留着条目糊住退化）：{sorted(stale)}")
    illegal = {k: s for k, s in ledger.items() if s not in _VALID_STATUS}
    if illegal:
        v.append(f"[非法收编状态] 状态只准 {_TO_BE_WIRED}/{_WIRED}：{illegal}")
    to_be_wired = sum(1 for s in ledger.values() if s == _TO_BE_WIRED)
    if to_be_wired > baseline:
        v.append(f"[to_be_wired 棘轮上升] 现 {to_be_wired} > 基线 {baseline}（只准降不准升，新增欠债须先降一笔）")
    return v


def _found_families_files(index: dict[str, str]) -> set[tuple[str, str]]:
    vocab = derive_family_vocab(index)
    return {(fam, rel) for fam, rel, _line in _consumption_pairs(index, vocab)}


# ---------------------------------------------------------------------------
# ① 活性判据：真树消费点 ⇔ ledger，双向闭合
# ---------------------------------------------------------------------------
def test_real_tree_provider_consumption_matches_ledger() -> None:
    index = _load_consumption_index()
    found = _found_families_files(index)
    assert check_consumption(found, CONSUMPTION_LEDGER, baseline=TO_BE_WIRED_BASELINE) == [], (
        f"provider 消费 ledger 漂移：实得 {sorted(found)} ≠ 登记 {sorted(CONSUMPTION_LEDGER)}"
    )


def test_search_web_chat_consumption_is_actually_detected() -> None:
    """活性证据：chat.py 的确被本门扫成 search.web 消费点（不是靠 ledger 自证存在）。"""
    index = _load_consumption_index()
    found = _found_families_files(index)
    assert ("search.web", "domains/chat_reply/capabilities/chat.py") in found, (
        "S-W1B 实证的 chat.py web provider 旁路未被扫到——门瞎了"
    )


# ---------------------------------------------------------------------------
# 派生自证：词表真的从真身类 AST 出来（改名/坐标漂走 → 抛，而非静默变空变哑）
# ---------------------------------------------------------------------------
def test_vocab_derived_from_provider_classes_not_handcopied() -> None:
    index = _load_consumption_index()
    vocab = derive_family_vocab(index)
    # search.web provider 的核心方法名必在派生集内（S-W1B 依赖 .search / .fetch_page_text）
    assert {"search", "fetch_page_text"} <= vocab["search.web"], f"web 词表派生缺项：{vocab['search.web']}"
    # housekeeping 名不得混入（否则 close()/is_enabled() 误伤全树）
    assert "close" not in vocab["search.web"] and "is_enabled" not in vocab["media.vision"]


def test_missing_provider_source_raises_not_silent_blindness() -> None:
    """真身坐标漂走 → 派生当场抛，而不是把该族悄悄变空（=假绿）。"""
    with pytest.raises(AssertionError):
        derive_family_vocab({"domains/core/search/web_search.py": "x=1\n"})  # 缺 media 真身


# ---------------------------------------------------------------------------
# ② 注毒自证：合成树逐条证明每不变量真的会红，且点名红在哪条（不认「抛异常即过」）
# ---------------------------------------------------------------------------
def _synth_web() -> dict[str, str]:
    """够用的合成 provider 真身三件（供 derive 不炸），均落在豁免面（_DEF_FILES）故自身不成消费点。"""
    return {
        "domains/core/search/web_search.py": (
            "class ChainedWebSearchProvider:\n"
            "    def search(self, q): ...\n"
            "    def fetch_page_text(self, u): ...\n"
            "    def close(self): ...\n"
        ),
        "domains/media/ingest/vision_describe.py": "class DynamicVisionProvider:\n    def generate(self, m): ...\n",
        "domains/media/ingest/transcribe.py": "class DynamicASRProvider:\n    def generate(self, a): ...\n",
    }


def test_poison_unregistered_consumption_is_red() -> None:
    """注毒：非豁免模块里新冒出一处 web provider 消费 → 红在「未登记消费点」（空 ledger 隔离本不变量）。"""
    index = _synth_web()
    index["domains/foo/sneaky.py"] = "def f(web_search_provider, q):\n    web_search_provider.search(q)\n"
    found = _found_families_files(index)
    v = check_consumption(found, {}, baseline=0)
    assert any("未登记消费点" in s and "sneaky.py" in s for s in v), f"新消费点未被拦：{v}"
    assert not any("登记已失效" in s for s in v), f"应只报未登记，不该连带误报失效：{v}"


def test_poison_getattr_indirect_consumption_is_detected() -> None:
    """注毒：provider 方法经 getattr 间接取用（chat.py:3301 真实形态）也必须被扫到——
    少了这臂，最硬的一个消费点会溜检。断言它进 found 而非仅『不崩』。"""
    index = _synth_web()
    index["domains/foo/indirect.py"] = (
        "def f(active_web_provider, u):\n"
        "    m = getattr(active_web_provider, 'fetch_page_text', None)\n"
        "    return m(u)\n"
    )
    found = _found_families_files(index)
    assert ("search.web", "domains/foo/indirect.py") in found, f"getattr 间接消费漏检：{sorted(found)}"


def test_poison_stale_registration_is_red() -> None:
    """注毒：ledger 登了一条但真树没有（消费点已消失/改名却留条目）→ 红在「登记已失效」。"""
    index = _synth_web()  # 无任何非豁免消费点
    found = _found_families_files(index)
    poisoned_ledger = {("search.web", "domains/ghost/where.py"): _TO_BE_WIRED}
    v = check_consumption(found, poisoned_ledger, baseline=1)
    assert any("登记已失效" in s and "where.py" in s for s in v), f"失效登记未被拦：{v}"
    assert not any("未登记消费点" in s for s in v), f"真树无消费点，不该报未登记：{v}"


def test_poison_ratchet_cannot_grow() -> None:
    """注毒：to_be_wired 比基线多一笔 → 红在「棘轮上升」；wired 条目多则不数（只卡欠债）。"""
    ledger = {
        ("search.web", "domains/chat_reply/capabilities/chat.py"): _TO_BE_WIRED,
        ("search.web", "domains/chat_reply/capabilities/chat2.py"): _TO_BE_WIRED,  # 多一笔欠债
    }
    v = check_consumption(set(ledger), ledger, baseline=1)
    assert any("棘轮上升" in s for s in v), f"to_be_wired 上升未被拦：{v}"
    # 反例：多一笔 wired_via_invoker 不该顶爆棘轮
    ledger_ok = {
        ("search.web", "domains/chat_reply/capabilities/chat.py"): _TO_BE_WIRED,
        ("search.web", "domains/chat_reply/capabilities/wired.py"): _WIRED,
    }
    v2 = check_consumption(set(ledger_ok), ledger_ok, baseline=1)
    assert not any("棘轮" in s for s in v2), f"wired 条目不应计入棘轮欠债：{v2}"


def test_poison_illegal_status_is_red() -> None:
    """注毒：收编状态写错值 → 红在「非法收编状态」（防有人塞 exempt/whitelist 之类的第二豁免面）。"""
    ledger = {("search.web", "domains/foo/sneaky.py"): "grandfathered_forever"}
    v = check_consumption(set(ledger), ledger, baseline=0)
    assert any("非法收编状态" in s for s in v), f"非法状态未被拦：{v}"


def test_never_wired_forever_documented_invariant() -> None:
    """方向锁（RF2-1）：手写基线**必须等于** ledger 现算欠债——它不再由 ledger 自动派生，故此断言
    从"同表达式恒等（自指假锁）"升为真锁。新增欠债不同步改常量、或迁走欠债不下调常量，本锁皆红，
    把"清单被偷偷养肥"变成一次必须显式改常量的动作。钉死『清空是终点』：全接完时基线应为 0。"""
    derived = sum(1 for s in CONSUMPTION_LEDGER.values() if s == _TO_BE_WIRED)
    assert TO_BE_WIRED_BASELINE == derived, (
        f"手写基线 {TO_BE_WIRED_BASELINE} 与 ledger 现算欠债 {derived} 脱钩——"
        "改 ledger 数就必须同步改基线常量（新增欠债须评审、迁走欠债只准降），别留漂移"
    )


def test_baseline_ratchet_is_handwritten_literal_not_derived() -> None:
    """结构锁（RF2-1 自证形态）：从本文件源码 AST 断言 ``TO_BE_WIRED_BASELINE`` 被赋为**整数字面量**，
    而非 ``sum(... CONSUMPTION_LEDGER ...)`` 这类从被检对象现算的表达式。若有人把基线改回自指写法
    （评审 P1 定罪的形态），本用例当场红——运行期"常量==现算"两式在清单不变时同值，唯 AST 判据能拆穿。"""
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    value: ast.expr | None = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "TO_BE_WIRED_BASELINE":
                    value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "TO_BE_WIRED_BASELINE":
            value = node.value
    assert value is not None, "源码顶层找不到 TO_BE_WIRED_BASELINE 的赋值（判据被搬走？）"
    assert isinstance(value, ast.Constant) and isinstance(value.value, int) and not isinstance(value.value, bool), (
        "棘轮基线必须是手写整数字面量，不得从 CONSUMPTION_LEDGER 现算（自指=棘轮恒不执法，评审 RF2-1）"
    )
    assert value.value == TO_BE_WIRED_BASELINE, "AST 字面量值与运行期常量不一致（被别处覆写？）"


def test_poison_added_debt_trips_real_gate_ratchet() -> None:
    """活性注毒自证（RF2-1）：真门谓词喂**手写基线常量** + 一条"新消费点同步登记为欠债"的合成 ledger
    ⇒ 棘轮臂必红。修法前基线随 ledger 现算，此类欠债 to_be_wired==baseline 恒不红（评审 P1 []）。"""
    index = _load_consumption_index()
    found = _found_families_files(index)
    debt = ("search.web", "domains/poison/new_consumer.py")
    inflated_ledger = {**CONSUMPTION_LEDGER, debt: _TO_BE_WIRED}
    violations = check_consumption(found | {debt}, inflated_ledger, baseline=TO_BE_WIRED_BASELINE)
    assert any("棘轮上升" in s for s in violations), f"手写基线未生效、新增欠债漏检：{violations}"
