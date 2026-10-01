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
- **影响**：盲 SSRF 一跳——借「候选是否被接受落盘」差异侧信道探测内网端口存活；个人 NAT 部署真实靶标=本机 SnowLuma 3001（无鉴权 WS）/webhook 8080/control plane 8742（有 Bearer）。
- **修法**：http_util 出口统一挂连接级逐跳校验（自定义 no-redirect opener，逐跳过 `check_download_url`）——禁区文件，先评审再动；DNS rebind 可加「入口解析与真实抓取前二次解析比对」或接受现状（落点复查已拦回显）。
- **验收**：构造 302→`127.0.0.1:8742` 候选 URL，断言连接层未发出请求（而非仅内容不入卡）；解析域既有回归（16 文件 163 例）全绿。
- **出处**：security-report M-5/I-2 残余 + ssrf-guard-report §6（三条残余同源，收编一条防重复立条）。

### P2-13 文件出站面缺「洗完仍带盘符形态就整段隐去」的后置兜底
- **现象**：出站正文只过**替换式**打码，没有「打码后复查、仍泄漏就整段隐去」的第二道。中央真身
  `domains/render/plain_text.py::redact_local_secrets` 洗的是键值与形态（键名保留、值替成 `<已隐藏>`），
  若某条本机路径形态它认不出，就原样出站，无人再拦。
- **位置**：口径原住在 `domains/files/sender/restricted_runner.py::plain_outbound_body`（后置断言那一腿），
  2026-09-26 S-FILES-LAND 判**删优于接**、连同 `build_aligned_file_outbound` 等八枚符号移除（全仓零生产调用点）；
  现役三腿真身＝`domains/transport/sender/file_gateway.py` + `sender/nonebot.py` 装配段。
- **根因**：那条兜底**当年就是死件**，从未接进生产 ⇒ 退役它的锁并**没有让任何现役能力降级**；
  真实情况是这条口径在文件出站面**今天既无实现也无锁**，属既存欠账被这次退役查清并摊开。
- **影响**：走文件出站的一切随附正文（导出文档回显、QQ/TG/邮件三腿附件的说明文字）。
  边界要说准：「打码**有效**」这一半**有现役锁**＝`tests/test_file_outbound_channels.py:309→:337`
  （真网关+真邮件腿，断言正文一个「盘符+分隔符」形态都不剩、`sk-` 不残留、附件字节不被改写）；
  缺的只是「打码**失效时**」的抑制。私聊/群聊正文主链路同样无此后置兜底（同一口径，本条不扩大射程）。
- **修法**：兜底只准加在**出站咽喉**（`output/plain_text` 那一层），**严禁**在 files 域长第二份打码
  （AGENTS 第四部分「文件出站」红线＝取字节前统一判定、禁第二通路）。形态尺复用既有
  `_DRIVE_FORM_RE` 同源正则，不新烧一份。
- **验收**：新锁 monkeypatch `redact_local_secrets` 为恒等 ⇒ 断言出站正文整段隐去且零盘符形态；
  正常态断言隐去句**不**出现（否则就是把能说的也吞了）；`test_file_outbound_channels.py` 与
  `test_file_gateway_phase1.py` 保持全绿。
- **出处**：2026-09-29 S-FILEOUT-LEGS——收 `tests/test_file_exchange_restricted_runner.py` 五枚确定性红时
  裁定「甲＝维持退役」，按「安全口径不许静默消失」的要求随此立账；退役判据见该件第⑧节墓碑。

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

---

## 2026-09-18/19 统一收尾大波次缺口（unify-wave 批追加入档，2026-09-19）

> **入档口径**：编号顺延既有最大 P3-15；本批七条编号项均为 P3 轻微/backlog（无 P2），另有裁定/取证结论两条与交叉引用一条不占编号。只追加，不改既有条目。
> **来源**：`.superpowers/sdd/2026-09-18-unify-wave/` 各席 progress 检查点（2026-09-19 读取时点：BACKEND/FINMKT/MISC/UNIVERSAL/SPECS/CORE/GATES/ANIM/WEBUI/ACCEPT）。
> **在飞快照**：SWITCH 席与 WEBUIFE 席检查点截至入档时点未落盘（master-plan Wave 2 在飞），无快照可录；ANIM 席已收口（其取证结论收编本节裁定段）；WEBUI 采纳席 A-F 终态无缺陷遗留（六页真数据接线/envelope 对表/SSE 鉴权对表=Wave 2 后续席工作项，见 progress-WEBUI.md §席位终态，不入台账）。

