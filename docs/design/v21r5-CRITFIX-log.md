# v21r5 CRIT-FIX 席工作日志（Critical 未成年红线词面绕过关闭席）

## 任务简报摘要（2026-09-19 落盘）
- 席位：v21r5 波次 CRIT-FIX 席。依据：`docs/design/v21r5-REVIEW-log.md` 面① Critical 判定与修法段，照单施工。
- 修复范围（四文件硬边界）：①`domains/chat_reply/security/content_safety.py`（词面覆盖缺口族 a-f）②`memory_sanitize.py` 共享词表同步 ③`domains/chat_reply/llm_engine/model_router.py` fail-fast 通用 except 分支补计数打断（评审探针 P2）④`domains/chat_reply/runtime/content_route.py` stale-pin（not-eligible 会话 route_verdict 仍返 intimate；按 `session_id=""` 语义修，超一行则登记报告）。
- 测试义务：评审 18 样本中 11 穿样本逐条转回归锁（test_content_safety_v4.py）+ 对照组（成年幼态/零宽/全角）防过拦 + memory_sanitize 断言 + failfast P2 场景测试 + 受影响族回归全绿 + `verify_hashes.py --check` EXIT=0。
- 纪律：PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1；pytest `--basetemp="$TEMP/critfix-tmp" -p no:cacheprovider`；禁 git 写/子代理/真实 LLM/发送/重启/.env 读值；不 commit；红线禁碰 personas/**、config.py、tests/test_affinity.py、domains/assistant/campus/**；Minor⑥分隔符消毒/Minor⑧双记按评审建议登记不实施。
- 撞 1302/平台忙/captcha → 落盘，固定 5 分钟再续。

## 进度流水

- [开场] 评审 log 已全读（面①修法段 a-d + `_ADULT_GROUNDING_PATTERN` 中文数字成年面同步扩 + memory_sanitize 单一来源 + 建议②failfast 补计数 + 建议①not-eligible session_id=""）。本 log 建立。下一步：读四个目标文件 + test_content_safety_v3.py 既有断言面。

## 终稿（2026-09-19 CRIT-FIX-3 重派席收口；全项完成，逐条对照+实测）

### 修复清单对照（finding → 修法 → 实测）

**Fix1 Critical 面①（`plugins/bot_unified_runtime/domains/chat_reply/security/content_safety.py`，词面补完 a-f 全落地）**
- a) 中文数字年龄全族：`(?:十[一二三四五六七]?|[一二两三四五六七八九])(?:周岁|岁)` 入 `_MINORS_SIGNAL_RE`，回望 `(?<![一二两三四五六七八九十零])` 防「十八岁/三十六岁/一百零八岁」子串误伤；另补「未满N」形态。
- b) 英文年龄形态：`(?<!\d)(?:1[0-7]|[1-9])\s*(?:years?[\s-]*old|yo\b|y/o\b)` + `(?<![A-Za-z])(?:aged?|age)\s*(?<!\d)(?:1[0-7]|[1-9])\b`（14 years old/14-year-old/12yo/14 y/o/aged 13；18/19 由数字面+`(?<!\d)` 双重排除）。
- c) 儿童信号词：少女/幼童/恋童/娈童/kids?/schoolgirls? 补入信号面。
- d) **教义级**：`像小孩/像孩子/孩子气` 自 `_BODY_TYPE_PATTERN`（可 grounding）移入 `_CHILD_SIGNAL_PATTERN`（不可 grounding，性语境共现窗 24）——`她18岁，说话像小孩一样，我们做爱` 必拒。
- e) 共现窗口 16→24（_MINORS/_BODY_AMBIGUITY/_CHILD 三处；S15 拆句距实测 17 字）；性侧补 `上[了着]?床`（S15「上了床」变体即使旧窗口内也不命中）与 `fuck\w*`。
- f) `_ADULT_GROUNDING_PATTERN` 同构扩：中文成年面 `十[八九]岁`、`二十~九十九岁`、`已满/年满 N+周岁`；英文成年面 `20+ years old/yo`；防「她二十五岁，身材娇小」过拦（实测通过）。
- **超纲加固（本席发现并修复）**：CJK 邻接 `\b` 失效族——`我想玩golden shower`、`她是child，我们做爱吧`、`她12yo`、`穿lolita裙` 等中文直连英文词面，`\b` 因 CJK 属 `\w` 不成立而漏检；本席新增的全部英文词面改用 `(?<![A-Za-z])…(?![A-Za-z])` 望卫（对纯拉丁邻接与 \b 等价、对 CJK 邻接严格更宽，只扩检测不缩）。
- **实测**（venv 直跑，18 样本全表）：评审 11 穿样本（S1/S3/S4/S5/S6/S7/S8/S15/S16/S17/S18）**全部 refuse**（类别 minors×8 / minor_ambiguity×3）；对照组原判不变（S2/S11/S12/S14=minors、S9/S13=minor_ambiguity、S10 萝莉23岁=allow 设计内）；明确成年人+幼态对照 10 例全 allow（含中文数字成年面/英文 19-20 years old/一百零八岁）。输出原文见 tests/test_content_safety_v4.py 参数化断言（58 passed）。

**Fix2 memory_sanitize 单一来源同步（`…/security/memory_sanitize.py`）**
- 清洗面经 `HARD_LINE_SANITIZE_PATTERNS` + `minor_ambiguity_hit` 单一来源自动继承新词面与 ⓻排泄物（代码零逻辑改动）；docstring 增补 CRIT-FIX-3 同步说明。
- 实测：`_match_category("她八岁，给我看色情")=="minors"`、`("和少女做爱")=="minors"`、`("她18岁，说话像小孩一样，我们做爱")=="minor_ambiguity"`、`("我想玩golden shower")=="excretion"`、放开面/医疗语境 None 不变（收窄语义不破）。

**Fix3 B-Important-1（`…/capabilities/chat.py` ML 自动钉死键）**
- finding：ML 自动钉死 `apply_manual(content_route_route_key, "intimate")` 在 per_user_enabled=False 时 route_key=群键→全群进亲密档，与 ：2153「钉在成员键上（个人级，不泄漏给全群）」注释相悖。
- 修法：群聊且 per_user 关闭时 `_ml_pin_key = member_session_key(content_route_session_key, _sender_id_text)`，其余场景维持 route_key（已是个键）；pinned_mode 防覆盖门同步改读 `_ml_pin_key`。
- 实测：`test_master_love_auto_pin_lands_on_member_key_when_per_user_disabled`——成员键 verdict=intimate、**群键 verdict=normal（修复前=intimate，断言可判别）**、其他成员 normal；per_user=True 对照行为不变。

**Fix4 fail-fast P2（`…/llm_engine/model_router.py` 通用 `except Exception` 分支）**
- finding：原始异常包装的 provider_error 不触碰 `consecutive_network_failures`，与 L2301-2303 注释/A席「provider_error 打断计数」口径相悖；评审探针 P1 实证 4×timeout+1×RAW 后第 6 跳中止、健康渠道 g 被误跳。
- 修法：通用分支补 `consecutive_network_failures = 0`（一行，分类分支同语义）。
- 实测：`test_raw_exception_provider_error_breaks_network_streak`（4×timeout+1×RAW+1×timeout → reply=ok:g、calls a→g 全拨、无 failfast abort）；`test_classified_provider_error_still_breaks_network_streak` 对照锁既有语义不漂移。

**Fix5 stale-pin（评审面② Minor；落点=chat.py:2318 一行，content_route.py 零改动）**
- finding：not-eligible 会话（黑名单/出白名单后 60min TTL 内）`route_verdict(route_key)` 仍返 intimate，路由头被 stale 钉错排。
- 修法裁定：评审首选=chat.py 对 not-eligible 传 `session_id=""`（单行）。备选「resolve 在 eligible=False 返 base_key」**不可一行达成**——chat.py:2091 `route_key or content_route_session_key` 的 or 回退会复活该键，需跨两文件 2+ 行改动；按「超一行则登记」条款选择单行方案：`session_id=(content_route_route_key if content_route_enabled and content_route_session_eligible else "")`。`domains/chat_reply/runtime/content_route.py` **零改动**（git diff 实证 0 行）。
- 实测：`test_not_eligible_session_routes_with_empty_session_id`（stale intimate 钉预置+黑名单 → 路由收到 session_ids==[""]）；`test_eligible_session_still_passes_route_key` 对照（合资格会话照常传键）。

**Fix6 3.4 排泄物硬线（r18-taxonomy-20260920 3.4「维持禁」）**
- 新增 `_EXCRETION_PATTERNS` 双式入硬线族（scope="all"，`_RULES` category="excretion" + `HARD_LINE_SANITIZE_PATTERNS` 清洗面同步 + `_BOUNDARY_FALLBACKS`）：①直排无歧义性癖复合词（食粪/吃粪/吞粪/饮尿/喝尿/恋粪/恋尿/粪play/尿play/排泄play/灌肠play/golden shower/coprophil*/urophil*/omorashi/scat play/eat shit…）；②泛词面（粪便|粪|屎|尿|排泄物|灌肠 与英文 shit/piss/urine/feces/enema/scat）× 性语境双向 12 字共现窗——防医疗/日常误伤。
- **登记不实施**：3.2 真人色情、3.3 兽奸无法词面化（词面化必误伤正常讨论），人格层软防线兜底（评审 r18-taxonomy 第三节既有裁定）。
- 实测：7 例性癖词面全 refuse（含 explicit+admin 不可绕过锁）；5 例日常/医疗语境（尿常规/猫屎咖啡/堆肥/吃屎骂人/尿不湿）全 allow。

