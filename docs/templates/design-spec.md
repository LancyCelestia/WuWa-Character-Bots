<!-- @schema:BEGIN
sections: 目的与范围 | 现状与根因? | 设计 | 接口与字段? | 验收 | 开放问题?
params:
- spec_id | text | literal | req | nonempty
- owner_board | text | auto:category_owner_board | req | nonempty
- spec_status | text | literal | opt | enum:draft,active,archived
@schema:END -->

# 模板：design-spec（架构规格 / 设计文档件 · 唯一模板源）

本文件是「先成文后实现」类规格件（类别 `design-spec`，`docs/design/**`）的唯一模板。规格件只声明决策与契约，不携带实现事实。
一类内容一份模板；内容页通过页首 front-matter 调用，`@schema` 覆盖不到的字段一律规格外，由 `scripts/doc_template_sync.py --check` 判红。渲染器只重写 `TEMPLATE-AUTO` 标记内的机器段。

## 怎么用（内容页侧）

```markdown
---
template: design-spec
params:
  spec_id: （必填）
  owner_board: （必填）
  spec_status: （可省略）
---
```

- **契约标识符（协议字段名、类名、端点）一字不动**；改动走升级流程。
- 本类件数极多且形状分族（SPEC-TARGETS §1-9 建议按前缀拆子模板），单枚 schema 覆盖全部章节名不现实：分族证据与槽位建议按 PARKED 交回，不得为凑门砍字段或加通配槽。

## 骨架（新页照抄；机器段由 --write 注入，节名必须逐字等于 @schema sections）

<!-- TEMPLATE-AUTO:BEGIN -->
- spec_id：{{fact:spec_id}}
- owner_board：{{fact:owner_board}}
- spec_status：{{fact:spec_status}}
<!-- TEMPLATE-AUTO:END -->

## 目的与范围

## 现状与根因（可选）

## 设计

## 接口与字段（可选）

## 验收

## 开放问题（可选）

## @schema 字段语义（门侧口径）

- `sections`：有序节序列，尾缀 `?`＝可选；必填缺失 / 表外节 / 顺序偏离各独立码。
- `params` 五列 `key | kind | source | req | domain`（本模板全 `literal`，无现算参数）。
- 渲染区 `{{fact:KEY}}` 的 KEY 必须在 params 内且被消费（否则 `DEAD_PARAM`）。
- 字节确定性：LF 写盘、声明序、机器段零时间戳 ⇒ 两次 `--write` 字节相等。
