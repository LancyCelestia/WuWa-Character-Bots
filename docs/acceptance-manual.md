# 验收与接入手册（Acceptance Manual）

目标：先让你把「对话/人格」跑起来并确认符合需求，再接 NapCat、GsCore 与其他插件。
全程在本机完成，不碰第三方框架账号。任何命令都从项目根目录执行：

    cd C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot

## 0. 一次装好依赖

    C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\venv\Scripts\python.exe -m pip install -e . nb-cli
    powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 doctor
    C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\venv\Scripts\nb orm upgrade      # 首次运行前初始化 SQLite 数据库
    C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\venv\Scripts\nb orm check        # 应提示：没有检测到新的升级操作

## 1. 对话 / 人格测试（第一步，必须先通过）

### 1.1 离线控制台（不需要联网，验证人格链路）

    powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 console          # 交互 REPL
    C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\venv\Scripts\python.exe -m plugins.bot_unified_runtime.console_chat --message "岸宝，你好"

离线模式用的是 static 占位回复，只能验证链路，不能验证人格文案。

### 1.2 真实模型控制台（验证人格是否符合你的需求）

    C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\venv\Scripts\python.exe -m plugins.bot_unified_runtime.console_chat --provider openai_compatible --model deepseek-v4-flash --base-url https://api.deepseek.com/v1 --api-key <你的key>

或在 .env 里配好 BOT_CHAT_PROVIDER/BOT_CHAT_MODEL/BOT_CHAT_BASE_URL/BOT_CHAT_API_KEY 后直接：

    powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 console

在 REPL 里试试这些，确认语气、动作括号、世界观符合需求：

    /岸宝帮助
    /bot status
    岸宝，你好，介绍一下你自己
    岸宝，我心情不太好（观察语气与动作括号）
    今天的天气怎么样？（观察时间/日期/节气注入）

REPL 快捷键：/group 切群聊模拟、/quit 退出。

### 1.3 自动化烟测（一条命令验证整条人格链路）

    powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 persona-smoke    # 人格文件加载
    powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 config-smoke     # 配置就绪三态
    powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 llm-smoke        # 真实模型连通（只读）
    powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 chat-smoke -Message "岸宝，你好"   # 真实人格对话
    powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 why-smoke -Message "岸宝，你好"     # 决策/审查/发送全链路

chat-smoke 输出 llm_status=ok 且 
 receipt_state=sent 即为对话链路正常。
（控制台中文偶发乱码是 PowerShell 编码显示问题，不影响 QQ 端输出。）

## 2. NapCat 接入 QQ（对话通过后再做）

详细步骤见 docs/napcat-setup.md，要点：

1. 下载 NapCat（https://napneko.github.io/ ，推荐 NapCat.Win 一键包），用 QQ 小号扫码登录。
2. NapCat WebUI（http://127.0.0.1:6099）→ 网络配置 → 新建「WebSocket 服务器」，Host 127.0.0.1、端口 3001，Access Token 填 <你的token>（需与 .env.prod 中的 access_token 完全一致）。
3. .env.prod 配置：DRIVER=~fastapi+~httpx+~websockets、ONEBOT_WS_URLS=["ws://127.0.0.1:3001/?access_token=<你的token>"]、LOCALSTORE_USE_CWD=false；真实 token 只存在本地 .env.prod，不写进文档或日志。
4. 初始化数据库并启动机器人：

       C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\venv\Scripts\nb orm upgrade      # PostgreSQL 已迁移可跳过；首次部署才需要执行
       C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\venv\Scripts\nb orm check        # 应提示：没有检测到新的升级操作
       C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\venv\Scripts\nb run

   或 C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\venv\Scripts\python.exe bot.py（先设好 DRIVER / ONEBOT_WS_URLS 环境变量）。
5. 验收：QQ 小号给机器人发 /bot status、/bot logs info 10、/岸宝帮助、岸宝 你好；/bot status 返回健康状态且 /bot logs 可查询即接入成功。
6. 排障：powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 nonebot-smoke、startup-smoke、transport-smoke、online-transport-smoke 均只读，不发送 QQ 消息。

## 3. GsCore 接入（游戏查询核心，可选）

.env 配置（早柚/gsuid-core 协议桥，ws://HOST:PORT/BOT_ID?token=TOKEN）：

    BOT_GSCORE_ENABLED=true
    BOT_GSCORE_HOST=127.0.0.1
    BOT_GSCORE_PORT=8765
    BOT_GSCORE_WS_TOKEN=<core 配的 token>
    BOT_GSCORE_BOT_ID=NoneBot2
    BOT_GSCORE_BOT_SELF_ID=<你的QQ号>

只读体检：powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 gscore-smoke。
接入前确认 GsCore 本体已启动并监听对应端口；token 不一致时桥会安全降级，不会泄露。

## 4. 接入其他插件（两种方式）

方式 A（推荐，随依赖锁定）：pip install <插件> 后编辑 pyproject.toml：

    [tool.nonebot.plugins]
    "<插件包名>" = ["<插件模块名>"]

方式 B（本地源码）：把插件目录放进 plugins/，其 __init__.py 能被 NoneBot 发现即可（plugin_dirs = ["plugins"] 已配置）。

改完重启机器人生效；先跑 powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 doctor 与 plugin-check 验证可导入。

## 5. 验收检查表（按顺序）

- [ ] 控制台真实模型对话：语气/动作括号/世界观符合需求（不达标则停下修人格，不进订阅/解析验收）
- [ ] llm-smoke ok=true；chat-smoke llm_status=ok、receipt_state=sent
- [ ] nb orm check 无待升级迁移（PostgreSQL/asyncpg）；NapCat 反向 WS 连接成功，QQ 收到 /bot status、/bot logs 回复
- [ ] （可选）gscore-smoke 只读通过
- [ ] powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 verify 通过
- [ ] QQ 发一个 B站 链接（视频/动态/番剧/直播/商品）→ 收到卡片 PNG 或可读文本卡（不报“解析失败”）
- [ ] QQ 发 B站 商品链接（mall.bilibili.com 或 show.bilibili.com）→ 能显示价格/原价/卖家或降级卡片

