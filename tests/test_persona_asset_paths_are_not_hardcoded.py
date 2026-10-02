"""S5 席（多人格隔离波 单元 1）：人格身份/路径禁写死在代码里。

立尺动机（现场取证，全部现算可复跑）：切到备用人格后，四处仍替**主人格**说话——

* ``vector_knowledge.py`` 的 persona 族判据是一枚硬编码人名字面量 ⇒ 新人格的正文
  进不了人格保留位、主人格 3.5 万块继续占槽（检索串味）。
* ``runtime/aliases.py`` 的策展昵称兜底**无条件**并入 ⇒ 非主人格没词表时被主人格的
  九名顶包（昵称门/表情主体判定/命令别名三条腿一起认错人）。
* ``character/glossary.py`` 的 ``SEED_GLOSSARY_PATH`` 把 ``personas/<主人格>/`` 写死。
* ``card_render/theme_tokens.py`` 的卡面中文署名此前只有品牌缺省一条腿。

同一族事故在册两次（台账 #66★「意象名词禁抄进代码」、#72★「接线 AST 锁须同认
``to_thread``/``run_in_executor``），所以本件照 #66 那把尺的写法：
**尺的判据来自注册表真身，不来自本文件手抄的名字**——注册表长一格，尺自动多咬一处；
名册空/读不出＝当场红（该尺自证不空跑），并配注毒腿。

离线纪律：不建库连接、不 import 生产 ``Config``、不写 ``personas/**``、``BOT_AUTOSYNC=0``。
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PKG = REPO_ROOT / "plugins" / "bot_unified_runtime"

# 扫描面＝单元 1 点名的四件真身。少一件＝尺没牙。
TARGETS: dict[str, Path] = {
    "vector_knowledge": PKG / "domains/chat_reply/character/vector_knowledge.py",
    "aliases": PKG / "domains/chat_reply/runtime/aliases.py",
    "glossary": PKG / "domains/chat_reply/character/glossary.py",
    "theme_tokens": PKG / "domains/render/card_render/theme_tokens.py",
}


def _registry_personas() -> dict[str, str]:
    """注册表真身：persona_id → display_name（尺的判据唯一来源）。"""
    from plugins.bot_unified_runtime.domains.chat_reply.character.persona_profile import (
        PersonaProfileRegistry,
    )

    registry = PersonaProfileRegistry()
    records = registry.all()
    assert records, "人格注册表读不出任何一格 ⇒ 这把尺是空跑的"
    mapping = {
        record.persona_id: record.display_name for record in records.values()
    }
    assert any(mapping.values()), "注册表全是空 display_name ⇒ 这把尺是空跑的"
    return mapping


def _string_constants(tree: ast.Module) -> list[tuple[int, str]]:
    """AST 里**作为代码**出现的字符串常量 `(行号, 值)`；docstring 不算。

    走 AST 而不是 grep：注释与 docstring 里讲历史事故必须提到旧名字，那是记账不是
    写死；只有进入字节码的常量才是第二真身。ast.walk 覆盖 def 体内、lambda 体内、
    ``asyncio.to_thread(...)`` / ``run_in_executor(...)`` 实参里的常量——台账 #72★
    点名的正是"接线腿把调用形式换了、按文本行的尺当场瞎掉"这一形态。
    """
    docstring_nodes: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            docstring_nodes.add(id(node.value))
    return [
        (int(node.lineno), node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstring_nodes
    ]


def _code_string_constants(path: Path) -> list[str]:
    return [value for _line, value in _string_constants(_tree(path))]


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _exempt_ranges(path: Path, binding: str) -> list[tuple[int, int]]:
    """取模块级 `binding = ...` 赋值的行区间（登记在册的"人格数据本体"位）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    ranges: list[tuple[int, int]] = []
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        names = {
            t.id for t in targets if isinstance(t, ast.Name)
        }
        if binding in names:
            ranges.append((int(node.lineno), int(node.end_lineno or node.lineno)))
    return ranges


# 在册豁免：**只当数据、不参与任何判定**的人格本体常量，按 (文件, 绑定名) 逐条登记。
#   * aliases.DEFAULT_PERSONA_NICKNAMES＝主人格 aliases.txt 的同内容副本，
#     与文件逐字相等由 tests/test_nickname_default_seed.py 钉住，且**是否入场**
#     已由 _curated_fallback_applies 按人格判（见本件行为锁）。
#   * theme_tokens.BRAND_THEME＝渲染契约哈希册钉住的品牌缺省 token；人格腿是
#     brand_display_name_for/brand_theme_for（本件另有一把行为锁）。
# 豁免只放行"这一行区间里的常量"，不许放行整件文件；登记的名字若在盘上消失＝当场红
# （台账 #72★「缺席哨兵入库后空转」同族：哨兵必须自己带牙）。
CURATED_DATA_BINDINGS: dict[str, str] = {
    "aliases": "DEFAULT_PERSONA_NICKNAMES",
    "theme_tokens": "BRAND_THEME",
}


