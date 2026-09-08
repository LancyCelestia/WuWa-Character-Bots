# 开发命令

所有命令从以下目录执行：

```text
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot
```

统一入口：`scripts/dev.ps1`。它优先使用工作区外的 `ChatBot_Runtime\venv`，不会要求把虚拟环境放回源码目录。

## 高频命令

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 help
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 doctor
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 readiness-smoke
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 console
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 backend-smoke -Message "测试后端主链路"
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 run
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 verify
```

## 任务表

| 任务 | 用途 | 网络/副作用 |
|---|---|---|
| `help` | 显示任务帮助 | 无 |
| `doctor` | 检查 Python、NoneBot、适配器和本地依赖 | 不调用 LLM |
| `install` | 用 `uv sync` 或 pip 安装依赖 | 修改外部 venv |
| `dev` / `run` | 启动 NoneBot | 连接已配置平台 |
| `run-watch` | 退出后自动重启 NoneBot | 连接已配置平台 |
| `console` | 控制台对话，默认 static provider | 默认离线；可手动启用 LLM |
| `backend-smoke` | 单轮执行核心后端链路并输出 JSON | 默认离线；不连接平台、不发送真实消息 |
| `readiness-smoke` | 聚合本地就绪状态 | 默认不调用真实 LLM |
| `dialogue-smoke` | 验证一轮对话诊断 | 依配置决定是否调用 LLM |
| `chat-smoke` | 验证人格、知识、LLM 和发送链路 | 不连接 NapCat |
| `config-smoke` | 检查配置和路径就绪 | 不联网 |
| `persona-smoke` | 检查人格与知识来源 | 不调用 LLM |
| `context-smoke` | 生成安全的上下文数字摘要 | 不输出原文/密钥 |
| `why-smoke` | 解释路由、策略、回执和审计 | 本地优先 |
| `llm-setup` | 输出安全的 LLM 配置清单 | 不写密钥、不调用 provider |
| `llm-smoke` | 检查配置的 OpenAI-compatible LLM | 只读网络检查 |
| `nonebot-smoke` | 检查 NoneBot/OneBot 插件导入 | 不连接 NapCat |
| `startup-smoke` | 子进程加载 NoneBot 后退出 | 不连接 NapCat |
| `queue-smoke` | 使用临时 SQLite 验证发送队列 | 不发送 QQ |
| `transport-smoke` | 使用 fake transport 验证消息段 | 不连接 NapCat |
| `online-transport-smoke` | 读取在线状态 | 不调用发送 API |
| `credential-smoke` | 检查 Cookie/凭据状态 | 不打印凭据值 |
| `embedding-smoke` | 检查嵌入服务 | 不改动向量数据库 |
| `knowledge-sync` | 分块并写入向量知识库 | 修改外部 data |
| `gscore-smoke` | 检查 GsCore 桥接就绪 | 只读 |
| `route-demo` | 离线输出问法路由矩阵 | 无网络 |
| `route-smoke` | 验证天气/wiki/Epic/点歌等真实能力 | 可能联网，不发送 QQ |
| `docs-check` | 检查当前文档和关键配置锚点 | 只读 |
| `plugin-check` | 检查 `plugins/` 发现契约 | 只读 |
| `smoke` | 文档、插件、NoneBot import 和 CLI 检查 | 只读 |
| `test` | 执行当前保留的 4 个关键回归测试 | 临时目录在外部 Runtime；不会生成源码 `.pytest_cache` |
| `lint` | 执行 `ruff check .` | 只读，可能生成 `.ruff_cache/` |
| `typecheck` | 通过当前 Python 执行 mypy 检查 `plugins/` | 只读，可能生成缓存 |
| `verify` | docs/plugin/pytest/ruff/mypy 总检查 | 当前 4 个测试会执行；完整测试树仍在外部归档 |

## 测试策略

当前源码保留 4 个低体积关键回归测试，可直接通过 `test` 或 `verify` 执行。完整测试套件不常驻当前 AI 工作区；需要时从以下归档包恢复到项目根目录：

```text
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Archive\2026-08-27_2026-08-28\development-materials-2026-08-28.tar.gz
```

恢复后执行：

```powershell
$PY = "C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\venv\Scripts\python.exe"
& $PY -m pytest "C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\tests"
```

完整测试完成后把恢复的 `tests/` 移出工作区；不要把日志、pytest 临时目录、数据库或虚拟环境复制回工作区。

## 路径与安全规则

- 运行数据统一在 `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\data\`；其中包括向量库、聊天记忆、NoneBot data、日志和媒体缓存。
- Ruff/mypy 缓存统一写入 C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\cache\，不会重新创建到当前工作区。
- 归档统一在 `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Archive\YYYY-MM-DD\`；压缩包不要留在当前工作区。
- `.env`、Cookie、Token、数据库内容和完整 prompt 不进入聊天、日志或文档。
- `.gitignore` 只减少 Git 跟踪内容；要减少 AI 上下文，必须把目录移到当前工作区之外。
Canonical verification entry: scripts/dev.ps1 verify

搜索 API 配置和验收顺序见 [docs/search-api-adapters-2026-09-06.md](docs/search-api-adapters-2026-09-06.md)。

```powershell
# 只生成并保存脱敏 Prompt，不调用 LLM；先看这个结果再允许后续执行
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task prompt-preview -Message '测试后端主链路'"
```

```powershell
# 离线真实后端底座验收：NoneBot/plugin、startup、OneBot transport、backend pipeline
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task backend-base-smoke -Message '测试后端底座'"
```

## 2026-09-06 详细回答与记忆抽取调试

```text
/bot reply 详细
/bot runtime get BOT_REPLY_DETAIL
/bot runtime get BOT_CHAT_MAX_TOKENS
/bot runtime set BOT_CHAT_FAST_MODE false
/bot runtime set BOT_CHAT_MAX_TOKENS 65538
/bot runtime set BOT_MEMORY_EXTRACT_TIMEOUT_SECONDS 15
/bot runtime set BOT_MEMORY_EXTRACT_MAX_TOKENS 200
/bot runtime set BOT_MEMORY_EXTRACT_ERROR_COOLDOWN_SECONDS 300
/bot runtime set BOT_MEMORY_EXTRACT_ENABLED false
/bot model list
/bot model priority <注册ID> 1
/bot help 回复
/bot help 设置
/bot help 模型
/bot cookie
/bot cookie import <平台> <Cookie头>
```

/bot cookie（管理员）：按平台查看 17 个平台凭证状态（只显示 cookie 名与到期日，不回显值）；/bot cookie import <平台> <Cookie头>：把浏览器复制的 `名=值; ...` 整行追加写入 cookies.txt（同名不覆盖），下一次解析即热生效。统一命令格式：/bot <模块词> <功能词> [参数]。

65538（约 64K）是最大输出预算，不是强制长度；运行时覆盖优先于 .env。聊天上限允许 0..65538；抽取 timeout/cooldown 取有限值 (0,3600] 秒，抽取 tokens 取 1..4096。false 暂停自动抽取，不删除记忆；启动时本就关闭的实例需本地启用后重启，不能仅靠 true 热创建 writer。模型 priority 为 1..N 唯一槽位，移动其他项顺移；手动指定和生效时段组优先于基础 priority。model list 是候选配置，/bot llm 会新发可能收费的诊断请求。真实密钥只在本地安全配置，不在聊天发送。

验收证据与完整待办：docs/chat-memory-routing-fixes-2026-09-06.md。

## Wiki 列表条目与环境诊断续修
`维基 守岸人`、`维基 鸣潮守岸人`、`维基 漂泊者`、`维基 卡提希娅·` 支持独立页缺失后的精确列表条目提取。
本地 `.env` 可设置 `BOT_WIKI_ENTRY_PAGES=["鳴潮角色列表"]`（最多优先 3 页，`[]` 禁用），重启生效；不是 runtime set 热配置。
`doctor` 现在优先寻找所选 Python 的同目录 nb.exe，避免 PATH 未激活误报。说明与待办见 docs/live-chat-followup-2026-09-06.md。


## Phase 0-3 输出与安全
`BOT_CHAT_MAX_TOKENS=65538`、`BOT_CHAT_FAST_MAX_TOKENS=65538` 是最大上限，不是强制每次生成 64K；科普/知识问题在 auto 模式下会优先完整解释核心内容、当前状态和相关关系。文件内容通过安全读取，不执行代码；代码/长文在用户明确要求生成或保存时写入文件并通过统一出站发送。

