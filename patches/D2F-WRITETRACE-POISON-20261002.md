# 工单 D2F-WRITETRACE-POISON-20261002 — 席 D2F 修注毒腿最后一枚红

## §1 现状核实（file:line）

- 实跑（17:1x，venv python）：`pytest tests/test_store_write_trace_d2.py -q` ⇒ **1 failed, 16 passed**；红＝`test_poison_gate_self_proves_the_static_scan_is_live`，`AssertionError: []`（tests/test_store_write_trace_d2.py:584 的 `assert any(...), violations`，violations＝空清单）。
- 直接机理：该腿注毒串只替换 quirks.py **ok/noop 腿**那一枚 `_record`（tests/test_store_write_trace_d2.py:576-580 → quirks.py:392）；但 `QuirkStore.retire` 本有**两腿**留痕——except 失败腿 quirks.py:389 `self._record("retire", OUTCOME_FAILED, ...)` 仍在 ⇒ `_is_traced`（tests/test_store_write_trace_d2.py:504-513，全函数 AST 判据）仍判 True ⇒ 不出「没有留痕」违规 ⇒ 清单空。
- 写面归属：红根因在**测试件**（注毒构造时按「单枚 _record」假设写），生产件 quirks.py 两腿留痕各司其职、**无误不需改**；`domains/core/write_trace.py`（席 L2 面）与本红无涉（扫描只读 quirks.py 源文本）。测试件 mtime 2026-10-02 16:24（< 16:30 门，非他席在飞）；git 状态＝测试件 untracked、quirks.py modified（席 D2 未入库 WIP）。

## §2 根因与修法

- 根因：注毒只抹 `retire` 两腿之一，AST 尺按「函数内任一 `_record` 调用」判——except 腿替被抹的 ok/noop 腿顶账，自证失效（假绿），恰是本腿要防的那类盲区在注毒样本自身复现。
- 修法（仅 tests/test_store_write_trace_d2.py:565-593 注毒腿内）：注毒改为**两腿同批抹净**——①原 ok/noop 腿替换不动；②追加第二枚 replace 把 except 腿 `            self._record("retire", OUTCOME_FAILED, type(exc).__name__)`（12 空格缩进，quirks.py:389 原样）抹成 `            pass  # .record( 注毒：失败腿的留痕一并抹掉`；`poisoned != original` 断言扩为「两步都打中」；`.record(` 子串留存断言不变（文本尺假绿性质保留）；docstring 补一句「两腿都要抹净，否则 except 腿顶账」。16 枚绿腿判据零触碰。

## §3 判据读数（实跑末行原样）

- 修后全件：`pytest tests/test_store_write_trace_d2.py -q`（venv python，带卫生前缀）⇒ `.................                        [100%]` / **`17 passed in 3.54s`**。
- lint：`ruff check tests/test_store_write_trace_d2.py --no-cache` ⇒ **`All checks passed!`**（ruff 0.16.4，未打回 L1 的绿）。

## §4 净新增红 A/B

- A（本件修前基线，17:1x 实跑）＝`1 failed, 16 passed`（红＝注毒腿自身）；修后＝`17 passed`，**净新增红 0**。
- B（他面外溢）：只改测试件注毒腿内部＋docstring，16 枚绿腿判据零触碰、生产件零触碰；无他件被牵动（本件 untracked，quirks.py 工作树 diff 与席 D2 交付一致、本席未动）。
- 注毒自证（改错必红）已由 A/B 现算坐实：单腿注毒＝假绿红在断言（改前态），双腿注毒＝扫描器判出「QuirkStore.retire 没有留痕」⇒ 绿；若哪天 quirks.retire 留痕写法再变，两步 replace 的联合断言当场改口「注毒没打中」。

## §5 未尽事项

- `write_trace.py`（席 L2 在写）本红无涉、未读未动；若 L2 改动 `WriteTrace` 公开面无需回头照顾本件（本件只消费 quirks.py 源文本与三 store 公开口）。
- 本件与其余 D2 WIP 均未入库（untracked）；提交由用户/主会话执行，本席零 git 写。
- 工单与测试件成对交付：删任何一边，另一边的「注毒没打中」断言会拦住静默漂移。
