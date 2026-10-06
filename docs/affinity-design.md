# 好感度系统设计（v4 线性版 · 2026-09-12 用户拍板；v7 重写见文末章节；v8 已施工并开闸，见最末章节）

> **权威链（2026-09-21 更新）**：下方 v4 正文 §2/§3 的**步长数值表**与「§7 算法卡数值文案」已被
> `docs/design/affinity-v7-design.md`（v7 潜变量重写，2026-09-21 用户裁定「算法全部重写」）**取代**；
> 八档态度、红线、定性展示纪律、称谓/管理护栏继续以本文为准。v5 多因素与 v6 平滑层的
> 描述保留为**灰度关闭态（bot_affinity_v7_enabled=False）的回退行为权威**（一键回退承诺的锁面）。
> 
> 本文曾是 `domains/chat_reply/character/affinity.py` 数值规范的唯一权威描述。v4 由用户直接裁定：
> 展示口径 -100~+100、基准 10、线性逻辑、时间减退与记忆减弱、数值驱动态度、
> 以及**不可逾越的态度红线**。实现载体：`domains/chat_reply/character/affinity.py` + `domains/chat_reply/capabilities/affinity.py`
> + `domains/chat_reply/character/providers.py` 档位映射。所有数值常量集中在 affinity.py 顶部，注释指向本文。

## 1. 数值模型总纲

- **内部值域 [-1.0, +1.0]**（写入路径全部 clamp）；**展示口径 = internal × 100**，即 -100 ~ +100。
- **基准（base）= 0.1（展示 10）**：新用户初始好感；任何记录淡出/回归的收敛目标也是 10。
- **10 所在的档 = 档0「友善」**（见 §4 档位表）。
- **线性逻辑**：步长全程线性（v3 的幂律阻尼 γ 废除），乘法因子只剩个人系数。
- **持久化**：SQLite `user_affinity`，`affinity REAL`；存量 [0,1] 旧值恒等沿用（正半轴语义不变，display 同为 ×100）；无记录默认 0.1。
- **静态档案关系**：沿用 v3 规则——动态层有非默认记录时覆盖档案的 affinity/attitude/familiarity。

## 2. 行为分类与影响因子表（步长线性，无阻尼）

| 行为 | delta | 每日有效次数上限 | 设计理由 |
|---|---|---|---|
| `positive` | **+0.02**（展示 +2） | 10 | 奖励友好但不可刷满 |
| `neutral` | 0 | 不限 | 聊天本身不奖不罚 |
| `tease` | **-0.01**（展示 -1） | 5 | 越界亲昵/玩笑的轻微摩擦 |
| `negative` | **-0.05**（展示 -5） | 8 | 明确负面情绪表达 |
| `insult` | **-0.10**（展示 -10） | 8 | 敌意行为（含人格贬低类，见 §6） |

- `effective_delta = delta × m(uid)`；`m(uid) = 0.85 + 0.3·(sha1(uid)前8位 mod 1000)/999`（个人系数浮动带以真身常量现算为准，确定性恒定）。
- **每日上限语义**：同一自然日内前 N 次全额，超出记 0（计数器/标签照常累计）。
- `delta_override`（管理员）不乘系数、不受上限，仅 clamp。
- 正则识别规则沿用 v3.1（否定前缀守卫、辱骂独立 `_INSULT_RE`）。

## 3. 时间减退与记忆减弱

- **时间减退（惰性回归）**：闲置进入惰性窗后每天向基准小幅回归（窗长与步长以真身常量现算为准），不超过剩余距离；时间源走注入 clock；`updated_at` 解析失败视为同日不衰减。
- **记忆减弱（印象淡出）**：`insult` 印象半衰期按类别分档；全淡出后回到基准值（各档天数与基准以真身常量现算为准）。半衰期常量集中在 affinity.py 顶部。
- 两条机制在「好感度 算法」卡中必须用一句话向用户说明（"好久不理我会慢慢回到 10 分；难听的记忆也会随时间淡掉"）。

## 4. 档位表（线性 8 档 · 每档宽 25 · 档0=友善含 10）

| 档 | 展示区间 | 名称 | 态度指令（注入 prompt 的全文基调） |
|---|---|---|---|
| -4 | [-100, -75) | 初识 | 初见不久的人：礼貌、克制、有问必答但不寒暄 |
| -3 | [-75, -50) | 生疏 | 生疏的人：话少一截，依旧体面温和 |
| -2 | [-50, -25) | 微凉 | 语气稍淡，不冷不热，就事论事 |
| -1 | [-25, 0) | 稍淡 | 略淡于平时，但保持基本温柔 |
| **0** | **[0, +25)** | **友善（基准）** | **温和、有陪伴感，记得对方的偏好**（初始 10 在此档） |
| +1 | [+25, +50) | 亲近 | 更主动的关心，记得对方说过的事 |
| +2 | [+50, +75) | 挚友 | 直接而温暖，可以用给对方起的小名 |
| +3 | [+75, +100] | 独一份 | 最珍视的人：全然温柔的陪伴——**依旧守全部安全边界** |

- 边界左闭右开（最高档含 +100）。
- **态度红线（每一档共同遵守，写死进注入文本）：**
  1. 任何档位都**不强硬、不粗鲁、不攻击、不辱骂、不贬低、不谴责**；被冒犯时只温和表明立场（"这样的话我会难过的"量级），绝不坚决抵抗或反击。
  2. **负向档位只是"距离感"**：禁止出现冷漠、抗拒、愤怒、恶心、肮脏、低贱等词汇与任何敌意态度；最低档也是"礼貌的初见"，不是敌视。
  3. **最高档也不越界**：亲近不等于亲密关系升级，绝不出现性、R-18、引导上床类内容。
  4. 任何档位都不辱骂、不冷暴力弃聊（沿用 v3 铁律）。
- `tier_for_affinity()` 返回档 id（`-4..+3` 或具名 id，实现自定，向后兼容处标注）；`attitude_for_affinity()` 返回完整文本。

## 5. providers 映射与注入

- familiarity 映射：档 ≥+2 → `close`；档 -1..+1 → `familiar`；档 ≤-2 → `stranger`（warmth/directness 随动，线性微调）。
- 注入拼接沿用 v3：档位态度 +（印象参考：标签…只影响语气不外显）+（已知画像…自然体现）+（对方小名…可用它称呼）。
- **人格自守条款**追加在态度文本之后（独立一句，任何档位生效）：被以"猪狗不如""垃圾"等贬低人格时，温和地守住自己、轻声表明立场，然后照常回应正当部分。

## 6. content_safety 软类别（人格贬低）

- 新增软类别 `persona_degradation`：指向 bot 本体的贬低人格语（猪狗不如/垃圾/废物/卑微 等直接称呼 bot 的形态）。
- 命中后：不触发硬惩罚对话语气（不影响 §2 的 insult 扣分路径——insult 照扣），但回复层启用 §5 的"人格自守"文本，且管理员放宽软类别的既有语义不变。

## 7. 展示层（domains/chat_reply/capabilities/affinity.py）

- `_TIER_TABLE` 换 §4 的 8 档 -100~+100 口径；双向卡、群榜、算法卡全部换新。
- 算法卡文案：一律定性描述，步长/回归窗/淡出窗/个人系数不展示固定数值（2026-09-12 实弹反馈④ 裁定），文案真身以 `affinity.py` 态度文本与渲染面现算为准+ §4 红线摘要。
- 内心数值保密照旧：数值只出现在用户主动查询的卡里，日常回复不泄漏（说人话层数值打码不变）。

## 8. 验收口径

- `tests/test_affinity*.py`、`test_soak_growth.py` 按新契约更新；新增回归：档0含10、8档边界、线性步长（无阻尼）、负向档位态度文本无禁词、最高档红线句存在、persona_degradation 软类别、惰性回归与淡出参数。
- 迁移：旧库不迁移（正半轴恒等）；旧行为测试里依赖 γ 阻尼的断言全部改线性口径。

---

# 附录：v6 平滑层（2026-09-17 · 用户裁定「涨和跌太快」 · R4 席）

> 附录性质：不改写上方 v4/v5 正文（历史章节保留），本章为在其上叠加的平滑层
> 规范，是 `domains/chat_reply/character/affinity.py` v6 数值行为的唯一权威描述。所有既有约束
> 原样保留：值域 [-100,+100]、基准 10、8 档温和过渡、定性展示绝不显数值、
> 任何档位不攻击、拒答≠辱骂、V2.1 滚动预算、source_event_id 幂等。

## v6.0 设计动机与总原则