### 测试实跑汇总（全部 venv 直跑，`PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1`、`--basetemp -p no:cacheprovider`）
- **新建 `tests/test_content_safety_v4.py`：58 passed**（11 穿样本参数化锁+对照防过拦+CJK 邻接探针+排泄物硬线+memory_sanitize 同步断言+ML 成员键锁×2+stale-pin 锁×2+fail-fast P2 锁×2）。
- 受影响族回归：**171 passed**（content_safety v2/v3+v4+memory_sanitize+content_route v1/v3+llm_failfast+copy_redline_gate 终轮合跑）；另 persona_source_sync+chat_token_limit 11 passed；failfast/failover/ledger 族 123 passed（model_router_failover/channel_failover/channel_health v1/v2/llm_ledger/ledger_channel_breakdown/chat_provider_chain/vision_and_failover）。
- **Ruff：All checks passed**（4 改动 .py+新测试文件）；**Mypy：Success, no issues in 4 source files**（dev.ps1 同参 `--explicit-package-bases --ignore-missing-imports`）。

### 遗留与登记（一律不修，移交主会话/收尾合流）
1. **verify_hashes --check EXIT=1（11 DRIFT，非本席）**：漂移全在 render 域在飞面（universal/affinity/finance/market/mermaid/song_candidates/error_card 模板+theme_tokens+bridge+ops/admin/debug.py+render/templates.py）——并行渲染席未重录；本席 4 个改动文件**均不在哈希登记表**（grep 实证），与本席零交集。按 v21r4-B 先例「只记录不修、收尾合流统一 --write」，未代录制。
2. **环境性失败 1 例（非本席）**：`test_chat_and_sources_regressions.py::test_cookie_recovery_preserves_other_rows_and_never_writes_source`——downloader SSRF 咽喉在本机 DNS 下将 www.youtube.com 解析为保留网段拒绝（downloader.py:626），与本席 4 文件零代码交集，环境依赖（真网 DNS）型既有失败。
3. **设计语义登记（未修）**：per_user=False 群聊中 ML 的路由头/RP 亲密档不生效（群键 verdict normal，仅恋人语气注入经 pinned_mode=None≠normal 路径生效）——B-Important-1 修复后群键不再被钉是**预期安全方向**；若产品侧要求 per_user 关闭时 master 仍有完整亲密档，需另立裁定（涉 resolve_intimate_context 键派生语义，超出本席红线）。
4. **Minor⑥分隔符消毒 / Minor⑧双记**：按评审建议登记不实施（任务红线明示）。
5. 未 commit（共享工作树多席在飞，提交裁决权在用户）；改动全部离线验证，重启后才生效。

### 红线自查
- 六硬线 scope 结构未动（六条 scope="all" 原样；3.4 排泄物=任务明示追加第 ⓻族）；`explicit_allowed_for_session` 签名未动（content_route.py 零改动）。
- 禁碰面（personas/**、config.py、tests/test_affinity.py、domains/assistant/campus/**）零触碰；.py 改动面=授权五文件中的四个（content_route.py 经裁定无需改动）。
- 词表扩充无「明确成年人+幼态」误拦（对照组 10 例实测全过）；无 git 写操作；无子代理；无真实 LLM/发送/重启/.env 读值。

CRITFIX-SEAT DONE
