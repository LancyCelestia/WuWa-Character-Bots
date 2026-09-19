# F19 — 版式宪法门「补牙」施工记录（2026-09-19）

## 0. 状态（进行中/完成 + 时间戳，随时更新）
- **完成**（终跑以 §6 最后一条实跑时间为准，约 2026-09-19 17:56—18:0x）。2026-09-19 17:36 开工（快照口径以 17:36—收尾终跑为准）。骨架落盘 → 基线实测 → 门禁改造 → 三次牙齿实证 → 终验全绿。
- 域纪律：仅改 `webui/scripts/layout-constitution.mjs` 一个文件；.tsx/.ts/.css/.json 零改动；无 git 写操作；无新文件（豁免基线内嵌进门脚本，不建 .json——建 .json 越域）。

## 1. 基线实测（改之前门禁的真实输出，原样粘贴）
```
> shorekeeper-webui@0.1.0 lint:layout
> node scripts/layout-constitution.mjs

版式宪法机器门：全部通过（hex=0 / 字号五档 / 间距 4px 栅格 / 调色板类=0）
EXITCODE=0
```
（2026-09-19 17:31 实跑，exit 0。）

### 1.1 现存族复扫（快照口径 2026-09-19 17:36—17:40，node 逐 token 程序化枚举，非旧席数字）
- **margin 全族 23 处**：`mx-auto`×17、`ml-auto`×1、`mt-1`×3（patterns.tsx:33、memory-graph.tsx:247/251·锚点 `fs-caption font-medium` 行下方数据范围两行）、`ml-1`×1（logs.tsx:202·锚点 `'text-muted-foreground'`前行 ml-1）、`mt-3`×1（memory-graph.tsx:195·锚点 `rounded-md border bg-card/80`）。**全在栅格 {0,1,2,3,4,6} 或 auto，负 margin=0、任意值=0、脱档=0**。
- **rounded 全族 42 处**：`rounded-md`×22、`rounded-full`×12、`rounded-lg`×5、`rounded-xl`×3。脱三档（sm/none/2xl/裸 rounded/任意值/方向变体）=**0**。`rounded-full` 12 处全为**无方向几何圆**（圆点/胶囊/进度条/空壳 chip 包装），族清单（锚点复验）：patterns.tsx:115（`inline-flex shrink-0 items-center rounded-full`）、theme-switch.tsx:15（`className='rounded-full'`）、badge.tsx:9、calls.tsx:74/76（`h-1.5 overflow-hidden rounded-full` / `h-full rounded-full bg-primary/70`）、knowledge.tsx:137（Skeleton）/224（`rounded-full disabled:pointer-events-none`）、memory-graph.tsx:116/124（`<button … className='rounded-full'>` 空壳）/128/199/212（`size-2 rounded-full` 圆点）。
- **同元素类型双写**（行内 token 级，修饰符链分离）：`fs-* + font-medium`（ROOT 链）**15 处** = F16 §1.2 A1 名单逐条复验一致（app-shell.tsx:22/34 为 `[&.active]:font-medium`，特异性 (0,2,0) 裁决确定，按 F16 裁定**不算违例**，规则必须不误伤它们）；`fs-* + leading-*` **0 处**（F17 已删 2 处 `fs-caption leading-relaxed`；app-shell.tsx:88 `leading-tight` 在父 div、非同元素双写，合法）；`fs-* + text-{size}/text-[..]` 0 处（全站 text-{size}=0，存量规则已禁）。
- **`layout-allow` 行级豁免标记**：现树 **0 处** → 豁免基线以空集起步。
- 顺带在册（**本席不立规则、只登记**，超任务域）：`size-[1.2rem]`×2（theme-switch.tsx:19/20）、`max-h-[90svh]`（settings-dialog.tsx:96）、`max-h-[60vh]`（logs.tsx:300）、`ring-[3px]`×6（settings-dialog:119/140、badge:9、button:9、knowledge:205、memory-graph:144，全为 shadcn 规范焦点环）、canvas 字体字面量 1 处（memory-canvas.tsx:179 锚点 `context.font = '12px`）。→ 详见 §7。

