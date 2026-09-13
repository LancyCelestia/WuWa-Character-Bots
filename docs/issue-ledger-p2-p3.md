# P2/P3 问题台账（2026-09-13 实战审计批）

> **本文件定位**：AGENTS.md 第六部分是问题索引，本文件是 P2/P3 逐条**可执行详情**——
> 每条写清：现象是什么、问题出在哪个文件哪一行、根因是什么、影响谁、怎么修、
> 修完怎么验收。接手者无需考古即可动手。
> 分级口径沿用用户给定四级表：P0 致命 / P1 严重 / P2 一般（有绕行，排期修）/ P3 轻微（backlog）。
> P0/P1 已在 2026-09-13 当日处理完毕（见文末「本批已闭环」），此处只留活口。

---

## P2（排期修复）

### P2-1 cryptography CVE ×3 —— 上游阻塞
- **现象**：pip-audit 报 `cryptography 48.0.1` 命中 PYSEC-2026-3552/3553/3554，修复版 49.0.0/50.0.0。
- **位置**：Runtime venv 依赖图；唯一使用方 `nonebot-adapter-qq 1.7.2`（已钉死 `cryptography<49.0.0,>=43.0.3`）。
- **根因**：适配器上游版本约束与安全修复版本互斥；PyPI 上 1.7.2 已是最新（无放宽约束的版本）。
- **影响**：QQ 适配器的密码学路径。CVE 细节以 pip-audit 数据库为准；bot 场景（QQ 适配器本地签名/token）暴露面有限。
- **修法**：等 nonebot-adapter-qq 放宽到 `>=49` 后 `pip install -U cryptography`；或换用维护中的适配器分支。**禁止**无视钉死强升（2026-09-13 已试装 50.0.1 即遭 pip 依赖冲突，已回滚 48.0.1 并以 `pip check` 验证零冲突）。
- **验收**：升级后 `pip check` 零冲突 + 重跑文末 CVE 复审命令，cryptography 行消失。

### P2-2 aiosmtplib CVE ×2 —— 上游阻塞
- **现象**：pip-audit 报 `aiosmtplib 3.0.2` 命中 PYSEC-2026-2338/3805，修复版 5.1.1/5.1.2。
- **位置**：唯一使用方 `nonebot-adapter-mail 1.0.0a7`（metadata 钉死 `aiosmtplib~=3.0`）。
- **根因**：同 P2-1，跨两个大版本的修复与适配器约束互斥。
- **影响**：SMTP 客户端路径；SMTP 服务器是用户自配的可信端点，实际暴露面有限。
- **修法**：等 nonebot-adapter-mail 出支持 `aiosmtplib>=5.1.2` 的版本。
- **验收**：同 P2-1。

### P2-3 渲染 Phase 2 并发/预算解锁
- **现象**：渲染等待预算与并发框架已落地但**缺省关闭**（字节级等价安全位），真实收益未生效。
- **位置**：`plugins/bot_unified_runtime/output/render_backends.py`（`:213 max_concurrency: int = 1`、`:319/:391 wait_budget_ms` 消费点、`:453` 实例化点）；规格 `docs/design/render-pipeline-optimization-spec.md`；执行清单 `docs/perf-optimization-plan.md`。
- **根因**：Phase-1 刻意只落框架不动缺省（等重启实测后再解锁）。
- **影响**：多卡并发时渲染串行排队；固定 sleep 等待地板未消除。
- **修法**：按 perf-optimization-plan 的 Phase 2 清单接线配置键并灰度。
- **验收**：见 perf-optimization-plan §验收。

### P2-4 U14 反注入护栏文案（产品裁决）
- **现象**：触发反注入护栏时，回复文案向触发者**明示**「系统提示/密钥/本机文件」存在。
- **位置**：`plugins/bot_unified_runtime/capabilities/chat.py:2150` 一带（护栏 body）。
- **根因**：威慑设计与攻击面提示之争，属产品裁决非文字问题（q1-inventory U14）。
- **影响**：恶意用户可从文案反推防御焦点；普通用户无感。
- **修法（二选一，等用户裁定）**：①保留威慑版；②改极简版「我不能聊这些，换个话题吧」。
- **验收**：改后跑 chat 反注入相关测试 + 人工发一条注入样例看回复。

