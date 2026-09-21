# v21r5 FINAL-REVIEW-3 席工作日志（SDD 终审：代码质量 + 规格符合度）

## 任务简报摘要（2026-09-20/19 开场落盘）

- **席位**：v21r5 波次 FINAL-REVIEW-3（重派；前两任死于平台故障零进度）。
- **职责**：SDD 终审=代码质量+规格符合度全查；与在飞恶毒安全评审互补（它攻安全绕过，本席查质量/规格/接缝）。
- **只读席**：零代码编辑（唯一写面=本 log）。禁 git 写操作；禁再派子代理；.env 不读值；可跑离线 pytest/python -c 取证。
- **审查对象**（三席 log 改动地图）：
  - A 席 TIMEOUT：domains/chat_reply/llm_engine/model_router.py（fail-fast 块）+ channel_health.py（config_missing 冷却）+ tests/test_llm_failfast.py
  - B 席 INTIMACY：domains/chat_reply/runtime/content_route.py（410→614 行）+ capabilities/chat.py 亲密缝 + config.py 四新键 + config-catalog + .env.example + tests/test_content_route_v3.py
  - C 席 POLICY：security/content_safety.py + memory_sanitize.py + character/affinity.py §4 + personas 四处 + Runtime 副本 + tests/test_content_safety_v3.py 等
- **审查维度**：①规格符合度（r18-taxonomy §六全量；亲密模式双开关/TTL 60min/四名单语义）②代码质量 ③接缝一致性（双门同源/单一事实源旁路面/垫片完整/渲染契约零触碰）④测试卫生 ⑤边界与错误态 ⑥文档一致。
- **收尾**：本 log 末尾=终审报告（逐维度判定+Critical/Important/Minor 分级清单+总裁决），末尾 `FINALREVIEW-SEAT DONE`。

## 进度流水

- [开场] 三席 log + r18-taxonomy-20260920.md（含 §六裁定结果）已读。改动地图明确。开始逐文件实读。

## 发现清单（随时落盘）

### A 席 TIMEOUT 面（model_router.py / channel_health.py / test_llm_failfast.py）

- [A-核实] 常量区 L69-95 四常量+语义注释与实现一致；`_health_record_config_missing`（L642-685）全链 try/except 静默与既有健康面同纪律；`record_config_missing`（channel_health.py L281-295）锁内 O(1)、计数只增不清零=「进程生命周期」语义成立；字典以 model_id 为键、规模受注册表约束无泄漏面。
- [A-核实] 主循环接缝：config_missing 分支（L2214-2218）计数且中性于 fail-fast；failfast 达阈值 `attempts.append("failover:failfast_network")`+warning+双层 break（L2308-2323, L2357-2360）；链尾 `raise last_error`（L2362-2364）原样承接=能力层失败面产出可见回复，符合设计。`_last_channel_id`（L1755-1782）`failover:` 前缀跳过确认=计费归因零影响。hedge 分支（L1438-1440）只补 config_missing 计数不引 fail-fast，与 log 声明一致。
- [A-核实] 分类语义实核：providers.py ConnectTimeout/ConnectError→network、Timeout→timeout（L607-620）与 `_NETWORK_FAILFAST_KINDS={"network","timeout"}` 对齐；providers.py L624 泛化异常→LLMProviderError(kind=provider_error) 走 LLMProviderError 分支会重置计数，与注释「provider_error 打断计数」一致。
- [A-Minor-1] **注释声明与实现的窄缝隙：工厂异常路径的 provider_error 不重置计数**。model_router.py:78-79 注释称「provider_error（未分类异常包装）按保守原则打断计数」，但重置逻辑只存在于 `except LLMProviderError` 分支（L2304-2307）；`except Exception` 工厂分支（L2333-2347，`provider_for` 抛非 LLMProviderError 异常→包装为 kind=provider_error）直接 `continue`，既不累加也不重置。后果：网络失败×4 → 工厂异常 → 网络失败×1 会在第 5 个网络失败处中止，而按注释语义应被打断重置。实际影响窄（工厂异常罕见、偏早停方向），判 Minor。
- [A-Minor-2] test_llm_failfast.py:308 白盒读私有态 `store._config_missing_counts`——项目既有测试也有类似手法，可接受，登记备查。

### B 席 INTIMACY 引擎面（content_route.py 614 行全读）