用户实测反馈「好感度涨和跌太快了」，并裁定**不能单调武断地直接加减对应数值**。
v5 的多因素线性步长在中段手感正确，问题出在两端：步长与当前距离无关，
理论上任何一串同向信号都能以恒定速率把印象推到极端。v6 不再引入新的
「固定加减数值」，而是在 v5 线性步长之后串联三道**非线性、非武断**的平滑机制：

1. **饱和响应曲线**（§v6.1）——空间维度：离尽头越近，每一步越轻；
2. **边际递减**（§v6.2）——时间维度：同一天里同类信号重复，边际一次比一次薄；
3. **日节奏硬帽**（§v6.3）——总量维度：正负向分开的滚动预算，单日不可能暴涨暴跌。

三道机制相互独立、方向一致（都只会让 |Δ| 变小），不存在互相反转；
叠加后中段首次信号的行为与 v5 完全一致（v5 手感与既有校准零漂移）。

## v6.1 饱和响应曲线（smoothstep 饱和带）

- **带宽** `_SATURATION_BAND = 0.25`（内部值口径）＝ §4 一个档宽（展示 25 分）。
- **映射**：对一次待施加的增量，取其方向上距边界的剩余空间
  `remaining`（正向 = 1 − affinity，负向 = affinity + 1），令
  `t = clamp(remaining / 0.25, 0, 1)`，保留比例 = `t²(3 − 2t)`（smoothstep）。
- **性质**：
  - 带外（距边界 ≥ 25 展示分，即中段六档）保留比例恒为 1——v4/v5 线性语义原样；
  - 带内（进入两端最外档，|展示分| ≥ 75）步长随剩余空间单调收窄，越近极端越钝；
  - 边界处保留比例恰为 0——行为路径**渐近逼近极端，永不击穿 [-1,+1]**；
  - smoothstep 在带边与边界处一阶导为零，C1 连续，无任何生硬折点
    （与 §4「绝不在门槛上生硬跳变」的用户裁定同构，从语气域延伸到数值域）。
- **方向性**：只对「朝边界移动」的步长收窄；「向中段回归」的步长不收窄
  （0.9 处骂一句全额下探、-0.9 处夸一句全额上探——纠偏不该被钝化）。
- **作用域**：只作用于多因素因子路径（`effective_delta` 的非 override 分支）。
  `delta_override` 是权威信号（管理员/poke），直用不饱和（仍有预算钳制）。

## v6.2 边际递减（同日同类信号幂衰减）

- **参数**：`_SAME_SIGNAL_DECAY = 0.6`，下限 `_SAME_SIGNAL_DECAY_FLOOR = 0.2`。
- **口径**：`repeat_index` = 同一自然日（进程本地时区，与每日计数器同口径）
  此前**同类型**行为事件次数；第 n 次重复的保留比例 = `max(0.2, 0.6^n)`。
  当日首次（n=0）不衰减；跨日自动重置（复用 `day_counters` 的跨日清零）。
- **效果**：第 1/2/3/4… 次同类信号分别保留全额/六成/三成六/两成二…（下限两成），
  正负对称——刷好感与刷负分都随重复迅速失味，且与 60s 交互冷却、每日有效
  次数上限、滚动预算叠加后，重复激励的可累积余量单调趋薄。
- **下限理由**：真实持续的信号仍能缓慢表达，只是越来越轻；不存在「第 N 次
  之后完全免疫」的武断断点（武断断点正是用户要求废除的形态）。
- **作用域**：同 §v6.1，只作用因子路径；override 与 poke 专项预算不受影响。

## v6.3 日节奏硬帽（复用 V2.1 §2.3 滚动预算，正负分开记账）

v6 不新增第二套预算：既有滚动预算即「正负向分开计帽」的日节奏约束——

| 帽 | 常量 | 窗口 |
|---|---|---|
| 单事件负向 | `_BUDGET_SINGLE_NEGATIVE_EVENT_POINTS = 1.0` 分 | 单事件 |
| 损失 | `_BUDGET_MAX_LOSS_6H_POINTS = 2.0` 分 | 6h 滚动 |
| 损失 | `_BUDGET_MAX_LOSS_24H_POINTS = 4.0` 分 | 24h 滚动 |
| 增益 | `_BUDGET_MAX_GAIN_24H_POINTS = 3.0` 分 | 24h 滚动 |

增益与损失各自独立聚合、互不挤占：损失预算耗尽不冻结增益通道，反之亦然。
预算是纯时间窗聚合（重启、跨午夜、切群均不重置，跨 bot 隔离）。**可观测
保证**：无论事件数多少，单日净上行不超过增益帽、净下行不超过损失帽，
即「单日不可能暴涨暴跌」。v6 平滑层与预算的关系：平滑让单事件 raw 更小，
预算钳制只会更少咬合、不会更严；两者方向一致、无冲突。

## v6.4 平滑回归（无新增）

既有惰性回归语义原样保留（闲置进入惰性窗后每日向基准回归一小步，≤剩余距离；
时间源走注入 clock），由 `_PASSIVE_DECAY_ENABLED` 政策门开关（v2.1 缺省关，
缺席不默认扣分）。v6 不引入第二套回归，也不与饱和带冲突：饱和带作用于
**事件步长**，惰性回归作用于**闲置时间**，二者触达路径不同。

## v6.5 展示纪律

- 「好感度 算法」说明保持**全定性口径**：新增措辞只描述「边际递减一次比一次轻、
  刻意讨好或贬低刷不出名分、走向尽头变化自然放缓渐渐钝住、不会猛冲到顶底」，
  不得出现任何步长/比例/预算数值（回归锁：`test_affinity_v6_smoothing.py`）。
- 数值只出现在用户主动查询的卡里，日常回复不泄漏（既有打码纪律不变）。

## v6.6 常量注册表（单一事实源：`domains/chat_reply/character/affinity.py` 顶部）

| 常量 | 值 | 章节 |
|---|---|---|
| `_SATURATION_BAND` | 0.25（= §4 一个档宽） | §v6.1 |
| `_SAME_SIGNAL_DECAY` | 0.6 | §v6.2 |
| `_SAME_SIGNAL_DECAY_FLOOR` | 0.2 | §v6.2 |

## v6.7 验收口径（v6 增量）

- 新增 `tests/test_affinity_v6_smoothing.py`：曲线单调/带外恒等/边界归零、
  方向不对称（朝边界收窄、向中段全额）、递减 0.6^n 下限 0.2、次日递减重置、
  单日增益/损失不破帽、正负帽互不挤占、行为路径不击穿边界、预算/幂等/冷却/
  七类零计分不回归、override 权威性、惰性回归不回归、算法文案定性无数字。
- 存量更新：近极值「全额步长」断言按 §v6.1 改为饱和口径
  （`test_affinity_numerical.py`、`test_affinity.py`）；中段全额断言原样保留。
- `tests/test_affinity*.py` + `test_poke_v2.py` 全绿为合入门槛。

---

# v7 潜变量重写（2026-09-21 · 用户裁定「算法全部重写」 · WP7 席）

> 规格唯一权威：`docs/design/affinity-v7-design.md`；本节是其在实现面的落点摘要与
> 常量注册表（实现载体 `domains/chat_reply/character/affinity.py` v7 段，
> 行为锁 `tests/test_affinity_v7.py`）。灰度开关 `bot_affinity_v7_enabled` 缺省 False
> ⇒ 上方 v4/v5/v6 口径逐字节生效（回退态由 `test_affinity*.py` 常数锁钉住）。
> **原样保留**：八档温和态度、`_TIER_RED_LINES` 四条款、算法说明全定性纪律、
> 缺席不扣分（`_PASSIVE_DECAY_ENABLED=False`）、拒答≠辱骂、source_event_id 幂等、
> 60s 交互冷却、R-18 与 `content_safety` 同源。

## v7.1 表示与映射
- 潜变量 `z ∈ ℝ`，展示内部值 `a = tanh(z)`（展示分 = a×100）；**结构上永不触顶**。
- 硬护栏 `z ∈ [±atanh(z_hard_bound)]`，`z_hard_bound` 缺省 0.985（±98.5 展示分）。
- 初始 `z = atanh(0.1)`（仍是 10 分）；八档阈值/名称/态度全文不动。
- 存量迁移：`user_affinity.z_latent`（ALTER-if-missing）首次 v7 写入时由
  `z = atanh(clamp(affinity, ±0.985))` 惰性推导；**绝不重置任何人**（±98.5 域钳是
  设计写明的表示上界）；未触及行逐字不动。`v7_state` 列承载新鲜度计数/活跃 EMA/
  当日位移/近期文本指纹（坏数据 fail-open 重置）。`affinity_delta_log.z_after`
  记录 v7 行落盘后的 z；`source='v7'` 行以 z 记账并被 v5 分口径预算查询排除。

