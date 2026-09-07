# Bot-Character-Bots

NoneBot AI 聊天机器人项目，包含守岸人人格、向量知识检索、聊天记忆、QQ/Telegram/Mail 适配器、媒体解析、订阅、表情包和统一运行时插件。

## 工作区边界（重要）

当前 Codex/AI 工作区**只能打开源码子目录**：

```text
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\
```

当前磁盘布局已经整理为：

```text
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\
├─ ChatBot\          当前生产源码（AI 工作区）
├─ ChatBot_Runtime\  运行数据、向量库、记忆、日志、缓存、SVG、虚拟环境
└─ ChatBot_Archive\  历史/测试/研究/备份压缩归档
```

以下目录不属于 AI 工作区，AI 默认不应扫描或主动读取：

```text
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Archive\
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\
C:\Users\LancyCelestia\Documents\MyWorkspace\
```

其中 `ChatBot_Runtime\data\` 包含向量嵌入数据库、聊天记忆、NoneBot data、日志、下载和运行状态；`venv\` 是 Python 虚拟环境；`ChatBot_Archive\` 只保存压缩归档。压缩这些运行数据不会减少 AI 上下文，**真正的隔离方式是只把源码子目录设置为工作区**。

以后归档统一写入：

```text
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Archive\YYYY-MM-DD\
```

日期目录必须直接放在 `ChatBot_Archive` 下，不要再套一层同名 `ChatBot_Archive`。归档包只在明确恢复历史内容时读取；不要把归档目录设置为当前工作区。

完整操作规则见 [WORKSPACE_GUIDE.md](WORKSPACE_GUIDE.md) 和 [docs/workspace-archive-policy.md](docs/workspace-archive-policy.md)。
## 快速启动

Windows 统一从项目根目录执行：

```powershell
$ROOT = "C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot"
$PY = "C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\venv\Scripts\python.exe"

# 离线控制台，不调用真实 LLM
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '$ROOT\scripts\dev.ps1' -Task console"

# 一轮本地验证
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '$ROOT\scripts\dev.ps1' -Task readiness-smoke"

# 启动 NoneBot/NapCat
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '$ROOT\scripts\dev.ps1' -Task run"

# 单轮后端核心链路（默认离线，不连接平台）
& "$ROOT\scripts\dev.ps1" -Task backend-smoke -Message "测试后端主链路"

# 文档、插件、lint、typecheck 验证（测试套件默认在工作区外）
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '$ROOT\scripts\dev.ps1' -Task verify"
```

真实 LLM 参数只放在本地 `.env`/`.env.prod`，不要写入文档、日志或 Git。第三方插件运行配置位于 `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\config\`，源码内不保留 `config\` 运行时目录。完整任务表见 [COMMANDS.md](COMMANDS.md)。

## 项目结构

```text
bot.py                         # NoneBot 初始化、适配器注册、插件加载
plugins/                       # 生产插件源码，运行核心，不要整体删除
plugins/bot_unified_runtime/   # 路由、人格、知识、LLM、策略、发送和渲染
personas/                      # 当前活动人格与知识源
ChatBot_Runtime\config\       # 第三方插件运行配置（源码工作区外）
scripts/                       # 启动、诊断、导入和维护脚本
docs/                          # 当前有效的接入、路由和归档说明
.env                           # 本地实际配置，禁止提交
.env.example                   # 配置键模板
.env.prod                      # 本地生产覆盖配置，禁止提交
pyproject.toml                 # 依赖、NoneBot 插件目录和适配器配置
```

## 运行数据与知识

代码默认使用 `data/...` 相对路径；`BOT_RUNTIME_DATA_DIR` 已将这些路径解析到外部运行目录。因此不要为了“清理工作区”删除或压缩活动中的 SQLite、FAISS、记忆、向量嵌入、Cookie、订阅和媒体库；它们已经脱离 AI 工作区。

Ruff/mypy 缓存也由 scripts/dev.ps1 写到外部 ChatBot_Runtime\cache\，不会在工作区重新堆积。

当前工作区中必须保留：

- `plugins/` 生产源码及 `ChatBot_Runtime\card_render_assets\`、模板；
- `personas/shorekeeper/` 活动人格和知识文件；
- `plugins/bot_unified_runtime/sources/data/qx.json`（天气功能读取）；
- `.env`、`.env.example`、`.env.prod`、`pyproject.toml`、`bot.py`；
- `scripts/` 维护入口和 `docs/` 当前有效说明。

## 测试与归档

完整测试树、研究源码、旧工作树、备份和临时文件已先压缩到外部归档，再从当前工作区移除。当前源码只保留 4 个关键回归测试：`test_chat_provider_chain.py`、`test_model_router_failover.py`、`test_nonebot_event_adapters.py`、`test_nonebot_sender.py`；它们不参与机器人运行，但用于验证 LLM 降级、事件适配和发送链路。需要完整测试时，只恢复归档包中的 `tests/`，测试完成后再次移出，不要把完整测试树长期放在 AI 工作区。

当前文档压缩前版本已归档：

```text
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Archive\2026-08-27_2026-08-28\documentation-before-compaction-2026-08-28.tar.gz
```

2026-08-28 清理报告与 Telegram/邮箱接入记录已于 2026-08-30 归档至 `ChatBot_Archive\2026-08-30\docs-completed-reports-and-plans.tar.gz`（含 `WORKSPACE_CLEANUP_REPORT.md`、`docs/email-telegram-setup.md` 等，详见归档目录内 README.md）。路由实现说明见 [docs/route-matrix.md](docs/route-matrix.md)，NapCat 见 [docs/napcat-setup.md](docs/napcat-setup.md)。