- [B-核实] 模块 docstring v21r5 扩展（5/6/7 点）与实现一致；`member_session_key`/`split_member_session_key`（L171-190）rpartition 取末段、空段防误判，群键形如 `group:<数字>` 不含 `||u:` 分隔符，碰撞面实际为零。
- [B-核实] TTL 语义正确落实裁定 3：`activated_at` 激活时刻起算、读取时惰性过期（L263-272）、`apply_manual` 重开即重置（L495）、群级/个人级同一 `intimate_ttl_minutes` 键；`max_ttl=120` 保留为按活动滑动的硬上限（L273-279）；时钟默认 `time.monotonic`（L212）——单调钟免疫系统回拨（审查维度 5 结论：无回拨风险）。
- [B-核实] `route_verdict`/`pinned_mode` 成员键感知（L348-397/L439-470）：群钉 intimate→全员；群钉 normal 不压制成员个人档（设计裁定已记录）；滞回带逻辑逐字节保留。
- [B-核实] `explicit_allowed_for_session`（L501-550）：私聊黑名单最高优先→白名单空=放开/非空=名单内→console 常开；`sender_id` 缺省=旧行为（被动好感感知旧调用面零破坏）；群分支零改动 `in (wl - bl)` 黑名单赢。fail-open False。
- [B-核实] `resolve_intimate_context`（L553-597）：外门（名单）∧ 用户级状态合成，fail-open 落安全侧（eligible=False、mode=normal、键回退原会话键）。per_user 关或非群或无 sender_id → route_key=原会话键。
- [B-Minor-3] `_extra_patterns` 缓存结构残留退役槽位：`patterns = (strong_re, None)` 第二元恒 None（L243，`_borderline_retired` 命名已自证）；类型标注 `tuple[re.Pattern|None, re.Pattern|None]` 保留了已废的擦边词槽。纯死重不误行为，判 Minor（代码质量维度：可简化为一元返回）。

### C 席 POLICY 面（content_safety.py / memory_sanitize.py / affinity §4 / personas）

- [C-核实] 六硬线齐备且全部 scope="all"（_RULES L253-290：minors/graphic_violence/asphyxiation/system_degradation/violent_sm/livestock_treatment），`assess_public_content` 无任何覆盖参数（`del admin` 显式弃用，L308）——「任何设定/开关压不过硬线」结构性成立（意志自主条款落地）。minor_ambiguity 在规则表之前先行判定（L311-315）=fail-closed 无绕行。
- [C-核实] 放开面词面缺席核验：§六无条件放开 10 项+条件放开 4 项的词面（触手/兽人/乱伦/暴露/睡眠/药物/TSF/轻痛感/vore/义体/体型差/兽化/拘禁/breeding/产卵）均不在任何硬线命中区；条件项的例外面有正则落地——4.6 牲口式=livestock_treatment（繁殖工具/配种机器/breeding stock）、4.9 系统级=system_degradation、4.13 严重暴力=graphic_violence、4.5+4.15 意志自主=affinity §4+人格文本+六硬线 scope=all。
- [C-核实] memory_sanitize 清洗面=HARD_LINE_SANITIZE_PATTERNS+minor_ambiguity_hit 单一来源（L28-32 导入、L51-61 消费），隔离表先存证后删除可审计；normalize_for_matching（NFKC+零宽+空白折叠）两处口径一致。
- [C-核实] affinity §4 第 3 条红线（L424-437）=定稿措辞：放开面枚举+六硬线+「明确无歧义的自主意识成年人」fail-closed+意志自主；test_affinity.py:92-99 文本锁已按 C 席定稿对齐（92 行注释自证 2026-09-20 对齐），遗留问题 #1 已收口。
- [C-核实] 人格四处实读一致：identity.md L29-31、核心知识.md L25-27、表达规范.md（L909/922/1113 三处：群聊未开亲密模式回避行+亲密模式句数放开行+在场铺展锚定行，均挂「亲密边界政策 2026-09-20 版」）、Runtime 副本 守岸人_核心人格.md L81-87「亲密边界（用户政策，2026-09-20 起生效）」整节（放开面含 变大缩小/兽化/义体/产卵，比源多了显式括注，语义同向）。六硬线+意志自主+真人色情/涉政/注入红线四处同构。
- [C-Minor-4] **§六「维持禁止」3.2/3.3/3.4 在代码与人格层均无词面落点**（与波前状态一致，非本波回归）：真人色情=仅人格文本红线（identity.md「色情化真实真人」）；兽奸（真实动物）与排泄物（#36 曾禁）在 content_safety 六硬线词表与人格四处文本均未点名。属 #36→v21r5 政策迁移时的文档-实现缝隙（人格层软约束仍在「绝对红线」框架内但未枚举），登记为 Minor 待后续补人格文本或台账记录。
- [C-Minor-5] 乱伦（4.2 无条件放开）未在人格放开面枚举点名（identity/核心知识用「虚构的成年人之间」总括；R18 十词门禁 `乱伦` 一词本身禁写人格文本，构成措辞约束）；义体化/巨大化在源 persona 用「身体的奇幻变化」概括、Runtime 副本有显式括注。代码门已放开（无词面拦截）。判 Minor（人格层口径已可覆盖，仅显式度差异）。
- [C-Minor-6] asphyxiation 词面 `卡` 常语义误伤面：`(?:掐|勒|扼|卡|捂)(?:[住着了上紧扼]...)?(?:脖子|喉咙|...)`（content_safety.py:98）会把「喉咙卡了鱼刺」类医疗陈述判为硬线②拒绝（scope=all 全场景生效）。属安全词面的固有误伤取向（宁拦勿漏），判 Minor 备查。

