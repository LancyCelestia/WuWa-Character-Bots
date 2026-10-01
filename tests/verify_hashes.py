"""交付物 SHA-256 清单（交叉验证机制·哈希层，2026-09-13）。

用法：
    python tests/verify_hashes.py --write   # 记录/重录基线（有意识地改），并另发旁车自签
    python tests/verify_hashes.py --check   # 校验漂移（退出码非 0 = 有未记录变更或篡改）
    python tests/verify_hashes.py           # 缺省 = --check

pytest 常驻门：tests/test_cross_validation_gates.py 以 subprocess --check
方式守门——清单内任何文件出现未记录的**内容**变更，全量测试直接红，
强制走一次「有意识 --write」，改了 A 忘了 B 的事在门禁处现形。

哈希口径：换行统一为 LF 后再算（见 ``sha256_of``），因此哈希锚定的是
「提交内容」而非「工作区行尾状态」——主仓、linked worktree、CI 干净克隆
三种检出环境必须得出一致结果。

清单范围（视觉与规范交付物，对齐 DESIGN-SPEC.md §三）：
7 张 Jinja 模板 + theme_tokens.py + docs/rendering-contract.md + DESIGN-SPEC.md
+ docs/design/ 三份规格 + 6 个卡片 builder 源文件（审查 K-06 扩面，2026-09-14：
bridge/renderer/templates + echo/debug/usage_cards——模板只是壳，改 builder 的
f-string 文案同样改变出卡内容，不进清单就绕过了哈希门），共 19 项。

防篡改旁车（2026-09-26 改册事故 remediation，ECHO-WRITEBACK-FORENSIC §3 建议 1）：
``write()`` 全量写册成功后**另落** ``tests/render_hashes.meta.json``
= {full_write_at, entry_count, body_sha256}；``--check`` 增独立腿校验自签，
命中报 ``LEDGER_TAMPER``（与 DRIFT 分账、不混报）。旁车只由全量写产生，
任何工具外单行/少数行直改册体都会断自签——这正是 09-26 18:12 事故的形态。
绝不往 ``render_hashes.json`` 册内加键（tests/test_verify_hashes_coverage.py
的键集全等断言钉着，塞入需连改动该门、反而扩大改动面）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path(__file__).with_name("render_hashes.json")
META = Path(__file__).with_name("render_hashes.meta.json")

# ---------------------------------------------------------------------------
# 旁车 canonical 字节口径（写死，防实现漂移）：
#   册体 canonical bytes = MANIFEST 原始字节把每一处 CRLF(b"\r\n") 替换为
#   LF(b"\n") 之后的结果——与 sha256_of 同一轴（哈希锚定「提交内容」而非
#   工作区行尾状态），主仓 / linked worktree / CI 干净克隆三种检出必须得出
#   一致结果。write() 以 newline="\n" 落盘，此时 canonical == 原始字节；
#   body_sha256 = sha256(canonical bytes).hexdigest()。
# 旁车自身不参与该口径（它只是自签载体，篡改它会被册体重算腿与缺失腿抓住）。
# ---------------------------------------------------------------------------


def canonical_manifest_bytes() -> bytes:
    """render_hashes.json 的 canonical 字节（见上方写死口径）。"""
    return MANIFEST.read_bytes().replace(b"\r\n", b"\n")

TRACKED_FILES: tuple[str, ...] = (
    "plugins/bot_unified_runtime/domains/render/card_render/templates/universal_card.html",
    "plugins/bot_unified_runtime/domains/render/card_render/templates/affinity_card.html",
    "plugins/bot_unified_runtime/domains/render/card_render/templates/finance_card.html",
    "plugins/bot_unified_runtime/domains/render/card_render/templates/market_card.html",
    "plugins/bot_unified_runtime/domains/render/card_render/templates/mermaid_card.html",
    "plugins/bot_unified_runtime/domains/render/card_render/templates/song_candidates.html",
    "plugins/bot_unified_runtime/domains/render/card_render/templates/error_card.html",
    "plugins/bot_unified_runtime/domains/render/card_render/theme_tokens.py",
    "docs/rendering-contract.md",
    "DESIGN-SPEC.md",
    "docs/design/fstring-card-dom-spec.md",
    "docs/design/render-pipeline-optimization-spec.md",
    "docs/design/visual-effects-catalog.md",
    # --- 卡片 builder 源文件（审查 K-06 扩面，2026-09-14）---
    # 约束：这 6 个文件产出/装配模板 HTML（4 处 f-string 直拼卡见
    # tests/test_mica_builders_contract.py 的统一对象清单），改文案不改模板
    # 也必须过哈希门，否则「改 builder 绕过 --write」成为系统性漏洞。
    "plugins/bot_unified_runtime/domains/render/card_render/bridge.py",
    # v21r2 RWOC：debug 真身迁 domains/ops/admin/（旧路径只余垫片）。
    "plugins/bot_unified_runtime/domains/ops/admin/debug.py",
    # v21r2 RWC3：echo 真身迁 domains/chat_reply/capabilities/（帮助注册表真相源）。
    "plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py",
    "plugins/bot_unified_runtime/domains/render/card_render/usage_cards.py",
    "plugins/bot_unified_runtime/domains/render/renderer.py",
    "plugins/bot_unified_runtime/domains/render/templates.py",
)


def sha256_of(path: Path) -> str:
    """交付物内容哈希：换行统一为 LF 后再算。

    哈希必须锚定「提交内容」，不能锚定「工作区行尾状态」——Windows 上
    ``core.autocrlf`` 会把检出转成 CRLF，而 ``.gitattributes`` 又要求
    ``*.md/*.py/*.json`` 为 LF。若直接哈希原始字节，同一个 commit 在主仓、
    linked worktree、CI 干净克隆上会得出不同结果，哈希门随之失真
    （2026-09-14 审查实证：干净检出误报 4 项漂移）。
    """
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def build_manifest() -> dict[str, str]:
    return {name: sha256_of(ROOT / name) for name in TRACKED_FILES}


def tamper_problems(recorded: dict[str, str]) -> list[str]:
    """旁车自签独立腿——与册体 DRIFT/NEW/STALE 分账，命中一律报 LEDGER_TAMPER。

    判据三态：①旁车缺失/坏损 ⇒ 册体没有"全量写"来历凭据；②entry_count 与
    册内条目数不等；③按写死口径重算册体哈希 != 旁车 body_sha256。
    ②③ 任何一态都不依赖文件内容漂移——工具外只改册子一行（09-26 事故形态）
    即便 DRIFT 腿全绿，自签也必断。
    """
    problems: list[str] = []
    if not META.is_file():
        problems.append(
            f"LEDGER_TAMPER  {META.name}（旁车缺失——册体无全量写自签，"
            "安静窗确认后 --write 重录发旁车）"
        )
        return problems
    try:
        meta = json.loads(META.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        problems.append(f"LEDGER_TAMPER  {META.name}（旁车不可读/坏损）")
        return problems
    if not isinstance(meta, dict):
        problems.append(f"LEDGER_TAMPER  {META.name}（旁车非 JSON 对象）")
        return problems
    if not MANIFEST.is_file():
        problems.append(
            f"LEDGER_TAMPER  {MANIFEST.name}（旁车在册而册体缺位——自签无从重算）"
        )
        return problems
    entry_count = meta.get("entry_count")
    if not isinstance(entry_count, int) or entry_count != len(recorded):
        problems.append(
            f"LEDGER_TAMPER  {MANIFEST.name}（条目数漂移：旁车={entry_count} "
            f"册内={len(recorded)}）"
        )
    body_sha = meta.get("body_sha256")
    recomputed = hashlib.sha256(canonical_manifest_bytes()).hexdigest()
    if not isinstance(body_sha, str) or body_sha != recomputed:
        problems.append(
            f"LEDGER_TAMPER  {MANIFEST.name}（册体重算哈希 != 旁车自签——"
            "存在工具外改册，取证后安静窗 --write）"
        )
    return problems


def check(quiet: bool = False) -> list[str]:
    """返回漂移+篡改报告（空列表 = 干净）。缺文件/新文件未登记/字节变更都算；
    旁车自签腿独立成 LEDGER_TAMPER 账，与 DRIFT 分账不混报。"""
    problems: list[str] = []
    recorded: dict[str, str] = {}
    if MANIFEST.is_file():
        recorded = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for name in TRACKED_FILES:
        path = ROOT / name
        if not path.is_file():
            problems.append(f"MISSING  {name}（清单在册但文件不存在）")
            continue
        current = sha256_of(path)
        if name not in recorded:
            problems.append(f"NEW      {name}（未登记的新交付物——确认后 --write）")
        elif recorded[name] != current:
            problems.append(f"DRIFT    {name}（字节变更未记录——确认后 --write）")
    for name in recorded:
        if name not in TRACKED_FILES:
            problems.append(f"STALE    {name}（清单已登记但不在跟踪集——清理后 --write）")
    tamper = tamper_problems(recorded)
    if problems and not quiet:
        for line in problems:
            print(line, file=sys.stderr)
        print(
            f"verify_hashes: {len(problems)} 项漂移；"
            "确认属预期改动后执行 python tests/verify_hashes.py --write 重录。",
            file=sys.stderr,
        )
    if tamper and not quiet:
        for line in tamper:
            print(line, file=sys.stderr)
        print(
            f"verify_hashes: {len(tamper)} 项篡改（LEDGER_TAMPER，与漂移分账；"
            "整册确认无损后 --write 会刷新旁车自签）。",
            file=sys.stderr,
        )
    return problems + tamper


def write() -> None:
    manifest_payload = build_manifest()
    MANIFEST.write_text(
        json.dumps(manifest_payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    # 旁车只在全量写册成功后另落（绝不在册内加键）；body_sha256 按写死的
    # canonical 口径重算，full_write_at 提供"何时全量重录"的自证元数据。
    META.write_text(
        json.dumps(
            {
                "body_sha256": hashlib.sha256(canonical_manifest_bytes()).hexdigest(),
                "entry_count": len(manifest_payload),
                "full_write_at": datetime.now(timezone.utc).isoformat(
                    timespec="seconds"
                ),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        f"verify_hashes: 已记录 {len(manifest_payload)} 个交付物 -> {MANIFEST.name}"
        f"（旁车 {META.name} 已另发）"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="交付物 SHA-256 漂移门")
    parser.add_argument("--write", action="store_true", help="记录/重录基线")
    parser.add_argument("--check", action="store_true", help="校验漂移（缺省行为）")
    args = parser.parse_args(argv)
    if args.write:
        write()
        return 0
    return 1 if check() else 0


if __name__ == "__main__":
    raise SystemExit(main())
