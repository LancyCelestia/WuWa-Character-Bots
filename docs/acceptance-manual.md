# 验收与接入手册（Acceptance Manual）

目标：先让你把「对话/人格」跑起来并确认符合需求，再接 NapCat、GsCore 与其他插件。
全程在本机完成，不碰第三方框架账号。任何命令都从项目根目录执行：

    cd C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot

## 0. 一次装好依赖

    .venv\Scripts\python.exe -m pip install -e . nb-cli
    powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 doctor
    .venv\Scripts\nb orm upgrade      # 首次运行前初始化 SQLite 数据库
    .venv\Scripts\nb orm check        # 应提示：没有检测到新的升级操作

## 1. 对话 / 人格测试（第一步，必须先通过）

### 1.1 离线控制台（不需要联网，验证人格链路）

    powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 console          # 交互 REPL
    .venv\Scripts\python.exe -m plugins.bot_unified_runtime.console_chat --message "岸宝，你好"

离线模式用的是 static 占位回复，只能验证链路，不能验证人格文案。

### 1.2 真实模型控制台（验证人格是否符合你的需求）

    .venv\Scripts\python.exe -m plugins.bot_unified_runtime.console_chat --provider openai_compatible --model deepseek-v4-flash --base-url https://api.deepseek.com/v1 --api-key <你的key>

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

chat-smoke 输出 llm_status=ok 且  receipt_state=sent 即为对话链路正常。
（控制台中文偶发乱码是 PowerShell 编码显示问题，不影响 QQ 端输出。）

## 2. NapCat 接入 QQ（对话通过后再做）

详细步骤见 docs/napcat-setup.md，要点：

1. 下载 NapCat（https://napneko.github.io/ ，推荐 NapCat.Win 一键包），用 QQ 小号扫码登录。
2. NapCat WebUI（http://127.0.0.1:6099）→ 网络配置 → 新建「WebSocket 服务器」，Host 127.0.0.1、端口 3001，Access Token 填 <你的token>（需与 .env.prod 中的 access_token 完全一致）。
3. .env.prod 配置：DRIVER=~fastapi+~httpx+~websockets、ONEBOT_WS_URLS=["ws://127.0.0.1:3001/?access_token=<你的token>"]、LOCALSTORE_USE_CWD=true；真实 token 只存在本地 .env.prod，不写进文档或日志。
4. 初始化数据库并启动机器人：

       .venv\Scripts\nb orm upgrade      # PostgreSQL 已迁移可跳过；首次部署才需要执行
       .venv\Scripts\nb orm check        # 应提示：没有检测到新的升级操作
       .venv\Scripts\nb run

   或 .venv\Scripts\python.exe bot.py（先设好 DRIVER / ONEBOT_WS_URLS 环境变量）。
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
- 卡片模板参考 MIT 许可的 astrbot_plugin_parser，出处记录在 THIRD_PARTY_NOTICES.md。

## 6.2 向量知识库（本地 Ollama bge-m3 优先，百炼兜底）

1. 本地：确认 Ollama 在跑且已 `ollama pull bge-m3`（`http://127.0.0.1:11434`）；.env 中 `BOT_EMBEDDING_LOCAL_ENABLED=true`、`BOT_EMBEDDING_LOCAL_BASE_URL=http://127.0.0.1:11434/v1`、`BOT_EMBEDDING_LOCAL_MODELS=bge-m3`。
2. 兜底：在百炼控制台创建 API Key（形如 sk-xxxx）。
3. 编辑 .env（本地文件，不入库）：
   `BOT_EMBEDDING_ENABLED=true`、`BOT_EMBEDDING_MODEL=qwen3.7-text-embedding`、
   `BOT_EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`、
   `BOT_EMBEDDING_API_KEY=<你的Key>`、`BOT_EMBEDDING_DIMENSIONS=1024`。
4. 连通性验证（不写知识库，看 active_base_url 是否命中 127.0.0.1:11434）：`powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 embedding-smoke`，看到 ok=true 即成功。
5. 预建库（首次几分钟，断点续跑）：`powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 knowledge-sync`，完成后再启动机器人。
6. 验证检索：`scripts/dev.ps1 context-smoke`（或 QQ 私聊问一个鸣潮设定问题），确认知识库命中而不是顺序取块。
