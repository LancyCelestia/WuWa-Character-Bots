"""记忆总线装配可达性锁（S-MEMBUS-K4-PREP 接替段，2026-09-26，用户第 11 项 §2）。

判据一句话：**开关一置 true，总线真被装配且真在消息链上跑**——三段链一枚枚钉：

1. 根装配：``build_chat_capability(character_provider=build_character_context_provider(config, …))``
   （根 ``__init__.py``，本锁只 AST 读它，**一字不改**——另一路会话在写该文件）；
2. 装配缝：``build_character_context_provider`` 内 ``memory_provider=build_memory_read_provider(config)``
   （唯一缝），且 ``FileCharacterContextProvider.build_context`` 真消费 ``self.memory_provider.retrieve``；
3. 渲染腿：``chat.py`` 的 ``if context.memory_results.facts:`` 分支出【记忆】分区。

外加：

- **行为两态锁**：同一份 tmp 合成库，``bot_memory_bus_enabled`` 开/关给出可判别的两态
  （开=总线行进 ``retrieve()`` 且 ``memory_recall_audit_v21`` 落账；关=同一行召不回、recall_mode 变旧口径）——
  审计行是"路径真被走过"的实锤，不是"函数存在"的存在性判据。
- **E2E 半程**：经 ``FileCharacterContextProvider.build_context`` 走消费腿，证明检索发生在
  context 构建内部（不是只有装配口的 standalone 调用）。
- **杀伤力自证**：三段 AST 判据各喂一份**合成毒形副本**（tmp 拷贝上做字符串替换，
  生产文件零接触），断言摘掉装配调用必红——本仓先例 = ack 锁用合成"只入队"注毒体反验。
- **取数口绊线（§1 结论的常驻形态）**：
  ① 全 plugins 树禁 ``get_or("BOT_MEMORY…")`` 裸覆盖册口（防第 3 项 ACG 型病灶回潮/新增）；
  ② 根 ``setting("BOT_MEMORY_EXTRACT_*", …)`` 四枚的缺省侧必须现读 ``config.``（合并形态，
     ``.env`` 到得了）；改成硬字面量当场红；
  ③ ``build_memory_bus(semantic_scorer=…`` 生产侧仍须零注入——K4-1「在册未执法」的绊线：
     谁接线谁翻叙述（改本锁必须先改 AGENTS/HANDBOOK 口径并带证据，不许静默放行）；
  ④ ``absorb_preprocessed_summary``（媒体摘要→总线写腿）生产侧仍零调用点——同理。

断言一律吃**判据**不吃计数（"共 N 枚"式的写法一长就恒假红，本仓有先例）。
"""

from __future__ import annotations

import ast
import re
import sqlite3
from pathlib import Path

from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
    FileCharacterContextProvider,
    build_memory_read_provider,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_INIT = REPO_ROOT / "plugins" / "bot_unified_runtime" / "__init__.py"
PROVIDERS_PY = (
    REPO_ROOT
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "chat_reply"
    / "character"
    / "providers.py"
)
CHAT_PY = (
    REPO_ROOT
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "chat_reply"
    / "capabilities"
    / "chat.py"
)
PLUGINS_DIR = REPO_ROOT / "plugins"

GROUP_A = "group_1108838060_3865067623"
MEMORY_TEXT = "我喜欢柠檬茶"


class Cfg:
    """生产同形最小配置面：只放装配/读取路径真会 getattr 的键。"""

    bot_memory_enabled = True
    bot_memory_db_path = ""
    bot_memory_max_items = 5
    bot_memory_max_chars = 1200
    bot_memory_bus_enabled = True
    bot_memory_reflected_write_target = "legacy"
    bot_memory_strength_k = 3.0
    bot_memory_tau_stable_days = 180
    bot_memory_tau_seasonal_days = 45
    bot_memory_tau_episodic_days = 14
    bot_memory_relevance_weights = ""
    bot_memory_per_category_max = 1
    bot_memory_semantic_recall_enabled = True
    bot_reflection_enabled = False  # 本锁只管总线腿，反思候选源另件已锁
    bot_reflection_db_path = ""