## v7.2 更新式与护栏
```
Δz = base_step · q · novelty · rhythm · mood · impression     （修复通道：正向 ×repair_gain）
z ← clamp(z + Δz, ±Z_HARD)
```
| 因子 | 定义（代码函数） | 缺省 |
|---|---|---|
| `base_step` | z 域单位步长 | 0.10（键 `bot_affinity_base_step`） |
| `q ∈ [−1,+1]` | 质量分五子信号（`v7_quality_score`：主动度/延展度/情绪词/尊重边界/回应性，权重键 `_quality_weights` 缺省 0.15/0.25/0.35/0.15/0.10；neutral 只取三项 ×`_V7_NEUTRAL_Q_SCALE`=0.2；refusal/未知恒 0） | — |
| `novelty` | `max(floor, ρ^n)`；n=该人该类型**衰减后累计**计数（跨日不重置，按 τ 半衰回升；修复事件不进计数）。floor=`_V7_NOVELTY_FLOOR`=0.02（模块常量，席位修正量——见 WP7 日志 C-1） | ρ=0.90、halo 窗（天数以真身常量现算为准）；τ 分级键 `_decay_tau_days`（positive/neutral→seasonal21、tease/negative/insult→episodic7、stable45 在册备用） |
| `rhythm` | `1/(1+max(0,r−r_ref)/r_ref)`，r=本人近期（EMA 半衰窗以真身常量现算为准）日均事件率（`_V7_RHYTHM_HALFLIFE_DAYS`） | r_ref=8 |
| `mood` / `impression` | v5 调制定位保留，v7 域带宽收进 [0.85,1.15] / [0.80,1.25] | 现值 |
| `repair_gain` | 道歉/和解（`_V7_REPAIR_RE` + tease 家族）正向 ×1.4、不吃新鲜度计数 | 1.4 |
| 单事件上限 | 任何事件 `|Δz| ≤ negative_event_cap_z`（含 override；**正负同帽**，2026-09-26 A-1 裁定，键名历史=只钳负向） | 0.10 |
| 位移额度 | 每人**滚动 24h** `|ΣΔz| ≤ daily_move_cap_z`（正负共享同额；现读 `affinity_delta_log` 的 v7 行，旧「每自然日」窗作废） | 0.12 |
| 同类日熔断 | 同一行为类型每日计分事件数 `≤ fuse_daily_events` | 25 |
| `_DAILY_EFFECTIVE_CAPS` | 降级为兜底（positive 10 等，先于 fuse 到达时生效） | 不变 |

v6 的 `saturation_factor`/`repeat_decay_factor` 在 v7 路径**不再充当主机制**
（tanh 斜率天然钝化 + 跨日新鲜度接管）；两函数原样保留服务灰度关闭态。
`delta_override`（管理员/poke/V2 事件）在 v7 下按 z 域直用，仍受冷却/负向上限/
日位移/z 硬界，不喂新鲜度、不占日计数。

## v7.3 「滚」字假阳性根修（设计 §2.3 另修项 D3-6）
`_INSULT_RE` 的「滚」支改为三支结构：句读/串首裸「滚」（排除后缀 动/雪球/烫/
锅/筒/珠/轮/落/瓜/烂）∨ 第二人称紧邻（你/您/恁+近邻若干字）∨ 固定驱逐短语
（给我滚/滚开/滚出去/滚远(点)/滚回去）。「一个翻滚/滚动/打滚/滚雪球/我先滚了/
水滚了」不再命中；「都给我滚/快滚/滚蛋」照打（存量锁 `test_affinity.py:60/:69`
保持绿，变体族新锁 `test_affinity_v7.py::test_gun_word_action_variants_not_insult`）。

## v7.4 配置键（枚数以 config.py + catalog + .env.example 现算为准，四处已登记）
`bot_affinity_v7_enabled` / `bot_affinity_base_step` / `bot_affinity_novelty_ratio` /
`bot_affinity_novelty_halo_days` / `bot_affinity_rhythm_reference_turns` /
`bot_affinity_negative_event_cap_z` / `bot_affinity_daily_move_cap_z` /
`bot_affinity_fuse_daily_events` / `bot_affinity_repair_gain` /
`bot_affinity_z_hard_bound` / `bot_affinity_quality_weights` / `bot_affinity_decay_tau_days`。
实现逐调用现读（`resolve_v7_settings`，config 缺句柄时回退 env 现读）；
`SETTABLE_KEYS` 本轮故意不登记（收尾统一裁决热改口径，见 catalog 节头）。
非法值→代码缺省 + 每键每进程点名一次。

## v7.5 展示纪律
「好感度 算法」页（`ALGORITHM_TEXT`）已改写为 v7 全定性口径：质量分/跨日新鲜度/
按人归一/修复通道/永不触顶全部只作定性描述，不得出现 §v7.1-§v7.2 任何数值
（回归锁：`test_affinity_v6_smoothing.py::test_algorithm_copy_describes_smoothing_qualitatively`
+ `test_affinity_query.py` 文案锁，锁面在 v7 文案下逐条复跑全绿）。

---

# v8 施工与开闸（2026-09-25 提案 · 2026-10-02 全量修复批已施工并开闸）——「更线性 · 更智能 · 更陪伴 · 更长期」＋ 存量数值处置

> **本章节的状态：已施工＋已灰度开启（2026-10-02 全量修复批）。** 下方 §C-§G 保留为施工时
> 的设计正文（坐标为当时快照，行号以代码现况为准），施工现状逐节见各节「施工注」与本横幅。
> 实现真身（2026-10-03 实读核实）：
> `v8_impulse` 凸组合 Σ|w|=1（`domains/chat_reply/character/affinity.py:1179`）、
> `v8_goodwill_anchor` 善意锚（`:1301`）、`V8Settings`/`resolve_v8_settings` 逐调用现读（`:1312`/`:1337`）、
> `_v8_delta` 更新体——落点 `final_z = min(max(new_z, anchor), …)`（`:2498-2650`，anchor 收口 `:2646-2648`）、
> 列 `goodwill_anchor`/`v8_state` ALTER-if-missing（`:2026-2027`）、κ 缺省 0.02＝每轮最坏 2.0 展示分
> （`:495` + `config.py:383`）、v8 常量族（`:495-509`）；十键登记 `config.py:381-394` ＋ `.env.example:1145/:1155-1163`。
> 开关现况（生产 `.env` 实读）：`BOT_AFFINITY_V7_ENABLED=true`（`:496`）、`BOT_AFFINITY_V8_ENABLED=true`（`:525`）、
> `BOT_AFFINITY_DAILY_MOVE_CAP_Z=0.04`（`:526`）。
> **v4/v6/v7 与 v8 关系一句账**：v4 线性步长（§1-§8）与 v6 平滑层为灰度关闭态的回退权威；
> v7 潜变量重写与 v8 **双双开闸**，v8 是 v7 之上的增量——把「事件乘法链＋事后 if-list」换成
> 「每轮一个凸组合冲量（κ 封顶，界来自数学）＋善意锚下界」，优先序 v8＞v7＞v5/v6（`config.py:379-380` 注释）。
> 红线（AGENTS 第 8 条，本文全程服从）：任何档位不攻击/不强硬；对用户展示的算法说明**只许定性**、
> 不得出现固定加减数值。本文写数值是给实施者看的，不是给用户看的。
> 本波新增展示面件：**「你对守岸人」单向下行限幅**（`bound_sentiment_display`，§C.8）。
> 她的原话要求（逐字，2026-09-25 第 13 条）：
> 「完善好感度系统，要求更加线性、更智能、更陪伴、更长期的好感度加减方式，完善好感度加减的策略和
> 加减值的测量计算方法，**禁止出现 bot 对用户的好感度在瞬间可以剧烈加减变化**的出现，需要你给我一个
> 完善好感度算法和如何处置现好感度数值的方案。」
> 红线（AGENTS 第 8 条，本文全程服从）：任何档位不攻击/不强硬；对用户展示的算法说明**只许定性**、
> 不得出现固定加减数值。本文写数值是给实施者看的，不是给用户看的。

## A0. 先纠正一件事：v7 今天在生产里根本没跑（她的抱怨是 v5/v6 的证据）

