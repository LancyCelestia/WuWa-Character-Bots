# 设计规格：渲染管线性能优化（Track 2 — 等待策略 / 并发模型 / 渲染缓存 / 热点清理）

> **状态：部分实施（2026-09-19 复核、2026-09-20 随 F24/DOC1-b 落稿）**——并发/等待预算两键已接线（`config.py` `bot_render_max_concurrency`/`bot_render_wait_budget_ms`，13fcd30/AGENTS #31；2026-09-20 复核实存）；信号驱动等待/渲染缓存/热点清理各子项实施态**待逐 § 对 `render_backends.py` 现码复核**，未复核子项不得沿用旧「未实施」或新「已实施」判词。目标读者为下一实施会话。
> 事实来源：`.superpowers/sdd/2026-09-12-shorekeeper-global-audit/baseline-perf.md`（下称 baseline）、
> `plugins/bot_unified_runtime/output/render_backends.py`（现实现全文）、
> `docs/rendering-contract.md`（七条铁律，本规格零破坏为硬门）、
> `.superpowers/sdd/2026-09-12-shorekeeper-global-audit/review-c-final-report.md`（中毒修复史）。
> 日期：2026-09-13。现状断言均经源码核实（标注 `文件:行号`）；**所有性能收益与工作量数字均为估算**。
> 基线红线：生产 bot 未重启（台账 #10/#26），baseline 全部为离线实测，Live 延迟 unknown。

---

## 0. 范围与不做什么

**做**：①等待策略从固定 sleep 转信号驱动；②并发模型从全局锁串行转有界并行（渐进、与现
线程本地模型兼容）；③同 payload 渲染缓存（限高收益族）；④85 处静态热点中渲染/发送热路径
子集的清理位选；⑤分阶段实施计划（每阶段独立测试门+回滚）。

**不做**：不改任何模板 DOM/token（`docs/rendering-contract.md` 铁律 #1-#7 全程有效，本规格
不触碰其任何断言面）；不动人格资产；不动 mermaid 的 `wait_js` 语义（其「条件未达成→None
降级」是正确契约，render_backends.py:307-318）；不引入异步版 playwright（理由见 §3.3）；
85 处热点中不在渲染/发送热路径上的部分划出本 Track（§5）。

---

## 1. 现状事实与问题定性

### 1.1 基线已证事实（baseline，离线实测）

| # | 事实 | 出处 |
|---|------|------|
| F1 | 每卡渲染中位 2.28–3.10s；HTML 构建 <5ms 可忽略——成本 99% 在 Chromium 侧 | baseline §1/§2 |
| F2 | `render_backends.py:250` 默认 `wait_ms=1500` 构成固定地板；弹性部分 ~800–1600ms 与卡面面积正相关 | baseline §1 |
| F3 | 渲染全程持 `PlaywrightRenderBackend._lock`（:255）**全局串行**；`__init__` 的 `max_concurrency` 参数存而不用（:160 赋值后无任何引用） | baseline §1 + 源码核实 |
| F4 | **同线程第二个 sync_playwright 实例 chromium launch 100% 失败**（单线程顺序实测 3/3）；生产多线程路径 unknown | baseline §1 |
| F5 | 常驻 Chromium 单实例 RSS ≈260MB，随 distinct 线程数线性增长；管线池默认 8 worker（runtime/pipeline.py:139 默认 8、钳位 1..64）+ mermaid 专用单 worker（output/renderer.py:44） | baseline §5 + 源码核实 |
| F6 | mermaid 热态 ≈1783ms（wait_ms=120 + wait_js 等 SVG + jsDelivr CDN） | baseline §1 |
| F7 | 中毒修复史：旧 `_close_thread_browser` 调不存在的 `ctx.close()` 被吞 → 同线程 asyncio loop 永久中毒（C 方向根治，改 `ctx.__exit__`，双 exit 幂等已实证）；C-1 launch 重试分支漏毒已修（launch 异常当场 `__exit__`，tests/test_browser_ctx_leak.py ×4 回归锁）；M-3 wait_js 失败不计入 page_failures 的近似语义在案 | review-c-final-report 项目1 + 修复回执 |
| F8 | 任务输入提及的「C-6」编号在 review-c-final-report / final-review-report / handover-c 中**未检索到**；本规格按 F7 已验证条目表述，不臆造其内容 | 本次检索（诚实声明） |