### P3-16 stats/latency 历史曲线无持久化（history 恒 unavailable）
- **现象**：`/api/v1/stats/latency` 的 `history` 字段恒为 `{status: unavailable, reason: not_persisted}`，仪表盘无真历史曲线。
- **位置**：`plugins/bot_unified_runtime/control_plane/webui_stats.py`（`latency_view`）；数据源 channel_health store `report()` 仅存当前 EWMA/最近一次值。
- **根因**：channel_health 从不落时序——要真历史须先立时序采样表（定时快照落 SQLite），未立项。
- **影响**：延迟趋势不可回看；接口诚实返回 unavailable 不造数（数据面零风险）。
- **修法**：立项时序采样表（采样频率/保留期/库 owner 入 `docs/db-owners.md`），`latency_view` 改读表；落地前维持 unavailable 诚实体。
- **验收**：采样配置后 history 返回真序列（`tests/test_webui_stats.py` 扩例）；未配置时仍 unavailable 不报错；真机口径见 `docs/acceptance-manual.md` §6.6.9⑤。
- **出处**：progress-BACKEND.md §诚实缺口 2。

### P3-17 stats/calls 用户维度为会话键派生（audit_records 无 user 列）
- **现象**：`/api/v1/stats/calls` 的 `by_user` 按 OneBot v11 `get_session_id()` 稳定约定派生（`private_<uid>`/`group_<gid>_<uid>`/裸 uid）；审计表 `audit_records` 本身无 user 列。
- **位置**：`control_plane/webui_stats.py`（`AuditCallStatsService.calls` by_user 派生段）+ 审计库表结构。
- **根因**：审计写入面未携带原生用户标识，用户维度只能从会话键反推；约定外行（runtime/digest 等非会话来源）进 `unattributed_calls`，响应带 `user_attribution` 口径码——绝不造用户。
- **影响**：非会话来源调用无法归属用户（显式 unattributed，非错数）；前端需按口径码如实标注。
- **修法**：若需真用户维度——`audit_records` 加 user 列 + 审计写入点填充（表迁移+写入面改动，待立项）；短期靠 `unattributed_calls`+口径码诚实呈现。
- **验收**：加列后 by_user 直读列值、unattributed 归零或显式标注；`tests/test_webui_stats.py` 53 例回归绿。
- **出处**：progress-BACKEND.md §诚实缺口 1。

### P3-18 生产 `bot_audit_db_path` 默认空=内存实现，stats/calls 真数据等用户配置
- **现象**：生产 `.env` 未配 `bot_audit_db_path` 时审计为内存实现，stats/calls 在生产无真数据（200 信封内如实 `audit_source_not_configured`）。
- **位置**：config `bot_audit_db_path`（生产 `.env`，gitignored）→ `control_plane/webui_stats.py` `build_default_stats_service`。
- **根因**：默认空=内存实现系有意保守缺省；BACKEND 席按纪律未触 `.env`。
- **影响**：stats/calls 出真数据需用户先配路径；配置后控制面独立进程下次启动自带生效（无需重启 bot 主进程）。
- **修法**：用户在 `.env` 配 `bot_audit_db_path` 指向 Runtime 内路径（经 runtime_paths 重映射）；零代码改动。
- **验收**：配置后 `/api/v1/stats/calls` 返回真数据（by_session/by_capability 非空）；配置/未配置两态已被 `tests/test_webui_stats.py`+`tests/test_webui_http.py` 覆盖；真机步=`docs/acceptance-manual.md` §6.6.9③。
- **出处**：progress-BACKEND.md §诚实缺口 4。

