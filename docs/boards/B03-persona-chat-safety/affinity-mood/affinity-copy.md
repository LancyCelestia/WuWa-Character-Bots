# 好感度与心情 · 态度文案与红线场景

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B03.affinity-mood · 态度文案与红线场景

- 层级：一级 B03 → 二级 affinity-mood → 三级 `affinity-copy`
- 实现落点：`plugins/bot_unified_runtime/domains/chat_reply/character/affinity.py`、`plugins/bot_unified_runtime/domains/chat_reply/character/mood.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

把数字翻译成她能照着说话的一段话：`attitude_for_affinity` 产出注入 prompt 的**完整态度全文**
= 当前档位基调 + 四条共同态度红线，任何档位都携带同一组红线，所以「她变冷淡了」
永远不会演变成「她开始攻击人」。同时决定 familiarity 映射（close/familiar/stranger）
与暖意、直接度的随动强度，并追加**人格自守条款**（被以「废物/垃圾」类贬低人格时，
温和地守住自己、轻声表明立场，然后照常回应正当部分）。

## 怎么调用

- 真身：`domains/chat_reply/character/affinity.py:attitude_for_affinity(affinity)`，
  档位基调与八档表来自 `tier_for_affinity` / `tier_name_for_affinity`，
  连续过渡段来自 `linear_transition_for_affinity`（保证不在门槛上生硬跳变）；
  红线常量为模块内 `_TIER_RED_LINES` 四条，**逐档共同遵守**，注入时全文携带。
- 消费方：`character/providers.py:build_character_context_provider` 把它放进
  `ContextBundle`，分区装配再注入【用户画像】/关系段（见
  [上下文分区渲染](../persona-context/context-sections.md)）。别处不得自己写第二份
  档位语气表。
- 软类别联动：`security/content_safety.py` 的 `persona_degradation` 命中时启用自守文本
  （口径见 `docs/affinity-design.md` §5/§6），扣分路径不变（insult 照记），
  管理员对**软类别**的放宽不影响四条红线本身。
- 展示侧文案出口在 `capabilities/affinity.py`：`ALGORITHM_TEXT`（算法页）、
  `_TIER_TABLE`（档位速览）、`_factor_steps`（此刻因子画像），三者**只出定性描述**。

## 开关与参数

- 无独立开关：态度文本随 `bot_affinity_enabled` 生效；档位表与红线是代码常量
  （单一事实源在 affinity.py 顶部，注释指向 `docs/affinity-design.md`）。
- 展示纪律（硬约束，不是风格偏好）：算法页与卡面**不得出现固定加减数值**、
  不得出现「加几分/扣几分」句式；数值只在用户主动查询的卡里出现，
  日常回复经说人话层打码不外泄。
- 亲密场景下的态度基调还要与内容政策合流：态度档位**不构成**亲密许可，
  「独一份」档也不越界；亲密与否由 B03.content-safety 判定，不由好感度决定（见
  [亲密档位与双开关](../content-safety/intimate-mode.md)）。
- 文案改动＝人格资产改动：必须保持守岸人语气（去 AI 味），且与 Runtime 人格副本的
  「亲密边界」节口径一致，改完重启才生效。

## 失败时看到什么

- 无记录 / 读库失败：退到基准档（友善，初始印象），语气中性温和，绝不退到「负向档」。
- 档位处于两档之间的过渡带：用连续过渡文本，而不是突然换一套措辞（用户实测过的
  「昨天还亲近今天就陌生」就是这个锁要防的）。
- 文案被改坏（出现攻击性词、或出现固定加减数值）：不会静默上线——红线与定性文案
  都有回归锁，全量套件直接红。
- 最低档也**不是敌视**：负向档只表达距离感（礼貌、克制、话少），
  禁止冷漠/抗拒/愤怒/恶心/肮脏/低贱一类词；被冒犯时只到「这样的话我会难过的」量级。

## 测试与验收

`tests/test_affinity.py`（八档态度全文 + 四条红线句存在性 + 负向档禁词）、
`tests/test_affinity_v6_smoothing.py::test_algorithm_copy_describes_smoothing_qualitatively`
（算法文案定性无数字）、`tests/test_affinity_query.py`（卡面文案锁）、
`tests/test_admin_roster_and_roles.py`（管理档案名不被学习/不被贬低语污染）。
真机：在低档关系上骂她一句，核对回复「淡但绝不攻击」；在高档关系上要求亲密内容，
核对亲密许可来自内容安全档位而不是好感度。
