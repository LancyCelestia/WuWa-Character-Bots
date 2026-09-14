# ChatBot 工作区引导

## 先记住这一条

AI 当前只打开：

```text
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\
```

不要打开父目录。项目全貌与工作区规则见 [AGENTS.md](AGENTS.md)（AI 自动加载）。

## 三个目录的职责

```text
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\
├─ ChatBot\          生产源码；当前 AI 工作区
├─ ChatBot_Runtime\  运行时数据、SQLite 群、cookie、日志、缓存、卡片资产、虚拟环境
└─ ChatBot_Archive\  历史文档/评审/研究/备份压缩归档（按日期目录）
```

| 目录 | AI 是否扫描 | 说明 |
|---|---:|---|
| `ChatBot\` | 是 | 生产源码、`tests/` 回归树（用例数以最近一次实跑为准，规模口径见 `docs/auto-facts.md`）、现行 docs、`personas/`、脚本 |
| `ChatBot_Runtime\data\` | 否 | 向量嵌入、聊天记忆、cookie、订阅状态、日志、下载与运行状态 |
| `ChatBot_Runtime\venv\` | 否 | Python 依赖；不要复制回源码目录 |
| `ChatBot_Runtime\cache\` | 否 | Ruff/mypy/pytest 等可再生缓存 |
| `ChatBot_Runtime\card_render_assets\` | 否 | 卡片渲染资产 |
| `ChatBot_Archive\` | 否 | 历史压缩归档（docs-archive / code-hygiene 等，内含 manifest） |

> 卡片渲染 token 单一来源见 `docs/rendering-contract.md`（改模板前必读）；命令教程以自动生成的 `docs/command-catalog.md` 为准。

## 启动与验证

从源码目录执行（`scripts\dev.ps1` 自动定位外部 venv 并设置 `PYTHONDONTWRITEBYTECODE=1`）：

```powershell
Set-Location 'C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot'
powershell -NoProfile -ExecutionPolicy Bypass -Command "& .\scripts\dev.ps1 -Task help"            # 全部任务清单（以 help 实时输出为准）
powershell -NoProfile -ExecutionPolicy Bypass -Command "& .\scripts\dev.ps1 -Task readiness-smoke"
```

四道交付门禁（每轮改动前全绿）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "& .\scripts\dev.ps1 -Task test"           # 全量回归（以本次实跑输出为准；不在文档中手写固定用例数）
powershell -NoProfile -ExecutionPolicy Bypass -Command "& .\scripts\dev.ps1 -Task lint"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& .\scripts\dev.ps1 -Task typecheck"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& .\scripts\dev.ps1 -Task runtime-layout"
```

## 归档入口

归档只写入：

```text
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Archive\YYYY-MM-DD\
```

规程：**压缩 → 验证（testzip+副本）→ 移出源码区 → 附 manifest**。
先例：`2026-09-12\docs-archive-2026-09-12.zip`（26 份旧文档）与
`2026-09-12\code-hygiene-20260912.zip`（98 entries：docs 归档件 16 + 根目录 scratch + review/ + SDD 台账）。

## 测试树

`tests\` 是完整回归树（全离线 mock；测试文件数见 `docs/auto-facts.md`，用例数以最近一次实跑为准），**常驻源码区**，是质量护栏而非运行依赖。
测试若以默认路径写源码树 `data/` 属已知残留（AGENTS.md 问题台账 #1，Wave-6 tmp_path 化），
发现即备份 `%TEMP%` 后清除并复跑 `runtime-layout`。

## 不要做的事情

- 不要把 `MyWorkspace`、外层 `ChatBot` 容器、`ChatBot_Runtime` 或 `ChatBot_Archive` 设为 AI 工作区。
- 不要删除或压缩活动中的 SQLite、FAISS、向量嵌入、记忆、Cookie、NoneBot data 或日志。
- 不要把 `.env` 真实密钥复制到 Markdown、Issue、归档说明或聊天中。
- 不要在源码区重建归档中已移出的历史文档/评审/研究目录（需要时从归档包按需解压指定文件）。
- 不要绕过 `AGENTS.md` 第一部分的 git 纪律（禁 `add -A`、push 需用户明确指示）。
