# 守岸人 Bot（WuWa Character Bot）

NoneBot2 聊天机器人项目：守岸人人格对话、向量知识检索、聊天记忆、QQ/Telegram/Mail 适配器、
37+ 平台媒体解析、订阅推送、表情包、釉瑚云母卡片渲染与统一运行时插件（`plugins/bot_unified_runtime/`）。

> **接手必读**：[AGENTS.md](AGENTS.md)（工作区规则 + 项目全貌 + 架构/流程图，自动加载）→
> [docs/HANDBOOK.md](docs/HANDBOOK.md)（单一活文档：族谱/现行事实/总账/全史；§20 最新会话底账含权限链路图）。
> 命令手册：[COMMANDS.md](COMMANDS.md)；路由矩阵：[docs/route-matrix.md](docs/route-matrix.md)。
>
> **接手三步**：①读本文件+AGENTS.md 掌握边界与架构 → ②按 AGENTS.md 第五部分跑四门禁确认基线 →
> ③从 HANDBOOK §20.3 的「残余与建议」领任务。改代码必须重启 bot 才生效（铁律）。

## 工作区边界（重要）

当前 AI 工作区**只能打开源码子目录**：

```text
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\
```

磁盘布局：

```text
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\
├─ ChatBot\          生产源码（AI 工作区）
├─ ChatBot_Runtime\  运行数据、SQLite 群、cookie、日志、缓存、卡片资产、虚拟环境
└─ ChatBot_Archive\  历史文档/测试/研究/备份压缩归档（按日期目录 + manifest）
```

`ChatBot_Runtime\`、`ChatBot_Archive\`、上层目录不属于 AI 工作区，默认不扫描不读取；
压缩运行数据不会减少 AI 上下文，**真正的隔离是只把源码子目录设为工作区**。
归档统一写入 `ChatBot_Archive\YYYY-MM-DD\`，先压缩验证再移出，详见
[WORKSPACE_GUIDE.md](WORKSPACE_GUIDE.md) 与 [docs/workspace-archive-policy.md](docs/workspace-archive-policy.md)。

## 快速启动

Windows 统一从源码目录执行（venv 由 `scripts\dev.ps1` 自动定位到外部 Runtime，勿手工搬回）：

```powershell
Set-Location 'C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot'

# 离线控制台对话（默认静态 LLM，不真调）
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task console"

# 一轮就绪冒烟 / 后端核心链路（离线）
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task readiness-smoke"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task backend-smoke"

# 启动 NoneBot（生产/开发；需先起 NapCat，见 docs/napcat-setup.md）
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task run"

# 全部 40 个任务清单
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task help"
```

真实 LLM 参数只放本地 `.env`（gitignored），不写入文档/日志/Git。

## 验证门禁（每轮交付前全绿）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task test"           # 全量回归（基线 1766+ passed）
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task lint"           # ruff
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task typecheck"      # mypy（238 文件）
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task runtime-layout" # 源码树/边界体检
```

绕开 dev.ps1 直跑 python/pytest 必须 `PYTHONDONTWRITEBYTECODE=1` 并把临时目录指到源码树外。

## 真机验收

bot 在线后向白名单群真发全能力矩阵（解析卡/点歌/全球股指 18 指数/财经科技快报/天气预警/
随机图/占卜/help/好感度卡/长文转发）：

```powershell
& "$ROOT\scripts\dev.ps1" -Task run   # 先起 bot
python scripts\e2e_acceptance.py --target-group <white1群ID> --execute   # 默认 DRY-RUN
```

## 项目结构

```text
bot.py                         # NoneBot 初始化、适配器注册、插件加载、崩溃守卫
plugins/bot_unified_runtime/   # 统一运行时：路由/人格/记忆/LLM/策略/解析/订阅/发送/渲染
personas/shorekeeper/          # 守岸人人格与知识源（含 aliases.txt 昵称表）
scripts/                       # dev.ps1 统一入口、runtime_paths、e2e_acceptance 等
docs/                          # 单一活文档 HANDBOOK + 索引 README + design/ 架构规格 ×4 + 运维手册
tests/                         # ~1760 离线回归（全 mock）
COMMANDS.md                    # 命令人读手册（与 /bot help 同口径）
AGENTS.md                      # 工作区规则 + 项目全貌（AI 自动加载）
.env                           # 本地实际配置，禁止提交
.env.example / .env.prod       # 配置键模板 / 本地生产覆盖（禁止提交）
pyproject.toml                 # 依赖、NoneBot 插件目录与适配器配置
```

## 运行数据与知识

代码中的 `data/...` 相对路径经 `BOT_RUNTIME_DATA_DIR` 解析到外部运行目录
（`tests/test_datafix_runtime_paths.py` 锁定"源码树永不被写"）。
因此**不要**为清理工作区删除或压缩活动中的 SQLite、向量嵌入、记忆、Cookie、订阅和媒体库。

当前必须保留：`plugins/` 生产源码、`personas/shorekeeper/`、`scripts/`、`docs/` 现行文档、
`tests/` 回归树、`bot.py`、`pyproject.toml`、`.env*`。
历史文档/评审/研究/旧工作树已归档（见 `ChatBot_Archive\2026-09-12\`，内含 manifest）。
