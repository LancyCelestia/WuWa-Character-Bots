"""生成触发词拼音映射草稿（触发规范化规格的候选材料）。

输入（程序化提取，零 import 副作用，纯 AST 静态解析）：
- capabilities/echo.py 的 ``_HELP_ENTRIES`` 全部 aliases；
- runtime/base_router.py 引用的各 ``is_*`` 触发判定函数所在 capability 模块的词表
  （沿函数体 → 模块级常量 → re.compile 参数递归取字符串字面量）。

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
ECHO_PATH = REPO_ROOT / "plugins" / "bot_unified_runtime" / "capabilities" / "echo.py"
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
    """提取 echo.py _HELP_ENTRIES 的全部 aliases。"""
    tree = ast.parse(ECHO_PATH.read_text(encoding="utf-8"), filename=str(ECHO_PATH))
    words: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            hit = any(isinstance(t, ast.Name) and t.id == "_HELP_ENTRIES" for t in node.targets)
        elif isinstance(node, ast.AnnAssign):
            hit = isinstance(node.target, ast.Name) and node.target.id == "_HELP_ENTRIES"
        else:
            hit = False
        if not hit:
            continue
        for entry in ast.literal_eval(node.value):
            aliases = entry.get("aliases", ()) if isinstance(entry, dict) else ()
            for alias in aliases:
                token = str(alias).strip()
                if token:
                    words.add(token)
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
    for path_str, func_names in _base_router_capability_targets().items():
        path = Path(path_str)
        label = f"{path.stem}.{','.join(sorted(set(func_names)))}"
        words, word_sources = _extract_module_triggers(path, func_names, label)
        absorb(words, word_sources)

    return chinese, english, sources


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