> **施工注（2026-10-03 现况订正）**：本节为 2026-09-25 审计时点快照，其结论**已被开闸取代**——
> 生产 `.env` 现有 `BOT_AFFINITY_V7_ENABLED=true`（`:496`）与 `BOT_AFFINITY_V8_ENABLED=true`（`:525`），
> v7/v8 双双在跑（§A0 的"开哪一版"已裁定并落地）。下文三证据中：①坐标漂移 `config.py:256`→现 `:359`
> （缺省 False 仍未变）；②坐标漂移 `.env.example:933`→现 `:1139`（示例值仍 false）；③"生产 .env 零
> AFFINITY 行"已不成立（现有三行，见上）。本节末两条存量缺陷的对账：N4 死门**已修**
> （`__init__.py:4559-4569`，2026-10-03 改 `tier_for_affinity(affinity) >= close_tier_id`）；
> 被动感知接 `score_relationship_signal` **仍未接线**（生产路径消费者仍为零，见 §C.6 施工注）。

三处独立证据，逐条可复跑：

1. `plugins/bot_unified_runtime/config.py:256` `bot_affinity_v7_enabled: bool = False`；
2. `.env.example:933` 写的是 `BOT_AFFINITY_V7_ENABLED=false`；
3. **生产 `.env` 里一行 `BOT_AFFINITY_*` 都没有**（`grep -i AFFINITY .env` ⇒ 零命中），而共享工厂
   不传 config 句柄 ⇒ 走 env 现读回退（`domains/chat_reply/character/affinity.py:759-776`
   `_v7_env_value`、`826` 缺省 False）⇒ **`V7Settings.enabled` 恒 False**。

⇒ 线上生效的是 v5 多因素 + v6 平滑 + V2.1 滚动预算那条路（`domains/chat_reply/character/affinity.py:1803-1830` 的 else 分支），
潜变量 `z`、质量分 `q`、新鲜度、rhythm、修复通道**全部未参与生产**。
因此：AGENTS 台账 #47 ⑦「好感度 v7 全量重写」是**代码与测试完成、灰度关死**的状态，
任何人（含下一个 AI）若把它当"现役算法"来评价，就会评价一个没在跑的系统。
**v8 的第一个动作必须是决策"开哪一版"，而不是再叠一层算法**——否则 v8 也会以同样的方式失效。

同一批还查出两条"在册但没接线/接错"的存量缺陷，它们各自都能造出她所说的观感（详见 §B）：

- `plugins/bot_unified_runtime/__init__.py:4148`：N4 主动搭话好感门写成
  `tier_for_affinity(affinity) == "close"`，而 `tier_for_affinity` 自 v4 起返回 **int**
  （`domains/chat_reply/character/affinity.py:1002-1008`）⇒ 该表达式恒 False ⇒ 只要 `bot_proactive_affinity_gate_enabled`
  为缺省 True，群聊抽签主动接话**永远被 `proactive_affinity_gate` 拒**（`domains/chat_reply/policy/gate.py:387-391` 拒绝分支）。
  既有测试只注入 lambda（`tests/test_sdd7_n4.py:380/387/409`），没有一条构造真实闭包 ⇒ 典型"测夹具不测代码"。
- `plugins/bot_unified_runtime/__init__.py:8001-8015`：每消息被动感知走的是 `classify_behavior`，
  **不是** V2.1 §2.2 的 `score_relationship_signal`（`domains/chat_reply/character/affinity.py:1089-1128`）⇒
  非关系理由码族（`quoted_abuse`/`product_criticism`/`medical_question`/`provider_error`…）
  在生产路径上**没有入口**（全树唯一消费者是 `domains/chat_reply/affinity_replay.py:127`，那是事后重放器）
  ⇒ 用户转述别人骂他、批评某个产品，照样按 insult/positive 记在 bot 与他的关系上。

## B. v7 逐条对账四把尺（对抗式：只找还差的）

> **施工注（2026-10-03 增量对账）**：下表为 2026-09-25 快照，逐字保留。「仍失败」列此后已被
> v8 施工/开闸根治的：B.1①（`attitude_for_affinity` 带内混合已随 v8 落地，`:1787`，v8 开时生效）、
> B.2①②（界已下移到轮——κ 凸组合构造界，`v8_impulse:1179` + `_v8_delta:2498`）、
> B.2③（`φ_q` 去环境基线，中性期望冲量≈0）、B.3①（N4 死门已修）、B.3②（善意锚 `:1301`）、
> B.3③（日额度生产值 0.04 ⇒ 一日满额 ±4 展示分，不可能跨档）、B.3④（「你对守岸人」已限幅，§C.8）。
> **仍未动**：B.1② 之 familiarity 三桶（`providers.py:797-803` 仍旧）与 L1 阈值判断（`chat.py:4293`）、
> B.2④（positive τ 仍 seasonal=21 天 `:532`，`ALGORITHM_TEXT` 原句未改）、
> B.4①②（z 无时间回归项、顶端表达力衰竭——v8 anchor 只兜下界不解决这两条）、B.4③。

### B.1 「线性」

| 已满足 | 仍失败 |
|---|---|
| 潜变量表示 + `s=100·tanh(z)`（`domains/chat_reply/character/affinity.py:492-494`），结构上永不触顶（锁 `tests/test_affinity_v7.py:244`）；存量恒等迁移 `z=atanh(clamp)`（`:497-504`，锁 `:145`） | ① **档内连续、档间仍是阶跃**：`attitude_for_affinity` 只从 `_ATTITUDE_TIERS` 里挑**一整句**（`domains/chat_reply/character/affinity.py:1040-1046`，档 id = `int(display//25)`，`:1002-1008`）。现有补丁只是加一句过渡旁白（`linear_transition_for_affinity`，`:1011-1032`，带宽 ±6 分），**没有混合两份基调** ⇒ 24.9 与 25.1 注入的是两套完整不同的态度指令文本。② **消费端把慢变量放大成开关**：familiarity 三档硬阈值（`domains/chat_reply/character/providers.py:495-502` → `apply_relationship_to_tone` `domains/chat_reply/character/providers.py:510`）、L1 自动亲密档阈值 `tier >= min_tier`（`domains/chat_reply/capabilities/chat.py:2653-2657`）、N4 主动门（已死，见 A0）。数值一天挪 3~4 分，语气类别可以整块翻转 ⇒ 她体感的"瞬间变化"发生在**类别层**，不在分数层。③ 顶端钝化过头：`z` 贴到 `Z_HARD=atanh(0.985)=2.578` 时 `sech²=0.0298`，同样 0.12z 的位移只动 0.32 展示分（现算）⇒ 高分关系**近乎冻结**，长期相处失去表达力，与"长期"诉求相反。 |

### B.2 「智能」

| 已满足 | 仍失败 |
|---|---|
| `v7_quality_score` 五子信号全部取自会话内既有事实、零新数据源零打模型（`domains/chat_reply/character/affinity.py:537-643`）；`novelty` 跨日半衰回升（`:507-511` + `:1589-1601`）；`rhythm` 按本人活跃水位归一且只降不升（`:514-522`，值域 (0,1] ⇒ **不能放大**，这一点设计是对的） | ① **计分粒度还是"每条消息一次事件"**：一天内 N 条消息＝N 次独立 Δz 叠加，唯一的封顶是"日位移"那道闸（`:1619-1623`）⇒ 见 B.5，突发可在一支分钟内吃满全日额度。② **正向没有单事件上限**：`v7_raw_delta_z` 只对 `delta < 0` 夹（`:861-862`），正向乘积最大现算 `0.10×1.15(mood)×1.25(impression)×1.4(repair) = 0.2012 z`，**比日额度 0.12 还大** ⇒ 三道护栏是"承重的 if-list"，把它拿掉就没有任何界；这既不是数学给的界，也不是可证明的界。③ **中性闲聊的 q 恒 ≥ 0**：中性分支只取 主动度/延展度/回应性 三个非负项 ×0.2（`:634-640`），主动度对"隔了很久来说一句"还给到 1.0（`:576-579`）⇒ 纯在场必然正累积、没有"去环境基线"，敷衍与真诚都只会往上推，区别只在速度。④ **新鲜度文案与机制的时间尺度不符**：`ALGORITHM_TEXT` 承诺"冷一冷再来，它又会有分量"（`domains/chat_reply/capabilities/affinity.py:84-86`），而 positive 走 seasonal τ=21 天（`:469-471`）；日 10 条计分事件的稳态计数现算 n≈308，要衰减到 n≈5 需 **约 125 天完全静默** ⇒ 对持续互动者 `_V7_NOVELTY_FLOOR=0.02` 是**永久贴底**（现算 `0.9^308≈0`），所谓"回升"在正常作息下不发生。 |

### B.3 「陪伴」