### P2-5 help Mica 卡两栏排版
- **现象**：help 深度页四要素连排在 Mica 卡上单栏过长。
- **位置**：`docs/rendering-contract.md` 口径下的 help 卡模板/`_split_facets` 消费链（F13 残余）。
- **影响**：纯观感，信息完整。
- **修法**：卡模板两栏 CSS（遵守渲染契约：无 viewport、body 透明、动画在 .card 内）。
- **验收**：契约测试全绿 + 真机卡面人工过目（§6.6）。

### P2-6 f-string 直拼卡 DOM 统一
- **现象**：4 处 f-string 直拼卡未走 Jinja 模板共享壳，改 UI 需多处同改。
- **位置**：规格已成文 `docs/design/fstring-card-dom-spec.md`（Python 侧共享 mica 壳方案），**未实施**。
- **影响**：维护成本；不构成线上缺陷。
- **修法**：按 spec 实施（成文在先原则已满足）。
- **验收**：`test_mica_builders_contract.py` + 相关卡测试全绿。

### P2-7 cron/调度用系统本地时区
- **现象**：每日通讯 21:30、提醒投递等调度按宿主机本地时区算。
- **位置**：调度器族（`__init__._register_digest_push_scheduler` 等，台账 #3/#6 同源）。
- **影响**：异时区机器迁移后安静时间/推送时刻口径偏移。
- **修法**：调度统一改 `zoneinfo` 显式时区（配置键注入）。
- **验收**：改时区环境变量后断言触发时刻不变（新增单测）。

### P2-8 SQLite 限流路径不支持热改 + 调度器装配期 config 快照
- **现象**：`/bot runtime set` 热改限流参数对 SQLite 限流路径不生效；G-DIGEST 等调度器在装配期快照 config，当夜热改不生效。
- **位置**：policy/gate 限流实现 + 各调度器注册点（台账 #3 原文）。
- **影响**：管理员改参数需重启才全量生效（当前重启本来就要做，暂无实际损害）。
- **修法**：统一改造为「运行时读 config 现值」模式——架构级改动，单列排期。
- **验收**：热改后不重启，限流/推送行为随之变化（集成测试）。

### P2-9 触发词三语全量普查残余
- **现象**：简/繁/英触发词已按 T-Spec 收口 52 词/13 topic + tra49 批，但「全量」普查（逐词反查路由正则 vs help 注册）未建立机械门。
- **位置**：`tests/test_trigger_spec.py` 棘轮 + `scripts/extract_trigger_words.py`。
- **影响**：未来新增能力可能再现「路由有、help 搜不到」（求籤 即此类漏登实例）。
- **修法**：给 `_HELP_ALIAS_MAP` ↔ 各能力 `_COMMAND_RE` 建双向机械比对门（能力侧词表为真值源）。
- **验收**：故意删一个别名时门禁红；全量绿。

