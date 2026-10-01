# 验收与接入手册（Acceptance Manual）
> **术语说明（2026-09-20）**：本文中的 **NapCat** 指 2026-09-18 之前的 QQ 协议端（当时实况记录，保留原文不改写）；现役协议端为 **SnowLuma**，见 [snowluma-setup.md](snowluma-setup.md)。
> **环境坐标约定（2026-09-22）**：`<仓库根>`＝本仓检出目录；`<你的下载目录>`＝系统下载目录；`$DEV_ROOT`＝本机第三方软件安装根目录（SnowLuma / GPT-SoVITS / QQNT 等）；`$TEMP`＝系统临时目录；`..\ChatBot_Runtime`＝仓库根的兄弟目录（运行数据根）。以上为读者本机环境坐标，命令请按本机实际值替换，本文不再写死绝对路径。

目标：先让你把「对话/人格」跑起来并确认符合需求，再接 SnowLuma、GsCore 与其他插件。
全程在本机完成，不碰第三方框架账号。任何命令都从项目根目录执行：

    cd <仓库根>

## 0. 一次装好依赖

    ..\ChatBot_Runtime\venv\Scripts\python.exe -m pip install -e . nb-cli
    powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 doctor
    ..\ChatBot_Runtime\venv\Scripts\nb orm upgrade      # 首次运行前初始化 SQLite 数据库
    ..\ChatBot_Runtime\venv\Scripts\nb orm check        # 应提示：没有检测到新的升级操作

## 1. 对话 / 人格测试（第一步，必须先通过）

### 1.1 离线控制台（不需要联网，验证人格链路）

    powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 console          # 交互 REPL
    ..\ChatBot_Runtime\venv\Scripts\python.exe -m plugins.bot_unified_runtime.console_chat --message "岸宝，你好"

离线模式用的是 static 占位回复，只能验证链路，不能验证人格文案。

### 1.2 真实模型控制台（验证人格是否符合你的需求）

    ..\ChatBot_Runtime\venv\Scripts\python.exe -m plugins.bot_unified_runtime.console_chat --provider openai_compatible --model deepseek-v4-flash --base-url https://api.deepseek.com/v1 --api-key <你的key>

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

## 2. SnowLuma 接入 QQ（对话通过后再做）

详细步骤见 docs/snowluma-setup.md（旧协议端 NapCat 的说明已降级为回滚路径，见
docs/napcat-setup.md，新接入不要再照它操作），要点：

1. 启动协议端：双击 `$DEV_ROOT\SnowLuma\launcher.bat`（内部 `node ./index.mjs`，自带 node.exe），
   WebUI 起在 http://127.0.0.1:5099 ，用普通快捷方式启动 QQ 小号并登录。
2. SnowLuma 是**运行期手动注入**：WebUI「进程注入」页找到该 QQ 主进程（状态「可加载」）点
   「加载」，等状态走到「已在线」；默认 `hookAutoLoad=false`，不会自动注入，QQ 每次重启都要重点一次。
3. 「节点配置」页给该号建 WebSocket 服务器：Host 127.0.0.1、端口 3001、消息格式 array、
   **上报自身消息=开**、Access Token 填 <你的token>（需与 .env.prod 中的 access_token 完全一致；
   SnowLuma 强制令牌长度 ≥16 且 zxcvbn 评分 ≥3，不满足会拒绝保存）。多号同挂一个实例时，
   每个号的端口必须错开（学校号用 3002），否则新号自动生成的默认节点会与主号抢 3000/3001 而 EADDRINUSE。
4. .env.prod 配置：DRIVER=~fastapi+~httpx+~websockets、ONEBOT_WS_URLS=["ws://127.0.0.1:3001/?access_token=<你的token>"]、LOCALSTORE_USE_CWD=false；真实 token 只存在本地 .env.prod，不写进文档或日志。
5. 初始化数据库并启动机器人：

       ..\ChatBot_Runtime\venv\Scripts\nb orm upgrade      # PostgreSQL 已迁移可跳过；首次部署才需要执行
       ..\ChatBot_Runtime\venv\Scripts\nb orm check        # 应提示：没有检测到新的升级操作
       ..\ChatBot_Runtime\venv\Scripts\nb run

   或 ..\ChatBot_Runtime\venv\Scripts\python.exe bot.py（先设好 DRIVER / ONEBOT_WS_URLS 环境变量）。
6. 验收：QQ 小号给机器人发 /bot status、/bot logs info 10、/岸宝帮助、岸宝 你好；/bot status 返回健康状态且 /bot logs 可查询即接入成功。
7. 排障：powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 nonebot-smoke、startup-smoke、transport-smoke、online-transport-smoke 均只读，不发送 QQ 消息。

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
- [ ] nb orm check 无待升级迁移（PostgreSQL/asyncpg）；SnowLuma 正向 WS（3001）连接成功，QQ 收到 /bot status、/bot logs 回复
- [ ] （可选）gscore-smoke 只读通过
- [ ] powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 verify 通过
- [ ] QQ 发一个 B站 链接（视频/动态/番剧/直播/商品）→ 收到卡片 PNG 或可读文本卡（不报“解析失败”）
- [ ] QQ 发 B站 商品链接（mall.bilibili.com 或 show.bilibili.com）→ 能显示价格/原价/卖家或降级卡片

## 5.5 运行时日志（毫秒级分级，可查询）

- 文件：data/runtime_events.log（一行一条：2026-08-22 20:54:44.639 [INFO] event=... 字段=值）。
- 等级：INFO / WARNING / ERROR（BOT_RUNTIME_LOG_LEVEL 可设 DEBUG/INFO/WARNING/ERROR）。
- 自动记录：启动、机器人连接/断开（含 SnowLuma 正向 WS）、NoneBot 适配器日志、订阅推送成功/失败、订阅轮询异常等。
- 管理员需先在 .env 配置 `BOT_ADMIN_USER_IDS=["你的QQ号", ...]` 并重启机器人，才能使用下面的日志查询。
- QQ 内查询（仅管理员）：/bot logs（默认条数以命令真身为准）、/bot logs warning 20、/bot logs error。
- 本地查询：Get-Content data\runtime_events.log -Tail 50。

## 6. 平台 Cookie（B站动态/私密收藏夹、小红书等需要登录态）

你的 cookie 文件：<你的下载目录>\ec59136b-fe2a-4444-be7d-b7c6f5837a93.txt（Netscape 格式）。
复制为 data\platform_cookies.txt（已在 .gitignore，永不提交）：

    Copy-Item "<你的下载目录>\ec59136b-fe2a-4444-be7d-b7c6f5837a93.txt" data\platform_cookies.txt

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

覆盖项数以 `scripts/e2e_acceptance.py` 矩阵实况为准：文本三态（直发/长文合并
转发/chunks）/ B站解析卡 / 点歌候选卡 / 全球股指 18 指数 / 财经+科技快报 / 天气+预警 / 随机图 /
占卜（塔罗+金钱卦二态）/ help 卡 / 好感度卡 / 提醒查询 / 个股卡+非上市守卫 / 汇率面板+定向换算 /
称谓自助 / 多语言触发形态抽样（拼音/英文/繁體）/ 劫持守卫负样本。逐项打印发送回执，
在群里逐条核对后回复确认。

## 6.4 逐能力手工验收清单（2026-09-12 新增能力）

| 能力 | 操作 | 预期 |
|---|---|---|
| 全球股指 | 群里发 `行情` / `B股行情` / `莫斯科股指` | 18 指数分组快报（含上证B股/深证B股/俄罗斯MOEX），红涨绿跌 |
| 今日快报 | `快报` / `快报 科技` | V2EX 真 Atom + IT之家/少数派/华尔街见闻/BBC中文 条目 |
| 占卜 | `八字` / `塔罗 三张` / `占卜` | 排盘含藏干权重（如庚60壬30戊10）/塔罗正逆位/金钱卦 |
| 随机图 | `随机图` | 从 `BOT_RANDPIC_DIRS`（已配本机图片目录，`.env` `BOT_RANDPIC_DIRS` 现值为准）随机发一张 |
| 提醒 | `一分钟后提醒我喝水` → `提醒列表` | 约 1 分钟后守岸人语气督促；列表可见待办；`取消提醒 <id前缀>` 可撤 |
| 每日通讯总结 | 21:30（可配）自动 | 白名单群各收一条当日总结（引子「今天群里的对话，我都悄悄记下了：」），同群同天不重发 |
| 好感度 v5 | `好感度` / `好感度 算法` | -100~+100 八档卡（初始 10=档0 友善）；算法卡定性说明 v5 多因素线性步长+惰性回归+印象淡出（不展示固定加减数值）；数值不外泄 |
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
  ① `.env` 的 `BOT_KB_WIKI_ROOT` 已修至 `本机 wiki 爬取目录（`.env` `BOT_KB_WIKI_ROOT` 现值为准）`（wiki-health-report 实核 manifest 探测 400/400 全命中），且 knowledge-sync 修复已跑（人格 knowledge 库 113 pending 清零 + FTS/ANN 签名重建；离线探针实跑 wiki 检索 4 hits、知识检索「守岸人是谁」5 hits）——重启后按 §6.6.5④ 验证检索；
  ② 渲染预算键已解锁：`.env` `BOT_RENDER_MAX_CONCURRENCY=2` + `BOT_RENDER_WAIT_BUDGET_MS=1500`（13fcd30 机制层接线 `resolve_render_max_concurrency`/`resolve_render_wait_budget_ms`，缺省=字节级现状，删行即回滚）。
  ③ **重启前一键预检（A56，051261d 已入库）**：工作区根跑 `python scripts/pre_restart_check.py`（venv python 等价；`--json` 结构化输出）——检查项以脚本现跑输出为准（env 路径/人格锚定/哈希台账/事实册/KB 漂移/静态门/协议端探针）**无 FAIL（EXIT=0）再动手重启**；napcat 项（id 沿用，实体是 SnowLuma；探测端点取自 `.env` 的 `ONEBOT_WS_URLS`，两号即 3001+3002 逐个探，只取 host:port 不落令牌）未启动=SKIP 不阻断（bot 自带重连），kb_drift 首跑拷库到 $TEMP 需数秒～数十秒属预期非卡死；FAIL 项消息自带修复指引，先修后复跑至全绿。

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

> 外部运行时说明：LOCALSTORE_USE_CWD 必须保持为 false。ChatBot_Runtime\config、cache\nonebot 和 data\nonebot 是第三方插件的实际落盘位置；不要把它们改回源码目录。详见 [外部运行时访问与工作区边界](external-runtime-access.md)。

## 6.6 2026-09-13 批次重启验收清单（全域审计批次，重启生效）

> 覆盖 2026-09-13 全域审计批次：称谓体系 / 渲染契约 / 金融能力（个股+汇率）/ 占卜历史卡卡片化 / 帮助注册表 / mermaid 修复（AGENTS.md 台账 #26，同批含 #10/#22 重启生效项）。
> 这些项离线测试已绿，但**生产真机多未验证**（handover-c §三 诚实声明：重启后 Playwright 线程浏览器首启、占卜/历史卡出图、C5 启动接线均属首验）——首验不符不等于回归，先取证。

**前置**：管理员权限重启 bot（改代码必须重启才生效；生产进程常驻且管理员权限启动，杀它需要提权——台账 #10）。重启后先发 `/bot status` 确认 SnowLuma WS 重连正常，再逐项验收。

