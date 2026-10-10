"""生成触发词拼音映射草稿（触发规范化规格的候选材料）。

输入（程序化提取，零 import 副作用，纯 AST 静态解析）：
- domains/chat_reply/capabilities/echo.py 的 ``_HELP_ENTRIES`` 全部 aliases；
- runtime/base_router.py 引用的各 ``is_*`` 触发判定函数所在 capability 模块的词表
  （沿函数体 → 模块级常量 → re.compile 参数递归取字符串字面量）。

⚠ 真身位置（席 CMD-PINYIN-UNIFY，2026-10-08 修）：echo 早在 v21r2 RWC3 迁到
``domains/chat_reply/capabilities/``，本脚本的 ``ECHO_PATH`` 却还指着重构前的
``capabilities/echo.py``（那一格里如今只剩 ``__init__.py`` / ``content_parser.py``）
⇒ ``read_text()`` 当场 ``FileNotFoundError``、拼音候选表**今天根本生成不出来**。
同批第二个坑：``_HELP_ENTRIES`` 里有 **九簇** 词面不是字面量而是「在册纯投影」调用
（``nickname_verbs_for(...)`` × 7、``host_state_trigger_words()``、
``media_archive_trigger_words()``），对本文件自己 ``ast.literal_eval`` 必 ``ValueError``。
解法＝**复用 `scripts/command_catalog.py` 的取数口**（那里是这类投影的唯一在册实现，
`command_catalog.py:187` 明写「禁止在生成器里另抄一份投影逻辑」）——本脚本不自造第二把尺。

输出 JSON：
- mapping: {中文词: {"full": 全拼, "abbr": 首字母缩写(≤4位), "multi_tone_review"?, "abbr_truncated"?, "sources"}}
- conflicts: 缩写全表查重（中文↔中文、中文缩写↔英文触发词、全拼撞车）。

用法：
    python scripts/gen_trigger_pinyin.py             # 生成草稿 + 打印统计
    python scripts/gen_trigger_pinyin.py --selftest  # 已知多音字样例断言

设计裁定：触发词是闭集，运行时用静态映射表字面量（零运行时依赖）；本脚本只在
生成环节使用 pypinyin。生成结果是「候选」不是终稿，多音字打 flag 供人工审校。
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from pypinyin import Style, lazy_pinyin, pinyin

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "scripts") not in sys.path:  # 与 board_doc_sync/command_catalog 同形：同目录兄弟脚本直取
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

# 在册纯投影的唯一取数口（_HELP_ENTRIES 里 nickname_verbs_for 一类的 Call 只有它认）。
# 在本脚本里另写一份筛选逻辑＝造第二个事实源，command_catalog.py:187 已明文禁掉。
import command_catalog as cc
import doc_sync as ds  # 塌陷锁唯一真身（require_surface），不自造第二把「读空即抛」的尺

ECHO_PATH = cc.ECHO_SOURCE
BASE_ROUTER_PATH = REPO_ROOT / "plugins" / "bot_unified_runtime" / "domains" / "chat_reply" / "runtime" / "base_router.py"
DEFAULT_OUT = (
    REPO_ROOT
    / ".superpowers"
    / "sdd"
    / "2026-09-12-shorekeeper-global-audit"
    / "pinyin-mapping-draft.json"
)

ABBR_MAX_LEN = 4

# 多音字覆写表：pypinyin 逐字默认读音在二字词里翻错的，按「常见二字组合」人工纠偏。
# 例：裸 lazy_pinyin("重试") = ['zhong','shi']（错），词义为再次尝试 → chóng shì。
# 命中覆写的词同样打 multi_tone_review: true（审校时复核）。
MULTI_TONE_OVERRIDES: dict[str, tuple[str, ...]] = {
    "重试": ("chong", "shi"),
    "重发": ("chong", "fa"),
    "重连": ("chong", "lian"),
    "重启": ("chong", "qi"),
    "重置": ("chong", "zhi"),
    "重新": ("chong", "xin"),
}

_CJK_RANGES = (
    (0x4E00, 0x9FFF),
    (0x3400, 0x4DBF),
)


def _is_cjk_char(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


def contains_cjk(text: str) -> bool:
    return any(_is_cjk_char(ch) for ch in text)


def is_pure_cjk(text: str) -> bool:
    return bool(text) and all(_is_cjk_char(ch) for ch in text)


# ---------------------------------------------------------------------------
# 提取：AST 静态解析
# ---------------------------------------------------------------------------

def _literal_str_values(node: ast.AST, module_assigns: dict[str, ast.AST]) -> set[str]:
    """沿 AST 递归收集字符串字面量；Name 解引用到模块级赋值（带环保护）。

    跳过 ``match.group("xxx")`` / ``groupdict("xxx")`` 的参数——那是正则分组名，
    不是触发词。
    """
    found: set[str] = set()
    visited: set[int] = set()

    def walk(cur: ast.AST) -> None:
        if id(cur) in visited:
            return
        visited.add(id(cur))
        if isinstance(cur, ast.Constant) and isinstance(cur.value, str):
            found.add(cur.value)
            return
        if isinstance(cur, ast.Name):
            target = module_assigns.get(cur.id)
            if target is not None:
                walk(target)
            return
        if (
            isinstance(cur, ast.Call)
            and isinstance(cur.func, ast.Attribute)
            and cur.func.attr in {"group", "groupdict"}
        ):
            walk(cur.func)
            return
        for child in ast.iter_child_nodes(cur):
            walk(child)

    walk(node)
    return found


def _collect_module_assigns(tree: ast.Module) -> dict[str, ast.AST]:
    assigns: dict[str, ast.AST] = {}
    for stmt in tree.body:
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    assigns[target.id] = stmt.value
    return assigns


_REGEX_METACHARS = set("\\^$.*+?()[]{}|<>")


def split_trigger_tokens(raw: str) -> list[str]:
    """把词表字符串拆成干净触发词 token。

    is_* 词表常以正则形态出现（如 ``(股|大盘|大盤|指数)``、``提醒|叫我``），按
    ``|`` 拆分并剥掉首尾正则语法；含未剥离元字符的片段（``(?P<query>.*)`` 等）
    整段丢弃。不含元字符的字符串原样通过。
    """
    if not (_REGEX_METACHARS & set(raw)):
        return [raw.strip()]
    tokens: list[str] = []
    for part in raw.split("|"):
        token = part.strip().strip("(?:)")
        if not token or (_REGEX_METACHARS & set(token)):
            continue
        tokens.append(token)
    return tokens


def _acceptable_token(token: str) -> bool:
    if not token or len(token) > 16 or any(ch.isspace() for ch in token):
        return False
    return contains_cjk(token) or token.isascii()


def _extract_module_triggers(
    path: Path, func_names: list[str], source_label: str
) -> tuple[set[str], dict[str, set[str]]]:
    """从一个 capability 模块提取 is_* 函数可见的词表字符串。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    module_assigns = _collect_module_assigns(tree)
    words: set[str] = set()
    for node in tree.body:
        if not (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in func_names):
            continue
        for value in _literal_str_values(node, module_assigns):
            for token in split_trigger_tokens(value):
                if _acceptable_token(token):
                    words.add(token)
    per_word_sources = {word: {source_label} for word in words}
    return words, per_word_sources


