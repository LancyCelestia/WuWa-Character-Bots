# C 方向交接文档（统一 UI / 卡片 / 金融数据与图表）→ 移交 A Agent

> 日期：2026-09-13。作者：C 方向主代理（含子代理 C1 金融数据层 / C2 图表与菜谱质量 / C3 占卜与历史卡适配 / C4 直拼 HTML 统一主题 / C5 生产接线 / C6 mermaid 修复 / C7 文档门禁与终验）。
> 铁律提醒：以下所有「已完成」均有实跑证据；**生产 bot 未重启，全部改动待提权重启生效**（与台账 #10 同口径）。

---

## 一、成果清单（全部有实跑证据）

### A. 统一 UI / 渲染体系
1. **`output/card_render/theme_tokens.py`（新）**：主题 token 单一事实来源。`BRAND_THEME`（守岸人淡蓝 accent #318ce7）、`PLATFORM_THEMES`（17 平台 + 别名列键）、`DEFAULT_THEME`（中性灰兜底）、`FONT_WEIGHT_MAX=700`、`SHELL_RADIUS/PANEL_RADIUS/TILE_RADIUS`（30/18/14px）、`SHADOW_PRIMARY/SHADOW_SECONDARY`（两枚阴影 token）、`GAP_SCALE_PX` 间距刻度、`CARD_SHELL_WIDTHS` 宽度登记表、`DEFAULT_WASH_TOKENS`（=derive_wash_tokens(中性灰)，模板兜底字面量五卡逐字节统一为 #d9e0e7/#dfdae7/#dcdfea/#f4f5f6）、`META_VIEWPORT_POLICY="forbidden"`。
2. **bridge.py**：平台色/官方名/页脚标签全部改由 theme_tokens 派生（值与历史字面量逐键一致，渲染零变化）；`_derive_wash_tokens` 保持再导出（echo/debug/usage_cards/templates 四个历史导入面兼容）；新增 `render_finance_card_html`（stocks/fx 共用壳）；`render_market_card_html` 扩展 change 涨跌额/trend_note/crosscheck_note 并入 `__all__`。
3. **五张 Jinja 模板统一**：universal/market/affinity/mermaid/song + 新 finance_card.html。全仓执行 AGENTS.md UI 铁律：无 `<meta viewport>`（任务模板里的 viewport 示例与项目铁律冲突，按"保持既有截图契约"条款裁定为移除，已在 docs/rendering-contract.md 记录）、body 透明、字重 ≤700、动画仅在 .card 内 + reduced-motion、恰好两枚阴影 token（universal 的 14 处内联阴影全部收编）、根元素带 `.card`。
4. **修复两处真实缺陷**：①`market_card.html` 根元素缺 `.card` 导致整页截图带透明边（已修，元素截图契约恢复）；②`render_market_card_html` 零测试且不在 `__all__`（已修）。
5. **4 处 f-string 直拼 HTML（echo 帮助卡/debug LLM 检查卡/usage_cards/templates 旧媒体卡）全部接入 theme_tokens**（C4）：CSS 值级替换，DOM/文案零改动；新建 `tests/test_mica_builders_contract.py` 44 断言锁定。
6. **`tests/test_rendering_contract.py`（84 用例）**：五模板 + 主题注册表 + 桥接一致性 + 失败兜底契约的完整锁定；`docs/rendering-contract.md` 为其软文档。

