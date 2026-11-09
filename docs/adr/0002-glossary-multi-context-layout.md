# ADR-0002 · 术语表按 multi-context 布局落位，不建根目录单文件

- 状态：已采纳（2026-10-19）
- 影响面：`GLOSSARY-MAP.md`（新）、`plugins/bot_unified_runtime/GLOSSARY.md`（新）、`docs/agents/domain.md`
- 相关：issue #7（b · 命名/说明规范回到与代码一致的基线 + 术语表首立）

## 背景

本仓长期没有术语表。结果是同一批词在不同文档里意思不同，典型如
「在册 / 接线 / 已执法」被混成一句「已经做了」，「待生效 / 已生效」被混成「完成了」。

issue #7 最初提议的是**在仓库根建一个 `GLOSSARY.md`**。但本仓已经有在册的布局结论：
`docs/agents/domain.md` 明确写着 **multi-context**——子项目各一份 `GLOSSARY.md`，
根目录一份 `GLOSSARY-MAP.md` 指向它们；同一文件当时还写着「词条文件尚无，首次落词条时才建」（该句已随本 ADR 失效）。
读文档的那批技能（`/domain-modeling`、`/grill-with-docs`、`/improve-codebase-architecture`）
就是按这个布局去找词条的。

## 决定

按**已在册的布局**落位，不另起根目录单文件：

```
/GLOSSARY-MAP.md                         ← 索引，只指路
/plugins/bot_unified_runtime/GLOSSARY.md ← 词条真身（当前唯一 context）
```

- 词条只写一份，位置在主包（本仓实际上只有一个内容 context）。
- `GLOSSARY-MAP.md` 只做索引：将来出现第二个 context，在那里加一行，不建第二份索引。
- 词条只收「同一个词被当成两三种意思」的那批；一眼能懂、或代码里已有唯一真身的名字不收。

## 为什么不建根目录单文件

- 会与 `docs/agents/domain.md` 撞成第二份口径：同一个问题两个答案，下一个人不知道信哪份。
- 会让按布局找词条的技能**找错地方**：它们先读 `GLOSSARY-MAP.md`，根目录多一个同名文件只会制造歧义。

## 后果

- `docs/agents/domain.md` 里那节「现状」已同批改写为指向本 ADR 的落位（2026-10-19 完成，`test_glossary_has_a_single_true_source_and_is_indexed` 锁住）。
- 词条是**活件**：不追求一次写全，只要求同一个词只有一处定义。
- 本决定不引入任何机器门。术语表的约束力来自评审，不来自测试。
