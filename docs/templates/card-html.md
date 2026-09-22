<!-- @schema:BEGIN
sections: 契约锚点 | 变量供给 | 降级路径
params:
- card_id | text | auto:card_list_id | req | nonempty
- contract_home | text | literal | req | nonempty
- theme_tokens_ref | text | literal | opt | any
@schema:END -->

# 模板：card-html（卡片模板（非 Jinja 的裸 HTML 卡） · 唯一模板源）

本文件是 `surface="code"` 类 `html-card` 的 schema 契约：描述一张直拼 HTML 卡必须满足的渲染契约字段，不是拿来生成 md 页的骨架。
一类内容一份模板；内容页通过页首 front-matter 调用，`@schema` 覆盖不到的字段一律规格外，由 `scripts/doc_template_sync.py --check` 判红。渲染器只重写 `TEMPLATE-AUTO` 标记内的机器段。

## 怎么用（内容页侧）

```markdown
---
template: card-html
params:
  card_id: （必填）
  contract_home: （必填）
  theme_tokens_ref: （可省略）
---
```

- 契约标识符（`class="card"` 锚、`SHADOW_CSS_VARS` 族名、`theme_tokens` 变量）一字不动。
- 无 `<meta viewport>`、body 透明、字重 ≤700、动画在 `.card` 内、失败→纯文本兜底。

## 骨架（新页照抄；机器段由 --write 注入，节名必须逐字等于 @schema sections）

<!-- TEMPLATE-AUTO:BEGIN -->
- card_id：{{fact:card_id}}
- contract_home：{{fact:contract_home}}
- theme_tokens_ref：{{fact:theme_tokens_ref}}
<!-- TEMPLATE-AUTO:END -->

## 契约锚点

## 变量供给

## 降级路径

## @schema 字段语义（门侧口径）

- `sections`：有序节序列，尾缀 `?`＝可选；必填缺失 / 表外节 / 顺序偏离各独立码。
- `params` 五列 `key | kind | source | req | domain`（本模板全 `literal`，无现算参数）。
- 渲染区 `{{fact:KEY}}` 的 KEY 必须在 params 内且被消费（否则 `DEAD_PARAM`）。
- 字节确定性：LF 写盘、声明序、机器段零时间戳 ⇒ 两次 `--write` 字节相等。
