# 好感度与心情 · 好感度查询

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B03.affinity-mood · 好感度查询

- 层级：一级 B03 → 二级 affinity-mood → 三级 `affinity`
- 路由席位：`AFFINITY`（matcher `affinity`，command=False）
- 判定优先级：41
- 能力 id：`bot.affinity`
- 实现落点：`plugins/bot_unified_runtime/domains/chat_reply/character/affinity.py`、`plugins/bot_unified_runtime/domains/chat_reply/character/mood.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

「好感度」这类话是她**唯一**允许把内心数值摊开给用户看的场合。私聊回双向卡
（她对你的印象 / 你对她的印象）+ 此刻的因子画像（定性方向词）；群聊回本群好感榜
（有印象的成员网格，自己那一行高亮）；带「算法/说明/规则」参数时回算法页。
生效条件是 `bot_affinity_enabled` 为真——这个键同时门控路由判定与动态好感层，
关掉就是「不认得这个命令 + 不再更新印象」，两侧口径一致，不会出现「能查但不涨」。

## 怎么调用

真身在 `domains/chat_reply/capabilities/affinity.py`：

- `is_affinity_command(text)` ——路由侧谓词，由 `runtime/base_router.py` 的
  `affinity_match` 调用（该谓词第一件事就是查 `bot_affinity_enabled`）；
- `parse_affinity_query(text)` ——取出参数段（`算法` / `说明` / 空）；
- `build_private_payload(...)` / `build_group_payload(...)` / `build_algorithm_payload(...)`
  ——三种卡片载荷，**纯函数**，可离线断言，不碰数据库；
- `build_affinity_capability(affinity_store, config, ...)` ——装配口，注入
  `character/affinity.py:DynamicAffinityStore`（读侧方法 `snapshot`、`factor_profile`、
  `leaderboard`、`sentiment_for`）；
- 档位名与态度文本的唯一来源是 `character/affinity.py` 的 `tier_name_for_affinity` /
  `attitude_for_affinity` / `linear_transition_for_affinity`，卡片侧不得自己写档位表；
- 出图走 B08：独立模板 `affinity_card.html`（清单以 `docs/auto-facts.md` 派生为准），
  渲染失败自动回退纯文本；页脚头像等资源经 `output/bot_avatar.py:bot_avatar_uri`。

## 开关与参数

- `bot_affinity_enabled`（缺省 True）：查询与动态层共用总闸。
- `bot_affinity_db_path`（缺省 `data/user_affinity.sqlite3`，路径键经 runtime_paths
  重映射，改值须重启）。
- 展示口径：`-100~+100`、初始基准 10、八档（`_TIER_TABLE` 与
  `docs/affinity-design.md` §4 同源）——这是**档位口径**，不是算法步长；
  算法页永不出现固定加减数值（见 [态度文案与红线场景](affinity-copy.md)）。
- 榜单长度与预览数由模块常量 `_LEADERBOARD_LIMIT` / `_LEADERBOARD_PREVIEW` 控制，
  是代码常量不是配置键；要改就改常量并过测试。
- 触发形态：中文（含繁体）、拼音全拼与首字母缩写、`affinity` 英文词，带右侧词边界
  防 `affinityqq` 类胶合误触发；全量词表以 `docs/command-catalog.md`
  （`scripts/command_catalog.py` 从 `_HELP_ENTRIES` 生成）为准，本文不列。

## 失败时看到什么

- store 读不到 / 该用户无记录：按基准印象出卡，并在卡上如实表现「还在积累中」，
  不编历史。
- 卡片渲染失败：自动回退纯文本卡体，**契约零破坏**（不会因为出图失败而不回话）。
- 群聊请求看别人的具体分值：只给榜单口径（相对位置与档位名），不逐个私曝详细数值；
  私聊只回本人的双向卡。
- 算法页在 v7 开关切换时文案不同（v4/v5/v6 版与 v7 版各一套），但**两版都只定性**；
  出现任何「一次加几分」字样即视为回归，文案锁会红。

## 测试与验收

`tests/test_affinity_query.py`（三种载荷 + 文案锁 + 档位边界）、
`tests/test_affinity.py`（档位与红线条款、算法页定性）、
`tests/test_affinity_numerical.py`（读侧数值口径）、
`tests/test_admin_roster_and_roles.py`（管理名册与权限口径）。
真机：私聊发「好感度」→ 双向卡；群里发「好感度」→ 本群榜；发「好感度 算法」→ 说明页
且肉眼确认无固定加减数值；`BOT_AFFINITY_ENABLED=false` 重启后三种形态都回退到
「不认得」（不是报错）。
