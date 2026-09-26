"""统一安全与执行引擎（SAFE-EXEC，规格 `docs/design/safety-execution-engine-spec.md`）的域内包。

本目录按规格 §1 逐件落地：现役 `trust.py`（可信级派生 + 入站打标，S-T-SAFE-2 席，
2026-09-25）、`paths.py`（路径域判定，S-T-SAFE-1 系）、`config_risk.py` /
`consent.py`（参数风险档与同意账，S-T-CONS-1 系）、`action_catalog.py`（动作册）、
`policy.py`（策略裁决点 PDP：动作册 × 可信级 × 风险档的合成裁决口，S-T-SAFE-3 席，
2026-09-25）——规格 §1 表内本目录的件已全部在盘。本 `__init__` 刻意不做任何再导出
（`tests/test_safety_exec_paths.py::test_package_init_does_not_import_siblings` 执法），
消费方一律按模块名 import 真身。
"""
