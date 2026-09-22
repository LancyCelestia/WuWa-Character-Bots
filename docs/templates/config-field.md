<!-- @schema:BEGIN
sections: 键与类型 | 说明形状 | 取值域与默认
params:
- field_key | text | auto:config_field_key | req | nonempty
- description_shape | text | literal | req | nonempty
- catalog_home | text | literal | opt | any
@schema:END -->

# 模板：config-field（配置字段（代码内声明） · 唯一模板源）

本文件是 `surface="code"` 类 `config-field` 的 schema 契约：`config.py` 每字段`description=` 的统一形状（固定顺序：一句功能 / 取值域 / 默认值）。
一类内容一份模板；内容页通过页首 front-matter 调用，`@schema` 覆盖不到的字段一律规格外，由 `scripts/doc_template_sync.py --check` 判红。渲染器只重写 `TEMPLATE-AUTO` 标记内的机器段。

## 怎么用（内容页侧）

```markdown
---
template: config-field
params:
  field_key: （必填）
  description_shape: （必填）
  catalog_home: （可省略）
---
```

- 只改说明正文，字段名、类型、默认值、校验器是契约标识符，一字不动。
- 说明必须同步进 `docs/config-catalog-full.md`（生成物，跑 `doc_sync --check`）。

## 骨架（新页照抄；机器段由 --write 注入，节名必须逐字等于 @schema sections）

<!-- TEMPLATE-AUTO:BEGIN -->
- field_key：{{fact:field_key}}
- description_shape：{{fact:description_shape}}
- catalog_home：{{fact:catalog_home}}
<!-- TEMPLATE-AUTO:END -->

## 键与类型

## 说明形状

## 取值域与默认

## @schema 字段语义（门侧口径）

- `sections`：有序节序列，尾缀 `?`＝可选；必填缺失 / 表外节 / 顺序偏离各独立码。
- `params` 五列 `key | kind | source | req | domain`（本模板全 `literal`，无现算参数）。
- 渲染区 `{{fact:KEY}}` 的 KEY 必须在 params 内且被消费（否则 `DEAD_PARAM`）。
- 字节确定性：LF 写盘、声明序、机器段零时间戳 ⇒ 两次 `--write` 字节相等。
