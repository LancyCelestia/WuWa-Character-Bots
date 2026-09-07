# ChatBot 工作区与归档规范

> 本文是当前项目的引导文件。它同时约束人工操作和 AI/Codex 的读取边界。

## 1. 当前目录布局

当前磁盘上，外层容器与三个职责目录如下：

```text
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\
├─ ChatBot\          生产源码；Codex 只打开这一层
├─ ChatBot_Runtime\  运行时数据与依赖，不作为 AI 工作区
└─ ChatBot_Archive\  历史归档，不作为 AI 工作区
```

当前 AI/Codex 工作区：

```text
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\
```

运行目录：

```text
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\
```

以后归档统一写入：

固定归档根目录：

```text
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Archive\
```

## 2. AI 扫描边界

只把源码目录设置为 Codex 工作区：

```text
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\
```

不要打开以下目录作为工作区：

```text
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Archive\
C:\Users\LancyCelestia\Documents\MyWorkspace\
```

`.gitignore` 只影响 Git 跟踪，不负责限制 AI 扫描。减少 Token 的关键是工作区边界，而不是压缩数据库、日志或虚拟环境。

## 3. 归档规则

以后所有历史、测试、研究源码、备份和临时文件，统一按日期放入：

```text
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Archive\YYYY-MM-DD\
```

日期目录必须直接位于 `ChatBot_Archive` 下，禁止创建：

```text
...\ChatBot_Archive\ChatBot_Archive\YYYY-MM-DD\
```

标准流程：

1. 停止机器人、pytest、IDE 任务和相关 Python 进程。
2. 确认目标内容不是运行所需的源码、配置、活动人格、知识源、数据库或虚拟环境。
3. 使用 `.tar.gz` 或 `.zip` 压缩；大目录优先 `.tar.gz`。
4. 读取压缩包目录清单，确认包可以正常打开。
5. 把压缩包放入当天的日期目录。
6. 只有在压缩包验证通过后，才从源码工作区移除原目录。
7. 在日期目录的 `README.md` 中记录原路径、压缩包用途、日期和敏感信息风险。

PowerShell 示例：

```powershell
$root = 'C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot'
$archive = 'C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Archive\2026-08-27'
$target = 'old-experiment'

New-Item -ItemType Directory -Force -Path $archive | Out-Null
tar -czf "$archive\old-experiment.tar.gz" -C $root $target
tar -tzf "$archive\old-experiment.tar.gz" | Select-Object -First 20

# 确认清单无误后再执行：
Remove-Item -LiteralPath (Join-Path $root $target) -Recurse -Force
```

恢复时先解压到临时目录；不要直接在压缩包内部修改。测试运行结束后，测试目录应再次移出源码工作区。

## 4. 运行数据处理原则

以下内容由程序按自身格式管理，AI 不需要扫描：

- `ChatBot_Runtime\data\` 下的向量嵌入数据库、FAISS 索引和聊天记忆；
- NoneBot 固定 `data`、订阅、Cookie、媒体缓存和日志；
- `ChatBot_Runtime\cache\` 下的 Ruff/mypy 等可再生缓存；
- `ChatBot_Runtime\venv\` 下的 Python 依赖；
- `ChatBot_Runtime\card_render_assets\` 下的卡片 SVG；
- `ChatBot_Runtime\git\` 下的 Git 对象和回滚材料。

不要直接删除活动 SQLite、FAISS、Cookie、记忆或 NoneBot data。需要减小磁盘占用时，使用数据库 `VACUUM`、索引重建、日志轮转和媒体缓存配额；这些操作与减少 AI Token 是两件事。

## 5. 敏感信息

真实 `.env`、Token、Cookie、数据库内容、邮件状态和完整 prompt 不得写入聊天、报告或归档说明。归档前确认目录访问权限。若密钥曾经被复制到不安全位置，应在安全渠道轮换，但不要把密钥值贴到聊天中。

## 6. 本次合并归档

```text
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Archive\2026-08-27_2026-08-28\
```

该目录合并了 2026-08-27 与 2026-08-28 两次同一轮清理请求产生的压缩包。