### 接缝一致性（维度 3）

- [接缝-核实] **双门同源物理证实**：chat.py 经旧路径垫片 `runtime/content_route.py`（PEP 562 活转发到 domains/chat_reply 真身）导入 `SHARED_CONTENT_ROUTE_ENGINE`；root __init__.py:4636 `build_router_cb(_SHARED_CONTENT_ROUTE_ENGINE, ...)` 同一单例；注入缝（chat.py:2237-2248 二次 resolve）与路由 cb 同键（route_key=成员派生键）同函数（route_verdict）。垫片活转发=monkeypatch 两路径一致。
- [接缝-核实] **explicit_allowed_for_session 单一事实源全树核验**：生产消费点恰 3 处+合成函数内 1 处——chat.py:2071（kw sender_id）、root __init__:7367（kw sender_id，B 席遗留#2 已由后续补丁收口）、tts.py:673-677（位置参数 sender_id，fail-closed，M-02 根修注释）、content_route.resolve_intimate_context:586（kw）。**零旁路调用面**（无第三处绕开名单门的 explicit 判定）。
- [接缝-核实] **渲染契约零触碰证实**：三席 log 改动文件清单均不含 card_render/rendering-contract；mtime 实证 theme_tokens.py/bridge.py=09-18 03:33、mica_shell.py=09-18 23:28、test_rendering_contract.py=09-19 01:10、rendering-contract.md=09-19 00:49——全部早于 v21r5 开席（A 席 09-19 实警 15:02 后动工、C 席 09-20），属 v21r4-B/重组波未提交存量，v21r5 零触碰成立。
- [接缝-核实] 垫片转发完整性：runtime/content_route.py、security/content_safety.py、security/memory_sanitize.py、character/affinity.py 四张活垫片均为 PEP 562 `__getattr__` 实时转发真身（test_content_route_v3 经旧路径导入即消费真身单例，实证转发语义）。
- [接缝-核实] super_admin 判定链：policy/roles.py:31-37 `resolve_roles` 超管自动叠加 admin → `_manual_command_scope_key` 的 `"admin" in roles`（chat.py:2034）与 safety assess 的 admin 判定同口径，超管拨群键（开关二）语义正确。

### 测试卫生与实跑取证（维度 4）

- [测试-实跑] 本席复跑批（2026-09-20，`PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1` + `--basetemp=$TEMP/finalrev3-tmp -p no:cacheprovider`）：
  `tests/test_llm_failfast.py + test_content_route_v3.py + test_content_safety_v3.py + test_content_safety_v2.py + test_memory_sanitize.py + test_affinity.py + test_copy_redline_gate.py + test_persona_source_sync.py + test_doc_sync_gates.py + test_v21r2_content_probe.py → **126 passed in 8.88s**`（三席所有权面+文本锁+人格 sync 门+登记门禁一次性全绿，与主会话合流记录 8708P/14F-campus 债一致）。
