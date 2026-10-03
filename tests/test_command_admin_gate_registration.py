"""席 P3a（2026-10-02 续批）：命令登记面 vs 执行面管理门 —— 只读静态门。

全部 AST/文本判据：零生产 import、零 store 触达、零网络、零 git 写。
行号一律不作判据（#50★ 行号会漂），违规条目键＝``能力id:子命令名``。

在册管理令源（任一命中即算「登记为管理令」；三处真身）
  R1 ``domains/chat_reply/runtime/capability_registry`` 的 ``HelpTopicDecl(admin_only=True)``
     ——可见性权威声明（它与 ``echo._HELP_ENTRIES`` 的逐行 zip 由
     ``tests/test_capability_registry.py`` 执法；本门不重抄那份判据，只借 echo
     的别名表把「主题」落到「``/bot`` 子命令腿」上）
  R2 ``domains/core/decision/shadow._ROUTE_KIND_LEGACY_EQUIVALENTS["admin"]``
     ——中央决策引擎把哪些能力 id 登记成 admin 族等价
  R3 根 ``_handle_status``/``_handle_alias`` 的 ``/bot`` 分派链本身——``/bot`` 整族挂在
     RouteKind.ADMIN（label「管理员命令」）之下 ⇒ 链上每条腿都是命令登记面

实际门源（现网三种写法都要认，认不全＝判据退化成常绿）
  E1 分支自身判角色：
     · membership 形 ``"admin" in/not in <角色集>``
     · 交集形 ``set(actor_roles) & {"admin", "super_admin"}``
     · 角色常量形 ``ROLE_ADMIN not in roles``
     · 中央谓词直呼 ``is_admin_message`` / ``roles_satisfy`` / ``_is_admin_actor`` / ``resolve_roles``
  E2 分支把角色事实交给 builder（``actor_roles=``/``roles=``/``is_admin=``/
     ``sender_roles=``/``required_roles=``），且该 builder 体内确有 E1 形判据——判据
     可以是 builder 自己写的，也可以是它**用角色实参调用的**域内助手
     （``ops/admin/debug.py::_is_admin`` 那类）；「只传角色不判角色」不发绿

违规族（存量入基线，只降不升；新增即红；条目在真树已修好而清单没同步也红）
  V1 在册管理令而该腿执行面零门            → 基线 UNGATED_ADMIN_LEGS
  V2 admin 族在册、可见性却登成公开        → 基线 SHADOW_ADMIN_PUBLIC_LEGS
  V3 分支自身拒止、可见性却登成公开        → 基线 GATED_BUT_PUBLIC_LEGS
     （``VISIBILITY_SCOPED_IDS`` 豁免：帮助面用 is_admin 只收窄展示模块，不是整条拒止）

⚠ ``test_admin_gate_missing_on_route_commands`` 是**断链证明腿**：判的是「现状无门」。
补门一落地它必须转红 ⇒ 届时删除本条或翻正成「非管理员必拒」活性锁，并把 V1/V2
两行基线同批清掉（#68★：门 + 旗标 + 清单只动一边，必红另一边）。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "bot_unified_runtime"
ROOT_FILE = PLUGIN_ROOT / "__init__.py"
REGISTRY_FILE = PLUGIN_ROOT / "domains" / "chat_reply" / "runtime" / "capability_registry.py"
ECHO_FILE = PLUGIN_ROOT / "domains" / "chat_reply" / "capabilities" / "echo.py"
SHADOW_FILE = PLUGIN_ROOT / "domains" / "core" / "decision" / "shadow.py"

ID_RE = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+")
BOT_SUB_RE = re.compile(r"/bot\s+([A-Za-z\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff \-]*)")
ADMIN_WORD_RE = re.compile(r"['\"](?:super_)?admin['\"]|ROLE_(?:SUPER_)?ADMIN")
CENTRAL_PREDICATES = frozenset({"is_admin_message", "roles_satisfy", "_is_admin_actor", "resolve_roles"})
ROLE_ARGUMENT_NAMES = frozenset({"actor_roles", "sender_roles", "roles", "required_roles", "is_admin"})
ROLE_SOURCE_TOKENS = ("actor_roles", "sender_roles", "is_admin_message", "roles_satisfy", "is_admin")

# --- 存量基线（2026-10-02 席 P3a 现算复录；只降不升，改判据要同批同步）--------
#: V1 在册管理令而执行面零门：现状＝/bot route 与 /bot routes 两枚（本席缺陷单主角）
UNGATED_ADMIN_LEGS: frozenset[str] = frozenset({"bot.route:route", "bot.routes:routes"})
#: V2 admin 族在册而可见性登成公开：同一处缺陷的另一面（旗标侧）
SHADOW_ADMIN_PUBLIC_LEGS: frozenset[str] = frozenset({"bot.route", "bot.routes"})
#: V3 分支自身拒止、可见性却登成公开：现状零枚
GATED_BUT_PUBLIC_LEGS: frozenset[str] = frozenset()
#: 可见性收窄豁免：is_admin 只决定展示哪些帮助模块，不是整条命令的拒止
VISIBILITY_SCOPED_IDS: frozenset[str] = frozenset({"bot.help", "bot.commands"})


def leg_key(capability_id: str, keys) -> str:
    """违规条目键＝能力 id + 该腿认得出的子命令名（符号，不含行号）。"""
    return f"{capability_id}:{','.join(sorted(keys)) or '_'}"


# ===========================================================================
# 纯判据函数（喂合成数据即可注毒自证，不碰真树）
# ===========================================================================
def find_ungated_admin_legs(branches, registered_admin_caps, baseline):
    """V1：被登记源认成管理令、该腿执行面却零角色判据。返回 (违规条目, 陈旧条目)。"""
    violations = {
        leg_key(cap, row["keys"])
        for row in branches
        for cap in row["capability_ids"]
        if cap in registered_admin_caps and not row["gated"]
    }
    return violations, set(baseline) - violations


def find_shadow_admin_visibility_splits(branches, public_caps, shadow_admin_ids, baseline):
    """V2：中央 admin 族在册、帮助册可见性却登记成公开的腿。"""
    by_cap = {}
    for row in branches:
        for cap in row["capability_ids"]:
            by_cap[cap] = by_cap.get(cap, True) and row["gated"]
    violations = {cap for cap in shadow_admin_ids if cap in public_caps and by_cap.get(cap) is False}
    return violations, set(baseline) - violations


def find_gated_but_public_legs(branches, public_caps, exempt, baseline):
    """V3：分支自身拒止、可见性却对普通用户宣传（看得见、打不开）。"""
    violations = {
        leg_key(cap, row["keys"])
        for row in branches
        if row["self_denies"]
        for cap in row["capability_ids"]
        if cap in public_caps and cap not in exempt
    }
    return violations, set(baseline) - violations


# ===========================================================================
# 真树抽取（AST only）
# ===========================================================================
def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _string(node) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ""


def _nodes(body):
    return ast.walk(ast.Module(body=list(body), type_ignores=[]))


def _has_membership(body) -> bool:
    """体内确有「admin/super_admin ∈ 角色集」形状的判据（须同体见到角色事实）。

    现网三种写法逐条认：membership（``in``/``not in``）、交集（``set(roles) & {...}``）、
    角色常量名（``ROLE_ADMIN not in roles``）。
    """
    whole = ast.unparse(ast.Module(body=list(body), type_ignores=[]))
    if not any(token in whole for token in ROLE_SOURCE_TOKENS):
        return False
    for node in _nodes(body):
        if (
            isinstance(node, ast.Compare)
            and any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops)
            and ADMIN_WORD_RE.search(ast.unparse(node))
        ):
            return True
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitAnd):
            rendered = ast.unparse(node)
            if ADMIN_WORD_RE.search(rendered) and re.search(r"set\(|roles", rendered):
                return True
    return False


def _direct_predicate_call(body) -> bool:
    for node in _nodes(body):
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
            if name in CENTRAL_PREDICATES:
                return True
    return False


def _calls_with_roles(body) -> set[str]:
    """被调用件名，且该次调用把角色事实当实参交出去（E2 的第二段用得上）。"""
    out: set[str] = set()
    for node in _nodes(body):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
        if not name:
            continue
        if name in CENTRAL_PREDICATES:
            out.add(name)
            continue
        rendered = " ".join(ast.unparse(arg) for arg in node.args) + " " + " ".join(
            ast.unparse(kw.value) for kw in node.keywords
        )
        if any(token in rendered for token in ROLE_SOURCE_TOKENS):
            out.add(name)
    return out


def package_gate_index() -> dict[str, bool]:
    """全主包函数：该函数体是否真判角色（自身 E1 形判据，或它用角色实参调了一个
    判角色的助手——``_is_admin`` 这类家规助手要认，助手之助手再传一轮即止）。"""
    own: dict[str, tuple[bool, set[str]]] = {}
    for path in sorted(PLUGIN_ROOT.rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        try:
            tree = _parse(path)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                judgement = _has_membership(node.body) or _direct_predicate_call(node.body)
                callees = _calls_with_roles(node.body)
                prev = own.get(node.name)
                if prev is None:
                    own[node.name] = (judgement, callees)
                else:
                    own[node.name] = (prev[0] or judgement, prev[1] | callees)
    gated = {name: flags[0] for name, flags in own.items()}
    for _round in range(2):
        for name, (judgement, callees) in own.items():
            if gated[name]:
                continue
            if any(gated.get(callee, False) for callee in callees):
                gated[name] = True
    return gated


def _command_keys(nodes) -> list[str]:
    keys: list[str] = []
    for node in ast.walk(ast.Module(body=[*nodes], type_ignores=[])):
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == "command_text":
            for comparator in node.comparators:
                value = _string(comparator)
                if value and value not in keys:
                    keys.append(value)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"startswith", "removeprefix"}
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "command_text"
        ):
            for arg in node.args:
                for element in (arg.elts if isinstance(arg, ast.Tuple) else [arg]):
                    value = _string(element).strip()
                    if value and value not in keys:
                        keys.append(value)
    return keys


def _assigned_caps(body) -> list[str]:
    caps: list[str] = []
    for node in _nodes(body):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "capability_id":
                    value = _string(node.value)
                    if value and value not in caps:
                        caps.append(value)
    return caps


def _branch_row(handler: str, body, gate_index: dict[str, bool], line: int, test_node) -> dict:
    whole = ast.unparse(ast.Module(body=list(body), type_ignores=[]))
    hands_off = any(f"{arg_name}=" in whole for arg_name in ROLE_ARGUMENT_NAMES)
    self_denies = _has_membership(body) or _direct_predicate_call(body)
    builder_denies = any(gate_index.get(name, False) for name in _calls_with_roles(body))
    keys = _command_keys([*body, *([test_node] if test_node is not None else [])])
    return {
        "handler": handler,
        "keys": keys,
        "capability_ids": _assigned_caps(body),
        "gated": bool(self_denies or (hands_off and builder_denies)),
        "self_denies": bool(self_denies),
        "builder_mediated": bool(builder_denies),
        "line": line,
    }


def chain_branches() -> list[dict]:
    """根 ``/bot`` 分派链逐条腿（只走 if/elif/else 链本身，不下钻闭包内的嵌套 if——
    闭包内的 ``if`` 是一条命令腿**内部**的分支，把它当腿会把「同命令的两个内部分支」
    读成「一枚有门一枚没门」，判据就失去意义）。"""
    handlers = [
        node
        for node in ast.walk(_parse(ROOT_FILE))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in {"_handle_status", "_handle_alias"}
    ]
    assert handlers, "根里找不到 _handle_status/_handle_alias——分派形态变了，本门先报警而不是静默绿"
    gate_index = package_gate_index()
    rows: list[dict] = []
    for handler in handlers:
        for statement in handler.body:
            if not isinstance(statement, ast.If):
                continue
            chain: ast.If | None = statement
            while chain is not None:
                rows.append(_branch_row(handler.name, chain.body, gate_index, chain.lineno, chain.test))
                orelse = chain.orelse
                if not orelse:
                    break
                inner = [s for s in orelse if isinstance(s, ast.If)]
                if len(orelse) == 1 and len(inner) == 1:
                    chain = inner[0]
                    continue
                rows.append(_branch_row(handler.name, orelse, gate_index, orelse[0].lineno, chain.test))
                break
    unique: dict[tuple, dict] = {}
    for row in rows:
        if not row["capability_ids"]:
            continue
        unique.setdefault((row["handler"], row["line"], tuple(row["capability_ids"]), tuple(row["keys"])), row)
    return list(unique.values())


def help_entry_aliases() -> dict[str, tuple[str, ...]]:
    """``echo._HELP_ENTRIES`` 的 topic→aliases（用户实际打得出那串词）。"""
    out: dict[str, tuple[str, ...]] = {}
    for node in ast.walk(_parse(ECHO_FILE)):
        if not isinstance(node, ast.Dict):
            continue
        keys = [_string(k) for k in node.keys]
        if "topic" not in keys or "admin_only" not in keys:
            continue
        values = dict(zip(keys, node.values))
        topic = _string(values["topic"])
        alias_node = values.get("aliases")
        aliases = tuple(
            _string(element)
            for element in (alias_node.elts if isinstance(alias_node, (ast.Tuple, ast.List)) else ())
            if _string(element)
        )
        if topic:
            out[topic] = aliases
    return out


def help_declarations() -> list[dict]:
    """R1 权威声明 + 借 echo 别名表把主题落到 ``/bot`` 子命令。"""
    aliases_by_topic = help_entry_aliases()
    rows = []
    for node in ast.walk(_parse(REGISTRY_FILE)):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "HelpTopicDecl":
            fields = {kw.arg: kw.value for kw in node.keywords}
            admin = fields.get("admin_only")
            capability = _string(fields.get("capability"))
            topic = _string(fields.get("topic"))
            rows.append(
                {
                    "topic": topic,
                    "admin_only": isinstance(admin, ast.Constant) and admin.value is True,
                    "declared_admin_only": "admin_only" in fields,
                    "capability": capability,
                    "ids": ID_RE.findall(capability),
                    "subs": [s.strip().split()[0] for s in BOT_SUB_RE.findall(capability)],
                    "aliases": aliases_by_topic.get(topic, ()),
                    "line": node.lineno,
                }
            )
    return rows


def shadow_admin_ids() -> set[str]:
    ids: set[str] = set()
    for node in ast.walk(_parse(SHADOW_FILE)):
        targets = getattr(node, "targets", None) or (
            [node.target] if isinstance(node, ast.AnnAssign) else []
        )
        if not any(isinstance(t, ast.Name) and "LEGACY_EQUIVALENTS" in t.id for t in targets):
            continue
        value = getattr(node, "value", None)
        if not isinstance(value, ast.Dict):
            continue
        for key, element in zip(value.keys, value.values):
            if _string(key) != "admin":
                continue
            args = element.args if isinstance(element, ast.Call) else [element]
            for arg in args:
                for item in getattr(arg, "elts", []):
                    text = _string(item)
                    if text:
                        ids.add(text)
    return ids


def _caps_of_decl(decl, key_to_caps) -> set[str]:
    """主题 → 能力 id：只吃 capability 的**主登记位**与 echo 别名表。

    capability 登记文里括号内的交叉引用（如「亲密模式」那行提到 ``/bot identity``、
    「供应商」那行提到 ``/bot model``）不是本主题的命令入口，吃了就会把别的腿错标成
    本主题的可见性——表一旦错标，整把尺就废了。故 ``/bot 子命令`` 位只在登记文以
    ``/bot`` 开头时取。
    """
    caps = set(decl["ids"])
    words = list(decl["aliases"])
    if decl["capability"].lstrip().startswith("/bot"):
        for sub in decl["subs"]:
            words.append(sub)
            words.append(sub.split()[0])
    for word in words:
        caps.update(key_to_caps.get(word, ()))
    return caps


def registered_admin_caps(branches, decls) -> set[str]:
    key_to_caps = {key: row["capability_ids"] for row in branches for key in row["keys"]}
    out: set[str] = set()
    for decl in decls:
        if decl["admin_only"]:
            out |= _caps_of_decl(decl, key_to_caps)
    return out


def public_caps(branches, decls) -> set[str]:
    key_to_caps = {key: row["capability_ids"] for row in branches for key in row["keys"]}
    out: set[str] = set()
    for decl in decls:
        if not decl["admin_only"]:
            out |= _caps_of_decl(decl, key_to_caps)
    return out


# ===========================================================================
# 真树判据
# ===========================================================================
def test_admin_gate_missing_on_route_commands():
    """断链证明（现状读数）：``/bot route`` 与 ``/bot routes`` 此刻确实零管理门。

    今天必须绿＝缺陷仍在、台账未欠账；补门落地后本条**必须转红**，届时删除或翻正为
    「非管理员必拒」活性锁，并同批清掉本文件 V1/V2 基线。
    """
    rows = chain_branches()
    by_cap = {cap: row for row in rows for cap in row["capability_ids"]}
    registered = shadow_admin_ids()

    for cap, key in (("bot.route", "route"), ("bot.routes", "routes")):
        row = by_cap.get(cap)
        assert row is not None, f"{cap} 的 /bot 分派腿在根链上找不到了——分派形态变了，先核实再翻案"
        assert not row["gated"], (
            f"{cap} 执行面已出现角色判据＝补门已落地；删除本断链条或翻正为 deny 活性锁，"
            "并同步 V1/V2 基线清单（工单 patches/P3A-ROUTE-GATE-PROPOSAL-20261002.md）"
        )
        assert key in row["keys"], f"{cap} 的腿不再由子命令「{key}」命中——分派形态变了，基线条目键要重新现算"
        assert cap in registered, f"{cap} 已不在中央决策引擎 admin 族等价表里＝口径来源变了，重新现算基线"


def test_no_new_ungated_admin_command_leg():
    """V1 棘轮：在册管理令而该腿执行面零门——新增即红，修好却不同步清单也红。"""
    rows = chain_branches()
    registered = registered_admin_caps(rows, help_declarations()) | shadow_admin_ids()
    violations, stale = find_ungated_admin_legs(rows, registered, UNGATED_ADMIN_LEGS)
    assert not violations - UNGATED_ADMIN_LEGS, (
        f"新增「登记为管理令而执行面零门」的命令腿: {sorted(violations - UNGATED_ADMIN_LEGS)}"
    )
    assert not stale, f"基线登着的无门腿在真树已被补门（清单未同批同步）: {sorted(stale)}"


def test_no_shadow_admin_leg_declared_public():
    """V2 棘轮：中央 admin 族在册、帮助册可见性却写公开——同一处缺陷的另一面。"""
    rows = chain_branches()
    violations, stale = find_shadow_admin_visibility_splits(
        rows, public_caps(rows, help_declarations()), shadow_admin_ids(), SHADOW_ADMIN_PUBLIC_LEGS
    )
    assert not violations - SHADOW_ADMIN_PUBLIC_LEGS, (
        f"新增 admin 族在册而可见性登公开的分裂腿: {sorted(violations - SHADOW_ADMIN_PUBLIC_LEGS)}"
    )
    assert not stale, f"口径分裂基线里的条目已修好（清单未同步）: {sorted(stale)}"


def test_no_gated_but_public_command_leg():
    """V3 棘轮：分支自身拒止、帮助册却对普通用户宣传（看得见、打不开）。"""
    rows = chain_branches()
    violations, stale = find_gated_but_public_legs(
        rows, public_caps(rows, help_declarations()), VISIBILITY_SCOPED_IDS, GATED_BUT_PUBLIC_LEGS
    )
    assert not violations - GATED_BUT_PUBLIC_LEGS, (
        f"新增「公开登记、执行必拒」的腿: {sorted(violations - GATED_BUT_PUBLIC_LEGS)}"
    )
    assert not stale, f"V3 基线条目已修好（清单未同步）: {sorted(stale)}"


def test_extractor_is_not_a_green_lie():
    """抽取器空转防护：三处登记面与根链都要有读数，既有管理令要判得出「有门」，
    按设计公开的腿不许被判成有门（尺子两头都要有牙）。"""
    rows = chain_branches()
    assert len(rows) >= 28, f"/bot 分派链只读出 {len(rows)} 条腿，抽取器疑似失效"
    caps = {cap for row in rows for cap in row["capability_ids"]}
    assert {
        "bot.route", "bot.routes", "bot.status", "bot.parse", "bot.search", "bot.group_policy"
    } <= caps, sorted(caps)
    ungated_caps = {cap for row in rows for cap in row["capability_ids"] if not row["gated"]}
    must_be_gated = {
        "bot.status", "bot.parse", "bot.search", "bot.group_policy", "bot.reply", "bot.logs",
        "bot.roles", "bot.config", "bot.identity", "bot.quirk", "bot.audit", "bot.receipt",
        "bot.recent", "bot.queue", "bot.context", "bot.history", "bot.control", "bot.runtime",
        "bot.persona", "bot.dialogue", "bot.readiness", "bot.why", "bot.setup.llm", "bot.llm",
        "bot.alert",
    }
    assert not (must_be_gated & ungated_caps), (
        f"这些既有管理令有腿判不出「有门」＝判据退化成常绿: {sorted(must_be_gated & ungated_caps)}"
    )
    gated = {cap for row in rows for cap in row["capability_ids"] if row["gated"]}
    must_stay_public = {"bot.route", "bot.routes", "bot.download", "bot.memory", "bot.affinity"}
    assert not (must_stay_public & gated), f"这些无门腿被判成了有门＝尺子过严，会误伤下一波: {sorted(must_stay_public & gated)}"
    index = package_gate_index()
    for builder in ("build_feature_control_result", "build_reply_policy_preset_result", "build_status_result"):
        assert index.get(builder) is True, f"{builder} 的门形没被认出来——现网第三种写法要补进 _has_membership"
    decls = help_declarations()
    assert len(decls) >= 80, len(decls)
    assert sum(1 for d in decls if d["admin_only"]) >= 40, sum(1 for d in decls if d["admin_only"])
    assert all(d["aliases"] for d in decls), "有主题在 echo 别名表里取不到词——主题与条目脱钩，V1/V2 会瞎"
    assert shadow_admin_ids() >= {"bot.status", "bot.route", "bot.routes"}, sorted(shadow_admin_ids())
    assert {"bot.route", "bot.routes"} <= registered_admin_caps(rows, decls) | shadow_admin_ids()


# ===========================================================================
# 注毒自证（做错必须红 + 做对不误伤；合成数据，不碰真树）
# ===========================================================================
def test_poison_ungated_admin_leg_is_detected_and_gated_leg_is_not():
    branches = [
        {"capability_ids": ["bot.ok"], "keys": ["ok"], "gated": True, "self_denies": True},
        {"capability_ids": ["bot.newhole"], "keys": ["newhole"], "gated": False, "self_denies": False},
    ]
    violations, stale = find_ungated_admin_legs(
        branches, {"bot.ok", "bot.newhole"}, baseline=frozenset({"bot.legacy:legacy"})
    )
    assert violations == {"bot.newhole:newhole"}, violations
    assert "bot.ok:ok" not in violations
    assert stale == {"bot.legacy:legacy"}


def test_poison_visibility_split_fires_only_on_ungated_public_admin_family():
    branches = [
        {"capability_ids": ["bot.route"], "keys": ["route"], "gated": False, "self_denies": False},
        {"capability_ids": ["bot.status"], "keys": ["status"], "gated": True, "self_denies": True},
    ]
    violations, stale = find_shadow_admin_visibility_splits(
        branches,
        public_caps={"bot.route"},
        shadow_admin_ids={"bot.route", "bot.status"},
        baseline=SHADOW_ADMIN_PUBLIC_LEGS,
    )
    assert violations == {"bot.route"}, violations
    assert "bot.status" not in violations
    assert stale == {"bot.routes"}


def test_poison_gated_but_public_is_detected_and_scoped_help_is_not():
    branches = [
        {"capability_ids": ["bot.help"], "keys": ["help"], "gated": True, "self_denies": True},
        {"capability_ids": ["bot.sneaky"], "keys": ["sneaky"], "gated": True, "self_denies": True},
    ]
    violations, _stale = find_gated_but_public_legs(
        branches,
        public_caps={"bot.help", "bot.sneaky"},
        exempt=VISIBILITY_SCOPED_IDS,
        baseline=frozenset(),
    )
    assert violations == {"bot.sneaky:sneaky"}, violations
    assert "bot.help:help" not in violations


def test_poison_membership_shapes_all_recognised():
    """三形门都要认得；缺任何一形都会把既有管理令读成「无门」（＝假红）或反之（＝假绿）。"""
    sources = {
        "membership": 'def _a(actor_roles):\n    if "admin" not in {str(r) for r in actor_roles}:\n        return 1\n',
        "intersection": 'def _b(actor_roles):\n    if not set(actor_roles) & {"admin", "super_admin"}:\n        return 1\n',
        "role_const": (
            'def _c(actor_roles):\n    roles = {str(r) for r in actor_roles}\n'
            '    if ROLE_ADMIN not in roles and ROLE_SUPER_ADMIN not in roles:\n        return 1\n'
        ),
        "no_gate": 'def _d(actor_roles):\n    return actor_roles\n',
    }
    for shape, source in sources.items():
        tree = ast.parse(source)
        func = tree.body[0]
        judged = _has_membership(func.body)
        if shape == "no_gate":
            assert not judged, shape
        else:
            assert judged, shape