### 1.2 wait_ms 调用点实况普查（本规格新证据，baseline 未列）

对全部 `render_card` 调用点的 `wait_ms` 实值逐一核实：

| 档位 | 调用点 | 实值 | 说明 |
|---|---|---|---|
| **0ms 档** | market.py:222、fx.py:154、stocks.py:289/331、affinity.py:269、debug.py:839、echo.py:2844、usage_cards.py:227 | `wait_ms=0` | 纯静态内联卡已零固定等待，耗时 = networkidle + img 解码 + 截图编码 |
| 300ms 档 | music.py:646 | `wait_ms=300` | 候选卡 |
| **3000ms 档** | content_parser.py:386（`render_card_png` Mica 分支） | `wait_ms=3000` | **解析卡族共用管线：解析卡/epic/菜谱(eat.py:444)/占卜(divination.py:348) 全在此档**；注释明示「此前 1500ms 经常截在低分辨率占位帧上，出图发糊」——**盲目调低已有实弹翻车史** |
| 1500ms 档 | content_parser.py:399（media 兜底分支 `{"html": ...}`） | 缺省→1500 | 旧媒体降级卡 |
| 120ms 档 | bridge.py:1574（mermaid） | `wait_ms=120` + wait_js | 语义正确，不动 |

**定性修正**：「1500ms 固定地板」只命中 media 兜底与任何缺省调用；生产大头是解析卡族的
**3000ms** 档与 0ms 档的弹性部分。§2 的等待策略因此分档施策，不做一刀切。

---

## 2. 等待策略：固定 sleep → 信号驱动自适应

### 2.1 方案权衡

| 方案 | 做法 | 收益 | 风险 | 判断 |
|---|---|---|---|---|
| a. 全局调低 wait_ms 默认值 | :250 默认 1500→更低 | 立竿见影 | **已实证翻车**：1500ms 截低清占位帧（content_parser.py:386 注释）；远程封面族必糊 | **否决** |
| b. **信号驱动 + 预算封顶（推荐）** | `wait_ms` 语义从「固定 sleep」改为「**预算上限**」：依次等待 ①`document.fonts.ready` ②全部 `img.complete` 且 `naturalWidth` 稳定（两次采样一致） ③双 `requestAnimationFrame` 帧界；信号齐即截，未齐等到预算封顶。新增可选 payload 键 `wait_budget_ms`；缺省时沿用现 `wait_ms` 值——**不传新键的调用零行为变化** | 3000ms 档估降至 800–1500ms（估算）；1500ms 档估降至 600–1000ms（估算） | 字体晚到 swap 截图中途换字形——由信号①覆盖；信号轮询本身 ~每 100ms 采样一次的开销可忽略 | **推荐**，渐进且向后兼容 |
| c. 按卡型基线化超时表 | 以 P0 实测分位数（P95+余量）登记每模板预算（如 universal 2500 / market 1500 / mermaid 维持 wait_js），超预算→重渲一次→仍败 None→文本兜底（铁律 #7 语义不变） | 防慢资源把锁/槽持满 8s（现状 `_SET_CONTENT_TIMEOUT_MS=8000`，:136） | 预算表需随模板演进维护 | 与 b 组合使用（预算封顶值来自此表） |
| d. 替换 networkidle | `set_content(wait_until="domcontentloaded")` + 显式信号等待 | 消除 networkidle 的 500ms 网络静默隐性下限与慢资源 8s 持锁面 | 字体/图片晚到竞态面变大；0ms 档卡已依赖其「请求静默」语义 | **观察期后再裁**（开放问题 #2），P0 不动 |

### 2.2 推荐组合与预期收益（**全部为估算**，以 P0 实测为准）