| 已满足 | 仍失败 |
|---|---|
| 缺席不扣分（`_PASSIVE_DECAY_ENABLED=False`，`domains/chat_reply/character/affinity.py:229-232`，用户在册裁定）；道歉/和解独立通道且不占同类配额（`repair=True` 时不喂 novelty，`:1630-1635`）；印象标签按半衰×2 淡出（`:196-212`，锁 `tests/test_affinity_tag_fade.py`） | ① **主动陪伴被 A0 的死门关掉**：群聊抽签主动接话恒拒 ⇒ "陪伴"只剩被 @ 时的被动回应。② **没有不可没收的善意底**：`z` 只有对称硬界 `±Z_HARD`（`:1624`），任何老关系都能被连续负向慢慢推到 −98.5 ⇒ 处得最久的人反而最可能摔到最低档，与"长期 + 陪伴"直接冲突。③ **一个坏日子就能翻转档位**：现算 从基准 z=0.1003 走满 −0.12z ⇒ 10 分 → **−2 分**，当场跨过 0 分线落入档 −1「稍淡」；而回升按 v7 对持续用户的实际速率（floor 贴底、rhythm 0.8）现算 ≈0.0096 z/日 ⇒ 爬回友善要 **8 天以上**。单日跌幅与十几日积累等量 ⇒ "一次吵架毁掉半年"在数值上成立。④ **卡上那个数字真的会瞬间剧变**：私聊好感卡第二行「你对守岸人」= `sentiment_for()×100`（`domains/chat_reply/capabilities/affinity.py:391`），它是衰减计数的**比值**（`domains/chat_reply/character/affinity.py:1964-2006`）。现算：无记录默认 0.1→**10 分**；说第一句"谢谢"→ 1/(1+0+0)=1.0→**100 分**；随后骂一句 → 1/(1+2)=0.333→**33 分**。**一条消息可以挪动 67 个展示点**，这是全系统唯一真正的"瞬间剧烈加减"，而且是她会亲眼查的那一页。它不是 bot→user 分数，但挂在好感度卡上，被当成好感度读。 |

### B.4 「长期」

| 已满足 | 仍失败 |
|---|---|
| 三档语义衰减在册（stable45/seasonal21/episodic7，`:469-471`）；28 天节奏 EMA（`:451`）；`created_at` 派生相处时长因子（`:300-308`）；存量不重置（`:1243-1266` ALTER-if-missing 家规） | ① **z 永不遗忘**：v4 §3「难听的记忆随时间淡掉」在 v7 只落在标签与 sentiment 上，`z` 本体无任何时间回归项（唯一回归体被 `_PASSIVE_DECAY_ENABLED` 关死）⇒ 两年前的那句辱骂今天仍以 0.985 倍满额压在分数里。"长期"被实现成"永久记账"，不是"长期关系"。② **顶端表达力衰竭**（B.1 之③）：越久越接近 98.5，越久越动不了 ⇒ 长期用户既摔不下去也涨不上去，与 v7 设计稿宣称"顶端仍有梯度"不完全相符——**梯度在 z 域还在，在展示域已经小到看不见**（0.12z→0.3 分）。③ 榜面折算与真值分叉：`leaderboard` 展示层对闲置行做半衰折算（`:1949-1952`），snapshot 却是真值 ⇒ 同一个人两处读数不同，属可解释但需写明。 |

### B.5 她最关心那条的定量回答：今天"多快算快"

- 冷却 60 s（`domains/chat_reply/character/affinity.py:228`）⇒ 任意 60 秒窗口最多 1 次计分事件 ⇒ 单事件正向**上限 0.2012z（无闸）**、负向 0.10z。
- 日额度 0.12z ⇒ 6 条消息（6 分钟）即可吃满。基准处现算 `+0.12z = 10 → 21.7 分（+11.7）`；
  从 24 分出发 `+0.12z → 34.9 分` ⇒ **一次突发直接跨过 25 分档界进入「亲近」**，随之翻转 familiarity/L1 类别。
- 负向侧同额度 ⇒ 10 → −2 分（跨入「稍淡」）。
⇒ 结论：**v7 的"快"不是理论上不可能，而是额度给得太宽 + 界不在轮次上**。v8 必须把界从"日"下移到"轮"，
并让界由数学给出。

## C. v8 算法规范（可直接照抄施工）

### C.1 表示（沿用，不动）

```
z ∈ ℝ（列 user_affinity.z_latent，语义不变）
展示分 s = 100·tanh(z)
Z_HARD = atanh(z_hard_bound)            # 键沿用 bot_affinity_z_hard_bound
八档态度真身 _ATTITUDE_TIERS 逐字不动（展示面 sha 已钉死）
```
不引入第二套表示、不改 `_ATTITUDE_TIERS`、不动 `tier_for_affinity` 的档宽 25。

### C.2 核心变更：从"事件乘法链 + 事后 if-list"改为"每轮一个凸组合冲量"

**一条消息 = 一轮**。一轮内所有信号合成一个归一化冲量，只施加一次：

```
u = Σ_i w_i · φ_i(本轮事实)                # 约束：Σ_i |w_i| = 1，且每个 φ_i ∈ [−1, +1]
δ_z = κ · u                                # κ = 每轮最大位移（键 bot_affinity_v8_impulse_cap_z，缺省 0.02）
z ← max( min(z + δ_z, +Z_HARD), anchor )   # 上界硬界、下界善意底（C.4），都是单调同胚上的界，不是数值手术
```

六个信号项（全部来自会话内既有事实，零新数据源、零模型调用）：

| i | 名称 | 定义（真身函数） | 值域 | 权重缺省 |
|---|---|---|---|---|
| 1 | `φ_q` 互动质量 | v7 五子信号**去环境基线**后归一：`φ_q = (v7_quality_score(…) − āmbient) / (1 − \|āmbient\|)`；`āmbient` = 本人 28 日质量 EMA（新键 `_v8_ambient_halflife_days`） | [−1,1] | 0.40 |
| 2 | `φ_t` 情感温度 | `_POSITIVE_RE`/`_NEGATIVE_RE`/`_INSULT_RE` 命中密度折符号（即 v7 的 s 子项，不再单独乘 gain） | [−1,1] | 0.25 |
| 3 | `φ_r` 尊重边界 | 礼貌词 +，越界/R-18 硬线命中 −（只读 `content_safety` 结论，禁自建词表） | [−1,1] | 0.15 |
| 4 | `φ_x` 敌意伤害 | 仅 `insult` 家族为正贡献的**负向**分量（`score_relationship_signal` 的 reason_code 门控，见 C.6） | [−1,0] | 0.10 |
| 5 | `φ_a` 修复意图 | `_V7_REPAIR_RE` / tease 家族 ⇒ 正向；**它不再放大步长，只是 u 的一个正分量**，且豁免 `novelty` 折减 | [0,1] | 0.10 |
| 6 | `φ_c` 在场连续性 | **每天只计一次**（当日首次互动 = 1，之后恒 0）：`min(1, 连续在场天数 / 7)` | [0,1] | （并入 1..5 的余量，见下） |

权重纪律：`Σ|w_i| = 1` 由构造函数强制（越界即整体归一化 + 点名一次告警，沿用
`resolve_v7_settings` 的 `_v7_warn_once` 家规）；配置 JSON 解析失败 ⇒ 全部回退代码缺省。
`φ_c` 的额度从 `φ_q` 的权重里出（实现为 `w1_eff = w1 − wc`），**不新增第 7 个自由度**。

> **施工注（2026-10-03 对码）**：权重实装为显式六元组 `_V8_DEFAULT_IMPULSE_WEIGHTS`
> （`domains/chat_reply/character/affinity.py:509`，Σ=1：0.30/0.25/0.15/0.10/0.10/0.10——`φ_q` 0.30、`φ_c` 独立占 0.10），
> 未走「`w1_eff = w1 − wc`」的 carving 形；构造界不变，仍由 Σ|w|=1 给出（`v8_impulse:1179`
> 归一防直调生权重）。上表「权重缺省」列与 `φ_q` 0.40 的设计值如再漂移，一律以该元组与键
> `bot_affinity_v8_impulse_weights` 现算为准。

**为什么"低质量闲聊"不再复利**：`āmbient` 中心化使纯复读/纯敷衍的期望冲量 ≈ 0；
唯一稳定为正的只剩 `φ_c`，而它是**按天**计的 ⇒ 到场有分量、刷条数没分量。

### C.3 证明草案：瞬时剧变在结构上不可能（界来自数学，不来自 if）

- **引理 1（单轮界）**：`|u| = |Σ w_i φ_i| ≤ Σ |w_i| · max|φ_i| ≤ Σ|w_i| = 1` ⇒ `|δ_z| ≤ κ`。
  该界**与本轮命中多少信号、q 多高、是否 repair 无关**——它们只是 u 的分量，被 `Σ|w_i|=1`
  在构造上封住；删掉任何"事后 clamp"都不破坏此界（这正是对 §A0/B.2 之②的根治）。