def test_no_persona_identity_is_hardcoded_in_code() -> None:
    """四件真身里，除**在册豁免的"人格数据本体"绑定**外，一枚都不许写死人格身份。"""
    identities = set()
    for persona_id, display_name in _registry_personas().items():
        identities.add(persona_id)
        if display_name:
            identities.add(display_name)
    offenders: list[str] = []
    for name, path in TARGETS.items():
        assert path.is_file(), f"扫描面对不上真身：{name} -> {path}"
        exempt = _exempt_ranges(path, CURATED_DATA_BINDINGS.get(name, ""))
        if name in CURATED_DATA_BINDINGS:
            assert exempt, f"{name}.py 的豁免绑定 {CURATED_DATA_BINDINGS[name]} 已不在盘上"
        for line, text_value in _string_constants(_tree(path)):
            if any(start <= line <= end for start, end in exempt):
                continue
            text = text_value.strip()
            if text in identities:
                offenders.append(f"{name}.py:{line}: {text!r}")
                continue
            # 路径形态单独判：`personas/<某格>/…` 整条拼死在代码里。
            for identity in identities:
                if identity and f"personas/{identity}/" in text.replace("\\", "/"):
                    offenders.append(f"{name}.py:{line}: {text!r}")
                    break
    assert not offenders, "人格身份被写死在代码里（切人格时它不跟）：\n" + "\n".join(
        sorted(set(offenders))
    )


def test_poisoned_persona_path_and_name_are_both_caught(tmp_path: Path) -> None:
    """注毒腿：摘干净判据尺必须红——合成一件"写死主人格路径 + 写死人格名"的件。"""
    identities = set()
    for persona_id, display_name in _registry_personas().items():
        identities.add(persona_id)
        identities.add(display_name)
    sample = sorted(i for i in identities if i)[:2]
    bad = tmp_path / "bad_persona_asset.py"
    bad.write_text(
        "from pathlib import Path\n\n"
        f'_ROOT = Path("personas") / "{sample[0]}"\n'
        f'NAME = "{sample[1] if len(sample) > 1 else sample[0]}"\n'
        f'PATH = "personas/{sample[0]}/aliases.txt"\n',
        encoding="utf-8",
    )
    constants = _code_string_constants(bad)
    assert any(f"personas/{sample[0]}/" in c for c in constants), constants
    assert any(c.strip() in identities for c in constants), constants
    # 反向不误伤：docstring 里讲旧形态提到人格路径，不算写死（判据看代码不看散文）。
    good = tmp_path / "good_persona_asset.py"
    good.write_text(
        '"""历史记账：旧写法把 personas/'
        + sample[0]
        + '/ 写死过，本件改为按人格派生。"""\n\n'
        '_X = ""\n',
        encoding="utf-8",
    )
    assert not [c for c in _code_string_constants(good) if f"personas/{sample[0]}/" in c], (
        "docstring 被误当写死 ⇒ 尺会拦住记账文字，下一波只会把整条尺删掉"
    )


def test_persona_source_prefix_is_derived_not_a_literal() -> None:
    """检索侧 persona 族的前缀＝按人格派生的**集合**，旧的字面量常量必须已退役。"""
    import plugins.bot_unified_runtime.domains.chat_reply.character.vector_knowledge as vk

    assert not hasattr(vk, "_PERSONA_SOURCE_PREFIX"), (
        "字面量前缀常量还在 ⇒ 尺退化成空转"
    )
    prefixes = vk.persona_source_prefixes()
    assert isinstance(prefixes, frozenset) and prefixes, "派生前缀集合为空 ⇒ persona 族永不成族"
    main = vk.persona_source_prefixes()
    registry = _registry_personas()
    assert main & set(registry.keys()) or main & {
        v for v in registry.values() if v
    }, (main, registry)
    # 另一格必须拿到**另一套**前缀，且两套互不含（这才叫"跟人格外壳走"）。
    other = next((pid for pid in registry if registry[pid] not in main), "")
    assert other, "注册表只有一格 ⇒ 这条 A/B 腿没得判，尺需随册补格"
    other_prefixes = vk.persona_source_prefixes(other)
    assert other_prefixes and not (other_prefixes & main), (other_prefixes, main)
    # 族判定跟着换：新人格自己的正文归 persona 族，主人格的正文不再归。
    stem = f"{registry[other]}_核心知识"
    assert vk._source_family(stem, other_prefixes) == vk._PERSONA_FAMILY
    assert vk._source_family(stem, main) != vk._PERSONA_FAMILY
    # 册外人格不许借主人格的前缀（回落形态＝只认自己的 slug）。
    assert vk.persona_source_prefixes("ghost-not-in-register") == frozenset(
        {"ghost-not-in-register"}
    )