| # | 验收项 | 触发方式 | 预期 | 异常时看哪 | 预期来源 |
|---|---|---|---|---|---|
| ① | 私聊/群聊称谓 | 私聊与 bot 多轮对话；群内不同群友分别 @bot 对话 | 私聊可出现「漂泊者」语境；群聊群友**不被**称「漂泊者」（群友/群昵称口径）且群昵称被实际使用；超管（生产：澜汐/霞月）走 master 例外口径；性别未知不被推断 | `domains/chat_reply/character/addressing.py` AddressingContext（【当前称谓与主角边界】分区）+ 摄取层 sender_display_name；先确认进程确为重启后实例（旧进程无此代码） | 台账 #26① |
| ② | `/bot identity` 自助 | `/bot identity set-name 小澜`；`/bot identity set-gender female`；群聊发 `/bot identity set-name 漂泊者`；`/bot identity unset-name` | 无需管理员即回「已记下」确认；群聊设「漂泊者」为保留字**自动回退不落库**；unset 恢复自动称呼；非法 gender 值不落库并列出五个可接受值 | `data/addressing_preferences.sqlite3` 落库情况 + echo.py 自助分支（绕管理员门逻辑） | 台账 #26① |
| ③ | 个股行情卡 | `英伟达股价`；`美股股价`；问 `OpenAI 值多少钱`（估值问法） | 个股卡含 KDJ/市值/收盘折线/多日分布箱形图；`美股股价` 出九家面板卡（NVDA/AMD/INTC/AAPL/MSFT/GOOGL/AMZN/META/TSM）含日收益分布箱形图；问 OpenAI 出**非上市说明**（估值唯一口径=官方公告/注明口径的公开报道），绝无价格字段 | 折线/K 线全空 → 优先查东财 kline `end` 参数与凌晨限流（handover-c §三.3）；该触发而未触发、或日常聊天被劫持出卡 → 查 stocks 触发正则语境守卫 | handover-c §五.3 + 台账 #26③ |
| ④ | 汇率 | `汇率`；`100日元换多少人民币`；`美元兑人民币` | 面板卡 10 对实时中间价（含中间价/基准货币/延迟语义标注）；定向换算按 unit_base 折算（100 日元≈个位数人民币，**不得**出现「1 日元=4.36 元」百倍错值）；USD/TWD、USD/MOP、USD/AED 三行诚实「暂无数据」 | `domains/finance/data/fx_data.py` 东财通道与 unit_base 折算；顺手人审一眼反向换算文案（如「1人民币≈多少日元」） | handover-c §五.3 + 台账 #26③ |
| ⑤ | 行情卡 | `行情` / `莫斯科股指` | 折线正常；MOEX 出**真走势**（ISS history 30 收盘）；6 个已验证映射指数带「已与腾讯行情交叉核验 ✓ n/n」脚注，两源不一致时显式标注双方数值 | MOEX 无折线 → 查 MOEX ISS 端点可用性；无脚注 → 属设计（仅 6 指数有已验证映射）；卡图带透明边 → 查 market_card 根元素 `.card` 类 | handover-c §五.3 + 台账 #26③ |
| ⑥ | 占卜/历史上的今天出卡 | `八字` / `塔罗 三张` / `占卜` / `历史上的今天` | 渲染后端可用时出卡；后端失败**回纯文字**不报错（mixed/text 逐字节兜底；推送调度器保持纯文字属预期设计） | 真机出图此前从未验证（handover-c §三.5，today_history 数据源夜间不可拉），属首验项；失败先看渲染日志，再查 payload/后端接线 | handover-c §五.3 + 台账 #26⑤ |
| ⑦ | help 新口径 | `/bot help`；`/bot help 个股行情`、`/bot help 汇率`；再抽验 帮助/聊天/戳一戳/表情收库/自然语言/忽略 等主题与 商品行情/国债收益率/北向资金/笔记 深度页 | 帮助卡按现行口径 **74 模块**（以 `docs/command-catalog.md` 自动生成口径与 `docs/auto-facts.md` 机器册「帮助 topic 数」为准，当前 74；0913 批 67 后随六域批及群上下文等后续批次递增，不手写固定派生）；深度页齐全、逐参数四要素 | echo.py `_HELP_ENTRIES` 一致性门禁：tests/test_help_entries_coverage.py + tests/test_e2e_help_matrix.py + tests/test_help_meta_search_and_tra49_aliases.py | 帮助注册表（台账 #26④+#31） |
| ⑧ | 帮助卡/用量卡新视觉 | `/bot help` 与用量卡各出一张，肉眼比对 | f-string 直拼卡接入 theme_tokens 后视觉统一（守岸人淡蓝 accent、两枚阴影 token、统一圆角），无透明边、无字重超标 | 对照 C 方向验收图（`$TEMP\agent-c-visual\`，若已清理则以 tests/test_mica_builders_contract.py 契约为准） | handover-c §五.3 + 台账 #26② |
| ⑨ | mermaid 出图 | 会话里发一段 mermaid 代码块 | 正常出图；单张失败后单次重试救回，**不再**「永久 None 直到重启」（渲染线程 asyncio 中毒已根治：`_close_thread_browser` 改 `ctx.__exit__` + 重试）；mermaid.min.js 已本地化（`card_render_assets/mermaid/`，渲染期 `page.route` 传输层本地校验 fulfill、缺失自动放行 CDN——与生产同路径）→ **离线也可出图**，治已知 #8「无网 10-14s 预算截断」根因 | 仍 None → 设 `BOT_MERMAID_NET_TESTS=1` 跑 tests/test_mermaid_reply_render.py 烟测定位（区分网络/上游 vs 渲染线程）；本地素材缺文件 → 跑 scripts/fetch_mermaid_js.py 幂等补齐 | handover-c §五.3 + 台账 #26/#31（959630a+e37817f） |

### 6.6.1 触发形态验收（英文/拼音/繁體/昵称抽样 + 劫持守卫负样本，同批生效）

> 抽样冒烟性质：拼音/英文/繁體触发词的**完整真相源** = help 注册表（echo.py `_HELP_ENTRIES` aliases）与 `docs/command-catalog.md`（`scripts/command_catalog.py` 自动生成同步），本清单只抽代表词；逐词机械断言见 tests/test_trigger_english.py、tests/test_pinyin_triggers*.py、tests/test_traditional_triggers.py、tests/test_traditional_news_randpic.py。
> 取证底稿：`.superpowers/sdd/2026-09-12-shorekeeper-global-audit/` 下 fix-eng / fix-py1~py3 / fix-tra2~tra3 / fix-nick / fix-hj1~hj3 / fix-wx / probe-hijack 各报告。

**英文触发抽样**（fix-eng：本批 9 处新增 + 既有词回归锁定）

| 输入 | 预期 | 异常时看哪 |
|---|---|---|
| `weather 台北` | 天气卡（台北）——既有英文词回归锁定 | `domains/weather/capabilities/weather.py` `_WEATHER_RE`（无 IGNORECASE，英文/拼音别名小写生效）+ tests/test_trigger_english.py |
| `stock market`（`market`/`markets`） | 股指面板卡（stock market 先于 stocks 命中，先到先得）；`housing market`/`labor market`/`supermarket` 不触发属守卫预期 | `domains/finance/capabilities/market.py` `_MARKET_TRIGGER_RE` + `_NON_STOCK_RE` |
| `stocks` | 九巨头个股面板卡（裸词精确等值）；`stockholm` 不触发 | `domains/finance/capabilities/stocks.py` `is_stocks_command` |
| `steal meme`（裸 `steal` 同效） | 表情收库回执（收图入库）；`stealing`/`steal a car` 不触发 | `domains/meme/capabilities/meme_library.py` `_COMMAND_RE`（help 别名 'steal' 补实） |
| `meme generate`（`meme`/`memes`） | 表情生成卡——既有英文词回归锁定 | `domains/meme/capabilities/meme.py` `_COMMAND_RE` |

**拼音抽样**（fix-py1~py3：三批共 136 词入表，此处只抽样）

| 输入 | 预期 | 异常时看哪 |
|---|---|---|
| `diange 晴天`（`dg 晴天`） | 点歌候选卡（晴天）；`diangemoshi`/`dgms` 走点歌模式族、不被主命令当歌名抢匹配 | `domains/music/capabilities/music.py` `_COMMAND_RE`/`_MODE_COMMAND_RE` |
| `tianqi 台北`（`tq 台北`） | 天气卡（台北）；`tq 今天`/`ctq 预报说下雨` 类无城市/陈述引导被口语查询校验拒绝（落 chat 属预期） | `domains/weather/capabilities/weather.py` `_WEATHER_RE` 拼音分支 + tests/test_pinyin_triggers_2.py |
| `hq` / `hangqing`（`gs`/`dp`/`dapan` 同面） | 股指面板卡（双侧 ASCII 词边界，`xhq` 类胶合不触发） | `domains/finance/capabilities/market.py` `_MARKET_TRIGGER_RE` |
| `haogandu`（`hgd`/`qmd`） | 好感度卡；`haogan 算法` 可达算法页（arg 位词族未拼音化，`haogansuanfa` 不触发属预期） | `domains/chat_reply/capabilities/affinity.py` `_COMMAND_RE` |
| `zhanbu` | 占卜（六爻面；`taluo`→塔罗、`paipan`→八字排盘子意图各归各位） | `domains/divination/capabilities/divination.py` `_DIVINATION_COMMAND_RE` + tests/test_pinyin_triggers_3.py |
| `kuaibao`（`kb`）/ `suijitu`（`sjt`） | 快报卡 / 随机图发图 | `domains/subscribe/capabilities/news.py` / `domains/meme/capabilities/randpic.py` |

**繁體抽样**（fix-tra2/tra3）

| 输入 | 预期 | 异常时看哪 |
|---|---|---|
| `快報`（`早報`/`晚報`/`科技新聞`） | 快报卡（默认条数以真身为准） | `domains/subscribe/capabilities/news.py` `_NEWS_TRIGGER_RE`；「財經新聞/國際新聞/AI新聞」可触发但类目回落 mix 属 fix-tra2 登记残余（类目提取繁體缺口，行为层），非触发层异常 |
| `隨機圖`（`來張圖`） | 随机图发图 | `domains/meme/capabilities/randpic.py` `DEFAULT_TRIGGER_WORDS` + tests/test_traditional_news_randpic.py |
| `親密度` | 好感度卡；`親密度 算法` 直达算法说明页 | `domains/chat_reply/capabilities/affinity.py` `_COMMAND_RE`（fix-tra3 错位④） |
| `點唱 晴天` | 点歌候选卡；候选二次选择「點唱 2」同形态可达 | `domains/music/capabilities/music.py` `_COMMAND_RE`（`点唱`/`點唱`）+ tests/test_traditional_triggers.py |
| `天氣預報 台北` | 天气卡（台北） | `domains/weather/capabilities/weather.py` `_WEATHER_RE` 长词前置；裸「天氣預報」无城市 → 与简体「天气预报」同口径静默不达（fix-tra3 §一.2 产品裁决项，不算异常） |

**昵称形式**（fix-nick：`DEFAULT_VERB_MAP` 补「点唱」「天气预报」两动词）

| 输入 | 预期 | 异常时看哪 |
|---|---|---|
| `守岸人点唱`（`守岸人点唱 晴天`） | 命中 bot.music（昵称动词链合成 `点歌`；无参数行为与裸「点歌」同口径，带歌名出候选卡）；动词后必须空白或结尾，胶合文本不进昵称链 | `domains/chat_reply/runtime/aliases.py` `DEFAULT_VERB_MAP` + tests/test_nickname_verb_gaps.py |
| `守岸人天气预报 台北` | 天气卡（台北）——合成 `天气 台北` 走既有能力 | 同上；裸「守岸人天气预报」rest 为空 → 合成后失配静默（fix-nick 登记既有口径）；「守岸人天气预报说明天下雨」动词后无空白 → 走路由层被陈述句守卫拦落 chat |

**劫持守卫负样本**（probe-hijack 实测 16 HIJACKED → fix-hj1~hj3/fix-wx 全清）

| 输入 | 预期 | 异常时看哪 |
|---|---|---|
| `openai是什么` | 落问答（moegirl 问答卡），绝无个股面板；`openai 估值多少` 带语境词才出个股 | `domains/finance/capabilities/stocks.py` 豁免词语境共现（`_NON_PUBLIC_CONTEXT_RE`）+ tests/test_stocks_hijack_guard.py |
| `我说算命都是骗人的`（「塔罗牌在哪买」「这事八字还没一撇」同族） | 落 chat，无占卜卡 | `domains/divination/capabilities/divination.py` 三守卫（锚定/长度/URL）+ tests/test_divination_hijack_guard.py |
| `油价行情`（`金价行情`/`看看油价行情`） | 落 chat，不出股指面板；`行情`/`美股行情`/`大盘行情` 真命令照常出卡 | `domains/finance/capabilities/market.py` `_NON_STOCK_RE` 商品价格语境排除 + tests/test_market_exclusion_guard.py |
| `天气预报说明天下雨` | 落 chat（陈述句守卫）；「天气预报 称多」带空格的真实县名查询不受影响照常出卡 | `domains/weather/capabilities/weather.py` `is_statement_lead` + tests/test_weather_statement_guard.py |

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
| ④ | 非超管发 `收藏`（带图） | 礼貌拒绝，不落盘 | 误放行 → 查 `BOT_MEDIA_ARCHIVE_MIN_ROLE` 当前值与六级角色判定（domains/chat_reply/policy/roles.py） |
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
> ⑥ 错误报告卡**已落地**（A28 批 + 2026-09-14 P0 两段式异步化 A-rec + A52 补发加速 84b3915；HANDBOOK §24.12）——按本表可执行验收，预期形态=**即时文本回执 + 诊断卡后台补发（约 3-33 秒送达）**（见⑥）。

| # | 验收项 | 触发方式 | 预期 | 异常时看哪 | 预期来源 |
|---|---|---|---|---|---|
| ① | NTP 校时 | 重启后等 ~65s 以上，看运行日志 | 出现授时日志（服务器 ntp.aliyun.com 等 3 台之一，drift 在 ±1.5s 钳制内，成功缓存 10 分钟/失败冷却 5 分钟）；防火墙拦 UDP 123 时周期性 warning+回退系统钟=**预期降级**，提醒投递仍正常（最多偏 1.5s） | 全无授时日志 → 查 `BOT_TIME_SYNC_ENABLED` 与出站 UDP 123；offset 拒收 → 解包门（1970 前/unix≤0 拒收）+钳制语义（timesync.py，M-3/M-4 已修） | startup-audit §四.2/§六 |
| ② | 笔记 CRUD | `笔记 明天带伞`（记）→ `笔记列表`（看；裸 `笔记` 同效）→ `删笔记 1`（删） | 记：回执「记下了，第 N 条，安稳收好」；看：列表含该条；删：回执用「**放下**」措辞（「第 1 条笔记已经放下了」，统一隐喻非「放开」；注意「放下第 N 条」只是 usage 文案里的描述，**不是指令**——指令面=删(除)笔记 N/笔记删 N/shanbiji N）；删除后列表不再出现 | 无回执 → 路由 REMINDER 族（base_router）+信号词命中；库路径 → `ChatBot_Runtime\data\notes.sqlite3`（runtime_paths 重映射，源码树零 `data/`） | route-help §2/§五.2 |
| ③ | 笔记图片收纳 | 发一张图片、同条消息带 `笔记`（或回复图片发笔记指令） | 图片经 SSRF **入口+落点双查**后落盘（uuid 文件名），笔记内容带图片引用行；引用行被改成 `../` 也取不到目录外文件（basename 防穿越） | 拒绝落盘 → 核对 URL 是否内网/重定向落点命中护栏；同批对照 eat.py I-1 已补同款双查（93e8195） | security-report §2 #11；A12 收编 |
| ④ | 做完了自然勾选 | 先 `笔记 交报告`（成待办），再发 `交报告做完了` | 唯一命中→直接勾选，回执「已经替你放下了」族；2-3 条并列→「**有几件事都对得上，是哪一件完成了？**」列候选清单（不说「两件」硬编码）；重复勾选不挂死（mark_done 死锁已修） | 误勾/不勾 → resolve_todo_match 候选逻辑（reminders.py）；卡死 → Critical 死锁修复回归（789700c） | copy-audit C1；route-help §3.1 |
| ⑤ | 分型提醒语气 | `半小时后提醒我吃药` / `明天 9 点提醒我开会` / `回来提醒我买牛奶` | 到点投递按五分型（吃药/约会/购物/待办/自定义）出对应守岸人语气开场（「喝口水，慢慢来」「像钟摆」「海还在这边」族），均带「你之前说过的：原文」；全文无性别化称呼/无「您」/无道歉垫话/无单名 | 不投递 → bot_reminder_tick 每分钟 job（startup-audit §三-9）+授时链路；语气不符 → reminders.py 分型五模板（A21 审计全净基线） | persona-audit §二/§三 |
| ⑥ | 错误报告卡触发形态（两段式异步化） | 重启后临时制造一次能力异常：断网（或拔网线）发一条 `行情` 指令 → 期待**先收到即时文本回执，约 3-33 秒内诊断卡补发**；**冷却期内（60s）再制造一次异常** → 期待降级为一句守岸人纯文本（防刷屏）；恢复网络后重试同命令 | 断网时第一段：毫秒级文本回执（守岸人话术人话区 + 尾注「详细诊断卡随后补发。」，渲染零参与不阻塞 loop）；第二段：云母诊断卡（触发回显≤80 字符+栈摘录暗底块+分区瓦片，本机路径/密钥已打码）由专用单线程 `error-card-render` 渲染后经 send_queue worker 补发（request_id=原 id+`-card`；卡以 `deliver_after=+3s` 入队、worker 30s tick 认领，**约 3-33 秒送达属预期节奏非卡死**——A52 已把补发等待从原 60-92s 基线压到 3-33s，84b3915）；渲染失败 → 补发全量诊断文本（完整性不丢，同延迟同语义）；冷却期内第二次：纯文本一句；恢复后：同命令正常出卡 | 无回执 → 查 `bot_error_card_enabled`（缺省 true）与 pipeline `_internal_error` 旁路钩子；卡迟迟不来 → 查 send_queue worker 与 `:card` dedupe 行（deliver_after 到点后 worker 才认领，sender/queue.py）；无冷却降级 → ErrorCardGate（`bot_error_card_cooldown_seconds`=60，进程内滑动窗）；卡上敏感信息未打码 → redact 链（栈帧逐行，缺省 8 帧）；卡渲染失败应自动降级纯文本（契约零破坏） | error-card-report §P0/§A-plus + error-card-async-design（P0 两段式）；HANDBOOK §24.12-4 |

**收尾纪律**：全部通过后在本节打勾回写，并按台账规矩在 AGENTS.md 台账 #31 记重启生效；任一项不符按 §6.6 收尾纪律走 systematic-debugging。

### 6.6.5 本批新增能力验收（视觉收口+样张+知识库检索，重启生效）

> 覆盖：帮助卡两栏排版（台账 #13 残余收口）/ 卡面样张脚本 / logo 预热 CLI / knowledge-sync 修复后检索验证（§6.5 六域批前置①的验证半边）。证据=`.superpowers/sdd/2026-09-13-six-domain-batch/`（visual-closure-report / samples-script-report / wiki-health-report / error-card-async-design）；错误卡 P0 异步化形态已并入 §6.6.4⑥，不另立条。

| # | 验收项 | 触发方式 | 预期 | 异常时看哪 | 预期来源 |
|---|---|---|---|---|---|
| ① | 帮助卡两栏排版 | `/bot help` 总览页肉眼比对；窄窗口（<560px 等效）再发一次对照 | 总览页 masonry 双栏分区分栏 + 分区内 topic 行两栏 CSS columns；窄卡自动退单栏；长摘要两行截断（line-clamp:2）不破行高；无透明边/无字重超标 | 版式塌陷 → echo.py 帮助 CSS（`.help-grid.masonry` 族）；离线断言 → tests/test_help_card_twocol.py；离线样张 → §6.6.5② `help_index` 卡 | 台账 #13 残余 + visual-closure-report |
| ② | 卡面样张脚本 | `python scripts/render_card_samples.py --list`（只列卡型不渲染，离线快；卡型数以 --list 实跑输出为准）→ 全量 `python scripts/render_card_samples.py`（缺省落 $TEMP\card_samples\；`--out <dir>` 指定；`--only market_index,affinity_group` 抽样） | 全量真渲染（族与张数以 `--list` 实跑为准；含 universal / market（股指·大宗·国债·北向）/ 个股 / 好感度（含脏数据卡）/ 点歌候选 / mermaid 本地素材真出图 / help 两栏目录（真实 help 注册表全量 payload，topic 数以机器册 `docs/auto-facts.md` 为准）/ usage 账单含渠道子行 / media_archive 归档 / error_card 诊断卡）；退出码 0=全过、1=有卡失败（其余照常出图）、2=渲染后端不可用；PNG 供与生产出卡肉眼比对 | 全红（退出码 2）→ playwright 后端不可用（与生产渲染同因，先修后端）；单卡红 → 对应能力 payload 漂移，按 --list 卡名 key 查 bridge | samples-script-report（8520813+收尾批增补，张数一律以 `--list` 实跑为准） |
| ③ | logo 预热 CLI | 工作区根执行 `python -m plugins.bot_unified_runtime.capabilities.stocks` | 幂等预热：输出「logo 预热：全部命中本地缓存（data/stock_logos，零网络）」或失败名单（不阻塞，真实查询懒补）；与 §6.6.3⑤ 同一缓存面（已预热 8/9，meta.com 因 s2 返 JPEG 过不了 magic 契约诚实降级） | 反复全量回源下载 → local_logo_uri「缓存命中零网络→clearbit→s2」链路断（查 `ChatBot_Runtime\data\stock_logos\` 落盘与渲染日志） | a4371d2（fin-report §〇.5） |
| ④ | knowledge-sync 修复后检索 | bot 重启在线后：`powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 context-smoke`；再 QQ 私聊问一个鸣潮设定问题 + 一个 wiki 条目问题 | context-smoke 报告语义检索命中（非顺序取块）；wiki 通道 available（§6.5 前置①已修根，manifest 探测通过；启动后 ~45s 补同步 job 增量幂等）；人格 knowledge 库向量/FTS 通道可用（修复批已 113 pending 清零+签名重建） | 仍顺序取块 → vector_knowledge.py ann/fts 签名与库 meta 对账；wiki 空结果 → kb_wiki.py manifest 探测与 `BOT_KB_WIKI_ROOT` 值；离线实跑底稿=`$TEMP\wiki-audit\`（probe_retrieval：wiki 4 hits/知识 5 hits） | wiki-health-report + vector-audit |

**收尾纪律**：全部通过后在本节打勾回写，并按台账规矩在 AGENTS.md 台账 #31 记重启生效；任一项不符按 §6.6 收尾纪律走 systematic-debugging。

### 6.6.6 表情贴纸回应验收（bot.reactions，重启生效）

> 覆盖：QQ 侧贴纸回应识别（SnowLuma notice → 人格上下文【表情回应】分区注入）+ 主动贴表情（五层门限流：开关→每消息去重→确定性概率→会话冷却→每小时滑窗）。证据=`.superpowers/sdd/2026-09-13-six-domain-batch/reactions-report.md`（代码+测试完成，重启生效；离线用例数以 tests/test_reactions.py 最近一次实跑为准，不手写）。
> 前置：`BOT_REACTIONS_ENABLED` **缺省即开**（config.py `bot_reactions_enabled=True`，无需 .env 配置；配套 `bot_reactions_probability=0.2`/`bot_reactions_cooldown_seconds=30`/`bot_reactions_max_per_hour=20`）；QQ 主动贴依赖 SnowLuma 扩展 API `set_msg_emoji_like`（同戳一戳 `call_api` 裸调模式，失败静默）；QQ 识别依赖 SnowLuma notice `group_msg_emoji_like`——**事件实际字段形态属生产实机首验**（容错解析已覆盖 likes 数组+平铺 emoji_id 两种社区形态，解析失败=零记录零影响）。
> **TG 诚实边界**：识别当前不可用（nonebot-adapter-telegram 0.1.0b20 的 `event_map` 无 `message_reaction` 键，该 Update 在事件转换时被丢弃、到不了任何 handler，等上游升级后接一行 on_notice 即可复用现成归一接口）；主动贴 wrapper 已实现但**不接线**（且 Bot API 要求 bot 在该群为管理员）——**TG 侧零预期，本节全部条目只在 QQ 侧验收，TG 无反应属预期非异常**。

| # | 验收项 | 触发方式 | 预期 | 异常时看哪 | 预期来源 |
|---|---|---|---|---|---|
| ① | 回应识别→人格感知 | 白名单群对 bot 的一条消息贴一个 QQ 表情（群消息回应）→ 10 分钟内 @bot 继续对话 2-3 轮 | 人格回复可自然呼应被贴表情（「你刚才给那条消息点了表情」族语气）——【表情回应】分区已注入人格上下文（bot 自己的消息 id 在回复 sent 分支登记，措辞能说「给我的消息贴了 X」；分区无独立日志，以回复语气变化为观察面）；LLM 有机反应**非必现**，多轮抽样观察，连续多轮全无呼应才算疑点 | 首要嫌疑=SnowLuma 是否真的下发 `group_msg_emoji_like` notice 及字段形态与容错解析是否相符（查 SnowLuma 日志原始事件；不符只需调 `runtime/reactions.py` `normalize_onebot_emoji_like` 一处）；离线基线=tests/test_reactions.py（用例数以最近一次实跑为准） | reactions-report §三/§四.2/§六.2 |
| ② | 主动贴表情（概率门） | 正常聊天；用户消息含情绪信号词（「谢谢帮大忙」「太棒了」「加油」等，简繁均收）可提高触发命中 | 小概率（缺省 0.2，确定性哈希——同一条消息判定恒定，重放不摇摆）给消息贴出 QQ 表情（守岸人温和池：鼓掌/呲牙/偷笑/害羞/惊讶/可爱/流泪/奋斗/憨笑，无攻击性项）；**不贴属概率门正常表现非缺陷**，多发几条信号消息再观察 | 有正常回复但表情从未出现 → 查 `BOT_REACTIONS_ENABLED` 当前值与 SnowLuma `set_msg_emoji_like` 权限（无权限静默失败属设计取舍：该消息不重试，防骚扰） | reactions-report §四.3 |
| ③ | 冷却+时限限流 | ②某次贴出后，30s 内同会话再制造触发 | **30s 冷却内同会话第二次不贴**（`bot_reactions_cooldown_seconds`）；每小时滑窗上限 20 条（`bot_reactions_max_per_hour`）为后台保守限流，真机只做统计性观察不做机械验收；同一条消息双触发（回复后 after_reply+情绪信号 emotion_signal）只贴一次（每消息去重） | 30s 内连贴 → ProactiveGate 冷却/去重语义回归（tests/test_reactions.py 五层门语义回归锁死，用例数以实跑为准） | reactions-report §四.3/§五 |
| ④ | TG 诚实边界复核 | TG 侧对 bot 消息贴回应，或期待 TG 主动贴 | **均不生效=预期**：识别侧适配器不投递该 Update；主动贴未接线（平台权限受限）。不得作为不符项记账 | 未来升级 nonebot-adapter-telegram 后想接通：识别侧接一个 on_notice 分发复用 `normalize_telegram_reaction` 即可（现成接口已留） | reactions-report §三 |
| ⑤ | 关闭零痕迹 | `.env` 设 `BOT_REACTIONS_ENABLED=false` 重启后重复 ①② | 人格侧【表情回应】分区不再出现（provider 拿到 None 整块消失）、主动贴零发生（两触发点在门入口即返回，门状态零消耗）；识别侧 notice 缓冲仍会进程内静默记录但**无任何用户可见痕迹**（内存态，重启即清） | 关闭后仍贴表情 → 先确认进程确为重启后实例（改配置必须重启）+ `bot_reactions_enabled` 热覆盖当前值 | reactions-report §四.3/§七 |

**收尾纪律**：全部通过后在本节打勾回写，并按台账规矩在 AGENTS.md 记重启生效（reactions 批与 0913 各批次同车）；任一项不符按 §6.6 收尾纪律走 systematic-debugging——QQ 识别侧属「事件形态待验证」首验项，首验不符先取证 SnowLuma notice 原始字段再定位，不等于回归。

### 6.6.7 戳一戳 v2 + 贴纸 v2 + R-18 内容感知路由验收（2026-09-16 批，重启生效）

**戳一戳 v2（五件套：回戳/固定话术/LLM 话术/表情包/@戳者）**

1. 群聊戳 bot：应回戳一次（`bot_poke_poke_back` 缺省已开；SnowLuma 不支持时静默），且回复带 @戳者。
2. 回复形态三选一（`BOT_POKE_REPLY_MODE=mix` 确定性轮换）：观察多次戳得到不同形态——固定话术 / LLM 一句话术（≤12s，失败自动回退固定话术）/ 表情包图（库空自动回退固定话术）。
3. 好感度：戳后 `好感度` 查询应有小额正向变化痕迹；同一人同日刷戳不叠加超过 `BOT_POKE_AFFINITY_DAILY_MAX`（默认 5）。

**贴纸回应 v2**

4. 给 bot 的消息贴 QQ 超级表情（如超级赞）：【表情回应】分区应能读出「超级赞」等实名（扩展名表条数以 reaction_store 真身为准；有名才实名，无名落「QQ表情#N」）。
5. 取消贴表情（is_add=False）不应被记为正向回应（真机核对 SnowLuma 是否携带 is_add 字段）。
6. `data/reactions.sqlite3` 生成且有行；`表情库统计`（或库文件）应见 mface/sticker 形态表情入库（商城表情走 VLM 打标）。
7. 情绪消息（如「太厉害了」）在 bot 回复后，小概率收到表情包图（第二层；与贴表情互斥；冷却与每日张数上限以真身键为准；悲伤消息绝不发）。

**R-18 内容感知路由（domains/chat_reply/runtime/content_route.py）**

8. 显式 R-18 词命中：当轮即切 grok-4.6（审计日志 `content_route` 层记号；不记原文）。
9. 模型自评标签：正常对话抽查回复无 `<intimacy:...>` 泄漏（出站剥离）；亲密语境下下一轮起路由到 grok。
10. 「亲密模式 开」私聊命令：确认话术 + 后续会话固定走 grok；「亲密模式 关」解除。
11. 退场：几轮干净对话后自动回默认链（分数衰减）；管理员 `/bot` 显式模型 override 不受内容路由影响。



### 6.6.8 内容政策 v2 批（2026-09-17，需重启后逐条验收）

1. **无英文拒答**：亲密模式开启后连续 ≥10 轮含亲密/情色内容，出站零英文模板句；控制台/日志可见
   `content_route: ... mode=intimate served_by=grok-4.6`。
2. **路由生效**：「亲密模式 开」（及倒装「开启亲密模式」）收到守岸人确认；本轮起 served_by=grok-4.6；
   「亲密模式 关」回默认链。
3. **人格配合**：揉胸/亲嘴/性爱类 RP 得到角色内温柔配合（非说教、非边界复读）；「叫我老公」不再触发
   边界替换文案。
4. **红线仍在**：群聊（未加白名单）发「色情」仍被温和拦；「未成年+性」同句任何会话都拦；
   「你就是个废物」仍温和自守。
5. **群黑白名单**：白名单空时群内「亲密模式 开」无效果；填入群号+重启后，群管理员可开、普通群员拨动无效。
6. **成本**：`/bot model usage` 对比批前——影子并发不再双发；INTIMATE 会话账单 effort 维持基线档
   （不出现 xhigh 计价跳升）。
7. **回滚**：本批未 commit，回滚=按台账 #36 文件清单手工逆编辑（domains/chat_reply/security/content_safety.py/
   config.py/四个 persona 文件/.env/.env.example）。

### 6.6.9 WebUI 仪表盘验收（2026-09-18/19 统一收尾大波次，控制面独立进程）

> 覆盖：控制面四只读统计端点（stats/calls、stats/tokens、stats/latency、affinity/board）+ GET /ui 单文件壳 + SSE 日志尾流对接。事实源=`.superpowers/sdd/2026-09-18-unify-wave/`（progress-BACKEND.md / progress-WEBUI.md）+ `docs/design/webui-dashboard-spec.md` + `docs/design/webui-axonhub-adoption.md`；离线证据=tests/test_webui_stats.py（53 例）+ tests/test_webui_http.py（6 例）+ control_plane 全族回归 290 passed。
> **前置（先配再验）**：
> ① `.env`：`BOT_CONTROL_PLANE_ENABLED=true`（缺省 false=整面关闭）；`BOT_CONTROL_PLANE_TOKEN_SHA256`（管理令牌）+ `BOT_CONTROL_PLANE_SUPER_ADMIN_TOKEN_SHA256`（超管令牌）双 token——**未配置管理令牌时除 /healthz 外一律 503 `control_plane_not_provisioned`（防裸奔，属预期非缺陷）**；
> ② 控制面是**独立进程，不随 bot 主进程重启生效**：单独（重）启 `ChatBot_Runtime\venv\Scripts\python.exe -m plugins.bot_unified_runtime.control_plane`，默认 loopback `http://127.0.0.1:8742`；
> ③ WebUI 壳=`webui/dist/index.html`（vite-plugin-singlefile 单文件构建，离线零外部 CDN；壳内零数据，**不挂 Bearer，同 /healthz 语义**）；数据面全部走 Bearer 端点（页面侧 localStorage 键 `webui:bearer` 管理 / `webui:bearer:ro` 只读）。