## 2. 白名单收编（rounded-full 族）
族定义：**无方向后缀的 `rounded-full`** = 几何圆形制（圆点/胶囊/进度条/空壳 chip 包装，9999px 语义非档位），收编为宪法白名单，写死在门内 `radiusViolation()` 的 `tier==='full' && !dir` 分支；**带方向的 full（`rounded-t-full` 等）不收编=违例**。白名单基准=实盘 12 处（快照口径 2026-09-19 17:36，行号随行修漂移，以锚点为准）：

| # | 文件 | 锚点 | 语义 |
|---|---|---|---|
| 1 | `src/components/patterns/patterns.tsx` | `'inline-flex shrink-0 items-center rounded-full px-2 py-1 fs-caption font-medium'` | CategoryChip 胶囊基类 |
| 2 | `src/components/theme-switch.tsx` | `className='rounded-full'` | 图标圆钮 |
| 3 | `src/components/ui/badge.tsx` | `'inline-flex items-center justify-center rounded-full border …'` | Badge 胶囊基类 |
| 4 | `src/pages/calls.tsx` | `'h-1.5 overflow-hidden rounded-full bg-accent'` | 进度条轨 |
| 5 | `src/pages/calls.tsx` | `'h-full rounded-full bg-primary/70'` | 进度条填充 |
| 6 | `src/pages/knowledge.tsx` | `<Skeleton key={index} className='h-8 w-32 rounded-full' />` | 胶囊骨架 |
| 7 | `src/pages/knowledge.tsx` | `'rounded-full disabled:pointer-events-none disabled:opacity-50'` | chip 空壳包装 |
| 8-9 | `src/pages/memory-graph.tsx` | `<button key=… type='button' … className='rounded-full'>` ×2 | chip 空壳包装 ×2 |
| 10-12 | `src/pages/memory-graph.tsx` | `cn('size-2 rounded-full', TYPE_DOT[…])` ×3 | 类型圆点 ×3 |

白名单**有牙实证**（临时摘除 full 分支 → 真身 12 处全数判红；已恢复）：
```
版式宪法机器门：12 处违例
  components/patterns/patterns.tsx:115  [radius] rounded-full：DEMO 临时摘除 full 白名单: rounded-full
  components/theme-switch.tsx:15  [radius] …
  components/ui/badge.tsx:9  [radius] …
  pages/calls.tsx:74 / :76 / pages/knowledge.tsx:155 / :242
  pages/memory-graph.tsx:127 / :135 / :139 / :229 / :242   ← knowledge/memory-graph 行号已随并发席编辑漂移
EXITCODE=1
```
恢复后（17:56 终跑）：`全部通过（…圆角三档+full 白名单…）EXITCODE=0`。
预扫描在册的 `ring-[3px]` 规范值收编**本席未做**（任意值盒尺寸族整体不在本席任务域，登记见 §7）。

## 3. 新增规则（margin / rounded / 同元素双写）
全部实现在 `webui/scripts/layout-constitution.mjs` 单文件内，六条存量规则原样保留（未削弱）。行级判定共用纯函数 `lineRuleHits()`，**内置自测锁（37 例）每次全量跑强制执行**——把「假牙」（正则空转）本身变成门禁失败项（PAGES2 与 prescan selftest 两教训的常驻化）。

1. **⑤margin 同栅格**（`marginViolation`）：m/ms/me/mt/mb/ml/mx/my 只许 {0,1,2,3,4,6} 或 auto；**负 margin 全禁**；任意值仅 `var(`/`--` 通道放行；`px/%` 等脱档形态全禁。
   **牙齿判定（诚实）**：现树 23 处 margin **全在栅格/auto，命中 0** → 本族今日为**纯预防**，牙齿由自测锁 7 条负样本证明（`mt-7/-mb-2/m-[9px]/mx-0.5/ms-14/-mx-auto/my-px` 必命中 + 5 条正样本必放行，实跑 37/37）。**不是「今日抓到真违例」，如实记账。**