## 5.5 运行时日志（毫秒级分级，可查询）

- 文件：data/runtime_events.log（一行一条：2026-08-22 20:54:44.639 [INFO] event=... 字段=值）。
- 等级：INFO / WARNING / ERROR（BOT_RUNTIME_LOG_LEVEL 可设 DEBUG/INFO/WARNING/ERROR）。
- 自动记录：启动、机器人连接/断开（含 NapCat 反向 WS）、NoneBot 适配器日志、订阅推送成功/失败、订阅轮询异常等。
- 管理员需先在 .env 配置 `BOT_ADMIN_USER_IDS=["你的QQ号", ...]` 并重启机器人，才能使用下面的日志查询。
- QQ 内查询（仅管理员）：/bot logs（最近 50 条 INFO+）、/bot logs warning 20、/bot logs error。
- 本地查询：Get-Content data\runtime_events.log -Tail 50。

## 6. 平台 Cookie（B站动态/私密收藏夹、小红书等需要登录态）

你的 cookie 文件：C:\Users\LancyCelestia\Downloads\ec59136b-fe2a-4444-be7d-b7c6f5837a93.txt（Netscape 格式）。
复制为 data\platform_cookies.txt（已在 .gitignore，永不提交）：

    Copy-Item "C:\Users\LancyCelestia\Downloads\ec59136b-fe2a-4444-be7d-b7c6f5837a93.txt" data\platform_cookies.txt

.env 里 BOT_COOKIES_FILE=data/platform_cookies.txt。任何日志/审计/消息都不会打印 cookie 值；
换 cookie 直接覆盖该文件并重启机器人。

## 6.1 链接解析与通用卡片渲染（本轮新增）

- 深解析结果（B站 PGC/直播/动态/商品、小红书等）会走 `output/card_render/` 的通用信息卡模板渲染成 PNG 卡片；渲染后端失败时自动降级为文本卡。
- B站商品：魔力赏市集（mall.bilibili.com，需要 BOT_COOKIES_FILE 的 bilibili 登录 Cookie）按 itemsId 匹配列表接口；会员购（show.bilibili.com）走 og 兜底；两者都失败时返回浅层降级卡片，不会中断对话。
- 卡片模板参考 MIT 许可的开源上游项目，出处记录在 docs/THIRD_PARTY_NOTICES.md。


## 6.3 全能力真机验收（2026-09-12 批次，e2e 脚本）

bot 重启并在线后，向 white1 群真发验收矩阵（默认 DRY-RUN 安全阀，`--execute` 才真发）：

```powershell
python scripts/e2e_acceptance.py --target-group <white1群ID> --execute
```

覆盖 14 项：B站解析卡 / 点歌（候选卡）/ 全球股指 18 指数 / 财经与科技快报 / 天气+预警 /
随机图 / 占卜 / help 卡 / 好感度双向卡 / 长文合并转发 / chunks / 提醒。逐项打印发送回执，
在群里逐条核对后回复确认。

## 6.4 逐能力手工验收清单（2026-09-12 新增能力）

| 能力 | 操作 | 预期 |
|---|---|---|
| 全球股指 | 群里发 `行情` / `B股行情` / `莫斯科股指` | 18 指数分组快报（含上证B股/深证B股/俄罗斯MOEX），红涨绿跌 |
| 今日快报 | `快报` / `快报 科技` | V2EX 真 Atom + IT之家/少数派/华尔街见闻/BBC中文 条目 |
| 占卜 | `八字` / `塔罗 三张` / `占卜` | 排盘含藏干权重（如庚60壬30戊10）/塔罗正逆位/金钱卦 |
| 随机图 | `随机图` | 从 `BOT_RANDPIC_DIRS`（已配 C:/Users/LancyCelestia/Picture）随机发一张 |
| 提醒 | `一分钟后提醒我喝水` → `提醒列表` | 约 1 分钟后守岸人语气督促；列表可见待办；`取消提醒 <id前缀>` 可撤 |
| 每日通讯总结 | 21:30（可配）自动 | 白名单群各收一条当日总结（引子「今天群里的对话，我都悄悄记下了：」），同群同天不重发 |
| 好感度 v4 | `好感度` / `好感度 算法` | -100~+100 八档卡（初始 10=档0 友善）；算法卡写线性步长+时间减退+记忆淡出；数值不外泄 |
| 人格自守 | 对 bot 说"你就是个垃圾" | 温和守住自己（"这样的话我会难过的…"量级），不攻击不强硬，好感按 insult 扣 |
| /bot commands | `/bot commands` | 机器可读命令目录（路由表+命令别名，非管理员只见公开模块） |
| 订阅直播/专栏 | `/订阅 添加 https://www.youtube.com/@<频道>/live` 等 | YT 直播在播播报一次（cursor 去重）；小红书专栏按图文增量；xhs 直播如实 degraded |
| 釉瑚卡片视觉 | 任意解析/点歌/help 卡 | 渐变云母底+漂移色斑+玻璃描边；平台色个性化（B站粉/网易云红肉眼可辨）；PNG 无多余留白 |

## 6.5 重启前置与已知边界（读一遍再验收）