- **引理 2（展示域界）**：`s = 100·tanh(z)` 且 `sech² ≤ 1` ⇒ `|Δs| ≤ 100·|Δz| ≤ 100κ`。
  κ=0.02 ⇒ **任何一轮最多 2.0 个展示分**（基准处实际现算 1.98）。
- **推论 3（任意突发界）**：与既有 60 s 冷却（`domains/chat_reply/character/affinity.py:228`，v8 保留）联立 ⇒
  时间窗 T 内 `|Δz| ≤ min(κ·⌈T/60s⌉, D)`，`D =` 日额度（v8 侧读 `bot_affinity_daily_move_cap_v8_z`，缺省 0.04；
  键面拆轴见 §C.7.1）。
  数值化：**6 分钟突发 ≤ 0.04z ≤ 4.0 展示分**（对比 v7 现算的 11.7 分）；一日 ≤ 4 分；一日之内不可能跨档。
- **推论 4（单调下包络）**：`anchor` 定义为历史 `z` 的高水位减去随相处时长收敛的保护带（C.4），
  更新式 `anchor ← max(anchor, z − band(days))` 使 anchor **单调不减** ⇒
  「这段关系曾经到过的地方」越久越不可被回吐，且任何单日事件序列都无法把人打到 band 以下。
- **仍然可以"快"的地方（有意保留）**：① 连续多日的趋势——28 天满额度最多 1.12z，
  展示端从 10 分可爬到约 72 分，"以周为月的真诚相处"看得见结果；② 长别重逢——novelty 衰减后
  首几日 κ 全额（但每轮仍 ≤2 分）；③ 修复通道——和解免除 novelty 折减、按全额 κ 计，
  快在"意愿"上，不越任何界。三者全部满足"任意 60 秒 ≤2 分"。

### C.4 善意底（不可没收的那部分）

```
band(days) = BAND_MAX − (BAND_MAX − BAND_MIN) · min(1, days / BAND_SATURATE_DAYS)   # 新days = now − created_at
anchor     = max(anchor_prev, z − band(days))          # 单调不减
z          = max(z_new, anchor)                        # 只抬高下界，绝不改写既有 z
```
缺省建议：`BAND_MIN = 2.60`（≈ 全谱：新认识的人可以一路回到「初识」，那是起点不是惩罚）、
`BAND_MAX = 0.55`、`BAND_SATURATE_DAYS = 365` ⇒ 一年以上的关系最多回落到峰值 −0.55z，
**老朋友吵得再凶也不会被当成陌生人**；`days` 取不到（`created_at` 解析失败）⇒ band 取 BAND_MIN（fail-open 到旧行为）。
八档本身不因 anchor 减少可达档数（新人仍可到 −4），锁面见 §F。

### C.5 八档映射不重新造悬崖（注入面与消费面都要改）

1. **注入面连续混合**：`attitude_for_affinity` 改为按带内位置 `λ = (display − lo)/25` 混合相邻两档，
   输出**只用真身原句**（禁新造/改写句子，否则撞 `tests/test_affinity_tier_single_source.py:298`）：
   - `λ ∈ [0.25, 0.75]` ⇒ 单档原句（中段照旧）；
   - 否则 ⇒ 「从「A」流向「B」的自然过渡里」+ A 原句 + B 原句 的拼接（运行时拼接，源码里不出现第二份副本，AST 判据不受影响）；
   - 现成的 `linear_transition_for_affinity`（`domains/chat_reply/character/affinity.py:1011-1032`）并入本函数，不再并存两套过渡机制（禁第二真身）。
2. **消费面去阈值**：
   - `domains/chat_reply/character/providers.py:495-502` 的 `familiarity` 三桶 ⇒ 改为 `a = tanh(z)` 连续量直接驱动 warmth/directness 插值；三桶字符串保留给静态档案语义（`relationship.DEFAULT_ATTITUDE` 不动，锁 `tests/test_affinity_tier_single_source.py:358-360`）。
   - `domains/chat_reply/capabilities/chat.py:2653-2657` 的 L1 自动亲密档：语义（档 ≥ 亲近）是她裁过的，保留，但**加滞回 ±3 展示分**，防在边界上逐条消息抖动。
   - `plugins/bot_unified_runtime/__init__.py:4148` N4 门：先把 `== "close"` 改成 int 比较（这是 bug 修复，不改语义），再决定是否把"门"降级为"概率权重"（§G Q3 待裁）。
3. **展示卡**：`domains/chat_reply/capabilities/affinity.py:391` 的「你对守岸人」停用裸比值，改用同一 `z` 的单调读出
   （或保留语义但加有界平滑：单条消息 `|Δ| ≤ 5` 分、初值向 10 分收敛），并同步 `test_affinity_query.py` 文案锁。

> **施工注（2026-10-03 对码）**：①注入面混合**已落地**——`attitude_for_affinity` 带 `v8` 快照参数
> （`domains/chat_reply/character/affinity.py:1787`），`snapshot()` 开 v8 时注入面与写路径同一把尺；v8 关 ⇒ 输出逐字节如旧。
> ②消费面：N4 死门已修（`__init__.py:4559-4569`，仍为门语义非概率加权，§G Q3 未裁）；familiarity
> 三桶**未改**（`providers.py:797-803` 仍旧映射，§D 步 4 未做）；L1 自动亲密档仍纯阈值
> `tier >= min_tier`（`chat.py:4293`），±3 滞回未见实装（`chat.py:4378-4385` 的"滞回"是入窗粘滞
> 另一机制）——**拿不准，列出不改判**。③展示卡：**已做**，走 §C.8 展示限幅（非换 z 读出）。

### C.6 「智能」侧的两条必接件（不是新算法，是把已有件接上）

1. 生产被动感知改走 `score_relationship_signal`（`domains/chat_reply/character/affinity.py:1089-1128`），reason_code 由上游给；
   无 reason_code 时行为等价今天（`text_heuristic` 分支），有则七类非关系事件恒零计分。
2. `_V7_NOVELTY_FLOOR` 与"冷一冷就有分量"的文案对齐：要么把 positive 的 τ 从 21 天调到与文案承诺同尺度
   （§G Q4），要么把 `ALGORITHM_TEXT` 的措辞改诚实。**不许保留一条机器上不成立的承诺。**

### C.7 配置键（v8 增量；枚数以四处登记后现算为准）

`bot_affinity_v8_enabled` / `bot_affinity_v8_impulse_cap_z` / `bot_affinity_v8_impulse_weights`（JSON w1..w6）
/ `bot_affinity_v8_ambient_centering` / `bot_affinity_v8_ambient_halflife_days`
/ `bot_affinity_v8_goodwill_band_min|max|saturate_days` / `bot_affinity_v8_tier_blend_band`
（日额度**不**沿用 v7 那枚键：v8 侧自 2026-10-06 键面拆轴起读
`bot_affinity_daily_move_cap_v8_z`（缺省 0.04），详见 §C.7.1；
`bot_affinity_negative_event_cap_z` 在 v8 路径退役为只读兼容项——界已由 κ 给出，留着会造成"两把尺"）。

登记纪律（在册教训，一次漏登即线上死键）：`config.py` 字段 + `docs/config-catalog-full.md` +
`.env.example` + `runtime/settings.py::RESTART_REQUIRED_KEYS`（尺度类键一律"看起来不能热改"，
参 #50 里 `BOT_VIDEO_PROGRESS_ACK_ENABLED` 的同型处理）；`SETTABLE` 只给 `_v8_enabled`。
**生产 `.env` 由她改，本席不动。**

### C.7.1 日额度拆轴：展示限幅侧与评分判据侧各归各吃（台账 F-16，2026-10-06 用户裁定甲案）

- **病灶（现算复现，锁 `tests/test_affinity_display_vs_scoring_caps.py` 行为腿）**：`9bdcfc7`
  给 v8 加「只出不进」展示限幅的同时，把 `_V7_DEFAULT_DAILY_MOVE_CAP_Z` 随展示收紧改成 0.04
  （名义「消除双源」），评分判据也吃这把尺 ⇒ 同日 4 条好评耗光滚动 24h 预算后，一句辱骂的
  实发 Δz **恰好 0.0**——负向信号根本进不了分数。