### P3-19 玻璃 token 消费切换被 `_GLASS_MARKERS` raw 源断言阻塞（门演进待后续批次）
- **现象**：规格 §2.2-5 要求 `.row`/`.index`/`.glass` 等玻璃面改 token 消费（`var(--mica-glass-*)`），但 `tests/test_template_visual_audit.py` `_GLASS_MARKERS`（:36）对**原始模板源文本**断言 `padding-box`/`border-box` 等标记——var() 化即红。FINMKT/MISC 各面均已按 canonical 字面收口（值合规、零视觉差），token 消费切换推迟。
- **位置**：`tests/test_template_visual_audit.py:36`（`_GLASS_MARKERS`）；受影响面=finance/market `.row`/`.index`+两卡 `.bot-foot`/壳描边、affinity/song `.glass` 主规则（2026-09-19 grep 实证四模板现存 padding-box 字面 4/4/11/4 处）。
- **根因**：审计门断言对象是 raw 模板源而非渲染产物；门语义（防玻璃值漂移）与 token 单源化（值外移）结构性冲突。
- **影响**：维护单源性未达成；当前值已合规无视觉差，非线上缺陷。
- **修法**：门演进二选一——①断言对象改生成器/渲染产物产出；②改语义标记（检查 var() 引用而非字面值）。演进落地后 FINMKT/MISC 各「待补」点统一切换 `{{ glass_main }}`/`{{ glass_edge }}` 通道（bridge 已注入可用）。
- **验收**：门演进+切换后 test_template_visual_audit/test_rendering_contract/test_phase_determinism 全绿，样张 payload 数据段与基线逐字节一致。
- **出处**：progress-FINMKT.md §规格×机器门冲突记录+§遗留登记；progress-MISC.md §冲突记录①。
- **终态（2026-09-19 凌晨，主会话裁决·INTG-F 执行注记）**：`_GLASS_MARKERS` 原文断言**维持现状**；玻璃 token 消费切换**延后**（`{{ glass_main }}`/`{{ glass_edge }}` 通道键已可用，后续批次可直取）。理由：门演进风险>收益——审计门断言 raw 源防玻璃值漂移的语义与 token 单源化结构性冲突，演进需动机器门断言对象且收益仅维护单源性；当前各面字面已与 GLASS 常量逐字对齐、零视觉差，非线上缺陷。

### P3-20 universal hot-comment/forward-box 平值玻璃未并入主档（Minor）
- **现象**：`universal_card.html` :594（hot-comment）/:729（forward-box）仍为 `rgba(255,255,255,0.55)` 平值玻璃；裁决第 4 条只点名 header/content/footer 三处，两处无工单。
- **位置**：`plugins/bot_unified_runtime/domains/render/card_render/templates/universal_card.html`:594/:729（2026-09-19 grep 复核现行行号）。
- **根因**：平值不在玻璃档位登记表（GLASS_MAIN/FOOT/EDGE）内且裁决未点名，UNIVERSAL 席按边界保留。
- **影响**：纯观感/维护单源性（Minor）。
- **修法**：并入主档渐变（同 :445 content 先例，均值不变）或登记为合法档位；随 P3-19 门演进一并收口。
- **验收**：切换后 v21r3 八门+visual_audit 绿、样张目验零视觉差。
- **出处**：progress-UNIVERSAL.md §观察项。
- **已修注记（2026-09-19 GLASS2 席）**：两处（:594/:729）已并入 GLASS_MAIN 主档（样张专项图 glass2-hotcomment-forward.png 验证）。

### P3-21 song `.ttl`/affinity `.pill` 徽章两档描边（0.95/0.45）无工单项未动（Minor）
- **现象**：song_candidates `.ttl` 与 affinity_card `.pill` 徽章描边为两档 `rgba(255,255,255,0.95)/rgba(255,255,255,0.45)`，不在 C3 玻璃映射表且无工单项，本批未动。
- **位置**：`templates/song_candidates.html`:173 一带（`.ttl`）、`templates/affinity_card.html`:155 一带（`.pill`）（2026-09-19 实读复核）。
- **根因**：0.95/0.45 两停与登记档 GLASS_EDGE（0.95/0.35/0.72 三停）不一致；归 GATES 基线第 3 条（玻璃两档）口径裁决——该门本批未设（rgba 语境扫描易误伤 glow/mist，归 token 席）。
- **影响**：纯观感/维护单源性（Minor）；徽章 accent 着色 padding-box 层不受影响。
- **修法**：等基线第 3 条门禁/口径裁决后归档（归 GLASS_EDGE 或新立徽章档）。
- **验收**：裁决落地后门禁绿+样张目验描边无回归。
- **出处**：progress-MISC.md §冲突记录②；progress-GATES.md §五「基线第 3 条玻璃两档未设门」。
- **已修注记（2026-09-19 GLASS2 席）**：徽章描边 0.45→0.35 规范化（并排目验清晰可辨，未走登记制）；门 9 已锁两档（gate09[usage_report] 经 GLASS3 收口转绿）。