- [测试-核实] test_llm_failfast：真断言语义（calls 列表证明后续渠道零拨号、attempts 轨迹全列断言、冷却时长 850<Δ≤950 区间断言、健康层关闭零足迹断言）；autouse fixture 单例复位+tmp_path 隔离，无跨用例泄漏。
- [测试-核实] test_content_route_v3：28 例全语义断言——TTL 边界（59/61 分钟、活跃不续期、重开重置、max_ttl 交叠、normal 钉不吃 TTL）、两级状态优先级、成员隔离（第三人/群键不受影响）、指令分流 5 态、四名单全场景（None 容错/黑名单赢/群黑名单关个人钉/ML 压不过黑名单）、resolve fail-open（_Boom 配置对象安全侧收口）、build_chat_result 群聊端到端 4 例；注入 clock=list 钉帧确定性。共享引擎用独立群号隔离（非引擎复位）——可行但依赖键唯一性，登记为风格注记。
- [测试-核实] test_content_safety_v3：六硬线中英各例经 `_assert_hard_line`（explicit+admin 双参数下仍 refuse=不可绕过结构锁）、放开面畅通例、dirty talk/轻痛感边界例、memory_sanitize 收窄例（tmp_path sqlite）。
- [测试-核实] test_webui_http 时间炸弹夹具已由主会话修复（coordination 记录+实读 `_config(tmp_path…)` tmp_path 化，6/6 绿），与本波三席无交集。
- [测试-缺口→Important-1 证据] test_content_route_v3 无「ML × per_user=False × 群聊」组合用例（ML 相关仅 blacklist-压过-ML 的 resolve 例 1 例）。

### 维度 5：边界与错误态核查

- TTL 时钟：ContentRouteEngine 默认 `time.monotonic`——单调钟，系统回拨无影响；测试注入 clock 钉帧。
- 成员键分隔符碰撞：`||u:` 双竖线+u: 前缀；群键=`group:<数字>`、私聊=`private:<数字>`，天然不含分隔符；split 空段防误判（roundtrip 测试锁）；rpartition 取末段，极端畸形键只会落幽灵键无害（状态永不钉于彼）。
- config 缺省语义：四新键缺省 `[] [] 60 True`；`_knobs` getattr 缺省链与 SimpleNamespace 测试双保险；resolve fail-open 落安全侧；explicit_allowed fail-open False；apply_manual/route_verdict/pinned_mode 全 fail-open。
- 空输入：match_manual_command 空文本 None；member_session_key 空段不构成键；observe_turn 空键直接返回。
- 并发：channel_health `self._lock` 内 O(1)；ContentRouteEngine OrderedDict 与 v21r4 既有口径一致（单例共享消费，未新增共享写风险面）；LRU 4096 封顶防泄漏。
- config_missing 冷却：健康层关闭整体空转（测试锁）；计数内存态重启清零（log 已诚实声明）。

---

# 终审报告（v21r5 FINAL-REVIEW-3，2026-09-20）

## 逐维度判定

| 维度 | 判定 | 依据摘要 |
|---|---|---|
| ① 规格符合度 | **符合**（1 项 Important 边缘语义待裁） | A 席=fail-fast 5 跳/config_missing ≥3 次×10 冷却与简报逐条一致且不改 config.py；B 席=双开关/TTL 60min 两开关同一/四名单不对称语义/黑名单永远赢/双门同源全部落实，4 处设计偏差均有裁定记录且方向正确；C 席=六硬线 scope=all+放开面词面缺席+memory_sanitize 收窄单一来源+人格四处与 §六逐条对齐（唯一不服从用户字面处的 fail-closed 偏差已按既定口径落码） |
| ② 代码质量 | **良好** | 新代码与原住民风格同构：设计注释带出处与动机、常量语义化、fail-open 边界全 try/except 静默、类型标注完整；ruff/mypy 三席各自 scoped 全绿（VERIF 618 文件 mypy 全绿可复用）；死重仅 B-Minor-3 一处 |
| ③ 接缝一致性 | **同源成立** | 双门同源物理证实（同一 SHARED_CONTENT_ROUTE_ENGINE 单例+同一 route_verdict+同一 route_key）；explicit_allowed_for_session 全树恰 3+1 消费点全部传 sender_id、零旁路；四张活垫片转发完整；渲染契约面零触碰（mtime 实证） |
| ④ 测试卫生 | **良好** | 全离线 mock、tmp_path 化、注入 clock 钉帧、断言语义独立（轨迹全列/拨号列表/时长区间）；无实现复述式断言；126 例本席独立复跑全绿 |
| ⑤ 边界与错误态 | **扎实** | monotonic 钟免疫回拨、分隔符碰撞面为零、config 缺省全链一致、fail-open 落安全侧、LRU 封顶、健康层开关空转语义有测试锁 |
| ⑥ 文档一致 | **一致** | config.py 四新键 ↔ config-catalog L796（含不对称语义与 v21r5 描述段）↔ .env.example L514-523 逐一对照无缺漏；doc_sync 门禁在复跑批内绿；三席 log 的改动清单与文件实态一致（含行号抽查吻合） |