### B. 金融数据与能力（全部 API 形状 2026-09-12/13 curl 实测 verified）
1. **股票**：`sources/stock_data.py`——9 家科技巨头（NVDA/AMD/INTC/AAPL/MSFT/GOOGL/AMZN/META 均东财 105=NASDAQ，TSM 106=NYSE），快照批量接口 + 日 K（`f51..f56`=日期,开,收,高,低,量）+ 市值 **f20**（实测纠正了 f116 惯用法）+ KDJ（1/3 平滑）+ 箱形统计（type-7 分位，min-5 样本门）。
2. **OpenAI 等非上市红线**：`NON_PUBLIC_EQUITIES` 注册表（OPENAI/ANTHROPIC/BYTEDANCE）结构性无任何价格字段、分支不触行情外呼；估值唯一口径=官方公告（OpenAI 8520 亿美元 2026-03；Anthropic 1830 亿美元 2025-09）或明确标注的公开报道口径（字节跳动约 3000 亿美元 2024-12 回购定价，注明非官方财报）。
3. **汇率**：`sources/fx_data.py` 东财主源 10 对实测（USD/CNY→133.USDCNH 现货；EUR/CNY、JPY/CNY[100日元中间价 unit_base=100]、HKD/CNY→120.*；USD/JPY、EUR/USD、GBP/USD、USD/KRW、USD/HKD、USD/SGD→119.*）；**USD/TWD、USD/MOP、USD/AED 东财无源→诚实「暂无数据」**；表达面解析 `parse_fx_query`（美元兑人民币/USD-CNY/100日元换多少人民币/日元汇率/匯率繁体）。
4. **指数多源交叉查验（新，用户裁定）**：`sources/market_crosscheck.py`——腾讯 qt.gtimg.cn 二次核验 6 个已验证映射（上证/深成/创业板/恒生/道指/标普），两源一致卡脚注声明「已与腾讯行情交叉核验 ✓ n/n」，不一致显式标注双方数值，通道不可用保持沉默不声明。**实测双源数值逐位一致**（道指 52573.29 等）。100.NDX 刻意不映射（东财口径=综合指数，与腾讯 .NDX 纳斯达克100 不同，避免假告警）；同花顺无免费稳定通道（需 hexin-v 反爬令牌）未接。
5. **MOEX 真走势（新）**：`fetch_index_trend("100.IMOEX")` 改走 MOEX ISS `/iss/history` 尾部窗口（cursor TOTAL 分页），实测取回 30 个真实收盘——MOEX 卡从「暂无历史走势数据」升级为真折线；ISS 端点故障时自动回退缺口文案。
6. **能力层**：`capabilities/stocks.py`（个股卡含 KDJ/市值/趋势折线/多日收盘分布箱形图；未点名公司→九家面板卡含多股日收益分布箱形图）、`capabilities/fx.py`（东财主源 + 面板卡 + 兑换换算 + 反向换算标注）、`capabilities/market.py`（涨跌额/数据源/数据时间/延迟/交叉核验脚注）。触发词多语言：简体+繁体（大盤/股價/個股/匯率/兌換/換匯）+英文（stock|stocks、fx|forex|exchange rate，词边界）。
7. **生产接线（C5）**：base_router 增 `RouteKind.FX`(41)/`STOCKS`(42) 与 matchers（config 开关 `bot_fx_enabled`/`bot_stocks_enabled` 默认开）；`__init__.py` 分发接线 + OFFLOADED 池 + divination/today_history 生产调用点传入共享 render backend；`tests/test_finance_routing.py` 31 用例。

### C. 功能卡片补全（C3）
- 占卜（八字/塔罗/金钱卦）与历史上的今天：卡片适配就绪（payload 构造 + mixed/text 逐字节兜底 + request_id 去重键），20 用例；生产接线已由 C5 完成（传入后端即出图）。

### D. 图表库（C2）
- `sources/finance_chart.py`：`line_chart_svg`（首尾涨跌自动红绿，<2 点→unavailable）、`box_plot_svg`（inclusive 五数、1.5×IQR 须、离群点、列级 ≥4 样本门、labels html 转义）、`daily_returns`。**K 语义=K 线烛台 OHLCV**（KDJ 独立为 KDJSnapshot），单日 OHLC 被守门拒绝画箱形图。

