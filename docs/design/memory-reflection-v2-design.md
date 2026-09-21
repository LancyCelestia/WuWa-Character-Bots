# 记忆与反思 v2 设计（2026-09-21，用户裁定「键形只是表象，算法要重做」）

> 实施波：`.superpowers/sdd/2026-09-21-fix-wave/master-plan.md` 的 WP6。
> 她的原话：「6.A1（但有没有更好的算法和思路，这个我不满意）」⇒ 本件不止修键形，**重做沉淀与召回**。
> 与第 10 项的关系：本件的"单一记忆总线"是中央能力调度层接入的**先行样板**（先在一个子系统里证明收敛可行）。

## 一、现状的真问题（键形只是最表层的一个）

| # | 事实（已核到行号） | 为什么不够 |
|---|---|---|
| 1 | **两套并行记忆存储**：`memory_entries_v21`（用户可 `记忆 add/list/delete` 的显式事实，带 `confidence/sensitivity/source/source_event_id` + tombstones + index） ⟷ `reflection_facts`（夜间反思归纳，带 `confidence/superseded/session_key`） | 两套键形、两套可见性语义、两套"谁作废旧谁"的规则，只在 `_MergedMemoryProvider` 用 `fact_id` 去重拼一下 ⇒ **两条来源互相矛盾时无人裁决** |
| 2 | 反思召回 SQL：`(? IS NULL OR session_key = ? OR session_key IN ('','*','global'))`，绑定**裸** `session_id`；写侧 `session_key = f"{platform}:{session_id}"` | 主会话探针实证：写 1 行、按写侧键召回 **1**、按读侧真实入参召回 **0** ⇒ 反思事实**一条都没进过 prompt**（`bot_reflection_enabled=True` 时整链静默死路） |
| 3 | 可见性写在**字符串**里（`''`/`'*'`/`'global'`/`platform:` 前缀混用） | 无法校验、无法索引、无法演进；`session_keys.py` 中央件不覆盖这类复合键（D6 数出四类未覆盖） |
| 4 | 取信判据只有 `confidence >= 阈值` + `superseded=0` + `ORDER BY created_at DESC` | **`query_text` 收了不用** ⇒ 零相关性打分：不相关的老事实照样注入，相关的旧事实被 top-K 挤掉；说过 20 次和说过 1 次权重相同 |
| 5 | 去重靠"归一化文本相同 ⇒ 旧的置 superseded"（keep-newest） |  contradiction 与"重复确认"被同一个机制吞掉：**否认**（「我不喜欢柠檬茶了」）与**再确认**（又喝了一次）在数据上无法区分 |
| 6 | 注入了什么，事后**看不到** | 用户/维护者只能靠感觉判断"它记不记得"，是"感觉不够智能"的最大来源之一 |

## 二、v2 的四条原则

1. **一个真身存储**：事实只有一张表（`memory_entries_v21` 扩列），反思从"另一套存储"降级为**写侧归纳器**。
2. **可见性是列，不是字符串**：`scope_kind` + `scope_key`，构造唯一走 `session_keys.py`（并**扩展它**覆盖平台复合键与 `||u:` 成员键——顺带关闭 D14 的 reflection 那一支）。
3. **证据累积而非计数**：区分「再确认」「矛盾」「过期」三态，置信度由证据史算出，不由一次 LLM 输出拍板。
4. **召回要打分、要多样、要可观测**：相关性 × 强度 × 新近度 − 冗余；用了哪几条要能在 `/bot why`/审计里看见。

## 三、数据模型（只加列，不重置任何既有行）

```
memory_entries_v21 新增列（ALTER-if-missing，先例：affinity 三列 / shared_export 坐标 / emergency level 回写）
  provenance        TEXT  DEFAULT 'explicit'      -- explicit | reflected | derived
  confirm_count     INTEGER DEFAULT 1
  contradict_count  INTEGER DEFAULT 0
  first_seen_at     TEXT
  last_confirmed_at TEXT
  scope_kind        TEXT  DEFAULT 'global'        -- global | session | group_member
  scope_key         TEXT  DEFAULT ''              -- 由 session_keys 唯一构造；'' 仅当 global
  supersedes        TEXT  DEFAULT ''              -- 指被它取代的 fact_id（裁决留痕，不再静默覆盖）
  decay_class       TEXT  DEFAULT 'slow'          -- stable(偏好/身份) | seasonal | episodic
```
`reflection_facts`/`reflection_digests` **保留**：digest 仍是有用的"当日会话摘要"，
但 `reflection_facts` 停止新写入（写侧改投总线），旧行做一次性迁移（幂等、迁移前备份 `%TEMP%`、迁移后保留原表 30 天再谈退役）。

## 四、算法

### 4.1 写入（`observe/absorb`）
```
候选事实 f（来自显式命令 或 夜间归纳）
  norm = canonical(f.text)                        # 现有 _normalize_fact_text 复用，不另建
  e = 命中同 (subject, norm, scope兼容) 的既有事实 ?
  ├─ 有 ⇒ 确认：confirm_count+=1, last_confirmed_at=now,
  │        strength = 1 - exp(-confirm_count/k) 型饱和；confidence 上限随来源可靠度封顶
  └─ 无 ⇒ 查矛盾：同 subject、同"谓词槽"（谓词由现有 category 收紧为受控小词表）且值不同
          ├─ 矛盾 ⇒ 新行写入 + supersedes=旧 id + 旧行 contradict_count+=1
          │         两者都进"待裁决"降权（不立刻判死），高确认次数一方胜出
          └─ 无 ⇒ 直插（provenance 标明来源）
```
> 关键差别：**"又说起"≠"改了主意"**。v5 两者都走 keep-newest 覆盖，这是"记性不稳"的根因。