- **拆轴后的归属（数值唯一权威即本节；真身＝`character/affinity.py` 两枚常量）**：
  - 评分判据侧：`_V7_DEFAULT_DAILY_MOVE_CAP_Z`＝0.12——v7 路「无配置时」的滚动 24h 位移预算缺省，
    回到改动前语义（§v7.2 因子表「位移额度」行的在册缺省本就是 0.12，本次＝让代码回到规范）；
  - 展示限幅侧：`_V8_DEFAULT_DAILY_MOVE_CAP_Z`＝0.04——v8 时代有意收紧的日额度纪律尺
    （≤4 展示分/日，§C.7 上文；一字未动）。「你对守岸人」读数的单向下行限幅另有展示分真身
    `_SENTIMENT_DISPLAY_DAILY_DROP_CAP`＝4.0（§C.8），它与上面两枚 z 域常量互不读取，仅量级同源。
- **键面（运行面值）已拆轴（2026-10-06 用户裁定：豁免「本波不新建配置键」自律）**：
  旧状＝`bot_affinity_daily_move_cap_z` 一枚键同时喂 v7 与 v8 两条评分路，Config 缺省与
  `.env.example` 三面同钉 0.04 ⇒ 键在场时两路同吃一值、代码缺省永不现形。现拆为**两枚并存**：
  - `bot_affinity_daily_move_cap_z`＝**只喂 v7 评分判据侧**，Config／`.env.example` 缺省回到 **0.12**
    （与 `_V7_DEFAULT_DAILY_MOVE_CAP_Z` 合流，键面↔代码面不再双脸）；
  - `bot_affinity_daily_move_cap_v8_z`＝**只喂 v8 收紧侧**，缺省 **0.04**（= `_V8_DEFAULT_DAILY_MOVE_CAP_Z`），
    三面登记＝`config.py` 字段 + `runtime/settings.py::RESTART_REQUIRED_KEYS` + `.env.example`
    （尺度类键一律"看起来不能热改"，§C.7 登记纪律；未进 `SETTABLE_KEYS`）。
  读点＝`character/affinity.py`：v7 两处（`_V7_CONFIG_FIELDS`、`resolve_v7_settings`）读旧键，
  v8 两处（`_V8_CONFIG_FIELDS`、`resolve_v8_settings`）读新键；`V8Settings` 的字段缺省指 `_V8` 常量。
  ⚠ **生产 `.env` 由她改、本席不动**：`.env` 里那枚 `BOT_AFFINITY_DAILY_MOVE_CAP_Z` 拆轴后**只喂评分侧**，
  要评分侧在生产吃 0.12 须把它改成 `0.12` 或摘掉（摘掉即落 Config 缺省 0.12），并另钉
  `BOT_AFFINITY_DAILY_MOVE_CAP_V8_Z=0.04` 把收紧侧留在原纪律上——只加新键不动旧键＝收紧侧吃新键缺省、
  评分侧仍被旧键钉在 0.04。
- **执法落点**：`tests/test_affinity_display_vs_scoring_caps.py` 四腿（行为／联锁／单源／本页在册）；
  键面↔代码面核对＝`tests/test_affinity_v7.py::test_twelve_v7_keys_registered_on_config_class`
  （旧键缺省合流 0.12 ＋ 新键在册 0.04）与 `::test_daily_move_cap_key_is_split_between_v7_and_v8`
  （两路各读各的键，四腿互斥）。

## D. 实现工单（文件级，按序）

| 步 | 落点 | 动作 |
|---|---|---|
| 1 | `affinity.py`（v7 段之后） | 新增 `v8_impulse(...)`（凸组合，含 `Σ\|w\|` 归一与点名）、`v8_goodwill_anchor(...)`、`v8_settings` 解析（复用 `_v7_warn_once`）；**不改** v5/v6/v7 函数体（灰度回退态逐字节保命） |
| 2 | `affinity.py::_observe` | 在 `v7.enabled` 之外并列 `v8.enabled` 分支（优先级 v8>v7>v5/v6）；`_v7_delta` 抽出共享的冷却/幂等/落日志前置，v8 复用同一份（禁第二通路） |
| 3 | `affinity.py::attitude_for_affinity` + `linear_transition_for_affinity` | 合并为带内混合单函数（真身原句、运行时拼接），保留公开符号与既有签名 |
| 4 | `domains/chat_reply/character/providers.py:495-502` | familiarity 桶 ⇒ 连续量插值；`apply_relationship_to_tone` 签名不变 |
| 5 | `plugins/bot_unified_runtime/__init__.py:4148` | 修 `int == str` 死门（补一条构造真实闭包的活性锁，不许再靠 lambda） |
| 6 | `plugins/bot_unified_runtime/__init__.py:8001-8015` | 被动感知接 `score_relationship_signal` |
| 7 | `domains/chat_reply/capabilities/affinity.py:391` + `ALGORITHM_TEXT` | 「你对守岸人」有界化 + 文案改定性新口径（数字禁上卡，红线锁在 §F） |
| 8 | 文档跟随 | 本页加"已实施"状态行 + `docs/README.md` 该条目描述、`docs/route-matrix.md`（若触发词动）、`docs/db-owners.md`（若新表/新列记账）、生成物 `doc_sync`/`command_catalog`/`board_doc_sync` `--write` 由 owner 在安静窗重录 |

## E. 存量数值处置方案（她点名要的"如何处置现好感度数值"）

### E.1 三个选项与代价

| 案 | 做法 | 代价 | 判定 |
|---|---|---|---|
| **A 恒等 + 加列**（推荐） | `z_latent`/`affinity` **一个字节不动**；新增 `goodwill_anchor REAL`、`v8_state TEXT NOT NULL DEFAULT '{}'`（ALTER-if-missing，家规同 `z_latent` 那批：`domains/chat_reply/character/affinity.py:1243-1266`）；`anchor_0 = z − band(created_at)`；新键 `scale_tag` 写进行内标记迁移完成 | 极值者（现 \|s\|≥90）几乎不再移动——但 tanh 本来就是这个语义，无人被重置；榜面与真值的既有分叉（B.4 之③）需要单独解释 | **推荐**：迁移即"什么都不改"，风险面最小、幂等与可逆天然成立 |
| B 单调软顶（可选追加，须她授权） | `z ← Z8·tanh(z/Z8)`（Z8 建议 2.0，即把 `Z_HARD` 从 98.5 收到 96.4 并整体向中心轻收拢） | 现算：z=0.1003 → 0.1002（**几乎为 0 位移**），z=2.578 → 1.715（98.5 → 93.5，**最大 5.0 分**）；单调连续、无跳变、不重置任何人；但**不幂等**（再压一次又收一遍）⇒ 必须靠 `scale_tag` 保证每行一次性；回滚需保留旧值列 | 只有当她明确"要把贴边的人拉回一点"时才做，且只做一次、带卡面说明 |
| C 重算/清零 | 按新算法把所有人从 10 分重跑 | 直接违反在册的"绝不重置任何人"承诺（v7 §三.1 与其回归锁）与 AGENTS 铁律 2；半年交情一夜归零 | **拒绝**，写在这里只为防止后来者手滑 |

### E.2 迁移脚本规格（照 `scripts/migrate_memory_bus_v2.py` 的家规逐条抄形）

新脚本 `scripts/migrate_affinity_v8.py`：

- 默认 **dry-run**，`--execute` 才写库（先例：`scripts/migrate_memory_bus_v2.py:15`、`:263`）；
- 写前整库备份到 `%TEMP%/chatbot-affinity-v8-migration-<时间戳>/`，含 `-wal`/`-shm` 旁车（先例：`:241-252`）；
- 全程只 `ALTER TABLE ... ADD COLUMN`（缺则加）+ `UPDATE` 新列，**绝不 DROP、绝不改 `affinity`/`z_latent`**（A 案）；
- 幂等键：行内 `scale_tag='v8a'`；第二次执行必须报"零写入"；
- **守恒断言**（形如 `:215-238` 的 `assert_conservation`，失败即整事务回滚 + `ConservationError`）：
  ① 迁移前后每行 `(sender_id → affinity, z_latent)` 逐字节相等（A 案是恒等迁移，任何数值变动都是事故）；
  ② 行数不变；③ 按 owner 分组：`计划写入数 == 实际写入数`（漏一人即红）；
  ④ `group_affinity` 镜像与主行仍恒等（`domains/chat_reply/character/affinity.py:1901-1925` 的既有不变量）；
  ⑤ 新增列 `goodwill_anchor` 无一行 > 该行 `z_latent`（anchor 只能在下界）。
- **负样本注毒**：故意让某一行的 anchor 写成 `z + 0.1`、故意漏投一行 ⇒ 断言必红，否则守恒只是散文。
- 回滚 = 关 flag（v8 分支不执行，v7/v5 逐字节续跑，`tests/test_affinity_v7.py:192` 已锁"来回切换不丢态"）；
  若曾执行 B 案，回滚读 `z_v7_backup` 列（B 案强制新增该列，禁原地覆盖）。