### E. 菜谱图片（C2 + 用户裁定预热）
- eat.py 质检升级：候选按序遍历 + PIL 像素校验（min 边≥300、宽高比 1/3~3、verify 拒坏图）+ `来源落盘 <菜名>.source.txt`；四级封面来源（本地图包→SQLite 图库索引→抓取缓存→空）。
- **图库预热已执行**：`python -m plugins.bot_unified_runtime.capabilities.eat --limit 0` 全量 61 道菜 **60 道成功入库**（food_images/ + library.sqlite + source.txt 来源记录；仅「蒜香排骨」本轮无合格图，下次预热自动重试）。

### F. 真实渲染验收（用户质疑「html 对吗」的正面回答）
- 浏览器直接打开 templates/*.html 看到的是 **Jinja2 源码占位符**（{{ }}/{% %}），不是渲染产物；真实渲染 = bridge 注入数据 → Playwright 截图。
- 两轮真机验收（生产同款管线、实时数据）：8 张 PNG 全部亲眼检查通过——行情卡（实时点位/涨跌额/折线/MOEX 走势/交叉核验脚注）、汇率卡（10 对实时中间价）、面板卡（九家折线 + 箱形图）、universal/song/affinity/stocks。验收图存本机临时目录（agent-c-visual）。
- **验收抓到并修复一个真实线上级 bug**：东财 kline 接口 2026-09-13 起缺 `end` 参数返回空（market_data/stock_data 两处 `_KLINE_URL` 已补 `&end=20500101`，有回归测试锁死）。

### G. mermaid「真机 None」根因修复（C6，重要）
- **根因不是 CDN/预算**：是 Playwright 自愈机制的结构性缺陷——`render_backends._close_thread_browser` 对 ctx（PlaywrightContextManager）调用不存在的 `.close()`（AttributeError 被静默吞掉），僵尸浏览器的传输掐不断 → 该线程 asyncio loop 永久中毒 → 后续渲染**永久 None 直到进程重启**（这正是 2026-09-12 17:28 生产事故形态）。
- **两层修复**：①`render_mermaid_png` 失败后单次重试（首败已触发自愈，重试用上新浏览器，收益提前到本张卡）；②bridge 装配钩子 `_install_ctx_exit_on_self_heal`——自愈关闭前显式 `ctx.__exit__()`；③**上游根治（主代理落地）**：`render_backends._close_thread_browser` 改为 `ctx.__exit__(None,None,None)`（旧 `.close()` 调用对象无此方法）——该缺陷影响**所有** Playwright 渲染线程，不只 mermaid。
- 实证：僵死注入两轮单次入口即救回；3 连跑 89679/88781/86591 bytes 稳定出图；回归 120 passed。诊断脚本存本机临时目录（agent-c6-mermaid）。

### H. 文档门禁、四门禁与终验（C7 + C8 + 主代理）
- `test_documentation_consistency` 两门禁已绿（route-matrix 的 fx/stocks 两行由 B 方向在途改动覆盖，catalog 经 `--write` 再生成幂等校验一致）。
- C 方向合并终验 **610 passed, 3 skipped**（19 个测试文件；skip=环境变量门控网络测试）；ruff C 方向全部文件 All checks passed；`git diff --check` 干净。
- **工作区四门禁全绿（C8）**：lint ✅（修复 stocks.py 重复导入/finance_data 导入序）· **typecheck ✅（mypy 零问题）** · runtime-layout ✅（源码树运行数据残留的测试 SQLite 已备份至本机临时目录后清理）· test ✅。
- 他方向 lint 残留 3 处（归 R/character 方向收尾）：`character/__init__.py:30` RUF022、`contracts/__init__.py:9` F401（AddressingContext）、`tests/test_admin_roster_and_roles.py:42` C408。

### I. C9 独立代码评审与修复（2026-09-13 终态）
独立评审（实跑复现式）结论：数据层/契约层/渲染层质量高、测试密度足、诚实降级到位；发现 **P0×1 + P1×2 + P2×2**，已全部修复并补回归测试：
- **P0-1（已修）**：fx 直盘参考行忽略 unit_base——「日元兑人民币」曾展示 `1 JPY = 4.3614 CNY`（100 倍错误）。修复为按 unit_base 折算（`1 JPY = 0.043614 CNY`）+ 回归断言锁死（`1 JPY = 4.3614` 不得出现）。
- **P1-1（已修）**：个股/汇率触发面过宽劫持日常聊天（「我想吃苹果」→苹果股价卡、「单位换算」→汇率卡、「I bought some stock」→面板卡）。修复：纯公司别名必须伴随股票语境词（股/市值/行情/价格/涨跌）；非上市公司别名（openai/anthropic/字节）豁免语境（估值查询是合法意图）；英文 stock 须伴随 price/market/quote/tech/us；裸「换算」须同句含币名。补 12 条触发面回归。
- **P1-2（已修）**：繁体「大盤」入触发词但语境守卫未收录——`_STOCK_HINT_RE` 补 大盤、`_NON_STOCK_RE` 补 繁体（房價/幣圈/顯卡/期貨/匯率），繁简守卫语义一致（测试锁死）。
- **P2-1（已修）**：crosscheck 差异分支对 change_pct=None 会 TypeError 且 price=0 被误判「一致」——改为 None 容错展示「未知」、0 价按差异处理。
- **P2-2（已修）**：九家面板改用带 10 分钟 TTL 的 `fetch_stock_history`（原每次 9 个无缓存外呼）；个股查询现价+市值双外呼问题登记为低优先级（需 provenance 链缓存，本轮不动）。
- P3 全部记录未动（fx 卡文件名覆写、单币种查询附面板卡、_get_browser launch 失败泄漏传输线程等——见九.文件清单后的原评审报告存档位置：本文件同目录无，C9 报告全文见会话记录）。
- 修复后终验：**610 passed, 3 skipped**（19 测试文件）+ ruff All checks passed + `git diff --check` 干净。

---

## 二、未完成部分（按优先级）

| # | 事项 | 状态/交给谁 |
|---|---|---|
| 1 | ~~route-matrix/command-catalog 文档门禁~~ | ✅ 已绿（B 方向在途改动覆盖 + catalog 幂等确认，C7 核验 20 passed） |
| 2 | ~~mermaid 真机 None~~ | ✅ 根因修复（C6，见一.G；重启生效） |
| 3 | bot 重启后真机验收：行情卡折线与交叉核验脚注、股票面板/箱形图、fx 面板、占卜/历史卡、帮助/用量卡新视觉、mermaid | 需用户提权重启后人工看图 |
| 4 | usage_cards/echo/debug 三处 f-string 卡与 Jinja 模板的「布局结构层」统一（当前只统一了 token 值层，DOM 各自独立） | 低优先级重构，建议出独立规格再动 |
| 5 | 箱形图其余用例上卡（指数波动率比较、汇率波动范围——后两者当前无历史数据源，只能等源） | 有源后再接 |
| 6 | 东财美股/指数接口凌晨限流（02:00-02:40 实测间歇性空响应）→ 可考虑请求退避/错峰 | 已有「失败→诚实降级」兜底，非阻塞 |
| 7 | 占卜/历史卡 **emoji 点缀**未做：卡片文案被既有测试逐字节锁定，加 emoji 需先定契约（标题加 or 正文加，改哪侧测试） | A 裁定后 10 分钟工作量 |

---

## 三、低可信度部分（诚实声明）

1. **真机 PNG 视觉效果**：验收图全部由本机 Playwright 真跑 + 亲眼检查（high→verified），但生产环境（管理员权限服务、常驻浏览器复用、多卡并发）下的表现未验证——尤其 PlaywrightRenderBackend 线程本地浏览器在重启后的首启。
2. **OpenAI/Anthropic/字节跳动估值数字**：OpenAI/Anthropic 来自官方公告 URL（verified 来源存在性；数字我方无法独立审计）；字节跳动为公开报道回购定价口径（low→medium，代码与卡面均明示「非官方财报」）。
3. **东财 kline `end` 参数**：差异探测（带 end=有数据/不带=空）支持「必须带」结论；但不能排除「限流叠加」的混淆因素——若生产出现 K 线全空，优先查此参数与限流。
4. **腾讯长格式字段序（[31]=涨跌额/[32]=涨跌%）**：实测于恒指/道指/标普（verified）；其余市场若未来加入映射需重新实测字段序。
5. **占卜/历史卡的真机出图**：payload 与 weather/epic 逐字段同构（high），未真机截过图（today_history 数据源夜间不可拉）。
6. **C5 的启动函数体内部接线**：以 AST 断言 + 模块导入验证（无法离线启动 nonebot 单测），残余风险低但未运行时验证。

---

## 四、新发现（A Agent 需要知道的事实）

1. **东财 kline 接口行为变更**：缺 `end` 参数返回空 klines（2026-09-12 还不需要）。已在两处 URL 修复 + 测试锁死。**建议**：全仓 grep 其他使用 push2his 的模块确认无漏网。
2. **东财/腾讯凌晨限流**：02:00-02:40 高频调用会得到空响应/缺行（非 JSON 错误）。现有「失败不缓存+诚实降级」已覆盖；但 **market_data 旧实现会把空走势缓存 10 分钟**——已改为「空结果不缓存」，建议保持该纪律。
3. **`market_card.html` 曾缺 `.card` 根类**：导致该卡长期走整页截图路径（透明边）。已修；建议重启后对比该卡图片边缘确认。
4. **100.NDX 口径差异**：东财「纳斯达克」(100.NDX 实为综合指数口径 26333) ≠ 腾讯 .NDX 纳斯达克100 (29368)——交叉查验映射刻意排除，任何接入第二指数源的人需注意。
5. **多代理并发现实**：本会话期间 echo.py 曾出现他方向在途语法错误（全角括号入码，几分钟内被其作者自行修复）；base_router/__init__/route-matrix 均带多方向在途 hunks。**建议**：A 汇总时对共享文件做一次整体 review。
6. **`docs/rendering-contract.md`**（新）：渲染契约的软文档，模板改动前必读；契约测试会检查其存在与关键词。
7. **test_market_card.py 等 6+4 个测试文件从无到有**：金融/渲染域此前近乎零覆盖，现在任何模板/token 改动都会被 ~571 用例咬住。

---

## 五、建议（给 A Agent 的行动清单）

1. **立即**：确认 C6/C7 结果（若未完成按上表 #1/#2 收尾）；然后 `dev.ps1 -Task test / lint / typecheck / runtime-layout` 全量四连（typecheck 全仓 238 文件本次未跑，多代理在途状态归属不清）。
2. **重启前**：`git diff --stat` 全量过目（多方向在途 hunks 混杂）；确认无 `data/`/`__pycache__` 残留（runtime-layout 任务）。
3. **重启后真机验收清单**（按卡）：行情卡（折线+交叉核验脚注+MOEX 走势）→「英伟达股价」（KDJ/市值/箱形图）→「美股股价」（九家面板+收益分布）→「汇率」（10 对+暂无数据行）→「美元兑人民币」「100日元换多少人民币」→ 占卜/历史上的今天出图 → 帮助卡/用量卡新视觉 → mermaid 代码块出图。
4. **文档**：本文件与 docs/rendering-contract.md 归档进 HANDBOOK §三/相关章节时，保留「无 viewport=铁律」「K=K线非 KDJ」「TWD/MOP/AED 无源」「东财 kline 需 end 参数」四条事实。
5. **B 方向协同**：command-catalog/route-matrix 已由 C7 机械同步，B 若有 trigger 词表改动需同步 capabilities 三个正则与文档门禁。
6. **后续增强候选**（收益排序）：东财请求退避/错峰（治凌晨限流）→ 箱形图上「指数波动率比较」（等源）→ 同花顺通道调研（hexin-v 令牌逆向成本高，建议放弃或找付费源）→ f-string 三卡的 DOM 层统一。

## 六、计划（若 A 继续此方向）
1. 重启后按上面清单逐卡验收，问题按 systematic-debugging 走。
2. 东财限流观察一周：若白天生产时段出现空响应，加 429/空响应退避重试（单次重试 + 指数退避，保持「失败不缓存」）。
3. 占卜/历史卡出图后，把 emoji 丰富度做一轮实调（当前走 universal/media 卡文本通道，emoji 已可安全渲染）。
4. 预热机制日常化：蒜香排骨等 MISS 项可在任意时点重跑 `python -m plugins.bot_unified_runtime.capabilities.eat`（幂等，只补缺失）。

## 七、未解决漏洞 / 遗留风险台账

| # | 漏洞/风险 | 严重度 | 状态 |
|---|---|---|---|
| 1 | 东财上游对高频/夜间请求返回空（无错误码）——限流无法程序化区分「真无数据」 | 中 | 已用「空→诚实降级」兜底；退避重试未做 |
| 2 | ~~documentation_consistency 两门禁红~~ | 中 | ✅ 已绿（20 passed，C7） |
| 3 | ~~mermaid None~~ | 低→中 | ✅ 根因修复（C6 + render_backends 上游根治，重启生效） |
| 4 | ~~全仓 mypy/typecheck 未跑~~ | 中 | ✅ 已跑：mypy 247 文件零问题（C8）；另有 3 处他方向（R 系列/character）lint 残留归该方向收尾 |
| 5 | 生产 bot 未重启——本方向全部改动（含路由 fx/stocks、图库、图库预热）待生效 | 高（阻塞验收） | 等用户提权重启 |
| 6 | eat.py 无 TTL 的常驻图包缓存（按设计是资产库，但无容量上限） | 低 | 图库 61 张体量小；扩展菜品库时需配额清理 |
| 7 | fx 兑换查询的「反向换算」在 unit_base≠1 的对（JPY/CNY→CNY/JPY）数学已验证、真机文案未人审 | 低 | 重启后看一眼「1人民币≈多少日元」文案 |
| 8 | 交叉查验只覆盖 6 指数（腾讯无已验证代码的 12 指数不声明） | 低（设计取舍） | 有新源再扩 map |
| 9 | **Playwright ctx 生命周期上游缺陷已根治**（`_close_thread_browser` 现在正确 `ctx.__exit__`）——但 2026-09-12 生产 17:28 事故即此形态，重启前旧进程仍会复发 | 中 | 已修待重启；C9 评审复核中 |
| 10 | C 方向代码评审（C9）P0/P1 发现 | 待定 | C9 运行中，结果回填 |

## 八、本轮触达文件全集（供 review）
改：bridge.py、market_card/universal_card/affinity_card/mermaid_card/song_candidates.html、capabilities/{market,stocks,fx,eat,divination,today_history,echo,debug}.py、output/{templates.py,card_render/usage_cards.py}、sources/{market_data,stock_data,fx_data}.py、runtime/base_router.py、__init__.py、docs/route-matrix.md。
新：theme_tokens.py、finance_card.html、contracts/finance.py、sources/{stock_data,fx_data,finance_chart,market_crosscheck}.py、capabilities/{stocks,fx}.py、docs/{rendering-contract.md,handover-c-20260913.md}、tests/{test_rendering_contract,test_finance_data,test_stock_data,test_fx_data,test_finance_charts,test_market_card,test_eat_image_quality,test_feature_cards,test_finance_routing,test_mica_builders_contract}.py。
（echo/debug/usage_cards/templates 的 diff 内混有他方向在途 hunks，review 时以各子代理报告的 hunk 清单为准。）
