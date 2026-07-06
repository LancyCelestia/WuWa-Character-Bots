# 开发命令

本项目统一使用 `scripts/dev.ps1` 作为 Windows 本地开发、验证和启动入口。

这些命令会诚实反映当前项目阶段：仓库已有研究资料和契约文档，但统一运行时插件还没有正式实现。

## 常用命令

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 help
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 install
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 dev
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify
```

## 命令矩阵

| 任务 | 用途 | 当前行为 |
| --- | --- | --- |
| `help` | 显示帮助。 | 始终可用。 |
| `install` | 安装项目依赖。 | 如果存在 `uv` 就执行 `uv sync`，否则执行 `python -m pip install -e .`。 |
| `dev` | 启动本地开发机器人。 | 执行 `nb run`；如果没有 NoneBot CLI 会失败。 |
| `run` | 使用同一运行命令启动机器人。 | 目前等同于 `dev`，生产部署以后可以单独扩展。 |
| `docs-check` | 检查命令文档、契约文档、人格/知识库文档、媒体流水线文档、parser/render 锚点和关键配置指针。 | 文档和规格存在且包含必要锚点时通过。 |
| `plugin-check` | 检查 `plugins/` 是否已配置，并报告本地插件是否存在。 | 在 Milestone 0 之前没有本地插件是预期警告。 |
| `smoke` | 检查文档、插件配置、NoneBot import 和 `nb` CLI。 | 依赖未安装前会失败。 |
| `test` | 执行 `pytest`。 | 在 `tests/` 和 pytest 不存在时明确失败。 |
| `lint` | 执行 `ruff check .`。 | 在 ruff 未安装时明确失败。 |
| `typecheck` | 执行 `mypy .`。 | 在 mypy 未安装时明确失败。 |
| `verify` | 当前阶段默认验证入口。 | 执行 `docs-check`、`plugin-check`，如果测试/ruff/mypy 可用则一起执行。 |

## 验证策略

`verify` 是当前仓库阶段的默认门禁。它不能假装缺失的检查已经通过。

- 缺少契约文档或配置指针会失败。
- 缺少本地插件 Python 文件会给出警告，直到 Milestone 0 创建统一运行时插件。
- 缺少 `tests/` 时，`verify` 只警告；但单独执行 `test` 必须失败。
- 缺少 `ruff` 或 `mypy` 时，`verify` 只警告；但单独执行 `lint` 或 `typecheck` 必须失败。
- `smoke` 比 `verify` 更严格：它要求依赖和 NoneBot CLI 已安装。

推荐顺序：

1. 实现前：先跑 `docs-check` 和 `verify`。
2. 依赖安装后：再跑 `smoke`。
3. 创建测试后：`test` 应成为 `verify` 的强制部分。
4. 引入 lint/type 工具后：`lint` 和 `typecheck` 应进入 CI。

## 本地启动

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 dev
```

当前命令包装的是 `nb run`。项目配置来自 `pyproject.toml`：

- `plugin_dirs = ["plugins"]`
- `builtin_plugins = ["echo"]`
- 适配器：OneBot V11、Console、Mail
- 支撑插件：status、apscheduler、localstore、alconna、filehost、orm、htmlkit

## NoneBot / NapCat 运行边界

NoneBot 只负责插件加载、事件分发和适配器抽象。NapCat 作为 OneBot V11 实现时，进入项目的事件必须先归一化为 `IncomingMessage`，离开项目的消息必须由统一 sender 将 `SendRequest.content` 转成 OneBot/NapCat 消息段。

能力模块不能直接调用 `bot.send_private_msg`、`bot.send_group_msg`、`event.send` 或 NapCat HTTP/WebSocket API。只有 sender/transport adapter 可以触碰具体发送 API，并且必须返回 `DeliveryReceipt`。

## 下一阶段命令里程碑

统一运行时插件实现后，需要收紧这些检查：

- `plugin-check` 必须要求运行时插件包存在。
- `smoke` 必须验证运行时插件能被 NoneBot 加载。
- `verify` 必须要求运行时契约、策略决策、发送回执和审计记录测试通过。
- 数据库或迁移命令只在 ORM schema 存在后再加入。