| # | 验收项 | 触发方式 | 预期 | 异常时看哪 |
|---|---|---|---|---|
| ① | /healthz 存活探针 | `curl http://127.0.0.1:8742/healthz` | 200 `{"ok": true}`，无鉴权无信息量 | 连接拒绝 → 控制面进程未启动/端口非 8742，看启动日志「控制面启动：http://127.0.0.1:8742（/healthz 探针…）」 |
| ② | /api/v1/protocol 功能树 | 带 `Authorization: Bearer <管理token>` 请求 `/api/v1/protocol` | 200 信封，功能树可见（webui stats/ui 新路由已注册面） | 401 → token 哈希与 .env 不匹配；503 → 管理令牌未配置（前置①）；语义对表见⑦ |
| ③ | stats/calls | `GET /api/v1/stats/calls?window=24h`（Bearer） | 200 信封：总调用数 / by_session（HMAC 假名）/ by_user（`private_<uid>`/`group_<gid>_<uid>` 派生 + unattributed_calls + user_attribution 口径码）/ by_capability / trend（UTC hour\|day 桶）；窗口 24h\|7d\|30d | 422 `stats_invalid_query` → 参数非法（窗口拼错等）；信封内 `source_unavailable`/`audit_source_not_configured` → **空态预期**：生产 `bot_audit_db_path` 默认空=内存实现无数据（诚实降级，不假装修好）；配了库仍空 → 核对 .env 审计库路径与真实落盘；派生口径细节 → progress-BACKEND.md 诚实缺口 1 |
| ④ | stats/tokens | `GET /api/v1/stats/tokens?window=7d` | 200 信封：四项 token（input/output/cache_read/cache_creation）按模型族聚合；空 actual_model 只入 totals 不冒充族 | `source_unavailable` → ledger 记录面无数据（`BOT_LLM_BILLING_ENABLED` 关或库空=空态预期非缺陷）；跨时区历史行窗口边界偏移属既有 P3-9 单时区取舍（progress-BACKEND.md 诚实缺口 3） |
| ⑤ | stats/latency | `GET /api/v1/stats/latency` | 200 信封：渠道 EWMA 当前值 + last_error（已经 redact 脱敏）；`history` 恒 `{status:"unavailable", reason:"not_persisted"}`——**历史曲线无存储不造数，页面历史曲线区无数据=预期**；store 缺失=`not_connected` | 渠道全空 → channel_health store 未装配/无调用记录；last_error 出现敏感串 → 脱敏链失效（登记缺陷）；口径 → progress-BACKEND.md 诚实缺口 2 |
| ⑥ | affinity/board 榜 | `GET /api/v1/affinity/board?limit=10&order=desc` | 200 信封：昵称 + `affinity` 内部值 + `score`（×100 **显数值**，2026-09-15 用户裁定 WebUI 直显；聊天内侧定性口径不变）+ tier/tier_name 档位（复用聊天侧档位表）；limit≤200、order=desc\|asc | `source_unavailable` → 好感库路径未配/空库；数值与 QQ 端 `好感度` 卡对不上 → 核对两处是否同库（bot_affinity_db_path 经 runtime_paths 重映射） |
| ⑦ | 空态/鉴权语义矩阵 | 同一端点分别用：未配令牌 / 错 token / 合法 token+空库 / 非法参数 | 未配管理令牌=503 `control_plane_not_provisioned`；错 token=401；空库=**200 信封内** `source_unavailable`（不是 404/500）；参数非法=422 `stats_invalid_query`；429 限速走既有 v1 读依赖 | 语义错位 → tests/test_webui_http.py（401/503/422/信封/降级/ui 404+200 六例）+ tests/test_webui_stats.py（53 例）逐条对表，再查 progress-BACKEND.md |
| ⑧ | /ui 单文件壳 | 浏览器开 `http://127.0.0.1:8742/ui`（不带 Bearer） | 200 text/html 出单文件页（Cache-Control: no-store）；侧边栏六项导航（总览/调用统计/Token/延迟/好感度/日志）+ hash 路由（如 #/affinity）；暗色切换生效；断网刷新仍可开（零外部 CDN） | 404 `ui_not_built` → webui/dist/index.html 未构建，按 progress-WEBUI.md Stage E 补 `npm run build`；白屏 → 浏览器控制台查 color-mix() 兼容（现代浏览器要求，adoption §六 风险③） |
| ⑨ | 页面五块+日志页【待真机】 | 登录态（页面填双 token）逐页走：总览 / 调用统计 / Token / 延迟 / 好感度榜 / 日志尾流 | 有数据页渲染真数据、空态优雅降级（source_unavailable 如实标注、不放假数据）；好感度榜显数值+档位色阶（负值红阶）；总览三统计卡若仍带 mock 徽章=wave-2 真接口接线未完成的如实演示（非缺陷） | mock 徽章长期不消 → 查 WEBUI-feature/接线席 progress（progress-WEBUIFE.md 落盘状态）；页面字段与端点对不上 → adoption §四 envelope 宽容解包只动 webui/src/lib/api-client.ts 一处 |
| ⑩ | SSE 日志尾流【待真机】 | 日志页开启尾流，另在 QQ 侧触发一条可观测事件（如 /bot status） | EventSource 流式追加滚动；断线自动重连后续流不丢段（Bearer 传递与重连语义以控制面 events 实现为准） | 不滚动 → 先 `curl -N` 直连 `/api/v1/logs/stream` 分层定位前端/后端；握手 401/503 → 同⑦矩阵 |

> **诚实边界**（progress-BACKEND §诚实缺口）：stats/calls 用户维度是**派生值**（audit_records 无 user 列，OneBot session 约定外行进 unattributed_calls，响应带 user_attribution 口径码，页面应如实标注）；stats/latency 历史曲线无存储（要真历史需先落时序表，未立项）；/ui 不挂 Bearer 属设计（壳零数据），如要求壳也鉴权是加一行依赖的事。
> **收尾纪律**：全部通过后在本节打勾回写，并按台账规矩在 AGENTS.md 记重启生效（控制面=独立进程重启）；任一项不符按 §6.6 收尾纪律走 systematic-debugging——浏览器视觉面属生产首验，首验不符先取证（截图+控制台+响应原文）再定位，不等于回归。

**二期三页（知识库/插件/记忆图谱）验收**（2026-09-18/19 波次增补，编号自⑪顺延）

> 事实源=`docs/design/webui-pages2-spec.md`（§1-§7，含 §7 参照图逐项判定）+ `.superpowers/sdd/2026-09-18-unify-wave/progress-BACKEND2.md`（三组只读端点实作与诚实降级；三新文件 55 passed+控制面族回归 406 passed 实跑记录）。
> **数据源（二选一）**：①离线=`python scripts/webui_mock_server.py`（默认 `http://127.0.0.1:8743`，`--port` 可换；`--bearer any` 开 Bearer 存在性校验；确定性夹具固定假时刻 2026-09-18T12:00:00Z，两次启动同请求响应逐字节一致可做目验基线；不模拟 503 未配令牌语义）；②真实=控制面独立进程 `http://127.0.0.1:8742` + 双 token Bearer（前置同本节①②，页面侧 localStorage `webui:bearer`）。**正式验收以真实控制面+重启后为准**（mock 仅离线开发/目验/截图对比用，与生产链路零关联）。

