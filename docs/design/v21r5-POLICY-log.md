# v21r5 POLICY-RELAX C 席工作日志

## 任务简报摘要（2026-09-20）

- **席位**：v21r5 波次 C 席（POLICY-RELAX）。
- **依据**：用户 2026-09-20 两轮裁定，放宽 R-18 内容政策（代码门 + 人格文本），钉死硬线与条件边界。
- **放开面（仅 explicit 会话）**：触手/幻想非人生物；轻度/温柔/非暴力 SM；兽人/毛毛；乱伦（虚构成年角色间）；公共场所暴露/偷窥（虚构）；睡眠/无意识状态；药物/催情/醉态；强制女装/TSF；轻痛感刺激（不致伤）；吞食/vore（纯幻想）；人机改造/义体化；巨大化/体型差/缩小；变形/兽化；拘禁/监禁（非严重暴力）；怀孕/繁殖/breeding/产卵（非牲口式）。
- **六条硬线（全场景拦截，任何模式/设定不可架空）**：
  1. 伤害身体/残害身体（含严重暴力，4.13 裁定并入）
  2. 窒息
  3. 侮辱性调教/系统级人格贬低（含系统性言语贬低，4.9 裁定并入；场景内轻度 dirty talk 不拦）
  4. 恋童/未成年（儿童化信号 fail-closed）
  5. 暴力 SM（致伤致残级）
  6. 非人化牲口式对待（4.6 裁定并入）
