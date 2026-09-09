# 好感度系统数值化设计（C组交付）

> 日期：2026-09-10 · 实现载体：`plugins/bot_unified_runtime/character/affinity.py`（本文件是其数值规范的唯一权威描述）
> 原则：先成文后实现；所有数值常量集中在 affinity.py 顶部，注释指向本文档。

## 1. 数值模型总纲

- **基数（base）= 0.5**：新用户无任何记录时的中性初始值；`snapshot()` 无记录也返回 0.5，保证读路径恒定可用。
- **值域 [0.0, 1.0]**：任何写入路径（observe/delta_override/衰减）落库前 clamp 到该区间。
- **持久化**：SQLite `user_affinity` 表，`affinity REAL`；每用户一行（sender_id 主键）。
- **静态档案关系**：`relationship.py` 的档案有 affinity 用档案；动态层有「非默认记录」（affinity≠0.5 或有标签）时覆盖档案的 affinity/attitude，档案其余字段（称呼/偏好/备注）保留。注入代码在 `character/providers.py`（`ContextBundle` 构建段）。

## 2. 行为分类与影响因子表

分类入口：`classify_behavior(text, safety_category, safety_action)` → 五类互斥行为。
优先级（自上而下先命中先得）：安全硬类别 > 安全软类别 > 文本正则。

| 行为 | 触发条件 | delta | 每日有效次数上限 | 设计理由 |
|---|---|---|---|---|
| `positive` | 文本命中感谢/夸奖/问候/陪伴语（谢谢/辛苦了/晚安…） | **+0.02** | 10（每日净增益 ≤ +0.20） | 奖励友好，但不可靠刷问候快速拉满 |
| `neutral` | 其余普通对话 | 0 | 不限 | 聊天本身不奖不罚，好感只由态度驱动 |
| `tease` | 安全软类别（excessive_intimacy / persona_breaking）或玩笑语（哈哈/骗你的…） | **-0.01** | 5 | 轻微摩擦：越界亲昵与调戏让守岸人不适，但非敌意 |
| `negative` | 文本命中抱怨/贬低词（烦死了/真差劲/闭嘴…） | **-0.05** | 8 | 明确的负面情绪表达 |
| `insult` | 安全硬类别（harassment / insult_nickname）或 safety_action=refuse，或文本命中辱骂词（傻/蠢/滚…） | **-0.10** | 8 | 敌意行为，快速但非瞬时可拉到 0（连续 5 条 -0.50） |

- **每日上限语义**：同一行为在「同一自然日（UTC）」内，前 N 次全额生效，超出后 delta 视为 0（计数器与印象标签照常累计）。防止单日刷同一句话把好感推满/砸穿。
- 正则表是保守近似：不追求语义理解，只捕获高频明确的信号；误伤容忍度由「每日上限+clamp+衰减」三重兜底。

## 3. 加减算法

```
effective_delta(behavior, 当日已计次数 n) =
    0                                若 n >= 每日上限
    因子表 delta                     若 n <  每日上限
affinity_next = clamp(affinity + effective_delta + 惰性回归调整, 0.0, 1.0)
```

- `delta_override`（管理员/未来 LLM 评估接口）直接替换本条 delta，但仍受每日上限**不**约束——override 视为权威信号，仅受 clamp 约束。设 override 时该条不进入每日计数。
- **惰性回归（衰减）**：写路径（observe）时检查 `updated_at`：若距今 ≥ 7 个自然日且 affinity 偏离 0.5，向 0.5 每天回归 0.01（单向、不超过剩余距离）；回归后若当日无新事件也落库（避免只读漂移永不持久）。读路径（snapshot）**只读不衰减**，保证快照无副作用。
  - 时间源统一走构造时注入的 `clock`（默认 `time.time`）；`updated_at` 解析失败视为同日（不衰减），兼容旧数据与固定时钟测试。
- **印象标签只增不减**（本版约定）：达标即打标，去重，不因后续行为移除；标签列表上限自然受规则表约束（当前 5 条规则）。
- **画像事实（profile_notes）**：`learn_profile` 合并去重、保留最新 12 条；**observe 不得覆盖/清空 profile_notes**（修复历史缺陷：INSERT OR REPLACE 未携带该列导致每次行为记录清空画像）。
- **每日计数存储**：`user_affinity` 表加列 `counter_day_index INTEGER DEFAULT -1` + `day_counters TEXT DEFAULT '{}'`（当日各行为已计次数，UTC 日索引，跨日自动清零）——沿用只加列迁移先例；`snapshot()` 新增返回 `tier` 与 `profile_notes` 两个键。

## 4. 档位与语气态度映射

| 档位 id | 区间 | 注入 prompt 的态度文本 |
|---|---|---|
| `close` 亲近 | [0.75, 1.00] | 更直接的关心与陪伴，可以用你给对方起的小名称呼 |
| `friendly` 友善 | [0.45, 0.75) | 温和有陪伴感，记得对方的偏好 |
| `polite` 客气 | [0.25, 0.45) | 礼貌但有距离，不假装熟识 |
| `distant` 疏离 | [0.00, 0.25) | 简短、有分寸的疏离；保持人格与体面，绝不辱骂或人身攻击 |

