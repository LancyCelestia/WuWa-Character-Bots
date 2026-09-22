<!-- @schema:BEGIN
sections: 登记入口 | 壳与注入 | 契约锚点
params:
- builder_id | text | auto:mica_builder_id | req | nonempty
- contract_home | text | literal | req | nonempty
- theme_tokens_ref | text | literal | opt | any
@schema:END -->

# 模板：card-fstring（f-string 直拼卡 · 唯一模板源）

本文件是 `surface="code"` 类 `fstring-card` 的 schema 契约。在册账＝登记制 `_BUILDERS`（`tests/test_mica_builders_contract.py` 执法），未登记的直拼卡即红。
一类内容一份模板；内容页通过页首 front-matter 调用，`@schema` 覆盖不到的字段一律规格外，由 `scripts/doc_template_sync.py --check` 判红。渲染器只重写 `TEMPLATE-AUTO` 标记内的机器段。

## 怎么用（内容页侧）

```markdown
---
template: card-fstring
params:
  builder_id: （必填）
  contract_home: （必填）
  theme_tokens_ref: （可省略）
---
```

- 壳与通水件走共享 mica 壳，禁止逐卡手抄 CSS。
- DOM 锚点与色值由视觉审计门钉帧，改前读渲染契约。

## 骨架（新页照抄；机器段由 --write 注入，节名必须逐字等于 @schema sections）

<!-- TEMPLATE-AUTO:BEGIN -->
- builder_id：{{fact:builder_id}}
- contract_home：{{fact:contract_home}}
- theme_tokens_ref：{{fact:theme_tokens_ref}}
<!-- TEMPLATE-AUTO:END -->

## 登记入口

## 壳与注入

## 契约锚点

## @schema 字段语义（门侧口径）

- `sections`：有序节序列，尾缀 `?`＝可选；必填缺失 / 表外节 / 顺序偏离各独立码。
- `params` 五列 `key | kind | source | req | domain`（本模板全 `literal`，无现算参数）。
- 渲染区 `{{fact:KEY}}` 的 KEY 必须在 params 内且被消费（否则 `DEAD_PARAM`）。
- 字节确定性：LF 写盘、声明序、机器段零时间戳 ⇒ 两次 `--write` 字节相等。
