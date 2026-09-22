<!-- @schema:BEGIN
sections: 工作区规则 | 项目身份? | 目录地图? | 架构与消息主链路? | 功能清单? | 验证与门禁? | 已知问题台账? | 交接史与权威链?
params:
- rules_scope | text | literal | req | nonempty
- owner_board | text | auto:category_owner_board | req | nonempty
- enforce_gate | text | literal | opt | any
@schema:END -->

# 模板：workspace-rule（工作区规则 / 项目总纲件 · 唯一模板源）

本文件是「规则 + 项目全貌」类内容件（类别 `root-rules`，现网唯一实例＝仓库根 `AGENTS.md`）的唯一模板。该类件的特征是：条款有执法后果，正文与常驻门一一对应。
一类内容一份模板；内容页通过页首 front-matter 调用，`@schema` 覆盖不到的字段一律规格外，由 `scripts/doc_template_sync.py --check` 判红。渲染器只重写 `TEMPLATE-AUTO` 标记内的机器段。

## 怎么用（内容页侧）

```markdown
---
template: workspace-rule
params:
  rules_scope: （必填）
  owner_board: （必填）
  enforce_gate: （可省略）
---
```

- `rules_scope` 写这份规则管哪个工作面；`owner_board` 写归属板块；`enforce_gate`（可省略）写执法它的那道门路径。
- 条款计数、域数、键数一律「以机器册为准」——与 G-T3 同尺，裸写必红。

## 骨架（新页照抄；机器段由 --write 注入，节名必须逐字等于 @schema sections）

<!-- TEMPLATE-AUTO:BEGIN -->
- rules_scope：{{fact:rules_scope}}
- owner_board：{{fact:owner_board}}
- enforce_gate：{{fact:enforce_gate}}
<!-- TEMPLATE-AUTO:END -->

## 工作区规则

## 项目身份（可选）

## 目录地图（可选）

## 架构与消息主链路（可选）

## 功能清单（可选）

## 验证与门禁（可选）

## 已知问题台账（可选）

## 交接史与权威链（可选）

## @schema 字段语义（门侧口径）

- `sections`：有序节序列，尾缀 `?`＝可选；必填缺失 / 表外节 / 顺序偏离各独立码。
- `params` 五列 `key | kind | source | req | domain`（本模板全 `literal`，无现算参数）。
- 渲染区 `{{fact:KEY}}` 的 KEY 必须在 params 内且被消费（否则 `DEAD_PARAM`）。
- 字节确定性：LF 写盘、声明序、机器段零时间戳 ⇒ 两次 `--write` 字节相等。
