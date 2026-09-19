# F4 前端门禁与构建产物审计（unify-audit-20260919）

## 快照声明

- **取值时刻**：`date` 实跑 = **Sat Sep 19 16:07:47 2026**（本机本地时区 +08:00；取证跨度 16:07–16:40）。
- **并发写警告**：前端域与渲染域可能有在飞席并发写树。**实证已发生**：本席 16:07 后检查树卫生时，`.ruff_cache/0.16.4/*` 出现 mtime ≥16:00 的新条目（本席从未运行 ruff，归属并发席）；`webui/node_modules/.tmp/*.tsbuildinfo` mtime = 12:48（早于本席，归属更早的 tsc -b 手工跑）。本报告全部结论只对 **16:07 快照**负责。
- **本席零写证**：本席对真实工作树未新建/修改/删除任何文件（除本份日志）；三门实跑中 `tsc` 用 `--noEmit -p --incremental false` 零写形态（跑前后 `.tsbuildinfo` mtime 逐字节未动，已实测比对）；违例样本全部只存在于 `%TEMP%/f4-sandbox/`；pytest 单文件跑带 `--basetemp=$TEMP/f4-* -p no:cacheprovider PYTHONDONTWRITEBYTECODE=1`。

## ① 门清单与常驻判定表（实测）

锚点复核（2026-09-19 审计 P1-2 预言「grep 应命中 0」）：**`grep -rn "layout-constitution|tsc|node --test" tests/` = 0 命中，现状维持**。dev.ps1 全文对 webui/layout-constitution/graph **0 接线**；`e2e_acceptance.py` 无 webui 段；`tests/test_cross_validation_gates.py` 对 webui **0 引用**。

| # | 门 | 载体 | 触发方式 | pytest 常驻？ | 前置条件 | 当前红/绿（本席实跑） |
|---|---|---|---|---|---|---|
| 1 | 版式宪法门 | `webui/scripts/layout-constitution.mjs` | 手工 node 或 `npm run build` 前置（package.json:8） | **否** | node（脚本纯 fs 读，不写盘，已全文核验） | **绿**（exit 0，16:1x 实跑于真 src） |
| 2 | TS 类型门 | `tsc -b`（package.json:9） | 手工 `npm run typecheck` | **否** | node + node_modules | **绿**（本席零写等价式 `tsc --noEmit -p tsconfig.app.json` 与 `tsconfig.node.json` 各 exit 0） |
| 3 | 图布局确定性单测 | `webui/src/lib/graph-layout.test.ts` | 手工 `node --test`（仅存于文件注释；package.json **无 test 脚本**） | **否** | node ≥23（本机 v26.7.0） | **绿 7/7**（实跑） |
| 4 | WebUI 后端契约组 | `tests/test_webui_{http,stats,knowledge,plugins,memory_graph}.py` | 全量 pytest 自然收集 | **是** | 无（离线 mock/TestClient） | **绿**：http 6、stats 58、knowledge+plugins+memory_graph 66（分文件实跑） |
| 5 | dist 形态检查 | `scripts/pre_restart_check.py::check_webui` + `tests/test_pre_restart_check.py` §8 | 常驻 pytest 只测 **tmp_path 合成数据**；真 dist 仅在重启预检跑 | 部分是（合成） | python | **绿**（27 passed）；**真 dist 无任何常驻检查者** |
| 6 | 哈希门 | `tests/verify_hashes.py`（19 项全渲染域）+ `test_cross_validation_gates.py` 常驻 subprocess --check | 常驻 | **是** | 无 | `--check` **exit 0**（当前绿）；**webui/src、dist 零覆盖** |
| 7 | e2e 目验 | `scripts/webui_acceptance.py`（playwright 9 页） | 手工 | **否** | playwright+chromium+mock/真 API+起端口 | 本席未跑（禁起服务器；§④审判据） |
| 8 | 夹具后端 | `scripts/webui_mock_server.py` | 手工（默认 127.0.0.1:8743） | 否 | python stdlib | 本席未跑（禁占端口；审读完毕） |

**判定**：三门（宪法/tsc/node --test）确认游离于一切常驻自动化之外——与 2026-09-19 审计 P1-2 记录一致，无变化。唯一常驻且与前端相关的执法 = ④API 契约 + ⑤合成形态检查 + ⑥哈希门，而 ⑥④⑤ **均不触碰 webui/src、真 dist、样式产物**。

