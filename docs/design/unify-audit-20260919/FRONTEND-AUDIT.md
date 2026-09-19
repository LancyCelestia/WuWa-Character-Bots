# 前端统一审计总账（2026-09-19）

> 范围口径（用户 2026-09-19 裁定）：**前端 = WebUI + 卡片渲染**；后端与非前端由他席另查。
> 授权：前端「已收口，允许我修」+「P0/P1 自动修复，实在决定不了再找我」+ `webui/` 提交入库。
> 席位对账单 22 份同目录并存（`F2…F25`、`S8`）。**本文件是唯一读数入口**，席位文件是证据附件。
> 全文数字均为**快照口径**：树在被并发写，每条计数都带测量时点，引用前先复测。

## 〇、一句话结论

「统一协议/统一消息」在**控制面→前端这一段是真断的**：不是没写代码，而是**判据写在了会被上游统一文案吃掉的位置**（按文案正则匹配 404）、**门的判据与实现各说各话**（tailwind-merge 看不见自定义 utility，门只查字面量）、**窗口口径两套**（账本按本地时区写、查询按 UTC 字符串比）。本波把这三类根因逐个钉死，并给门禁补上自测牙；同时**推翻了两条本波自己报出的假发现**（见 §五）。

## 一、P0（6 修 + 1 移交）

| # | 问题 | 根因 | 落点 | 证据 |
|---|---|---|---|---|
| P0-1 | Token 面板「24h」实际偏 8 小时 | 账本 `completed_at` 按**本地时区**写（`model_router` `datetime.now(self._zone)`），窗口边界按 **UTC 文本**做 ISO 字典序比较 | `control_plane/metrics.py` 新增 `_stored_offset_zone()`，边界随库内真实偏移渲染 | `pytest tests/test_webui_stats.py` **59 passed**；`+08:00` 夹具双向实证：旧界外得 `['gpt-5.6-terra']`（丢 6 分钟前的行、收 26 小时前的行），新界得 `['gemini-3.8-flash']` |
| P0-2 | 卡片标题行高/字重被组件基类静默吃掉 | `cn()=twMerge(clsx())`，tailwind-merge 3.7.0 的默认组表**没有任何 `fs-*` 字面量** → 自定义 `@utility` 从不折叠，胜负交给产物层叠序（实测五档全部早于 `leading-*`，基类恒胜） | `webui/src/lib/utils.ts` 改 `extendTailwindMerge({extend:{classGroups:{'font-size':TYPE_LADDER,'background':TONE_FACE}}})` | 行为锁在 `tests/test_webui_constitution.py` 门 5：`cn('leading-none font-semibold','fs-card')` → `font-semibold fs-card`（旧：三条全留） |
| P0-3 | `webui/` 整树历史上**零提交**（改错不可归因、不可回滚） | 从未 `git add` | 首次入库 | commit **`a76cc2b`**：43 files / 8852 insertions |
| P0-4 | 数据卡把错误态渲染成正常态 | `StatCard` 是 `value!==undefined ? 数字块 : children` 的**互斥三元**，错误/降级子节点被静默丢弃 | `patterns/patterns.tsx` 改并列渲染 | 复跑 `npm run build`+`node --test`；四态手验见 §四 |
| P0-5 | 设置面板保存时**静默清空凭据** | 输入框打开即空，`save()` 无条件把空串写回 localStorage | `settings-dialog.tsx`：留空=保持原值；清除改显式按钮（`hasStored` state 驱动，修掉「清除后界面不重绘」） | 新增 `settings.clearToken` 双语言键；`npm test` 14/0 |
| P0-6 | **验收门会为一页手写 HTML 出具「9/9 PASS·mode=data」绿单**（旧行为：只查 DOM 文本标志 + 白名单吞掉全部网络噪声） | `webui_acceptance.py` 判据只看文案是否在场，从不要求任何真实请求；SKIP 不进退出码；产物落后源码也照跑 | 四颗牙：①数据态必须有 `/api/` 200 证据（文档自身 200 不算）②`--expect data\|graceful` 把模式升格为判定量③页内值域探针（`NaN/undefined/[object Object]/Invalid Date`，两态都查）④SKIP 默认计红 + dist 落后 src 拒跑 | **四条负控全部实跑**：手写假页 → `FAIL mode=data 但窗口内零真实 /api/ 200 响应`（exit 1）；假页含 `NaN` → `FAIL 值域探针违例`；`--expect data` 打无后端真产物 → `FAIL mode=graceful 不满足 --expect data`（exit 1）；回拨 495s 的 dist → `[uiacc] dist 落后 src 495s`（exit 1），`--allow-stale-dist` 后 exit 0；真产物 9 页跑 = **PASS 9/0/0**（探针零误伤）；`ruff` 0 |
| P0-7 | **移交**：渲染域 `domains/` 零 git 回滚面 | `domains/render` 21 文件仅 12 入哈希锁、275 垫片退役波正在进行 | 未动（F22-b 出七节施工图 + 7 个待裁点 D1–D7） | `git ls-files plugins/bot_unified_runtime/domains` = **0**；`F22-render-rollout-plan.md` |

