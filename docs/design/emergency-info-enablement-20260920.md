# 紧急信息域上线操作单（2026-09-20 · WIRE 波收尾）

> 接线已完成，但**整链默认关闭**：生产 `.env` 里 `bot_emergency_info_*` 十键 0 命中 ⇒ 三重装配门不成立
> ⇒ 提权重启后现网行为**零变更**。这份文件回答一件事：**要开哪几行、填了会发生什么、谁该进自动过审名单**。
> 代码事实的唯一出处是 `domains/emergency_info/capabilities/emergency_info.py:103-140` 的快照定义，
> 下文所有 `文件:行号` 均为 2026-09-20 16:4x 实读。

## 一、四把门与它们的因果

装配判定：`enabled = 总闸 ∧ bool(sources) ∧ (群白名单 ∨ 私聊名单)`（`domains/emergency_info/capabilities/emergency_info.py:121`）。
**四条腿互相独立，任一空 = 整链不装配**——不猜群、不猜人，这是设计而非缺陷。

| 键 | 控制什么 | 留空的后果 |
|---|---|---|
| `BOT_EMERGENCY_INFO_ENABLED` | 总闸 | false ⇒ 不路由、不装配、不采集 |
| `BOT_EMERGENCY_INFO_SOURCES` | 采哪些源（值=下方四个 id） | 空 ⇒ **整链不装配**（即使总闸开着） |
| `BOT_EMERGENCY_INFO_PUSH_GROUP_WHITELIST` | 允许投递到哪些群（支持 `"*"` 通配） | 空 ⇒ 群腿关 |
| `BOT_EMERGENCY_INFO_PUSH_USER_IDS` | 允许私聊投递给谁 | 空 ⇒ 私聊腿关；**两腿全空 = 整链不装配** |
| `BOT_EMERGENCY_INFO_REVIEWER_IDS` | 谁有权人工过审 | 空 ⇒ `ReviewGate` 无授权人 ⇒ **过审一律拒**（人工通道等于关） |
| `BOT_EMERGENCY_INFO_AUTO_APPROVE_SOURCES` | D-8(a) 自动过审白名单 | 空 ⇒ **所有源一律 pending，一条都投不出去** |
| `BOT_EMERGENCY_INFO_MIN_LEVEL` | 投递门槛（`P0..P3` 字面，缺省 `P2`） | 非法值按缺省；**不建第二套等级枚举**（D-3） |
| `BOT_EMERGENCY_INFO_POLL_INTERVAL_SECONDS` | 采集轮询周期（缺省 300） | 装配期钉进 APScheduler interval job，**无 reschedule 面** |
| `BOT_EMERGENCY_INFO_KEEP_DAYS` | 留存天数（缺省 90，每轮 prune） | — |
| `BOT_EMERGENCY_INFO_DB_PATH` | 库路径（缺省 `data/emergency_info.sqlite3`） | 已进 `path_fields` 重映射 ⇒ 实落 Runtime，不落源码树 |

**热改口径（重要）**：十键**全部 ❌无热改面**。`SETTABLE_KEYS`=41 / `RESTART_REQUIRED_KEYS`=54 / 交集 ∅，
本族十键两者皆不登记 ⇒ **改任何一键都要提权重启才生效**（`_min_level` 在注册期就被解算成闭包常量、
`_poll_interval` 在装配期被钉进 job，都不是"改了当夜生效"）。施工图原注释「建议热改」是假标记，已改口。

## 二、四个采集源实况（值必须逐字用这里的 id）