## ② 宪法门「有牙/无牙」逐条裁决（全部现场实测）

方法：复制门脚本至 `%TEMP%/f4-sandbox/gate-test/scripts/`（脚本 SRC 解析为脚本同级 `../src`，结构天然可移植），违例样本只进沙箱 `src/`，跑真门。两轮输出原样记录。

**有牙（实测抓到）**：
1. 裸 hex（含模板字符串、注释内）：`#aabbcc` 在注释里也被抓 →「裸 hex=0」宣言成立；注释命中同时构成误伤面（见无牙第 9 条）。
2. 阶梯外字号族：`text-xs..6xl`、`text-[任意]`、`style={{fontSize:`（camelCase 带冒号）。
3. padding 族脱栅格：`pt-5`、`pb-9`（含 `p-0.5/p-14` 语义，PAGES2 修复后正则真实有效）+ 任意值 `p-[`/`px-[`。
4. gap 族脱栅格：`gap-8` 被抓（但同一处报两条，见无牙第 10 条）。
5. 调色板类名直引：正则表完整（`bg-white/50`、`text-amber-500` 类形态在表内，含无数字后缀）。

**无牙（现场骗过，样本已在沙箱复现，exit 码不变绿/违例清单不含该样本）**：
1. **margin 族整体脱法**：`mt-5 mb-2.5 mx-7 -mt-2 ml-[13px] md:mr-9` → **0 命中**（正则前缀表无 m/mx/my/mt/mb/ml/mr，任意值表也无）。当前 src 真实用 `mt-1 mt-3 ml-1 mb-4`（恰好全在刻度上）——**今日无现行犯，属执法面真空而非现行违例**。
2. **圆角整族无门**：宣称「圆角三档锁死 30/18/14」只活在 `webui/src/index.css:13,182-187` 的注释+@theme 钉值里；门对 `rounded-[9px]` **0 命中**。缓和事实：`rounded-md/lg/xl` 类经 theme 间接（14/18/30px）所以类名直引天然安全，漏洞只在任意值 `rounded-[..]`；另 `--radius-sm:8px` 是钉进主题的**第四档**（现 0 处使用），与「三档」口径不符。src 现存用量：md×22/full×12/xl×5/lg×5（full=圆点徽章，属登记特例与否无门可证）。
3. **非 hex 内联色全脱**：`rgba()`、`hsl()`、`color-mix()`、`rgb(...)` 无论出现在 class 任意值、style 对象还是模板字符串——**0 命中**（门只认 `#`）。
4. **canvas 字体**：门不扫；**现役活体证据** = `webui/src/components/graph/memory-canvas.tsx:179` `context.font = '12px "Segoe UI", "Microsoft YaHei", sans-serif'` 今日就在 src 里、门今日全绿。审计 P1-3「未登记豁免」复验成立（比未登记更糟：门根本看不见这条战线，src 内也无任何豁免登记机制）。
5. **space-y-5 / space-x-7** 脱栅格 → 0 命中（前缀表无 space）。
6. **任意值非间距属性**：`w-[13px] h-[7px] border-[3px] leading-[1.33]` → 0 命中。
7. **`.css` 文件整体免扫**（walk 只收 `\.(ts|tsx)$`）：沙箱 `color.css{color:#112233;font-size:13px;border-radius:9px}` → 0 命中——宪法①②③④对 CSS 源文件零执法。
8. **字符串拼接绕过**：`'text-' + 'amber-500'` → 0 命中，**零痕迹**（无 TODO/豁免注释可扫）。
9. **camelCase 之外的 style 写法**：`{'font-size': 13}` kebab 键、`style={{ fontSize }}` shorthand（无冒号）→ 0 命中；模板字符串里的 `font-size: 17px;` → 0 命中。
10. **门自身机制问题**：全文 66 行**无任何 xfail/allowlist/skip 机制** → 「一行注释永久放行」漏洞**不存在**；代价是反向的——合法例外（如 memory-canvas 读 token 前形态）**无处登记**，规避文化只能是拼写花活（第 6-8 条）而非登记。另有报告瑕疵：`gap-8` 一处报两条（正则 `gap|gap-x|gap-y` 交替重叠所致，纯计数噪声）。

