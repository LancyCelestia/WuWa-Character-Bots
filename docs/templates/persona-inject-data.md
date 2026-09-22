<!-- @schema:BEGIN
sections: 一、鸣潮核心名词 | 二、游戏黑话/缩写
params:
- persona_id | text | auto:persona_dir_id | req | nonempty
- persona_source | text | literal | opt | any
- owner_board | text | auto:category_owner_board | req | nonempty
@schema:END -->

# 模板：persona-inject-data（运行期注入用的世界观词条档 · 唯一模板源）

本文件是「既是人格知识、又是运行期注入数据文件」这一簇
（现册一页：`personas/shorekeeper/knowledge/worldview_glossary.md`）的唯一模板。
该类页的特殊性：`#` 行是 provider 读的注释、`##` 行是**注入分类节名**（会被拼进模型上下文），
所以骨架只能锁形状，**动不得任何一句正文**——改节名＝改注入语义＝用户可见表达变更。

## 骨架怎么从语料真形长出来（席 S62，2026-09-22）

现算该页 H2 恰两枚：`一、鸣潮核心名词（本节前 8 条=每轮注入优先级…）`、`二、游戏黑话/缩写（仅收社区高频…）`。
判据 `_match_slot` 认「槽位名 + （」前缀，故两枚必选节写作括号前的主干即可逐字命中，
**不需要**尚未实现的别名／剥形机制（P-S55-3）。沿用的旧 `persona` 骨架会造出 5 枚违例
（席 S55 实算与本席复算一致）。

- 两枚都是**必选**：该类页天然就这两节，少一节即结构变更，该红。
- 出现任何第三枚 `##` ⇒ `SECTION_UNKNOWN` 判红（严判保留）。

> **注入语义报备**：该页正文里 `SEED_MAX_ENTRIES（8）` 两枚 8 的真身是
> `plugins/bot_unified_runtime/domains/chat_reply/character/glossary.py::SEED_MAX_ENTRIES`（席 S55 grep 实证），
> 但其中一枚落在**注入分类节名**里 ⇒ 改成指针会改运行期注入文本，属「会改变用户可见表达」，
> 本席按简报留着写工单，不改。

## 怎么用（内容页侧）

```markdown
---
template: persona-inject-data
params:
  persona_id: shorekeeper
  owner_board: B10
---
```

## 骨架（新页照抄；机器段由 --write 注入，节名必须逐字等于 @schema sections 或落在其「（」前缀形内）

<!-- TEMPLATE-AUTO:BEGIN -->
- persona_id：{{fact:persona_id}}
- persona_source：{{fact:persona_source}}
- owner_board：{{fact:owner_board}}
<!-- TEMPLATE-AUTO:END -->

## @schema 字段语义（门侧口径）

- `sections`：两枚必选、声明序即文档序；缺节 / 表外节 / 乱序 / 重节各自独立码。
- `params` 五列 `key | kind | source | req | domain`（全 `literal`，均有既存事实来源）。
- 渲染区 `{{fact:KEY}}` 的 KEY 必须在 params 内且被消费（否则 `DEAD_PARAM`）。
- 字节确定性：LF 写盘、声明序、机器段零时间戳 ⇒ 两次 `--write` 字节相等。
- **落地依赖**：同 `persona-provenance`——`classify()` 未分簇之前该类接不到页；
  另 S55 §四 建议「整件摘出内容管辖面」（它是 provider 回退数据），代价与替代方案在主代理手上，本席不自行豁免。
