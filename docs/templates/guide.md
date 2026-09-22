<!-- @schema:BEGIN
sections: 用途 | 读者 | 正文 | 参考?
params:
- guide_scope | text | literal | req | nonempty
- owner_board | text | auto:category_owner_board | req | nonempty
@schema:END -->

# 模板：guide（指南 / 叙事件（docs 顶层杂项） · 唯一模板源）

本文件是 `docs/` 顶层其余指南与叙事件（类别 `doc-misc`）的唯一模板。它与 `handbook` 的差别：单一主题、不承担全史账。
一类内容一份模板；内容页通过页首 front-matter 调用，`@schema` 覆盖不到的字段一律规格外，由 `scripts/doc_template_sync.py --check` 判红。渲染器只重写 `TEMPLATE-AUTO` 标记内的机器段。

## 怎么用（内容页侧）

```markdown
---
template: guide
params:
  guide_scope: （必填）
  owner_board: （必填）
---
```

- 正文里指向代码的，一律写当前真身路径，不写旧路径。
- 会漂移的计数一律指向真身或机器册。

## 骨架（新页照抄；机器段由 --write 注入，节名必须逐字等于 @schema sections）

<!-- TEMPLATE-AUTO:BEGIN -->
- guide_scope：{{fact:guide_scope}}
- owner_board：{{fact:owner_board}}
<!-- TEMPLATE-AUTO:END -->

## 用途

## 读者

## 正文

## 参考（可选）

## @schema 字段语义（门侧口径）

- `sections`：有序节序列，尾缀 `?`＝可选；必填缺失 / 表外节 / 顺序偏离各独立码。
- `params` 五列 `key | kind | source | req | domain`（本模板全 `literal`，无现算参数）。
- 渲染区 `{{fact:KEY}}` 的 KEY 必须在 params 内且被消费（否则 `DEAD_PARAM`）。
- 字节确定性：LF 写盘、声明序、机器段零时间戳 ⇒ 两次 `--write` 字节相等。
