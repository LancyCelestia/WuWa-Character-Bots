# ChatBot 工作区引导

## 先记住这一条

Codex/AI 当前只打开：

```text
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\
```

不要打开它的父目录。父目录同时包含约两万份运行文件，会让搜索、上下文建立和索引变慢。

## 三个目录的职责

```text
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\
├─ ChatBot\          生产源码；当前 AI 工作区
├─ ChatBot_Runtime\  运行时数据、数据库、日志、缓存、SVG、虚拟环境
└─ ChatBot_Archive\  历史/测试/研究/备份压缩包
```

| 目录 | AI 是否扫描 | 说明 |
|---|---:|---|
| `ChatBot\` | 是 | 当前生产源码、必要配置、精简文档和 4 个关键回归测试 |
| `ChatBot_Runtime\data\` | 否 | 向量嵌入、聊天记忆、NoneBot data、日志、下载和运行状态 |
| `ChatBot_Runtime\venv\` | 否 | Python 依赖；不要复制回源码目录 |
| `ChatBot_Runtime\cache\` | 否 | Ruff/mypy 等可再生缓存 |
| `ChatBot_Runtime\card_render_assets\` | 否 | 卡片渲染 SVG |
| `ChatBot_Archive\` | 否 | 历史文件、测试、研究源码和备份的压缩归档 |

## 启动与验证

从源码目录执行：

```powershell
Set-Location 'C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot'
powershell -NoProfile -ExecutionPolicy Bypass -Command "& .\scripts\dev.ps1 -Task help"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& .\scripts\dev.ps1 -Task readiness-smoke"
```

`scripts\dev.ps1` 会自动计算同级的 `ChatBot_Runtime\venv\`，所以不要手工把虚拟环境移回源码目录。

该入口还会设置 PYTHONDONTWRITEBYTECODE=1，避免运行验证在源码目录重新生成 __pycache__ 和 .pyc。

## 归档入口

以后归档只写入：

```text
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Archive\YYYY-MM-DD\
```

日期目录必须直接位于 `ChatBot_Archive` 下。归档后，Codex 不会主动扫描压缩包，除非用户明确要求恢复指定文件。归档包不应重新设为工作区；需要恢复时只解压指定子目录，验证完再移出。

## 当前保留的最小回归测试

源码内的 `tests\` 只保留 4 个关键回归测试。它们不是机器人运行依赖，但属于低体积、高价值的质量护栏，可直接执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "& .\scripts\dev.ps1 -Task test"
```

脚本会把临时目录放在 `ChatBot_Runtime\cache\`，并禁用 pytest 缓存插件，不应在源码目录生成 `.pytest_cache`、`__pycache__` 或 `.pyc`。

## 恢复完整测试树的流程

1. 停止机器人和相关任务。
2. 从归档包解压完整 `tests\` 到源码目录。
3. 运行 pytest 或目标测试。
4. 保存必要结果；把完整 `tests\`、测试缓存和日志再次移出源码目录。
5. 归档或删除临时解压内容。

## 不要做的事情

- 不要把 `MyWorkspace`、外层 `ChatBot` 容器、`ChatBot_Runtime` 或 `ChatBot_Archive` 设置为 Codex 工作区。
- 不要为了减少 Token 压缩或删除活动中的 SQLite、FAISS、记忆、Cookie、NoneBot data 或日志；隔离目录即可。
- 不要把 `.env` 的真实密钥复制到 Markdown、Issue、归档说明或聊天中。
- 不要把归档中的完整 `tests\`、`research\`、`backups\`、`tmp\` 或大型第三方源码树长期恢复到源码目录；当前保留的 4 个最小回归测试除外。