### P3-22 mermaid JS 上下文字体栈为全栈字面量（结构性取舍，G7 门锁逐字）
- **现象**：mermaid_card JS 初始化的 `fontFamily` 为 FONT_FAMILY_STACK 全栈逐字字面量，非 `var()` 消费——全卡唯一不走 CSS var 的字体面。
- **位置**：`templates/mermaid_card.html`:24（Jinja 注释载明取舍）/:31（fontFamily 字面量；行号为 2026-09-19 复核值）。
- **根因**：mermaid JS 配置上下文不可用 CSS var（结构性）；曾议走 bridge 注入模板变量，GATES 终版指示放弃——逐字门已锁，注入属多余复杂度。
- **影响**：无运行时影响；字面与 theme_tokens.FONT_FAMILY_STACK 的漂移风险由 G7 字体逐字门（var() 消费放行、字面量 ⊆ 登记栈）拦截。
- **修法**：无需动作（取舍成立）；未来 theme_tokens 改字体栈时 G7 门红即提示同步此字面量。
- **验收**：G7 门常驻回归即验收（改栈不同步必红）；`tests/test_v21r3_visual_gates.py`。
- **出处**：progress-MISC.md §mermaid 2；progress-SPECS.md §关键口径差（mono 四处/sans 脱钩两处）；progress-GATES.md §一 G7。

### 本批裁定/取证结论（防重复考古，不立工单）
- **TYPE_SCALE_PX 维持「声明不接线」**：字号阶梯仅作声明/参考不入消费链，全量接线列为收口规格 §六非目标边界（progress-SPECS：增补 `body_sm` 成员仅供 CORE 参考，接线非目标）。防后人把「有刻度表」误读为「模板必须查表取字号」；字号收敛实际走 C8 逐点判定（如 12.5px→12px）。
- **截图动画冻结取证结论（ANIM 席终版，已完成落地）**：`animations="disabled"` **不采纳**——infinite 动画被取消到基底位，`--phase` 钉帧位尽失（CORE 实弹：disabled 截图==animation:none 基底位，≠paused 参照帧）；`page.add_init_script` 注入 paused 样式被 `set_content` 文档重建抹除、`add_style_tag` 后注入冻结在流逝位（非钉帧位、非确定）、html `<head>` 手术破坏 `test_render_wait_budget.py:145` 对 `set_content(html)` 原样的断言——三者均否决。**采纳=render_backends `_pin_card_animations` WAAPI 钉时**（`.card` 子树全部动画含 `::before/::after` 伪元素 `pause(); currentTime=0`，负 delay 补齐=钉帧位；显式设时与调用时刻无关→双渲字节确定；fail-open）。基线重录 `baseline-20260919-paused` 19/19 面 STABLE，**自此 PNG 字节等值为全部 19 面验收判据（html_sha256 主判据口径作废）**；生产生效待重启 bot（铁律）；verify_hashes 重录归 INTG。（底册原口径「animation-play-state:paused 首帧前注入采纳」已被 ANIM 终版实证修正为 WAAPI 钉时——机制等效、实现路径不同，以本条为准。）出处：progress-ANIM.md 全文+progress-CORE.md §SAMPLES 转达取证项。

### 交叉引用（不新立条）
- **tokens 窗口过滤时区取舍**：`LedgerMetricsService.token_families`（stats/tokens 数据源）窗口过滤复用 `aggregate_channel_usage`（**P3-9**）`completed_at` 文本字典序+同进程单一时区偏移取舍——跨时区偏移混写历史行的窗口边界可能偏移，系既有取舍非本批新引入；修法/验收随 P3-9 一并收敛。出处：progress-BACKEND.md §诚实缺口 3。
- **批次内待办（非台账缺口，归 INTG 施工面）**：decor 通水（bridge 向模板上下文注入 `decor_css`/`blobs_html` 后，FINMKT/MISC/UNIVERSAL 各「通水待补」点整层换血）、`bridge._spark_points`（现行 bridge.py:1430；FINMKT 记 :1396 系并行编辑前行号）SVG 折线色第二份字面量 #d54941/#2e9e6b、verify_hashes 漂移统一 `--write` 重录——均已在其 progress §遗留登记与 master-plan Wave 3 跟踪，INTG 收口后若仍有残余再入本台账。

**本批收口状态：批次进行中，INTG 收尾后可增补。**
