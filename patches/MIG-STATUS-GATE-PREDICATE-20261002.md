# 工单 · MIG —— MigrationStatus 赋值门量具收窄（2026-10-02 下午窗）

> ⚠ **本工单由主会话代写**：席 MIG 于 16:21 完成全部修复与自测后被平台并发墙收走（`user concurrency limit exceeded`，在飞 849 秒），工单未及落盘。以下全部读数由主会话在盘上现算复核（实跑末行原样），改动面以本单 §2 记账。**判据归属＝席 MIG**。

## ① 现状核实（file:line）

- 修复前 `pytest tests/test_migration_status_assignment_gate.py -q` ＝ `1 failed, 14 passed`（探索席实跑，2026-10-02 15:4x）。
- 红＝`test_status_is_not_derived_from_control_plane`，断言原文：`这些 status= 赋值不是字面枚举成员（派生式＝状态可由读数算出来）：["line 123: 'bound'", 'line 200: placeholder']`。
- 机理：AST 门谓词扫全文件 `node.arg == "status"` 的 Call keyword，只放行 `MigrationStatus.X` 属性形态；而 `outbound_registry.py` 存在互不相干的第二状态概念——`TransportEntry` 绑定生命周期（字符串字面量）：`:123` `status="bound"`、`:185→:200` 经局部别名 `status=placeholder`。两者均非控制面派生。另 `:359-368` 的 AnnAssign 缺省计数断言 3 枚，实际 4 枚（`:101` `TransportEntry.status: str = "placeholder"` + 三枚接管条目 `status: MigrationStatus = MigrationStatus.LEGACY`）——只修 keyword 腿会挪红到计数腿。
- 初判＝**测试量具过宽**（测试错），非产品缺口：生产侧零 control_plane import、全部 MigrationStatus 出现均为字面缺省 `LEGACY`。

## ② 改法与理由（只动测试件；生产侧一字未动）

1. **Keyword 腿允许集改为封闭集**：`MigrationStatus.X` 属性形态 ∪ `TRANSPORT_BINDING_LIFECYCLE_LITERALS = frozenset({"bound", "placeholder"})`（测试件 `:109-115`，注释记明成员名已现算核对不在 `MigrationStatus` 枚举内、这是与 MigrationStatus 互不相干的第二状态概念）∪ 名字解析到该字面量的**局部别名**（`:263` 助手现算 `:185 placeholder = "placeholder"` → `:200 status=placeholder`，且该名字未被重新赋值）。其余一切（函数调用/下标/非 MigrationStatus 属性链/未知名字）仍然红 ⇒ **派生式判据零放松**（结构性：函数调用不可能命中封闭集三形之一）。
2. **AnnAssign 腿按注解类型过滤**（`:337-354`）：只数注解为 `MigrationStatus`（Name 或 Attribute 形态）的 `status` 字段缺省 ⇒ `TransportEntry.status: str` 按注解排除，期望恰 3 枚恢复成立。
3. 同件 `:59:84` RUF100（`# noqa: E402` 未启用规则）：删 noqa、意图改普通注释。

## ③ 判据读数（实跑末行原样）

```
...............                                                          [100%]
15 passed in 3.52s
```
（主会话 16:3x 复跑；ruff：`All checks passed!`。改前基线 `1 failed, 14 passed`。）

## ④ 净新增红 A/B

- 本件净新增红 **0**：15 发全绿（改前 14 绿 1 红）；无邻域件被牵动（量具只扫 `outbound_registry.py` 单文件，生产件未动）。

## ⑤ 未尽事项

- 注毒腿形态说明：谓词允许集为封闭集（枚举属性 ∪ 两个具名字面量 ∪ 字面量别名），**函数调用/下标/未知名字结构性不可能通过**＝判据牙齿在结构上；若后续有人给 `outbound_registry.py` 加第四种合法 `status=` 形态，须同批扩此白名单并给成员名证明（同 `MigrationStatus` 无 `bound/placeholder` 成员的现算口径）。
- 该测试件为未跟踪新件（G1c 主席面），入库由用户执行。
