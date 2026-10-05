# 内容安全与亲密模式 · 记忆侧净化同源

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B03.content-safety · 记忆侧净化同源

- 层级：一级 B03 → 二级 content-safety → 三级 `memory-sanitize`
- 实现落点：`plugins/bot_unified_runtime/domains/chat_reply/runtime/content_route.py`、`plugins/bot_unified_runtime/domains/chat_reply/runtime/intimate_control.py`、`plugins/bot_unified_runtime/domains/chat_reply/security/content_safety.py`、`plugins/bot_unified_runtime/domains/chat_reply/security/memory_sanitize.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

记忆侧的净化同源件：把已经进长时记忆库的硬线内容清出去。它**不新增一套判定词面**——清洗面就是 [六条硬线与不可架空](hard-lines.md) 那套的单一来源（同一批共享模式 + 未成年歧义谓词），保证「守界拦一套、清洗另一套」不再可能。产出是一份 `SanitizeReport`（扫描数、命中数、按类别计数）。生效条件：显式跑这条离线入口才动库；在线链路不自动清洗。

## 怎么调用

真身在 `plugins/bot_unified_runtime/domains/chat_reply/security/memory_sanitize.py`；`security/` 下旧同名件已是兼容垫片——用 `python -m` 打进垫片会 import 完就静默退出、参数被吞＝假成功，只准用 canonical 模块路径。

- `sanitize_memory_db(db_path, *, apply=False)`：核心入口；`apply=False` 是 dry-run 只报告不删，`apply=True` 才隔离并删除。
- `_match_category(text)`：先 `normalize_for_matching` 归一再逐条命中，与守界闸共用同一批模式（含未成年 fail-closed 那一条）。
- `resolve_memory_db_path(config)`：从配置字段解析记忆库路径、经 runtime 路径映射到数据根，正文不写死磁盘路径。
- `main(argv)`：命令行入口，`--dry-run` 与 `--apply` 互斥、`--db` 覆盖路径；也可走 `scripts/dev.ps1 -Task memory-sanitize`。

## 开关与参数

- 没有热开关：这是一条需人工触发的离线运维命令，跑与不跑、dry-run 还是 apply 都由操作者显式决定。
- 唯一相关配置是记忆库路径 `bot_memory_db_path`（进路径重映射，逐键语义以 `docs/config-catalog-full.md` 与 `config.py` 真身字段为准）。
- 清洗范围 = 六条硬线 + 未成年（含未成年歧义那一条）。**范围外**——explicit 会话内已放开的授权亲密内容、普通侮辱、强制人格类文本——按 2026-09-20 政策收窄后不再清洗；这条与守界档放开保持一致，别把清洗面写回旧口径。

## 失败时看到什么

- 库文件不存在：返回全零报告（扫描数为零），不崩、也不误报「清了几条」。
- 未配置记忆库路径：打印「无事可做」并以非零退出码结束，绝不拿猜测路径动库。
- 为可审计，删除前把命中行**先复制**进隔离表（带命中类别与时间戳）再删原表行——清空证据不留白。
- 单条判定异常不外抛打断整轮：逐行独立，最坏这一行不命中，保守保留。

## 测试与验收

`tests/test_memory_sanitize.py`：dry-run 不删、apply 走隔离后删除、命中类别与守界闸同源、范围外不清洗。
真机：先 `--dry-run` 核对报告与分类计数，确认无误再 `--apply`；用例数以最近一次 `scripts/dev.ps1 -Task test` 实跑输出为准。
