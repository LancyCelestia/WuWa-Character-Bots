<!-- @schema:BEGIN
sections: 文档族谱与权威链 | 现行事实速查 | 未完成总账 | 波次总账? | 权威正文?
freeform: on
params:
- handbook_scope | text | literal | req | nonempty
- owner_board | text | auto:category_owner_board | req | nonempty
- refresh_cmd | text | literal | opt | any
@schema:END -->

# 模板：handbook（单一活文档（总账 / 权威正文）件 · 唯一模板源）

本文件是「一份活文档承载全史」类内容件（类别 `handbook`，现网唯一实例＝`docs/HANDBOOK.md`）的唯一模板：族谱、现行事实、跨波次总账、权威正文四层。
一类内容一份模板；内容页通过页首 front-matter 调用，`@schema` 覆盖不到的字段一律规格外，由 `scripts/doc_template_sync.py --check` 判红。渲染器只重写 `TEMPLATE-AUTO` 标记内的机器段。

## 怎么用（内容页侧）

```markdown
---
template: handbook
params:
  handbook_scope: （必填）
  owner_board: （必填）
  refresh_cmd: （可省略）
---
```

- **波次总账是 append-only 开放序列**：新波次必然追加一节。`@schema` 没有「同类节可重复」这一槽位，故本模板只把四层稳定结构设为骨架，逐波节名的枚举缺口按 PARKED 交回（见 `SEAT-S4.md`）。在那之前，本文类内容件不得为凑门去改写历史节名。
- 一切会随代码漂移的计数写「以机器册 `docs/auto-facts.md` 为准」。

## 骨架（新页照抄；机器段由 --write 注入，节名必须逐字等于 @schema sections）

<!-- TEMPLATE-AUTO:BEGIN -->
- handbook_scope：{{fact:handbook_scope}}
- owner_board：{{fact:owner_board}}
- refresh_cmd：{{fact:refresh_cmd}}
<!-- TEMPLATE-AUTO:END -->

## 文档族谱与权威链

## 现行事实速查

## 未完成总账

## 波次总账（可选）

## 权威正文（可选）

## @schema 字段语义（门侧口径）

- `sections`：有序节序列，尾缀 `?`＝可选；必填缺失 / 表外节 / 顺序偏离各独立码。
- `params` 五列 `key | kind | source | req | domain`（本模板全 `literal`，无现算参数）。
- 渲染区 `{{fact:KEY}}` 的 KEY 必须在 params 内且被消费（否则 `DEAD_PARAM`）。
- 字节确定性：LF 写盘、声明序、机器段零时间戳 ⇒ 两次 `--write` 字节相等。