### 4.2 强度与遗忘
`strength = saturate(confirm_count) · exp(-Δt/τ(decay_class)) · source_reliability(provenance) · (1 - contradict_penalty)`
- `decay_class=stable`：长期偏好/身份/忌口 ⇒ 半衰期长（缺省 180 天）
- `seasonal`：季节/时段相关（「最近爱喝冰的」）⇒ 半衰期中（缺省 45 天）
- `episodic`：单次事件 ⇒ 快衰减（缺省 14 天），且**默认不参与长期画像**
显式用户命令（`记忆 add` / `记忆 delete`）**永远压过归纳**（意志自主条款在记忆面的对应物）。

### 4.3 召回打分
`score = w_rel·relevance(f, query) + w_str·strength(f) + w_rec·recency(f) − w_red·redundancy(f, 已选集)`
- `relevance`：两级，**不引新依赖**——① 有向量的仓内资产（`vector_knowledge`/FAISS 已在）走语义相似；
  ② 无向量时退化为关键词/别名重叠（复用 `_normalize_fact_text` + 既有词表），**明确降级并在可观测面标注"语义召回不可用"**；
- `redundancy`：同 `category`/同谓词槽最多留最高分 1 条（MMR-lite），治"三条近重复吃掉预算"；
- 隐私闸：`requester==subject` 与 `sensitivity` 四级（含 `credentialed` 永不进 prompt）**原样保留并加锁**，
  `scope_kind` 判据改走 `session_keys`，**跨会话召回必须显式为 global 才允许**（v5 是"忘了传就是全会话"，fail-open）。

### 4.4 可观测（这一条最便宜、最像"变聪明了"）
每次注入落一行审计/诊断记录：`fact_id + provenance + score 明细 + confirm/contradict 计数`，
`/bot why` 与 `/bot memory list` 能看到"这条为什么被用/为什么没被用"。
（沿用本仓"观测面不是可选项"的既有纪律，如 `audit_tags`、`ResultUnknownLedger`。）

## 五、配置键（9 枚，缺省保守、可整体灰度）
`bot_memory_bus_enabled`(False→灰度后 True) / `_reflected_write_target`(bus|legacy)
/ `_strength_k`(3.0) / `_tau_stable_days`(180) / `_tau_seasonal_days`(45) / `_tau_episodic_days`(14)
/ `_relevance_weights`(JSON w_rel,w_str,w_rec,w_red) / `_per_category_max`(1) / `_semantic_recall_enabled`(True)

> 热改档位：`_reflected_write_target` 与 `_semantic_recall_enabled` 走 `SETTABLE_KEYS`（可回退），其余需重启。
> 落 `config.py` + catalog + `.env.example` + `SETTABLE_KEYS` 四处同生，**由主会话统一改**。

## 六、迁移与回滚（运行数据不可删）
1. 一次性幂等迁移 `reflection_facts → memory_entries_v21`（`provenance='reflected'`），迁移前整库备份 `%TEMP%`（台账 #1 规程），迁移只 INSERT 不 UPDATE 原表；
2. 双读影子期：`bot_memory_bus_enabled=False` 时仍走旧路径 ⇒ 灰度期间两路都能跑，出问题一键回退；
3. 回滚粒度＝"停止写总线 + 新列闲置"，**不删列、不删行**；
4. 迁移脚本必须自带**守恒断言**（迁移前后条数/按人分组数一致，且旧行零丢失）与负样本（漏一行即红）。

## 七、验收（可测的行为断言，不是"感觉更好"）

| 场景 | v5/v1 实况 | v2 期望 |
|---|---|---|
| 群聊里说过的私事 | 靠字符串键碰运气（且反思链恒召回 0） | `scope_kind=session` 明确隔离，跨会话**结构性**召不回 |
| 同一偏好说 5 次 | 5 次都是独立行或互相覆盖 | 1 行 + `confirm_count=5` ⇒ 强度显著上升，注入时排得更前 |
| 改主意（「现在不喝柠檬茶了」） | keep-newest 覆盖，且**说不清被谁改的** | 双行 + `supersedes` + 旧行降权，可观测面能解释"为什么用新的" |
| 无关的旧事实 | 只要 confidence 够就照塞 | relevance 低 ⇒ 不占预算 |
| 近重复三条 | 吃掉 3 个名额 | 同谓词槽只留 1 条 |
| 「它到底记没记住」 | 看不出来 | `/bot why` 列出用了哪几条、分数、来源 |

真机验收消息（重启后）：写入 `docs/audit-20260921-commands.md` F 组。

## 八、红线与不变量（实施席必须锁）
1. `credentialed` 敏感级**永不进 prompt**、`redact_local_secrets` 出站打码链**不得因此次改动绕开**（V3-3 在册）。
2. 记忆面未成年/亲密红线清洗继续走 `content_safety`/`memory_sanitize` **单一来源**（六硬线 + minors，fail-closed）。
3. 用户显式删除（`记忆 delete` / 被遗忘权）必须**真删 + tombstone**，且总线迁移不得复活已删事实（tombstone 优先）。
4. 夜间反思作业的**装配点不变**（只换存储与判据），避免与第 10 项中央层接入波撞车。
