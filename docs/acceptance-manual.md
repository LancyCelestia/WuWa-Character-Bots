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
| ⑦ | help 新口径 | `/bot help`；`/bot help 个股行情`、`/bot help 汇率`；再抽验 帮助/聊天/戳一戳/表情收库/自然语言/忽略 六个新主题深度页 | 帮助卡按新口径 **67 模块**；8 个新主题（帮助/聊天/戳一戳/表情收库/自然语言/忽略/个股行情/汇率）深度页齐全、逐参数四要素 | echo.py `_HELP_ENTRIES` 与帮助注册表一致性门禁（tests/test_help_registry*） | 帮助注册表（台账 #26④） |
| ⑧ | 帮助卡/用量卡新视觉 | `/bot help` 与用量卡各出一张，肉眼比对 | f-string 直拼卡接入 theme_tokens 后视觉统一（守岸人淡蓝 accent、两枚阴影 token、统一圆角），无透明边、无字重超标 | 对照 C 方向验收图（`%TEMP%\agent-c-visual\`，若已清理则以 tests/test_mica_builders_contract.py 契约为准） | handover-c §五.3 + 台账 #26② |
| ⑨ | mermaid 出图 | 会话里发一段 mermaid 代码块 | 正常出图；单张失败后单次重试救回，**不再**「永久 None 直到重启」（渲染线程 asyncio 中毒已根治：`_close_thread_browser` 改 `ctx.__exit__` + 重试） | 仍 None → 设 `BOT_MERMAID_NET_TESTS=1` 跑 tests/test_mermaid_reply_render.py 烟测定位（区分网络/上游 vs 渲染线程） | handover-c §五.3 + 台账 #26（mermaid 待重启观察） |

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
