"""哈希门 builder 覆盖测试（审查 K-06，2026-09-14）。

K-06 病灶：tests/verify_hashes.py 的 TRACKED_FILES 原本只含 7 张模板 +
theme_tokens + 文档，而真正产出模板 HTML 的 builder 源文件（bridge/renderer/
templates + echo/debug/usage_cards）改文案不触发哈希门——「改 builder 绕过
--write」是系统性漏洞。本文件钉死覆盖面，防将来倒退：

1. 6 个 builder 源文件必须全部在清单内（删条目 = 直接红）；
2. 覆盖必须真实生效：临时改动一个 builder 文件 → --check 红（DRIFT 指名
   该文件）→ 字节级还原 → --check 回绿（证明门盯的是 builder 本体）；
3. render_hashes.json 的键集与 TRACKED_FILES 严格一致（防 STALE/漏登）；
4. build_manifest 纯函数幂等（同树两次求值结果相等）。

连续两次 ``--write`` 无 diff 的幂等证明属「有意识重录」人工流程，不入
自动化——测试内绝不写 render_hashes.json，避免测试改变仓库状态。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from verify_hashes import MANIFEST, TRACKED_FILES, build_manifest

# 审查 K-06 扩面的 6 个 builder 源文件（与 TRACKED_FILES 尾部块一一对应；
# 改动清单时必须同步这里，否则覆盖面测试先红）。
BUILDER_SOURCES: tuple[str, ...] = (
    "plugins/bot_unified_runtime/domains/render/card_render/bridge.py",
    # v21r2 RWOC：debug 真身迁 domains/ops/admin/。
    "plugins/bot_unified_runtime/domains/ops/admin/debug.py",
    # v21r2 RWC3：echo 真身迁 domains/chat_reply/capabilities/。
    "plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py",
    "plugins/bot_unified_runtime/domains/render/card_render/usage_cards.py",
    "plugins/bot_unified_runtime/domains/render/renderer.py",
    "plugins/bot_unified_runtime/domains/render/templates.py",
)

# 漂移演练用受害者：旧媒体卡降级器（f-string 卡 builder 之一）。选它而非
# echo.py/debug.py，是因为并行代理常在后者上作业，几毫秒的临时改写窗口
# 可能撞车；templates.py 无在飞域。
_DRILL_TARGET = ROOT / "plugins/bot_unified_runtime/domains/render/templates.py"


def _run_check() -> subprocess.CompletedProcess[str]:
    # `-X utf8` + 显式 encoding：子进程打印的是中文报告，父进程按 locale(GBK) 解码
    # 会在 reader 线程抛 UnicodeDecodeError ⇒ stderr=None ⇒ 本门假红（跑测试时
    # export PYTHONIOENCODING=utf-8 即复现，属本仓既定跑法）。编码两端都钉死才不看环境。
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(ROOT / "tests" / "verify_hashes.py"), "--check"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        cwd=str(ROOT),
        check=False,
    )


def test_builder_sources_all_tracked() -> None:
    """覆盖面防倒退：6 个 builder 源文件必须全部在哈希清单内。"""
    for name in BUILDER_SOURCES:
        assert name in TRACKED_FILES, f"builder 源文件脱离哈希门：{name}"
    # 演练目标本身也必须在册（否则下面的红/绿演练测的是空气）。
    rel = _DRILL_TARGET.relative_to(ROOT).as_posix()
    assert rel in TRACKED_FILES


def _drift_files(text: str) -> set[str]:
    """从 --check 输出里取漂移件名集合（只认报告自己的行，不猜格式）。"""
    return {
        token
        for line in text.splitlines()
        for token in line.replace(",", " ").split()
        if "DRIFT" in line and token.endswith(".py")
    }


def test_builder_drift_gate_red_then_green() -> None:
    """新覆盖真实生效：临时改动 builder → --check 红；还原 → 漂移面回到改前集合。

    还原判据**不比"全树绿"**：基线里若另有他件未重录（并发波常态），
    "全树绿"会把一次彻底还原误报成"基线被污染"（2026-09-22 全量真值席实测假红）。
    正确的判据是"漂移集合回到改前"——既证还原无痕，也不替他件背锅。
    """
    original = _DRILL_TARGET.read_bytes()
    before = _drift_files(_run_check().stderr)
    assert "templates.py" not in before, "演练起点就不干净：目标件已在漂移面里"
    try:
        # 追加一个换行：内容变了（哈希必变），语义零影响，恢复即无痕。
        _DRILL_TARGET.write_bytes(original + b"\n")
        result = _run_check()
        assert result.returncode == 1, "builder 漂移未被哈希门拦截（K-06 复发）"
        assert "DRIFT" in result.stderr
        assert "templates.py" in result.stderr, "漂移报告未指名被改的 builder"
    finally:
        # 字节级还原（非 --write：演练不许污染基线）。
        _DRILL_TARGET.write_bytes(original)
    after = _drift_files(_run_check().stderr)
    assert after == before, (
        f"还原不彻底或被本演练污染：改前漂移面={sorted(before)} 改后={sorted(after)}"
    )


def test_manifest_keys_match_tracked_files() -> None:
    """render_hashes.json 键集 == TRACKED_FILES（防 STALE 残留/漏登）。"""
    recorded: dict[str, str] = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert set(recorded) == set(TRACKED_FILES)
    assert len(recorded) == len(TRACKED_FILES) == 19


def test_build_manifest_pure_idempotent() -> None:
    """同树两次求值哈希一致（--write 幂等的纯函数前提，零文件写入）。"""
    assert build_manifest() == build_manifest()
