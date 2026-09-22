<!-- @schema:BEGIN
sections: 模板契约 | 注入上下文 | 降级路径
params:
- template_id | text | auto:card_list_id | req | nonempty
- render_backend | text | auto:render_backend_home | req | nonempty
- theme_tokens_ref | text | literal | opt | any
@schema:END -->

# 模板：card-jinja（卡片模板（Jinja 卡） · 唯一模板源）

本文件是 `surface="code"` 类 `jinja-template` 的 schema 契约：Jinja 卡模板的字段清单与契约锚点。真身住 `domains/render/card_render/templates/`，受 `tests/test_rendering_contract.py` 逐条执法。
一类内容一份模板；内容页通过页首 front-matter 调用，`@schema` 覆盖不到的字段一律规格外，由 `scripts/doc_template_sync.py --check` 判红。渲染器只重写 `TEMPLATE-AUTO` 标记内的机器段。

## 怎么用（内容页侧）

```markdown
---
template: card-jinja
params:
  template_id: （必填）
  render_backend: （必填）
  theme_tokens_ref: （可省略）
---
```

- 模板清单由 `scripts/doc_sync.py` 派生进机器册，本模板不手写枚数。
- 通水件（decor/blobs/玻璃脚注）必须走 `bridge.py` 注入，禁止第二份副本。

## 骨架（新页照抄；机器段由 --write 注入，节名必须逐字等于 @schema sections）

<!-- TEMPLATE-AUTO:BEGIN -->
- template_id：{{fact:template_id}}
- render_backend：{{fact:render_backend}}
- theme_tokens_ref：{{fact:theme_tokens_ref}}
<!-- TEMPLATE-AUTO:END -->

## 模板契约

## 注入上下文

## 降级路径

## @schema 字段语义（门侧口径）

- `sections`：有序节序列，尾缀 `?`＝可选；必填缺失 / 表外节 / 顺序偏离各独立码。
- `params` 五列 `key | kind | source | req | domain`（本模板全 `literal`，无现算参数）。
- 渲染区 `{{fact:KEY}}` 的 KEY 必须在 params 内且被消费（否则 `DEAD_PARAM`）。
- 字节确定性：LF 写盘、声明序、机器段零时间戳 ⇒ 两次 `--write` 字节相等。
