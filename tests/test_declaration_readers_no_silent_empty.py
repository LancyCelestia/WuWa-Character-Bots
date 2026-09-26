"""CM-P-9（S44 席）：三支按路径读声明源的脚本 = 追再导出 + 塌陷锁 的三腿锁件.

覆盖对象（只测「眼睛」，不动任何账）：
  ① ``scripts/channel_capability_declaration.py``（tags 真身读取口）
  ② ``scripts/configure_axonhub_registry.py``（经①取数 + 自己的空判据闸）
  ③ ``scripts/capability_manifest_projection_check.py``（load/module_exports/表塌陷锁）

每支三腿：真身现读非空 / 合成"再导出壳"仍解析得出 / 空表必抛。
合成壳一律在 ``tmp_path`` 造源码，**绝不改真树**。

起点基线（本席 2026-09-24 现算，写死在注释、断言只设地板，防"起点==实测判未做"）：
  ① 1 entry（axon-gemini-38-flash）/ 3 kinds（animation,audio,video）/ 前缀 "native-"
  ② AXONHUB_ROUTES 17 + DEEPSEEK_FALLBACK 1；build_registry 17 条、tags 共 50 枚；闸问题 0
  ③ 五表 35/20/78/43/3；module_exports registry=11 taxonomy=7 tags=10；row_count=120；
     diffs=1216；FACETS 13；EVIDENCE 1；UNCOVERED_CEILING 107
改前/改后上述计数逐一对齐的实跑证据在 SEAT-S44.md（本席只修眼睛不动账）。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from scripts import capability_manifest_projection_check as s3
from scripts import configure_axonhub_registry as s2
from scripts.channel_capability_declaration import declaration_path, load_declaration

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------- 合成夹具


_REAL_TAGS = '''"""合成真身册（字面量族全形态覆盖）."""
from types import MappingProxyType

NATIVE_TAG_PREFIX = "native-"
NATIVE_MEDIA_KINDS: tuple[str, ...] = ("animation", "audio", "video")
CHANNEL_CAPABILITY_KINDS = MappingProxyType({
    "axon-gemini-38-flash": ("animation", "audio", "video"),
})
'''


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _tags_layout(tmp_path: Path, shell_body: str | None, real_body: str = _REAL_TAGS) -> Path:
    """造一个假仓库根：tags 位文件 +（可选）它所再导出的合成册，返回 project_root."""
    core = tmp_path / "plugins" / "bot_unified_runtime" / "domains" / "core"
    if shell_body is None:
        _write(core / "channel_capability_tags.py", real_body)
    else:
        _write(core / "manifest_fx.py", real_body)
        _write(core / "channel_capability_tags.py", shell_body)
    return tmp_path


_SHELL_EXPLICIT = '''"""合成薄壳：P2 迁移后的再导出形态（from X import Y as Y + __all__）."""
from .manifest_fx import (
    CHANNEL_CAPABILITY_KINDS as CHANNEL_CAPABILITY_KINDS,
    NATIVE_MEDIA_KINDS as NATIVE_MEDIA_KINDS,
    NATIVE_TAG_PREFIX as NATIVE_TAG_PREFIX,
)

__all__ = [
    "CHANNEL_CAPABILITY_KINDS",
    "NATIVE_MEDIA_KINDS",
    "NATIVE_TAG_PREFIX",
]
'''

_SHELL_STAR = '''"""合成薄壳：星号再导出形态."""
from .manifest_fx import *  # noqa: F401,F403
'''


# ================================================================ ① S1 三腿


def test_s1_real_declaration_nonempty():
    """腿①：真身现读非空（起点：1 entry / 3 kinds / 前缀非空）."""
    view = load_declaration(PROJECT_ROOT)
    assert len(view.declared_entry_ids()) >= 1          # 起点=1
    assert len(view.known_kinds) >= 3                    # 起点=3
    assert view.native_prefix.strip() == view.native_prefix and view.native_prefix
    assert any(view.required_tags_for(e) for e in view.declared_entry_ids())


@pytest.mark.parametrize("shell_body", (_SHELL_EXPLICIT, _SHELL_STAR), ids=["alias-as", "star"])
def test_s1_follows_reexport_shell(tmp_path: Path, shell_body: str):
    """腿②：tags 文件降为再导出壳（两种形态）⇒ 顺链到真身后照旧取值."""
    root = _tags_layout(tmp_path, shell_body)
    view = load_declaration(root)
    assert view.declared_entry_ids() == ("axon-gemini-38-flash",)
    assert view.known_kinds == ("animation", "audio", "video")
    assert view.native_prefix == "native-"
    assert view.required_tags_for("axon-gemini-38-flash") == (
        "native-animation", "native-audio", "native-video")


def test_s1_two_hop_shell(tmp_path: Path):
    """腿②续：壳→壳→真身两跳链也要追得通（P2 不保证只有一层壳）."""
    middle = '''from .manifest_fx import (
    CHANNEL_CAPABILITY_KINDS as CHANNEL_CAPABILITY_KINDS,
    NATIVE_MEDIA_KINDS as NATIVE_MEDIA_KINDS,
    NATIVE_TAG_PREFIX as NATIVE_TAG_PREFIX,
)
'''
    outer = '''from .middle_fx import (
    CHANNEL_CAPABILITY_KINDS as CHANNEL_CAPABILITY_KINDS,
    NATIVE_MEDIA_KINDS as NATIVE_MEDIA_KINDS,
    NATIVE_TAG_PREFIX as NATIVE_TAG_PREFIX,
)
'''
    root = _tags_layout(tmp_path, outer)
    _write(root / "plugins/bot_unified_runtime/domains/core/middle_fx.py", middle)
    view = load_declaration(root)
    assert view.known_kinds == ("animation", "audio", "video")


@pytest.mark.parametrize("broken", (
    '''NATIVE_TAG_PREFIX = "native-"
NATIVE_MEDIA_KINDS: tuple[str, ...] = ("animation", "audio", "video")
CHANNEL_CAPABILITY_KINDS: dict[str, tuple[str, ...]] = {}
''',
    '''NATIVE_TAG_PREFIX = "native-"
NATIVE_MEDIA_KINDS: tuple[str, ...] = ()
CHANNEL_CAPABILITY_KINDS: dict[str, tuple[str, ...]] = {"a": ("audio",)}
''',
    '''NATIVE_TAG_PREFIX = ""
NATIVE_MEDIA_KINDS: tuple[str, ...] = ("audio",)
CHANNEL_CAPABILITY_KINDS: dict[str, tuple[str, ...]] = {"a": ("audio",)}
''',
), ids=["empty-kinds-table", "empty-known-kinds", "empty-prefix"])
def test_s1_empty_table_raises(tmp_path: Path, broken: str):
    """腿③：三枚常量任一读成空 ⇒ 当场抛、点名表名（禁"空=默认绿"）."""
    root = _tags_layout(tmp_path, None, real_body=broken)
    with pytest.raises(ValueError, match="(为空|塌陷锁)"):
        load_declaration(root)


def test_s1_shell_over_empty_real_raises(tmp_path: Path):
    """腿③续：壳→真身链通、但真身表是空的 ⇒ 一样必抛（壳读壳那一形）."""
    broken = '''NATIVE_TAG_PREFIX = "native-"
NATIVE_MEDIA_KINDS: tuple[str, ...] = ("animation", "audio", "video")
CHANNEL_CAPABILITY_KINDS: dict[str, tuple[str, ...]] = {}
'''
    root = _tags_layout(tmp_path, _SHELL_EXPLICIT, real_body=broken)
    with pytest.raises(ValueError, match="CHANNEL_CAPABILITY_KINDS"):
        load_declaration(root)


def test_s1_unresolvable_reexport_raises(tmp_path: Path):
    """腿③边：再导出目标在仓内不存在 ⇒ 点名抛，绝不落回"缺常量=空视图"."""
    shell = '''from .nowhere_fx import (
    CHANNEL_CAPABILITY_KINDS as CHANNEL_CAPABILITY_KINDS,
    NATIVE_MEDIA_KINDS as NATIVE_MEDIA_KINDS,
    NATIVE_TAG_PREFIX as NATIVE_TAG_PREFIX,
)
'''
    root = _tags_layout(tmp_path, shell)
    with pytest.raises(ValueError, match="真身"):
        load_declaration(root)


def test_s1_circular_reexport_raises(tmp_path: Path):
    """腿③边：互相再导出的环 ⇒ 停手点名，不静默耗尽栈."""
    a = '''from .tags_b import (
    CHANNEL_CAPABILITY_KINDS as CHANNEL_CAPABILITY_KINDS,
    NATIVE_MEDIA_KINDS as NATIVE_MEDIA_KINDS,
    NATIVE_TAG_PREFIX as NATIVE_TAG_PREFIX,
)
'''
    b = '''from .channel_capability_tags import (
    CHANNEL_CAPABILITY_KINDS as CHANNEL_CAPABILITY_KINDS,
    NATIVE_MEDIA_KINDS as NATIVE_MEDIA_KINDS,
    NATIVE_TAG_PREFIX as NATIVE_TAG_PREFIX,
)
'''
    core = tmp_path / "plugins" / "bot_unified_runtime" / "domains" / "core"
    _write(core / "channel_capability_tags.py", a)
    _write(core / "tags_b.py", b)
    with pytest.raises(ValueError, match="(循环|绕回)"):
        load_declaration(tmp_path)


# ================================================================ ② S2 三腿


def test_s2_registry_tags_flow_from_declaration():
    """腿①：写回装配的 tags 里能力标签来自声明源（起点：17 条路由、50 枚 tags、闸 0 问题）."""
    registry = s2.build_registry()
    assert len(registry) == len(s2.AXONHUB_ROUTES) >= 17          # 起点=17
    assert sum(len(entry["tags"]) for entry in registry.values()) >= 50  # 起点=50
    declared_native = [t for t in registry["axon-gemini-38-flash"]["tags"] if t.startswith("native-")]
    assert len(declared_native) >= 3                              # 起点=3
    assert s2.capability_guard_problems(registry) == []


def test_s2_reads_declaration_through_shell(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """腿②：本席不抄第二套解析——tags_for/闸经由①的追链，壳形态下照常合成能力标签."""
    root = _tags_layout(tmp_path, _SHELL_EXPLICIT)
    monkeypatch.setattr(s2, "REPO", root)
    tags = s2.tags_for("axon-gemini-38-flash", ["low"])
    assert {"native-animation", "native-audio", "native-video"} <= set(tags)
    assert s2.capability_guard_problems(s2.build_registry()) == []


def test_s2_vacuous_guard_raises_not_empty_list(tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch):
    """腿③：表有行但所有行零必带标签 ⇒ 闸失去判据 = DeclarationBlindError，**不是**返回 []."""
    vacuous = '''NATIVE_TAG_PREFIX = "native-"
NATIVE_MEDIA_KINDS: tuple[str, ...] = ("animation", "audio", "video")
CHANNEL_CAPABILITY_KINDS: dict[str, tuple[str, ...]] = {"axon-gemini-38-flash": ()}
'''
    root = _tags_layout(tmp_path, None, real_body=vacuous)
    monkeypatch.setattr(s2, "REPO", root)
    with pytest.raises(s2.DeclarationBlindError, match="塌陷锁"):
        s2.capability_guard_problems({"axon-gemini-38-flash": {"tags": ["low"]}})


def test_s2_empty_table_raises_via_shared_reader(tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch):
    """腿③续：空表形态由①的塌陷锁接住（S2 不自建第二把锁、也绝不静默放行）."""
    broken = '''NATIVE_TAG_PREFIX = "native-"
NATIVE_MEDIA_KINDS: tuple[str, ...] = ("animation", "audio", "video")
CHANNEL_CAPABILITY_KINDS: dict[str, tuple[str, ...]] = {}
'''
    root = _tags_layout(tmp_path, None, real_body=broken)
    monkeypatch.setattr(s2, "REPO", root)
    with pytest.raises(ValueError, match="塌陷锁"):
        s2.capability_guard_problems({"axon-gemini-38-flash": {"tags": ["low"]}})


# ================================================================ ③ S3 三腿


def test_s3_module_exports_real_ledgers_nonempty():
    """腿①：三处旧账的公开导出面现读非空（起点 11/7/10 枚）."""
    floors = {"capability_registry": 11, "board_taxonomy": 7, "channel_capability_tags": 10}
    for key, path in s3.LEGACY_LEDGERS.items():
        surface = s3.module_exports(path)
        assert len(surface) >= floors[key], (key, len(surface))


def test_s3_full_run_rows_and_tables(tmp_path: Path):
    """腿①续：全量 run() 通读（改前该路径直接 TypeError 崩在盘上——本席根修归因见 SEAT-S44）."""
    payload, code = s3.run(None)
    assert payload["row_count"] >= 120                     # 起点=120
    assert len(payload["diffs"]) >= 1000                   # 起点=1216（等值证据在席报告）
    assert payload["manifest_side"]["facet_ids"], payload["manifest_side"]
    assert payload["manifest_side"]["placeholder"] == []   # 合法可空（在册名册今日为空）
    assert code in (0, 2)


@pytest.mark.parametrize("shape", ("alias-as", "star"), ids=("alias-as", "star"))
def test_s3_load_module_follows_reexport(tmp_path: Path, shape: str):
    """腿②：注册册降为薄壳后，load_module 顺链充实常量表 ⇒ 读点不再 KeyError/读空."""
    real = '''"""合成册."""
CAPABILITY_FX_TABLE = ("row-one", "row-two")
_FX_HIDDEN = ("private-name",)
'''
    core = tmp_path / "pkg"
    _write(core / "manifest_fx.py", real)
    shell = ('from .manifest_fx import CAPABILITY_FX_TABLE as CAPABILITY_FX_TABLE\n'
             if shape == "alias-as" else 'from .manifest_fx import *\n')
    shell_path = _write(core / "registry_fx.py", shell)
    facts = s3.load_module(shell_path, s3.Ctx())
    assert "CAPABILITY_FX_TABLE" in facts.consts
    value = ast.literal_eval(facts.consts["CAPABILITY_FX_TABLE"])
    assert value == ["row-one", "row-two"] or value == ("row-one", "row-two")
    assert facts.reexport_origin.get("CAPABILITY_FX_TABLE")
    exports = s3.module_exports(shell_path)
    assert "CAPABILITY_FX_TABLE" in exports
    if shape == "star":
        assert "_FX_HIDDEN" not in exports  # 星号面只并公开名（下划线名不进）


def test_s3_registry_table_collapse_locks(tmp_path: Path):
    """腿③：五表缺名/零行 ⇒ SystemExit 点名文件与表名（绝不交空表给下游派生）."""
    empty_mod = _write(tmp_path / "registry_empty.py", '"""壳占位."""\n')
    ctx = s3.Ctx()
    facts = s3.load_module(empty_mod, ctx)
    evaluator = s3.Evaluator({"r": facts}, ctx)
    with pytest.raises(SystemExit) as caught:
        s3.read_registry_tables(facts, evaluator)
    assert "ROUTE_CAPABILITY_DECLARATIONS" in str(caught.value)

    zero_mod = _write(tmp_path / "pkg2" / "registry_zero.py",
                      'ROUTE_CAPABILITY_DECLARATIONS: tuple[str, ...] = ()\n')
    facts2 = s3.load_module(zero_mod, s3.Ctx())
    evaluator2 = s3.Evaluator({"r": facts2}, s3.Ctx())
    with pytest.raises(SystemExit) as caught2:
        s3.read_registry_tables(facts2, evaluator2)
    assert "零行" in str(caught2.value) and "ROUTE_CAPABILITY_DECLARATIONS" in str(caught2.value)

    # 壳→册链通的零行：壳 import 空表 ⇒ 追到手仍是零行 ⇒ 必抛（追再导出不放宽塌陷锁）
    real = _write(tmp_path / "pkg2" / "manifest_fx.py",
                  'ROUTE_CAPABILITY_DECLARATIONS: tuple[str, ...] = ()\n')
    shell = _write(tmp_path / "pkg2" / "registry_shell.py",
                   'from .manifest_fx import ROUTE_CAPABILITY_DECLARATIONS '
                   'as ROUTE_CAPABILITY_DECLARATIONS\n')
    facts3 = s3.load_module(shell, s3.Ctx())
    assert "ROUTE_CAPABILITY_DECLARATIONS" in facts3.consts          # 链通了
    with pytest.raises(SystemExit) as caught3:                        # 但空表照抛
        s3.read_registry_tables(facts3, s3.Evaluator({"r": facts3}, s3.Ctx()))
    assert "零行" in str(caught3.value)
    assert real.is_file()


def test_s3_module_exports_unreadable_and_empty_raise(tmp_path: Path):
    """腿③续：读不出≠没有导出（旧版静默返回空集那一形已根修）；空面必抛."""
    with pytest.raises(SystemExit, match="FATAL"):
        s3.module_exports(tmp_path / "不存在的文件.py")
    shell_only_private = _write(tmp_path / "pkg3" / "shell_priv.py",
                                'from .real_fx import _hidden as _hidden\n')
    _write(tmp_path / "pkg3" / "real_fx.py", '_hidden: tuple[str, ...] = ("x",)\n')
    with pytest.raises(SystemExit, match="导出面为空"):
        s3.module_exports(shell_only_private)


def test_s3_manifest_side_unresolved_raises_not_empty(tmp_path: Path):
    """腿③边：册侧四件求不出 ⇒ 点名抛；旧版把求不出降级成 []/{}（本席接手实测 placeholder=[]）."""
    manifest = _write(tmp_path / "pkg4" / "manifest.py", '''"""合成册."""
FACETS: dict[str, str] = {"bot.fx": "row"}
EVIDENCE: dict[str, str] = {}
UNCOVERED_CEILING: int = 7
PLACEHOLDER_UNIMPLEMENTED = unknown_runtime_call("x")
''')
    ctx = s3.Ctx()
    facts = s3.load_module(manifest, ctx)
    evaluator = s3.Evaluator({"m": facts}, ctx)
    with pytest.raises(SystemExit, match="PLACEHOLDER_UNIMPLEMENTED"):
        s3.read_manifest_side(facts, evaluator)


def test_s3_declaration_path_identity():
    """尺身份自检：①的读取口钉的是 tags 真身路径（改这条=改账，须走主代理）."""
    assert declaration_path(PROJECT_ROOT) == (
        PROJECT_ROOT / "plugins/bot_unified_runtime/domains/core/channel_capability_tags.py")