- P0 落地 b+c：解析卡族 3000ms 档 → 信号驱动 + 2500ms 预算；media 兜底 1500 档 → 信号驱动
  + 1200ms 预算；0ms 档与 mermaid 本轮不动。
- 估算账（相对 baseline 中位）：解析/占卜/菜谱/epic 卡 3.8–4.6s（3000+弹性）→ **估 1.5–2.5s**；
  media 兜底卡 → **估 1.2–1.8s**；若开放问题 #2 裁决替换 networkidle，0ms 档弹性 0.8–1.6s →
  **估 0.4–0.9s**。全卡型中位 2.3–3.1s → **估 1.0–2.0s**（收益 35–60%，估算）。
- 测量方式：复用 baseline §8 `render_bench.py` 同源脚本前后各跑一轮（同机同 payload），输出
  进 HANDBOOK 台账，杜绝「想象中的收益」。

---

## 3. 并发模型：全局锁串行 → 有界并行

### 3.1 两条硬约束（任何方案必须先过）

1. **同线程第二 sync_playwright 实例 100% launch 失败**（F4，3/3 实测）。推论：**每线程任一
   时刻至多存在一个活跃 sync_playwright ctx** 是不可逾越的不变量；并行只能来自**跨线程**。
2. **中毒修复史（F7）**：异常路径曾致线程永久中毒至进程重启。任何新增的浏览器创建/销毁
   路径，其清理出口**必须且只能**复用已验证的 `_close_thread_browser`（render_backends.py:216，
   双 `__exit__` 幂等 + 退出后同线程可重启 + 端到端自愈，三项已实证）；禁止任何新代码绕开它
   自行 close/exit。`tests/test_browser_ctx_leak.py` ×4 为硬回归门。

### 3.2 方案对比

| 方案 | 做法 | 并行度 | 内存 | 对硬约束 | 工作量（估算） | 判断 |
|---|---|---|---|---|---|---|
| a. 现状全局锁 | :255 全程串行 | 1 | 随 distinct 线程线性（F5，最坏 9 实例 ≈2.3GB 估算） | 天然满足 | — | 基线；批卡串行累加是主要痛点 |
| **b. 线程本地 + 有界并发槽（推荐）** | 把 `with self._lock`（:255）改为 `BoundedSemaphore(max_concurrency)`——**激活 :160 存而不用的参数**；线程本地浏览器复用、懒启动、自愈逻辑**原样保留**；新增常驻实例登记（原子计数）+ 超员空闲回收：释放槽后若常驻数 > 槽位上限，本线程调用 `_close_thread_browser` 退役 | = 槽数（建议 2 起步） | 常驻实例被钳到 ≈槽数（260MB×槽数，估算） | 跨线程并行不触发 F4；回收/重建全部走 F7 已验证出口；M-2（锁内 `__exit__` 无超时）从「占全局锁」降为「占本线程」，附带改善 | 2–3 轮 | **推荐**，渐进最小改动 |
| c. 单实例多 page | 一个浏览器多 page 并行 | 名义 N 实为 1 | 最省 | sync API 线程绑定：单线程内调用串行，无真并行；换异步 API 则与 offload 线程模型正面冲突（Sync-inside-asyncio 中毒史的镜像风险） | 大（重写） | **否决** |
| d. 进程池 | ProcessPoolExecutor，每进程独立浏览器 | N | N×260MB | 中毒类缺陷被进程边界根除（最强健壮性）；代价：Windows spawn + venv + 常驻池管理复杂；HTML/PNG IPC（上限 2.8MB PNG，pickle 毫秒级，可接受） | 4–6 轮 | 后备路线：b 失败或内存失控时启用，不进首批 |

### 3.3 推荐方案 b 的关键设计

- **配置面**：新增 `BOT_CARD_RENDER_MAX_CONCURRENCY`（config.py 注册表语义，装配期快照，
  热改不生效与台账 #3 同口径），**默认 1 = 现状串行语义**（即天然回滚位），真机观察后再调 2。