### P2-10 渠道价目表 52 条审计——可疑/过时/unknown 清单（等用户更新价目表）
- **现象**：2026-09-14 六域批账单席对价目表 52 条逐条核对（官方直连按厂商刊例逐位核对；中转按 ¥7.2/USD 折算判定，low 置信，影响的是"可疑"带宽不影响官方逐位核对），发现多档可疑/过时/unknown。分档口径与逐行全表见 `.superpowers/sdd/2026-09-13-six-domain-batch/billing-report.md` §3。
- **计数**（billing-report §3.3 原文）：官方直连 11 行=7 OK+1 可疑+2 过时+1 unknown；中转 41 行=4 可疑-高+18 可疑-低+2 低-关注+13 OK≈+2 unknown（2 过时与可疑-高重叠计数）；axonhub 网关覆盖 3 条含 2 unknown。
- **需用户更新价目表的 6 项优先清单**（照 §3.3 摘录）：
  1. api.deepseek.com **deepseek-v4-pro**：输入 3→谷 4.5/峰 9、缓存 0.10→0.15（现价与谷/峰两档均不符，低估 33%~67%）。
  2. api.deepseek.com **deepseek-v4-flash / deepseek-v4-flash-vision-exp**：官方已下线，旧名由 V4.1-Flash 接管按谷 1/4 计费。
  3. newapi.qianqianye.com **deepseek-v4-flash(-vision-exp) 4.5/13.5 与 v4-pro 13.5/40.5**：官方价的 3~4.5 倍（可疑-高），确认实收或弃用。
  4. newapi.qianqianye.com **gpt-5.6-luna 3/18**：官方折算 ¥1.44/¥8.64 的 2.1 倍，倒挂。
  5. aiprc.top **claude-fable-5 (1.5/7.5) vs fable-5-1 (10/50)**：两行同官价内部矛盾 6.7 倍，必有一错。
  6. axonhub **gemini-3.8-flash 裸名 0.3/1.5**（GATEWAY_OVERRIDES「恒星纪元」注释）：与 starapi.cc 裸名 1.35/6.75 不一致，需用户确认该路径上游归属。
- **结构性提示**：①DeepSeek 官方峰谷差价（峰=谷×2），注册表单一价按谷价记账→峰时调用账单低估一半，如需精确需扩 price 字段（超本批范围未动）；②多个中转按「官方美元数值×固定小倍率当人民币」计价，若与渠道实际扣费一致则记账无误，建议核对一次真实扣费账单。
- **修法**：用户核对后走 `/bot model price` 热改，或改 `scripts/import_model_prices.py` 后 `--apply` 重跑。
- **验收**：更新后按 billing-report §3 方法复跑价目审计对照，优先 6 项转 OK/确认。

### P2-11 账本历史行 cost 千倍虚大——清洗裁定待用户
- **现象**：`ledger.build_call_draft` 旧实现 `round(tokens × price)` 未除 1000，按「价=元/1M tokens、cost=毫厘（1 元=1000 毫厘）」口径 cost 恰放大 1000 倍；代码已修（`/1000`，与 `runtime/pricing.model_call_cost_milli` 同口径），但**生产 store 中 `pricing_source='channel_spec'` 的历史行（若 `BOT_LLM_BILLING_ENABLED` 开过）费用列仍虚大 1000 倍**。
- **位置**：生产账本 store（llm/ledger.py 写入路径）；事件日志 transport_receipt cost_milli 走 pricing.py 正确口径，**不受影响**。
- **修法（等用户裁定，本批未动生产库）**：①按 1/1000 批量 UPDATE 历史行；②加标注字段不动数值；③账本从未开过则无需动作。
- **验收**：裁定后抽 3 行历史+1 行新写入对账，cost 与 `/bot model usage` 面板一致。

### P2-12 HTTP 抓取重定向「事后复查」家族残余——彻底收敛需禁区 http_util 连接级逐跳校验
- **现象**：全部用户 URL 抓取护栏（downloader/notes/eat/parser 解析链）均为「响应已取回后」判定——入口+最终 URL 双查拦得住**内容回显**，拦不住**请求本身**（302→内网的盲 SSRF 一跳仍在）。
- **位置**：`sources/parsers/http_util.py`（http_get* 全家，禁区文件）；已挂入口+落点双查的点位=`capabilities/notes.py:196-199`（geturl 双查先例）、`capabilities/eat.py`（93e8195 补落点复查）、解析链（`content_parser.py:654` guard_user_url 入口 + `platforms_generic._og_scrape` check_fetch_landing 落点，本批工作树未提交）；`sources/downloader.py:370-372` docstring 自认残余。
- **根因**：urllib 默认自动跟随 30x 且逐跳不复查。同源窄攻击面残余：①DNS rebind 窗口——自控域首次查询 NXDOMAIN 过入口、抓取时解析到内网（og 兜底落点复查仍拦回显；深解析链 xhs/douyin 抓的是平台自有域短链，攻击者无法投毒重定向，实际风险低）；②非 og 深解析抓取（xhs INITIAL_STATE、douyin _ROUTER_DATA 等）无落点复查（入口护栏已拦字面量内网 URL）。
- **影响**：盲 SSRF 一跳——借「候选是否被接受落盘」差异侧信道探测内网端口存活；个人 NAT 部署真实靶标=本机 NapCat 3001（无鉴权 WS）/webhook 8080/control plane 8742（有 Bearer）。
- **修法**：http_util 出口统一挂连接级逐跳校验（自定义 no-redirect opener，逐跳过 `check_download_url`）——禁区文件，先评审再动；DNS rebind 可加「入口解析与真实抓取前二次解析比对」或接受现状（落点复查已拦回显）。
- **验收**：构造 302→`127.0.0.1:8742` 候选 URL，断言连接层未发出请求（而非仅内容不入卡）；解析域既有回归（16 文件 163 例）全绿。
- **出处**：security-report M-5/I-2 残余 + ssrf-guard-report §6（三条残余同源，收编一条防重复立条）。