def _base_router_capability_targets() -> dict[str, list[str]]:
    """解析 base_router 的 import：capability 模块文件 → is_* 函数名列表。"""
    tree = ast.parse(BASE_ROUTER_PATH.read_text(encoding="utf-8"), filename=str(BASE_ROUTER_PATH))
    targets: dict[str, list[str]] = {}
    prefix = "plugins.bot_unified_runtime."
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(prefix)):
            continue
        rel = node.module.replace(".", "/")
        candidate = REPO_ROOT / f"{rel}.py"
        if not candidate.is_file():
            continue
        names = [alias.name for alias in node.names if alias.name.startswith("is_")]
        if names:
            targets.setdefault(str(candidate), []).extend(names)
    return targets


def extract_echo_aliases() -> tuple[set[str], dict[str, set[str]]]:
    """提取 echo.py ``_HELP_ENTRIES`` 的全部 aliases。

    取数走 `command_catalog` 的在册字面量口（见模块 docstring）：它认字面量，也认
    ``nickname_verbs_for`` / ``host_state_trigger_words`` / ``media_archive_trigger_words``
    这三枚**在册纯投影**的 Call（按真身模块的定义就地求值，实现只有一份）。

    🔴 响亮失败三处（「门会缩不会红」那一型，2026-10-08 同批根修）：
    缺文件／``_HELP_ENTRIES`` 取空／aliases 一枚没提到 ⇒ 一律抛，不返回空集。
    旧写法是 `for node in tree.body: … if not hit: continue`——别名册改名或整块搬走时
    这里安静返回 ``set()``，草稿照样写出、照样「跑通」，只是词全没了。
    """
    if not ECHO_PATH.is_file():
        raise FileNotFoundError(
            f"帮助册真身不在位：{ECHO_PATH}（echo 的 aliases 词面取不到 ⇒ 拼音候选表无从生成；"
            "先核对 ECHO_PATH 是否又跟着 domains/ 重构漂了）"
        )
    entries = cc._literal_assign(cc._module_tree(ECHO_PATH), "_HELP_ENTRIES")
    if not isinstance(entries, list) or not all(isinstance(item, dict) for item in entries):
        raise ValueError(f"{ECHO_PATH.name}::_HELP_ENTRIES 不是 dict 列表 ⇒ 无法按条目取 aliases")
    ds.require_surface("echo._HELP_ENTRIES 条目集", entries, ECHO_PATH, ("_HELP_ENTRIES",))

    words: set[str] = set()
    for entry in entries:
        for alias in entry.get("aliases", ()) or ():
            token = str(alias).strip()
            if token:
                words.add(token)
    ds.require_surface("echo._HELP_ENTRIES[*].aliases 词面集", words, ECHO_PATH, ("aliases",))
    return words, {word: {"echo._HELP_ENTRIES"} for word in words}


