<!-- @schema:BEGIN
sections: 需求与裁定? | 概览 | 现状 | 发现与结论? | 改动清单 | 问题与处置 | 复跑命令簿 | 禁碰面? | 坑? | 执行安排? | 并行边界? | 波次增补?
freeform: on
params:
- wave_id | text | literal | req | nonempty
- handoff_date | text | literal | req | nonempty
- audience | text | literal | opt | any
@aliases: 概览=波次定位|接手须知|现在有什么|项目 30 秒|冷启动清单|开工前必读|一句话现状|一句话总结
@aliases: 现状=现状基线|现状快照|系统现状快照|项目现状快照|现役状态|进度
@aliases: 改动清单=本波到底改了什么|已落库滚动清单|交付史与提交索引
@aliases: 问题与处置=还剩什么没做|还没做的|待办清单|用户必须做的事
@aliases: 复跑命令簿=常用命令|门禁真值|证据地图
@aliases: 禁碰面=硬约束|红线|硬规矩
@aliases: 坑=已知坑|排障手册
@aliases: 需求与裁定=你的需求|五问|mandate 对账|她怎么工作|用户 mandate
@aliases: 执行安排=工作包|执行顺序|接手开工清单|下一个 AI 请先做什么|你的第一个动作|一键自检|开工流程|续接指南|给下一个 AI 的交接提示词
@aliases: 波次增补=增补|合并时间线|基线十笔|审计修复五笔|已修缺陷|v21r2 波次|v21r3 波次|v21r4 波次|Wave G 施工批|TTS 全链|2026-09-15 后端协议扩展增量|2026-09-15 控制面后端实现进度|2026-09-21 收尾交接态|控制面核心续接：本轮实现与审查|当前交接：后端 V2.1|档案索引
@aliases: 并行边界=与同日另一波|与《前端渲染扩展交接书》的零交叉边界|与《后端协议交接书》的零交叉边界|会话被封事件归档
@aliases: 发现与结论=关键探索发现|全案三条承重结论|审查结果|为什么长这样|探索方法论
@aliases: 概览=一页总览|一页速览|波次总览
@aliases: 现状=十三项四态总表
@aliases: 改动清单=改动全清单
@aliases: 问题与处置=已知残留与阻塞|已知残留缺陷|已知问题与递延项|发现的问题全集|问题/漏洞/Bug 全集|未完成部分|未修/未闭合|未闭合与缺口清单|六个 P0|在飞/待办
@aliases: 禁碰面=禁碰面清单|纪律红线|自动同步铁律
@aliases: 坑=踩过的坑|下一个 AI 必知的六个坑|陷阱清单
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