---

## 已裁定/已定性（无需动作，防重复考古）

| 项 | 裁定/定性 | 证据 |
|---|---|---|
| 10 个死配置键 | **有意设计非误留**（4 个休眠预留模块，docstring 写明），保留不加标注 | R65（final-report-draft.md）|
| route-matrix 覆盖门子串匹配偏弱（M-2） | **已修**：`tests/test_documentation_consistency.py` 改 `\b{kind}\b` 词边界，MARKET 不再撞 STOCK_MARKET | 2026-09-13 实改+测试绿 |
| `zb` 拼音归属 | **设计裁定：永不启用**（bz/zb/sz/sm 四缩写真冲突，divination.py 词表注释钉死）+ 测试锁 `test_conflict_initials_stay_disabled` | 2026-09-13 实改 |
| `求籤` 触发词 | **已另立**：入 `_ICHING_RE`+`_DIVINATION_COMMAND_RE` 双正则 + echo aliases/META 注册 + help 搜索可命中 + 回归锁 | 2026-09-13 实改 |
| qx.json 三次消失 | **根治**：随包入库（.gitignore 例外早已就位，文件本体 2026-09-13 提交后由 git 兜底） | 提交哈希见提交批 ⑥ |
| 根目录 `.mypy_cache` | 历史裸跑 mypy 残留（dev.ps1 本身已正确外置 cache 到 Runtime），已清 | dev.ps1:325 `--cache-dir` |
| `.claude/.codex/.grok` 未跟踪目录 | 本地工具配置，已加入 .gitignore | 2026-09-13 实改 |
| curl-cffi 0.14.0 CVE | **已升** 0.16.3（无反向依赖），CVE 清零 | pip-audit 复审 |
| fin/billing 两报告 per-file 测试计数笔误 | **已勘误**：独立评审 --collect-only 实跑核对——金融合计 66 恰好一致（per-file 分布虚报）、账单实跑 20 多于声称 18（方向安全）；无虚报通过数，不影响交付实质 | review-fin-billing §一 |
| run_code_debug 非沙箱执行上传代码 | **已文档化的接受风险**：admin 门 verified 存在 + `python -I` + 最小 env；保持 admin-only 红线即可，不另立项 | security-report M-7（file_exchange.py:57-114 + __init__.py:3935） |
| 解析链护栏 DNS 解析失败放行 | **设计裁定**：`RejectedUrlError.__cause__` 为 gaierror（结构判定非字符串匹配）时放行——油管/推特/Pixiv/FB 走 bot_download_proxy，本机 DNS 查不到≠抓不到，硬拒误伤纯代理平台；内网字面量/localhost/metadata/DNS 成功解析到内网照拒 | ssrf-guard-report §3（test_parser_ssrf_guard.py 策略锁死；护栏 5 文件在工作树待随批提交） |
| 三道菜 Bing 源缺（蒜蓉西兰花/清炒藕片/蒜香排骨） | **已闭环**：Tavily 图搜兜底上线——Bing 三轮未中菜一次全收，图库 61/61 满编实证，五道质检闸（域黑名单/SSRF/字节/magic/像素）全链复用 | bdbc88b 提交信息 + docs/handover-c-20260913.md §35（蒜香排骨 MISS 在案） |
| 导入时长门（perf-report §五草案） | **已落地**（并行席收编进 test_perf_regression，工作树待随批提交）：test_package_import_duration_no_collapse——子进程整包导入 **3 次取中位** <10s（基线 1.9~2.1s，余量 5x），docstring「import 期塞重活」缺口补齐 | tests/test_perf_regression.py:78/88（可复跑：pytest 该用例） |
| 路由 P50 +14% 漂移（0.014→0.016ms） | **已定性：测量噪声非代码退化，不立项**（同代码重跑方差 ±15~25%；进程内 A/B 摘 media_archive 新规则反慢 2µs=成本低于噪声地板）；**基线口径今后以「新进程 3 次取中位」为准**（同进程长跑受 CPU 频率漂移污染） | perf-report §二/§五.4（verified 实跑） |