def extract_all() -> tuple[set[str], set[str], dict[str, set[str]]]:
    """返回 (中文候选词, 英文触发词, 词→来源)。"""
    chinese: set[str] = set()
    english: set[str] = set()
    sources: dict[str, set[str]] = {}

    def absorb(words: set[str], word_sources: dict[str, set[str]]) -> None:
        for word in words:
            bucket = chinese if contains_cjk(word) else english
            bucket.add(word)
            sources.setdefault(word, set()).update(word_sources.get(word, set()))

    absorb(*extract_echo_aliases())
    targets = _base_router_capability_targets()
    # 🔴 路由面整体取空也要抛（同「门会缩不会红」型）：`_base_router_capability_targets`
    # 对非文件的 import 目标静默 `continue`，base_router 若整体搬家/改名 ⇒ 这里返回 {} ⇒
    # 草稿只剩帮助册那一簇词，看起来仍是「跑通且有一堆词」。
    ds.require_surface("base_router 的 is_* 能力模块目标表", targets, BASE_ROUTER_PATH, ("is_",))
    for path_str, func_names in targets.items():
        path = Path(path_str)
        label = f"{path.stem}.{','.join(sorted(set(func_names)))}"
        words, word_sources = _extract_module_triggers(path, func_names, label)
        # 单模块取空**不**抛：is_* 判定常从他处 import 后再被 base_router 引名，那一格本就无词；
        # 聚合面由下一行的 require_surface 兜住（一枚中文词都没有 ⇒ 响）。
        absorb(words, word_sources)

    return ds.require_surface(
        "中文触发词候选集（拼音映射的输入面）", chinese, BASE_ROUTER_PATH, ("_HELP_ENTRIES",)
    ), english, sources


# ---------------------------------------------------------------------------
# 拼音映射
# ---------------------------------------------------------------------------

def word_full_pinyin(word: str) -> str:
    overridden = MULTI_TONE_OVERRIDES.get(word)
    if overridden is not None:
        return "".join(overridden)
    parts: list[str] = []
    for part in lazy_pinyin(word, style=Style.NORMAL, errors="default"):
        parts.append("".join(ch.lower() for ch in part if ch.isascii() and ch.isalnum()))
    return "".join(p for p in parts if p)


def word_abbr(word: str) -> str:
    overridden = MULTI_TONE_OVERRIDES.get(word)
    if overridden is not None:
        return "".join(p[0] for p in overridden)
    letters: list[str] = []
    for readings in pinyin(word, style=Style.FIRST_LETTER, errors="default"):
        piece = "".join(ch.lower() for ch in readings[0] if ch.isascii() and ch.isalnum())
        if piece:
            letters.append(piece[0])
    return "".join(letters)


def has_heteronym_char(word: str) -> bool:
    """逐字（脱离词组语境）检测多音字。

    注意：pypinyin 的 ``heteronym=True`` 在词组语境下会按词定读（如「行情」只回
    háng），因此必须对单字分别查询才能暴露「该字存在其他读法」这一事实。
    """
    for ch in word:
        if not _is_cjk_char(ch):
            continue
        readings = pinyin(ch, heteronym=True, errors="default")
        if readings and len(readings[0]) > 1:
            return True
    return False


def build_entry(word: str, source_labels: set[str]) -> dict[str, object]:
    entry: dict[str, object] = {
        "full": word_full_pinyin(word),
        "abbr": word_abbr(word),
    }
    if word in MULTI_TONE_OVERRIDES or has_heteronym_char(word):
        entry["multi_tone_review"] = True
    raw_abbr = str(entry["abbr"])
    if len(raw_abbr) > ABBR_MAX_LEN:
        entry["abbr"] = raw_abbr[:ABBR_MAX_LEN]
        entry["abbr_truncated"] = True
        entry["full_abbr"] = raw_abbr
    entry["sources"] = sorted(source_labels)
    return entry