## 二、P1（9 修，全部带锁或带复算）

| # | 问题 | 修法 | 锁/复算 |
|---|---|---|---|
| P1-1 | **三张「未部署」卡是不可达代码**：控制面把 404 也包成统一 message（`_app.py` HTTPException 处理器），前端 `isNotFound` 按 `/HTTP 404/` 匹配文案 → 恒不命中，操作员只看到「加载失败」 | error 相位加可选 `status`/`code`；判据改结构化状态码并收成单源 `webui/src/lib/semantics.ts` | `semantics.test.ts` 显式锁「统一中文 message + status 404 → true」「只有文案 → false」 |
| P1-2 | Token 堆叠图**双计缓存**：`prompt_tokens` 恒含缓存子集（结算是 `billed_input = prompt − cache_read − cache_write`），四项直接堆叠柱长虚高 | 堆叠段改「非缓存输入/读缓存/建缓存/输出」，段和=输入+输出；缓存未上报按 0；缓存反超输入则不拆段 | 7 例新锁含「和恒等 120 而非 160」与矛盾数据分支 |
| P1-3 | 侧栏派生 `.filter` 抛错会卸载**整棵布局**（`AppShell` 在错误边界之外——它是边界的主人） | 派生提为纯函数 + `Array.isArray` 降级；根路由接 `errorComponent`（明确**不用** `defaultErrorComponent`） | `pickEnabledCollections` 三例（null/undefined/null 元素） |
| P1-4 | 日志流游标去重与溢出记账（同批 F17 校正）：效果内重建 Set 少去重、裁剪后旧游标不释放 | `seenRef` 同步增删 + `droppedCount`；`clearView()` 供重订阅与改筛共用 | `webui_acceptance.py` 页面回归 + 代码复核 |
| P1-5 | **亮色 warn 对比度 8 处不达 WCAG AA**（最低 2.65:1，暗色 0 处） | `--tone-warn` 亮色 `oklch(0.666 0.179 58)` → `oklch(0.516 0.1009 64.8)`（≈`#8f5a1e`）；**暗色不动** | 独立脚本 `%TEMP%/f11b/f11b_contrast.py` 复算：`textFail 0 / uiFail 0 / minText 4.57 / minUi 4.36`；OKLab 转换器自校验（`#318ce7→oklch(0.632 0.1608 252)` 与 `--primary` 逐字相符） |
| P1-6 | 窗口命名与实态不符：滚动 24h 写成「今日」 | zh 两处文案改「近 24 小时」并显式「非自然日」；en 同步 | 与 P0-1 同族，防再漂 |
| P1-7 | 概览调用卡脚注在计数为 null 时输出**空句** | `formatInt` 包裹两字段 | 复跑 `tsc` 0 |
| P1-8 | **版式宪法门无牙**（只查字面量，规则可退化为空转而全绿） | 新增三条规则（margin 同 4px 栅格 / 圆角三档+`rounded-full` 几何白名单 / 同元素字重·行高·字号双写）+ **37 例内建自测每次跑** + 行级豁免棘轮（基线 0/0） | `npm run lint:layout` 输出含「自测 37/37」；构造期自测真抓到 2 个实现 bug；权重棘轮存量 16 处在册 |
| P1-9 | 前端质量门**不常驻**（跑不跑全看人） | 新增 `tests/test_webui_constitution.py` 5 门（版式门/tsc 双项目/纯函数/脚本入口一致性/cn 行为锁）；缺 node 判**失败不跳过** | `pytest tests/test_webui_constitution.py` **5 passed** |

