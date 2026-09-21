# 邮件与控制台适配器 · 控制台一次性驱动

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B01.mail-console · 控制台一次性驱动

- 层级：一级 B01 → 二级 mail-console → 三级 `console-driver`
- 实现落点：`plugins/bot_unified_runtime/mail_adapter.py`、`plugins/bot_unified_runtime/mail_bridge.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

不开协议端、不起 HTTP，用同一套统一运行时流水线在终端里跟守岸人对话。它是「先验证人格链路，再接 QQ」这条验收顺序的第一入口，也是排查「到底是模型的问题还是链路的问题」时的最小复现环境。默认走离线 static provider，配了真实模型或用命令行覆盖就走真实模型（覆盖只在本进程生效，绝不写回 `.env`）。

## 怎么调用

真身 `domains/ops/smoke/console_chat.py`（模块级 `main(argv=None)`，可 `python -m` 直跑）：

- 一条命令：`powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 console`（可加 `-Message` 走单轮非交互）。
- 直跑：`python -m plugins.bot_unified_runtime.domains.ops.smoke.console_chat --message "你好"`（直跑按铁律带 `PYTHONDONTWRITEBYTECODE=1`，并加 `-p no:cacheprovider` 类卫生参数不适用——它不是 pytest）。
- 交互命令：`/help` `/status` `/why` `/quit`；配了 `BOT_RUNTIME_PERSONA_NICKNAME` 后昵称同义词一并可用（走 `CommandAliasResolver`）。
- 内部件：`_build_runtime(...)` 组装 pipeline 与发送队列、`_route_for_message(...)` 复用 B02 的 `classify_message_route`、`run_once(...)` 与 `run_interactive(...)` 两种驱动形态。

现役状态说明：插件在根 `__init__.py` 的 `supported_adapters` 里放行了 `~console` 驱动，但生产 `DRIVER` 不指向它；日常用的是上面这个 smoke 入口，而不是 NoneBot 自带 console 聊天。

## 开关与参数

- 命令行：`--env`、`--provider`、`--model`、`--base-url`、`--api-key`、`--temperature`、`--message` 等，全部只在本次进程生效。
- 配置文件：`.env` / `.env.example`（同一条 `Config` 装载路径，热改一律不认，改完重跑即可）。
- 谁能用：本机持有仓库与 Runtime 目录的运营者/管理员；它不接任何平台，因此不存在对外暴露面。

## 失败时看到什么

- 不连 SnowLuma、不发 QQ：审计与回执留在进程内，终端直接打印回执摘要（`_last_receipt_summary`）与状态行（`_status_summary`）。
- 离线 provider 下回复是确定性的静态话术——看到「不像真人」属预期，那是链路验收不是人格验收，要验人格得显式给真实模型参数。
- 多轮历史只在内存里，退出即清空：这里看不到持久化记忆的效果，别拿它当记忆验收。

## 测试与验收

离线：作为 smoke 族的一员被 `scripts/dev.ps1` 的 `verify`/smoke 面调用（`tests/` 内无独立 `test_console_*.py`，此项如实登记）。
真机：`docs/acceptance-manual.md` §1.1（离线控制台）与 §1.2（真实模型控制台）——注意该手册正文里有一条命令写的是旧路径 `plugins.bot_unified_runtime.console_chat`，真身已迁至 `domains/ops/smoke/console_chat.py`，照手册原样执行会 `ModuleNotFoundError`；以本页命令或 `dev.ps1 console` 为准。