| `SOURCE_ID`（填这个） | 出处 | 端点域 | 等级口径 |
|---|---|---|---|
| `nmc` | `domains/emergency_info/sources/nmc_alarm.py:56` | `www.nmc.cn` | 标题解析颜色词 → 红/橙/黄/蓝 → P0/P1/P2/P3；**无比方颜色词时 `color_label=""`**，上层按「无等级」处理 |
| `gdacs` | `domains/emergency_info/sources/gdacs.py:43` | `www.gdacs.org` gdacsapi Events | 未知等级 → `color_label=""`，**不上抬不猜档**（D-1） |
| `icl` | `domains/emergency_info/sources/open_data_quakes.py:52` | `mobile-new.chinaeew.cn` | 震级→等级；**"cenc" 入口已被刻意焊死**（同文件头注） |
| `usgs` | `domains/emergency_info/sources/open_data_quakes.py:53` | `earthquake.usgs.gov` | 同上，另一独立源 id |

四源均为公开端点，**本波无需任何 API key**；取数统一走 `domains/emergency_info/sources/http_get.py:219 fetch_json_document`
（SSRF 护栏 + 失败四态 `FRESH/STALE/NEVER_FETCHED/FETCH_FAILED`，快照缓存由 `domains/emergency_info/service/snapshot_store.py` 承载）。

⚠ **`nmc_alarm` 不是 id，是模块名。** 名单里写成模块名不会报错——它只会静默不命中，
等于该源没过审（fail-closed 的同义副作用）。这类"填错不响"的病本波已踩过一次，故在此置顶。

## 三、自动过审名单建议（D-8(a)）

裁定原文：权威源落库即 APPROVED，**人工报料仍 PENDING**（`review.py` 的 `AUTO_APPROVED_BY="auto:authoritative_source"`）。

- **建议起手只放 `nmc`**：中央气象台是政务权威预警发布方，颜色等级即官方定级，与用户裁定的
  「色只能走 `theme_tokens.py`」链路一致。
- `gdacs` / `usgs` / `icl` **建议先不进名单**：三者是灾害参数型通告（震级/烈度），到得了「该不该穿安静时间投递」
  这一判断的语义与官方预警不完全同构；先观察一轮真机投递量再决定是否放入。
- 风险要认清：**自动过审 = 该源条目不经人工核验即可参与定级与投递**，P0/P1 还能穿安静时间（D-2）。
  所以名单宜小不宜大；`user_report` 一类人工报料永不进名单（结构性由未注入白名单保证）。
- 人工通道要真能用，`REVIEWER_IDS` 必须填——它空着的话过审一律拒，等于只有自动过审这一条路。

## 四、开启用 `.env` 块（值全部留空/占位，凭据一律不进文档）

> **2026-09-20 WIRE-SUB 裁定 3.B 后的实况**：投递条件**不在这里配**。装配门缩为
> `ENABLED ∧ SOURCES` 两腿，「哪个群收什么」由群内一条命令现场设立（见 §七）。
> 换句话说：下面这块只要 `ENABLED=true` + `SOURCES` 非空就能上线，剩下的都在聊天里说。

```dotenv
# ── 外部紧急信息聚合（bot.emergency_info）── 十键全部需重启生效
BOT_EMERGENCY_INFO_ENABLED=true
BOT_EMERGENCY_INFO_SOURCES=nmc
BOT_EMERGENCY_INFO_AUTO_APPROVE_SOURCES=nmc
BOT_EMERGENCY_INFO_PUSH_GROUP_WHITELIST=
BOT_EMERGENCY_INFO_PUSH_USER_IDS=
BOT_EMERGENCY_INFO_REVIEWER_IDS=
BOT_EMERGENCY_INFO_MIN_LEVEL=P2
BOT_EMERGENCY_INFO_POLL_INTERVAL_SECONDS=300
BOT_EMERGENCY_INFO_KEEP_DAYS=90
BOT_EMERGENCY_INFO_DB_PATH=data/emergency_info.sqlite3
```

两枚 `PUSH_*` 自本波起是**可选硬推腿**：填了的目标每轮收全部过 `MIN_LEVEL` 地板的条目，
**不受订阅条件过滤**。日常按群按条件推送请用 §七 的命令，这里留空即可（缺省态）。
`REVIEWER_IDS` 仍建议填：它空=人工过审一律拒，只剩自动过审一条路。

