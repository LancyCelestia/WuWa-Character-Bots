# v21r5 帮助注册表快照（2026-09-21 凌晨，主会话代 HELP-SNAPSHOT 席拟）

> 用途：另一会话（TTS/前端/KB）帮助面在飞改动（echo.py 05:09/05:17、config.py 05:07）收口后的**对照参考基线**。本快照非哈希门、非契约，仅对照用；其收口后以终态为准。

## 快照值（实跑提取）

- **topics 总数：77**（与 auto-facts 机器册口径一致）
- **categories：3**——管理员专属 / 大模型相关 / 子功能（完整列表按 echo.py `_HELP_CATEGORIES` 顺序）
- **topics 排序串接 sha256 短指纹：`c64c485a0c82ec89`**
- 提取命令：`from plugins.bot_unified_runtime.domains.chat_reply.capabilities.echo import _HELP_ENTRIES, _HELP_CATEGORIES`（PYTHONPATH=工作区）

## 当前红测试期望差异（其收口后应消失）

1. `test_model_admin_and_schedule::test_model_help_is_unique_and_covers_runtime_controls`——运行时 /bot model help body 缺 `/bot model vision mode` 条目（echo.py 05:17 编辑后）。
2. `test_documentation_consistency::test_tone3_config_lines_carry_four_facets`——tone3 config 行四要素不全（config.py 05:07 新键）。
3. `test_runtime_config_loader::test_parity_with_nonebot_dotenv_source`——config.py 新键与 .env 源 parity（在飞中途态）。

## 既有波内基线（对照用）

- v21r5 波域帮助相关全绿基线：doc_sync_gates 门禁、command-catalog.md（2026-09-21 凌晨 --write 重录，53951 字节）、topic=77。

（HELP-SNAPSHOT 完）