- 区间**左闭右开**，边界值归属上一档（0.45 是友善不是客气；0.75 是亲近不是友善）。
- `tier_for_affinity() -> str` 返回档位 id（新增，供测试/运维查询）；`attitude_for_affinity()` 维持返回完整文本（向后兼容，providers 注入与既有测试不变）。
- 最低档红线：态度疏离 ≠ 人格破坏——任何档位都不辱骂、不冷暴力弃聊。

## 5. 注入规则（providers.py 成文）

`ContextBundle` 构建时，若动态层 snapshot 满足「affinity ≠ 0.5 **或** 有印象标签」：
1. 用动态 affinity 覆盖档案 affinity；
2. 态度文本 = 档位态度 + 依序拼接：`（印象参考：标签、…；只影响语气，不外显为标签）`、`（已知画像：事实；…自然体现不逐条复述）`、`（对方的小名：X；可用它称呼对方）`；
3. 融合后经 `apply_relationship_to_tone` 映射到 warmth/directness 语气参数。

## 6. 并发与持久化

- 进程内单 SQLite 连接复用（`check_same_thread=False`）+ 实例级 `threading.Lock` 串行全部读写；上层（`__init__.py`）按 db 路径缓存 store 单例，避免热路径连接风暴。
- 时间戳统一 `YYYY-MM-DDTHH:MM:SSZ`（UTC）。

## 7. 边界与失败语义

- 空 `sender_id`：observe 返回基数 0.5 不落库；snapshot 返回中性默认。
- 未知 behavior：delta 记 0（防御），计数器不增。
- 数据库异常：由调用方兜底（`__init__.py` 被动感知段 try/except 吞掉，不影响主链路）；store 自身不额外吞错，保证测试可见。
- 存量库兼容：schema 迁移仅加列（`profile_notes`/`counter_day_index`/`day_counters`，缺哪列补哪列）；不改既有列。

## 8. 验收口径

- 既有 `tests/test_affinity.py` 全部用例**不改一字**保持通过（算法对小序列向后兼容：小次数不触每日上限、固定时钟不触衰减）。
- 新增 `tests/test_affinity_numerical.py` 独立命名覆盖：画像不被 observe 清空、每日上限、时钟注入、惰性回归、档位边界、override clamp。

## 9. 查询命令与双向展示（好感度卡）

### 9.1 双方向口径（诚实边界）

系统只有一个信号源（用户对机器人说的话 + 安全评估），两个方向是同一数据的两个诚实投影，卡片与帮助文本必须写明，不假装读心：

- **守岸人对你（印象好感度）**：§1-§4 的动态 affinity 本值，展示为 0-100（affinity×100，1 位小数）。档位着色：≥75 亲近（强调色）/ 25-75 常规 / <25 疏离（警示色）。
- **你守岸人（表达倾向）**：从行为计数派生的加权正向占比 `positive / (positive + negative + 2×insult)`（无任何行为信号时默认 0.5）。含义是「你说出口的话里，对机器人友好成分的加权比例」，不是对内心的测量。

### 9.2 命令

| 命令 | 场景 | 行为 |
|---|---|---|
| `好感度` / `好感查看` / `查询好感` | 私聊 | 双向分值卡（高亮双列表 + 档位 + 算法摘要） |
| `好感度` | 群聊 | 本群排行榜卡（有印象的成员网格，按印象好感度降序，自己一行高亮） |
| `好感度 我` | 任意 | 只看自己的双向分值卡 |
| `好感度 算法` / `好感度 说明` | 任意 | 文本说明：加分/轻微波动/扣分三档规则 |

### 9.3 群镜像表

动态层主表仍是每用户一行（全局）；群排行榜用**镜像表** `group_affinity (group_id, sender_id, display_name, affinity, 计数列…, updated_at, PRIMARY KEY(group_id, sender_id))`：`observe()` 增可选 `group_id`/`display_name` 参数，命中群会话时同事务镜像一行。镜像行与主行数值恒等，由同一写路径保证；`leaderboard(group_id, limit)` 按印象好感度降序、interaction_count 次序、sender_id 兜底排序。

### 9.4 算法说明文案（`好感度 算法` 输出与帮助页共用）

- **加分**：感谢/夸奖/问候/陪伴（+0.02/次，每日前 10 次有效）。
- **轻微波动**：玩笑与越界亲昵（-0.01，每日前 5 次）；普通聊天（0）；闲置 ≥7 天每天向 50 回归 1 点。
- **扣分**：抱怨/贬低（-0.05，每日前 8 次）；辱骂/骚扰/硬拒绝（-0.10，每日前 8 次）。
- 全程 clamp 0-100；好感只影响语气态度，任何档位都不辱骂、不弃聊。

### 9.5 卡片（Mica 规范，独立模板）

`templates/affinity_card.html` + `bridge.render_affinity_card_html(payload)`；主色无平台语境，取配置 `bot_help_card_color`（留空中性灰 #607080）走同一 `--pc`/`color-mix` 派生；单柔光阴影、圆角/字重 token、透明 body；网格参考样本：名称+ID+分值，正分强调色、低分警示色、自己一行描边高亮；数字保留 1 位小数。渲染走 `render_backend.render_card`，失败回退纯文本表格。

### 9.6 验收

`tests/test_affinity_query.py`（独立命名）：镜像行与主行一致、排行榜排序与上限、双向分值计算（含零信号默认 0.5）、私聊/群/算法三种结果、帮助条目存在且公开且唯一、模板 HTML 含分值/着色类/自己高亮。
