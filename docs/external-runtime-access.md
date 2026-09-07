# 外部运行时访问与工作区边界

## 结论

**现在机器人可以访问工作区外的数据，但机器人不是通过阅读 Markdown 来找到这些数据。**
真正生效的入口是：

1. `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\.env` 和 `.env.prod`；
2. `plugins\bot_unified_runtime\config.py` 对 `data/...` 的统一解析；
3. `bot.py` 的启动初始化；
4. `scripts\dev.ps1` 的固定工作目录与外部虚拟环境；
5. NoneBot localstore 的外置目录设置。

Markdown（本文件、`WORKSPACE_GUIDE.md`、`README.md`）是给人和 AI 的操作边界说明，不是机器人的运行时配置。

## 数据流

```text
源码 ChatBot\\
  ├─ .env / .env.prod
  ├─ bot.py + plugins/
  └─ scripts/dev.ps1
       │ 读取并解析路径
       ▼
外部 ChatBot_Runtime\\
  ├─ data\\knowledge_embeddings.sqlite3       向量库
  ├─ data\\knowledge_faiss.index              FAISS 索引
  ├─ data\\wuwa_memory.sqlite3               机器人记忆
  ├─ data\\wuwa_history.sqlite3              对话历史
  ├─ data\\nonebot\\                         NoneBot 插件数据
  ├─ data\\downloads\\ / cards\\ / meme_library\\媒体与缓存
  ├─ config\\                                  第三方插件配置
  ├─ cache\\                                   Ruff/mypy/localstore 缓存
  └─ venv\\                                    Python 运行环境
```

### 机器人如何引用

- `BOT_RUNTIME_DATA_DIR` 指向 `ChatBot_Runtime\data`。
- 配置中写作 `data/xxx` 的数据库、日志、下载、卡片和订阅路径，会由 `Config._resolve_runtime_data_paths()` 转成外部绝对路径。
- `BOT_PERSONA_FILES` 和 `BOT_KNOWLEDGE_FILES` 支持绝对路径，因此库街区百科可以留在外部，守岸人活动人格可以留在源码或 Runtime。
- 卡片 SVG 由 `BOT_CARD_ASSET_DIR` 或 `ChatBot_Runtime\card_render_assets` 自动发现。
- `nonebot-plugin-localstore` 使用 `.env.prod` 中的外部 `LOCALSTORE_*_DIR`，所以不会因 CWD 把数据写回 `ChatBot\cache`、`ChatBot\config` 或 `ChatBot\data`。
- 启动崩溃日志在 NoneBot 初始化后绑定同一个外部 Runtime data 目录；不会因 `bot.py` 过早安装崩溃钩子而回流源码目录。

## Codex/AI 如何避免扫描

### 正确做法

在 Codex 中关闭当前外层容器工作区，只打开：

```text
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot
```

打开后根目录应直接看到 `bot.py`、`plugins\`、`scripts\`、`personas\` 和 `pyproject.toml`。

### 不要打开

```text
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Archive
```

`.gitignore` 只能影响 Git 跟踪，**不能可靠地限制 AI 上下文扫描**。限制扫描的决定性措施是工作区根目录只选源码子目录。

## 启动、调试与恢复

所有命令都从源码目录执行：

```powershell
Set-Location 'C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot'
powershell -NoProfile -ExecutionPolicy Bypass -Command "& .\scripts\dev.ps1 -Task runtime-layout"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& .\scripts\dev.ps1 -Task config-smoke"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& .\scripts\dev.ps1 -Task readiness-smoke"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& .\scripts\dev.ps1 -Task startup-smoke"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& .\scripts\dev.ps1 -Task run"
```

请注意上面的 `runtime-layout` 是最关键的外部边界检查；它只读目录和配置，不打开数据库内容，不调用 LLM，不连接 QQ/NapCat。受限终端优先使用上面的 `-Command "& .\scripts\dev.ps1 -Task ..."` 写法；如果独立 PowerShell 环境支持 `-File`，也可以使用旧的等价写法。

如果检查失败，优先修正 `.env`/`.env.prod`，不要把 Runtime 目录复制回源码工作区。

## 维护脚本

以下脚本的默认数据库和输出目录已经改为读取 `BOT_RUNTIME_DATA_DIR`：

- `scripts\knowledge_progress.py`
- `scripts\knowledge_bench.py`
- `scripts\import_meme_packs.py`

表情包导入脚本写入数据库的文件路径也使用绝对路径，避免数据库位于 Runtime 时，后续清理操作错误地把相对路径解释到源码目录。

## 归档与恢复

归档固定写入：

```text
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Archive\YYYY-MM-DD\
```

归档包不属于当前 AI 工作区。只有在明确恢复某个测试或历史文件时，才临时解压到源码目录；验证完成后再次移出。运行中的 SQLite、FAISS、记忆、Cookie 和 NoneBot data 不要直接压缩后继续运行，也不要直接删除。

## 快速故障判断

| 现象 | 首先检查 |
|---|---|
| 源码目录重新出现 `data/`、`config/` 或 `cache/` 文件 | `LOCALSTORE_USE_CWD=false`，以及 `LOCALSTORE_*_DIR` 是否仍指向 Runtime |
| 知识检索为空 | `BOT_RUNTIME_DATA_DIR`、向量 SQLite、FAISS 索引和 `BOT_KNOWLEDGE_FILES` |
| 人格缺失 | `BOT_PERSONA_FILES` 是否全部存在，文件是否仍在原位置 |
| 卡片图标缺失 | `ChatBot_Runtime\card_render_assets\` 是否存在，或设置 `BOT_CARD_ASSET_DIR` |
| AI 上下文又变大 | Codex 是否重新打开了外层 `ChatBot` 容器，而不是源码子目录 |
| 运行后出现 `__pycache__` | 使用 `scripts\dev.ps1`；直接调用 Python 前设置 `PYTHONDONTWRITEBYTECODE=1` |

## 验收标准

下列命令全部通过，才可以认为“外部数据访问引导”有效：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 runtime-layout
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 docs-check
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 plugin-check
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 config-smoke
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 readiness-smoke
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 startup-smoke
```

这些检查不等同于真实平台联调；真实 NapCat/QQ 连接仍需在用户明确要求时单独验证。