def find_conflicts(
    mapping: dict[str, dict[str, object]], english_words: set[str]
) -> list[dict[str, object]]:
    conflicts: list[dict[str, object]] = []

    by_abbr: dict[str, list[str]] = {}
    by_full: dict[str, list[str]] = {}
    for word, entry in mapping.items():
        by_abbr.setdefault(str(entry["abbr"]), []).append(word)
        by_full.setdefault(str(entry["full"]), []).append(word)

    for abbr, group in sorted(by_abbr.items()):
        if len(group) > 1:
            conflicts.append({"type": "abbr", "key": abbr, "items": sorted(group)})
    en_lower = {w.lower() for w in english_words}
    for word, entry in sorted(mapping.items()):
        if str(entry["abbr"]) in en_lower:
            conflicts.append(
                {
                    "type": "abbr_vs_english",
                    "key": str(entry["abbr"]),
                    "items": [word, str(entry["abbr"])],
                }
            )
        if str(entry["full"]) in en_lower:
            conflicts.append(
                {
                    "type": "full_vs_english",
                    "key": str(entry["full"]),
                    "items": [word, str(entry["full"])],
                }
            )
    return conflicts


def build_mapping(chinese: set[str], sources: dict[str, set[str]]) -> dict[str, dict[str, object]]:
    mapping: dict[str, dict[str, object]] = {}
    for word in sorted(chinese):
        mapping[word] = build_entry(word, sources.get(word, set()))
    return mapping


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------

def run_selftest() -> int:
    """已知多音字样例断言（不依赖仓库文件）。"""
    cases_pass = True

    def expect(word: str, full: str, abbr: str, flagged: bool) -> None:
        nonlocal cases_pass
        entry = build_entry(word, {"selftest"})
        ok = (
            entry["full"] == full
            and entry["abbr"] == abbr
            and bool(entry.get("multi_tone_review", False)) is flagged
        )
        if not ok:
            cases_pass = False
        print(f"  {word}: full={entry['full']} abbr={entry['abbr']} "
              f"flag={entry.get('multi_tone_review', False)} -> {'OK' if ok else 'FAIL'}")

    print("[selftest] 多音字与缩写样例：")
    expect("点歌", "diange", "dg", False)
    expect("行情", "hangqing", "hq", True)      # 行 háng（不是 xíng）
    expect("重试", "chongshi", "cs", True)      # 覆写表：chóng（不是 zhòng）
    expect("长得", "zhangde", "zd", True)       # 长 zhǎng
    expect("历史上的今天", "lishishangdejintian", "lssd", True)  # 缩写截断≤4：lssdjt→lssd

    conflicts = find_conflicts(
        {"点歌": build_entry("点歌", set()), "点工": build_entry("点工", set())},
        {"dg"},
    )
    types = {c["type"] for c in conflicts}
    ok = types == {"abbr", "abbr_vs_english"}
    print(f"  冲突检测(点歌/点工 撞 dg)：types={sorted(types)} -> {'OK' if ok else 'FAIL'}")
    cases_pass = cases_pass and ok
    print("[selftest]", "PASS" if cases_pass else "FAIL")
    return 0 if cases_pass else 1


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成触发词拼音映射草稿")
    parser.add_argument("--selftest", action="store_true", help="运行已知多音字样例断言")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="输出 JSON 路径")
    args = parser.parse_args(argv)

    if args.selftest:
        return run_selftest()

    chinese, english, sources = extract_all()
    mapping = build_mapping(chinese, sources)
    conflicts = find_conflicts(mapping, english)
    flagged = sum(1 for e in mapping.values() if e.get("multi_tone_review"))
    truncated = sum(1 for e in mapping.values() if e.get("abbr_truncated"))
    abbr_conflicts = sum(1 for c in conflicts if c["type"] == "abbr")
    en_hits = sum(1 for c in conflicts if c["type"].endswith("english"))
    stats = {
        "chinese_words": len(mapping),
        "english_trigger_words": len(english),
        "multi_tone_flagged": flagged,
        "abbr_truncated": truncated,
        "abbr_conflict_groups": abbr_conflicts,
        "english_collision_pairs": en_hits,
        "conflict_records": len(conflicts),
    }

    payload = {
        "meta": {
            "generated_at": datetime.now(tz=timezone.utc).date().isoformat(),
            "generator": "scripts/gen_trigger_pinyin.py",
            "note": "候选草稿（非终稿）：多音字取常见二字组合，multi_tone_review=true 待人工审校；"
                    "缩写截断≤4 位；终稿由执行波在规格确认后审校。",
        },
        "stats": stats,
        "mapping": mapping,
        "conflicts": conflicts,
        "english_trigger_words": sorted(english),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(json.dumps(stats, ensure_ascii=False))
    print(f"written: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
