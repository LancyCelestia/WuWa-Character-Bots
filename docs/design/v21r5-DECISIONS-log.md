# v21r5 DECISIONS-LOG-2 席工作日志 — 用户三裁决落账

- 日期：2026-09-21
- 席位：DECISIONS-LOG-2（**重派**：前任死于平台故障，零进度零落盘，本席从零起跑；开场即建本 log 小步落盘）
- 任务：把用户三项裁决落账到 coordination 状态区 + HANDBOOK §34.8；**零代码改动**。
- 三裁决原文：①U17-CAMPUS-WIRE=实施（两裁定点按席位推荐接受：review 门 fail-closed、1501 字零改动）——实施席在飞；②kb_drift=不重建（维持现状挂账，此后不再列为待决项）；③`aged 130` 数字续位望卫=执行（FIX-N1b 席已收口落码）。

## 改动清单（仅两文件+本 log）

1. `docs/design/v21r5-coordination.md`：状态区末尾追加「用户三裁决」条目（含对应席位状态：U17-IMPL 在飞 / FIX-N1b 已收口 FIXN1B-SEAT DONE / kb_drift 终局裁定；并注遗留用户项①②③出清、剩④⑤）。
2. `docs/HANDBOOK.md` §34.8：末尾追加一条目记录三裁决与执行载体（U17=实施席+runbook 终态待回填；kb_drift=纯终局裁定无施工载体；aged 130=FIX-N1b 已落码即载体；kb_drift 此后台账不再列为待办）。
3. **AGENTS.md #43 不动**——分工记明：U17 终态（builder×2+root handler 改管线分发+11 例 xfail 摘牌）由实施完成后的回填席统一落账，避免与本席双写漂移；本席只落裁决本身与执行载体指针。

## wc 对照（写前→写后）

| 文件 | 写前 | 写后 | Δ |
|---|---|---|---|
| docs/design/v21r5-coordination.md | 34 行 | 35 行 | +1 |
| docs/HANDBOOK.md | 2412 行 | 2413 行 | +1 |

标记核验：`用户三裁决` 两文件各恰 1 处（grep -c 实证）。

## 红线自查

- 只改上述两文件+本 log，零代码改动 ✓
- 未预填 U17 实施终态（在飞，明示由回填席统一落账）✓
- 禁 git 写操作 / 禁子代理 ✓；未 commit（共享工作树，提交裁决权在用户）
- kb_drift 数字（ANN=35341 vs chunks=35477，已嵌入 4539）与 FIX-N1b 尾卫改法均引自 v21r5-VERIF-log.md / v21r5-FIXN1B-log.md 原文，零臆造

DECISIONS-SEAT DONE