- **同线程单实例不变量**：thread-local 存储结构（`_local.browser/_local.playwright_ctx`）与
  `_get_browser`/`_close_thread_browser` 主体零改动；信号量只包裹 `render_card` 的进入与退出，
  不改变任何 ctx 生命周期时序。
- **mermaid 专用单 worker（renderer.py:43-47）不动**：它已是「专用线程 + 专属后端单例
  （bridge.py:1503）」的正确形态；b 方案不上其线程。
- **回收触发条件**（防新中毒面）：仅在本线程**成功完成一次渲染后**释放槽的时机检查超员；
  失败路径不自毁浏览器（交给既有连续失败 ≥2 自愈，:150/:340-348 语义不变）。
- **边界**：`max_concurrency=1` 时信号量退化为互斥，行为与现状等价（仍保留实例登记，供
  内存观测）；此等价性写进 P1 离线测试断言。

### 3.4 收益估算（估算）

订阅批量推送与连发场景：批 N 卡耗时从 `N × 单卡延迟` → `⌈N/槽数⌉ × 单卡延迟`（槽数 2 时
估省 ~45%）；单人会话单卡无感。内存上限从「随 distinct 线程数线性（最坏 9 实例）」收紧到
「≈槽数」，是**负优化债务**（现状 600s 空闲回收 :134 已缓解，b 使其有硬上界）。

---

## 4. 渲染缓存：同 payload 去重的机会与风险

### 4.1 机会排序（按 命中率 × 单次成本）

| 族 | 机会 | 依据 | 判断 |
|---|---|---|---|
| **mermaid** | **最高**：同 code 幂等（同图重发/群聊转发常见），单次 ≈1783ms（含 CDN 拉 mermaid.js，F6） | bridge.py:1552 起，code→SVG 确定性渲染 | **P2 首选**：键=sha1(code)，TTL 24h + LRU 32 枚 |
| market / fx | 高：market 数据 60s TTL 缓存内重复查询 → HTML 全同；fx panel 语义幂等（fx.py:160-168 注释明示「同文件幂等」） | market.py:227 digest=code:price 内容摘要，天然对齐 | P2 次选：TTL ≤ 数据源 TTL（60s），LRU 16 枚 |
| usage / help / debug | 低频管理命令，命中率趋零 | — | 不做 |
| **divination** | **禁入缓存**：「每抽一图」是产品语义（dedupe_key 每抽唯一子目录，divination.py:335-337） | — | 显式排除并写注释防误收 |
| affinity | 禁入：数值随相处连续变化，payload 几乎不重复 | — | 排除 |

### 4.2 digest 语义与落盘路径（风险核心）

现存落盘 digest 各族语义**不同**且各有理由：market=内容摘要（同行情覆写同文件，market.py:227-232）、
fx=semantic_key（面板/换算方向不互覆，fx.py:159-169）、解析卡=canonical_url（content_parser.py:406-414）、
usage=request_id+prefix、divination=每抽唯一。缓存层的约束：

1. **缓存命中不得改变落盘路径语义**：命中后仍按各族现行 digest 规则定位/覆写文件（或检测
   已存在即复用），保证 QQ 引用路径稳定与 `prune_prefixed` keep=120 配额语义（各能力现行）
   零变化。
2. **易变字段剥离**：`updated_at`/「生成于」时间戳/`--phase` 随机相位脚本使字节级同 payload
   稀少——缓存键必须用**语义 digest**（剥离易变字段后哈希）；`--phase` 冻结为缓存时的随机值
   对静态 PNG 视觉无影响（可接受，注释写明）。
3. **新鲜度上限**：缓存 TTL 不得超过该族数据源缓存 TTL（market/fx 60s），杜绝旧报价假新卡。
4. **契约 #7 兼容**：miss→render→`None`→文本兜底，链路零改动；`None` 结果**绝不入缓存**
   （与 market_data.py:428-29「失败不缓存」同纪律）。
5. **内存护栏**：PNG 最大单枚 2.8MB（F1 echo_help），LRU 按枚数+字节双上限（估 64MB 封顶）。

---

## 5. 热点清单位选（85 处 → 渲染/发送热路径子集）