2. **⑥圆角三档**（`radiusViolation` + 同链双写检测）：只许 `md/lg/xl`（=14/18/30px 值册）+ 无方向 `full`（§2 白名单）；禁裸 `rounded`/`sm`/`none`/`2xl`/任意值/带方向 full；同修饰符链两条 rounded 并写=违例。**现树脱档命中 0**（42 处全在册档）→ 同属预防 + 自测锁 7 负 3 正；「摘除白名单炸 12」实证见 §2。
3. **⑦同元素排版双写（F16 规则 F1）**（`lineRuleHits` 写者表，属性×修饰符链分桶）：`fs-*`（三属性合一）与 `leading-*`/`font-{9档权重}`/`text-{size或任意px}` 同链并写=违例；**不同修饰符链按特异性裁决、安全**（app-shell `[&.active]:font-medium` 不误伤，自测锁正样本钉死）；`font-mono/sans` 属 font-family 不沾边。**牙齿判定：font-weight×fs-* 今日真违例 16 处**（§5 棘轮债务清单，抓到即红/登记即绿，实证见下）；line-height×fs-* 与 font-size×fs-* 今日 0 处（F17 已清 2 处 leading 双写）→ 这两支为预防 + 自测锁（`fs-caption leading-relaxed`/`fs-body leading-[1.9]`/`fs-num text-[13px]`/`fs-caption fs-body` 必命中）。
   **施工期间抓到活体**：17:36 快照后并发席在 memory-graph.tsx 新增第 2 处 `fs-caption font-medium`（:169 `fs-caption font-medium text-tone-warn`），门首跑即判「权重双写未登记」红 → 按约束 2 以实收编入棘轮（15→16），这正是棘轮执法形态的实弹证据。
4. **登记表豁免**：一行 ≥3 枚不同 `fs-*` 判为注册清单（lib/utils.ts `TYPE_LADDER` 实弹误伤后定型），只让位双写族、不让位 margin/radius，自测锁钉死。
5. **权重双写棘轮实证**（临时摘除 dashboard 条目 → 恰 1 红；已恢复）：
```
版式宪法机器门：1 处违例
  pages/dashboard.tsx:63  [dup-font-weight] 权重双写未登记（fs-* + font-*）：新增须换 fs-* 档位或登记 WEIGHT_RATCHET（棘轮只减不增，基线 0）: 同元素 font-weight 双写（fs-* 多属性合一，胜负靠层叠，禁）：font-medium + fs-caption
EXITCODE=1
```

## 4. layout-allow 豁免棘轮
机制（全在门文件内，**不建 .json**——建文件越域）：
- 命中行行尾 `// layout-allow: <理由>` 生效，对**全部九族**（含存量六族）统一放行进入认领账 `exemptClaims`；理由 <4 字 → 判「空豁免理由」红（防旁路后门）。
- 认领键=`相对路径|族|命中token`（**无行号**——并发编辑行号必漂，键形制免疫），额度表 `EXEMPTION_BASELINE`（**快照口径 2026-09-19：现树 0 标记 → 空集起步**）。认领超额度 → 红「豁免膨胀」；额度未认领 → stdout「富余请收窄」提示（exit 0，合法清理不砸门）。权重双写白名单同形制（`WEIGHT_RATCHET`）。
- 权重双写行带 `layout-allow:` 标记时**优先走豁免账**（不静默吞进权重棘轮），两账不串。
- 棘轮纯函数 `excessEntries` 进自测锁：超额必判、额度内必放行——膨胀门空转本身=门禁失败。
- 调试口 `--src <目录>`：正式命令不带参。端到端实证（scratch=`C:\tmp\f19-demo\demo.tsx`，五行五型，用毕已删）：