| # | 验收项 | 触发方式 | 预期 | 异常时看哪 |
|---|---|---|---|---|
| ⑪ | 知识库页·collections 全载与 not_available 灰态 | 打开 `#/knowledge`（mock 或真实 Bearer） | collections 全量渲染：页头下居中宽搜索框（占位「搜索术语 / 别名」）+顶部 CategoryChip 集合行；可用集合=可点 chip（选中=品牌色），默认选中=第一个可用集合；not_available 项（真实与 mock 均含「B站网络热门梗」「战双」）=灰态 disabled chip 不可点、附「未启用」标，响应内 reason（`no_dedicated_store`）在页面如实可见，不给假详情 | collections 401/503 → 同⑦矩阵；灰 chip 可点=违规格 §1.2 裁决；端点不可用 → 页面级诚实态卡（说明未启用与启用方式一句话，非白屏） |
| ⑫ | 知识库页·terms 搜索 | 选中可用集合，搜索框输入中文词（mock 夹具词条数以测试件为准（含中文术语/别名））；再输入必然无结果的串 | 输入 300ms 防抖后出结果，中文词命中（术语名/别名任一匹配）；无结果=诚实空态+「清空搜索」按钮（非白屏非报错）；改搜索词重置 page=1 | 对 not_available 集合请求=信封 `source_unavailable/collection_not_available` 诚实降级（非报错）；命中为空仍显旧数据 → 查 Query key `[knowledge, collection, q, page]`；无效参数 → 信封 `invalid_request`（校验先于 IO） |
| ⑬ | 知识库页·分页 total 一致 | terms 列表翻页（mock 条数以测试件为准；真实 `page_size≤100`） | Pager 渲染；响应含 `total`（真实端点返回全量条数），页码/「第 x / y 页」与 total÷page_size 一致、翻页不重不漏；切集合/改搜索词重置 page=1 | 页码不符 → 比对响应 total 与 items 实长；total 缺失时退化上一页/下一页二态属规格预案（以返回为准，现返回含 total） |
| ⑭ | 知识库页·词条卡四行结构 | 任一可用集合的词条卡网格（等宽 3 列 `md:2/xl:3`） | 卡内固定四行：术语名（text-lg）→别名行（text-sm muted，无别名整行省略）→释义（text-sm line-clamp-4，卡尾「展开」toggle 可选）→meta 行（text-xs：来源 Badge muted 态+适用范围文本）；后端缺字段省略对应项，不造占位文案 | 出现空行/占位假文案=违 §1.3「缺字段就省略」 |
| ⑮ | 插件页·四组齐全+event_matchers 诚实空态 | 打开 `#/plugins` | 四组固定顺序：内置 builtins→适配器 adapters→事件匹配器 event_matchers→迁移插件 migrated_modules，组头 text-lg+数量徽章；event_matchers=诚实空态组（后端组级 not_available+reason `cross_process_introspection_unavailable`，不从路由表反推假清单）→整组一张「事件匹配器清单暂不可用」空态卡，不渲染空网格；某组空数组=组头+「暂无条目」不藏组 | 事件匹配器组出现条目列表=假数据（违诚实纪律）；组序错乱/藏组=违 §2.2 |
| ⑯ | 插件页·徽章三态+无假按钮 | 逐组看条目卡徽章；全页扫一遍按钮 | 徽章三态严格：`hot_reload===true`→品牌（default）态「热更新即可」；`===false`→secondary 灰态「要重启」（adapters/migrated 真实值即 false）；`null`/缺字段→不渲染徽章（builtins 依 descriptor.hot_toggle，无值不猜）；本页纯只读：无启停/重载/配置/详情任何按钮（后端无操作端点，参照图「配置」钮已判不适配 §7-D5） | null 也渲染徽章=违三态；出现操作按钮=放假功能，对照 §2.3/§2.4 |
| ⑰ | 记忆图谱页·六统计卡窗口联动 | 打开 `#/memory-graph`，切 24h/7d/30d/all | 六枚 StatCard 顺序固定（人物/群聊/对话/长期记忆/已学规则/发言条数），数值随窗口切换联动；stats 恒为截断前总量（不因 max_nodes 截断缩水）；全源缺失=200 信封 `source_unavailable/all_sources_missing`+stats 全 0（诚实空态非报错） | 数值不随窗口变 → 查 Query key 是否含 window；stats 小于画布节点数=截断撒谎（缺陷） |
| ⑱ | 记忆图谱页·画布出图+图例+truncated+只读提示 | 选节点多的窗口（如 all；`max_nodes≤200` 缺省 120） | 画布出静态力导向一帧（d3-force 固定 300 tick，无动画循环）；画布下方图例五类型（人物/群聊/对话/长期记忆/已学规则）色点与节点色一一对应（chart-1..5 token，canvas 经 getComputedStyle 取色不造色）；`truncated:true`→画布顶部 info 条「仅显示关联最多的 N 个节点」（N=实际 nodes.length，响应带 nodes_total）；画布角落常驻「拖拽平移 · 滚轮缩放 · 点击节点看详情」+连线只读提示（§7-B9「连线只读、不会改动记忆」语义吸收入文案） | 不出图 → 浏览器控制台+该窗口 nodes 是否为空（空=空态卡「该时间窗内无记忆关联数据」提示换更大窗口，非缺陷）；图例/节点色不对应 → 查 token 读取链 |
| ⑲ | 记忆图谱页·节点详情侧栏+重排确定性 | 点击任一节点；同窗口反复切换视图/重开页；换窗口再换回 | 点击节点→右侧详情侧栏（名称/类型/关联度/后端返回节点字段逐项展示，未知字段不编造）；确定性：同窗口同数据两次渲染布局坐标全等（布局纯函数=固定初始化+固定 tick，确定性断言入 tests 容差 0）；数据未变时切换视图/重开页不重排；五类型全不选=自动回全选（不给空图死局） | 同数据布局漂移 → 跑确定性单测+查是否混入随机初始化/动画循环；侧栏造数=违诚实纪律 |
| ⑳ | 通用·版式宪法机器门+零硬编码 | 跑硬编码扫描机器门（脚本由 WEBUI-FE 席交付，脚本名以其 progress 落盘为准），范围=三页+专属子组件目录 | 机器门退出码 GATE_EXIT=0（色值字面量/任意值字号/刻度外间距/圆角档外值命中=0）；零硬编码色值与字号（颜色只走语义 token 与 --chart-1..6；字号五档 12/14/16/18/20px；间距 4px 刻度；圆角 30/18/14）；新写 CSS 类=0、新增 .css 文件=0；内联 style 仅画布容器两处白名单（画布高度/侧栏宽度）且在 progress 登记文件+行号 | 门非 0 → §5 等价快查 `rg -n "#[0-9a-fA-F]{6}\|rgba?\(\|oklch\(\|text-\[\|\[\d+px\]" src` 定位；白名单外内联 style=违组件复用率门 |
| ㉑ | 通用·三页优雅态（无后端非白屏） | 三页分别在 后端未启（连接拒绝）/端点 404/200 信封 source_unavailable 三种形态下打开 | 三页均有优雅态：页面级诚实态卡或组级空态（说明未启用/不可用+一句话指引），骨架屏/错误卡收尾，绝不白屏、绝不放假数据；请求失败错误卡展示 code/message | 白屏 → 浏览器控制台（color-mix() 兼容同⑧）+该页错误边界；出现 mock 数据 → 全站纪律禁止（dashboard 既有 mock 徽章演示卡为唯一例外） |

> **诚实边界**（progress-BACKEND2）：event_matchers 组=跨进程无内省通道的如实 not_available（绝不反推假清单）；memory graph 截断如实 truncated+nodes_total（stats 不缩水）；knowledge kb_docs 的 updated_at 无存储=诚实 null；全源缺失一律 200 信封内降级码（非 404/500）。回归锚点=tests/test_webui_knowledge.py+test_webui_plugins.py+test_webui_memory_graph.py（55 passed）+控制面族回归 406 passed（progress-BACKEND2 实跑记录）。
> **收尾纪律**：同本节上方既有纪律；三页首验不符先取证（截图+控制台+响应原文）再定位，前端交付状态以 `.superpowers/sdd/2026-09-18-unify-wave/progress-PAGES2.md` 落盘为准，不等于回归。

### 6.6.10 渲染统一收口批观察点（11 面，2026-09-18/19 波次，重启生效）

> 覆盖：渲染统一收口批渲染面数值收口（面数以 C1-C13 值册为准）（`docs/design/v21r3-render-closing-spec.md` 裁决 C1-C13：字号≥12px / 三枚色斑 46/52/58s / 玻璃两档 / 语义色单源 / 行高刻度 / mono 栈等）。事实源=同规格 §0.2/§一/§二 + `.superpowers/sdd/2026-09-18-unify-wave/`（progress-DIRECT / progress-FINMKT / progress-UNIVERSAL / progress-CORE / progress-SAMPLES / progress-MISC2 / progress-PRECHECK3）。
> **前置**：bot 提权重启（渲染链路在主进程，改代码必须重启生效）。
> **落地状态（终态，判定前先读）**：数值收口面数以 C1-C13 值册为准，**全部落地**——直拼卡（直拼族以括注为准）（echo/debug/usage/media，progress-DIRECT）+ finance/market（progress-FINMKT）+ universal（progress-UNIVERSAL）+ misc 四模板 mermaid/song/affinity/error（MISC2 切换 + MISC3 验证收尾：bridge 通水、mermaid 伪元素特例复位、error wash_blob_mix=24 豁免闭环，progress-MISC2）；「通水」（壳层/装饰层切 mica_shell 生成器消费，C13）**已完成**；渲染全域门禁 **588 passed / 0 failed**（progress-PRECHECK3），样张判据=`baseline-20260919-paused` PNG 字节等值。**唯一待执行项=INTG verify_hashes 哈希重录**（各席守纪未 --write，15 项 DRIFT 收尾一次重录；重录前不影响本节真机观察）。

**通用观察点（11 面逐卡过一遍）**

| # | 观察点 | 预期 | 异常时看哪 |
|---|---|---|---|
| ① | 字号下限 | 无 <12px 观感（11/11.5/12.5px 全收敛 12px，脱阶 13.5/14.5px 收敛 14px）；**echo 帮助卡无小字** | 样张复核 `python scripts/render_card_samples.py --only <卡key>`；源面 grep 12.5px/11.5px/11px（规格 §0.2-E 清单：12.5px 实测 5 处） |
| ② | 三枚漂移色斑 46/52/58s | 每卡三枚色斑（drift-a/b/c，46s/58s/52s）交错漂移——全 11 面已落地：finance/market（DOM 补 drift-c）+ universal 非视频分支 + echo 帮助卡通水补齐（gate02 全 11 面绿实证，PRECHECK3）；mermaid 为伪元素特例（.card::before/::after 两斑，MISC3 复位）；error 卡 wash_blob_mix=24 豁免保持（MISC3 闭环实证） | 逐卡数 DOM `<span class="drift-blob drift-[abc]">`（mermaid 例外查 .card::before/::after）；时长不符查 mica_shell 生成器 BLOB_DURATIONS 与手抄层残留（通水已完成，不符按回归定性） |
| ③ | reduced-motion 关停 | 系统开「减少动态效果」后色斑静止；finance/market 已修特异性缺陷（关停规则 `.drift-blob.drift-a/.b/.c` 与动画声明同构、源序其后=结构性可靠，progress-FINMKT #3） | 仍漂移 → 查该卡手写 `@media` 残留（规格 §0.2-G9 特异性竞争形态）；离线=test_phase_determinism + 生成器 reduced-motion 断言 |
| ④ | 语义红绿一致 | 红系一律 #d54941（危险/涨）、绿系一律 #2e9e6b（成功/跌）、琥珀 #b07d1a（警告）——usage ok/bad、debug good/bad 已换值（progress-DIRECT）；finance/market --up/--down 经 var(--semantic-danger/success) 消费（progress-FINMKT #1，实现名以 --semantic-* 为准）；**A股红涨绿跌语义不变**；好感度评分色 #157347/#b42334 是刻度色、非语义红绿混淆项 | 同一「涨/跌/成功/失败」在不同卡颜色不同 → 查该面是否残留 #d64545/#1a9e6c 旧字面（门4 黑名单）；bridge._spark_points 直出 SVG 折线色为已登记遗留（progress-FINMKT 遗留1，归 CORE/INTG） |
| ⑤ | 渲染失败纯文本兜底 | 任一卡渲染后端失败回纯文本不报错不刷屏（兜底契约零破坏，最坏=外观回退） | 兜底白底方块/报错 → render_backends 兜底分支 omit_background（C12）+ 渲染日志 |
| ⑥ | 玻璃两档观感 | 面板档 0.66→0.44、页脚档 0.66→0.46、描边 0.95/0.35/0.72；无 0.68/0.55/0.60/0.62/0.50 散值观感（字面归档与 token 消费均已落地） | 分层不可辨/疑漂 → 规格 §一 C3 归一映射表逐行对 |

**逐卡触发清单**（每卡触发一次，通用观察点①-⑥逐卡过）

| 卡 | 触发方式 | 本卡重点 |
|---|---|---|
| 帮助（echo 直拼） | `/bot help` | 无小字；两栏排版不崩；色斑三枚已通水补齐 |
| 账单（usage 直拼） | `/bot model usage`（账本开时） | 状态胶囊绿 #2e9e6b / 红 #d54941；渠道子行正常 |
| 解析（universal） | 发一条 B站链接 | 视频/非视频分支壳 30px 圆角观感；非视频分支第三枚色斑垫底不越层 |
| 媒体（media 直拼） | 触发一次媒体归档出卡 | 行高/徽章遮罩观感正常 |
| 好感度（affinity 模板） | `好感度` | 档位色阶不回归（score hot/cold 刻度色） |
| 点歌（song 模板） | `点歌 晴天` | 12px 收敛；玻璃 0.68→0.66（misc 席已落地） |
| 行情（market 模板） | `行情` | 三枚色斑；红涨绿跌 #d54941/#2e9e6b；.index .pct 无小字 |
| 金融（finance 模板） | `黄金` / `英伟达股价` | 同上（.row .delta 无小字） |
| mermaid（mermaid 模板） | 会话发一段 mermaid 代码块 | 正常出图；字体栈统一观感 |
| 错误卡（error 模板） | 断网发 `行情`（两段式形态参照 §6.6.4⑥） | 第三枚色斑（misc 席已落地，wash_blob_mix=24 豁免保持）；冷却降级纯文本不破 |
| debug 检查卡（debug 直拼） | 管理员触发 LLM 检查出卡（样张 key=debug_llm_setup） | 等宽字体统一（Cascadia Mono 栈）；warn 琥珀 #b07d1a |

> **离线复核手段**（真机存疑时）：样张基线比对=`python scripts/render_card_samples.py --out <目录>` 后与 `$TEMP/shorekeeper-samples/baseline-20260919-paused/` 逐面比 PNG 字节等值（主判据，WAAPI 钉帧后双渲逐字节确定；html_sha256 做旁证）；机器门=tests/test_v21r3_visual_gates.py 九门 + 五族既有契约（rendering_contract/mica_builders/visual_audit/e03/phase_determinism）；INTG 收尾状态以 master-plan Wave 3 与其 progress 为准。
> **收尾纪律**：全部通过后在本节打勾回写，并按台账规矩在 AGENTS.md 记重启生效；任一项不符按 §6.6 收尾纪律走 systematic-debugging——misc 席四模板与通水项**均已落地**（progress-MISC2/PRECHECK3），首验不符先对照该席终态证据再定性；当前唯一待执行项=INTG verify_hashes 哈希重录（见顶部终态声明）。

### 6.6.11 语音合成（bot.tts）验收（Wave G 契约波定版（项数以本节各阶段表为准），2026-09-20；重启生效）

> **本节为整节替换版**：旧 14 项经 T36 取证**无一完整可跑通**（生产可证成功合成 0 次=T21；③⑩⑫根本验不了、③⑤⑨⑫⑬预期与实码相反或过强=T7 §3），已整体作废，按 `.superpowers/sdd/2026-09-19-unify-audit/report-T36.md` 换成 **30 项**（离线 O1-O8｜只启引擎 E1-E6｜真机 R1-R16；「只启引擎、不重启 bot」可走完 O+E 全部 14 项）。旧 14 项→新 30 项映射见节末表。
> 事实源=`report-T36.md`（蓝本+探针）＋已落行为刷新：`report-T57.md`（M-09 退避真闸 30s/M-11 缓存身份）、`report-T61.md`（预设表/Field 域闸/硬顶 2000 字·8MiB/静音三指纹闸/seed 确定性/配额缺省关）、`report-T70.md`（触发词∪追加口径，T70 时点 11 词）、`report-T92.md`（繁體收口 11→16：說/語音/唸/朗讀/語音合成，ff091dc）、`closeout-manifest.md` §五。**标注约定**：〔播声依赖 T32〕=QQ 语音条播不播得出待 T32 结论（NapCat 吃不吃 wav、silk 谁转），先判到「落盘/出站」层；〔T73 在建，默认关〕=voice hook 装配在飞、缺省关不影响本节判据；〔T75 待落〕=M-14 截断可观测化+M-17 名单同源在飞，行为变化待其披露表，本节不写死。
> **取证留痕纪律（全节适用，T36 §4）**：证据落 `$TEMP/t76-evidence/<日期>/`（不落源码树）；每项最小留痕=输入原文截图→回执截图→产物 `ffprobe` 整行输出→命令+末行输出；每项只准写 **过/不过/未能取证**（后者必附原因），禁止「预期会过」代替实跑；`.env` 改动类先备份 `.env.bak-<日期>-<用途>`（不记密钥值）、测后恢复+二次重启也留痕；不合格样本 wav **复制**留证、不动 Runtime 原件；汇总「N 项全过」前逐项比对过判据原文，统计类必须给样本量与原始计数。