def test_glossary_seed_path_resolves_per_persona() -> None:
    """术语表种子按人格解析：没备料的那格＝申报缺席，绝不借主人格的表。"""
    import plugins.bot_unified_runtime.domains.chat_reply.character.glossary as gl
    from plugins.bot_unified_runtime.domains.chat_reply.character.persona_profile import (
        main_persona_id,
    )

    owner = main_persona_id()
    assert owner, "主格取不到 ⇒ 缺省路径无处派生"
    assert gl.seed_glossary_path(owner) == gl.SEED_GLOSSARY_PATH
    registry = _registry_personas()
    other = next((pid for pid in registry if pid != owner), "")
    assert other, "注册表只有一格 ⇒ A/B 腿没得判"
    path = gl.seed_glossary_path(other)
    assert path is not None and owner not in str(path.as_posix()), path
    assert str(path).replace("\\", "/").startswith(
        str(REPO_ROOT / "personas" / other).replace("\\", "/")
    ), path


class _StubConfig:
    """只带 persona 档的配置替身（不 import 生产 Config，台账 #66★）。"""

    def __init__(self, persona_id: str, **extra: object) -> None:
        self.bot_persona_profile_id = persona_id
        self.bot_persona_nicknames: list[str] = []
        self.bot_runtime_persona_nicknames: list[str] = []
        self.bot_glossary_files: list[str] = []
        for key, value in extra.items():
            setattr(self, key, value)

    def __getattr__(self, item: str) -> object:
        return None


def test_alias_fallback_does_not_borrow_the_main_persona() -> None:
    """非主人格缺词表＝申报缺席；主人格档保留出厂兜底（09-11 昵称无响应根修不许回退）。"""
    import plugins.bot_unified_runtime.domains.chat_reply.runtime.aliases as al
    from plugins.bot_unified_runtime.domains.chat_reply.character.persona_profile import (
        main_persona_id,
    )

    registry = _registry_personas()
    owner = main_persona_id()
    curated = set(al.DEFAULT_PERSONA_NICKNAMES)
    assert curated, "兜底表空 ⇒ 这把行为尺没得判"
    assert set(al.persona_alias_terms(_StubConfig(owner))) >= curated, (
        "主人格档丢了策展兜底 ⇒ 昵称无响应根修回退"
    )
    other = next((pid for pid in registry if pid != owner), "")
    assert other, "注册表只有一格 ⇒ A/B 腿没得判"
    terms = set(al.persona_alias_terms(_StubConfig(other)))
    assert not (terms & curated), f"{other} 借了主人格的策展昵称：{sorted(terms & curated)}"
    # 注毒腿：把兜底无条件并回来必须红——用 env 显式昵称证明口径只认"这一格自己的料"。
    named = al.persona_alias_terms(
        _StubConfig(other, bot_persona_nicknames=["只属于这格的称呼"])
    )
    assert named == ("只属于这格的称呼",), named


def test_card_identity_follows_the_active_persona() -> None:
    """卡面中文署名有**人格源**（品牌缺省只在该格查不到时兜底，不反过来）。"""
    import plugins.bot_unified_runtime.domains.render.card_render.theme_tokens as tt

    registry = _registry_personas()
    for persona_id, display_name in registry.items():
        if not display_name:
            continue
        assert tt.brand_display_name_for(persona_id) == display_name, persona_id
    other = next(
        (pid for pid, name in registry.items() if name and name != tt.BRAND_THEME.display_name),
        "",
    )
    assert other, "注册表里没有第二格中文名 ⇒ 派生腿无从现算"
    theme = tt.brand_theme_for(other)
    assert theme.display_name == registry[other]
    assert theme.accent == tt.BRAND_THEME.accent, "配色必须不随人格（产品视觉基线）"
    # 主人格档返回本体同一枚 ⇒ 既有渲染哈希逐字节不变。
    owner = next(
        pid for pid, name in registry.items() if name == tt.BRAND_THEME.display_name
    )
    assert tt.brand_theme_for(owner) is tt.BRAND_THEME
    assert tt.brand_theme_for("") is tt.BRAND_THEME
    assert tt.brand_theme_for(other) is not tt.BRAND_THEME


def test_new_lock_family_is_not_empty_running() -> None:
    """自锁：本件确实读到了注册表的两格以上，且四件真身都在盘上（防尺随重构静默瞎掉）。"""
    registry = _registry_personas()
    assert len(registry) >= 2, registry
    assert all(path.is_file() for path in TARGETS.values()), TARGETS