**4a 未登记豁免+各族违例（空基线）→ exit 1，五型各中一条：**
```
版式宪法机器门：5 处违例
  demo.tsx:5  空豁免理由（layout-allow: 后须≥4字真实理由）: p-5
  demo.tsx:1  [dup-line-height] 同元素 line-height 双写…：fs-caption + leading-relaxed: fs-caption+leading-relaxed
  demo.tsx:2  [margin] margin 脱离 4px 栅格 {0,4,8,12,16,24}：mt-7: mt-7
  demo.tsx:3  [radius] 脱三档圆角 rounded-sm（许可 md/lg/xl/无方向full）: rounded-sm
  demo.tsx:4  豁免膨胀（未登记基线）：demo.tsx|dup-font-weight|font-medium+fs-body ×1（基线 0）——layout-allow 新增须用户裁定后登记 EXEMPTION_BASELINE（棘轮只减不增）
```
**4b 同文件、临时把 demo.tsx:4 之键登记进基线（额度 1）→ 该行被吸收，违例 5→4（`demo.tsx:4` 行消失，其余四违例照红）；演示后基线已恢复空集，scratch 目录已删。**
**4c 真身树在严格模式（无基线）下对五型全红**：scratch 复跑 `SCRATCH_EXITCODE=1`。

## 5. 违规清单（未修的部分，逐条 文件:行 + 判据）
本席禁改前端文件，以下全部**登记不修**。行号=快照口径 2026-09-19 17:36—17:56（并发改树必漂，以锚点为准）。

**A. 权重双写棘轮债务 16 处**（`fs-* + font-medium` 同元素，fs 权重分量成死声明，F16 §1.2 A1 + 施工期新增 1）：
patterns.tsx×3（锚 `items-center rounded-full px-2 py-1 fs-caption font-medium` / `rounded-md border px-3 py-1 fs-caption font-medium` ×2）、badge.tsx:9、button.tsx:9（cva 基类内）、affinity.tsx:38（`'truncate fs-body font-medium'` 锚）+ :85（排序按钮）、calls.tsx:35（WindowSwitch）+ :109（粒度切换）、dashboard.tsx:63（`{label}` 小标题）、latency.tsx:25（渠道名单元格）、memory-graph.tsx :169（partialTitle，**施工期新增**）+ :279（数据范围标题）、tokens.tsx:50（模型族名）+ :99 + :100（时间窗两态）。**清理一处=同步减一额度，棘轮只减不增。**

**B. rounded-full 几何族 12 处**：已按 §2 白名单收编（不占豁免额度，白名单=宪法扩编，**待用户追认**，不追认则转 §4 基线登记）。

**C. 发现未修（本席任务域外，预扫描已有处置建议）**：
| 位置（锚点） | 问题 | 建议 |
|---|---|---|
| theme-switch.tsx `size-[1.2rem]` ×2（Moon/Sun 图标） | 任意值盒尺寸（19.2px 脱栅格） | → `size-5`（0.8px 视觉差）；arb-box 族未立规 |
| settings-dialog.tsx `max-h-[90svh]`、logs.tsx `max-h-[60vh]` | 视口相对限高，栅格语义不适用 | 未来立 arb-box 族时走 layout-allow+基线登记 |
| `ring-[3px]` ×6（badge:9、button:9、knowledge input、memory-graph input、settings-dialog ×2） | shadcn 规范焦点环 | 未来 `CANONICAL_ARB` 规范值收编（prescan §1.3-B） |
| memory-canvas.tsx `context.font = '12px …'` | canvas 字体字面量脱五档 | 走 readToken 旁路或行级豁免；canvas-font 族未立规 |
| utils.ts `TYPE_LADDER` 行 | 曾触门误伤 | 已以「≥3 枚 fs-* 登记行豁免」结构性解决（§3.4） |
| 基类↔调用点跨 cn() 边界双写（F16 B 类 7 对） | 静态行级门**原理上管不到** | 由 utils.ts merger 注册（F16 方案①，另一席已落）+ 本门写码期禁新增兜 | 