85 处 = re.compile-in-loop 3 + in-func 4 + re-op-in-loop 30 + sync-IO-in-loop 13 + sql-in-loop 30
+ 大对象 5（baseline §6；机读全量 `hotspot_scan.json`）。仅以下在**渲染/发送热路径**上值得
本 Track 优先（其余划出，见 §5.2）：

| 优先 | 位置（hotspot_scan.json） | 函数 | 热路径定性 |
|---|---|---|---|
| P1 | `output/plain_text.py:125` | `_table_text` re.fullmatch | **出站每条消息**都过 plain_text（说人话/打码层） |
| P1 | `runtime/base_router.py:620` | `extract_http_urls` re.compile | **入站路由每条消息** |
| P1 | `runtime/mentions.py:46` | `detect_name_mention` re.compile | 入站提及检测热路径（R3 同人点名门所在，**改动必须过 test_policy_sender_interval / test_policy_soft_mention_gate 回归**） |
| P2 | `sources/registry.py:55` | `_match_url` re.compile | 链接解析入口（发链接即解析） |
| P2 | `sender/queue.py:492` | `claim_due` 循环内 sqlite execute | 发送队列 30s worker（批量改 executemany/事务外包） |
| P3 | `capabilities/echo.py:2596+2604` | `_help_index_sections` re.compile+re.sub | /bot help 卡构建（HTML 构建本身 <5ms，F1，收益小，随 P3 顺手） |

`runtime/aliases.py:207`（`__init__` 内，启动期一次）与 `backend_unit.py:170` 收益存疑，靠后。

### 5.2 划出本 Track 的部分

vector_knowledge ×10、subscription_store_v2 ×4、meme 族、smoke/epic/steam cookie 读取等
（合计 ~70 处）：不在渲染/发送热路径或属夜间批处理，另立「代码卫生批次」处理，避免本
Track 范围膨胀。

---

## 6. 分阶段实施计划（每阶段独立可验证）

统一测试门（每阶段全跑）：渲染契约 `tests/test_rendering_contract.py`（98 断言）+
`tests/test_mica_builders_contract.py`（44 断言）**零改动全绿**；触发体检
（test_trigger_spec / test_trigger_english / test_traditional_triggers / test_help_entries_coverage）
零破坏；`dev.ps1 -Task test/lint/typecheck` 全绿。验证命令遵守源码树零缓存规矩
（`PYTHONDONTWRITEBYTECODE=1 --basetemp -p no:cacheprovider`）。

| 阶段 | 内容 | 阶段专属门 | 回滚 | 轮次（估算） |
|---|---|---|---|---|
| **P0 等待策略** | render_backends 增信号驱动等待（新 payload 键缺省=旧行为）；content_parser.py:386 的 3000 与 media 兜底 1500 切换为信号+预算；预算常量表（§2.1c） | 新增离线单测（fake page 断言等待序列与预算封顶）+ bench 前后对比（复跑 baseline §8 脚本，收益按 §2.2 估算口径对账） | revert 单 commit；新键不传即旧行为 | 2–3 |
| **P1 并发槽** | :255 锁→BoundedSemaphore + 实例登记/超员回收 + `BOT_CARD_RENDER_MAX_CONCURRENCY`（默认 1） | `test_browser_ctx_leak.py` ×4 绿 + 新增多线程并发离线测试（stub 后端断言：≤N 并发、=1 时与串行等价、回收后同线程可复用）+ 真机观察 RSS | 配置回 1（运行语义等价现状）或 revert | 2–3 |
| **P2 渲染缓存** | mermaid（24h LRU32）+ market/fx（≤60s LRU16）；divination/affinity 显式排除 | 新增缓存单测（TTL 过期/容量驱逐/None 不缓存/digest 语义对齐现行落盘）+ test_mermaid_retry_budget.py 不回归 | 开关默认关或 revert | 1–2 |
| **P3 热点清理** | §5 表 P1×3 → P2×2 → P3×1，每处独立 commit | 每处跑全量 + R3 策略回归（mentions 触及者）；`queue.py` 改动加 queue 现有测试 | revert 对应单 commit | 2 |
| 收尾 | HANDBOOK §22 台账 + 本规格状态更新 + AGENTS.md 受影响章节 | 交接规矩（哈希+实跑证据） | — | 1 |

