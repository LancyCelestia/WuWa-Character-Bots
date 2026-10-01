"""llm_chain_selfcheck 单元回归（W1-重启自检门）。

- 注册表扫描：只收含 model_registry 的载荷，坏件跳过；
- 应急地板判定：只有 127.0.0.1:11434 直连档算地板（经网关的不算）；
- 三跳判定：GO 仅当网关可达 ∧ 地板在位 ∧ 地板可达；各失败面出对应
  NO-GO 行。probe 全程注桩，零真实网络。
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.llm_chain_selfcheck import (
    find_emergency_floor,
    run_selfcheck,
    scan_registry_payloads,
)


def _write_registry(tmp_path: Path, name: str, registry: dict) -> Path:
    path = tmp_path / name
    path.write_text(
        json.dumps({"model_registry": registry}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def test_scan_registry_payloads_skips_invalid(tmp_path: Path) -> None:
    _write_registry(tmp_path, "runtime_settings_a.json", {"ch": {"base_url": "x"}})
    (tmp_path / "runtime_settings_broken.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "runtime_settings_empty.json").write_text("{}", encoding="utf-8")
    (tmp_path / "unrelated.json").write_text("{}", encoding="utf-8")
    payloads = scan_registry_payloads(tmp_path)
    assert len(payloads) == 1
    assert "ch" in payloads[0]["model_registry"]


def test_scan_registry_payloads_missing_dir(tmp_path: Path) -> None:
    assert scan_registry_payloads(tmp_path / "nope") == []


def test_find_emergency_floor_requires_loopback_ollama() -> None:
    payloads = [
        {"model_registry": {"axon": {"base_url": "http://127.0.0.1:8090/v1"}}},
        {
            "model_registry": {
                "floor": {"base_url": "http://127.0.0.1:11434/v1"},
            }
        },
    ]
    assert find_emergency_floor(payloads) == "http://127.0.0.1:11434/v1"
    # 只有经网关的应急档 = 没有地板。
    assert find_emergency_floor(payloads[:1]) is None


def _selfcheck(probe_results: dict[int, bool], payloads: list[dict]):
    return run_selfcheck(
        gateway_base_url="http://127.0.0.1:8090/v1",
        registry_payloads=payloads,
        probe=lambda host, port: probe_results.get(port, False),
    )


def test_selfcheck_go_when_all_legs_ok() -> None:
    payloads = [
        {
            "model_registry": {
                "axon": {"base_url": "http://127.0.0.1:8090/v1"},
                "floor": {"base_url": "http://127.0.0.1:11434/v1"},
            }
        }
    ]
    result = _selfcheck({8090: True, 11434: True}, payloads)
    assert result.verdict == "GO"
    assert result.lines[0] == "llm selfcheck: GO"


def test_selfcheck_no_go_when_gateway_down() -> None:
    payloads = [{"model_registry": {"floor": {"base_url": "http://127.0.0.1:11434/v1"}}}]
    result = _selfcheck({8090: False, 11434: True}, payloads)
    assert result.verdict == "NO-GO"
    assert result.gateway_ok is False
    assert any("UNREACHABLE" in line for line in result.lines)


def test_selfcheck_no_go_when_floor_missing() -> None:
    result = _selfcheck({8090: True}, [{"model_registry": {"axon": {"base_url": "http://127.0.0.1:8090/v1"}}}])
    assert result.verdict == "NO-GO"
    assert result.emergency_floor_url is None
    assert any("MISSING" in line for line in result.lines)


def test_selfcheck_no_go_when_ollama_down() -> None:
    payloads = [{"model_registry": {"floor": {"base_url": "http://127.0.0.1:11434/v1"}}}]
    result = _selfcheck({8090: True, 11434: False}, payloads)
    assert result.verdict == "NO-GO"
    assert result.emergency_floor_url is not None
    assert result.ollama_ok is False
    assert any("Ollama" in line for line in result.lines)