**D. 归属他席的一次性红**：17:55 `tsc -p tsconfig.app.json` 6 错（TokenFamilyRow/TokenStackRow 未定义，tokens.tsx/semantics.ts **17:55:33/52 正在被并发席编辑**，非本席文件）→ 17:56:07 复跑 **exit 0**（并发席收尾），如实记录两次输出。

## 6. 验收命令与实跑输出
```
$ cd webui && npm run lint:layout                    # 基线（改造前）
版式宪法机器门：全部通过（hex=0 / 字号五档 / 间距 4px 栅格 / 调色板类=0）      EXIT=0

$ cd webui && node scripts/layout-constitution.mjs   # 终态（17:56，F19 后）
版式宪法机器门：全部通过（自测 37/37；hex=0 / 字号五档 / 间距 4px 栅格 / 调色板类=0 / margin 同栅格 / 圆角三档+full 白名单 / 同元素双写=0；行级豁免 0/0 基线，棘轮只减不增；权重双写白名单 16 处存量在册）
EXITCODE=0

$ cd webui && npx tsc --noEmit -p tsconfig.app.json  # --noEmit -p 形态，零落盘（未用 tsc -b）
EXITCODE=0（首跑 17:55 曾红 6 错=并发席在飞中间态，见 §5-D；17:56 复跑绿）

$ PYTHONDONTWRITEBYTECODE=1 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_webui_constitution.py -p no:cacheprovider --basetemp=$TEMP/f19-pytest -q
5 passed in 6.97s        ← 常驻门含「全部通过」绿文案断言 + tsc 双项目 + cn() 行为锁，全绿

牙齿实证三次红跑：§2（摘 full 白名单→12 红）、§3.5（摘 dashboard 棘轮→1 红）、§4a/4c（空基线下豁免膨胀→红）。
卫生：本席零缓存落树（.mypy_cache/.pytest_cache/data/__pycache__ 实测不存在；.ruff_cache 为**他席存量**未动）；scratch 已删；`.tmp-test/` 未触碰；无 git 写操作（`git status` 只读核对：本席足迹=` M webui/scripts/layout-constitution.mjs` + 本台账一份）。
```

## 7. 遗留与风险
1. **arb-box / ring 规范值 / canvas-font / space-\* / 内联色函数五族未立规**（prescan §三.2 方案已备好）：立规即炸 4+6+1 处真违例，需与「禁改前端」的收编动作同波执行，本席任务域=margin/rounded/双写，未扩。现门绿文案已如实列执法族，不含未执法族——无「锁死」超前措辞。
2. **rounded-full 白名单=宪法扩编，待用户追认**（§2 族语义=几何圆）；不追认则 12 处转 layout-allow 基线（`count 1/1×12 键`），棘轮形态不变。
3. **棘轮键随行号免疫但随「同文件同 token 组合」聚认**：同文件把双写搬到另一行不会被抓新——口径为「每文件每组合只减不增」，比行号锚定的 F16 草案弱在位置维、强在并发漂移维，取舍已在 §4 说明。
4. **同链圆角方向组合**（`rounded-md rounded-t-lg` 型分层圆角）现判双写违例（现树 0 处）；若未来真需分层圆角设计，走白名单扩编而非豁免。
5. **并发漂移**：施工期间 memory-graph/tokens/knowledge 行号与双写计数均有漂移（15→16 收编），终态计数以最后一次门实跑为准；他席再新增双写必红，由收尾席按棘轮规则处置或登记。
6. **文档措辞**（建议，非本席域）：HANDBOOK/AGENTS「版式宪法门」表述可升级为「九族执法 + 自测锁 37 例 + layout-allow 棘轮（基线 0，只减不增）」。
