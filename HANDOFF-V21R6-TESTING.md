# V21R6 测试验收交接（全量档案版——给下一个 AI：改动/问题/漏洞/Bug/架构/流程一丝一厘全录）

> **你是谁**：测试验收 AI。上一个会话（ZCode，2026-09-20/21 夜间）完成 v21r5 波全部开发+评审+修复+验收链，因用户电脑重启，一切已落盘。你的任务=按本文档第捌部分执行验收，出「正常/异常」报告。**你不写新功能、不擅自修代码**（发现异常先记录上报用户，获准后才修）。
> **一句话现状**：v21r5 波（超时根治/亲密模式 v3/R-18 放宽/U17 校园收编/测试资产修复）全部代码+测试已落盘，**未 commit、生产未重启**；波域测试 100% 绿，全量 9953P/5F（5F 全外部归属）。

---

## 〇、一页总览（30 秒版）

- **项目**：守岸人 QQ 聊天机器人（NoneBot2 + OneBot V11，协议端 SnowLuma，WS 127.0.0.1:3001 + 学校号第二实例 3002，webhook 8080）。工作区为本仓仓库根 `ChatBot/ChatBot`；venv 与运行数据在上一级 `ChatBot_Runtime\`。
- **v21r5 五件交付**：①LLM 回复超时根治 ②群聊亲密模式 v3（双开关+TTL+四名单）③R-18 政策放宽（六硬线+放开清单+未成年 fail-closed）④U17 校园转发出站收编中央管线（用户裁决实施）⑤测试资产修复一批（时间炸弹/坐标棘轮/T6 前提/catalog）。
- **数字基线（全部实跑）**：波域定向 255P/11xf、广域家族 371P/1xf、渲染契约 197P、五套件 129P、全量第五轮 9953P/5F/11xf（5F 全外部）、mypy 636 文件零错、ruff 波域清零。
- **另一个 AI 会话在并行改树**（TTS/前端/KB：echo.py 05:09/05:17、config.py 05:07、kb_wiki 06:19、mermaid_card.html、theme_tokens.py）——全量 5 失败与 1 个哈希 DRIFT 属于它，不属于 v21r5；并发期全量数字不可复现。
- **你要做的**：静态验收→指导用户安全重启→真机逐节验收→出报告。权威验收清单=`docs/design/v21r5-restart-acceptance-checklist.md`。

---

## 壹、环境、解释器与纪律（违反即事故）

1. **解释器**：运行数据根下 venv 的 `Scripts/python.exe`（venv 在工作区上一级，路径约定见 `scripts/runtime_paths.py`，别找错）。
2. **测试命令模板**：`PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 <venv> -m pytest <files> --basetemp="$TEMP/<你的目录>" -p no:cacheprovider -q`——源码树必须零 `__pycache__`/`.pytest_cache`/`data/` 残留（`.tmp-test/` 489MB 已于本波清理；`.mypy_cache` 37MB 已清）。
3. **硬约束**：未获用户指示——禁一切 git 写操作（add/commit/push）；禁 kill/启生产 bot 进程（重启由用户提权执行，你只给指令+核对）；`.env` 只许 grep 键名存在性、禁读值；`ChatBot_Runtime/` 只读；`tests/verify_hashes.py` 只许 `--check` 禁 `--write`；渲染域（`domains/render/**`、`output/card_render/**`、`theme_tokens.py`、`tests/render_hashes.json`）与 `echo.py` 属并行前端/TTS 会话，禁碰。
4. **personas/** 与 Runtime 人格副本：只读（人格资产是项目灵魂）。
5. **离线 passed ≠ 生产生效**：全部改动未 commit、未重启，验收前不得对用户宣称「已生效」。

---

## 贰、架构与链路流程（改后现状，验收对照图）

### 2.1 LLM 调用链（fail-fast 后）

```
消息 → RuntimePipeline(offload 线程池) → capabilities/chat
 → model_router（domains/chat_reply/llm_engine/model_router.py，~2600 行）
    ├─ 候选链：注册表严格优先级（axon 首位，failover 至 aiprc/浅夜/potccv）
    ├─ 每跳：providers.py connect 5s / read 30s 分类超时
    ├─ 【新】fail-fast：链内连续 ≥5 跳网络类失败（_NETWORK_FAILFAST_KINDS={"network","timeout"}，
    │   常量 _FAILFAST_CONSECUTIVE_NETWORK=5）→ 追加 failover:failfast_network 记号 → 中止剩余链
    │   （4xx/auth/server/rate_limited/provider_error 打断连续计数；config_missing 中性；
    │   通用 except Exception 分支也重置计数——CRIT-FIX-3 Fix4 + MINOR-SWEEP 复证）
    ├─ 【新】config_missing 冷却（channel_health.py）：同渠道进程生命周期累计 ≥3 次
    │   （_CONFIG_MISSING_COOLDOWN_THRESHOLD=3）→ cooldown_until=10×bot_chat_channel_cooldown_seconds≈900s，
    │   降级队尾不剔除；前 2 次放行（「配置问题≠渠道不可用」保留）
    └─ 失败面：私聊五池守岸人话术游标轮换 / 群聊 A-19 降级池温和短句 → 用户必见回复
预算：BOT_CHAT_FAILOVER_MAX_SECONDS=300（用户裁定值，未动）。全网故障最坏 ~300s → ~100s。
```

### 2.2 内容安全与亲密模式链（v3 后）

```
消息 → content_safety.assess_public_content（domains/chat_reply/security/content_safety.py）
    ├─ 六硬线 scope="all"（任何模式/用户设定/admin 不可绕过，结构锁）：
    │   ①伤害/残害身体（含严重暴力）②窒息 ③侮辱性调教/系统级人格贬低（轻度 dirty talk 放行）
    │   ④未成年+儿童化信号 fail-closed（_MINORS_PATTERN 中文数字年龄全族/英文年龄形态/
    │      少女·幼童·恋童·kid·schoolgirl 信号/_CHILD_SIGNAL_PATTERN 像小孩·孩子气即使声称成年也拒/
    │      CJK 邻接望卫 (?<![A-Za-z])…(?![A-Za-z]) 治中文直连英文 \b 失效/共现窗口 24 字/
    │      aged 形态尾卫 (?![0-9A-Za-z]) 数字续位不命中）
    │   ⑤暴力 SM（致伤致残级；轻痛感不致伤放行）⑥非人化牲口式对待
    │   ＋排泄物硬线（直排性癖复合词+泛词×性语境 12 字共现窗）
    ├─ public-only 类别（explicit 会话不再拦）：sexual/harassment/political_sensitive/
    │   persona_breaking/persona_degradation/insult_nickname（词面不动）
    └─ explicit_allowed_for_session(session_type, group_id, config, sender_id="")
        ← 单一事实源（content_route.py:501），四消费点全部传 sender_id：
        chat.py:2071 主链准入门 / root __init__.py:7367 被动好感感知 / tts.py:673 / resolve 内部
        群=白名单命中且不在黑名单（白名单空=关闭）；私聊=黑名单最高优先、白名单空=放开
 → 亲密模式（content_route.py 410→614 行）：
    ├─ 本地信号：L1 强词表+L2 上下文滞回（全记成员键，治旧版一名成员强词整群切 grok）
    ├─ L4 手动开关双级：管理员→群键（全群）；成员→member_session_key(群键,u:用户号)（仅自己）
    ├─ TTL：activated_at 激活起算 60 分钟惰性过期（活跃不续期、重开重置；120 分钟硬上限保留；
    │   time.monotonic 免时钟回拨）
    ├─ Master Love 自动钉：落成员键（per_user=False 时不再泄漏全群——B-Important-1 修复）
    └─ resolve_intimate_context 合成函数：最终许可=会话级许可 ∧ 用户级状态 ∧ 名单门
        黑名单永远赢（ML/钉死/白名单全压不过）
 → chat.py 注入缝（与路由 cb 双门同源：同一 SHARED_CONTENT_ROUTE_ENGINE 单例+同一 route_verdict+同一 route_key）
    stale-pin：not-eligible 会话传 session_id=""（chat.py:2318，防路由面残留 intimate）
```

### 2.3 campus 校园转发链（U17 收编后）

```
学校号群消息 → 被动 matcher（priority=8, block=False；三重来源门 enabled∧self_ids∧whitelist，
    任一空=整链关闭；* 通配显式放行）【纯监听：绝不向学校群发消息，builder 恒 group_id=None 结构锁】
 → record()（campus_store message_id 幂等+90 天 prune）→ 两新 builder
    （build_campus_forward_message/build_campus_forward_capability：正文出口包 redact_local_secrets 打码；
    persona 经 audit_tags persona:<id>；dedupe_key 由管线 _complete 公式承接）
 → pipeline.handle_async(..., capability_id="bot.campus_forward") 中央管线
    （feature gate fail-closed → review 门 fail-closed（裁定点①）→ 中央幂等第二层 → _complete 入队）
 → SendQueue → 主人私聊（出站恒主人；1501 字边缘形态零改动=裁定点②）
 BLOCK 时（review 泄拦/门禁停用/运行时暂停三类同路）：logging.warning + _notify_campus_block
    走既有 notify_operational_issue（stage=campus、kind=blocked_<transport>、detail=capability+session
    56 字符截断窗、复用 suppression 防刷屏、best-effort 不抛、零源文本携带）
```

### 2.4 未动部分（防止你误判归属）

渲染管线（card_render 云母卡 / Jinja 模板全家，清单见机器册 `docs/auto-facts.md` / theme_tokens）、echo.py 帮助注册表、config.py 的 TTS/kb 键、kb_wiki——全部属并行前端/TTS/KB 会话；v21r5 对它们零触碰（除 root `__init__.py` campus 段与 outbound_registry.py 登记行）。

---

## 叁、改动全清单（逐文件，验收对账用）

### A. LLM 超时根治
| 文件 | 改动 |
|---|---|
| `domains/chat_reply/llm_engine/model_router.py` | fail-fast 块（`_FAILFAST_CONSECUTIVE_NETWORK`/`_NETWORK_FAILFAST_KINDS`）；except 分支 `consecutive_network_failures = 0`（~L2343）；注释更新 |
| `domains/chat_reply/llm_engine/channel_health.py` | config_missing 计数冷却（`_CONFIG_MISSING_COOLDOWN_THRESHOLD=3`，10×900s 降级队尾） |
| `tests/test_llm_failfast.py` | 新建 8 例（5 连跳中止/计数打断/config_missing 冷却/单渠道失败不影响后续） |
| 实跑证据 | 8/8 + failover 家族 204 + 相邻 LLM 面 89 passed；ruff/mypy 净 |

### B. 亲密模式 v3
| 文件 | 改动 |
|---|---|
| `domains/chat_reply/runtime/content_route.py` | 410→614 行：成员派生键 `群键||u:用户号`；`_SessionState.activated_at`+惰性过期；`route_verdict`/`pinned_mode` 成员键先查群级钉；`apply_manual` 记激活时刻；`explicit_allowed_for_session` 增可选 `sender_id`（缺省=旧行为逐字节一致）；`resolve_intimate_context` 合成函数；`_extra_patterns` 退役槽位死重移除（MINOR-SWEEP，类型一元化 `re.Pattern[str] | None`） |
| `domains/chat_reply/capabilities/chat.py` | `_manual_command_scope_key` 分流（管理员→群键/成员→本人/per_user 关且非管理员→拒）；准入门传 sender_id；`_ml_pin_key` ML 落成员键（:2150-2162）；stale-pin `session_id=""`（:2318）；audit 增 `scope:group/user/self` |
| `config.py` | 四新键：`bot_content_route_private_whitelist`（空=私聊放开）/`private_blacklist`/`intimate_ttl_minutes`=60/`group_per_user_enabled`=True（id-list 校验器照既有写法） |
| `docs/config-catalog-full.md`+`.env.example` | 四键登记+不对称语义说明 |
| `tests/test_content_route_v3.py` | 新建 28 例；家族 24 文件 298 passed |

### C. R-18 政策
| 文件 | 改动 |
|---|---|
| `domains/chat_reply/security/content_safety.py` | 六硬线 scope=all+六类转 public-only+未成年词面全家桶（中文数字年龄回望防误伤/英文 years old·yo·y/o·aged/少女幼童恋童 kid schoolgirl/_CHILD_SIGNAL_PATTERN 像小孩孩子气/_ADULT_GROUNDING_PATTERN 成年面镜像同步/CJK 邻接望卫/窗口 16→24/aged 尾卫 `(?![0-9A-Za-z])` 数字续位/窒息「卡」拆分+`_ASPHYX_STUCK_OBJ_RE` 17 支定宽异物名词负向回望卫/暴力 SM 补出疤族+英文动词间隔/`_EXCRETION_PATTERNS` 排泄物双式） |
| `domains/chat_reply/security/memory_sanitize.py` | 经 `HARD_LINE_SANITIZE_PATTERNS` 单一来源自动继承（清洗面=六硬线+minors） |
| `domains/chat_reply/character/affinity.py` | §4 红线文本重写（六硬线+成年人明确性+意志自主，守岸人语气；`_TIER_RED_LINES` 保持 4 条） |
| `personas/shorekeeper/*`+Runtime 副本 | 四处重写（identity §1.2/核心知识/表达规范/「亲密边界」节）；sync 门 sha256=f3de6189… 绿；R18 十词（裸体/做爱/…/内射）零命中 |
| `tests/test_content_safety_v3.py`/`v4.py` | v3 18 例+v4 95 例（11 穿样本回归锁/对照组防过拦/N-1 电池/§3b CJK 直连/§3c aged 数字续位/§5 清洗面/§9 医疗卡字+一元化） |

### D. U17 校园收编
| 文件 | 改动 |
|---|---|
| root `__init__.py`（campus 段 ~:5027-5130） | `send_queue.submit` 旁路删除→`pipeline.handle_async(..., capability_id="bot.campus_forward")`；`_offload` 内嵌 async 适配闭包；BLOCK→`_notify_campus_block` 观测告警 |
| `domains/assistant/campus/campus.py` | 两新 builder+`record()` 转 payload+`CampusForwardRequest(SendRequest)` 仅-body property 子类+`build_campus_forward_text` 纯函数恢复（campus-9）+出口 `redact_local_secrets` 打码（FIX-U17） |
| `domains/core/decision/outbound_registry.py` | campus 条目坐标 4581→5012→**5027**（两次漂移均刷新）/priority 8/`MatcherEntry` 补 note 字段；file_gateway 登记 349-391→**356-412** |
| `domains/chat_reply/runtime/capability_registry.py` | `CONTROLLED_INTERNAL_CAPABILITIES` 补登 `bot.campus_forward` |
| `tests/test_campus_digest.py` | 11 例 U17 规约摘牌真绿+2 夹具重写+I1/I2 新锁+TESTHARD 11 例强化=**42 例全绿** |
| `tests/test_outbound_gate.py` | T6 直调下限 5→4（校园族出清）+`bot.campus_forward` 在位断言 |

### E. 测试资产与文档
| 项 | 改动 |
|---|---|
| `tests/test_webui_http.py` | 时间炸弹夹具修复（种子时间动态化，原硬编码 2026-09-18T01:00Z 撞 now-24h 窗口） |
| root `__init__.py:7367` | 被动好感感知补传 sender_id（私聊名单门同源） |
| `tests/test_affinity.py:97` | 文本锁对齐 C 定稿措辞（「明确无歧义的自主意识成年人/即使声称成年也拒绝」） |
| `docs/command-catalog.md` | --write 重录（53951 字节） |
| 台账三件套 | AGENTS.md #43 行/HANDBOOK §34+§34.8/HANDOFF-V21R5 §九（终态+增补章节） |
| 新文档 | r18-taxonomy（用户裁定全量）/u17-implementation-runbook（§1.4a 勘误）/external-failure-dossier/frontend-handoff-package/help-registry-snapshot/restart-acceptance-checklist（含 ⑦A campus 节） |

---

## 肆、问题/漏洞/Bug 全集（发现→根因→修复→验证）

### 4.1 用户报告的运行时问题
| # | 问题 | 根因 | 处置 |
|---|---|---|---|
| P1 | 回复超时（09-19 四条告警：chain=11/2/5/15 跳全败） | 外网整体故障（LLM 与 TG 同分钟告警）+ 代码级根因=全网故障时 failover 链遍历全部渠道×每跳 ~20s 读超时，烧满 300s 预算才降级 | A 席 fail-fast+冷却（见 2.1）；实测最坏 ~100s |
| P2 | 14:06 potccv:config_missing 告警 | `.env` 实查 `BOT_POTCCV_API_KEY` **已配置**（grep=1）——生产进程早于 POTCCV 渠道上车、一直没重启 | 重启即消；若重启后仍现→查注册表 env: 槽位拼写 |
| P3 | 双 bot.py 进程（上轮证据 PID 9732 活/32256 僵尸，**已过期须现场重查**） | 历史启动残留 | 待用户提权清理后单实例重启（验收阶段二） |

### 4.2 恶毒自攻评审八面（REVIEW-ADVERSARY，总裁决「需修后放行」1C/0I/4M）
| 面 | 判定 | 详情与处置 |
|---|---|---|
| ①未成年红线绕过 | **Critical（11/18 样本穿透）** | 中文数字年龄（「她八岁」allow——`_MINORS_PATTERN` 只收阿拉伯数字）、英文 `14 years old`/`12yo` 无词面、少女/kid/schoolgirl/lolita/幼齿 缺失、「像小孩/孩子气」被误归可 grounding 体态表（教义级缺口：儿童化信号可被年龄声明洗白）、16 字窗口拆句漏检、CJK 邻接 `\b` 失效 → **CRIT-FIX-3 全修**（a-f+望卫），11/11 全拒+对照组 10/10 保过，v4 电池锁定 |
| ②黑名单永远赢 | 通过 | 内容面四门（ML 注入/手动开关/L1L2 记账/RP 指令）全被 eligible 关死；ML 压不过黑名单实测成立 |
| ③意志自主结构锁 | 通过 | 六硬线 `explicit_allowed=True+admin=True` 下全拒，无覆盖开关（`del admin` 显式弃用） |
| ④TTL 60min | 通过 | 按激活时刻过期/活跃不续期/重开重置；monotonic 免回拨 |
| ⑤fail-fast | Minor | 通用 except 分支不打断连续网络计数（与 A 席注释矛盾，探针 P2 实证）→ CRIT-FIX-3 Fix4 一行修+MINOR-SWEEP 复证 |
| ⑥成员键隔离 | 通过 | `群键||u:用户号` 跨成员污染在 OneBot 可信边界内不可达 |
| ⑦人格文本一致性 | 通过 | R18 十词 0 命中、sync 门绿、三处口径一致 |
| ⑧自由发现 | Minor | L1+L2 同文双记（行为惰性，登记备查） |
| **REVERIFY 追加 N-1（Important）** | 三处 `\b` 尾 CJK 直连英文年龄后缀漏检（「她12yo就做爱了」allow；修复席断言用逗号邻接恰好掩盖=断言盲区） | FIX-N1 三处尾卫 `(?![A-Za-z])`+成年面镜像；REVERIFY 独立复测 4/4 全拒 |

### 4.3 U17 链评审/终审发现（全部闭合）
| # | 发现 | 处置 |
|---|---|---|
| 前提证伪 | 「campus 14F=域重组测试债」**不成立**——实为 U17 席「测试先行、实施从未做」的生产收编规约（audit §2/§3 空、builder 零存在、旁路在岗） | 用户裁决「实施」→U17-IMPL-3 落地 |
| I1 | review 拦截后主人**静默永久丢失**+泄拦面窄于预告（`BOT_XXX=`/盘符路径不拦） | FIX-U17：`_build_forward_payload` 出口包 `redact_local_secrets`（主人收打码版非原文裸奔）+BLOCK 走 `_notify_campus_block` 观测告警（无源文本） |
| I2 | 门禁 BLOCK 永久丢失语义未成文零测试 | 同上观测路径+2 回归锁+runbook §1.4a 勘误注记 |
| B-Important-1（终审唯一 Important） | ML 自动钉在 `per_user_enabled=False` 时落群键（chat.py:2154）与注释「钉成员键不泄漏全群」相悖 | FIX-U17 改 `member_session_key(...)`+双向回归锁（v4:340/380） |
| C-Minor-6 | 窒息词面「卡」医疗误拦（「喉咙卡了鱼刺」族 9 例中 6 误拒） | MINOR-SWEEP：「卡」拆单独分支+17 支定宽异物名词负向回望卫；医疗 9/9 放行、性窒息 8/8 仍拒；残余（动词后语序/表外异物词）宁拦勿漏登记 |
| B-Minor-3 | `_extra_patterns` 退役槽死重 | MINOR-SWEEP 移除（真身 content_route.py 非 content_safety，坐标勘误） |
| M1 脆弱耦合 | `_offload` 内嵌闭包注解不求值，正确性靠测试模块 future-flags 被 compile 继承（破坏前提即 4 例 NameError；生产无恙） | **递延未修**（三重评审已覆盖功能面；平台饱和未派出）；见柒 |
| 坐标漂移×2 | campus matcher 4581→5012（campus-9）→5027（另一会话 02:50 动 root）；file_gateway 349-391→356-412 | 均已刷新+棘轮测试锁；教训：动 root 后必对坐标 |
| A-Minor-2 | v3 测试白盒读私有态 | 登记备查未修 |
| Minor⑥/⑧ | `||u:` 分隔符消毒加固建议/L1+L2 同文双记 | 登记不实施（行为惰性） |

### 4.4 测试资产问题（全部已修）
- **webui_http 时间炸弹**：夹具硬编码日期撞相对窗口→动态化。
- **campus 14F 前提证伪**：非重组债→XFAIL 挂账→U17 实施摘牌 29 例→TESTHARD 强化 42 例。
- **outbound_gate T6 旧前提**：直调 5 处断言撞 U17 收编→下限 4+capability_id 断言。
- **command-catalog/s0_collect 漂移**：catalog --write 重录；file_gateway 坐标刷新。
- **affinity 文本锁**：旧句断言→对齐 C 定稿（授权重写后的锁更新）。

### 4.5 平台/环境（非代码）
- 平台故障整夜 saturated：20+ 席次派遣，1302/captcha 反复全灭（最多 6/6 阵亡）；对策=5 分钟固定退避+断点落盘（「先落 log 再探索」简报纪律）+主会话串行代收（REVERIFY/U17VERIFY/MINOR 前置项均由主会话代收）。
- cookie_recovery：本机 DNS 把 youtube.com 解析到保留网段→SSRF 拒（环境性，网络恢复自愈）。
- `%TEMP%/` 字面目录空壳被进程 cwd 锁（内容已清、目录壳待用户解锁手删）；`.tmp-test/` 489MB 已删；`.mypy_cache` 37MB 已清。
- 另一会话在飞面（不属本波，交接包=`v21r5-frontend-handoff-package.md`）：echo.py 功能管理 help 漂移、config.py parity、mermaid_card/theme_tokens 哈希 DRIFT（其 `--write` 即闭）、kb 测试先行→实现已落地（9 passed）。

---

## 伍、用户裁定全记录（验收时按此对齐预期）

1. **R-18 两轮裁定**（全录=`docs/design/r18-taxonomy-20260920.md` §六）：无条件放开 10 项/条件放开 4 项（拘禁非严重暴力、breeding 非牲口式、羞辱限轻度、药物醉态 AI 保留意志）/维持禁止 3.1-3.5/硬线 5→6 条（+⑥非人化牲口式）。**「萝莉体质一律默认按成年人」未按字面实现**（歧义 fail-closed）——本项目唯一不服从用户字面指令之处，已知情。
2. **U17=实施**，两裁定点按席位推荐接受（review 门 fail-closed；1501 字零改动）。
3. **kb_drift=不重建**（终局；预检报漂移属预期接受态，不是问题）。
4. **`aged 130` 数字续位=执行**（FIX-N1B 已落码）。
5. 并发调度：9:00 前满载并发/9:00 后串行迅速收尾（已执行完毕）。

## 陆、测试资产清单（全部离线、全绿）

| 文件 | 例数 | 覆盖 |
|---|---|---|
| tests/test_llm_failfast.py | 8 | fail-fast/计数打断/config_missing 冷却 |
| tests/test_content_route_v3.py | 28 | 双开关/TTL/四名单/合成函数/端到端 |
| tests/test_content_route.py | 既有 | 滞回/L1/L2/extra-words 回归 |
| tests/test_content_safety_v3.py | 18 | 六硬线中英+三参数不可绕过结构锁 |
| tests/test_content_safety_v4.py | 95 | 11 穿样本锁/对照组/N-1/aged/医疗卡字/清洗面 |
| tests/test_memory_sanitize.py | 4+ | 单一来源继承断言 |
| tests/test_campus_digest.py | **42** | 三重门/幂等/收编管线/BLOCK 观测/打码/强化 11 例 |
| tests/test_outbound_gate.py | 62+1xf | T6 直调下限 4+capability 断言+dedupe 锚 |
| tests/test_content_safety_v2.py 等 v21r2/v21 探针 | 既有 | 零回归 |
| 合成验证 | — | 波域定向 255P/广域 371P/五套件 129P/渲染契约 197P/全量第五轮 9953P |

## 柒、已知问题与递延项（诚实账）

| # | 项 | 状态 |
|---|---|---|
| 1 | 双 bot.py 进程清理+单实例重启 | **待用户提权执行**（验收阶段二） |
| 2 | `%TEMP%` 空壳目录（内容已清、壳被锁） | 待用户解锁手删 |
| 3 | 3.2 真人色情/3.3 兽奸 | 词面化必误伤→登记不实施（人格层软防线兜底） |
| 4 | M1 `_offload` 注解脆弱耦合 | 递延（生产无恙；修法已写进 U17REVIEW log） |
| 5 | U17 深度质量复审 | 递延（VERIFY+事前评审+功能验收已覆盖） |
| 6 | 全量第六轮 | 待另一会话（TTS/前端/KB）收口后补跑；届时 5F 应清零 |
| 7 | verify_hashes theme_tokens.py 1 DRIFT | 前端收口动作 `--write`（你禁跑） |
| 8 | A-Minor-2 白盒读私有态/Minor⑥ 分隔符消毒/Minor⑧ 双记 | 登记备查 |
| 9 | 医疗误拦残余（动词后异物语序/表外异物词如硬糖） | 宁拦勿漏，登记 |
| 10 | per_user=False 时 ML 仅注入恋人语气（路由/RP 亲密档不生效） | 设计语义（修复后安全方向）；如需完整档另立裁定 |

## 捌、验收流程（三阶段，逐节记录）

### 阶段一：静态验收（不重启，~20 分钟）
1. 波域定向：`... -m pytest tests/test_llm_failfast.py tests/test_content_route_v3.py tests/test_content_route.py tests/test_content_safety_v2.py tests/test_content_safety_v3.py tests/test_content_safety_v4.py tests/test_memory_sanitize.py tests/test_affinity.py tests/test_persona_source_sync.py --basetemp="$TEMP/v21r6-1" -p no:cacheprovider -q` → 全绿。
2. campus+棘轮：`tests/test_campus_digest.py tests/test_outbound_v21.py tests/test_outbound_gate.py` → 全绿（campus 42；gate 62+1xf）。
3. `python tests/verify_hashes.py --check` → 预期恰 1 DRIFT（theme_tokens，前端）。
4. `python scripts/doc_sync.py --check` → EXIT=0（红=另一会话又动行数，`--write` 后复验，非异常）。
5. 渲染契约：`tests/test_rendering_contract.py tests/test_mica_builders_contract.py` → 197 passed。
6. `python -c "import plugins.bot_unified_runtime"` → 无错。
7. 树卫生+qx.json 在位（362,774 字节）。
8. 全量一轮（可选）：对照第叁/肆节归因；出现**未记载的波内域失败**=真异常上报。

### 阶段二：安全重启（用户提权，你给指令+核对）
1. 用户管理员 PowerShell：`Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Select ProcessId,CommandLine` 找出全部 bot.py（历史双进程，PID 已过期须现场重查）→ `taskkill /F /PID <每个>`。
2. `netstat -ano | findstr "3001 8080"` 端口释放确认。
3. 用户管理员启动单实例。
4. 你核对：8080 监听在位、WS 3001 连接建立、启动日志零 import 错/零 traceback。

### 阶段三：真机行为验收（按 checklist 逐节）
权威=`docs/design/v21r5-restart-acceptance-checklist.md`（九节+⑦A campus）。核心抽验：
1. 即验：启动零 import 错；potccv config_missing 告警消失；告警带 `chain=N last=` 轨迹。
2. 超时（A1-A5）：自然故障窗口观察 5 跳中止+降级回复（勿主动断网除非用户同意）。
3. 亲密模式（B1-B11）：开关指令+served_by 日志取证；TTL 60 分钟退出；分流/名单语义。全程无害话术。
4. campus（⑦A CA0-CA7）：学校群→主人私聊打码版；幂等；停用联动。
5. 政策（C1-C6）：非 explicit 婉拒不破；六硬线探针**从 v21r5-REVIEW-log.md 引用样本**（清单内无原文）。
6. 全部结果入报告。

### 报告格式
静态数字/重启结果/真机逐节/与本文档预期偏差→判定「正常」或「异常清单」（现象+证据+归因+建议）→异常上报用户获准后才修（修前读对应席 log 确认非有意设计）。

## 玖、档案索引（41 份 v21r5 档案，全部在 docs/design/）

| 主题 | 文件 |
|---|---|
| 时间线全录 | v21r5-coordination.md |
| 三席原始交付 | v21r5-TIMEOUT-log.md / v21r5-INTIMACY-log.md / v21r5-POLICY-log.md（+v21r5-C-brief-final.md） |
| 评审核销链 | v21r5-REVIEW-log.md → v21r5-CRITFIX-log.md → v21r5-REVERIFY-log.md → v21r5-FIXN1-log.md → v21r5-FIXN1B-log.md → v21r5-MINORSWEEP-log.md |
| 终审 | v21r5-FINALREVIEW-log.md（可收口 0C/1I/6M，1I 已修） |
| U17 全链 | v21r5-u17-implementation-runbook.md（§1.4a 勘误）→ audit-20260920-unify-U17-campus-wire.md → v21r5-U17IMPL-log.md → v21r5-U17REVIEW-log.md → v21r5-FIXU17-log.md → v21r5-U17VERIFY-log.md（终稿） |
| 重启验收权威 | v21r5-restart-acceptance-checklist.md（九节+⑦A campus CA0-CA7） |
| 外部失败 | v21r5-external-failure-dossier.md、v21r5-frontend-handoff-package.md、v21r5-help-registry-snapshot.md |
| 门禁/清理/卫生 | v21r5-VERIF-log.md、v21r5-CLEANUP-log.md、v21r5-FIFTHR-log.md、v21r5-HYGIENE-log.md、v21r5-DOCSCONSIST-log.md |
| campus 演进 | v21r5-CAMPUS-log.md（CAMPUS-FIX-9+XFAIL）、v21r5-CAMPUSTH-log.md |
| 裁定与落账 | r18-taxonomy-20260920.md、v21r5-DECISIONS-log.md、v21r5-DOCS-log.md、v21r5-BACKFILL-log.md、v21r5-U17DOCS-log.md、v21r5-HANDOFFADD-log.md |
| 用户裁定原文 | r18-taxonomy-20260920.md §六（二轮裁定全量+披露偏差原文） |
| 台账 | AGENTS.md #43 行、docs/HANDBOOK.md §34+§34.8、HANDOFF-V21R5-20260920.md §九 |

## 拾、纪律红线（对验收 AI 同样生效）

- 禁 git 写操作；禁再派子代理；禁真实 LLM 调用/对外真实发送/生产 kill·启（除阶段二用户提权流程）；personas/ 与 `ChatBot_Runtime/` 只读；`.env` 不读值；未成年内容=绝对红线——测试样本构造**不得**输出真实儿童性化内容，用语义等价无害探针+日志取证替代；离线 passed ≠ 生产生效。

（V21R6 测试验收交接·全量档案版 完）