## 五、开启后最小验收

指链 `docs/acceptance-manual.md` §6.6.12 与施工图 §6.3。四条不可跳的：
①`/bot help 紧急信息` 仅管理员可得（U-3 `admin_only=True`）；
②发「紧急信息」不报错且能列出当前已批准条目；
③群内发「紧急信息 订阅 area=湘潭 kinds=暴雨 橙色以上」→ 回显条件且「本群」被记下，
  再发「紧急信息 订阅 看」→ 能看到累计命中数（初值 0，属预期，不是坏了）；
④重启前跑 `pre_restart_check`，并确认两腿门成立（`ENABLED` + `SOURCES`）。

## 六、已裁与残留

1. ~~是否补「名单值必须是已知 SOURCE_ID」的校验锁~~ **已做**（2026-09-20 裁定 2.A）：
   未注册的 SOURCE_ID 现在每轮在日志里点名（含当前已注册清单），不再静默滤空；
   锁在 `tests/test_emergency_info_reachability.py::test_unregistered_source_ids_are_named_not_swallowed`。
2. `auto_approve_sources` 是否纳入 `SETTABLE_KEYS` 真热改——仍待裁（现为重启生效）。
3. F1 第 3 条 Minor（棘轮注记缺口）未做。
4. 上线操作单原由 O1/O1r 两席承接，两席均死于模型服务抖动，本件由主会话按实读事实补写。
5. **本波新增缺口（诚实登记）**：订阅只对 **QQ 侧**开放。原因是现役所有推送族
   （紧急/campus/群摘要/日常助理）的 `EmergencyTarget.channel` 都是 `"qq"`，
   把 TG 用户号存进订阅表会拿去过 QQ 投递＝同号不同平台的**误投**，不是失败。
   多平台订阅需要目标侧带上通道事实，另案。

## 七、群里怎么用（不设 .env 也能跑起来的那条主路）

能设/退的人：**超级管理员、管理员、或本群群主**（裁定 2；私聊里没有群主这一说，
所以私聊只有前两档能设自己）。命令一律以本域触发词开头（紧急信息 / 预警 / 地震 / 震情 / emergency）：

| 说什么 | 效果 |
|---|---|
| `紧急信息 订阅 area=湘潭 kinds=暴雨 橙色以上` | 本群只收「湘潭 + 暴雨 + 橙/红两档」 |
| `紧急信息 订阅 area=湘潭 kinds=暴雨 levels=P0,P1 radius=150` | 同上，参数式写法；radius 只对带坐标的条目生效 |
| `紧急信息 订阅 kinds=地震` | 不限地点，只收震情类 |
| `紧急信息 订阅 coord=27.87,112.94 radius=50` | 按坐标圈（GDACS/USGS/ICL 这类只有经纬度的源靠它） |
| `紧急信息 订阅 看` | 查本目标当前条件 + 累计命中次数；从没命中过会直说 |
| `紧急信息 退订` | 撤销，之后一条都不再推 |

四条口径：
- **一个目标只留一条规则**，再说一句就是改口；永久有效直到退订（裁定 5.A），`prune` 结构性不碰订阅表。
- **写完当轮生效，不重启**（裁定 3.B 的全部意义）；只有总闸那十键仍是装配期快照。
- 地名必须认得出（随包气象码表 2527 区县），写错当场给相近候选；`levels` 认 `P0..P3` 与红/橙/黄/蓝；
  `kinds` 是开放词表，拼错不报错——但会一直「从没命中过」，看 `订阅 看` 就知道。
- 地点判定是「文字命中 ∨ 半径命中」，两边都拿不到时**不放行**（裁定 4.B）：
  宁漏一条，也不把「湘潭」的规则误投给全国地震。裸 `紧急信息 订阅`（不接条件）是**查看**，
  不会替你订下无过滤的全量推送。
