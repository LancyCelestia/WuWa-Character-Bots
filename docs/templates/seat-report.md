<!-- @schema:BEGIN
sections: 裁决? | 任务书? | 计划? | 账目? | 进度? | 交付 | 证据? | 发现? | 缺口? | 自报? | 卫生? | 纪律?
params:
- seat_id | text | literal | req | nonempty
- wave | text | literal | req | nonempty
- status | enum | literal | req | enum:STARTED,RUNNING,BLOCKED,DONE
- role | enum | literal | req | enum:impl,readonly,conversion,gate,measurement,report
- report_class | enum | auto:seat_class | req | enum:SEAT,report,progress,log
- ledger_events | number | auto:page_stat:ledger | req | int:0..999999
@aliases: 裁决=一句话裁决|结论|结论一句话|结论摘要|总裁决|一句话结论|总结|速览|判定|交付摘要
@aliases: 任务书=任务|目标|背景|背景一句话|为什么派你|输入|要求|需求回指
@aliases: 计划=计划|Plan|执行计划|下一步|待办|队列|安排|执行顺序
@aliases: 账目=账目|流水|台账|记录|执行记录|逐文件通读记录|通读记录|过程|改动清单|改动面|改动文件
@aliases: 进度=进度|进度日志|进度流水|Log|Progress|状态|席位状态|断点
@aliases: 交付=交付|交付物|交付物清单|产出|成果|落码|清单|文件清单|交付结果
@aliases: 证据=证据|验证|实跑证据|复跑证据|验证证据|验证实录|回归与静态门|RED 证据|RED 先行|收尾实跑|回归|门禁|验收|冒烟|实测|核查
@aliases: 发现=发现|发现表|发现台账|主会话需要知道的事实|与前波冲突/印证|不确定项|疑虑|缺陷台账|正面记录|宣称复核表|风险|问题|根因|观察
@aliases: 缺口=缺口|诚实缺口|未决|遗留|遗留登记|阻塞|我没查到的|缺口与风险|盲区|局限|残留|待补|差异声明|未能取证 / 必须真机才能证|未决 / 诚实缺口|诚实缺口 / 差异声明
@aliases: 自报=自报|错误与没做到|没做什么|没做到|自伤|教训|打脸
@aliases: 卫生=卫生|树卫生|树卫生自查|树残留自查|计数|计数与卫生|自查|自查结论|收尾自检|纪律自查|纪律自检
@aliases: 纪律=纪律|边界遵守|铁律遵守|范围与纪律|覆盖面声明|禁写面|禁改面|独占可写面|独占文件面|报告契约|全局纪律|护栏|认领|铁约束|纪律与报告|纪律确认|范围
@schema:END -->

# 模板：seat-report（席位工作日志 · 唯一模板源）

本文件是 `.superpowers/**` 席位工作日志这一类内容的**唯一模板**。一类内容一份模板，内容页只通过
front-matter 参数调用它；`@schema` 覆盖不到的字段一律视为**规格外内容**，由
`scripts/doc_template_sync.py --check` 判红。渲染器只重写 `TEMPLATE-AUTO` 标记内的机器段，
标记外正文归人。

## 本版按语料真形改的两处（席 S21，2026-09-22）

1. **`role` 保留必填，但把它的真身来源写死成可核对的既存事实**（原来只写 `enum`，没说值从哪来 ⇒
   席 S5 实测「未驱动页零来源」并据此建议降选填）。现口径：
   `role` ＝ 该席在 `OWNERSHIP.md` 认领表「问题轴」列与 `BRIEFS.md` 席位小节标题里**已经登记的事实**，
   转换席按轴语义照抄，不发明：`GATE-*`/立门＝`gate`；`*-REVIEW`/`*-AUDIT`/`ATTACK`/`CRITERION`＝`readonly`；
   `CONVERT-*`/`TPL-*`/`RELOCATE`/`FACT` 清扫＝`conversion`；写实现与判据＝`impl`；
   出实测数＝`measurement`；只出报告＝`report`。
   **在册 4 枚已驱动试点页实证该形状可行且值真**（`%TEMP%/s21_fit*.py` 同口径复查）：
   `SEAT-T-CENSUS/T-ORPHAN/T-SHAPE`＝`readonly`（三席在 `LEGACY-SEATS.md` 为只读调研席）、
   `SEAT-T-TRANS1R`＝`conversion`——四值均与各自认领轴一致，且页侧机器段已渲染「性质：…」多年。
   ⇒ 因此**不删槽位**：删它只会①毁掉 4 枚页的既存事实并逼出 8 项
   `EXTRA_PARAM`+`AUTO_DRIFT`（本席实测复现，见下），②让 351 页与 4 页形状长期分裂（任务书点名的半删反面）。
   **升级路径（交回主代理 → S20）**：值改现算＝在 `scripts/doc_template_sync.py::PROVIDERS`
   加一行 `seat_role`（真身＝`OWNERSHIP.md` 问题轴表），届时本模板把
   `role | enum | literal | req` 改为 `role | enum | auto:seat_role | req`，人手不碰数。
   该 provider 不在本席独占面内，故本席只把 params 形状与来源口径就位，不动机制。
2. **`自报` 由必填改可选**，与散文「可省略」对齐（任务书 §S21-2 点名的自相矛盾，取散文那一侧、全类统一）。
   证据：351 枚未驱动页里节名恰为「自报」**0 枚**，而同义写法（错误与没做到／没做什么／自伤）存在；
   定为必填＝全类结构性挂不上。