## 三、登记未修（不在本波授权面内，或需要裁定）

| # | 事项 | 为什么不顺手修 |
|---|---|---|
| R-1 | 13 处文档互相矛盾 + 8 条「与实盘矛盾」的宣称（`rendering-contract.md` 首行「违反任意一条必拦」实为 8 值黑名单、其中 3 值被自家白名单自我中和，有效仅 5 值；acceptance-manual 把圆角判据写进门根本没执法的项） | 这些文件在 `verify_hashes.py` 19 件清单内，**改即红哈希门**，而本波纪律是禁 `--write`。订正稿 F24 已按文件分组写满 before→after，等重录授权 |
| R-2 | 未知 `reason` 码原样上屏（无兜底伞键） | 现注释是**有意**「未知码原样、绝不编语义」；控制面是给管理员看的，藏码反而更难诊断。属文案策略裁定，不是缺陷 |
| R-3 | `resolveSemantic` 把非数组 payload 判为 `items:[]` | 他席在飞域（`api-client.ts`），且需要 payload 形状契约同批改 |
| R-4 | 记忆图谱三项降级无指示位（meme_tags 坏 JSON 行、术语表逐文件静默读失败、信封 `source` 未被消费） | 后端**根本没发**这个标志位，前端造不出来；F2-b 已把精确补丁稿登记在 §6 |
| R-5 | `size-[1.2rem]`×2、`max-h-[90svh]/[60vh]`、`ring-[3px]`×6、canvas 字号字面量 | F19 报为「arb-box/画布字体族待专席」，需先定白名单语义 |
| R-6 | `npm run typecheck` 用 `tsc -b`（往树里写 `.tsbuildinfo`） | 门本体已改用 `--noEmit -p`；脚本改法涉及并发席正在动的 `package.json`，留收尾合流 |
| R-7 | 控制面注册 94 条路由，前端只消费 12 条（**79 条从不消费**，含 78 条排除 `/ui`） | 不是缺陷（控制面面向多客户端），但「前端↔后端配平」从此有据：**前端 12 条 → 后端缺失 0 条**（F4-b 穷举）。真要对齐得先裁端点，属产品裁定 |

## 四、复跑取证（本波最后一轮实跑，全部原样）

```
cd webui && npx tsc --noEmit -p tsconfig.app.json     → 0
cd webui && npm run lint:layout                        → 0  自测 37/37；margin/圆角/双写新牙；豁免棘轮 0/0
cd webui && npm test                                   → pass 14 / fail 0 / cancelled 0
cd webui && npm run build                              → 0  dist/index.html 980,836 B（gzip 299.01 kB）
pytest tests/test_webui_constitution.py                → 5 passed
pytest tests/test_webui_stats.py                       → 59 passed（含 P0-1 时区回归锁）
ruff check scripts/webui_acceptance.py tests/test_webui_constitution.py → All checks passed!
python scripts/webui_acceptance.py                     → PASS 9 / SKIP 0 / FAIL 0（全 graceful，逐行自证「未取数据」）
%TEMP%/f11b/f11b_contrast.py                           → textFail 0 / uiFail 0 / minText 4.57
```

已知**门禁抖动源**（不是代码问题）：常驻门 `test_tsc_typecheck_all_projects` 会 shell 出去跑 `tsc`，而本树正被多席并发写——17:55 他席 `tokens.tsx` 改到一半即红、17:56 绿。另记：本会话一次误用 `BOT_AUTOSYNC=1` 令 `docs/auto-facts.md`、`docs/command-catalog.md` 被重写（内容为当前树真值重生成，非陈旧），`tests/render_hashes.json` 的 `--write` 因 `OSError 22` **失败未落盘**；此后一律 `BOT_AUTOSYNC=0`。

