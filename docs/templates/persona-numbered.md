<!-- @schema:BEGIN
sections: 边界与红线? | 来源?
params:
- persona_id | text | auto:persona_dir_id | req | nonempty
- persona_source | text | literal | opt | any
- owner_board | text | auto:category_owner_board | req | nonempty
@schema:END -->

# 模板：persona-numbered（零 markdown 标题的编号型人格档 · 唯一模板源）

本文件是「整页只用 `N.` / `N.N` 纯文本编号、**一个 markdown 标题都没有**」这类人格档
（现册一页：`personas/shorekeeper/identity.md`，现算 H2 数 0）的唯一模板。

## 骨架怎么从语料真形长出来（席 S62，2026-09-22）

判据 `check_sections` 只看 `##` 级标题（`_H2_RE`）。该页 H2 数 **0**：若沿用它旧挂的 `persona` 骨架
（`身份设定 | 表达规范 | 边界与红线` 三枚必选），就会凭空造出 3 枚 `SECTION_MISSING`
（席 S55 内存实算与本席复算同为 3）。所以本骨架的形态必须**显式声明「零标题」**：

- `sections` 只留两枚**可选**节（`边界与红线`、`来源`）＝「这页将来若分节，只准分成这两节」。
- 页内现有 `1.` / `2.1` 等编号是**散文大纲**，不是标题，判据看不见也不该看见 ⇒ 本骨架不假装管它。
- 若将来给该页加任何 `##` 标题而不在本清单内 ⇒ `SECTION_UNKNOWN` 判红（严判保留，不是放宽）。

> 大纲编号被 `doc_fact_discipline` 误判为裸阈值／裸计数（该页 3 行里的 `3.6` / `4.4`）属**判据标定面**，
> 已 PARK（P-S55-4，S46 简报第 3 项「成语与操作配方误伤」同族），本席不改判据。

## 怎么用（内容页侧）

```markdown
---
template: persona-numbered
params:
  persona_id: shorekeeper
  owner_board: B10
---
```

- **本席不动人格正文**：语气、红线文本、设定事实一字不削。

## 骨架（新页照抄；机器段由 --write 注入，节名必须逐字等于 @schema sections）

<!-- TEMPLATE-AUTO:BEGIN -->
- persona_id：{{fact:persona_id}}
- persona_source：{{fact:persona_source}}
- owner_board：{{fact:owner_board}}
<!-- TEMPLATE-AUTO:END -->

## @schema 字段语义（门侧口径）

- `sections`：全可选；空 H2 页天然合规，出现表外节 / 乱序 / 重节仍各自独立判红。
- `params` 五列 `key | kind | source | req | domain`（全 `literal`，均有既存事实来源）。
- 渲染区 `{{fact:KEY}}` 的 KEY 必须在 params 内且被消费（否则 `DEAD_PARAM`）。
- 字节确定性：LF 写盘、声明序、机器段零时间戳 ⇒ 两次 `--write` 字节相等。
- **落地依赖**：同 `persona-provenance`——`classify()` 未分簇之前该类接不到页（MISMATCH 在册判据）。