**合计：8–11 代理轮次（估算）**。P1 与 P2 理论可并行（文件域不相交），但共享 render_backends.py
的 P0 必须先行合入。

---

## 7. 风险清单

| # | 风险 | 等级 | 缓解 |
|---|---|---|---|
| R1 | **生产多线程路径 unknown 待重启实测**：F4 的 3/3 失败是单线程顺序测量所得；生产 chat-pipeline 8 线程 + mermaid 专用线程的真实实例分布、launch 成功率、常驻内存，**均未实测**（baseline §1 明示 unknown）。P1 的一切默认值（槽数、回收阈值）在真机数据回来前都只是假设 | **高（诚实声明）** | 默认槽数=1（等价现状）；重启后按 e2e_acceptance + RSS 观测再调；本条不解禁不上线槽数>1 |
| R2 | 台账 #10：0913 全域审计批次未重启生效，本 Track 改动将与其叠加——基线可比性受损，P0 前后对比可能混入未生效代码的开关效应 | 中 | 基线对比统一在重启后的同一生产版本上进行；差异异常时先二分归因 |
| R3 | 信号驱动等待引入新的截图竞态（字体/图片晚到）致「糊图」复发 | 中 | 3000ms 档预算保留 2500ms 余量；P0 离线单测 + 真机目测解析卡封面清晰度（沿用 content_parser.py:386 注释的验收口径） |
| R4 | 并行后 Chromium 资源竞争使单卡延迟上升（CPU/内存挤压，测量环境已有 ~52 个 chrome 进程共存，baseline 头注） | 中 | 槽数从 2 起步；bench 按串行/2 槽/4 槽三档实测后再定默认 |
| R5 | 回收路径引入新中毒面（本规格最高敏区） | 中 | 强制复用 `_close_thread_browser` 唯一出口；`test_browser_ctx_leak` 扩展回收场景用例；禁止新代码直接触碰 ctx |
| R6 | 渲染缓存展示陈旧数据（报价类） | 中 | TTL ≤ 数据源 TTL（§4.2.3）；None 不缓存 |
| R7 | 契约破坏（.card 选择器/阴影 token/兜底链） | 低 | 98+44 断言每阶段全绿为硬门；本规格不触碰模板与 token |
| R8 | mermaid CDN 依赖（jsDelivr）在缓存 miss 时仍 1.7s+ | 低 | 缓存正缓解；断网路径已有 20s 预算钳制与 None 降级（review-c I-1 修复后语义） |
| R9 | config 装配期快照（台账 #3 家族）：新配置热改不生效 | 低 | 文档明示需重启；与现行 .env 注册表语义一致 |

---

## 8. 开放问题（实施前需用户裁决）

1. **并发槽默认值与解禁条件**：建议默认 1、真机实测后手动调 2——是否接受「槽数>1 必须以
   R1 实测数据过关为前提」的节奏。
2. **networkidle 替换（§2.1d）**：P0 即做，还是观察期后独立裁决（建议后者）。
3. **渲染缓存范围终裁**：mermaid-only（最小面），还是 +market/fx（建议，含 60s TTL 纪律）。
4. **3000ms 档预算值**：2500ms（保守，建议）或更低；糊图复发时接受回退到固定 sleep。
5. **热点清理是否留在本 Track**：§5 的 P1×3 出站/入站热路径收益面广但属消息链路文件域，
   也可另立批次（建议留 P3，因均是小改动）。
6. **方案 d 进程池**：是否预研立项（建议：仅当 R1 实测显示线程模型内存/稳定性不可接受时）。
7. **真机验收窗口**：全部改动需 bot 提权重启生效（生产常驻，重启由用户执行）；P0–P2 的
   验收清单建议并入 `docs/acceptance-manual.md` 下一次重启批次。
