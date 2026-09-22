"""WIRE-L2 装配可达性锁：把「机制存在但生产零接线」从"靠人查"升级成机器门。

三条锁（全部正向实断言，不挂 xfail）：

- **R1 投递触点可达**：V2a 席实测 `deliver_emergency` 曾在 plugins 全树零引用
  ——四把锁全绿而投递是死代码。本锁三段判据：
  ① 排除紧急域自身后，仍有 `ImportFrom(...service.push)` 且 names 含
  `deliver_emergency`（域外真消费者）；② 装配面（根 `__init__.py` /
  `domains/chat_reply/runtime/service_wiring.py` / `capability_registry.py` 真身）出现
  `deliver_emergency(` 调用；③ 参与扫描的文件数地板（反空转：扫描器本身
  瞎了也必须红）。任一段缺失即 fail 并点名缺哪一段。
- **R2 D-8(a) 装配注入可达**：R2 评审席实测 `bot_emergency_info_auto_approve_sources`
  是死键（config.py 之外零消费点，权威源自动过审根本没生效）。本锁钉死根装配
  确实以 `build_review_gate(store, source)` 注入 `review_gate=`——名单与
  authorizer 两枚旋钮都从快照同源搬运。
- **R3 十键死键锁**：`bot_emergency_info_*` 十枚键逐个核，除 `config.py` 与
  测试面外至少有一个生产读点。**口径分界**（防误伤台账 #26 的既有裁定）：
  本锁只覆盖紧急信息域本波新落的键族；旧批「休眠预留」键不在任何新锁的射程内。

测试面排除：本件与全部 `tests/` 都位于 plugins 树之外，R1/R3 只扫
`plugins/`，天然满足「非测试读点」口径。

全离线：纯文件 AST/文本扫描，零网络、零 NoneBot、零 SQLite。
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGINS_ROOT = REPO_ROOT / "plugins"
DOMAIN_DIR = (
    PLUGINS_ROOT / "bot_unified_runtime" / "domains" / "emergency_info"
)
CONFIG_FILE = PLUGINS_ROOT / "bot_unified_runtime" / "config.py"
ASSEMBLY_FILES = (
    PLUGINS_ROOT / "bot_unified_runtime" / "__init__.py",
    PLUGINS_ROOT / "bot_unified_runtime" / "domains" / "chat_reply" / "runtime" / "service_wiring.py",
    PLUGINS_ROOT
    / "bot_unified_runtime"
    / "domains"
    / "chat_reply"
    / "runtime"
    / "capability_registry.py",
)

#: 反空转地板：实测 plugins 树 646 个 py 文件、紧急域自身 17 个。留足余量取 400，
#: 远低于现值（正常漂移不会红）、远高于「扫描器退化」（目录拼错只剩几十文件必红）。
SCANNED_FILE_FLOOR = 400

#: `config.py:482-491` 的十枚域键（逐字面，改名即红＝本锁自带防漂移）。
EMERGENCY_INFO_CONFIG_KEYS = (
    "bot_emergency_info_enabled",
    "bot_emergency_info_sources",
    "bot_emergency_info_auto_approve_sources",
    "bot_emergency_info_poll_interval_seconds",
    "bot_emergency_info_min_level",
    "bot_emergency_info_push_group_whitelist",
    "bot_emergency_info_push_user_ids",
    "bot_emergency_info_reviewer_ids",
    "bot_emergency_info_keep_days",
    "bot_emergency_info_db_path",
)


def _scan_files() -> list[Path]:
    """plugins 全树 py 文件，排除紧急域自身（域内自引用不算"接线到了生产"）。"""
    return [
        path
        for path in sorted(PLUGINS_ROOT.rglob("*.py"))
        if DOMAIN_DIR not in path.parents and path.name != "__pycache__"
    ]


def _importers_of_push(module_tail: str, symbol: str) -> list[Path]:
    """AST 级判据：域外文件中 `from ...<module_tail> import (... symbol ...)` 的命中。"""
    hits: list[Path] = []
    for path in _scan_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - 全树可解析是既有门
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            module = str(node.module or "")
            if not module.endswith(module_tail):
                continue
            if any(alias.name == symbol for alias in node.names):
                hits.append(path)
                break
    return hits


# ---------------------------------------------------------------- R1 投递触点可达


def test_deliver_emergency_is_reachable_from_production_assembly() -> None:
    missing: list[str] = []

    # 段③先算：地板不过 ⇒ 前两段结论无效（扫描器空转）。
    scanned = _scan_files()
    if len(scanned) < SCANNED_FILE_FLOOR:
        missing.append(
            f"反空转地板：参与扫描文件数 {len(scanned)} < {SCANNED_FILE_FLOOR}"
            "（扫描根/排除规则被改坏，任何'零引用'或'有引用'结论都不可信）"
        )

    # 段①：域外存在 `from ...service.push import deliver_emergency`。
    importers = _importers_of_push(
        "domains.emergency_info.service.push", "deliver_emergency"
    )
    if not importers:
        missing.append(
            "段①：plugins 树（排除紧急域自身）没有任何 "
            "`ImportFrom(...domains.emergency_info.service.push)` 且 names 含 "
            "`deliver_emergency` ⇒ 投递触点在域外零消费者＝死代码回场"
        )

    # 段②：装配面出现真调用 `deliver_emergency(`。
    call_sites = [
        path
        for path in ASSEMBLY_FILES
        if path.is_file() and "deliver_emergency(" in path.read_text(encoding="utf-8")
    ]
    if not call_sites:
        names = ", ".join(str(p.relative_to(REPO_ROOT)) for p in ASSEMBLY_FILES)
        missing.append(
            f"段②：装配面（{names}）没有任何 `deliver_emergency(` 调用"
            "⇒ 采集/投递 job 不再经过中央投递触点"
        )

    assert not missing, "投递触点可达性被破坏：\n- " + "\n- ".join(missing)


# ---------------------------------------------------------------- R2 D-8(a) 装配注入


def test_auto_approve_wiring_is_injected_at_the_root_assembly() -> None:
    root = ASSEMBLY_FILES[0]
    assert root.is_file(), f"根装配文件缺失：{root}"
    text = root.read_text(encoding="utf-8")
    missing: list[str] = []

    if "review_gate=build_review_gate(" not in text:
        missing.append(
            "根装配未以 `review_gate=build_review_gate(...)` 注入审核门"
            "⇒ EmergencyInfoService 会退回内联缺省闸（R2 评审席抓的"
            "「auto_approve_sources 死键、所有源一律 pending」正是这个形态）"
        )
    importers = _importers_of_push(
        "domains.emergency_info.capabilities.emergency_info", "build_review_gate"
    )
    if root not in importers:
        missing.append(
            "根装配没有 `from ...capabilities.emergency_info import build_review_gate`"
            "（AST 级判据，域外 importers="
            + ", ".join(str(p.name) for p in importers)
            + "）"
        )
    assert not missing, "D-8(a) 装配注入被拆：\n- " + "\n- ".join(missing)


# ---------------------------------------------------------------- R3 十键死键锁


def _production_read_points(key: str) -> list[Path]:
    """plugins 树（排除键定义面 `config.py`）里**真读**该键的生产文件。

    判据是 AST 而非子串（WIRE-V2 M2）：旧实现用 `key in text`，于是
    「把读点删掉、只留一句提到该键的注释」也能骗绿——正是本锁要治的死键病可以
    骗过本锁。现只认三种真读形态：
    ① `ast.Attribute` 且属性名==key（`config.bot_emergency_info_*`）；
    ② `getattr(obj, "<key>")` 第二实参为该键的字面常量；
    ③ `obj["<key>"]` 下标为字面常量（映射式配置读法）。
    """
    hits: list[Path] = []
    for path in sorted(PLUGINS_ROOT.rglob("*.py")):
        if path == CONFIG_FILE:
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:  # pragma: no cover
            continue
        if key not in source:  # 先粗筛，避免对全树每个文件都 parse
            continue
        if _ast_reads_attribute_key(source, key):
            hits.append(path)
    return hits


def _ast_reads_attribute_key(source: str, key: str) -> bool:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == key:
            return True
        if isinstance(node, ast.Call) and _is_getattr_of(node, key):
            return True
        if isinstance(node, ast.Subscript) and _is_subscript_of(node, key):
            return True
    return False


def _is_getattr_of(node: ast.Call, key: str) -> bool:
    func = node.func
    if not (isinstance(func, ast.Name) and func.id == "getattr"):
        return False
    if len(node.args) < 2:
        return False
    name = node.args[1]
    return isinstance(name, ast.Constant) and name.value == key


def _is_subscript_of(node: ast.Subscript, key: str) -> bool:
    index = node.slice
    return isinstance(index, ast.Constant) and index.value == key


def test_every_emergency_info_config_key_has_a_production_reader() -> None:
    """本波十键逐个核：除 config.py 与 tests/ 外至少一个生产读点。

    口径分界：台账 #26「死配置键=休眠预留不加废弃标注」是**旧批休眠键**的
    既有裁定，本锁不追溯别人那批键；本锁只管 `bot_emergency_info_*` 这一族
    ——新落的键不许当死键（R2 评审席的 `_auto_approve_sources` 教训）。
    """
    offenders: list[str] = []
    for key in EMERGENCY_INFO_CONFIG_KEYS:
        hits = _production_read_points(key)
        if not hits:
            offenders.append(
                f"{key}：config.py 之外全 plugins 树零命中 ⇒ 死键"
            )
    assert not offenders, (
        "紧急信息域出现死配置键（装配没接、名单空转、机制不生效）：\n- "
        + "\n- ".join(offenders)
    )


# ────────────────────────── §D 装配语义结构锁（1.A / 2.A）──────────────────────────

ROOT_INIT = PLUGINS_ROOT / "bot_unified_runtime" / "__init__.py"
#: 装配门两腿（WIRE-SUB 裁定 3.B 后的口径，第三腿见 `_REMOVED_LEG`）。
_ASSEMBLY_LEGS = (
    "emergency_source.enabled",
    "and emergency_source.sources",
)
_REMOVED_LEG = "(emergency_source.push_group_whitelist or emergency_source.push_user_ids)"


def _root_source() -> str:
    return ROOT_INIT.read_text(encoding="utf-8")


def test_gate_absent_keeps_query_alive_but_never_delivers() -> None:
    """1.A（用户裁定）：闸缺位不再关整条链，但一条都不许投。

    口径：装配条件必须仍是**两腿**（不得顺手放宽成只看总闸，那会把 I-1 刚补上的
    路由/装配同腿性又打破）；闸缺位时投递目标必须是空集，
    而不是带着 None 去调 `deliver_emergency`（钉死③：不许出现不经闸的裸投递）。
    """
    src = _root_source()
    for leg in _ASSEMBLY_LEGS:
        assert leg in src, f"装配门腿被改动，缺 `{leg}`"
    assert _REMOVED_LEG not in src, (
        ".env 投递名单又变成装配门第三腿 ⇒ 没有名单就没有 matcher ⇒ "
        "群里第一句「紧急信息 订阅」永远没人应答（裁定 3.B 已作废这条腿）"
    )
    assert "and outbound_gate is not None" not in src, (
        "闸缺位又被挪回装配关 ⇒ 查询面/采集会随闸一起死（1.A 已裁定不允许）"
    )
    assert "[] if gate is None else _push_targets()" in src, (
        "闸缺位时没有把投递目标收空 ⇒ 可能带着 None 去调闸，退化成不经闸投递"
    )


def test_delivery_targets_are_read_live_from_subscriptions() -> None:
    """裁定 3.B 的活性锁：目标每轮**现读**订阅表并按条过滤，装配期冻结=功能失效。

    只查字符串存在性不够——曾经烧过的坑是"机制存在但装配落空"（D-8(a) 那回）。
    因此三处同时钉：现读取数、逐条过筛、命中记账；任何一处被拆都意味着订阅面
    退化成「写了不生效」，正是本域最不该再犯一次的错。端到端的真投递可达性由
    本文件 R1 那族用例（`_FakeGate`/`_FakeQueue`）负责，不靠本锁自证。
    """
    src = _root_source()
    assert "service.store.list_subscriptions()" in src, (
        "投递目标不再现读订阅表 ⇒ 群里设完要重启才生效，等于把这条功能的意义抹掉"
    )
    assert "matches_subscription(graded, rule)" in src, (
        "订阅条件不再参与逐条筛选 ⇒ 全量条目会无视地点/类型/等级推给每个订阅目标"
    )
    assert "note_subscription_match(rule.target_key, at=now)" in src, (
        "命中不再记账 ⇒ `订阅 看` 的「从没命中过」观测面变成假话"
    )
    assert "for target, rule in targets" in src, "目标-规则成对投递的循环被拆开"


def test_unregistered_source_ids_are_named_not_swallowed() -> None:
    """2.A（用户裁定）：`sources` 里写了未注册的 SOURCE_ID 必须点名，不许静默滤空。

    已知薄弱点：`if not deps.sources: return` 会让填错 ids 变成"一声不响地什么都不采"，
    与今天那个 `nmc_alarm` 误填事故同型。本锁钉三件事——从真注册表取合法值（不许另抄名单）、
    算出差集、并把差集打进日志。
    """
    src = _root_source()
    assert "{task.source_id for task in deps.sources}" in src, (
        "合法源清单不再取自真注册表 ⇒ 会出现第二份名单并各自漂移"
    )
    assert "set(source.sources) - registered" in src, "未注册的 ids 不再被算出来"
    assert '",".join(unknown)' in src, "未注册的 ids 被算出来却没说出去（静默滤空回潮）"