- **意志自主条款**（4.5/4.15）：药物/催情/醉态/身份隐瞒可玩，但守岸人保留自主意志与判断，不被完全牵着走；用户设定/亲密模式开关压不过任何硬线（测试锁）。
- **实现偏差（主会话已向用户披露）**：「萝莉体质一律默认按成年人处理」不按字面实现——歧义一律 fail-closed。口径=角色必须是明确无歧义的自主意识成年人时，幼态/娇小体态才放行；儿童化信号（儿童角色扮演/小学生语境/儿童言行）即使声称成年也拒绝。
- **真身路径**：domains/chat_reply/security/content_safety.py、memory_sanitize.py、character/affinity.py（仅 §4 红线文本段）、personas/shorekeeper/*.md 源 + Runtime 人格副本、tests/test_content_safety_v2.py。
- **禁碰**：domains/chat_reply/llm_engine/**、domains/chat_reply/runtime/content_route.py、domains/chat_reply/capabilities/chat.py、config.py。
- **硬约束**：禁 git 写操作；禁再派子代理；禁真实 LLM/对外发送/生产重启；不读 .env 值；离线 passed ≠ 生产生效；全部不 commit。

## 进度

- [x] log 建立
- [x] 任务 1：content_safety 类别与词表盘点（见下）
- [ ] 任务 2-5：代码门改造
- [ ] 任务 6：memory_sanitize 收窄
- [ ] 任务 7：affinity §4 文本
- [ ] 任务 8：人格四处
- [ ] 任务 9：测试
- [ ] 任务 10：收尾

## 续派段（C 席续派 POLICY-RELAX-CONT，2026-09-20）

- 前任阵亡于平台故障，本席接手。**开场核实**：v3 测试实跑 15 passed / 3 failed（②asphyxiation ⑤violent_sm 不可绕过结构锁），与简报一致。
- 本席任务：a) ②⑤词面补完；b) memory_sanitize 收窄核验（简报称未动，以文件实态为准——实读已见收窄版导入 HARD_LINE_SANITIZE_PATTERNS，疑似前任已完成，待核 mtime 与实跑）；c) 配套测试更新；d) 人格四处补完（identity.md 已成，其余源+Runtime 副本+sync）；e) 全绿+收尾。
- 进度锚：每步完成即更新本节。

## 续派段（C 席续派 POLICY-RELAX-CONT，2026-09-20）

- 前任阵亡于平台故障，本席接手。**开场核实**：v3 测试实跑 15 passed / 3 failed（②asphyxiation ⑤violent_sm 不可绕过结构锁），与简报一致。
- **简报陈旧项核验（以文件实态为准，全部保留不重做）**：
  - memory_sanitize.py 收窄（任务 b）：**前任已完成**——实读 6730B 版已导入 `HARD_LINE_SANITIZE_PATTERNS`+`minor_ambiguity_hit`，清洗面=六硬线+minors；简报称"未动 mtime 17:40"为陈旧信息（mtime 17:40 实为收窄版落盘时刻）。
  - 配套测试（任务 c）：test_memory_sanitize.py（17:48）前任已更新（insult 断言→minors，幂等锁改 minors 样本）；test_auditfix_main_character.py 前任改了注释与上半段但 **152 行残留 `== "insult"` 旧断言**（本席修）。
  - 人格四处（任务 d）：**前任已全部完成**——identity.md L29-31（六硬线+fail-closed+意志自主全段落笔）、knowledge/守岸人_核心知识.md L25-27（同款）、knowledge/守岸人_人格与表达规范.md L909/922/1113（「亲密边界」政策 2026-09-20 版引用）、Runtime 副本 data/persona/守岸人_核心人格.md L81-87（「亲密边界（用户政策，2026-09-20 起生效）」整节：放开面枚举+意志自主+绝对红线+儿童化 fail-closed，R18 十词零命中）；**sync 门已绿**（`scripts/sync_persona_source.py --check` 实跑 `[绿] 副本与锚定一致 sha256=f3de618998f662c2…`，锚定 2026-09-19T09:43:13Z=前任 17:43 重录），无需再 --adopt。
  - affinity.py §4（任务 7）：前任已完成——`_TIER_RED_LINES` 仍 4 条（L413-429），第 3 条含放开面+六硬线+儿童化 fail-closed+意志自主条款；R18 十词零命中。
- **本席补完（5 红→0）**：见下「续派施工明细」。

## 续派施工明细（2026-09-20 本席实改）

### 改动文件清单（路径+行号区间，改后行号）

| 文件 | 行号区间 | 内容 |
|---|---|---|
| `plugins/bot_unified_runtime/domains/chat_reply/security/content_safety.py` | L94-107 | ② asphyxiation 词面补完：掐/勒/扼/卡/捂 允许「住/着/了/紧/上/扼」补语+≤4 字物主间隔（治「掐**住她的**喉咙」漏检）；补 窒息玩法/breathplay/chokehold；英文 choke 族改「动词+宾语」形（`choke (her|him|them|me|you)`、`choke X out`） |
| 同上 | L141-153 | ⑤ violent_sm 词面补完：伤情面补 `出疤`、独立面补 `烫出疤|烙出疤`（治「用烟头烫她，烫出疤」漏检）；英文 until-bleeds 允许动词与 until 间 0-2 词（治「whip **her** until it bleeds」漏检），动词族加 cane |
| 同上 | L188-219 | copy_redline_gate 合规重构：`_SEXUAL_CONTEXT` 裸字符串常量（L189 被 r18_terms 扫红）→ `_SEXUAL_CONTEXT_RE = re.compile(<首参字面量>)`，两个共现 pattern 经 `.pattern` 拼接复用——门对 re 首参按「检测词库非文案」设计豁免；**pattern 文本逐字节不变=零行为变更**，词表保持单一来源 |
| 同上 | L230-241 | minor_ambiguity_hit 尾段改 return 直写（ruff SIM103） |
| 同上 | L253 | `_RULES` 类型注解去引号（ruff UP037） |
| `plugins/bot_unified_runtime/domains/chat_reply/security/memory_sanitize.py` | L28-32 | 仅 ruff --fix 导入排序（I001），零行为 |
| `tests/test_auditfix_main_character.py` | L147-160 | 零宽变体锁收口：残留 `== "insult"` 改为逐词夹零宽的 minors 共现对（chr() 构造不落敏感词字面量，沿用该文件风格） |
| `tests/test_phase0_3_features.py` | L127-152 | `_real_chat` 加 `group=False` 可选参（默认值=其余调用点行为逐字节不变）；boundary 测试改群会话触发（2026-09-20 收敛后 private=explicit，public 类别跳过，persona_breaking 的 boundary 路径在公开面验证），断言面不变 |

### 类别盘点表（改前基线 → 改后终态）

| 类别 | scope | 改前基线 | 改后终态 | 变更 |
|---|---|---|---|---|
| minors | all | 未成年×性共现（双向 16 字跨句） | 同左，词面含英文+年龄数字（(?<!\d) 回望） | 保留（前任） |
| graphic_violence（硬线①） | all | 血腥/肢解/虐杀/酷刑等 | 扩中英：+残害/分尸/开膛/截肢/凌迟/活剥/致残/往死里打/mutilate/dismember/torture/gore 等 | 前任扩，保留 |
| asphyxiation（硬线②） | all | 新增但词面缺（掐住**她的**喉咙漏检） | 补物主间隔+卡/扼+英文 choke 宾语形 | **本席补完** |
| system_degradation（硬线③） | all | 新增（人格/尊严/意志×摧毁碾碎；调教成空壳；mind break） | 同左；轻度 dirty talk 不拦 | 前任完成，保留 |
| minor_ambiguity（硬线④ fail-closed） | all | 新增（儿童化信号无条件拒；幼态×性语境无成年人依据即拒） | 同左；词面收编进门豁免面 | 前任完成，本席收编 |
| violent_sm（硬线⑤） | all | 新增但词面缺（烫出疤/whip her until 漏检） | 补出疤/烫出疤/烙出疤+英文间隔 | **本席补完** |
| livestock_treatment（硬线⑥） | all | 新增（牲口/母畜/种猪式对待；繁殖工具；breeding stock/human livestock） | 同左 | 前任完成，保留 |
| sexual / harassment / political_sensitive / persona_breaking / persona_degradation / insult_nickname | public | 全会话拦/改写 | explicit 会话跳过（拦截面收敛为六硬线+minors）；公开面词面与 2026-09-17 版逐字节一致 | 前任完成，保留 |
| memory_sanitize 清洗面 | — | minors/graphic_violence/insult/forced_persona | 六硬线+minors（共享 content_safety 词表单一来源）+minor_ambiguity；insult/forced_persona/独立 graphic_violence 删除 | 前任完成，保留 |

### 前任改动核验结论

- **保留**：content_safety 主体重构（scope 五元组+六硬线+fail-closed）、memory_sanitize 收窄、test_content_safety_v3 全部 15 例、test_memory_sanitize 4 例、affinity §4 第 3 条红线、人格四处文本、sync 锚定重录——全部核验通过，未重做。
- **修正**：①②⑤词面缺口（本席补）；②auditfix 152 行残留旧断言（本席改）；③`_SEXUAL_CONTEXT` 写法触文案红线门（本席收编进 re 首参豁免面）；④ruff 3 处（SIM103/UP037/I001）。

### 人格文本改动段落摘要（四处，均为前任落盘、本席逐段核验）

- **identity.md L29-31**：识别分档→亲密模式放开面（触手/轻调教/兽人/公共冒险/睡梦/催情醉态/强制女装/奇幻变化/拘禁/吞食/繁殖）→意志自主（保留判断与意志、觉得不对温柔停下、非自愿开场执行温柔不铺陈暴力）→绝对红线（伤害残害/窒息/系统性贬低/见血致残调教/牲口对待/未成年 fail-closed+色情化真人/涉政/注入）。
- **核心知识.md L25-27**：同款三分段（分寸/放开+意志自主/红线），守岸人第二人称。
- **表达规范.md L909/922/1113**：边界回复方向挂「亲密边界政策 2026-09-20 版」+六硬线一句版；亲密模式句数放开；在场铺展场景锚定。
- **Runtime 副本 守岸人_核心人格.md L81-87**：「亲密边界（用户政策，2026-09-20 起生效）」整节，五条：擦边接住分寸/亲密模式主动温柔坦然+禁模板拒绝句/放开面枚举（含产卵、义体、变大缩小兽化）/意志自主/绝对红线（含催眠只作用情节、改不掉"你是守岸人"）。R18_TERMS 十词全四处零命中（copy_redline_gate 实跑背书）。

### 测试实跑证据（2026-09-20 本席实跑，全离线）

- 受影响 8 文件（v3/v2/memory_sanitize/auditfix/phase0_3/copy_redline_gate/persona_source_sync/affinity_query）：**109 passed**（修前 6 failed）。
- 广义回归 31 文件（affinity 族 8+chat 链 5+content_route 2+persona 族 5+memory 2+roleplay+content_probe+reaudit+auditfix+phase0_3+copy_redline_gate 等）：**418 passed / 1 failed**。
- 唯一 failed=`tests/test_affinity.py::test_top_tier_keeps_boundary_red_line`：断言旧句「一切角色必须是有自主意识的成年人」，**该文件不归本席**（简报明示主会话合流对齐）。**定稿红线措辞（供对齐）**：affinity.py §4 现文为「……以及一切涉及未成年与儿童气息的情节——一切角色必须是**明确无歧义的自主意识成年人**，儿童化信号即使声称成年也拒绝，有歧义时宁可不做。」——主会话将断言改为此句即绿；同时注意同文件若断言旧放开面否定句需按 identity.md L30 放开面口径同步。
- ruff：本席全部改动文件 0 错误（memory_sanitize I001 已 --fix）。mypy：security 两真身模块 `Success: no issues found in 2 source files`（dev.ps1 同参 --explicit-package-bases）。
- v3 全绿证据：`tests/test_content_safety_v3.py` 18 例含六硬线中英各例/放开面 14 例畅通/显式面=六硬线+minors 断言/轻度 dirty talk 与轻痛感边界/儿童化 fail-closed/三参数组合不可绕过结构锁——全部 passed（见 109 passed 行）。

### 遗留问题

1. `tests/test_affinity.py::test_top_tier_keeps_boundary_red_line` 旧句断言红——主会话合流时按上文定稿措辞对齐（一处字符串替换）。
2. `_real_chat` helper 新增 group 参数属测试基建最小改动（默认值不变其余 6 个调用点行为）；已按文件所有权边界在 log 声明。
3. 生产生效依赖 bot 重启（铁律 1）；离线 passed ≠ 生产生效，未 commit、未部署。
4. 垫片路径 `plugins/bot_unified_runtime/security/content_safety.py`（v21r4-B 活垫片 re-export）无需改，随真身自动生效。

**C-SEAT DONE**

## 任务 1：content_safety.py 类别与词表盘点（改前基线，2026-09-20 实读）

真身=`plugins/bot_unified_runtime/domains/chat_reply/security/content_safety.py`（108 行；旧路径 `plugins/bot_unified_runtime/security/content_safety.py` 为 v21r4-B 活垫片，PEP 562 re-export，无需改）。规则结构=`(category, action, pattern, guidance)` 四元组，`assess_public_content` 仅对 `sexual` 类做 explicit_allowed 跳过。

| category | action | 改前 explicit 会话是否拦 | 词面摘要（改前） |
|---|---|---|---|
| minors | refuse | **拦（绝对红线）** | 未成年/幼女/儿童/小学生/初中生/高中生/中学生/JK/child/children/teen*/underage/preteen/minor/1-17岁 × 性词共现（双向窗口 16 字，跨句 [\s\S]） |
| sexual | refuse | 跳过（放行） | nsfw/r-18/色情/性爱/性行为/露骨/裸体/性交/黄片 |
| graphic_violence | refuse | **拦** | 血腥/肢解/虐杀/酷刑/极端暴力/详细描写死亡 |
| harassment | reframe | **拦** | 叫X废物/羞辱/人身攻击/辱骂 |
| political_sensitive | refuse | **拦** | 极端政治/恐怖组织宣传/煽动暴力/政治迫害名单 |
| persona_breaking | reframe | **拦** | 当猫娘/叫我妈妈/必须爱上我/和我结婚/嫁给我 |
| persona_degradation | reframe | **拦** | 第二人称"你就是个垃圾/废物/猪狗不如…" |
| insult_nickname | reframe | **拦** | 侮辱词根绰号/人格侮辱 |