## 五、被推翻的假发现（本波自己报、自己复验、自己作废）

| 报出 | 宣称 | 复验结论 |
|---|---|---|
| F23 | 「SSE 端点 `/logs/live` 从未注册 → 实时日志**从来没通过**」P0 | **作废**。`api-client.ts:481` 造的是 `/api/v1/logs/stream`，后端 `events.py:88` 前缀 `/api/v1/logs` + `:131` `@router.get("/stream")` 完全配平，且 `tests/test_control_plane_events.py` 四处锁定 |
| F11 | 「改 `SEMANTIC_WARNING` 值即可救回告警对比度」 | **算术上证伪**。F11-b 实测：统一到值册 `#b07d1a` 救回 **0/5** 文本对（chip 2.65→3.00 仍不达 4.5）；真正约束是 14% 色面那一族。本波按实测值改，见 P1-5 |

教训已进纪律：**任何「P0」在动手前必须独立复测**，席位报告不是证据，可复跑命令才是。

## 六、待用户裁定（我决定不了的）

1. **提交范围**：`webui/` 授权已用尽（`a76cc2b`）。第二批要动的 `tests/test_webui_constitution.py`、`tests/test_webui_stats.py`、`control_plane/metrics.py` **都在 git 里从未存在**（整份文件是未跟踪新件，内容属他波），要不要随本波入库、以及那两份生成物（`auto-facts.md`/`command-catalog.md`/`render_hashes.json`）算谁的，请裁。
2. **渲染域入库与哈希重录权**（F22-b 的 D1/D2）：`domains/` 386 件零回滚面 vs 补锁前先动的顺序。
3. **`rounded-full` 几何白名单**是否批准为规范（F19 已按白名单放行 12 处，但白名单本身是设计裁定）。
4. **warn 新色值 `#8f5a1e` 需肉眼过一眼**：对比度是算术，观感不是。备选是更浅的 `#965820`（刚好 4.5，无余量）。
5. **双 `bot.py` 实例**仍在（F4 报，8080 归属待定）——按铁律不代重启、不 kill。
6. 文档订正稿（F24）执行前需要 `verify_hashes --write` 授权。

## 七、树卫生与并发状态（快照 17:58）

- 源码树内本会话零缓存产物；根目录既存 `.mypy_cache`/`.ruff_cache`/`.pytest_cache`/`.tmp-test/`（约 8100 件，制造 44 条 ruff 噪声）**非本波所造**，按规矩只登记不删。
- 禁触清单（`personas/`、`ChatBot_Runtime/`、`ChatBot_Archive/`、`.env`、`domains/weather/assets/qx.json`、台账外文件）全程未动；`.env` 未读明文。
- 席位产物：F2/F2-b/F3/F4/F4-b/F5/F7/F8/F9/F10/F11/F11-b/F12/F13/F14/F15/F16/F17/F18/F19/F20/F21/F22-b/F23/F24/F25/S8 共 27 份在同目录。

## 八、波次二（2026-09-19 晚，5 并发席）：已落定的追加项

> §一/§二 是「一次性串行修复」的账；本节是**用户 mandate 转并行席后**的增量。逐席对账单同目录
> （`K1-knowledge-paths.md` / `R5-impl.md` / `UNI1-impl.md`），进度与裁定以
> `.superpowers/sdd/FRONTEND-AUDIT/progress.md` 台账为准。

### 已入库（哈希为证）