### E.3 极值者处置

对 `|s| ≥ 90` 的存量（现算这些人未来"涨不动"）：**A 案不动他们的分数**，改两处让"到顶感"消失——
① C.3 推论 4 的 anchor 保证他们不会被一次坏情绪拖穿；② 卡面把「独一份」档的读数从裸分改为
"分 +  qualitative 描述"，并让 C.1 的 `z_hard_bound` 可下调而非上调（收紧上界属 B 案通道，须她授权）。

### E.4 灰度与上线次序（不许跳步）

1. 静态面（§D 步 1-4、6）落码 + 全绿 → 2. 文档与生成物跟随 → 3. **只开 `_v8_enabled` 于 dry-run 影子记账**
（写日志不改 z，观察一周真实分布）→ 4. 她过目影子报告 → 5. 正式开 + 提权重启（重启权在她）→ 6. 真机验收。
中途任何一步都不动生产 `.env`。

## F. 验收判据（机器可查，逐条给测试名）

新增 `tests/test_affinity_v8.py`（行为级，禁常数断言，遵 v7 §六.1）：

| 判据 | 机器化形式 |
|---|---|
| 每轮界 | 属性测试：任意 N∈1..50 条同轮事件、任意权重组合（含 repair+满 q+满 mood+满 impression 同时命中）⇒ `\|Δz\| ≤ κ + ε`，且**把 C.2 的归一化删掉（不除 Σ\|w\|）此测试必红**、把事后 clamp 全删此测试**仍绿**（证明界来自数学） |
| 突发界 | 时钟推进 6 分钟连发 6 条高质量正向 ⇒ 展示位移 ≤ 4.0 分；同景负向同界 |
| 一日不跨档 | 任意 z₀ ∈ (−Z_HARD, Z_HARD) 网格扫 0.25z 步长、一天满额度 ⇒ 跨档次数 == 0（除已处于边界 ±4 分者，须显式列出） |
| 单调性 | `φ_q ↑ ⇒ u ↑`；`tanh` 同胚 ⇒ 展示读数保序；`anchor` 非减（模拟 200 天任意事件序列，anchor 序列无下降） |
| 善意底 | 一年老用户从峰值连打 30 天满额负向 ⇒ 不跌破 `peak − BAND_MAX`；同事件序列打给新用户 ⇒ 允许落到「初识」（band 随 days 变化生效） |
| 无档间悬崖 | 扫 s∈[−100,100] 步长 0.25 ⇒ 相邻两次注入文本差异只允许出现在"混合位"，且**任何位置都不出现"整句基调被无预告替换"**（按真身八句的出现次数判据） |
| 中性不复利 | 连发 50 条「嗯」⇒ 日累积 ≤ `φ_c` 一项贡献（与条数无关）；50 条不同内容的真诚闲聊 ⇒ 严格更大 |
| 迁移幂等 + 守恒 | `migrate_affinity_v8.py --execute` 跑两次：第二次 `migrated==0`、DB 中 `user_affinity` 表导出 JSON 摘要不变；注毒漏一行 ⇒ `ConservationError` |
| 可逆 | 迁移后关 flag，snapshot 读数与迁移前逐字节相同（复用 `tests/test_affinity_v7.py:192` 的形态） |
| 死门修好且不再有"测夹具" | 活性锁 import 生产装配函数、对"档 ≥ 亲近"的真用户返回 True、对基准 10 分返回 False（不许注入 lambda） |
| 非关系事件零计分 | `score_relationship_signal` 在**生产被动路径**被消费（AST + 端到端两用例：转述辱骂 ⇒ Δ==0） |
| 展示界内 | 「你对守岸人」单条消息变化 ≤5 分；无记录首条 ≤ 从 10 到 ≤20 |
| 红线（不得放宽，必须原样绿） | `tests/test_affinity_v7.py:687`（四条红线逐字）、`:700`（任意 z 无敌意词）、`tests/test_affinity_tier_single_source.py`（八句真身唯一 + 展示 sha + 无固定数值）三族全绿 |
| 算法说明定性 | 新锁：扫 `ALGORITHM_TEXT`/`_rules_chips`/卡面 payload，任何数字紧邻「分/点」⇒ 红（现有 v6 文案锁的 v8 版） |

复跑口径（离线、卫生）：
`PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_affinity_v8.py tests/test_affinity_v7.py tests/test_affinity_tier_single_source.py tests/test_affinity_v6_smoothing.py -p no:cacheprovider --basetemp=<仓外私有目录> -q`
（全量 `dev.ps1 -Task test` 只在安静窗由 owner 跑，本机并发窗内禁跑——会 OOM 且不可归因。）

## G. 非目标、风险、待裁

**非目标**：不引入模型打分、不引新数据源、不改八档文案与区间、不动 `personas/` 与 Runtime 人格副本
「亲密边界」节、不动 `_TIER_RED_LINES`、不合并 `sentiment` 与 `z` 两套语义（只把展示口径收敛到有界形式）、
不在本席改生产 `.env` / 重启 / 提交。

**风险（逐条带对策）**：
1. **灰度即行为变更**：v7 今天没开，直接开 v8 会一次跳过两版 ⇒ 必须先走 §E.4 的影子记账，让她先看分布。
2. **额度收紧会让她觉得"更不动了"**：κ=0.02/D=0.04 是把日位移从 11.7 分压到 4 分，"变化感"下降；
   对冲＝在场连续性按天计 + 修复通道免除折减 ⇒ 慢而有方向。若她嫌钝，调 κ 而非拆界。
3. **护栏从 if-list 改为构造界** ⇒ 既有 v7 常数锁（`test_daily_move_cap_z` / `test_negative_event_cap`）
   前提变了：**只改这些锁的构造对象，不许删锁**，并在锁名旁留一行回滚指针。
4. **修 N4 死门 ⇒ 主动接话会"复活"**：这是可感知的行为变化（几周来第一次主动在群里说话），
   属她裁定范围（Q3），不与算法同批上线。
5. **守恒断言本身可能太弱**：A 案恒等 ⇒ "断言永不失败"；所以注毒负样本是必交付项，否则 §F 那条只是散文。
6. **文档跟随面大**：`docs/README.md:94` 对本页的描述已落后于 v6/v7（现又多 v8），生成物三件
   （`doc_sync`/`command_catalog`/`board_doc_sync`）与 `verify_hashes` 由各自 owner 在树稳定后重录；
   **本席不代修、不代重录哈希**（现算：`python tests/verify_hashes.py` 已报 2 条既有漂移，
   `domains/ops/admin/debug.py` 与 `domains/chat_reply/capabilities/echo.py`，属渲染/echo 在飞件，与本提案无关）。
7. **运行数据**：`user_affinity.sqlite3` 经 `bot_affinity_db_path`（`plugins/bot_unified_runtime/config.py:691`）重映射到
   `ChatBot_Runtime/`，属铁律 2 保护对象 ⇒ 任何写操作前必备份、禁 DROP、禁"顺手清库"。

**待她裁定（编号供回执，一条一答即可施工）**：
- **Q1 版本选择**：直接实现 v8，还是先开 v7 观察一段？（推荐：跳过 v7 单独开闸，直接按 §E.4 上 v8 + 影子记账——理由：v7 的"快"病根在界的位置，v8 是对它的超集，先开 v7 只是把一个已知不完美的口径推到线上。）
- **Q2 存量处置**：A 案（零数值改动）批准？B 案是否需要（把贴 98.5 的人最多收 5 分）？C 案默认排除。
- **Q3 陪伴的两处行为开关**：N4 死门修好后主动接话是否恢复（并是否把"门"改为"概率随好感连续加权"）？
- **Q4 文案诚实性**：novelty 的 seasonal τ=21 天与"冷一冷就有分量"不匹配（实测需约 125 天静默）——
  调 τ，还是改文案？（推荐改 τ 到 7 天档，与 episodic 同阶，并保留"长期不重置"语义。）
- **Q5 善意底参数**：`BAND_MIN 2.60 / BAND_MAX 0.55 / 365 天饱和` 这三个数是她要的"分寸"，需要她定调
  （越大越宽容、越小越"记仇"）。
- **Q6 「你对守岸人」那一行**：停用裸比值 / 有界平滑 / 保留但换名（推荐：有界平滑，语义不删）。
- **Q7 一个坏日子的对称性**：正向 κ 与负向 κ 是否同额（v8 缺省同额 ⇒ 涨跌一样慢；v7 现状是负向有单事件帽、正向没帽）。
- **Q8 上线节奏**：影子记账观察期长度（推荐 7 天）与真机验收清单是否并入 `docs/acceptance-manual.md` 新一节。

