<!-- @schema:BEGIN
sections: 概览 | 现状 | 改动清单 | 问题与处置 | 复跑命令簿 | 禁碰面? | 坑?
params:
- wave_id | text | literal | req | nonempty
- handoff_date | text | literal | req | nonempty
- audience | text | literal | opt | any
@schema:END -->

# 模板：handoff（根交接件 · 唯一模板源）

本文件是仓库根 `HANDOFF-*.md` / `HANDOVER-*.md` 这一类**跨波次交接件**的唯一模板（类别
`root-handoff`）。一类内容一份模板；内容页只通过页首 front-matter 调用它，`@schema` 覆盖不到
的字段一律视为规格外，由 `scripts/doc_template_sync.py --check` 判红。渲染器只重写
`TEMPLATE-AUTO` 标记内的机器段，标记外正文归人。

## 怎么用（内容页侧）

页首写 front-matter（自定义行语法子集，禁嵌套）：

```markdown
---
template: handoff
params:
  wave_id: 2026-09-22-taxonomy
  handoff_date: 2026-09-22
  audience: 下一个接手 AI
---
```

- 三枚参数皆为 `literal`（无自动真身来源）：`wave_id` 取波次目录名、`handoff_date` 取落盘日、
  `audience` 可省略。必填两枚缺失即 `MISSING_PARAM`；表外键即 `EXTRA_PARAM`。
- 正文小节只准用骨架节名（允许「节名（自由补充）」形式，门只比对括号前主干）；必填节为
  `概览 / 现状 / 改动清单 / 问题与处置 / 复跑命令簿` 五节，`禁碰面 / 坑` 可省略但出现时须保持顺序。
- **一次性事实（计数 / 阈值 / 清单 / 路径）禁裸写**：走「指向真身」句或机器 `auto:` 段，与
  G-T3 词表（`scripts/doc_fact_discipline.py`）同尺。本类无在册 `auto:` provider，故只准指针句。

## 骨架（新页照抄；机器段由 --write 注入）

<!-- TEMPLATE-AUTO:BEGIN -->
- 交接波次：{{fact:wave_id}}｜落盘日：{{fact:handoff_date}}｜面向：{{fact:audience}}
<!-- TEMPLATE-AUTO:END -->

## 概览

## 现状

## 改动清单

## 问题与处置

## 复跑命令簿

## 禁碰面（可选）

## 坑（可选）

## @schema 字段语义（门侧口径）

- `sections`：竖线分隔的有序节序列，尾缀 `?` ＝ 可选节；必填节缺失、出现表外节、顺序偏离，
  各自独立违规码。
- `params` 每行五列 `key | kind | source | req | domain`；kind ∈ text/number/path/list/enum；
  source = `literal` 或 `auto:<provider>[:arg]`（本模板全 `literal`）；req ∈ req/opt；
  domain ∈ nonempty / any / `enum:a,b` / `int:min,max`。
- 渲染区只准出现 `{{fact:KEY}}`，KEY 必须在 params 内且被消费（否则 `DEAD_PARAM`）。
- 字节确定性：只 LF 写盘、列表按声明序、机器段零时间戳 ⇒ 同输入两次 `--write` 字节相等。