| # | 事项 | 落点 | 提交 |
|---|---|---|---|
| B-1 | 主题切换图标脱栅（`size-[1.2rem]`×2）还债 | `components/theme-switch.tsx` → `size-5`；脱栅棘轮 3→1 | `97eccbc` |
| B-2 | **任意值字面量补牙**：规则⑧任意值方括号、⑨canvas 字体字面量；门自测 37→58 | `webui/scripts/layout-constitution.mjs` | `97eccbc` |
| B-3 | **三族判据/文案单源化**：`reason` 话术 4 套、窗口枚举 3 套、空值记号 11 处 | 新增 `lib/labels.ts`；`node --test` 14→29；locale zh=en 零漂移 | `f4f4572` |
| B-4 | 窄屏导航抽屉（复用同一份 nav 数组，换路由即关、Escape 归还焦点、aria-* 齐） | `components/layout/app-shell.tsx` | `1a134e3` |
| B-5 | **深链参数全站单点归一**：`SEARCH_SPECS` 声明表 → 生成 `validateSearch` → 唯一回写点 `replace` | `webui/src/router.tsx` | `1a134e3` |

### 运行数据修复（用户 19:05 显式授权动 `.env`）

台账外发现 **runtime-layout 两条红**：`BOT_KNOWLEDGE_FILES` 17 条中 2 条路径断。K1 查明**不是删除而是搬家**
（整目录 09-18 迁至 `Documents\Documents\AI提示词与人格\AI智能体有关材料\`，21 个同级文件全在）。
最小化改写两行前缀，改前整份备份 `%TEMP%\env-backup-20260919-192938`（23,848 B），替换数≠2 即拒写，全程不回显内容。
**复跑证据**：`python scripts/runtime_layout_smoke.py` → **exit 0**（此前 2 FAIL）。
遗留代价：`chunk_id` 含全路径 ⇒ 下次加载重嵌约 47.5 MB 并留旧路径残行，与待裁的 B5 `kb_drift` 重建同源。

### 评审抓出的两处「已交付件里的新缺陷」（不是席位交付不足，是并行树本身在漂）

| # | 缺陷 | 为什么严重 | 裁定 |
|---|---|---|---|
| CR-1 | **版式宪法门规则②的括号臂自始空转**：`OFF_LADDER_TEXT` 以 `\b` 收尾，而 `]` 之后永不构成词边界 | 实测 `text-xs` 红、`text-[13px]` / `text-[0.8rem]` **全绿** ⇒ B-2 号称收口的「五档字号阶梯」仍可静默入库，且席位台账已背书其安全；另发现 4 类绕行（负号前缀 / 透明度后缀 / 任意属性形 / 未列属性族） | 派 R5-FIX（轮 1/5）：每关一条绕行必须交**双向自测**（正样本变红 + 近似合法样本不变绿），否则视为未修。已核 `webui/src` 无 `text-[` 存量 ⇒ 纯门侧收口不新增违规 |
| CR-2 | **`labels.test.ts` 直读三份未跟踪后端 `.py`**（`control_plane/{metrics,webui_memory_graph,webui_stats}.py`） | 干净克隆必 ENOENT ⇒ `node --test` 失败 ⇒ B-3 刚立的 `test_pure_function_tests`（断言 `# fail 0`）把**整道 pytest 门**为非前端原因变红 | Ruling：`node --test` 套件一律**自闭包**（只读 `webui/`）；跨界对账迁新建 `tests/test_webui_labels_backend_parity.py`，控制面缺席即 `pytest.skip`——skip 是 pytest 一等概念，node 原生测试无等价物。派 UNI1-FIX（轮 1/5） |

### 移交下一位接手者的暗坑（B-5 的代价，务必读）

`SEARCH_SPECS` 是**声明式白名单**：任何页面把状态搬进 URL 后，**必须往表里加一行**，
否则该参数在深链回写时被归一洗掉——表现为「分享出去的链接打开后筛选条件丢了」，
且不报错、不留日志。这条约束目前只在代码注释与本台账里，尚未成为机器门。

### 在飞（本节写入时点）

DOC1（文档订正，等 `verify_hashes --write` 授权范围）· PERF1（`logs.tsx` + `graph/memory-canvas.tsx` 性能族）·
F12-REVIEW · R5-FIX · UNI1-FIX。**最终 `npm run build` 与全量套件由主会话在五席落地后单点执行**
（新鲜度门实测 `dist 落后 src 3302s`，并发构建会互相覆盖产物）。