## ③ dist 新鲜度与层叠取证（不许 build，只读取证）

**新鲜度**（`.gitignore:86` 有 `webui/dist/`，dist 不入库）：
- mtime：`dist/index.html` = **09-19 03:55**；`find src index.html package.json vite.config.ts -newer dist/index.html` = **空**（无 src 文件晚于 dist）；最新 src 两文件（settings-dialog.tsx、api-client.ts）= 03:54。
- 内容探针（弥补 mtime 不可信面）：对最新 5 个 src 文件抽引号字面量共 208 个探针查 dist 内 presence → **仅 1 个「缺失」= `DELETE`**（HTTP 方法常量，minifier 折叠所致，非语义标记）。
- **裁决：当前 dist 与 src 同步（点状取证成立）**。但这是快照事实，**不是任何门保证的事实**：无常驻门绑定 src↔dist（⑤只测合成数据、⑥零覆盖、三门不碰产物），下一轮改 src 不重建不会有任何门变红。「验收跑旧产物」的既往后果就是 P1-1 本体：src 文本层门全绿、产物层行高恒 1。

**层叠实测**（`node` 只读 `dist/index.html`，973,154 字节）：

| 规则 | 字节偏移 | 声明（原文摘录） |
|---|---|---|
| `.fs-num{` | 949449 | font-size:1.875rem(推) … |
| `.fs-body{` | 949547 | 13px/20px w400 系 |
| `.fs-caption{` | 949611 | `font-size:.75rem;font-weight:400;line-height:1.125rem` |
| `.fs-card{` | 949677 | `font-size:.875rem;font-weight:600;line-height:1.375rem` |
| `.fs-page{` | 949741 | 18px/28px w600 系 |
| `.leading-none{` | **949805** | `--tw-leading:1;line-height:1` |
| `.leading-relaxed{` | 949848 | line-height:1.625 |
| `.leading-tight{` | 949936 | line-height:1.25 |
| `.font-medium{` | 950018 | font-weight:500 |
| `.font-semibold{` | 950206 | font-weight:600 |

- **P1-1 复验成立（现行产物仍红）**：五枚 `fs-*` 全部生成于两枚 `leading-*` 与两枚 `font-*` **之前**；同 `@layer utilities` 同特异性 → 后来者胜。CardTitle 基类 `cn('leading-none font-semibold', className)`（`webui/src/components/ui/card.tsx:31`）+ 调用方传 `fs-card` → **line-height 恒 1**。
- **受害者清单（grep 实测，非 CardTitle 单点）**：
  - `fs-card + leading-none`（P1-1 本尊）：calls.tsx:61、calls.tsx:150、tokens.tsx:127、tokens.tsx:172、tokens.tsx:201（共 5 处调用点；审计说 6，本席按现行 src 实测 5）。
  - `fs-caption + leading-relaxed`：settings-dialog.tsx:139、logs.tsx:308 —— 行高被放宽到 1.625，「行高单一来源」在 src 文本层已被第二来源架空（产物层恰好是它们想要的方向，纯靠运气顺序）。
  - **权重第二来源 16 处**：`fs-caption/fs-body + font-medium` 同元素（button.tsx:9、badge.tsx:9、app-shell.tsx:22,34、patterns.tsx:116,152,163、affinity.tsx:38,85、calls.tsx:35,109、dashboard.tsx:63、latency.tsx:25、memory-graph.tsx:246、tokens.tsx:50,99,100）——`.font-medium`@950018 晚于一切 fs-* → 500 恒胜阶梯值。语义上大概率「有意覆盖」，但**结构病理与 P1-1 完全同族**：裁决权在构建器输出顺序，任何一次 vite/tailwind 升级或 fs-* 改 @layer 都能让它无声翻案，且无门看守。
  - `app-shell.tsx:80` 裸 `leading-tight`（父级 fs-body 继承被断）= 观察项。
- **根因一句话**：Tailwind v4 自定义 `@utility`（fs-*）与核心 utilities 同层无隔离，输出顺序是实现细节；宪法门扫 src 文本、看不见产物层叠，验收门只看文案、看不见 computed style——**层叠事实处于零执法地带**。

## ④ 验收判据强度裁决

