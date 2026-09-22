<!-- @schema:BEGIN
sections: 身份设定 | 表达规范 | 边界与红线 | 来源?
params:
- persona_id | text | auto:persona_dir_id | req | nonempty
- persona_source | text | literal | opt | any
- owner_board | text | auto:category_owner_board | req | nonempty
@schema:END -->

# 模板：persona（人格 / 世界观知识件 · 唯一模板源）

本文件是人格资产类内容件（类别 `persona-knowledge`，`personas/**.md`）的唯一模板。该类受工作区规则第 8 条保护：语气与设定不可为凑结构而改写。
一类内容一份模板；内容页通过页首 front-matter 调用，`@schema` 覆盖不到的字段一律规格外，由 `scripts/doc_template_sync.py --check` 判红。渲染器只重写 `TEMPLATE-AUTO` 标记内的机器段。

## 怎么用（内容页侧）

```markdown
---
template: persona
params:
  persona_id: （必填）
  persona_source: （可省略）
  owner_board: （必填）
---
```

- **本席不动人格正文**：模板先建（G-T5/三角闭合要它存在），页侧转换是否可行、是否改为类别级豁免，按 SPEC-TARGETS §3-E3 交用户裁，证据在 `SEAT-S4.md`。
- `来源?` 可选节承接「来源：…」这类清洗溯源节。

## 骨架（新页照抄；机器段由 --write 注入，节名必须逐字等于 @schema sections）

<!-- TEMPLATE-AUTO:BEGIN -->
- persona_id：{{fact:persona_id}}
- persona_source：{{fact:persona_source}}
- owner_board：{{fact:owner_board}}
<!-- TEMPLATE-AUTO:END -->

## 身份设定

## 表达规范

## 边界与红线

## 来源（可选）

## @schema 字段语义（门侧口径）

- `sections`：有序节序列，尾缀 `?`＝可选；必填缺失 / 表外节 / 顺序偏离各独立码。
- `params` 五列 `key | kind | source | req | domain`（本模板全 `literal`，无现算参数）。
- 渲染区 `{{fact:KEY}}` 的 KEY 必须在 params 内且被消费（否则 `DEAD_PARAM`）。
- 字节确定性：LF 写盘、声明序、机器段零时间戳 ⇒ 两次 `--write` 字节相等。