# ------------------------------------------------------------------ AST 判据（吃源码文本，毒形副本可直接喂）


def _is_call_to(node: ast.AST, name: str) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
    )


def gate_root_assembles(provider_source: str) -> bool:
    """链段 1：根文件把 build_character_context_provider 接进 build_chat_capability。

    首参必须是裸 ``config``（经包装件的副本走记忆缝=第二真身，判否）。
    """
    tree = ast.parse(provider_source)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id != "build_chat_capability":
            continue
        for kw in node.keywords:
            if kw.arg != "character_provider":
                continue
            value = kw.value
            if (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "build_character_context_provider"
                and value.args
            ):
                first = value.args[0]
                if isinstance(first, ast.Name) and first.id == "config":
                    return True
    return False


def gate_providers_seam(providers_source: str) -> bool:
    """链段 2a：装配缝唯一形态 ``memory_provider=build_memory_read_provider(config)``。"""
    tree = ast.parse(providers_source)
    fn = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "build_character_context_provider"
        ),
        None,
    )
    if fn is None:
        return False
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id != "FileCharacterContextProvider":
            continue
        for kw in node.keywords:
            if kw.arg == "memory_provider":
                return _is_call_to(kw.value, "build_memory_read_provider")
    return False


def gate_build_context_consumes(providers_source: str) -> bool:
    """链段 2b：``build_context`` 真调用 ``self.memory_provider.retrieve``。"""
    tree = ast.parse(providers_source)
    cls = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef)
            and node.name == "FileCharacterContextProvider"
        ),
        None,
    )
    if cls is None:
        return False
    for fn in cls.body:
        if not (isinstance(fn, ast.FunctionDef) and fn.name == "build_context"):
            continue
        for node in ast.walk(fn):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "retrieve"
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "memory_provider"
                and isinstance(node.func.value.value, ast.Name)
                and node.func.value.value.id == "self"
            ):
                return True
    return False


