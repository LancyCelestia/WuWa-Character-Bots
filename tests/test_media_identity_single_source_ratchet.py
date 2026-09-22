"""媒体内容身份只准走中央件（`domains/media/digest.py`）——禁第二份实现棘轮。

统一波「产出/内容统一」维的执法面。中央唯一入口 = `media_digest` / `media_digest_file`；
本门不禁"生产代码里用 hashlib"（token/盐/请求 id 都该用），**只禁"拿媒体字节的哈希当内容身份"**，
所以判据刻意做窄，且**带正样控制**：判据必须看得见中央件自己那两处，否则"零命中"只是尺子瞎
（本项目实锤过：拿一个看不见执法对象的扫描器报"全绿"）。

尺子口径（写死在这里，别让下游猜）：
- 扫描面＝媒体身份可能发生的五个域目录（media / render / meme / creation / files）；
- 命中＝`hashlib.{sha256,sha1,md5,blake2b}` 且**实参是字节形**（名字像字节，或来自 read/解码/响应体）；
- 字符串走 `.encode(...)` 的（token/盐/键）**不算**——那是另一种东西，管它是越权执法。

**本门的限缩（读绿之前先记住）**：它只拦"第二份媒体内容身份**实现**"，
**不拦"根本不出内容身份"**。设计席 PLAN-VOICE2 实读的自动配音**默认路径旧包装**
（root `_attach_voice_reply` → `maybe_attach_voice`，与 hook 形已不字节同构、缺 `content_sha256`
与 M-14 有损留痕）正落在盲区内——它不哈希，所以本门全绿也**不代表**每条配音产物都带内容身份。
那条路的收编与摘牌见 `decisions/VOICE-AUTO-DUB-CENTRAL-LEG-PLAN-20260922.md`，别拿本门的绿当它的凭证。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "plugins" / "bot_unified_runtime"
SURFACES = ("domains/media/", "domains/render/", "domains/meme/", "domains/creation/", "domains/files/")
HASH_FUNCS = frozenset({"sha256", "sha1", "md5", "blake2b"})
CENTRAL = "domains/media/digest.py"

_BYTESISH = re.compile(r"(bytes|blob|image|audio|media|payload|data|chunk|buffer)$", re.IGNORECASE)
_READISH = re.compile(r"(\.read\(|read_bytes|b64decode|\.content\b)")

#: **手写字面量**上限，只准降：非中央件的"媒体字节→哈希"站点数。迁掉一处就改小并追加 AUDIT_HISTORY。
NON_CENTRAL_IDENTITY_CEILING = 1
#: 已核账记录（日期, 当时站点数），**必须单调不升**。
AUDIT_HISTORY: tuple[tuple[str, int], ...] = (("2026-09-22", 1),)
#: 欠款登记（迁完必须从这里删掉，同时降上面两枚数字——留着＝谎报还在欠）。
KNOWN_DEBT: dict[str, str] = {
    "domains/meme/sources/meme_library_listener.py": (
        "P2：表情库下载去重用内联 md5(image_bytes) 当身份，应改 media_digest；"
        "若库内已有 md5 行不许清洗（AGENTS 运行数据保护），则并行写 sha256 新列后摘牌"
    ),
}


def _arg_is_bytesish(node: ast.expr) -> bool:
    text = ast.unparse(node)
    if ".encode(" in text:
        return False
    if isinstance(node, ast.Name):
        return bool(_BYTESISH.search(node.id))
    if isinstance(node, ast.Attribute):
        return bool(_BYTESISH.search(node.attr))
    return bool(_READISH.search(text))


def count_identity_sites_in_source(source: str, rel: str) -> int:
    """单一取数口：全树扫描与注毒自证共用同一判据（别再抄第二份 AST 抽取）。"""
    if not rel.startswith(SURFACES):
        return 0
    tree = ast.parse(source, filename=rel)
    total = 0
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in HASH_FUNCS
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "hashlib"
            and node.args
            and _arg_is_bytesish(node.args[0])
        ):
            total += 1
    return total


def scan_identity_sites() -> dict[str, int]:
    per_file: dict[str, int] = {}
    for path in PACKAGE_ROOT.rglob("*.py"):
        rel = path.relative_to(PACKAGE_ROOT.parent).as_posix().replace("bot_unified_runtime/", "", 1)
        n = count_identity_sites_in_source(path.read_text(encoding="utf-8"), rel)
        if n:
            per_file[rel] = n
    return per_file


def test_central_digest_is_visible_to_the_ruler() -> None:
    """正样控制：判据若看不见中央件自己，下面所有"零红"都没有意义。"""
    sites = scan_identity_sites()
    assert sites.get(CENTRAL), (
        f"中央件 {CENTRAL} 自己没被数到（只数到 {sorted(sites)}）——判据已瞎，本门现在是空跑"
    )


def test_no_new_media_content_identity_implementation() -> None:
    sites = scan_identity_sites()
    offenders = {rel: n for rel, n in sites.items() if rel != CENTRAL}
    assert sum(offenders.values()) <= NON_CENTRAL_IDENTITY_CEILING, (
        f"又长了第二份媒体内容身份实现：{offenders}（上限 {NON_CENTRAL_IDENTITY_CEILING}）。"
        f"改指 {CENTRAL} 的 media_digest / media_digest_file，别在本门里加豁免"
    )
    assert set(offenders) <= set(KNOWN_DEBT), f"未登记的媒体身份实现（先判它是不是真身份再谈豁免）：{sorted(offenders)}"


def test_registered_debt_is_still_real() -> None:
    """欠款不许挂着不销：迁完就把条目删掉，否则本门红（防止"账上永远欠着"式麻木）。"""
    sites = scan_identity_sites()
    stale = sorted(rel for rel in KNOWN_DEBT if rel not in sites)
    assert not stale, f"这些欠款已不成立，请从 KNOWN_DEBT 删除并把上限与 AUDIT_HISTORY 降一档：{stale}"


def test_ceiling_is_literal_and_never_rises() -> None:
    assigned: dict[str, ast.expr] = {}
    for node in ast.walk(ast.parse(Path(__file__).read_text(encoding="utf-8"))):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            assigned[node.targets[0].id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            assigned[node.target.id] = node.value
    ceiling = assigned.get("NON_CENTRAL_IDENTITY_CEILING")
    assert isinstance(ceiling, ast.Constant) and isinstance(ceiling.value, int), (
        "上限写成派生表达式（len/sum）＝与被检清单同一表达式，本门结构性失效"
    )
    history = assigned.get("AUDIT_HISTORY")
    assert isinstance(history, ast.Tuple) and history.elts, "核账记录必须留在本文件且非空"
    counts = [int(e.elts[1].value) for e in history.elts]  # type: ignore[attr-defined]
    assert counts == sorted(counts, reverse=True), f"核账记录回升（方向锁）：{AUDIT_HISTORY}"
    assert ceiling.value <= counts[0], "上限不得超过首届核账值"


def test_poison_new_site_is_caught() -> None:
    """注毒自证（内存样本，不碰源码树）：新增一处"读媒体字节→哈希当身份"必须数到。"""
    poison = "import hashlib\nfrom plugins.bot_unified_runtime.domains.media.digest import media_digest\n\n"
    for expr in ("hashlib.sha256(image_bytes)", "hashlib.md5(data)", "hashlib.sha256(raw.read())"):
        assert count_identity_sites_in_source(poison + f"h = {expr}\n", "domains/meme/x.py") == 1, expr
    # 反例：字符串哈希不是媒体身份（越权执法会把 35 处 token/盐全判成违规）
    assert count_identity_sites_in_source(poison + "h = hashlib.sha256(token.encode('utf-8'))\n", "domains/meme/x.py") == 0
    # 反例：域外（schedule 里给 payload 做键）不属本门
    assert count_identity_sites_in_source(poison + "h = hashlib.sha256(payload)\n", "domains/schedule/x.py") == 0