**`scripts/webui_acceptance.py`（369 行全文读）**：每页 PASS 判据 = 壳文案「守岸人控制台」在场 + 路由链接在导航中 +（**数据态文案任一 或 优雅降级态文案任一**）+ `<main>` 文本 ≥30 字 + 无非白名单控制台错误；FAIL 才置 exit 1，**SKIP（导航无该路由）不影响退出码**；mode 记录在输出里但**不参与判定**。

三个坏状态设计（**未实跑**——本席禁起服务器/占端口；均为实现读码推演）：
1. **BS1 后端全灭**（API 拒连/无令牌 503）：每页渲染 SemanticState「加载失败/暂无数据/控制面未配置访问令牌」（COMMON_GRACEFUL 内置）→ **9 页全 graceful-PASS，exit 0**。抓不到原因：判据设计上「优雅降级=通过」（验收意图=不白屏），数据在场与否从不强制。
2. **BS2 数据面全瘫但信封 200**：`source_unavailable`/items 全 null → latency/tokens 页走降级文案 = PASS；**dashboard 更糟**：ok 标记 = `["在线","降级"]`（PAGE_SPECS:52），`healthData.ok===false` 渲染「降级」徽章（dashboard.tsx:134-136）→ 系统降级本身满足**数据态**标记，PASS 且记 mode=data。
3. **BS3 样式层塌方**：删光 fs-* 类、把字号改回 text-sm、或拿旧 dist 冒充新 dist——只要壳标题与段落文案字符串未动、`aria-live` 行/canvas 元素在场，**9/9 照样 PASS**。抓不到原因：断言面 = 文案 + 2 个 DOM 选择器，零 class/computed-style/产物指纹断言。
   历史「9 页 9 PASS 双轮」跑的是 **MOCKUI 固定夹具**（确定性数据）——它证明的是「UI 消费夹具正确」，不构成「真后端数据在场」的证据。

**`tests/test_pre_restart_check.py` §8（27 passed 实跑）**：只断言存在/非空/≤10MB/无外链四类形态，且全部喂 tmp_path 合成 HTML；`webui/dist` 字样在 tests/ 仅此一处（合成路径）。**覆盖不到**：真 dist 新鲜度、内容正确性、层叠、样式。**它守的是「壳在不在」，不是「壳对不对」。**

**`tests/verify_hashes.py`（--check 实跑 exit 0）**：`TRACKED_FILES` 19 项 = Jinja 模板×7 + theme_tokens + 渲染规格文档 + builder×6，**`webui/` 与 `dist` 零条目**。前端交付物的内容漂移完全不进哈希门；哈希门对「改 A 忘 B」的强制重录机制在渲染域成立、在前端域缺席。

**总裁决**：**前端产物层（用户真正看到的那一层）当前零常驻执法**。常驻四件套（API 契约/合成形态/哈希/文档一致性）全部在产物侧无牙；三把真有牙的 node 门全部游离；验收门判据弱且历史执行绑夹具后端。

## ⑤ 日历炸弹与墙钟依赖清单

**原炸弹复验**：`tests/test_webui_http.py` 内锚点 `'2026-09-18T01:00:00+00:00'` **已不存在**——种子改动态（`test_webui_http.py:55-61`，注释自证「硬编码日期会在次日滑出窗口（2026-09-19 时间炸弹事故）」），本席实跑 **6 passed = 当前绿**。该字面量全树唯一残存处 = **`tests/test_webui_stats.py:596`**（`last_ok_at` 于 `_FakeHealthStore` 夹具）——`latency_view` 无 now 比较、纯映射透传（该文件 58 passed 实跑）→ **非炸弹**。