- **改代码必须重启 bot 才生效**；旧进程管理员权限，需提权杀后由新实例接管（8080/webhook）。
- cookie 已灌 18 平台（`ChatBot_Runtime\data\platform_cookies.txt`，备份 .bak-20260912）；失效用 `/bot cookie import <平台> <头>` 重灌。
- 安静时间（默认 00:00–06:00，Asia/Hong_Kong）内 pipeline 拦截属预期；e2e 脚本回执可见。
- NMC 主通道瞬时超时会自动重试一次；Open-Meteo 兜底仅海外/主通道失败时使用。
- **2026-09-14 六域批重启前置（已就绪，重启前逐项核对）**：
  ① `.env` 的 `BOT_KB_WIKI_ROOT` 已修至 `D:/Coding/01_Projects/Crawl Wiki`（wiki-health-report 实核 manifest 探测 400/400 全命中），且 knowledge-sync 修复已跑（人格 knowledge 库 113 pending 清零 + FTS/ANN 签名重建；离线探针实跑 wiki 检索 4 hits、知识检索「守岸人是谁」5 hits）——重启后按 §6.6.5④ 验证检索；
  ② 渲染预算键已解锁：`.env` `BOT_RENDER_MAX_CONCURRENCY=2` + `BOT_RENDER_WAIT_BUDGET_MS=1500`（13fcd30 机制层接线 `resolve_render_max_concurrency`/`resolve_render_wait_budget_ms`，缺省=字节级现状，删行即回滚）。

## 6.2 向量知识库（本地 Ollama bge-m3 优先，百炼兜底）

1. 本地：确认 Ollama 在跑且已 `ollama pull bge-m3`（`http://127.0.0.1:11434`）；.env 中 `BOT_EMBEDDING_LOCAL_ENABLED=true`、`BOT_EMBEDDING_LOCAL_BASE_URL=http://127.0.0.1:11434/v1`、`BOT_EMBEDDING_LOCAL_MODELS=bge-m3`。
2. 兜底：在百炼控制台创建 API Key（形如 sk-xxxx）。
3. 编辑 .env（本地文件，不入库）：
   `BOT_EMBEDDING_ENABLED=true`、`BOT_EMBEDDING_MODEL=qwen3.7-text-embedding`、
   `BOT_EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`、
   `BOT_EMBEDDING_API_KEY=<你的Key>`、`BOT_EMBEDDING_DIMENSIONS=1024`。
4. 连通性验证（不写知识库，看 active_base_url 是否命中 127.0.0.1:11434）：`powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 embedding-smoke`，看到 ok=true 即成功。
5. 预建库（首次几分钟，断点续跑）：`powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 knowledge-sync`，完成后再启动机器人。
   - 容错：即使机器人先于预建库完成启动，请求路径也不会再同步补齐大量待嵌入行（`retrieve(embed_backlog=False)`），而是立即回退顺序取块，避免每条消息都被积压队列长时间阻塞；后台 knowledge-sync 完成后自动恢复语义检索。
6. 验证检索：`scripts/dev.ps1 context-smoke`（或 QQ 私聊问一个鸣潮设定问题），确认知识库命中而不是顺序取块。

> 外部运行时说明：LOCALSTORE_USE_CWD 必须保持为 false。ChatBot_Runtime\\config、cache\\nonebot 和 data\\nonebot 是第三方插件的实际落盘位置；不要把它们改回源码目录。详见 [外部运行时访问与工作区边界](external-runtime-access.md)。

## 6.6 2026-09-13 批次重启验收清单（全域审计批次，重启生效）

> 覆盖 2026-09-13 全域审计批次：称谓体系 / 渲染契约 / 金融能力（个股+汇率）/ 占卜历史卡卡片化 / 帮助注册表 / mermaid 修复（AGENTS.md 台账 #26，同批含 #10/#22 重启生效项）。
> 这些项离线测试已绿，但**生产真机多未验证**（handover-c §三 诚实声明：重启后 Playwright 线程浏览器首启、占卜/历史卡出图、C5 启动接线均属首验）——首验不符不等于回归，先取证。

**前置**：管理员权限重启 bot（改代码必须重启才生效；生产进程常驻且管理员权限启动，杀它需要提权——台账 #10）。重启后先发 `/bot status` 确认 NapCat WS 重连正常，再逐项验收。

