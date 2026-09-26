"""doc_sync 反向自测与塌陷地板（TX281 续跑 TX264 · 只新建本件，不改任何既有断言）。

背景（判据沿用前任 TX264，原文见 BRIEFS-BATCH61.md §《TX264》）：
TX259 判：五组交付门里**只有 `doc_sync` 缺反向自测**、且无扫描面塌陷地板 ⇒
按准绳"无反向自测的门视为不存在"，这一组今天不算有门。

本件补齐 TX281《共享前言》要求的**两腿**（注毒全在内存 / tmp_path 副本，不落源码树，
绝不改 `scripts/doc_sync.py` 本体，也不改真身 `docs/auto-facts.md`）：

- 正常态腿：不注毒 ⇒ ``check()`` True / ``main(["--check"])`` == 0。
- 塌陷注入腿：把任一取数口在内存里改成空/零 ⇒ ``check()`` False / ``--check`` 非零。

外加：② 篡改一条机器事实值（非零错值）⇒ 必红；③ 扫描面塌陷地板（各计数现算 > 0，
不写死"应为几"）；④ 杀伤力自证（塌陷注入必须真的改变投影器输出，否则本用例当场红 ⇒
反向自测不会退化为空跑假绿）。

为与"新增测试件顶漂在盘计数（588→589）"解耦，两腿都走 tmp_path 基线副本：
夹具先把真身 ``build_document()`` 写进 tmp 文件并把 ``doc_sync.TARGET`` 指过去，
故本件不依赖真身 ``docs/auto-facts.md`` 此刻是否在同步态。
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import doc_sync

# 六支取数口：塌陷成"空/零"的注入函数（TX281③「把生成物/投影器输出改成空或零」）。
_COLLAPSE: dict[str, Callable[[], object]] = {
    "_tpl_list": list,
    "_route_kinds": list,
    "_help_topics": list,
    "_test_file_count": lambda: 0,
    "_config_key_count": lambda: 0,
    "_tracked_files": list,
}


@pytest.fixture()
def baseline_sandbox(tmp_path, monkeypatch) -> str:
    """把 TARGET 指向 tmp_path 上的未注毒基线副本，返回基线正文。

    两腿都相对这份内存基线判定，因此与真身 docs/auto-facts.md 的在盘漂移解耦，
    也不会写入源码树。
    """
    baseline = doc_sync.build_document()
    target = tmp_path / "auto-facts.md"
    target.write_text(baseline, encoding="utf-8", newline="\n")
    monkeypatch.setattr(doc_sync, "TARGET", target)
    return baseline


# ---------------------------------------------------------------------------
# 正常态腿（TX281③ 之一）：不注毒 ⇒ 必绿。
# ---------------------------------------------------------------------------
def test_doc_sync_normal_state_is_green(baseline_sandbox) -> None:
    assert doc_sync.check() is True
    assert doc_sync.main(["--check"]) == 0
    assert doc_sync.main([]) == 0  # 缺省等价 --check


# ---------------------------------------------------------------------------
# ① + TX281③ 塌陷注入腿：逐支取数口在内存打回空/零 ⇒ --check 非零 / check() False。
# 参数化到每一支，任一支取数口塌陷都能被这门咬住。
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("port", sorted(_COLLAPSE))
def test_doc_sync_collapse_injection_is_red(baseline_sandbox, monkeypatch, port) -> None:
    monkeypatch.setattr(doc_sync, port, _COLLAPSE[port])
    assert doc_sync.check() is False, f"取数口 {port} 塌陷成空/零，门却未红"
    assert doc_sync.main(["--check"]) == 1, f"取数口 {port} 塌陷，--check 退出码却为 0"


# ---------------------------------------------------------------------------
# ② 篡改一条机器事实值（非零错值）⇒ 必红（证明这门不只防"空"，也防"改了个不对的数"）。
# ---------------------------------------------------------------------------
def test_doc_sync_tampered_fact_value_is_red(baseline_sandbox, monkeypatch) -> None:
    real = doc_sync._test_file_count()
    tampered = real + 1  # 非零、看似合理的错值
    monkeypatch.setattr(doc_sync, "_test_file_count", lambda: tampered)
    assert doc_sync.check() is False
    assert doc_sync.main(["--check"]) == 1


# ---------------------------------------------------------------------------
# ③ 扫描面塌陷地板：各取数口现算必须 > 0（不写死"应为几"，只锁"非空非零"）。
# 与塌陷注入腿天然耦合：地板为真 ⇒ 打回空/零必改投影器输出 ⇒ 注入腿才有杀伤力；
# 一旦某支取数口静默返回空（例如路径搬走），地板先红、暴露盲区而非把红搬进别的账。
# ---------------------------------------------------------------------------
def test_doc_sync_scan_surface_floor_positive() -> None:
    assert len(doc_sync._tpl_list()) > 0, "模板清单取数口塌陷为空"
    assert len(doc_sync._route_kinds()) > 0, "RouteKind 取数口塌陷为空"
    assert len(doc_sync._help_topics()) > 0, "帮助 topic 取数口塌陷为空"
    assert doc_sync._test_file_count() > 0, "测试文件数取数口塌陷为零"
    assert doc_sync._config_key_count() > 0, "config 字段数取数口塌陷为零"
    assert len(doc_sync._tracked_files()) > 0, "哈希清单范围取数口塌陷为空"


# ---------------------------------------------------------------------------
# ④ 杀伤力自证：塌陷注入必须真正改变投影器输出。
# 若有人把这根"新腿"拔成空操作（injected == baseline），本用例当场红 ⇒
# 反向自测不可能退化成"注毒没生效却仍判绿"的空跑假绿。
# ---------------------------------------------------------------------------
def test_doc_sync_collapse_injection_has_killing_power(baseline_sandbox, monkeypatch) -> None:
    real = doc_sync._test_file_count()
    monkeypatch.setattr(doc_sync, "_test_file_count", lambda: 0)
    injected = doc_sync.build_document()
    assert f"测试文件数：{real}" in baseline_sandbox
    assert "测试文件数：0" in injected
    assert injected != baseline_sandbox, "塌陷注入未改变投影器输出 ⇒ 反向自测退化为空跑假绿"