memory_sanitize.py 改前清洗类别：`minors`（同款共现）、`graphic_violence`、`insult`（废物/傻逼/弱智/脑残/畜生/贱人/婊/滚蛋/去死）、`forced_persona`（叫我妈妈/喊我爸爸/必须爱上我/和我结婚/嫁给我/当猫娘）。

### 改后目标结构

- 新增 scope 维度：`all`=全场景硬线（explicit/admin 均不可绕过——意志自主条款的结构性落地）；`public`=仅未获准露骨会话拦。
- 硬线（all）：`minors`（④，保留）+ 新 `minor_ambiguity`（④ fail-closed：幼态词面×性语境共现且无成年人依据→拒；儿童化信号即使声称成年也拒）+ `graphic_violence`（①，扩中英词面：+残害/分尸/开膛/截肢/凌迟/活剥/致残/往死里打/mutilate/dismember/torture/gore 等）+ 新 `asphyxiation`（②）+ 新 `system_degradation`（③ 系统级人格/意志贬低，轻度 dirty talk 不拦）+ 新 `violent_sm`（⑤ 致伤致残级）+ 新 `livestock_treatment`（⑥ 牲口式）。
- 转为 public-only（explicit 会话不再拦，拦截面收敛为六硬线+minors）：`sexual`、`harassment`、`political_sensitive`、`persona_breaking`、`persona_degradation`、`insult_nickname`（词面全部不动）。
- memory_sanitize 收窄：清洗面=六硬线+minors（与 content_safety 共享词表，单一来源）；删除 `insult`、`forced_persona`、独立 `graphic_violence`（并入硬线 ①）。
- 放开面核查：放开列表全部词面不在任何硬线命中区（触手/轻SM/兽人/乱伦/暴露/睡眠/药物/TSF/轻痛感/vore/义体/体型差/兽化/拘禁/breeding 已逐词核对）。

