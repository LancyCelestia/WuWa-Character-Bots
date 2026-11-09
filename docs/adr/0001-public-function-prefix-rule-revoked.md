# ADR-0001 · 撤销「公开函数必须以动词前缀开头」的硬约束

- 状态：已采纳（2026-10-19）
- 影响面：`docs/boards/_conventions.md` §二「命名规范」、`docs/boards/B10-engineering-governance/naming-conventions/identifier-naming.md`
- 相关：issue #7（b · 命名/说明规范回到与代码一致的基线 + 术语表首立）

## 背景

2026-09-21 的统一规范里有一条硬约束：公开函数必须以 `build_*` / `get_*` / `is_*` / `has_*` /
`resolve_*` / `load_*` / `save_*` / `handle_*` / `check_*` / `normalize_*` / `sanitize_*` 之一开头。

这条规范从落地那天起就没有被执行过，也没有被任何机器门管着（`identifier-naming.md` 自己承认
「私有函数被跨模块调用、常量表命名不统一、docstring 缺失 = **无静态门**」）。
结果是它既没约束住代码，也没提示过任何人。

## 现算

口径（可复跑，AST，非文本匹配）：

- 扫描面：`plugins/bot_unified_runtime/**/*.py`
- 排除：`__init__.py`；文件头 600 字符内含 `Compat shim` 或 `再导出` 的垫片
- 取样：模块级 `def` / `async def`，名字不以 `_` 开头（公开函数）
- 命中：名字以上述 11 个前缀之一开头

读数（2026-10-19）：

```
total_public_module_level_funcs = 2401
prefix_ok                      =  616
violating                      = 1785  → 74.3%
```

复跑：

```python
import ast, pathlib
P = ("build_","get_","is_","has_","resolve_","load_","save_",
     "handle_","check_","normalize_","sanitize_")
tot = ok = 0
for p in pathlib.Path("plugins/bot_unified_runtime").rglob("*.py"):
    if "__pycache__" in p.parts or p.name == "__init__.py":
        continue
    src = p.read_text(encoding="utf-8", errors="replace")
    if "Compat shim" in src[:600] or "再导出" in src[:600]:
        continue
    for n in ast.parse(src).body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith("_"):
            tot += 1
            ok += n.name.startswith(P)
print(tot, ok, f"{(tot-ok)/tot*100:.1f}% violating")
```

## 决定

**撤销「必须以此开头」**，保留两件东西：

1. **动词-语义对照**（`build_` 造对象 / `get_` 取值 / `is_`·`has_` 判真假 / `resolve_` 归一点 /
   `check_` 可能拦停 / …）。这条有真信息量：它告诉调用方**失败语义**。
2. **同一语义只用同一个动词**。这是能真正执行的那条——同一个概念一半 `check_` 一半 `verify_`，
   调用方就会猜错它会不会拦流程。

## 为什么不是「让代码满足规范」

- 2400 量级的函数改名，收益是「名字好看」，代价是本仓已经反复吃过的那类事故：改名即断链
  （`identifier-naming.md` 自己写着「板块树靠 RouteKind 与 capability_id 认领能力，改名即断链」）。
- 一条大多数代码都违反的规范，信息量是零；留着它只会训练下一个人无视规范。
  这与本仓「门禁假绿」被列为 P1 是同一个道理。

## 后果

- 新代码**不再**因为「函数名没以动词开头」被判违规；评审只问「同一语义是否用了同一个动词」。
- 本决定**不**放松任何有牙的门（`test_board_taxonomy_gate`、`test_documentation_consistency`、
  `doc_ownership_sync --check` 全部不受影响）。
- 74.3% 这个数是**当时值**：函数会长、会改名。任何引用都必须重跑上面的复跑脚本，
  不要抄这个数（AGENTS 规则 10）。