**全树穷举判定**（grep `2026-`/`2025-`/ISO 串/datetime.now/timedelta 组合）：
- 含写死 ISO 时间戳的测试命中 **161 处 / 约 60 文件**（tests/*.py）。
- 生产端按「`now - timedelta` 开窗过滤」的服务实测 4 个：`control_plane/webui_stats.py:153`、`webui_memory_graph.py:142`、`metrics.py:296-298`（token_families）、`character/trend.py:73`；plugins 全域含 `now()-timedelta` 形态共 15 文件，其余为冷却/抑制/uptime/重试年龄语义（单调安全，如 `channel_health.py:157` `age >= _RETRY_INTERVAL_SECONDS`——固定旧日期只会「永远可重试」，永不翻红）。
- 上述开窗服务的测试对位：`test_webui_stats`（fixture `now=datetime.now` 动态，L69/280/423）、`test_webui_memory_graph`（L31 `NOW=datetime.now` 模块级动态）、`test_trend_write`（L51/135 显式 `max_age_days=0` 关门 + L36-44 当天写入）、`test_schedule_service_v21`（`FixedClock(BASE)` 注入）、`test_sdd7_n4.py:421,432`（`_R_NOW` 注入解析器）→ **全部分类为动态种子/显式时钟注入/关门/闭区间参数（ledger 系 5 文件为 since/until 显式形态）**。
- **「再过 N 天必红」判定：现行 0 条**。风险登记（非日历炸弹）：①`test_webui_stats.py:366` `abs((parsed-expected).total_seconds())<5` 墙钟调度余量 = 慢机器偶发红风险；②`webui_mock_server.py` 永久锚 `FIXED_NOW=2026-09-18T12:00Z`——「24h 窗口」夹具语义随真实日历滑走，截图基线与「x 分钟前」类渲染逐渐失真（无执法面，伤目验证据链新鲜度）；③`test_control_plane_m1.py:205` 等静态透传形态——安全，但若日后有人把它们接进开窗过滤链即成弹（结构脆点，登记即可）。

## ⑥ 新发现台账（七要素；严重度｜坐标｜锚点｜根因｜建议改法 before→after（不落盘）｜验证命令｜有无锁）

- **N1｜P1（新发现，超出现有审计清单）｜整棵 `webui/` 未被 git 跟踪**｜锚点：`git ls-files webui/` = **0**；`git status --porcelain webui` = `?? webui/`；`.gitignore:86` 另把 dist 排除｜根因：前端波次从未 `git add`（AGENTS #41/#42「未 commit」实为**从未入索引**，与「共享工作树、提交裁决在用户」的批次惯例叠加后，前端成为唯一无 git 史的大块交付）｜建议：by=前端全量以用户裁定节奏入库；after=src/配置入库、dist 维持 ignore——否则任何「回滚/对比/diff 审」都对前端失明，交接证据规则（提交哈希）对前端整域不可满足｜验证：`git ls-files webui/ | wc -l` >0 且 `git log --oneline -1 -- webui` 有值｜锁：无。
- **N2｜P1｜层叠零执法 + P1-1 现行产物仍红 + 受害面比审计清单大**｜坐标：`webui/dist/index.html` 偏移表见 §③；`webui/src/components/ui/card.tsx:31` + fs-card 调用 5 处 + leading-relaxed 2 处 + font-medium 16 处｜锚点：`.fs-card`@949677 < `.leading-none`@949805｜根因：fs-* 与核心 utilities 同层拼输出顺序，src 门/验收门均不观测产物层叠｜建议：before=`cn('leading-none font-semibold', className)` → after=`cn('font-semibold', className)`（行高唯一来源归 fs-*；audit §140-141 同方案）并加常驻断言「src 中同一 className 拼接路径禁止 fs-* 与 leading-* 共存」；权重 16 处要么改阶梯自带、要么显式登记「第二来源」豁免｜验证：重建后 `node -e "...indexOf('.fs-card{') < indexOf('.leading-none{')"` 语义改断「组合不存在」+ 浏览器目验知识库多行标题｜锁：无（登记即锁）。
- **N3｜P1｜三门游离现状维持，且 `node --test` 连 package.json 入口都没有**｜坐标：`webui/package.json` scripts 无 `test`；dev.ps1 webui 零接线｜锚点：§① grep=0 复验｜根因：门建了、跑法只活在注释（graph-layout.test.ts:6）｜建议：before=无；after=按 §⑦ 裁决常驻化 + package.json 补 `"test"` 入口｜验证：§⑦ 验证命令｜锁：本条即方案，落地后自然常驻。
- **N4｜P1｜宪法门执法面实测漏判清单（§②全部 10 条）**——与 P1-3 四缺吻合，另新增 6 个现场骗过面（space-*/w-[/h-[*/border-[3px]/leading-[任意]/css 文件/kebab style/concat 绕过/shorthand fontSize）。锚点：沙箱两轮 exit 与违例清单原文（§②）。建议：门正则补 margin 族、`rounded-\[`、`rgba?\(|hsl\(|color-mix\(`、`context\.font`、`\.css` 纳入 walk、`space-` 族；负 margin 与 `rounded-full` 白名单按用户裁。验证：`cd %TEMP%/f4-sandbox/gate-test && node scripts/layout-constitution.mjs`（新规则下 violations.tsx 应爆 margin/rounded/rgba/canvas 条目）。锁：无。
- **N5｜P2｜webui_acceptance 判据三坏状态（BS1-3，未实跑）**｜坐标：`scripts/webui_acceptance.py:52,272-304`（graceful=PASS、SKIP 不挡退出码、dashboard ok 含「降级」）。建议：输出表加「mode=data 覆盖率 <100% 即 exit≠0」硬门或至少 `--require-data` 档；SKIP 计数进退出码；ok 标记文案与 locales 键做单向锁（文案搬家即红）。验证：指向死端点跑 `--pages all` 应 exit≠0。锁：无。
- **N6｜P2｜哈希门/常驻形态门对 webui 全域零覆盖**（§④）。建议：随 §⑦ 主方案落常驻 node 门；freshness 用 build-stamp 补（见 §⑦替代段）。锁：无。
- **N7｜P3｜门噪声两处**：注释内 hex 被抓（误伤面，催生改字躲门）；`gap-8` 一处报双条。建议：门跳过 `//` 行注释或降级为 warning；交替组改 `gap(?:-[xy])?`。锁：无。
- **N8｜P3｜mock FIXED_NOW 永锚漂移 + test_webui_stats.py:366 五秒墙钟余量**。登记观察。锁：无。
- （日历炸弹：原判 0 条现行，原弹已修且实跑绿——不计新账。）

## ⑦ 离线纪律冲突裁决（唯一方案，不两头下注）

**裁决：主方案 = `tests/test_webui_constitution.py` 以 subprocess 常驻跑三门，node 缺失记 FAIL（不是 skip）**，理由链：
1. 三门全为纯本地计算（零网络，宪法门连 node_modules 都不需要），与「离线 mock」纪律的实质（不出网、不碰生产库）零冲突；node 与 python/mypy 同格——是开发环境的既成事实（本机 v26.7.0，dev.ps1 对 mypy 缺失也只是 warn+提示，测试层的正确语义是「环境缺件 = 红且可修」）。
2. **`skipif(NODE is None)` 方案（audit §166 草案原样）明确否决**：无 node 机器上三门永久静默 = 门消失；且 skip 一旦引入，「为绿加 skip」的通路就永久存在，与 §② 裁决（门只防老实人）叠加即归零。
3. 工程代价实测可控：宪法门 <1s、node --test 0.24s、tsc 5-15s（占全量套件 <0.3%）；tsc 常驻化建议用本席实测过的 `--noEmit -p tsconfig.app.json`（+tsconfig.node.json 或 `-b` 接受 `.tmp` 内 gitignored 写盘）；Windows 直调 `node node_modules/typescript/bin/tsc` 绕开 `.cmd` 路径差异；无 xdist 前不议并行锁。
4. **哈希化方案不作主选、只补一个正确位置**：verify_hashes 语义 = 防「未记录变更」，不判「违规变更」——新写一行 `rounded-[9px]` 再 `--write` 照样过，门义失守；且 dist 每次重建必换哈希，`--write` 噪声会驯化出无脑重录。其正确用处 = **src-tree hash 注入 dist 的 build-stamp**，由重启预检第 9+1 项断「产物 stamp == 当前 src 哈希」——治的是 §③「src↔dist 无人绑定」这一具体缺口，与门互补不互替。
5. 替代方案（仅当「测试层禁 subprocess node」成硬红线时启用，本席不推荐）：把宪法扫描逐规则移植纯 Python、规则表单源 JSON 双引擎共读；**明确其覆盖残差**：tsc 与 graph-layout 确定性不可移植 → 两门永久游离。两头下注在此关门：要么 subprocess 硬依赖，要么接受残差，本席裁前者。

---
*F4 席，只读取证。本席未改 `webui/**`、未动 dist、未 build、未起端口、无 git 写操作；沙箱样本在 `%TEMP%/f4-sandbox/`（violations.tsx / round2.tsx / color.css / conflict-scan.cjs / fresh.cjs / gate-test/），复跑即得 §② 全部结论。*