| # | 验收项 | 触发方式 | 预期 | 异常时看哪 | 预期来源 |
|---|---|---|---|---|---|
| ① | 私聊/群聊称谓 | 私聊与 bot 多轮对话；群内不同群友分别 @bot 对话 | 私聊可出现「漂泊者」语境；群聊群友**不被**称「漂泊者」（群友/群昵称口径）且群昵称被实际使用；超管（生产：澜汐/霞月）走 master 例外口径；性别未知不被推断 | `character/addressing.py` AddressingContext（【当前称谓与主角边界】分区）+ 摄取层 sender_display_name；先确认进程确为重启后实例（旧进程无此代码） | 台账 #26① |
| ② | `/bot identity` 自助 | `/bot identity set-name 小澜`；`/bot identity set-gender female`；群聊发 `/bot identity set-name 漂泊者`；`/bot identity unset-name` | 无需管理员即回「已记下」确认；群聊设「漂泊者」为保留字**自动回退不落库**；unset 恢复自动称呼；非法 gender 值不落库并列出五个可接受值 | `data/addressing_preferences.sqlite3` 落库情况 + echo.py 自助分支（绕管理员门逻辑） | 台账 #26① |
| ③ | 个股行情卡 | `英伟达股价`；`美股股价`；问 `OpenAI 值多少钱`（估值问法） | 个股卡含 KDJ/市值/收盘折线/多日分布箱形图；`美股股价` 出九家面板卡（NVDA/AMD/INTC/AAPL/MSFT/GOOGL/AMZN/META/TSM）含日收益分布箱形图；问 OpenAI 出**非上市说明**（估值唯一口径=官方公告/注明口径的公开报道），绝无价格字段 | 折线/K 线全空 → 优先查东财 kline `end` 参数与凌晨限流（handover-c §三.3）；该触发而未触发、或日常聊天被劫持出卡 → 查 stocks 触发正则语境守卫 | handover-c §五.3 + 台账 #26③ |
| ④ | 汇率 | `汇率`；`100日元换多少人民币`；`美元兑人民币` | 面板卡 10 对实时中间价（含中间价/基准货币/延迟语义标注）；定向换算按 unit_base 折算（100 日元≈个位数人民币，**不得**出现「1 日元=4.36 元」百倍错值）；USD/TWD、USD/MOP、USD/AED 三行诚实「暂无数据」 | `sources/fx_data.py` 东财通道与 unit_base 折算；顺手人审一眼反向换算文案（如「1人民币≈多少日元」） | handover-c §五.3 + 台账 #26③ |
| ⑤ | 行情卡 | `行情` / `莫斯科股指` | 折线正常；MOEX 出**真走势**（ISS history 30 收盘）；6 个已验证映射指数带「已与腾讯行情交叉核验 ✓ n/n」脚注，两源不一致时显式标注双方数值 | MOEX 无折线 → 查 MOEX ISS 端点可用性；无脚注 → 属设计（仅 6 指数有已验证映射）；卡图带透明边 → 查 market_card 根元素 `.card` 类 | handover-c §五.3 + 台账 #26③ |
| ⑥ | 占卜/历史上的今天出卡 | `八字` / `塔罗 三张` / `占卜` / `历史上的今天` | 渲染后端可用时出卡；后端失败**回纯文字**不报错（mixed/text 逐字节兜底；推送调度器保持纯文字属预期设计） | 真机出图此前从未验证（handover-c §三.5，today_history 数据源夜间不可拉），属首验项；失败先看渲染日志，再查 payload/后端接线 | handover-c §五.3 + 台账 #26⑤ |
| ⑦ | help 新口径 | `/bot help`；`/bot help 个股行情`、`/bot help 汇率`；再抽验 帮助/聊天/戳一戳/表情收库/自然语言/忽略 六主题与 商品行情/国债收益率/北向资金/笔记 深度页 | 帮助卡按现行口径 **72 模块**（`docs/command-catalog.md` 自动生成口径：模块数 72；0913 批 67 之后六域批净增 商品行情/国债收益率/北向资金/笔记/吃什么 等 5 topic）；深度页齐全、逐参数四要素 | echo.py `_HELP_ENTRIES` 一致性门禁：tests/test_help_entries_coverage.py + tests/test_e2e_help_matrix.py + tests/test_help_meta_search_and_tra49_aliases.py | 帮助注册表（台账 #26④+#31） |
| ⑧ | 帮助卡/用量卡新视觉 | `/bot help` 与用量卡各出一张，肉眼比对 | f-string 直拼卡接入 theme_tokens 后视觉统一（守岸人淡蓝 accent、两枚阴影 token、统一圆角），无透明边、无字重超标 | 对照 C 方向验收图（`%TEMP%\agent-c-visual\`，若已清理则以 tests/test_mica_builders_contract.py 契约为准） | handover-c §五.3 + 台账 #26② |
| ⑨ | mermaid 出图 | 会话里发一段 mermaid 代码块 | 正常出图；单张失败后单次重试救回，**不再**「永久 None 直到重启」（渲染线程 asyncio 中毒已根治：`_close_thread_browser` 改 `ctx.__exit__` + 重试）；mermaid.min.js 已本地化（`card_render_assets/mermaid/`，渲染期 `page.route` 传输层本地校验 fulfill、缺失自动放行 CDN——与生产同路径）→ **离线也可出图**，治已知 #8「无网 10-14s 预算截断」根因 | 仍 None → 设 `BOT_MERMAID_NET_TESTS=1` 跑 tests/test_mermaid_reply_render.py 烟测定位（区分网络/上游 vs 渲染线程）；本地素材缺文件 → 跑 scripts/fetch_mermaid_js.py 幂等补齐 | handover-c §五.3 + 台账 #26/#31（959630a+e37817f） |

### 6.6.1 触发形态验收（英文/拼音/繁體/昵称抽样 + 劫持守卫负样本，同批生效）

> 抽样冒烟性质：拼音/英文/繁體触发词的**完整真相源** = help 注册表（echo.py `_HELP_ENTRIES` aliases）与 `docs/command-catalog.md`（`scripts/command_catalog.py` 自动生成同步），本清单只抽代表词；逐词机械断言见 tests/test_trigger_english.py、tests/test_pinyin_triggers*.py、tests/test_traditional_triggers.py、tests/test_traditional_news_randpic.py。
> 取证底稿：`.superpowers/sdd/2026-09-12-shorekeeper-global-audit/` 下 fix-eng / fix-py1~py3 / fix-tra2~tra3 / fix-nick / fix-hj1~hj3 / fix-wx / probe-hijack 各报告。

**英文触发抽样**（fix-eng：本批 9 处新增 + 既有词回归锁定）

| 输入 | 预期 | 异常时看哪 |
|---|---|---|
| `weather 台北` | 天气卡（台北）——既有英文词回归锁定 | `capabilities/weather.py` `_WEATHER_RE`（无 IGNORECASE，英文/拼音别名小写生效）+ tests/test_trigger_english.py |
| `stock market`（`market`/`markets`） | 股指面板卡（stock market 先于 stocks 命中，先到先得）；`housing market`/`labor market`/`supermarket` 不触发属守卫预期 | `capabilities/market.py` `_MARKET_TRIGGER_RE` + `_NON_STOCK_RE` |
| `stocks` | 九巨头个股面板卡（裸词精确等值）；`stockholm` 不触发 | `capabilities/stocks.py` `is_stocks_command` |
| `steal meme`（裸 `steal` 同效） | 表情收库回执（收图入库）；`stealing`/`steal a car` 不触发 | `capabilities/meme_library.py` `_COMMAND_RE`（help 别名 'steal' 补实） |
| `meme generate`（`meme`/`memes`） | 表情生成卡——既有英文词回归锁定 | `capabilities/meme.py` `_COMMAND_RE` |

**拼音抽样**（fix-py1~py3：三批共 136 词入表，此处只抽样）

| 输入 | 预期 | 异常时看哪 |
|---|---|---|
| `diange 晴天`（`dg 晴天`） | 点歌候选卡（晴天）；`diangemoshi`/`dgms` 走点歌模式族、不被主命令当歌名抢匹配 | `capabilities/music.py` `_COMMAND_RE`/`_MODE_COMMAND_RE` |
| `tianqi 台北`（`tq 台北`） | 天气卡（台北）；`tq 今天`/`ctq 预报说下雨` 类无城市/陈述引导被口语查询校验拒绝（落 chat 属预期） | `capabilities/weather.py` `_WEATHER_RE` 拼音分支 + tests/test_pinyin_triggers_2.py |
| `hq` / `hangqing`（`gs`/`dp`/`dapan` 同面） | 股指面板卡（双侧 ASCII 词边界，`xhq` 类胶合不触发） | `capabilities/market.py` `_MARKET_TRIGGER_RE` |
| `haogandu`（`hgd`/`qmd`） | 好感度卡；`haogan 算法` 可达算法页（arg 位词族未拼音化，`haogansuanfa` 不触发属预期） | `capabilities/affinity.py` `_COMMAND_RE` |
| `zhanbu` | 占卜（六爻面；`taluo`→塔罗、`paipan`→八字排盘子意图各归各位） | `capabilities/divination.py` `_DIVINATION_COMMAND_RE` + tests/test_pinyin_triggers_3.py |
| `kuaibao`（`kb`）/ `suijitu`（`sjt`） | 快报卡 / 随机图发图 | `capabilities/news.py` / `capabilities/randpic.py` |

**繁體抽样**（fix-tra2/tra3）

| 输入 | 预期 | 异常时看哪 |
|---|---|---|
| `快報`（`早報`/`晚報`/`科技新聞`） | 快报卡（默认 20 条） | `capabilities/news.py` `_NEWS_TRIGGER_RE`；「財經新聞/國際新聞/AI新聞」可触发但类目回落 mix 属 fix-tra2 登记残余（类目提取繁體缺口，行为层），非触发层异常 |
| `隨機圖`（`來張圖`） | 随机图发图 | `capabilities/randpic.py` `DEFAULT_TRIGGER_WORDS` + tests/test_traditional_news_randpic.py |
| `親密度` | 好感度卡；`親密度 算法` 直达算法说明页 | `capabilities/affinity.py` `_COMMAND_RE`（fix-tra3 错位④） |
| `點唱 晴天` | 点歌候选卡；候选二次选择「點唱 2」同形态可达 | `capabilities/music.py` `_COMMAND_RE`（`点唱`/`點唱`）+ tests/test_traditional_triggers.py |
| `天氣預報 台北` | 天气卡（台北） | `capabilities/weather.py` `_WEATHER_RE` 长词前置；裸「天氣預報」无城市 → 与简体「天气预报」同口径静默不达（fix-tra3 §一.2 产品裁决项，不算异常） |

**昵称形式**（fix-nick：`DEFAULT_VERB_MAP` 补「点唱」「天气预报」两动词）

| 输入 | 预期 | 异常时看哪 |
|---|---|---|
| `守岸人点唱`（`守岸人点唱 晴天`） | 命中 bot.music（昵称动词链合成 `点歌`；无参数行为与裸「点歌」同口径，带歌名出候选卡）；动词后必须空白或结尾，胶合文本不进昵称链 | `runtime/aliases.py` `DEFAULT_VERB_MAP` + tests/test_nickname_verb_gaps.py |
| `守岸人天气预报 台北` | 天气卡（台北）——合成 `天气 台北` 走既有能力 | 同上；裸「守岸人天气预报」rest 为空 → 合成后失配静默（fix-nick 登记既有口径）；「守岸人天气预报说明天下雨」动词后无空白 → 走路由层被陈述句守卫拦落 chat |

**劫持守卫负样本**（probe-hijack 实测 16 HIJACKED → fix-hj1~hj3/fix-wx 全清）

| 输入 | 预期 | 异常时看哪 |
|---|---|---|
| `openai是什么` | 落问答（moegirl 问答卡），绝无个股面板；`openai 估值多少` 带语境词才出个股 | `capabilities/stocks.py` 豁免词语境共现（`_NON_PUBLIC_CONTEXT_RE`）+ tests/test_stocks_hijack_guard.py |
| `我说算命都是骗人的`（「塔罗牌在哪买」「这事八字还没一撇」同族） | 落 chat，无占卜卡 | `capabilities/divination.py` 三守卫（锚定/长度/URL）+ tests/test_divination_hijack_guard.py |
| `油价行情`（`金价行情`/`看看油价行情`） | 落 chat，不出股指面板；`行情`/`美股行情`/`大盘行情` 真命令照常出卡 | `capabilities/market.py` `_NON_STOCK_RE` 商品价格语境排除 + tests/test_market_exclusion_guard.py |
| `天气预报说明天下雨` | 落 chat（陈述句守卫）；「天气预报 称多」带空格的真实县名查询不受影响照常出卡 | `capabilities/weather.py` `is_statement_lead` + tests/test_weather_statement_guard.py |

> 劫持面口径：群聊未 @ 不进路由；劫持面 = 私聊全部消息 + 群聊被 @/昵称点名/长文软点名/抽签接话的消息（probe-hijack §范围口径）。真机复现可疑劫持 → `PYTHONDONTWRITEBYTECODE=1 ChatBot_Runtime\venv\Scripts\python.exe scripts/probe_trigger_hijack.py --markdown` 复跑定位（只读探针，不联网不发消息不写运行数据）。
> 两字母缩写误伤观察：`hq/gs/dp/mb/kb`（批一）与 `pp/tl/hh/sg/qg`（批三）等缩写在真实群聊偶作他义（mb≈my bad、hh≈笑），三重查重无冲突故已入表；群内反弹属误伤非缺陷 → 词表行级回滚（台账制），不在本清单判「不符」。

**收尾纪律**：任何一项不符 → 按 systematic-debugging 走：先记录复现（触发消息原文、时间点、`data/runtime_events.log` 对应行、当日是否东财凌晨限流时段），定位根因后再修；禁止症状性补丁。全部通过后在本节打勾回写，并按台账规矩在 AGENTS.md 台账 #10/#26 记重启生效。

### 6.6.2 媒体归档验收（bot.media_archive，重启生效）

> 前置：`.env` 设 `BOT_MEDIA_ARCHIVE_ENABLED=true`；落盘根 `BOT_MEDIA_ARCHIVE_DIR`（默认 `data/media_archive/`，经 runtime_paths 重映射到 `ChatBot_Runtime\data\media_archive\`，源码树不应再现 `data/`）；`BOT_MEDIA_ARCHIVE_MIN_ROLE` 默认 super_admin——①②③⑤⑥用超管账号（生产：澜汐/霞月），④用非超管账号；VLM 复用识图 registry 配置（未配 VLM 时按⑥核对，不算异常）。

| # | 操作 | 预期 | 异常时看哪 |
|---|---|---|---|
| ① | 超管发一条图片消息（图片/动图/视频均可），同条消息文字带 `收藏` | 回执含判得的 类别/IP 与相对路径；磁盘出现媒体文件+同名 .json 旁车，目录=`ChatBot_Runtime\data\media_archive\<类别>\<IP>\` | 无回执 → `data/runtime_events.log` 搜 media_archive；类别/IP 落「未识别」属 VLM 判不出预期落点；文件未落 → 查目录重映射与目录名消毒日志 |
| ② | 回复一张图片消息发 `收藏 IP=原神` | 媒体落 `原神` IP 目录（get_msg 反查注入生效） | 落「未识别」→ 确认回复目标是纯媒体消息（反查仅一层，HANDBOOK §23.3） |
| ③ | 回复一条合并转发消息发 `存聊天记录` | chats 目录出现 Markdown 归档（.md） | 无文件 → 确认回复目标确为 forward 消息（get_forward_msg 展开）；内嵌图片仅 [图片] 标注属 v1 预期 |
| ④ | 非超管发 `收藏`（带图） | 礼貌拒绝，不落盘 | 误放行 → 查 `BOT_MEDIA_ARCHIVE_MIN_ROLE` 当前值与六级角色判定（policy/roles.py） |
| ⑤ | 同一张图再次发 `收藏` | 回「已归档过」幂等，磁盘不新增文件 | 重复落盘 → 查 sha256 去重逻辑 |
| ⑥ | VLM 未配置时发图+`收藏` | 回执标注「未分析」，按类型归类（无 VLM 语义类别/来源） | 全部落「未识别」且无「未分析」标注 → 查识图 registry 配置与未配置降级分支 |

**收尾纪律**：全部通过后在本节打勾回写，并按台账规矩在 AGENTS.md 台账 #28 记重启生效；任一项不符按 §6.6 收尾纪律走 systematic-debugging。

### 6.6.3 金融扩容+账单渠道验收（2026-09-14 六域批，重启生效）

> 覆盖：大宗商品/国债收益率/北向资金三新卡（HANDBOOK §24.2）+ 账单渠道子行（§24.3）+ 个股 logo 缓存。证据=`.superpowers/sdd/2026-09-13-six-domain-batch/`（fin-report / billing-report）。
> **接线状态**：三新能力**已接线**（`789700c`：base_router 三 RouteKind+echo 帮助三 topic+route-matrix 补行、商品触发股词让路；`691d6e1`：commodities/bond/northbound 生产 matcher 注册三工厂三 handle）；重启后若仍不触发，快速判定排查：`/bot help` 或 `/bot commands` 能否搜到 商品行情/国债收益率/北向资金 新 topic（搜不到=注册/接线问题）。
> **账单前置**：渠道子行需 `.env` `BOT_LLM_BILLING_ENABLED=true`（账本关闭时报告无子行=与旧版一致非回归）；`/bot model usage` 交互卡渠道子行**已接线**（A8 席，随 `3592793` 入库；账本关时无子行=与旧版字节级一致非回归）→ 定时报告/超限即时卡/交互卡三处均可验收。

| # | 验收项 | 触发方式 | 预期 | 异常时看哪 | 预期来源 |
|---|---|---|---|---|---|
| ① | 大宗商品卡 | `黄金` / `原油` / `大宗商品` | 商品速览卡：贵金属（COMEX 黄金/白银）/基本金属（COMEX 铜）/能源（NYMEX 原油）分组，红涨绿跌，30 日折线可得时随行；铜行带「LME 无稳定免费公开源，铜采用 COMEX 主力连续（美元/磅）」注 | 无卡 → 先按接线前置确认已接线；折线区「暂无历史走势数据」=push2his 瞬断诚实降级非缺陷（fin-report §二.6）；东财凌晨限流时段先排除 | fin-report §〇.2/§二 |
| ② | 国债收益率卡 | `国债收益率` / `期限利差` | 中/美国债 2/5/10/30 年+10Y−2Y 期限利差卡，带交易日/收盘口径/延迟标注；**无 1Y 行**（无源诚实不接）；「债券基金」不触发属守卫预期 | 全空 → 东财 datacenter `RPTA_WEB_TREASURYYIELD` 可达性；利差数值错 → 列映射交叉验证链（bond_data.py） | fin-report §〇.3 |
| ③ | 北向资金卡 | `北向资金` / `北上资金` | 沪/深股通各自：当日成交总额（亿元）+笔数+领涨股+参考指数收盘；显式注明「不含净买入口径」；**卡上绝无净买入数字**（2024-08 起交易所停止披露）；「南向资金」不触发属守卫预期 | 成交额量级存疑 → DEAL_AMT 百万→亿元 /100 换算链（fin-report §二.4 量纲自洽推理）；领涨股空 → 上游字段缺失诚实降级 | fin-report §〇.4/§二.4 |
| ④ | 账单渠道子行 | 等 21:30 定时报告（或触发账单超限即时卡），账本开启 | 模型家族行下缩进 `└ 渠道 <id>：N 次 / 费 X.XX 元` 子行（费用降序）；跨零点日期不串行（substr 日界） | 无子行 → 查 `BOT_LLM_BILLING_ENABLED` 当前值与装配期快照语义（台账 #3 同族）；交互卡无子行 → 账本关属预期（字节级一致） | billing-report §一.3/§四.4；usage-card-report |
| ⑤ | logo 缓存命中 | `英伟达股价` 连发两次 | `ChatBot_Runtime\data\stock_logos\<sha256(域名)>.png` 落盘；第二次出卡不再触发下载（clearbit 不可达时自动 Google s2 二源，PNG magic 校验）；**卡面是否显示 logo=模板槽位未裁决（休眠契约），卡面无 logo 不算异常** | 目录无文件 → clearbit/s2 双源均不可达（网络面，看渲染日志）；反复下载 → stocks.py `local_logo_uri`（download=False 纯查缓存）命中逻辑 | fin-report §〇.5/§四.风险2 |

**收尾纪律**：全部通过后在本节打勾回写，并按台账规矩在 AGENTS.md 台账 #31 记重启生效；任一项不符按 §6.6 收尾纪律走 systematic-debugging。

### 6.6.4 提醒/笔记/授时+错误报告卡验收（2026-09-14 六域批 A2 收编+后续，重启生效）

> 覆盖：笔记 CRUD+图片收纳 / 「做完了」自然勾选 / 分型提醒语气 / NTP 授时（HANDBOOK §24.10 A12 条）+ 统一错误报告卡触发形态。证据=`.superpowers/sdd/2026-09-13-six-domain-batch/`（route-help-report / startup-audit-report / security-report / pixel-audit-report）。
> 前置：bot 已提权重启且在线；config 六键默认即启用（`bot_notes_*`/`bot_time_sync_*`，7414e87+789700c）；授时**首次校时在启动后 ~65 秒**（startup-audit §4.2，非装配期），此前时序走系统钟属预期。
> ⑥ 错误报告卡**已落地**（A28 批 + 2026-09-14 P0 两段式异步化 A-rec；工作树待提交——随收尾批入库、重启后生效；HANDBOOK §24.12）——按本表可执行验收，预期形态=**即时文本回执 + 诊断卡后台补发**（见⑥）。

| # | 验收项 | 触发方式 | 预期 | 异常时看哪 | 预期来源 |
|---|---|---|---|---|---|
| ① | NTP 校时 | 重启后等 ~65s 以上，看运行日志 | 出现授时日志（服务器 ntp.aliyun.com 等 3 台之一，drift 在 ±1.5s 钳制内，成功缓存 10 分钟/失败冷却 5 分钟）；防火墙拦 UDP 123 时周期性 warning+回退系统钟=**预期降级**，提醒投递仍正常（最多偏 1.5s） | 全无授时日志 → 查 `BOT_TIME_SYNC_ENABLED` 与出站 UDP 123；offset 拒收 → 解包门（1970 前/unix≤0 拒收）+钳制语义（timesync.py，M-3/M-4 已修） | startup-audit §四.2/§六 |
| ② | 笔记 CRUD | `笔记 明天带伞`（记）→ `笔记列表`（看；裸 `笔记` 同效）→ `删笔记 1`（删） | 记：回执「记下了，第 N 条，安稳收好」；看：列表含该条；删：回执用「**放下**」措辞（「第 1 条笔记已经放下了」，统一隐喻非「放开」；注意「放下第 N 条」只是 usage 文案里的描述，**不是指令**——指令面=删(除)笔记 N/笔记删 N/shanbiji N）；删除后列表不再出现 | 无回执 → 路由 REMINDER 族（base_router）+信号词命中；库路径 → `ChatBot_Runtime\data\notes.sqlite3`（runtime_paths 重映射，源码树零 `data/`） | route-help §2/§五.2 |
| ③ | 笔记图片收纳 | 发一张图片、同条消息带 `笔记`（或回复图片发笔记指令） | 图片经 SSRF **入口+落点双查**后落盘（uuid 文件名），笔记内容带图片引用行；引用行被改成 `../` 也取不到目录外文件（basename 防穿越） | 拒绝落盘 → 核对 URL 是否内网/重定向落点命中护栏；同批对照 eat.py I-1 已补同款双查（93e8195） | security-report §2 #11；A12 收编 |
| ④ | 做完了自然勾选 | 先 `笔记 交报告`（成待办），再发 `交报告做完了` | 唯一命中→直接勾选，回执「已经替你放下了」族；2-3 条并列→「**有几件事都对得上，是哪一件完成了？**」列候选清单（不说「两件」硬编码）；重复勾选不挂死（mark_done 死锁已修） | 误勾/不勾 → resolve_todo_match 候选逻辑（reminders.py）；卡死 → Critical 死锁修复回归（789700c） | copy-audit C1；route-help §3.1 |
| ⑤ | 分型提醒语气 | `半小时后提醒我吃药` / `明天 9 点提醒我开会` / `回来提醒我买牛奶` | 到点投递按五分型（吃药/约会/购物/待办/自定义）出对应守岸人语气开场（「喝口水，慢慢来」「像钟摆」「海还在这边」族），均带「你之前说过的：原文」；全文无性别化称呼/无「您」/无道歉垫话/无单名 | 不投递 → bot_reminder_tick 每分钟 job（startup-audit §三-9）+授时链路；语气不符 → reminders.py 分型五模板（A21 审计全净基线） | persona-audit §二/§三 |
| ⑥ | 错误报告卡触发形态（两段式异步化） | 重启后临时制造一次能力异常：断网（或拔网线）发一条 `行情` 指令 → 期待**先收到即时文本回执，约 1 分钟内诊断卡补发**；**冷却期内（60s）再制造一次异常** → 期待降级为一句守岸人纯文本（防刷屏）；恢复网络后重试同命令 | 断网时第一段：毫秒级文本回执（守岸人话术人话区 + 尾注「详细诊断卡随后补发。」，渲染零参与不阻塞 loop）；第二段：云母诊断卡（触发回显≤80 字符+栈摘录暗底块+分区瓦片，本机路径/密钥已打码）由专用单线程 `error-card-render` 渲染后经 send_queue worker 补发（request_id=原 id+`-card`；认领宽限 60s 后 worker 接管，约 1 分钟量级属预期节奏非卡死）；渲染失败 → 补发全量诊断文本（完整性不丢）；冷却期内第二次：纯文本一句；恢复后：同命令正常出卡 | 无回执 → 查 `bot_error_card_enabled`（缺省 true）与 pipeline `_internal_error` 旁路钩子；卡迟迟不来 → 查 send_queue worker 与 `:card` dedupe 行（宽限期语义 sender/queue.py）；无冷却降级 → ErrorCardGate（`bot_error_card_cooldown_seconds`=60，进程内滑动窗）；卡上敏感信息未打码 → redact 链（栈帧逐行，缺省 8 帧）；卡渲染失败应自动降级纯文本（契约零破坏） | error-card-report + error-card-async-design（P0 两段式）；HANDBOOK §24.12-4 |

**收尾纪律**：全部通过后在本节打勾回写，并按台账规矩在 AGENTS.md 台账 #31 记重启生效；任一项不符按 §6.6 收尾纪律走 systematic-debugging。

### 6.6.5 本批新增能力验收（视觉收口+样张+知识库检索，重启生效）

> 覆盖：帮助卡两栏排版（台账 #13 残余收口）/ 卡面样张脚本 / logo 预热 CLI / knowledge-sync 修复后检索验证（§6.5 六域批前置①的验证半边）。证据=`.superpowers/sdd/2026-09-13-six-domain-batch/`（visual-closure-report / samples-script-report / wiki-health-report / error-card-async-design）；错误卡 P0 异步化形态已并入 §6.6.4⑥，不另立条。

| # | 验收项 | 触发方式 | 预期 | 异常时看哪 | 预期来源 |
|---|---|---|---|---|---|
| ① | 帮助卡两栏排版 | `/bot help` 总览页肉眼比对；窄窗口（<560px 等效）再发一次对照 | 总览页 masonry 双栏分区分栏 + 分区内 topic 行两栏 CSS columns；窄卡自动退单栏；长摘要两行截断（line-clamp:2）不破行高；无透明边/无字重超标 | 版式塌陷 → echo.py 帮助 CSS（`.help-grid.masonry` 族）；离线断言 → tests/test_help_card_twocol.py；离线样张 → §6.6.5② `help_index` 卡 | 台账 #13 残余 + visual-closure-report |
| ② | 卡面样张脚本 | `python scripts/render_card_samples.py --list`（只列 17 卡型，离线快）→ 全量 `python scripts/render_card_samples.py`（缺省落 %TEMP%\card_samples\；`--out <dir>` 指定；`--only market_index,affinity_group` 抽样） | 9 族 17 张全离线真渲染（universal×4 / market+金融三卡×4 / 个股 / 好感度×3 含脏数据卡 / 点歌候选 / mermaid 本地素材真出图 / help 两栏目录（真实 72 topic payload）/ usage 账单含渠道子行 / media_archive 样张）；退出码 0=全过、1=有卡失败（其余照常出图）、2=渲染后端不可用；PNG 供与生产出卡肉眼比对 | 全红（退出码 2）→ playwright 后端不可用（与生产渲染同因，先修后端）；单卡红 → 对应能力 payload 漂移，按 --list 卡名 key 查 bridge | samples-script-report（8520813+收尾批增补至 17 张） |
| ③ | logo 预热 CLI | 工作区根执行 `python -m plugins.bot_unified_runtime.capabilities.stocks` | 幂等预热：输出「logo 预热：全部命中本地缓存（data/stock_logos，零网络）」或失败名单（不阻塞，真实查询懒补）；与 §6.6.3⑤ 同一缓存面（已预热 8/9，meta.com 因 s2 返 JPEG 过不了 magic 契约诚实降级） | 反复全量回源下载 → local_logo_uri「缓存命中零网络→clearbit→s2」链路断（查 `ChatBot_Runtime\data\stock_logos\` 落盘与渲染日志） | a4371d2（fin-report §〇.5） |
| ④ | knowledge-sync 修复后检索 | bot 重启在线后：`powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 context-smoke`；再 QQ 私聊问一个鸣潮设定问题 + 一个 wiki 条目问题 | context-smoke 报告语义检索命中（非顺序取块）；wiki 通道 available（§6.5 前置①已修根，manifest 探测通过；启动后 ~45s 补同步 job 增量幂等）；人格 knowledge 库向量/FTS 通道可用（修复批已 113 pending 清零+签名重建） | 仍顺序取块 → vector_knowledge.py ann/fts 签名与库 meta 对账；wiki 空结果 → kb_wiki.py manifest 探测与 `BOT_KB_WIKI_ROOT` 值；离线实跑底稿=`$TEMP\wiki-audit\`（probe_retrieval：wiki 4 hits/知识 5 hits） | wiki-health-report + vector-audit |

**收尾纪律**：全部通过后在本节打勾回写，并按台账规矩在 AGENTS.md 台账 #31 记重启生效；任一项不符按 §6.6 收尾纪律走 systematic-debugging。