def gate_chat_renders(chat_source: str) -> bool:
    """链段 3：``context.memory_results.facts`` 为真才渲染【记忆】分区。"""
    tree = ast.parse(chat_source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        chain_ok = (
            isinstance(test, ast.Attribute)
            and test.attr == "facts"
            and isinstance(test.value, ast.Attribute)
            and test.value.attr == "memory_results"
            and isinstance(test.value.value, ast.Name)
            and test.value.value.id == "context"
        )
        if chain_ok and any(
            isinstance(child, ast.Constant) and child.value == "【记忆】"
            for child in ast.walk(node)
        ):
            return True
    return False


# ------------------------------------------------------------------ 链三段：真源码必须绿


def test_message_chain_assembles_and_consumes_memory_bus() -> None:
    assert gate_root_assembles(ROOT_INIT.read_text(encoding="utf-8")), (
        "根装配段断了：build_chat_capability 不再把 build_character_context_provider(config,…) "
        "接到 character_provider 上——开关置 true 也不会有总线进消息链"
    )
    providers_source = PROVIDERS_PY.read_text(encoding="utf-8")
    assert gate_providers_seam(providers_source), (
        "装配缝断了：build_character_context_provider 的 memory_provider 不再"
        "=build_memory_read_provider(config)"
    )
    assert gate_build_context_consumes(providers_source), (
        "消费腿断了：build_context 不再调用 self.memory_provider.retrieve"
    )
    assert gate_chat_renders(CHAT_PY.read_text(encoding="utf-8")), (
        "渲染腿断了：chat.py 的【记忆】分区不再由 context.memory_results.facts 驱动"
    )


# ------------------------------------------------------------------ 杀伤力自证：合成毒形必红
#
# 注毒台守则的执行形态：本席**禁改生产文件**（根 __init__.py 另一路在写），
# 故毒全部下在 tmp 拷贝上——判据函数吃 source 文本的设计就是为此。
# 每发毒先断言锚点唯一（count==1），不唯一即抛，绝不在歧义锚上注毒。


def _poison_copy(source: str, anchor: str, replacement: str) -> str:
    assert source.count(anchor) == 1, f"注毒锚点不唯一：{anchor!r}"
    return source.replace(anchor, replacement)


def test_kill_power_root_seam_detached(tmp_path: Path) -> None:
    source = ROOT_INIT.read_text(encoding="utf-8")
    poisoned = _poison_copy(
        source,
        "character_provider=build_character_context_provider(",
        "character_provider=_seat_detached_for_poison(",
    )
    poisoned_path = tmp_path / "init_poisoned.py"
    poisoned_path.write_text(poisoned, encoding="utf-8")
    assert not gate_root_assembles(poisoned_path.read_text(encoding="utf-8")), (
        "毒形（摘根装配）没打红判据=锁是纸糊的"
    )


def test_kill_power_providers_seam_detached(tmp_path: Path) -> None:
    source = PROVIDERS_PY.read_text(encoding="utf-8")
    poisoned = _poison_copy(
        source,
        "memory_provider=build_memory_read_provider(config),",
        "memory_provider=NullMemoryProvider(),",
    )
    path = tmp_path / "providers_poisoned.py"
    path.write_text(poisoned, encoding="utf-8")
    assert not gate_providers_seam(path.read_text(encoding="utf-8"))


def test_kill_power_consumer_detached(tmp_path: Path) -> None:
    source = PROVIDERS_PY.read_text(encoding="utf-8")
    poisoned = _poison_copy(
        source,
        "self.memory_provider.retrieve(",
        "NullMemoryProvider().retrieve(",
    )
    path = tmp_path / "providers_poisoned2.py"
    path.write_text(poisoned, encoding="utf-8")
    assert not gate_build_context_consumes(path.read_text(encoding="utf-8"))


def test_kill_power_render_detached(tmp_path: Path) -> None:
    source = CHAT_PY.read_text(encoding="utf-8")
    poisoned = _poison_copy(source, '"【记忆】"', '"【记忆-断链】"')
    path = tmp_path / "chat_poisoned.py"
    path.write_text(poisoned, encoding="utf-8")
    assert not gate_chat_renders(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ 行为两态：开关真的活着


def _seed_and_retrieve(tmp_path: Path, *, bus_on: bool):
    config = Cfg()
    config.bot_memory_db_path = str(tmp_path / f"memory-{'on' if bus_on else 'off'}.sqlite3")
    config.bot_memory_bus_enabled = bus_on
    provider = build_memory_read_provider(config)
    if bus_on:
        bus = getattr(provider, "_audit_bus", None)
        assert bus is not None, "开态装配必须挂上总线（降级审计都无处落）"
        outcome = bus.absorb(
            owner_id="u1",
            subject_user_id="u1",
            text=MEMORY_TEXT,
            session_id=GROUP_A,
            category="preference",
        )
        assert outcome.action in {"inserted", "confirmed"}, outcome
    result = provider.retrieve(
        request_id="r1",
        requester_id="u1",
        subject_user_id="u1",
        session_id=GROUP_A,
        query_text="柠檬茶",
        max_items=5,
        max_chars=1200,
    )
    return config, provider, result


def test_switch_on_routes_through_bus_and_writes_audit(tmp_path: Path) -> None:
    config, provider, result = _seed_and_retrieve(tmp_path, bus_on=True)
    assert str(getattr(provider, "recall_mode", "")) == "memory_bus"
    texts = [str(fact.get("text", "")) for fact in result.facts]
    assert MEMORY_TEXT in texts, "开态：总线行必须经 retrieve() 回到消息链"
    with sqlite3.connect(config.bot_memory_db_path) as conn:
        audits = int(
            conn.execute(
                "SELECT COUNT(*) FROM memory_recall_audit_v21"
            ).fetchone()[0]
        )
    assert audits >= 1, "审计行是『召回真走了总线打分器』的实锤，缺它=路径没跑过"


def test_switch_off_same_row_is_not_recalled(tmp_path: Path) -> None:
    """同一份数据两态可判别 ⇒ 开关不是装饰。

    先在开态把行吸进总线，再拿同库走关态装配：旧腿只读 ``memory_facts``，
    总线行必须召不回，且 recall_mode 变旧口径。
    """
    seed_config = Cfg()
    seed_config.bot_memory_db_path = str(tmp_path / "memory-shared.sqlite3")
    from plugins.bot_unified_runtime.domains.chat_reply.character.memory_bus_v2 import (
        build_memory_bus,
    )

    bus = build_memory_bus(seed_config)
    assert bus is not None
    bus.absorb(
        owner_id="u1",
        subject_user_id="u1",
        text=MEMORY_TEXT,
        session_id=GROUP_A,
        category="preference",
    )

    off = Cfg()
    off.bot_memory_db_path = seed_config.bot_memory_db_path
    off.bot_memory_bus_enabled = False
    provider = build_memory_read_provider(off)
    assert str(getattr(provider, "recall_mode", "")) == "legacy_newest_n"
    result = provider.retrieve(
        request_id="r2",
        requester_id="u1",
        subject_user_id="u1",
        session_id=GROUP_A,
        query_text="柠檬茶",
        max_items=5,
        max_chars=1200,
    )
    texts = [str(fact.get("text", "")) for fact in result.facts]
    assert MEMORY_TEXT not in texts, "关态读到总线行=两真身并读，开关失守"


def test_build_context_end_to_end_reaches_memory(tmp_path: Path) -> None:
    """E2E 半程：经 FileCharacterContextProvider.build_context 消费腿拿到记忆。

    刻意不整链 import 根模块（NoneBot 装配面在离线测试里不可构造），
    用与根:5055 同一形状的构造参数接线（memory_provider=build_memory_read_provider(config)），
    根装配那一跳由 gate_root_assembles 的 AST 锁负责——两半合起来是全链。
    """
    config, _provider, _result = _seed_and_retrieve(tmp_path, bus_on=True)
    context_provider = FileCharacterContextProvider(
        persona_profile_id="test",
        persona_display_name="测试",
        persona_version="0",
        persona_files=[],
        knowledge_files=[],
        memory_provider=build_memory_read_provider(config),
        memory_max_items=config.bot_memory_max_items,
        memory_max_chars=config.bot_memory_max_chars,
    )
    bundle = context_provider.build_context(
        request_id="r3",
        sender_id="u1",
        session_id=GROUP_A,
        query_text="柠檬茶",
    )
    texts = [str(fact.get("text", "")) for fact in bundle.memory_results.facts]
    # build_context 出口比裸 retrieve 多一道 kind 标签渲染（【爱好与偏好】前缀），
    # 所以这里断**子串在场**——锁的是"记忆进了 bundle"，不是渲染措辞。
    assert any(MEMORY_TEXT in text for text in texts), (
        "build_context 没把记忆带进 bundle——消费腿断了"
    )


# ------------------------------------------------------------------ 取数口绊线（§1 的常驻形态）


def test_no_bare_override_port_reads_memory_keys() -> None:
    """全 plugins 树禁 ``get_or("BOT_MEMORY…")``——ACG 病灶（覆盖册独读）不得进记忆族。

    合法形态只有两种：getattr(config,…)（口 A）或 get_or(key, getattr(config,…))
    （口 B 带 Config 兜底）；后者在文本上不含 ``get_or("BOT_MEMORY``，本锁抓的是
    「把键名硬写进 get_or 第一参且没有 Config 兜底可见」的回潮形态。
    """
    pattern = re.compile(r"get_or\(\s*[\"']BOT_MEMORY")
    offenders: list[str] = []
    for path in PLUGINS_DIR.rglob("*.py"):
        if pattern.search(path.read_text(encoding="utf-8", errors="replace")):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        f"记忆键被裸覆盖册口读取（.env 永远到不了判据）：{offenders}"
    )


def _extract_setting_defaults_consult_config(source: str) -> bool:
    """根 ``setting("BOT_MEMORY_EXTRACT_*", <缺省>)`` 的缺省侧必须现读 config。"""
    tree = ast.parse(source)
    seen = 0
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id != "setting" or not node.args:
            continue
        key = node.args[0]
        if not (
            isinstance(key, ast.Constant)
            and isinstance(key.value, str)
            and key.value.startswith("BOT_MEMORY_EXTRACT")
        ):
            continue
        seen += 1
        if len(node.args) < 2:
            return False
        default = ast.unparse(node.args[1])
        if "config." not in default and "getattr(config" not in default:
            return False
    # 兜一条存在性：四枚读点必须都还在（拆了读点=热改面整体蒸发，同样要红）
    return seen > 0


def test_extract_family_default_side_is_config() -> None:
    source = ROOT_INIT.read_text(encoding="utf-8")
    assert _extract_setting_defaults_consult_config(source), (
        "BOT_MEMORY_EXTRACT_* 的缺省侧不再现读 config ⇒ 退化为『覆盖册独读』，"
        ".env 的值到不了判据（第 3 项 ACG 腿同型病灶）"
    )


def test_extract_family_kill_power(tmp_path: Path) -> None:
    source = ROOT_INIT.read_text(encoding="utf-8")
    anchor = '"BOT_MEMORY_EXTRACT_ENABLED", config.bot_memory_extract_enabled'
    poisoned = _poison_copy(source, anchor, '"BOT_MEMORY_EXTRACT_ENABLED", False')
    path = tmp_path / "root_poisoned.py"
    path.write_text(poisoned, encoding="utf-8")
    assert not _extract_setting_defaults_consult_config(path.read_text(encoding="utf-8"))


def _production_call_sites(symbol: str, defining_file: Path) -> list[str]:
    """plugins/scripts 面找 ``symbol(`` 调用点（排除定义文件自身与测试）。"""
    hits: list[str] = []
    roots = [PLUGINS_DIR, REPO_ROOT / "scripts"]
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if path.resolve() == defining_file.resolve():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for index, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if f"{symbol}(" in stripped and f"def {symbol}(" not in stripped:
                    hits.append(f"{path.relative_to(REPO_ROOT)}:{index}")
    return hits


def test_semantic_recall_leg_still_unwired_tripwire() -> None:
    """K4-1 绊线：``semantic_scorer`` 生产注入点今日为零。

    接线是允许的未来（推荐 A 接向量侧打分器），但**接线必翻叙述**——AGENTS/台账/HANDBOOK
    里「在册未执法」那句必须同笔改口并带实跑证据，之后才准把本锁改为正向锁。
    静默删本用例=违禁（只准收紧纪律）。
    """
    defining = (
        REPO_ROOT
        / "plugins"
        / "bot_unified_runtime"
        / "domains"
        / "chat_reply"
        / "character"
        / "memory_bus_v2.py"
    )
    offenders: list[str] = []
    for root in (PLUGINS_DIR, REPO_ROOT / "scripts"):
        for path in root.rglob("*.py"):
            if path.resolve() == defining.resolve():
                continue
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                    continue
                if node.func.id != "build_memory_bus":
                    continue
                for kw in node.keywords:
                    if kw.arg == "semantic_scorer" and not (
                        isinstance(kw.value, ast.Constant) and kw.value.value is None
                    ):
                        offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        f"semantic_scorer 出现生产注入点 {offenders}：K4-1 状态已变，"
        "必须同笔更新叙述口径与台账后改本锁，不接受静默放行"
    )


def test_media_absorb_leg_still_unassembled_tripwire() -> None:
    """§1.4 第二例绊线：媒体摘要→总线写腿（absorb_preprocessed_summary）零装配。

    与上一锁同一教义：接线合法，但必须同笔翻 §5 两态表并留证据。
    """
    defining = (
        REPO_ROOT
        / "plugins"
        / "bot_unified_runtime"
        / "domains"
        / "vision"
        / "capabilities"
        / "modality_preprocessing.py"
    )
    hits = _production_call_sites("absorb_preprocessed_summary", defining)
    assert not hits, (
        f"absorb_preprocessed_summary 出现生产调用点 {hits}：§5 两态表该格要同笔改"
    )