## 发现清单（分级）

**Critical：0**

**Important：1**

- [B-Important-1] **ML 自动钉死在 `per_user_enabled=False` 时落群键，与注释宣称的成员键语义相悖**。
  证据链：`chat.py:2154-2156` ML 自动钉 `apply_manual(content_route_route_key, "intimate")`，而 `content_route_route_key` 来自 `resolve_intimate_context`（content_route.py:579-585）——per_user=False 时 route_key=原群键；chat.py:2153 注释却宣称「v21r5：群聊场景钉在成员键上（个人级，不泄漏给全群其他成员）」。后果：运营者显式关 per_user（「仅管理员全群开关有效」）+ 白名单群内有 ML 名单成员时，该成员在场即自动钉死全群 intimate（全员 INTIMATE RP 文风+grok 候选头插）。默认 per_user=True 不受影响；管理命令路径已正确拒绝（`_manual_command_scope_key` per_user=False 非管理员→None），唯自动钉路径漏了对齐。测试缺口：v3 无此组合用例。
  建议二选一：①修复——群聊 ML 自动钉显式钉 `member_session_key(session_key, sender_id)`（与 per_user 解耦，一行改动+一例回归）；②裁定「ML 视作全群语义」并改注释+config-catalog 补记。本席只读，不动码。

**Minor：6**

1. [A-Minor-1] 工厂异常路径 provider_error 不重置 fail-fast 计数，与 model_router.py:78-79 注释声明的「provider_error 打断计数」存在窄缝隙（model_router.py:2333-2347 直接 continue；仅 `except LLMProviderError` 分支 L2304-2307 有重置）。实际影响窄、偏早停方向。
2. [A-Minor-2] test_llm_failfast.py:308 白盒读 `store._config_missing_counts` 私有态（项目既有风格可接受，登记备查）。
3. [B-Minor-3] content_route.py:243 `_extra_patterns` 缓存第二元恒 None（擦边词退役槽位残留），类型标注同步冗余。
4. [C-Minor-4] §六维持禁止 3.2/3.3/3.4（真人色情/兽奸/排泄物）代码与人格层均无词面落点（与波前一致非本波回归；人格层「绝对红线」框架未枚举后两者），建议后续补人格文本或入台账。
5. [C-Minor-5] 乱伦（4.2 已放开）因 R18 十词门禁（`乱伦` 本身禁写人格文本）未在人格放开面显式点名，靠「虚构的成年人之间」总括；义体化/巨大化源 persona 用「身体的奇幻变化」概括（Runtime 副本有显式括注）。
6. [C-Minor-6] asphyxiation 词面 `卡` 常语义误伤面：「喉咙卡了鱼刺」类医疗陈述会被 scope=all 硬线②拒绝（宁拦勿漏取向，备查）。

## 总裁决：**可收口**（附 1 项建议修复）

- 三席交付与用户裁定书（r18-taxonomy §六 + 亲密双开关/TTL/四名单）逐条对照**无漏项、无变味**；接缝（双门同源/单一事实源/垫片/渲染契约）全部实证成立；测试为真语义断言且本席独立复跑 126 passed 全绿。
- B-Important-1 非默认配置下的语义-注释分歧，不阻塞收口：建议合流席在收口波内二选一（修码或改注释+登记裁定），并补 1 例回归。
- 既有口径重申：全部改动未 commit（提交裁决权在用户）、未重启未部署，离线 passed ≠ 生产生效；真机验收需重启后按各席 log 验收清单执行。

FINALREVIEW-SEAT DONE