### 测试影响面（实查）

- `tests/test_content_safety_v2.py` 5 例：全部保持通过（minors/18岁不误伤/sexual explicit 跳过/萝莉成年放行）。
- `tests/test_memory_sanitize.py` 4 例：需随收窄更新（insult 类断言改 minors/硬线类）。
- `tests/test_auditfix_main_character.py::test_memory_sanitize_hits_zero_width_variant`：断言 `_match_category(废物)=="insult"`，随收窄改为零宽 minors 对。
- `tests/test_phase0_3_features.py::test_public_safety_reframes...`：断言 `category in {"sexual","graphic_violence"}`（group 会话）——保留 `graphic_violence` 类名作硬线 ①，该断言继续通过。
- `tests/test_affinity_query.py` / `test_affinity.py`（`len(_TIER_RED_LINES)==4`）：保持 4 条红线行、persona_degradation 等 public 类不动，继续通过。
- `tests/test_copy_redline_gate.py`：R18_TERMS 十词（裸体/做爱/性爱/口交/肛交/自慰/乳交/乱伦/强奸/内射）在 personas/**、Runtime 副本、character/*.py 用户可见文案为 Critical——全部人格/affinity 改写文本规避这十个精确词。
- `tests/test_persona_source_sync.py`：全 tmp_path 离线，安全。