骨架另从语料多数真形扩了 7 枚可选槽（裁决/计划/进度/证据/发现/缺口/卫生/纪律中取未在旧骨架者），
并把实测高频同义写法登进 `@aliases:`（一行一槽位、`|` 分隔、**只收同义不同写**）。
`@aliases:` 的**读取与剥形比对由 S20 在 `check_sections` 侧实现**（约定见 `BRIEFS.md` §S20 缺口一），
本文件只供数据、不执法。

## 怎么用（内容页侧）

页首写 front-matter（自定义行语法子集，禁嵌套），例如：

```markdown
---
template: seat-report
params:
  seat_id: T-EXAMPLE
  wave: 2026-09-22-taxonomy
  status: DONE
  role: measurement
  report_class: auto:seat_class
  ledger_events: auto:page_stat:ledger
---
```

- 有真身事实的参数**必须**写 `auto:`（值由渲染器现算，人手不碰数）：`report_class` 由文件名派生，
  `ledger_events` 由本页「账目」节的条目数现算。写了别的字面值即 `AUTO_SOURCE_MISMATCH` 红。
- `literal` 参数把值直接写在 `params:` 下；schema 之外的键 = 规格外，判红。
  `seat_id`/`wave`/`role` 三枚的字面值各有既存事实来源：文件名、所在 `.superpowers/sdd/<wave>/` 路径段、
  以及本节第 1 条的问题轴口径。
- `status` 取值域含 `STARTED`：开工即可先落状态行（前言硬规矩 1），收口必须是 DONE/BLOCKED。
- 正文小节只准用骨架节名（允许「节名（自由补充）」形式，门只比对括号前主干）；
  **必填节只有 `交付`**，其余全部可省略，但出现时必须保持下面的声明顺序。
- `@aliases:` 收录的是**同义写法**：页侧写「交付物」「一、结论」都算命中 `交付`/`裁决` 槽位；
  缺节、多节、换序仍各自判红（剥形与别名只放行"同义不同写"）。

## 骨架（新页照抄；机器段由 --write 注入）

<!-- TEMPLATE-AUTO:BEGIN -->
- 席位：{{fact:seat_id}}｜波次：{{fact:wave}}｜状态：{{fact:status}}｜性质：{{fact:role}}
- 报告族：{{fact:report_class}}（文件名派生）｜账目条数：{{fact:ledger_events}}（正文现算）
<!-- TEMPLATE-AUTO:END -->

## 裁决（可选：一句话结论）

## 任务书（可选：一句话任务 + 准绳指针）

## 计划（可选：分几步、每步判据）

## 账目（可选：按时刻追加的流水，一条一行）

## 进度（可选：断点与在飞状态）

## 交付（必填：产出清单 + 实跑证据）

## 证据（可选：复跑命令与实跑输出）

## 发现（可选：给下游席位的警讯）

## 缺口（可选：没做到的与卡住的判据）

## 自报（可选：错误与没做到，全为过去式）

## 卫生（可选：源码树卫生自查）

## 纪律（可选：禁写面与认领边界遵守）

## @schema 字段语义（门侧口径）

- `sections`：竖线分隔的有序节序列，尾缀 `?` ＝ 可选节；必填节缺失、出现表外节、
  出现顺序偏离，各自是独立违规码。
- `params` 每行五列：`key | kind | source | req | domain`。
  kind ∈ text/number/path/list/enum；source = `literal` 或 `auto:<provider>[:arg]`；
  req ∈ req/opt；domain ∈ nonempty / any / `enum:a,b,c` / `int:min,max`。
- `@aliases:` 一行一槽位，形如 `@aliases: 槽位名=别名1|别名2`；别名只准是**同一语义槽位的不同写法**。
  把「少一节」写成别名（例如给 `交付` 加 `无`）＝放宽判据，禁止。
- 渲染区（TEMPLATE-AUTO 之间）只准出现 `{{fact:KEY}}` 占位，KEY 必须在 params 内，
  否则 schema 装载即红。
- 字节确定性：渲染只用 LF 写盘、列表按 schema 声明序输出、机器段零时间戳；
  同输入两次 `--write` 字节必须相等（常驻用例断言）。

## 类别侧口径（本模板管辖什么页）

`.superpowers/**` 下文件名以 `SEAT-` / `report-` / `progress-` 开头、或以 `-log.md`
结尾的 .md —— 与 `.superpowers/sdd/2026-09-22-taxonomy/CENSUS.md` 的 seat-report 判据同源。
批量转换由后续切片执行；未迁移页照常计入 `--report` 的「未模板驱动」列，不判红。

**契合度实测（席 S21 快照，复跑＝`%TEMP%/s21_fit2.py`）**：未驱动 351 页里，按
"每节都可映射＋必填齐＋无重节＋顺序合"四条全满足的 **5 页**。三个残留数学阻断
（都不是模板侧能自足的，逐条已在报告 PARKED 交回）：
① 272/351 页至少一枚节名落在**任何稳定同义集之外**（长描述式标题，如
「§2 逐字交接块（主会话照抄即落…）」）——别名表只收同义写法，收不下自由标题；
② 230/351 页节序不是任何单一声明序的子序列（结论前置与结论收尾两种写法并存，
属内容差异，只能由转换席按页归一）；
③ 196/351 页有两节同义（如「交付」＋「交付物清单」＋「实跑证据」）⇒ 撞
`SECTION_DUPLICATE`「一类内容一份骨架」。②③ 需转换席改页侧（S5 面）或主代理裁是否放宽重节判据。
本席能做且已做的：把可收的同义写法全量登进 `@aliases:`（这一步本身即消掉 S5 点名的
「差一步改名即合规」微簇——改名规则进表，不逐页手抄）。