---

## P3（backlog）

| # | 问题 | 位置 | 修法 | 影响面 |
|---|---|---|---|---|
| P3-1 | bot 头像页脚用「守」字圆点 | `.env` BOT_PERSONA_AVATAR_URL 为空 | 用户提供头像图路径后配置 | 纯观感 |
| P3-2 | F6 meme 心情驱动主动发 | capabilities/meme_library.py | 需完整防骚扰门（概率×心情×冷却×NSFW×白名单），有意不做半吊子 | 主动社交体验 |
| P3-3 | F7 随机 cos 照片 | 等用户提供 gs_kuro_cos 插件+油猴脚本 | 借鉴其接口做 xhs/推特 cos 图随机发 | 新功能 |
| P3-4 | Ghost Downloader aria2 RPC 集成 | sources/downloader.py | 用户开 RPC+确认端口/token 后自动委托（装 aria2 即可） | 下载提速（可选） |
| P3-5 | 23:00 性能收尾批 | 见 `docs/perf-optimization-plan.md` | 定时任务自动执行 | Phase 2 解锁+五链路实测 |
| P3-6 | TG 正文嵌套块级元素早停（罕见残余）；social_v2 同函数 channel_title/bio 未改 | sources/parsers/social_v2 | 有实据再修 | 罕见 |
| P3-7 | Apple Music #fa243c × 小红书 #ff2442 accent ΔE=2.7 近不可辨（17 平台互异最小值，visual-report P3-1） | output/card_render/theme_tokens.py PLATFORM_THEMES | 两者均官方品牌色，动谁都伤品牌忠实度（实际靠页脚展示名文字区分）；若拉开建议 Apple Music → 粉品红系——**待用户裁决** | 卡面平台 accent 观感 |
| P3-8 | 视觉收官轮遗留裁决包（visual-report §2/§3/§7）：①universal/旧媒体卡页脚第二槽 'Shorekeeper' 是否改功能名「解析」；②usage 卡 kicker「测试 · 模型用量」与标题部分重复的去留；③market/finance data-foot 11.5px（<12px 下限，别席域）待收口+两测试文件豁免注释同步；④echo/debug 卡 9px/10px+脱刻度字距与 gap 9px 豁免待并入 | bridge.py / usage_cards.py / market_card.html / finance_card.html / echo.py / debug.py | 均为低收益打磨项，逐项用户裁决后按渲染契约收口；③④收口时随其批次 verify_hashes --write | 纯观感 |
| P3-9 | 账本聚合查询无 completed_at 前缀索引（账本量级下可忽略，报告已自行登记） | `llm/ledger.py` `aggregate_channel_usage`（substr(completed_at,1,10) 日界过滤全表扫描；5ba7c0f 已改完整常量 SQL，索引仍未建） | 修法：日界过滤改日期范围比较 + completed_at 建索引；验收：EXPLAIN QUERY PLAN 走索引，账单席回归绿（review-fin-billing 观察③） | 账单聚合查询耗时 |
| P3-10 | 价目审计 ¥7.2/USD 汇率假设影响中转「可疑」分档带宽（P2-10 方法学补充；官方直连逐位核对不受影响） | billing-report §3 审计口径 / P2-10 | 修法：并入 P2-10 用户核对动作——按渠道真实扣费账单复核中转 41 行分档，汇率敏感行单独标注；验收：P2-10 复跑审计时分档与真实扣费一致（review-fin-billing §三） | 中转分档判定准确性（low 置信已显式声明） |
| P3-11 | 视觉报告 ΔE 数字与 token 实算不符（报告笔误，疑调参后未同步；门 ≥2.5 不受影响） | visual-report.md §5.1（ΔE(a,n)=7.99/ΔE(b,n)=9.90 vs 同模型实算 8.46/10.36）；报告为存档件 | 修法：本条即勘误记录，报告以存档原件+本条为准，不回改；验收：无（review-visual-infra M-1） | 报告准确性 |
| P3-12 | 阴影门 context_keys 手工映射——登记表新增档位需手动补行，否则新档位 :root 字面量一致性不被校验 | tests/test_rendering_contract.py:174（{"--mica-shadow-panel": "shadow_elev_panel"}） | 修法：映射改由 bridge._VIS4_KEYS 反查派生；验收：theme_tokens 临时加假档位时校验自动覆盖（改前漏检、改后红）（review-visual-infra M-3） | 契约完备性（非后门） |
| P3-13 | box-shadow 门正则依赖行尾分号——无分号收尾声明漏检（当前模板全带分号，无现行漏检） | tests/test_rendering_contract.py:153、tests/test_template_visual_audit.py:115（`([^;]+);`） | 修法：正则改 `([^;]+)(?:;|$)`；验收：构造无分号违规样例两门仍红（review-visual-infra M-4） | 契约门完备性 |
| P3-14 | clean_food_gallery 脚本三缺陷：bool("false") 误判 True（污染图反被保留）/先移动后删 DB 行非原子（两步间崩溃留孤儿行）/TEMP 取法 KeyError+写法晦涩 | scripts/clean_food_gallery.py:96 / :148-158 / :119（`__import__("os").environ["TEMP"]`） | 修法：①`payload.get("is_food") is True`；②try/except 补偿（删行失败回滚移动）或先删行失败回捞；③顶部 `import os` + `os.environ.get("TEMP", tempfile.gettempdir())`；验收：三案例单测——is_food="false" 判移出、删行失败无孤儿、无 TEMP 环境不炸（review-visual-infra M-6/M-8/M-9；图库二轮已跑完，仅影响下次复判） | 清理脚本健壮性 |
| P3-15 | NTP 无响应源校验/无 originate 回显检查（链路攻击者可伪造 mode=4 应答；被 ±max_drift 默认 1.5s 钳制兜底） | runtime/timesync.py:40,173（_addr 直接丢弃；请求包时间戳恒零无从 echo） | 修法：请求包填 transmit ts + 校验应答 originate ts 回显 + 比对源地址；验收：离线伪造应答实验（$TEMP ntp_fuzz 法）被拒、真机校时偏差仍 ≤max_drift（security-report M-1） | 提醒投递时刻最多偏 1.5s，盲注无崩溃 |

---

## CVE 复审命令（可复跑）

```bash
# 生成生产依赖快照（只读，不动 Runtime venv）：
"C:/…/ChatBot_Runtime/venv/Scripts/python.exe" -m pip freeze --all | grep -v '@ file:\|-e ' > req-freeze.txt
# 临时 venv 审计（不污染生产 venv）：
python -m venv %TEMP%/pa-venv && %TEMP%/pa-venv/Scripts/python.exe -m pip install pip-audit
%TEMP%/pa-venv/Scripts/python.exe -m pip_audit -r req-freeze.txt --progress-spinner off
```
2026-09-13 实跑基线：curl-cffi 已清零；剩 cryptography ×3 + aiosmtplib ×2（均为上游阻塞，见 P2-1/P2-2）。