> **前置（先配再验）**：
> **P-1（配置面）** `.env`：`BOT_TTS_ENABLED=true`；`BOT_TTS_GPTSOVITS_DIR=$DEV_ROOT/GPT-SoVITS-V2Pro`；`BOT_TTS_REF_AUDIOS` ≥1 条，格式 `路径|参考文本|语种`；预设表选择键 `bot_tts_preset`（缺省 `shorekeeper`=v1 现状收编，枚举白名单 `TTS_PRESET_IDS`，T61）；数值键已上 Field 域闸（speed 0.6–1.65/top_k 1–100/top_p 0–1/temp 0–1 等，域值逐字=T53 真值表）、`0=不限` 语义已修死（T61 M-35）。⚠️ `BOT_TTS_*` 键族=RESTART_REQUIRED 诚实登记（能力持装配期 config，热改假生效——改键必重启，T61 登记矩阵）。自动化体检：`python scripts/pre_restart_check.py` 第 10 项=tts_voice 音色守望者（T60 `1b2860c`，SKIP 不假红/FAIL 五类人话）；.env 配置面体检=仓内 `scripts/verify_chatbot_env.py`（T87 重建 `7e2fe36`：判据走生产 Config 真身、治 T24 F1-F5 假安心；分工=本工具**手动快查** bot 侧配置面非重启门，重启前置体检=pre_restart_check 10 项、其第 10 项守**引擎面**音色身份，两者零重叠）；旧仓外件 `$DEV_ROOT\GPT-SoVITS-V2Pro\tools\verify_chatbot_env.py` 现状必崩（T24 P1-1）维持**不引用**；.env 人工核对=`grep '^BOT_TTS_' .env` 逐键对 `docs/config-catalog-full.md`。
> **P-2（引擎拉起）** 一律用 `$DEV_ROOT\GPT-SoVITS-V2Pro\启动守岸人.bat`（bot 在跑会自动只起引擎）；**禁止从其它目录裸敲 `/GPT-SoVITS-V2Pro/api_v2.py`**——权重相对路径按进程 CWD 判定，错 CWD **静默回退底模且 `save_configs` 写回 yaml 永久化**（T2 P1-2）。就绪判定：模型加载先于端口 bind，**9880 通=模型就绪**；首启 20~60s 为脚本自述非实测，预算 180s（本清单最长一步）。
> **P-3（绑定红线）** 起后核 `netstat -ano | findstr :9880` **只允许** `127.0.0.1:9880 LISTENING`；见 `0.0.0.0`/`[::]` 立即停。
> **P-4（参考音频）** 数秒至十秒级干声为引擎服务端硬卡（转 16kHz 后 48000~160000 采样点，无配置可放宽=T2）；bot 本地不预检（无 soundfile），越界=多付一次 HTTP 往返后收降级文案（命令式有文案、自动配音路径静默零提示=T7 P2-5）。语料面自动化判据（T136 登记=T96 新件）=`tests/test_tts_corpus_gate.py`：**权威=`.env` 运行时装载值、tsv 一律降为推导副本**；门体=清单钉死 8 条 flac/竖线污染探针（M-29）/FLAC STREAMINFO 时长 3~10s 引擎硬卡/**反向毒化探针**（把 tsv「可粘贴块」当 .env 清单喂门必红——锁死「照 tsv 覆盖 .env」歧路=M-28/M-30）；红面三件 `xfail(strict)` 棘轮=tsv 未回写校对的现状病（修复转 XPASS 当场报错即收口）；本机无 .env 语料或引擎目录→SKIP 不假红（2026-09-20 T136 实跑 5 passed/3 xfailed）。
> **P-5（重启窗）** bot 面验收前需提权重启：父 `venv\Scripts\python.exe bot.py` + 子 `python.exe bot.py` **两个都停**，重启命令走 `scripts/dev.ps1 -Task run`；重启窗=全工作树大合流，窗口由用户裁决。
> **P-6（stdout 重定向）** `ChatBot_Runtime/logs/nonebot.out.log` 自 2026-09-17 23:28 起零字节（T21）；重启时**必须**把 stdout 重定向落盘，否则本节所有「看日志」项（R1 计数、R13 日志核对）全部不可证。**前置自检一键编排**（T117 新件，T136 登记）=`venv python scripts/tts_offline_selfcheck.py`：三步串行 **pre_restart_check 10 项 → verify_chatbot_env（T87 重建件）→ 语料门 `tests/test_tts_corpus_gate.py`（存在才跑、缺=SKIP）**；纯编排零业务断言——判定逐项透传、SKIP 放行不假红、任一 FAIL→exit 1 并透传子工具逐项 fix_hint（`--json` 结构化、`--dry-run` 桩化演练）——重启前跑一遍即覆盖 P-1 自动化体检面，不替代各分项判据。**retcode 采集器（SnowLuma 换件判据工具行）**=`venv python scripts/tts_retcode_collect.py`：T55 §七唯一 open 项「SnowLuma 实回 1400/100 未真机复现（读码预判实集={100,1200,1400,1404}，置信度 high 非 verified）」的采集手段——**验收窗后**对缺省日志位（=本条重定向落盘的 stdout/err 日志）离线扫 retcode 分布：实测码集 ⊆ 预判集 → T55 §七闭合证据 +1（`--json` 输出即留痕件）；出现集合外码 → 新形态提示另案（留痕后对照 SnowLuma 枚举）；零记录 → 健康面提示（先核本条重定向是否落实）。证据采集器非门：出现失败码不非零退出（exit 1 仅当无一文件可读）；我方终态白名单现状=10 码 {403,404,100,1003,1200,1201,1400,1401,1403,1404}（`domains/transport/sender/onebot.py` `_is_final_failure_retcode`，T78：1400/100 已入名单、1200 挂起例外已删改终态化）。
> **P-7（观测面事实）** `runtime_events.log` **不记 bot.tts**（命令路 `_run_simple_capability` 零事件=T14/T21）；只作负对照（其中不应出现任何用户正文，出现即另立案）。语音主证据面=`ChatBot_Runtime/data/tts_output/` 产物 + nonebot stdout + QQ 截图。
> **P-8（T32 悬案）** 「QQ 语音条播不播得出来」待 T32 结论；凡判据含「听到声音」的项标〔播声依赖 T32〕——「发出去了吗」与「播得出来吗」分两栏记账，勿混判。

**阶段 O · 离线可验（不启引擎、不重启 bot、不发真实消息；项数以本阶段表行为准）**

复跑环境（每个 shell）：
```bash
cd "<仓库根>"
export PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1
PY="../ChatBot_Runtime/venv/Scripts/python.exe"
```

| # | 验收项 | 怎么触发（可粘贴） | 预期（过/不过判据） | 不过时看哪里 |
|---|---|---|---|---|
| O1 | 虚词负样本路由守卫·M-01【离线可验】 | 附录 A1 探针（10 句负样本逐句过 `classify_message_route`）；快捷=`"$PY" -m pytest tests/test_tts_hijack_guard.py -q -p no:cacheprovider --basetemp="$TEMP/t76/pt"` | **过**=探针 10/10 句 `kind=CHAT capability_id=bot.chat` 且回归锁全绿（本席 T76 2026-09-20 实跑 62 例 passed）；**不过**=任一句 `kind=TTS`。**修前（≤09-19 16:57 态）此组全红属预期**（T15 实锤 201/295）；18:33 边界集已去虚词，修复完整性以 T15 全量语料复跑定 | 边界真相源=`tts.py` `_TEXT_BOUNDARY_CHARS`（:103，纯标点空白+「不得出现汉字」棘轮断言；中央件 `domains/core/text_boundary.py` 权威取值即源于此=T59，randpic/media_archive/group_info/mentions/base_router 五副本已换线 `cf7ec29`）；`tts_match`（`domains/chat_reply/runtime/base_router.py:444`）；`extract_trigger_words` 盲区已修（`767f2b5`，bot.tts words 0→11） |
| O2 | 裸触发词不占路由（旧③离线锚）【离线可验】 | `"$PY" -m pytest tests/test_tts.py::test_tts_match_ignores_bare_trigger tests/test_tts.py::test_bare_trigger_word_yields_empty_body -q -p no:cacheprovider --basetemp="$TEMP/t76/pt"` | **过**=两例绿（只发「说」不路由、取正文为空）；**不过**=任一例红 | 根因链 `extract_tts_text` `stripped == word → ""`；能力层 `missing_text` 引导分支为**生产死分支**，勿按其存在反推真机出引导（T7 P1-2）；真机面=R3 |
| O3 | 概率门确定性+稀疏性（旧⑨⑩迁入）【离线可验】 | `"$PY" -m pytest "tests/test_tts.py::test_should_voice_reply_is_deterministic_and_sparse_by_default" "tests/test_tts.py::test_maybe_attach_voice_probability_gate_skips_synthesis" -q -p no:cacheprovider --basetemp="$TEMP/t76/pt"` | **过**=两例绿：同 seed 源（session_id:message_id）重复判定恒定、默认 0.05 下命中率≈5%（非全中）、「概率未命中→不付合成调用」；**不过**=任一例红或被人改成 `random`（铁律：概率门必须哈希，`tts.py` 内 `random` 只准出现在 `pick_ref_audio`） | 判定式 `should_voice_reply`（seed 哈希 bucket<p*10000，与 `gate.py` 确定性群抽签同构=T7 正面记录）；真机面=R10 |
| O4 | 门链先于概率·不叠加已有音频（旧⑫迁入）【离线可验】 | `"$PY" -m pytest "tests/test_tts.py::test_should_voice_reply_gates_before_probability" -q -p no:cacheprovider --basetemp="$TEMP/t76/pt"` | **过**=绿（`result.audio` 非空、非 bot.chat、总闸关等门逐一先短路）；**不过**=红。旧⑫真机场景不可构造（`_attach_voice_reply` 全仓唯一挂点只包 chat、chat 零 audio 产出=T7 P2-2），真机半=「R1 只见一条语音不双发」 | 门链锚点 `should_voice_reply`（`__init__.py:341/:356` 现值，行号以重启时代码为准——T73 hook 化在飞会移位〔T73 在建〕） |
| O5 | 错误体解析顺序（旧⑥离线锚）【离线可验】 | `"$PY" -m pytest "tests/test_tts.py::test_request_tts_error_body_prefers_exception_over_message" -q -p no:cacheprovider --basetemp="$TEMP/t76/pt"` | **过**=绿（引擎 400 体先读 `Exception` 后读 `message`）；**不过**=红=修复回归（真机面由 R6 判） | `_request_tts` 错误体分支；失败记账现收编 `_record_failure`（T57）；引擎实况 $DEV_ROOT 下 `/GPT-SoVITS-V2Pro/api_v2.py` 错误体（只读） |
| O6 | 出站形状契约（旧⑭离线半）【离线可验】 | `"$PY" -m pytest tests/test_tts_outbound_chain.py -q -p no:cacheprovider --basetemp="$TEMP/t76/pt"` | **过**=全绿（`CapabilityResult.audio → {"type":"record"} → SendQueue → onebot record 段`；用例数以实跑末行为准）；**不过**=红。**证明力边界**：该套测的是 dict 形状与键，对「QQ 播得出来」零证明力（T32 悬案），绿≠可播 | renderer audio 循环 + `domains/transport/sender/onebot.py` record 分支（⚠️ 必须写 domains 真身；旧径 `domains/transport/sender/onebot.py` 为 12 行垫片=T7 P3-1） |
| O7 | 打码旁路取证·M-03【离线可验】 | 附录 A2 探针：`clean_for_speech` 吃自造假值句 + grep tts 源零打码引用（T36 18:36 实跑三判据全中） | **修前预期=红（如实登记，不伪装成绿项）**：`sk-TESTFAKE…` 原样残留=True、盘符路径残留=True、`BOT_` 形态被清洗吃成打码器认不出的串=三条全中即 M-03 在位。**修后过判据**=探针断言反转：清洗产物不含 `sk-TESTFAKE`/`FakeTest` 且打码发生在 `clean_for_speech` **之前**（「先清洗后打码」对 BOT_ 形态必失效=T9 P0-3）。真机面→R13 | 打码器 `domains/render/plain_text.py:340 redact_local_secrets`（`_BOT_ENV_ASSIGN_RE`；占位符第二形态 `<本机路径已隐藏` 已补=T61）；语音入口 `tts.py` `clean_for_speech`；`domains/media/` grep `redact` 命中 0（T36 实跑） |
| O8 | 红线拦截缺席取证·M-02【离线可验】 | 附录 A3 探针：同一红线探针句分别过 `assess_public_content`（文字侧）与 `build_tts_capability`（语音侧，monkeypatch `_request_tts` 零网络） | **修前预期=红**：文字侧 `action=refuse`（minors/minor_ambiguity 硬线），语音侧照常产出 audio dict+落盘 wav=零拦截实锤（T9 P0-1 已实跑同款）。**修后过判据**=语音侧对同句**不合成**、回边界话术、无新 wav。⚠️ 探针句用无害构造（年龄词即可，勿写露骨文本）。真机面→R14（修前**不建议**真机跑，离线红即足以立案） | 文字侧闸 `domains/chat_reply/security/content_safety.py:383 assess_public_content`（minors fail-closed，任何参数不绕）；语音侧缺口=`tts.py` 全文零内容政策导入（T36 grep=0）；审核旁路根因=reviewer 对 audio 无文本可审（T9 P0-2）；群门不同源=`explicit_allowed_for_session` 零语音引用——M-17 中央同源施工中〔T75 待落〕 |

**阶段 E · 须引擎在跑（不重启 bot、不发真实 QQ 消息；项数以本阶段表行为准——前置 P-2/P-3；引擎目录零改动，U-21/U-22 引擎侧动作待用户授权=manifest §五.4）**

| # | 验收项 | 怎么触发（可粘贴） | 预期（过/不过判据） | 不过时看哪里 |
|---|---|---|---|---|
| E1 | 引擎拉起与监听面【须引擎在跑】 | 起前体检：`powershell -NoProfile -ExecutionPolicy Bypass -File "$DEV_ROOT\GPT-SoVITS-V2Pro\start-shorekeeper.ps1" -CheckOnly`；再双击 `启动守岸人.bat`（或同 ps1 `-NoBot`）；起后 `netstat -ano \| findstr :9880` | **过**=netstat 仅 `127.0.0.1:9880 LISTENING` 一行；**不过**=`0.0.0.0`/`[::]` 出现（立即关窗=P-3 红线）、或 180s 预算内端口不通（引擎窗口看 traceback） | 引擎控制台窗口尾部输出（ps1 现版不落盘 stdout——引擎侧落盘=U-22 待授权）；20~60s 自述非实测；⚠️ 别按 ps1 注释敲「`/启动守岸人.ps1`」（不存在，入口=bat，T20 卫生条） |
| E2 | 音色身份静态核对【须引擎在跑】 | `grep -E "t2s_weights_path\|vits_weights_path" "$DEV_ROOT/GPT-SoVITS-V2Pro/GPT_SoVITS/configs/tts_infer.yaml"` + 引擎窗口扫 `fall back to default` + `python scripts/pre_restart_check.py`（预检 tts_voice 项） | **过**=custom 段两行含 `shorekeeper`（`GPT_weights_v2ProPlus/shorekeeper_e15.ckpt` + `SoVITS_weights_v2ProPlus/shorekeeper_e8_s1144.pth`）且窗口无回退行、守望者项 PASS/SKIP（SKIP 不假红=T60）；**不过**=底模名（`s1v3.ckpt`/`v2Pro/s2Gv2ProPlus.pth`）⇒ **能出声但音色必不是守岸人**（静默回退+写回永久化，T2 P1-2），立即停引擎并从基线恢复 yaml（改前备份到 $TEMP；权重路径改绝对=U-21 待用户授权） | yaml mtime≈本次启动时刻属正常（`save_configs` 每次启动回写=T2/T20）；守望者 FAIL 五类人话输出=T60 判定序（基线→yaml→解析→语义→实存→sha256） |
| E3 | 浏览器试听=引擎契约直锤+音色第一耳【须引擎在跑】 | 附录 A4 curl 命令（`text_lang=zh` 与 `prompt_lang=zh` **必带**，漏传 AttributeError=引擎坑）落盘 `$TEMP/t76-evidence/e3.wav` 后 ffprobe+听 | **过**=HTTP 200、ffprobe `pcm_s16le/32000Hz/mono`（产物率=权重自带，bot 侧不可控=T25）、听到中文女声；**不过**=400/500（读错误体 `Exception` 原文归因）、**1 秒左右静音**（引擎推理期异常返 200+静音 wav=T2 P1-1——bot 侧捕手见 R15 三指纹闸）；**音色是否守岸人只能靠耳朵**（E2 静态过≠音色对） | 首页 `http://127.0.0.1:9880/` 返回 `Not Found` 属设计非故障、`/docs` 能开=活着；错误体形态全集=T2 §T2.2 |
| E4 | 参考音频越界引擎拒收（旧⑥引擎面，隔离 bot 变量）【须引擎在跑】 | 从 `$DEV_ROOT\GPT-SoVITS-V2Pro\refs\corpus_durations.csv` 挑一条 `duration_s>10` 的语料路径，代入附录 A4 的 `ref_audio_path`（正文用短合规句） | **过**=HTTP 400、JSON 体 `message="tts failed"` 且 `Exception` 含 `3~10秒`（本机 locale 实况为**繁体**「參考音頻」，简中四字**永不出现**=T2 P2-2，判据只钉 `3~10秒` 子串）；**不过**=200 出声（服务端硬卡被绕过=重大变更，核对引擎版本） | 引擎 `/GPT_SoVITS/TTS_infer_pack/TTS.py` 硬卡（只读）；bot 侧文案面同判→R6 |
| E5 | 括号动作引擎念法试听（听感首验）【须引擎在跑】 | 附录 A4 变体：`text=（微微一笑）今天的海风很温柔，你想我了么？`（=T25 实跑过清洗的出门形态原样喂引擎） | **修前预期=不合格**：动作文字（「微微一笑」等）**被完整念出**（全角括号大概率吞符号但内容字逐字念，cut5 把动作段切独立段+段尾 0.3s 静音，T25 P1-3）→录音存档即 M-04 听感缺陷立案证据；**修后过判据**=只念台词、动作处无字声或明示停顿。另听 `……` 截断处的「假完整」 | bot 清洗零括号规则（`clean_for_speech` 现状，T36 复跑残留=True）；文字侧真相源 `domains/render/roleplay.py`（修复应同源复用=T25 Q3） |
| E6 | 8 条参考池逐条试听（音色一致性+语气库建账）【须引擎在跑】 | 对 8 条 `refs/shorekeeper_ref_01..08.flac` 各发一条固定文本（`ref_audio_path` 轮换、其余参数同），每条落盘试听 | **过**=8 条听起来**同一个人**（守岸人）；**不过**=①两条间「两人格感」→扩池作废回 T3/§5.4 裁；②某条明显底模感→E2 复跑。逐条记「语气标签×听感」表（建池宣称=陈述/关切/歉意/承诺/解释/疑问/警告/陈述，handover §4.6）——随机消费下语气会无差别套在任何正文上（T25 P1-4 ≥3/8 错配），本项=让用户「听到错配是什么」的建账项，不判 pass/fail | 消费端 `pick_ref_audio`（`random.choice` 无内容入参=T25）；ASR 参考文本与音频不齐会污染音色（`.tsv` 是校对前错文本**勿照抄**=T24 #10） |

**阶段 R · 须真机 QQ + 须提权重启（项数以本阶段表行为准；凡「听到声音」判据〔播声依赖 T32〕；改 .env 项标〔动 .env〕〔二次重启〕）**

通用取证基座：stdout 重定向落 `ChatBot_Runtime/logs/nonebot.out.log`（P-6）；TTS 匹配器命中计数=`grep -c "lineno=<注册行>" nonebot.out.log`（NoneBot 自打 `handled by Matcher(... lineno=…)`，判据=T21 §3；注册行以重启时代码为准：T36 快照=6116→T76 2026-09-20 复核=`__init__.py:6131`，T73 hook 化在飞会再漂——重启后 `grep -n "tts = on_message" plugins/bot_unified_runtime/__init__.py` 取现值）。

须用户本人做的动作（AI 一律不代做，T36 §6）：起引擎/关窗停引擎（E 阶段项）；netstat 绑定核对（E1）；提权重启+stdout 重定向（R 阶段项）；`.env` 改动与还原（R6/R7/R9/R10）；**耳朵终审**（音色/括号动作/清晰度）；QQ 发消息与截图；提供 black/white 群号实况（R16）；M-02/M-03 修复立项裁决（O7/O8→R13/R14）；T32 结论回收（9 个播声项）。

| # | 验收项 | 怎么触发（可粘贴） | 预期（过/不过判据） | 不过时看哪里 |
|---|---|---|---|---|
| R1 | 命令式合成成功（旧①）【须真机 QQ】【须提权重启】〔播声依赖 T32〕 | 私聊发：`说 今天的潮汐很安静` | **过**=①只收到**一条语音条**（无文字无标题）；②`data/tts_output/` 新增 wav 且 ffprobe `32000Hz mono`、时长≈3.7~4.3s（9 字×0.411s/字+0.3s 段尾，T25 实推）；③stdout lineno 计数 +1；④（若可播）内容=原句；**不过**=回文字（→R5/R6/R7 归因）、无回执（计数 +0=路由没进；+1 无出站=出站断）、语音条纯静音（→R15）、双语音（判不过=旧⑫真机半） | 主判据=文案本身+产物+lineno 计数；`tts request failed/rejected` 类 stdout 行**仅 P-6 重定向后存在**（tts logger 不在 nonebot 树、INFO 级，生产必丢=T14 P1-1）；`_last_failure_reason` 无状态查询口（仅降级文案瞬间可见）；**不要查 runtime_events.log（结构性无 bot.tts，P-7）** |
| R2 | 触发词 16 词等价（旧②扩面=T70+T92 繁體收口 ff091dc）【须真机 QQ】【须提权重启】〔播声依赖 T32〕 | 依次私聊发：`语音合成 你好` / `语音 我在这里` / `念 我在这里` / `朗读 我在这里` / `tts hello` / `say hello` / `shuo 你好` / `yuyin 你好` / `nian 你好` / `langdu 你好`（「说」已由 R1/R3 覆盖） | **过**=各条行为同 R1（正文=触发词后剥边界字符的剩余；英文大小写不敏感）；**不过**=某条走 chat→该词不在 `DEFAULT_TRIGGER_WORDS`（16 词=语音合成/朗读/语音/念/说+tts/say/shuo/yuyin/nian/langdu+繁體 說/語音/唸/朗讀/語音合成；T76 2026-09-20 复核+T92 ff091dc 繁體登记在位）或第二字符非标点/空白；`BOT_TTS_TRIGGER_WORDS` 为**追加合并**语义（与内置 16 词合并去重、非整表替换，唯一入口 `effective_trigger_words`=T70）。**已知边界（不判不过）**：繁體触发词已登记（說/語音/唸/朗讀/語音合成 5 词=ff091dc/T92 §一：繁體正文原样合成不简转、繁體日常句负样本零劫持）；边界集=纯标点空白后 `说你好`（无空格）**不触发**属现行设计 | `extract_tts_text`（最长优先+边界集）；口径同源=`docs/route-matrix.md` §2 tts 行与 `COMMANDS.md`「语音」行（T70 已同步版；16 词口径以 tts.py `DEFAULT_TRIGGER_WORDS` 为准——含繁體 5 词=ff091dc，route-matrix/COMMANDS 繁體面同步在飞） |
| R3 | 裸触发词人格回应（旧③**预期反转**）【须真机 QQ】【须提权重启】 | 只私聊发一个字：`说` | **过**=收到守岸人的**人格聊天文字回复**（正常聊天，无引导话术、无语音）；**不过**=收到「在「说」后面接上…」引导（该分支生产不可达，出现=路由语义变更须另立评审）或收到语音 | 路由门 `tts_match`→`is_tts_command`（等价 `extract_tts_text` 非空）；口径同源=config-catalog「裸触发词交回人格对话」+COMMANDS.md「裸触发词不占路由」（U-15 a 案=T70） |
| R4 | 负样本句组真机抽查·M-01（**新增**）【须真机 QQ】【须提权重启】 | 私聊逐句发（每句独立一条）：`说了再见`、`说了一半就停了`、`说的对`、`语音哈喽`、`说了多少遍了`；群聊（非黑名单群）**@守岸人** 发：`@守岸人 说了再见`、`@守岸人 念了一遍还是记不住` | **过**=每一句都收到**正常人格聊天文字回复**，无私了语音、无「嗓子还没接上」故障文案、**无单字残片语音（「对」「喽」「吧」=T15 四单字形态，听到任一即不合格）**；**不过**=任一句被吞聊天（私聊收到残片语音或故障文案；群里没人 @ 它插话）。**修前预期=全红（T15 201/278 实锤）**；离线预检 O1 已绿（T76 实跑），真机半在重启窗口执行 | 离线先行判据 O1；分母=`grep -c "event=incoming_event" runtime_events.log`、分子=stdout lineno 计数（劫持句不该进）；根因修复归属=T15 中央化修复点（六处副本收编状态见 O1 锚点行） |
| R5 | 引擎未启动降级+退避真闸（旧⑤改写=T57 落地）【须真机 QQ】【须提权重启】（**本项恰在引擎没起时做**） | 确认 9880 无监听（`netstat -ano \| findstr :9880` 空）→ 私聊发 `说 测试一下`；**30 秒内**再发同一句；隔 >30s（窗满）再发一次 | **过**=①首发**即时（秒级）**收到「嗓子还没接上——语音服务好像没在跑，稍后再叫我一次吧。」且聊天链一切正常（fail-open）；②窗内第二发**不真打引擎**（引擎侧无新请求痕迹）、秒级返回降级文案——退避 reason 固定以「服务不可达」开头（`服务不可达：退避冷却中（剩 N 秒）｜上次失败：…`）经 `_FAILURE_KINDS` 前缀映射挂 `tts_service_unreachable`（可重试）、`_degrade` 按含「不可达」选 unreachable 分支文案（T57 承重契约）；③窗满第三发恢复真打（再收降级文案=窗自动放行，非永久拉黑）；**不过**=首发卡 ~60s 才回（loopback 拒绝本应即时，卡满=引擎在监听但挂起，按「引擎活着但慢」排障）、窗内每发都等完整 HTTP 超时（=退避闸未接线回归）、或文字链同时被打断（违反 fail-open） | 闸=`tts.py` `_record_failure/_clear_failure/_backoff_reason`，常量 `_HEALTH_BACKOFF_SECONDS=30.0`（T57 落地；闸在 synthesize 唯一 HTTP 入口前、**缓存查找之后**=命中不受影响）；真成功 `_clear_failure()` 清零、快速失败**不刷新**窗（防永久拉黑）；查闸与打请求之间不原子（窗沿并发前几请求可能真打=T57 已声明取舍）；离线锁 `tests/test_tts_health_backoff.py`（4 例，T76 实跑绿）。**旧指引「查 `_HEALTH_BACKOFF_SECONDS` 死变量」作废——该常量现为真闸**。诚实注记：引擎完全没起时首尾两发都秒级（loopback 拒绝即时），闸的分辨力在「引擎监听但挂起」形态下最明显；群聊失败降级=中央 A-19 降级池非私聊文案（S8 裁定=T70） |
| R6 | 参考音频越界降级文案 bot 面（旧⑥改写）【须真机 QQ】【须提权重启】【动 .env】【二次重启】 | `.env` 备份后，把 `BOT_TTS_REF_AUDIOS` **整表替换**为仅一条 >10s 越界条目（格式仍 `路径|文本|zh`；勿「追加」——随机池下只有 1/N 概率命中坏条）→ 重启 → 私聊发 `说 测试` | **过**=收到「还差一段合适的参考音频：3 到 10 秒的干声，我才能借到自己的音色。」（`_degrade` 参考音频分支命中；判据串靠 `3~10秒` 简繁同形侥幸命中=已知脆弱 T2 P2-2）。⚠️ **本次 400 计入 30s 退避窗（T57：`_request_tts` 失败写点收编 `_record_failure`）——窗内重发只会收到 unreachable 分支文案（「嗓子还没接上」），这不是回归；判据取窗内第一发，重测前等窗满或重启**；**不过**=首发即泛化「这次没能发出声音…」=错误体顺序回归（先跑 O5 区分层）；自动配音路径同错**静默无提示**属现状（T7 P2-5），如实记不判 fail | 引擎面先行隔离变量→E4；`_degrade` 三分支（:747-750 一带）；测完恢复 .env 备份再重启 |
| R7 | 缺参考音频降级（旧④）【须真机 QQ】【须提权重启】【动 .env】【二次重启】 | `.env` 置 `BOT_TTS_REF_AUDIOS=[]` → 重启 → `说 测试`；再把某条路径改错（池非空但文件缺）→ 重启 → 再发 | **过**=空池收到可读引导「还没有给我配参考音频。请在 BOT_TTS_REF_AUDIOS 里填一条…」；路径错收到「配置里的参考音频文件都找不到——检查…」——**两文案分支都要见到**（`_no_ref_audio_hint` 双分支；空池分支不发 HTTP、不进退避窗）；**不过**=抛异常/无响应 | `_no_ref_audio_hint`（:753-762 一带）；离线两例在 `tests/test_tts.py`；⚠️ 本项与 R6 各烧一次重启窗口，**排最后**；R6/R7 已过可裁决豁免（用户） |
| R8 | 缓存身份 v2+同句恒同音色（旧⑦改写）【须真机 QQ】【须提权重启】 | 同一进程存活期内连发两次 `说 今天的潮汐很安静`；再（别的重启窗口）发同一句，对新旧产物各存副本+md5、ffprobe+耳朵比对音色 | **过**=①同进程第二次**主观更快**、`tts_output/` **文件名不变不新增**（缓存命中；M-09 闸在缓存查找之后=命中不受退避影响）；②重启后同句：**再付一次完整合成属预期**（缓存仅进程内存不落盘）；缓存键=身份 v2（identity_version=2+api_url rstrip 归一+ref 指纹 sha256[:16]+stat 快路径+preset 身份+参数快照=T57/T61）⇒ **文件名与升级前存量不同（旧键 wav 全成孤儿，磁盘不清理；回收靠 `bot_tts_cache_max_bytes/max_age_days` 配额键，缺省 0/0=关=T61 U-04）**；③重启后同句再合成=**音色与之前相同**（seed 确定性派生，「同句恒同音色」=G2-R3 已裁语义变更、波末报备在案=manifest §五.1）；**不过**=同进程第二次落**新**文件（查 `BOT_TTS_CACHE_ENABLED`）；重启后同句音色变了=seed 确定性回归 | 命中/未命中无观测口（T14 债），本项只判文件面+耳朵；「同音色」以耳朵终审为准（T61 承诺同音色、不承诺字节恒等——md5 仅旁证） |
| R9 | 自动配音总闸+ALWAYS（旧⑧）【须真机 QQ】【须提权重启】【动 .env】【二次重启】 | `.env`：`BOT_TTS_AUTO_REPLY_ENABLED=true` + `BOT_TTS_AUTO_REPLY_ALWAYS=true` → 重启 → 私聊随便聊两句 | **过**=每条人格回复**同时**带一条语音条+文字并存；**不过**=完全不带（查 SCOPE 是否 private 而你在群里测/`BOT_TTS_ENABLED` 关）；**ALWAYS 是调试旁路绝不留过夜**（catalog 自警），测完改回 false+ENABLED=false 再重启（第 2 次） | 挂点链=`__init__.py:341/:356` `should_voice_reply` 短路→`maybe_attach_voice`（行号以重启代码为准，T73 hook 化在飞〔T73 在建，默认关=现链不变〕）；自动路径失败**用户侧零提示**、只 stdout（且要 P-6）；文字面零污染是既有契约（T7 正面 5） |
| R10 | 概率门真机统计（旧⑨改写）【须真机 QQ】【须提权重启】【动 .env】 | 同 R9 重启基础上 `ALWAYS=false`、`PROBABILITY=0.05` 私聊连发 30~40 条 | **过**=**0~3 条带语音都属正常**（30 条零命中概率≈21.5%=T7 P3-2.3；旧「一条都不带→查 PROBABILITY=0」指引**作废**）；**不过**=≥6 条带语音（查 `always` 误开/门短路——离线半先跑 O3）；「重发同一条结果恒定」半句已删（QQ 无重投同一 message_id 手段=T7 P2-3） | 概率=哈希门 `should_voice_reply`；「为什么这条没配」**无观测口**（门判否零留痕=T14 P1-3），只能统计不能归因 |
| R11 | 会话范围最小面（旧⑪改写）【须真机 QQ】【须提权重启】 | 生产缺省（SCOPE=private+自动配音开=R9 态）时**在群里聊天** | **过**=群聊一律不配音（private 拒群）；私聊全配=R9 已证 private 面；**不过**=群里冒出配音 | `auto_reply_scope_allows`；六格矩阵离线锁 `tests/test_tts.py:754 test_auto_reply_scope_allows_matrix` 在位——全形态跑完要 2-3 次重启，性价比判：离线锁+本 1 格真机即够，group/all 两面=裁决豁免候选 |
| R12 | 长度截断+硬顶+时长预算（旧⑬改写）〔播声依赖 T32〕〔T75 增量待落〕【须真机 QQ】【须提权重启】 | ①发 `说 <250 字带句末标点的话>`；②再发 `说 <230 字全程无任何标点和空格的话>`；③发 `说 <一段 >2000 字的话>` | **过**=①有标点→回看窗内句末标点处收尾（听感完整句止）；②无标点→硬切 200 字（`_truncate_at_sentence` 40 字回看窗内无标点即硬切——旧「按句末截断」是过强承诺）；③超硬顶 `bot_tts_hard_max_chars=2000` → **拒绝合成+可读引导文案、不拆条**，audit 记 `over_hard_cap`（T61/G2-R3）；产物字节超 `bot_tts_max_audio_bytes=8MiB` 同拒（8MiB≈131s 覆盖现 200 字档≈82s 留 50% 余量=manifest G2-R3）；时长预算：200 字≈80~90s 量级（T25 外推±15%）；清洗后为空（纯链接/代码）→纯文字发出不合成；`BOT_TTS_MAX_CHARS=0` 语义=**不限字数**（反转已修死=T61 M-35），但硬顶 2000 仍拦（0=不限≠无界=G-R-M1）；**不过**=念出超 200 字的全部内容、超顶仍合成出货、清洗空仍硬合成报错；截断可观测化增量〔T75 待落〕不写死 | `clean_for_speech`+`max_chars`（命令式 200/自动 120 **两阈值并存**=T25 P2-3，先认清发的哪条路）；⚠️ QQ 语音条时长上限与超限表现=**T32 判**，本项只量 wav 落盘时长 |
| R13 | 打码真机·M-03（**新增**）〔播声依赖 T32〕【须真机 QQ】【须提权重启】 | 私聊发：`说 我的密钥是 sk-TESTFAKE0123456 本机路径 <假盘符路径·整句原串见附录 A2 围栏块> 配置写着 BOT_SUPER_ADMIN_API_KEY=FAKEVAL123`（**全假值**，纪律：勿碰真凭据） | **修前预期=不合格（如实登记）**：语音里**听到** sk 串字母/盘符念出、`tts_output/` 新 wav 内容含该段、文字面反而不出（对照：同句走 chat 会被打码）——三者任一即红，录音+ffprobe+stdout 全量 grep `sk-TESTFAKE` 留证；**修后过判据**=①语音不含该类内容（拒合成或念打码占位）②stdout/事件日志零明文。**别写成一个永远绿的项** | 修前根因链=`clean_for_speech` 前无 `redact_local_secrets`（T9 P0-3+O7 实跑）；文字侧对照行为=chat.py 打码（`plain_text.py:340`）；顺序陷阱：先清洗会把 `BOT_` 形态吃坏→修后必核 O7 判据 |
| R14 | 红线真机·M-02（**新增**；修前不建议真机触发）〔T75 待落〕【须真机 QQ】【须提权重启】 | **修后**在私聊对含未成年红线信号的句子发 `说 <该句>`；群内（非白名单群）同做一例 | **修前**：真机**预期=能播出违规语音且 wav 常驻**（危险立案项，QQ 主动触发不建议；以 O8 离线红为证据载体）；**修后过判据**=语音不合成、收到与文字侧一致的边界话术、`tts_output/` 无新增文件；**不过**=任一环节出声/落盘。⚠️ 旧违规产物清理归 T9 P2-1（「运行数据不可删」规程叠加，用户裁），验收只登记不处置 | 修前可达链=matcher priority 41 block=True→门禁对命令句放行（gate.py 无内容判定）→`tts.py` 零内容闸；群侧现状按 **T27 矩阵**（非黑名单群未 @ 也开火；黑名单群全静默属设计）；语音群门与 `explicit_allowed_for_session` 不同源——M-17 中央同源〔T75 待落〕，落地后本项判据以其披露表为准 |
| R15 | 静音毒语音闸（**新增**=T61 M-07 已落）〔播声依赖 T32〕【须真机 QQ】【须提权重启】 | 引擎在跑时执行 R1；对收到的语音条：听+对当次新增产物 `ffprobe -show_entries format=duration`；若引擎窗口出现推理异常，对齐观察 bot 侧行为 | **过**=①正常形态：时长与字数折算相称（R1 量级）、正常出声**零误杀**（三指纹闸对有声/短夹具/非 1s 全过=T61 用例锁）；②毒形态：引擎返 200+**恰 1s 静音 wav**（16000Hz + 0.9~1.1s + 峰值≤2 近全零，三指纹**同中**才判）→ bot 判**失败**：不落盘、不入缓存、不出站（走降级面）——**旧「静音被当成功发送并毒化缓存」形态被闸住**；**不过**=毒形态仍收到语音条/落盘=闸未接线回归；⚠️ 已知边界（如实记不判 fail）：不满足三指纹的静音形态（如 32000Hz 静音、非 1s 静音）仍会通过——域值=T53 引擎陷阱实测值，扩域属规格变更 | 闸=`tts.py` `_inspect_wav_bytes` 静音指纹（`_SILENCE_RATE=16000` 等常量，T61 M-07）；引擎兜底=`$DEV_ROOT\GPT-SoVITS-V2Pro\GPT_SoVITS\TTS_infer_pack\TTS.py` yield 静音段；`/bot status` 与事件日志**都看不见**毒形态（T14 全绿假象链），只能靠耳朵+ffprobe |
| R16 | 出站现状记录：群命令/黑名单/安静时间（旧⑭真机半+**新增现状观察**）〔播声依赖 T32〕【须真机 QQ】【须提权重启】 | 三连观察，逐项记录（现状登记≠政策裁定）：①非黑名单群**未 @** 发 `说 测试`；②若用户可提供 black1/black2 群：同句发一条；③安静时间窗内私聊发 `说 测试` | **过（=记录与 T27 矩阵一致）**：①收到语音或降级文案（命令逃逸：门禁把 TTS 句当确定性命令，未 @ 也回——现状）；②black 群**完全静默**（回执被 `_record_receipt_safely` 抹空）；③安静时间照回（`direct_request_bypass`：capability_id 不在 {bot.chat,bot.content} 集合）；失败降级面：私聊=守岸人文案、**群内=中央 A-19 降级池**（S8 裁定，T70/COMMANDS 同口径）；**不过**=同一动作出现矩阵外第四形态（黑名单群出声/安静时间被拦=代码变了，先核坐标再归因）。**任何格不得引用 `BOT_GROUP_MESSAGE_POLICY`（幽灵键：全仓零消费=T27 P3-27b）** | 群终态权威=T27 二十格矩阵；black/white 名单实值自查 `bot_group_black1/black2/white1/2`；真身路径=`domains/chat_reply/policy/gate.py`（命令判定 :252-257 一带）与 `domains/chat_reply/policy/quiet_hours.py`（:120-124 一带）——旧径 `policy/*.py` 均为垫片；R4 修复合入后重跑本项，「未 @ 日常句开火」格应随劫持修复自然收窄 |

**旧版项 → 新版项映射**（保留｜改写〔含迁离线〕｜删除——被删的是失效信号引用｜新增，各目计数以本映射表逐行为准）：

| 旧项 | 处置 | 去向 |
|---|---|---|
| ① 命令式成功 | 保留（排障列换血） | R1（+R15 静音闸） |
| ② 触发词等价 | 保留扩面 | R2（16 词∪追加=T70+T92/ff091dc） |
| ③ 裸触发词引导 | 改写（预期反转+拆离线锚） | O2 + R3 |
| ④ 缺参考音频 | 保留 | R7 |
| ⑤ 服务未启动 | 改写（T57 退避真闸判据） | R5 |
| ⑥ 越界错误透传 | 改写拆三层 | O5 + E4 + R6 |
| ⑦ 结果缓存 | 改写（身份 v2+seed 确定性） | R8 |
| ⑧ 自动配音总闸 | 保留 | R9 |
| ⑨ 概率门 | 改写（0~3 条正常） | O3 + R10 |
| ⑩ 概率门确定性 | 迁离线 | O3 |
| ⑪ 会话范围 | 保留最小面 | R11 |
| ⑫ 已有音频不叠加 | 迁离线（真机半=单条语音） | O4 + R1 |
| ⑬ 长度上限 | 改写（硬顶/0=不限/两形态） | R12 |
| ⑭ 出站链路 | 改写拆形状锁/真机记录（可播性归 T32） | O6 + R16 |
| —— | **新增 ×13** | O1·O7/O8·E1-E6·R4·R13/R14·R15 |

**无效信号处置**（旧判据为什么不能再引用）：
- 旧①⑥异常列「日志 `tts request rejected`」——tts logger 不在 nonebot 树+INFO 级，生产必丢（T14 P1-1）：**删**；主判据=文案+产物+lineno 计数，stdout 行仅 P-6 重定向后可查。
- 旧⑤异常列「查 `_HEALTH_BACKOFF_SECONDS`（死变量）」——T57 已接成真闸：指引改为 R5 新行为（30s 窗/快速失败/真成功清零）。
- 旧前置②「裸敲 `/GPT-SoVITS-V2Pro/api_v2.py`+空测」——错 CWD 静默回退底模+yaml 写回永久化（T2 P1-2）：改为 P-2/P-3。
- 「离线复核手段 67 例全绿」旧口径——期望值过期+被读成「配置也被复核过」=假安心（T24 #11）：改为不写固定用例数+显式声明离线不覆盖面（见下）。
- `verify_chatbot_env.py`：旧判据指仓外件（`$DEV_ROOT\...\tools\`，import 即崩=T24 P1-1）**维持不引用**；配置面体检改走仓内重建版 `scripts/verify_chatbot_env.py`（`7e2fe36`=T87，生产 Config 真身判据、零裸 assert）；引擎面音色体检仍=pre_restart_check 第 10 项（T60）——两者分工零重叠（工具头注自述）。
- 群侧任何对 `BOT_GROUP_MESSAGE_POLICY/_ALLOW_MODE` 的依赖——幽灵键全仓零消费（T27 P3-27b）：R16 明文禁用。

> **探针附录**（全文可粘贴，均落 `$TEMP/t76/`，不落源码树；A1-A4 源=T36 §7）：
> **A1=O1 负样本探针**：`sys.path.insert(0,".")` 后 `Config.model_validate({"bot_tts_enabled": True})` + `classify_message_route`，负样本 10 句=`说了再见/说了一半就停了/说的对/语音哈喽/念了一遍还是记不住/朗读了三遍/说了多少遍了/语音了半天没接通/说了吧/说的我脸都红了`，过=全 `RouteKind.CHAT`。扩充语料回灌源=T15 报告 §逐条误伤表（201 句）。
> **A2=O7 打码探针**：以紧邻下方围栏块内整句原串喂 `clean_for_speech`（raw 串）→ 修前三判据全中=红在位；`tts.py` 源 grep `redact`=0。
```text
我的密钥是 sk-TESTFAKE0123456 本机路径 C:\FakeTest\secrets.env 配置写着 BOT_SUPER_ADMIN_API_KEY=FAKEVAL123 请念
```
> **A3=O8 红线探针**：同一含未成年信号（无害构造）句子分别 `assess_public_content(text, session_type="private")`（期望 refuse）与 `build_tts_capability(cfg)+monkeypatch(_request_tts)+capability(msg)`（修前期望：audio dict+临时 wav 存在；修后期望：不合成+边界话术）。判据以 T9 报告文本为准。
> **A4=E3/E4/E5 试听生成器**：
> `curl -G "http://127.0.0.1:9880/tts" --data-urlencode "text=今天的潮汐很安静" --data-urlencode "text_lang=zh" --data-urlencode "ref_audio_path=$DEV_ROOT/GPT-SoVITS-V2Pro/refs/shorekeeper_ref_01.flac" --data-urlencode "prompt_text=<该条参考文本逐字>" --data-urlencode "prompt_lang=zh" -o "$TEMP/t76-evidence/e3.wav" && ffprobe -hide_banner "$TEMP/t76-evidence/e3.wav" 2>&1 | tail -3`
> 过判据：200 + `pcm_s16le 32000 Hz mono`；E4 把 `ref_audio_path` 换 `corpus_durations.csv` 里 `duration_s>10` 条目→期望 400 含 `3~10秒`；E5 把 `text` 换 `（微微一笑）今天的海风很温柔，你想我了么？`。`text_lang/prompt_lang` 必带。

> **离线复核手段**（真机存疑时；用例数一律以实跑末行为准，不在文档手写）：`"$PY" -m pytest tests/test_tts.py tests/test_tts_audio_gate.py tests/test_tts_outbound_chain.py tests/test_tts_health_backoff.py tests/test_tts_cache_identity.py tests/test_tts_presets.py tests/test_tts_contract_layer.py tests/test_tts_hijack_guard.py tests/test_tts_failure_visibility.py tests/test_tts_speech_gate.py tests/test_text_boundary_central.py tests/test_tts_corpus_gate.py -q -p no:cacheprovider --basetemp="$TEMP/t76/pt"`。本席（T76）2026-09-20 实跑抽检两批 **216 passed / 0 failed**（O 相引用节点 93 + 四件 123）；T136 增补 `tests/test_tts_corpus_gate.py`（+5 passed/3 xfailed 环境相关，2026-09-20 实跑；语料门判据见 P-4）。**证明力边界（显式声明）**：离线手段**不覆盖** `.env` 实值、引擎行为、音频时长/音色/可播性（T32）、QQ 出站——这些只能走 E/R 相。
> **参考音频池**：已落盘若干条（`$DEV_ROOT\GPT-SoVITS-V2Pro\refs\shorekeeper_ref_01..08.flac`，48000Hz 单声道——这是**参考音频**率，合成产物是 32000Hz，两率勿混读=T25 §5）。扩池合规面按 T24 修正口径（全库合规 289 条/甜点区 117 条，旧 291/118 为虚增）。扩池/建账工具链（T136 登记=T106 收编件，逐字节副本+溯源块+原件 sha256 双向防漂移锚）=`scripts/tts_corpus/`：`scan_durations.py`（时长普查→corpus_durations.csv；已知缺陷原样保留：无字节去重=291/118 虚增口径出处、probe 全失败仍 exit 0）/`pick_refs.py`/`make_listening_checklist.py`/`transcribe_refs.py`（ASR tsv 生成——**粘贴块零防护勿照抄进 .env**，反向毒化门拦截面见 P-4）；冒烟门=`tests/test_tts_corpus_tools.py`（含 4 项引擎原件 sha256 双向防漂移实锚；引擎目录缺失按 skipif SKIP 不假红；用例数以实跑末行为准，2026-09-20 T136 实跑 18 passed）。
> **收尾纪律**：全部通过后在本节打勾回写，并按台账规矩在 AGENTS.md 记重启生效（tts 链路在主进程）；任一项不符按 §6.6 收尾纪律走 systematic-debugging；「修前预期=红」项（O7/O8/R13/R14 修前半）在修复立项施工前**保持红态登记**，不得粉饰。

### 6.6.12 紧急信息域接线验收（WIRE 波 A 段+B1/B3 + WIRE-SUB 订阅面，2026-09-20/21；重启生效）

> **前置**：本节各项**只有**在 WIRE-B3 装配半边（根 `__init__.py` 四处 + 采集调度器）与 WIRE-C1 生成物集中重录收口、且用户提权重启 bot 之后才可真机验收；书写时点本波状态=「代码+测试完成，未 commit，重启生效」。波次全录=`.superpowers/sdd/emergency-info-registration-runbook-20260920/`，施工图权威=`docs/design/emergency-info-registration-runbook-20260920.md`（§6.3 十一为本节母本；其 §4-面0 正则 `\b?` 形态已作废，真身=`domains/emergency_info/capabilities/emergency_info.py:52`）。

**重启前置体检（离线）**
- [ ] 四件合跑：`PYTHONDONTWRITEBYTECODE=1 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_emergency_info_core.py tests/test_emergency_info_push.py tests/test_emergency_info_review_gate.py tests/test_emergency_info_sources.py -p no:cacheprovider --basetemp="$TEMP/6612" -q`——基线（WIRE-D1 席 2026-09-20 15:3x 实跑）= **237 passed / 1 failed / 1 xfailed**；唯一红 `test_emergency_info_double_pin_is_registered_as_pending` 是计划内半接线探测器，**B3 装配后应摘牌转绿**；B3 后仍红=路由双钉没接全，停下走 systematic-debugging。
- [ ] 七件合跑参照（R-A2-1 收口态）= **329 passed / 1 xfailed / 0 failed**（含 `test_outbound_gate.py`+`test_emergency_info_review_gate.py`+core 族）。
- [ ] 生成物 `--check` 三件的紧急信息域条目在位（command-catalog topic=紧急信息 / auto-facts 字段数 / render_hashes 与本域无关则零变化）；C1 重录前他域红按 B1 六红归属表对号，**不得把本波红混进他席账**。
- [ ] `.env` 装配门按需配置（逐键含义见 `docs/config-catalog-full.md` 紧急信息节；**值不落本文档**）：`BOT_EMERGENCY_INFO_ENABLED`（缺省 false=整链不注册）+ `BOT_EMERGENCY_INFO_SOURCES`（两腿，缺一不装配）。**2026-09-20 WIRE-SUB 裁定 3.B**：旧第三腿（推送名单非空）已撤，投递目标改由群内/私聊订阅命令落库、每轮现读（用法与语法见 `docs/design/emergency-info-enablement-20260920.md` §七）；两枚 `PUSH_*` 降级为可选硬推腿（不受订阅过滤）。`BOT_EMERGENCY_INFO_AUTO_APPROVE_SOURCES` 缺省空=**全部人工 PENDING**（D-8(a) 真关死，V1b 注毒实证）；`BOT_EMERGENCY_INFO_REVIEWER_IDS` 定审核权归属。

**真机项（bot 提权重启 + 白名单会话实弹后逐条打勾）**

| # | 动作 | 预期 | 依据 |
|---|---|---|---|
| E1 | 发 `紧急信息 <事件描述>`（或 `预警`/`地震`/`emergency` 正样本，繁體 `緊急信息`/`預警` 同触发） | 能力命中回执；人工报料入库 PENDING，**不发推送** | 能力层 :170 / V1b 四探针 |
| E2 | 发 `emergencyxxx`、`emergency1`、裸聊天句含"紧急"但非触发形 | 一律**不命中**、零打扰；词边界门 G23 | `_EMERGENCY_RE:52` 形态锁 |
| E3 | 管理员 `/bot help 紧急信息`；非管理员同令 | 管理员=深度卡（aliases：紧急信息/预警/地震/震情/待审/emergency/緊急信息/預警）；非管理员=无此 topic（admin_only=True，U-3） | echo :2217/:2219 |
| E4 | 权威源（`AUTO_APPROVE_SOURCES` 白名单内采集通道）产出一条 | 落库即 APPROVED、`authorizer=auto:authoritative_source`；白名单外来源同内容仍 PENDING——两态同场可比 | review.py :79/:86 |
| E5 | `紧急信息 待审` 列表；`紧急信息 审核 <id> 通过` | 列表仅 PENDING 项；审核指令仅 `REVIEWER_IDS` 名单内可动，名单外拒绝话术；通过后 `level` 仍必经定级 `publishable_level()`（未定级不发布） | 审核族 17 锁 |
| E6 | 发布一条 ≥`MIN_LEVEL` 的已审条目 | **已订阅且条件对得上的目标**收到投递（守岸人话术）；未订阅会话、订阅条件不匹配的群**零推送**；同日 dedupe 生效；`PUSH_*` 硬推腿（若在配）收全部过门槛条目 | push.py + matches_subscription + SendQueue |
| E7 | 查投递审计 | 主动投递全部经 outbound_gate→`submit_active_push` 单触点；根 `__init__.py` 全文无 `submit_active_push` 字样（T6 门常绿可离线 grep 复跑） | 钉死③/R-S5 |
| E8 | 缺省态反证：`BOT_EMERGENCY_INFO_ENABLED` 不设（或 SOURCES 空），重启 | 整链不注册、任何触发词零反应、`/bot status` 无该域异常 | 装配门两腿缺省关 |
| E9 | 群内群主/管理员发 `紧急信息 订阅 area=<本市> kinds=<该警情>` | 回显"已经记下了，本群的紧急信息订阅：…"，条件逐项列出；普通成员同令=拒收话术且**不落库** | 裁定 2/6 + 权限族锁 |
| E10 | 紧接着（不重启）等一条对得上的预警进来 | **当轮就投**（这证的是"不必重启"）；`紧急信息 订阅 看` 的累计命中数 +1 | 现读锁 + e2e 用例族 |
| E11 | 发 `紧急信息 订阅 area=<不认得的县>`；再发 `紧急信息 退订` | 前者当场报错并给相近候选、不写库；后者回"已经退掉了"，此后该群零推送 | RuleError+candidates / delete 锁 |
| E12 | 非 QQ 会话（如 TG）发订阅命令 | 明确告知"订阅目前只能在 QQ 这边设"，**不写库**（防同号不同平台误投） | 平台门 + 变异锁 m7 |

> **离线复核手段**（真机存疑时；用例数以实跑末行为准，不在文档手写）：上列八件合跑（含 `tests/test_emergency_info_subscriptions.py` 与 `tests/test_outbound_gate.py`）；域内符号锚点现读现定（`grep -n "_EMERGENCY_RE\|AUTO_APPROVED_BY\|matches_subscription" plugins/bot_unified_runtime/domains/emergency_info -r`）。
> **诚实边界**：离线锁证"触点存在且唯一引用闸"，`test_emergency_info_subscriptions.py` 的端到端 job 用例进一步证"订阅条件真的决定了投给谁"（2026-09-21 就是这一族抓到 `item_id` 含 `:` 让每一条真实条目在拼幂等键时抛 ValueError、被兜底 except 吞成一行日志、**一条都投不出去**）——但两者都不证"QQ 那头真的收到了"，后者只有 E6/E9-E10 真机实弹能证。任何"已生效"宣称一律按未完成记账（铁律：改代码必须重启才生效）。
> **收尾纪律**：全部通过后在本节打勾回写，并按台账规矩在 AGENTS.md 记重启生效；任一项不符走 systematic-debugging，「B3 前预期红」项（探测器 #6）在 B3 施工前**保持红态登记**，不得粉饰。

### 6.6.13 中央执行层通电 + 主动投递唯一出口验收（2026-09-21/22 统一波；重启生效）

> **本节性质（先读这一句）**：本波改动**全部只在离线 mock 下验过**。下面每一项写的都是「线上重启后要亲眼看什么」，不是「已经验过了什么」。凡本节出现「应当看到」，在亲眼看到之前一律记「未验」（工作区规则 5）。
> 波次全录=`.superpowers/sdd/2026-09-21-unify-wave/`，改动地图与门禁真值=`HANDOFF-FIXWAVE-20260921.md`；在册清单（哪条能力走中央、以什么形态）一律以真身声明为准：`domains/chat_reply/runtime/capability_registry.py::ROUTE_CAPABILITY_DECLARATIONS` 的 `execution` 面 + `plugins/bot_unified_runtime/runtime/capability_protocols.py::_creation_descriptors`，**总数现值看机器册 `docs/auto-facts.md`，本文不手写**。

> **前置**：
> **P-1（重启）** 提权重启，父 `venv\Scripts\python.exe bot.py` + 子 `python.exe bot.py` **两个都停**再起重启（§6.6.11 P-5 同规程），并把 stdout 重定向落 `ChatBot_Runtime/logs/nonebot.out.log`（否则本节「看日志」类判据全部不可证=§6.6.11 P-6）。
> **P-2（审计去哪儿看）** 中央执行审计写在 `__init__.py::_record_capability_audit`，落的是**审计库**（`AuditRecord`）。`BOT_AUDIT_LOG_FILE` 缺省为空 ⇒ 不额外落文本文件（`domains/ops/audit/file_logger.py::build_audit_with_file_log`：路径空=只写主库）。人话入口=在 QQ 私聊发 `/bot recent`（诊断+发送回执+审计三合一）。想要一份能 grep 的文本审计流，就在 `.env` 设 `BOT_AUDIT_LOG_FILE` 后**再重启一次**——本节 A1 有「不设键版」和「设键版」两条路，任选其一即可。
> **P-3（闸的现值）** 出站防风暴闸 `bot_outbound_gate_enabled` **缺省关**（真身 `config.py::Config.bot_outbound_gate_enabled`，生产 `.env` 现在连这一行都没有）。关着的形态=与改道前逐字节同形的直通（`domains/transport/sender/outbound_gate.py::submit_active_push`）。⇒ 本节 B-2/B-3 的「顺延/限流/键形/闸审计」四件事**今天在线上一件都不生效**，这是诚实缺口不是已完成项，开口动作见 `PENDING-RULINGS-20260922.md` 第 9 项（**开之前要先定每分钟限额**，现缺省 2 条/分·6 条/时）。
> **P-4（群/白名单）** A3 的群聊项要在常规群做；B-1 的群摘要要在群摘要白名单群、日常助理要在 `BOT_DAILY_ASSIST_PUSH_USER_IDS` 名单内的私聊做，名单空的族整链不注册（绝不猜人），那就记「本项无从验收」而不是「通过」。

**阶段 A · 中央执行层（层 2）通电观察**

| # | 验收项 | 怎么触发（QQ 里打什么） | 应当看到什么 | 若不对最先看哪里 |
|---|---|---|---|---|
| A1 | 每次中央执行**恰落一行**审计 | 私聊发 `天气 湘潭`（任意一条在册能力都行，见 P-2） | 回复正常出天气卡/文字；`/bot recent` 的审计段里，这一轮该能力**只有一行** `stage=capability_invoke`，事件形如 `invoke_ok`（成功）或 `invoke_<终态>`，且带 `principal=`、`via=`、`elapsed_ms=`、`detail=` 四段。**`via` 现在是实际跑的那个执行体的「模块.限定名」**（形如 `caller_capability:plugins.bot_unified_runtime...build_weather_capability.<locals>._handle`），不再是光秃秃一个「走了调用方」——这一条就是本轮改的观测面，看到旧写法=没重启成功 | 落**两行**=缝被套了两遍（幂等标记 `orchestrated_capability_id` 失效，`plugins/bot_unified_runtime/runtime/capability_protocols.py::orchestrated_command` 尾部）；**零行**=审计 sink 没挂上（`attach_default_audit_sink` 只此一个注册口，`__init__.py` 装配段）；`via` 里没有点号路径=该能力根本没走中央（回 A2 判形态） |
| A2 | prepared 形能力逐条走层 2 | 逐条私聊各发一次：`天气 湘潭`、`行情`、`英伟达股价`、`美元兑人民币`、`黄金`、`国债收益率`、`北向资金`、`史诗`、`菜谱`、`塔罗`（或 `八字`）、`紧急信息` | **过**=每条的回复与从前肉眼一致（同样的卡、同样的口径），**用户侧看不出任何变化**——这轮改的是执行通路不是话术；`/bot recent` 里每条各有一行 A1 那形审计。**若哪天某条只回一句「这会儿说不上话来，稍后再试一次吧。」**：先去看那一行审计的 `event=` 与 `detail=`（是被拒、超时、未接线，还是能力真崩），**不要重启了事**——这句温和短句本身就是层 2 拦下时的出口，重启只会把证据抹掉 | 中央拦下时**绝不静默丢回复**是硬要求；温和短句文案真身=`plugins/bot_unified_runtime/runtime/capability_protocols.py::orchestrated_command`；某条压根查不到审计行=它不在册（`ROUTE_CAPABILITY_DECLARATIONS` 无 `execution` 面），属未迁移而非坏 |
| A3 | 多入口同权（别名 / 自然语言 / 命令） | 同一个能力换三种说法各发一次：①命令 `天气 湘潭`；②昵称别名 `守岸人 天气 湘潭`；③自然语言 `湘潭天气怎么样`（群里也可，正常 @ 或不 @ 按现行群政策） | **过**=三种说法**行为一致**（同一张天气卡/同一口径文字），且**三种说法都各留下一行 A1 那形审计**——本轮最后一个 Critical 修的就是「别名与自然语言两条入口绕开中央治理」，只有命令一条有审计行=没修上 | 汇合点唯一=`__init__.py::_run_capability_through_pipeline`（三条入口在这一个地方包缝，包过一次不包两遍）；别名表真身=`build_command_alias_resolver`；自然语言问法真身=`domains/chat_reply/runtime/natural_language.py`（「今天天气不错」这类陈述句**不该**进天气，进了算误判） |
| A4 | 崩溃保真：真崩出诊断卡、被拒不发卡 | ①真崩面：平时碰不到，只能等它自己出现——**不要为了验收去制造异常**，出现时按下面判据认；②温和面：对被门禁/被拒的请求（例如非管理员发 `紧急信息 审核 1 通过`，§6.6.12 E5） | **真崩**=原始异常交回层 1，**错误诊断卡旁路照旧工作**（云母卡照发，与接入层 2 之前逐字同构）；**被拒/超限/未接线**=只出一句温和短句、**不出卡**（诊断卡不该被"没权限"这种正常判定刷屏） | 交回通路=`plugins/bot_unified_runtime/runtime/capability_protocols.py::orchestrated_command`（认 `INVOKER_ERROR_DATA_KEY` 后原样 `raise`）+ 卡片旁路 `domains/ops/monitor/error_report.py`；反向症状=真崩时只收到温和短句而日志里一行栈都没有 ⇒ 崩溃保真被吞，直接立案。**已知诚实缺口（登记不判 fail）**：能力「挂死」走的是超时终态、不抛异常，所以那一类**不会发卡**，只在审计里留痕（`PENDING-RULINGS-20260922.md` 第 10 项待裁） |

**阶段 B · 主动投递唯一出口（四条）**

| # | 验收项 | 怎么触发（QQ 里打什么） | 应当看到什么 | 若不对最先看哪里 |
|---|---|---|---|---|
| B1 | 四条主动投递**该到的还到** | ①提醒：私聊发 `10分钟后提醒我 喝水`，到点看是否收到；②群摘要：在白名单群等 21:30 那一轮（或当日已推过则记「今日已推，明日再看」）；③日常助理：名单内私聊等 09:00 早报 / 11:15 吃什么 / 21:00 晚报；④cookie 到期：到期报告到点自然来，**不人为造** | **过**=四条各自照旧送达（话术、时点、去重都与从前一致）。闸关着的时候「改了出口」这件事对用户必须是**零可感差异**——看到任何新的延迟、重复或消失，都算不过 | 四条的真身：提醒 `__init__.py::_deliver_due_reminders`、cookie 到期 `_deliver_cookie_expiry_report_via_queue`（两条共用 `_push_via_central_exit_now`，因为它们是「送达才销账」的内联投递）、群摘要 `_push_daily_group_digests`、日常助理 `_push_daily_assist_private`；紧急域那条另见 §6.6.12 E7 |
| B2 | 四条**不该重发的不重发** | 上面每条触发的同一轮里，只看**同一条内容是否出现两次**（提醒尤其容易看出来：到点应只有一句） | **过**=同一条提醒/摘要/早报各只收到一份；**不过**=双发 ⇒ 出口改道把幂等键搞坏了，立刻立案（这是本轮唯一能证「改道没改坏投递」的真机判据） | 队列幂等与回执真身=`domains/transport/sender/queue`（SendQueue）+ `receipt_repository.latest()` 投前查；提醒的 dedupe 键形如 `reminder:<id>`（在 `_deliver_due_reminders` 里现读） |
| B3 | **诚实缺口**：闸今天关着 ⇒ 防风暴四件事线上不生效 | 什么都不用打——这一项是**读**的，不是做的 | 现网**看不到**顺延、限流、键形核验、闸审计，这是**预期**，不是坏了。要验它们，先按 `PENDING-RULINGS-20260922.md` 第 9 项裁：A 继续关（推荐）/ B 全开 / C 只对紧急域开；**开之前先定每分钟限额**（现缺省 2 条/分·6 条/时，太紧会把摘要当晚直接压掉） | 闸设置投影真身=`domains/transport/sender/outbound_gate.py::build_outbound_gate_settings`；开闸后 B3 判据落到下面的 B4 去做 |
| B4 | （开闸后才有）提醒被限流=**顺延不销账** | 开闸状态下把提醒挤在同一分钟里连发多条（或直接把限额调到很低再触发），观察：①当轮少收、②下一分钟补收、③**绝不双发** | **过**=被拦下的提醒**当轮不销账**（`__init__.py::_push_via_central_exit_now` 返回 False ⇒ 记一条 `held by central outbound gate; kept for retry` 的 warning 日志并留待下一 tick），下一轮由队列幂等 + 投前回执收敛，**最终只收到一份、可能晚一点**；**不过**=①晚到又双发（幂等没收住）②晚到后干脆没了（被当成已送达销了账）③顺延没留日志 | 「送达才销账」的读点在 `_deliver_due_reminders` 内联投递分支；顺延语义的离线锁在本波测试族（用例数以实跑为准，不在此写死）；⚠ 静默窗（深夜不顺发）与限流是**两套判定**，深夜那条要先核对安静时间设置再归因 |

**阶段 C · 观测闭环与诚实不可用**

| # | 验收项 | 怎么触发（QQ 里打什么） | 应当看到什么 | 若不对最先看哪里 |
|---|---|---|---|---|
| C1 | 语音探针告警闭环（一条 issue 只报一次） | **两种情形各看一次**：①**引擎没起**（`netstat -ano \| findstr :9880` 为空）时私聊发 `/bot status`；②引擎在跑时再发一次 `/bot status` | **过**=①情形：`/bot status` 里语音那一行显示**异常态**（探针的结论现在有一个生产读者，不再「存在但永远没人看见」）；且**管理员私聊只收到一条**运维告警；②情形（引擎起好后第一次查询）：显示恢复，**此后不再重复刷同一条**——投出去就 drain，不是粘滞。**不过**=同一条 issue 每查一次刷一条（=没 drain），或者引擎明确挂了却始终一声不响（=告警口没接上/告警名单为空） | 读者真身=`domains/media/voice_health_alert.py::flush_probe_issue_to_alerts`（`last_operational_issue()` 的**全树唯一生产读者**，活性锁钉死），调用点=`domains/chat_reply/capabilities/echo.py`（`/bot status` 读侧）；装配口=`__init__.py` 的 `install_probe_alert_sink`；节流=**共用**中央那枚 300s 抑制器（`operational_alert_suppression`），**不另造第二道闸**；告警目标名单为空时静默不发（属现状，记「无从验收」）。⚠ 语音链路本体的 30 项判据在 §6.6.11，本节只看「诊断到没到运维眼前」这一条 |
| C2 | AI 绘画：只有协议腿，永远诚实不可用 | 什么都不用打（今天 QQ 里**没有**一条指令会走到绘画，也不该有）。要留证据就看两件事：①`/bot status` 与 `routes` 类诊断里 `creation.image.generate` 的健康态是**未配置**，不是「可用」；②任何未来接入的评审都按「拿不到图就明说拿不到」判 | **过**=它对用户永远不产出图、**永远不谎报成功**；原因串可读（`domains/creation/reserved_provider.py::reserved_availability_reason` 现文案：`AI 绘图对接点未接线（reserved：零现载体），诚实 unavailable，未知任务不重发`）。**不过**=哪天它「成功」了却没图，或者接了 provider 就把未知态重发（会真扣钱：`count≤2` 的一次请求可能已产生费用，见 `domains/creation/image/contracts.py`） | 在册描述符=`plugins/bot_unified_runtime/runtime/capability_protocols.py::_creation_descriptors`（`fallback_chain` 钉诚实降级、`health_default=NOT_CONFIGURED`）；**本项离线锚=`tests/test_creation_job_protocol.py` 与 `tests/test_creation_protocol_parity.py`（离线验过、线上待看）**；供应商要不要真接=`PENDING-RULINGS-20260922.md` 第 2/3 项待裁，**本节不代表它已接** |

> **本节不写「已验证」**：A1–A4 / B1–B4 / C1–C2 的离线锚都在本波测试族里（合跑与变异注毒逐席记录在 `.superpowers/sdd/2026-09-21-unify-wave/logs/`），但**离线绿只证"代码形状对"，不证"QQ 那头收到了"**。任何一项没亲眼看到，就在台账上记「未验」，不许写「通过」。
> **收尾纪律**：逐项在「应当看到什么」后打勾并附一句实见（含日期与触发的原句）；任一项不符走 systematic-debugging，先归因「没重启」再归因「代码坏」的顺序不可颠倒（铁律：改代码必须重启才生效）。B3/B4 与 C2 属**登记性**条目——在闸未开、供应商未接的现在，它们的"过"就是"确实还没生效"，不得反过来当成绩写。
