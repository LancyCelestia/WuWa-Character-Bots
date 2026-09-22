# HANDOFF — 2026-09-21/22 统一波「所有内容走中央调度层」（给下一个 AI 的第一入口）

> **冷启动读这一份就够**：mandate 对账 / 门禁真值 / 还剩什么 / 禁碰面 / 证据地图 / 复跑命令 / 踩过的坑，全在这里。
> 想深挖再按 §6 点进 `.superpowers/sdd/2026-09-21-unify-wave/`。**别从 `AGENTS.md` 从头考古**（那是规则+项目全貌，不是本波进度）。
> 交接口径：以下每一条"已完成"都带**可复跑命令或指到执法它的门**；凡只有席位自述、代码里查不到的，一律标「席述」。
> 本波与前两波的关系：接续 `HANDOFF-FIXWAVE-20260921.md` 的 ⑩（调度层当时只做了 Wave 0），是它的**继续交付**；同工作树、互相继承红。

---

## 0. 五问（30 秒内答得出 = 上下文接上了）

| 问 | 答 | 出处 |
|---|---|---|
| 我在哪？ | 中央调度层做到"命令形全通电 + prepared 形分批落地 + 主动投递单一出口 + 崩溃保真 + 中央审计 + 权限门两向修正"这套**地基与好几批交付**；但 mandate **未达成**（见 §1 四条「在册但未执法／同级披露」、§3 挂账）。工作树大量改动，**基线由用户 01:19 `ebb7130` 存档、此后仍未 commit、未重启** | `decisions/COMPLETION-AUDIT-20260922.md` 行 16 / `SEAT-MAIN.md` §34 |
| 我要去哪？ | 剩两块：prepared **剩余两类**（六枚必须碰根 / 四枚已汇缝但两枚无宿主行可填）、调度层 **Wave 1–4 逐域**（紧急域 `WP3-TAXONOMY` 本窗已落地摘牌，见 §3 第 5 条）；外加 **16 条待裁项** | `decisions/PREPARED-ADAPTER-PLAN-20260922.md` / `PENDING-RULINGS-20260922.md` |
| 目标是什么？ | 用户原话 12 维「统一 消息/协议/架构/入口/口径/产出/文本/模板/内容/函数/参数/处理流程——**所有内容走中央调度层，TTS 也不例外**，**预留 AI 绘画接口协议**」+ 工作方式约束（并行满载/文件面互斥/补丁待审不部署/恶毒自攻评审/视觉裁定优先/看不懂就重来）。逐维现状见 §1 | `master-plan.md` 触发段 |
| 我学到了什么？ | 一批「全绿但没执法」的新形态：**注释比代码先腐烂、存在性糊过活性判据、声明即通电是假账、关态绿=测的是闸不存在、棘轮基线不能用被检对象自算**（本波两次栽在这上头）。全表 `findings.md` 首段 + §5 | `findings.md` |
| 我做了什么？ | 见 §1 逐维 + `SEAT-MAIN.md` §20–§38 逐回合流水；**席位实测推翻交接稿/审计口径 20+ 条**（含主会话自己 3 次自伤），逐条记 §24 | `SEAT-MAIN.md` §24/§34/§35/§38 |

---

## 1. mandate 对账（这一屏最重要，先读这段再读别的）

**判据口径**：只有「实跑证据 + 归属真身」算做到；「代码写了、门没跑过」算未做。逐维权威表在
`decisions/COMPLETION-AUDIT-20260922.md`（它已被 R-AUDIT 席推翻并就地订正过一轮，订正记录见 `SEAT-MAIN.md` §34）——下面是浓缩。

**⚠ 下面 4 条里，①②④ 是同一类「在册但未执法——只在生产不用的配置下才为真」，任何"受管辖/已执法/已接"的表述都必须同行带这句；③不是配置问题，是这类事件根本不进旁路**

1. **出站防风暴闸缺省是关的**（`config.py` 的 `bot_outbound_gate_enabled` 缺省 `False`，生产 `.env` 里连这行都没有）。
   关着时闸是"逐字节直通"——所以**顺延、限流、键形核验、闸审计这四件事现网一件都没在发生**，
   包括本波刚修好的那条键形边界（C-1）。"主动投递都经过 outbound_gate"今天只是**关态直通**，不是"受治理"。→ 待裁第 9 项。
2. **层 2 不执法功能开关**：中央 `invoke()` 全程**不读** `gate_feature_id`（该字段在册，登记面靠 `CapabilityRegistration.gate_scoped`
   在**层 1** 的 feature gate 执法，invoker 自己不因它拒绝执行）。规格 §5 那半条**未实现**。功能开关目前只在层 1 生效。→ 待裁第 11 项。
3. **能力"挂死"不会出诊断卡**：中央超时给的是终态而不是抛异常 ⇒ 交不回层 1，
   `_internal_error` 旁路对"卡住不动"这一类**永不触发**；用户只看到温和短句。
   「崩溃保真 / 错误卡旁路复活」那句话的适用范围是**能力真的抛异常**，不含超时。→ 待裁第 10 项。
4. **cookie 到期那一族今天仍不走中央出口**（第 4 枚"在册但未执法"，2026-09-22 由独立审计席 A-CHOKE2 现读抓出，本席复核属实）：
   接法本身在（`__init__.py` 的 `_deliver_cookie_expiry_report_via_queue`），但它被一枚**缺省关**的键挡着
   （`config.py::bot_cookie_expiry_reminder_via_queue = False` ⇒ 走下面那条旧直发分支）。
   ⇒ 说"四条主动投递族全接中央出口"**只在开态为真**；现网实况是**三条走、cookie 那族直发**。
   本波早期台账与 `task_plan` 第 7 阶段那句"四条全接"是**按代码接通写的、没带开关实况**，已就地补限定。→ 待裁第 14 项。

**逐维现状**（✅ 已落实跑 ／ 🟡 部分，括注剩余那一刀 ／ ⏳ 未做）

- 消息 🟡：出站面收口（主动投递族改走中央出口——**cookie 到期那一族今天仍不走**，见 §1 第 4 条），入站摄取单点归一是既有事实、本波未动。
- 协议 🟡：两层归并——呈现契约（contracts 版保名）vs `InvocationResult` 执行信封（壳版改名），跨层唯一通道 `PRESENTATION_DATA_KEY`；`test_capability_result_unique.py` 锁 + 注毒四形态。
- 架构 🟡：见上两枚 P0——"投递经 outbound_gate / 层 2 执法 feature gate"这两句**现网不成立**。prepared 形落了地基 + 金丝雀 `bot.weather` + B1 十枚 + B2 一枚 + **B3 一枚 `bot.ignore`**（在册执行形枚数**以 `test_descriptor_wiredness_ledger.py` 与 `_route_execution_adapters()` 现算为准**，本文件不抄数）。剩余两小类各有硬由：**六枚**（content/music/today_history/media_archive/meme_library/group_info）AST 实证不经两个汇合函数、**必须碰根**才能登记；**四枚**（music_mode/subscribe/mail.control/auto_send.preview）已汇缝但桶归属未裁，其中 `mail.control`/`auto_send.preview` **没有 RouteKind 宿主行**＝结构上无处填 `execution`。
- 入口 🟡：单点位门 `test_orchestration_callsite_single` + 唯一在册表 `CAPABILITY_DESCRIPTOR` + 禁第二处 authoring；ops 5 处隐形直呼已进门面（S-BLIND）。**本窗加做**：`base_router` 24 条旧垫片 import 全迁真身（MIG-BR1），并立 `tests/test_legacy_shim_import_ratchet.py`（生产侧旧垫片 import 边数**手写上限、零余量**，现值以该门现算为准）＋目录形垫片盲点锁＋**测试侧第二本账**（`tests/` 同尺子独立单调，两侧各有上限与方向锁，另有**斥离锁**防"把两本账并成一个数"——本窗真的混算过 296/135，口径错了两次才对齐）。prepared 剩余两类卡点见 §1「架构」行与待裁 7b。
- 口径 🟡：生成物三件（`command_catalog` / `verify_hashes` / `doc_sync`）+ `board_doc_sync` 的 `--check` **收尾必重录**（现值有他席在飞漂移），未全绿前不能说"处处跟随已闭合"。
- 产出 ✅（本窗现读更正，旧写法把已完成当在飞）：媒体内容身份的唯一入口 = `domains/media/digest.py`（`media_digest` / `media_digest_file`，全仓**只此一处定义**），消费方现算含 `media/capabilities/tts.py`（S2，T127 起缓存键与参考音频指纹都走它）、`media/archive/media_archive.py`（S5）、`render/renderer.py`、`meme/capabilities/meme.py`、`creation/{_common,tts,image}/contracts.py`；TTS 缓存键/落盘名/审计标签同源（`audio_sha256`）。**⚠ 但"只准用中央件、禁第二份内容身份实现"至今没有门**——现有一切只是各消费方自己的测试，没有一把"新写一处 `hashlib.sha256(媒体字节)` 就红"的执法面（与旧垫片 import 棘轮同型缺口，本窗已排入收尾后第一件）。
- 文本 🟡：文案单源门 `tests/test_copy_single_source.py`（**簇数一律现算，别抄本行数**——本窗现算登记面 74 簇／检出 74 簇，旧写的"81 簇"是当时值）＋四不变量＋注毒四发；**好感度八档三份副本已归一**（`tests/test_affinity_tier_single_source.py`）。**最大一族 `interface-double` 42 簇的收编已出设计件**：`decisions/INTERFACE-DECL-DEDUP-PLAN-20260922.md`。两条必读纠正（本席逐条 AST/实跑复核过）：①该族登记理由写"42 簇全出自接口清单双写"**不成立**——族成员里混着路由 reason 与内部 note（抽样即见"提醒（12点提醒我写作业…）""预留：游戏直播事件接入""内部：桥接层…"），所以**只改 `InterfaceEntry` 一侧收不掉整族**，硬删登记面会撞 NEW/STALE 两条不变量；②好消息是**两份清单没有分叉**：`tests/test_capability_registry.py` 已把 base_router 三张字面表与 keystone 声明逐字段**双向锁等值**（实跑 18 passed）⇒ 塌成一份属"观察输出零变更"的安全收编；③陷阱：清完整族后总簇 74→约 32，**低于 `_MIN_CLUSTER_FLOOR=60` 塌陷地板**，必须同批正当下调地板（判据门槛与归一化规则一字不动）——否则门会因自己写的守卫而红。施工推荐方向＝keystone 为 prose 唯一真身、base 侧改派生，分 4 批；**建议本波不施工**（要改生产根文件 `plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py` 与 scripts，命中坐标棘轮禁碰面），并入 WP8 Wave 排期 → 待裁见设计件 §7。
- 模板 ✅（本波未新开面）：渲染契约三门现役绿；本波只动了 `echo.py` 一处（`/bot status` 纯文本健康行），**收尾须重录渲染哈希**。
- 内容 🟡：描述符只声明不抄数值（TTS `limits={}` + `config_keys` 指中央件 `tts_presets`），漂移门 `test_creation_tts_drift_gate.py`；prepared 行的 `input_protocol` 随形分化待落。
- 函数 🟡：壳派生纯函数（描述符与 handler 同源同代际）；占卜算法/存储单一真身（前波 WP9）；creation id 归一口 `reserved_channel_for()` 修掉"在册名≠域内键"真分叉。
- 参数 🟡：幽灵键普查 + `.env.example` 补键；`config_keys` 逐枚 `model_fields` 证真（**以 `Config.model_fields` 为准，`hasattr` 对真字段也 False**）；幽灵键逐键裁 → 待裁第 三节。
- 处理流程 🟡：**"所有内容走中央调度层"字面仍不成立**——命令形与 prepared 已全经缝（逐枚现算），主动投递三族已接出口（第四族见 §1 第 4 条），其余直呼与调度器自产仍在外面；自动配音旁路在册豁免未收。**本窗根修一条真缺陷**：降级腿预算原为"主链剩下的渣"（实测恒 1 秒）⇒ 降级在册而不可达；现每次尝试各得一份单次预算（硬顶不动，`_attempt_budget` 唯一出处）。⚠ 仍开着：**主链超时不进降级链**（待裁第 15 项）、降级变慢的可感代价（待裁第 16 项）。
- **TTS 也不例外** 🟡：命令形路已中央且实跑；**自动配音这条第二出站路未接**（它交"结果变换形"，命令形 handler 没有承接前序 result 的槽位，S-VOICE 判：必须先有 prepared 形才接得住，该腿现网休眠）；`base_router` 仍走旧垫片 import 路径。 **⚠ 2026-09-22 设计席 PLAN-VOICE2 复核纠出一条更严重的实况**：不经中央的配音路**不是一条而是两条**——除在册豁免的 `voice_enricher`（hook 态直连 `synthesize`）外，**默认路径的旧包装**（root `_attach_voice_reply` → `maybe_attach_voice`，其 `asyncio.to_thread` 实参在 `__init__.py` 早期定义处）是第二条活旁路，而且它与 hook 形**已不字节同构**（缺 `content_sha256` 与 M-14 有损留痕，T73 自注的协调债未偿）。⇒ 方案与分批见 `decisions/VOICE-AUTO-DUB-CENTRAL-LEG-PLAN-20260922.md`（推荐 payload 形媒体内容件、零新 adapter；三批：建件 → 翻面摘第一枚 xfail → 退役旧包装摘第二枚，只有第三批碰 root）；待裁 V-1…V-4。⚠ 本窗新立的媒体身份棘轮门**看不见这条旁路**（它只拦"第二份哈希实现"，不拦"根本不产内容身份"）——这条限缩**待写进门内**（收官全量在跑、树冻结，本窗不再改测试件；已挂任务 #9 的收口动作）。
- **预留 AI 绘画接口协议** ✅（协议层）/ ⏳（接线）：`CreationJob` 单一真身（本波抓到两腿"结果侧只是散文、全仓不存在 CreationJob"的真洞并补），绘画/TTS 同构锁 `test_creation_protocol_parity.py`；未接 provider 时诚实 `UNAVAILABLE`，禁假成功。真接供应商要配置键+体积上限 → 待裁第 2、3 项（席位拒绝自造数字）。

工作方式维度：并行满载+文件面互斥 ✅、补丁待审不自动部署 ✅（但"全部未入库"已被 `ebb7130` 订正为"基线已存档、此后未 commit"）、恶毒自攻评审 🟡（R1/R-A/R-ROLE/R-FAKE2/R-CENTRAL/R-CENTRAL-b/R-AUDIT/R-PREP/S-TRUTH 全归队，推翻 20+ 条含审计自身 3 处）、视觉裁定优先 ⏳（本波零卡片/渲染改动，未触发）、看不懂就重来 ✅（`PENDING-RULINGS` 一句大白话+A/B/C+推荐）。

---

## 2. 门禁真值：哪些命令、什么算绿、两个必须知道的陷阱

**统一前缀**（缺一条就别跑，Windows 铁律）：
```bash
export PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8 BOT_AUTOSYNC=0
../ChatBot_Runtime/venv/Scripts/python.exe -m pytest <目标> \
  -p no:cacheprovider --basetemp="$TEMP/<步骤名>" -q
```

**两个陷阱（先记住再看数字）**：
1. **`BOT_AUTOSYNC` 必须显式 `=0`**。缺省（`dev.ps1` 里是 `=1`）会在跑测时**自动 `--write` 生成物**，
   让 `verify_hashes` / `doc_sync` / `command_catalog` 这几把生成物门**结构性不可能红**=假绿。要真值必须自带 `BOT_AUTOSYNC=0`。
2. **裸 pytest 不带 `-p no:cacheprovider` 会一次污染约 371 枚 `.pyc` 进源码树**，随后 `runtime-layout` 就红。
   `py_compile` / `compileall` **无视** `PYTHONDONTWRITEBYTECODE`（本波主会话就是元凶，别再用它做语法核验——根文件语法一律 `ast.parse`）。
   `git status` **看不见**这些缓存污染（都在 .gitignore），不能当卫生体检。

**绿的含义**：本波的"绿"=**中央电池 + 投递族 + prepared/creation/copy/affinity 各门实跑零红**，且**生成物 `--check` 归零**。

**冻结窗终值（2026-09-22，主会话本人实跑，`BOT_AUTOSYNC=0`）**：
- **终局全量 `dev.ps1 -Task test`（清树后、`BOT_AUTOSYNC=0`）＝ 0 红 / 11760 passed / 13 skipped / 29 xfailed / 2 xpassed / 833.25s，`DEVPS1_EXIT=0`**（2026-09-22 01:26，所有实施席交卷、本窗六把新门全部被该轮收集：shim 棘轮／媒体身份棘轮／via 身份中央门／降级预算件都现查在跑测日志里）。⚠ 该轮之后只做过**两处纯注释改动**（旁路门那串说谎的 docstring、媒体身份门的限缩注记），无逻辑变化，已各自单跑复验（31 passed / ruff 干净），**不另起全量**；这条如实记在这里而不是假装覆盖到秒。
  上一轮同命令曾 **1 failed**——那条红＝本窗根修的现状锁（§5 第 10 条同族的"随迁未随迁"问题），**修在前、跑在后**才算数。
- 四件生成物 `--check` **全 EXIT=0**（真退出码，非管道尾码）；`runtime-layout` **PASS**；全树 `ruff` 22 错 / `mypy` 24 错
  逐条归属＝**本波面 0 错**（余量他波，按 #47 纪律不代修）。
- 树卫生：`__pycache__`/`*.pyc`/`data/` 全 0，三件工具缓存已清，根目录 `%TEMP%` scratch 已搬出源码树。
- ⚠ **本终值的有效期边界**：跑在 F-BAKE（中央降级预算）与 HARDEN-1（via 身份执法 / 入口判据常驻）**落码之前**。
  那两席交卷后**必须复跑**，否则"全量零红"就是拿旧树糊新账（本项目实锤过的假绿形态）。
- 继承红 campus 坐标棘轮**已由本窗闭合**（成因＝本波在 root 上方插行顶漂，由本席对齐活体，非"他波不代改"那条）。


---

## 3. 待办清单（按依赖序，全部指文件不重述）

1. **R8/R9 记账口径并入台账**：`tests/test_descriptor_wiredness_ledger.py` 的 invoke 命中集已并入
   `seam_registered_cids()`（`test_orchestration_callsite_single.py`），`GAP_CEILING` 是**手写整数常量**（现值以该文件为准；
   **绝不写 `=len(GENERIC)+len(NOT_WIRED)`**，有 AST 方向锁逼常量==现算、改回现算当场红）。落地后确认该门**没被 skip**（skip=静默变哑，不是绿）。
2. **prepared 剩余批次**：施工图 `decisions/PREPARED-ADAPTER-PLAN-20260922.md`（B0 地基+金丝雀已落，B1 十枚、B2 一枚已随批并入；
   剩余按 S-PREP B0–B8 分批，**每批一枚金丝雀先行、每批同批改缺口账**）。
   **B6「root 内联闭包」那批必须串行**——它要先把内联闭包提成具名 builder（生产码改动，会咬装配现场）。
3. **自动配音第二条腿（`voice_enricher`）**：等 prepared 形接得住，S-VOICE 只交了 RED+xfail 零生产改动；现网该腿休眠。
4. **调度层 Wave 1–4 逐域**：规格 `docs/design/capability-orchestration-adoption-spec.md`（§4 Wave 序、§7 禁第三套）。
5. **`WP3-TAXONOMY` 紧急域定级改造**：✅ **本窗已落地摘牌（2026-09-22 实施席 WP3-IMPL）**——`grading.py` 新增 `earthquake_level`（只吃震级/深度/坐标三枚源侧事实，境内·境外两张分档表 + 深震降一档 + 无震级出最低档）、族内合法色档 `_legal_color_levels`（由注册表派生）、`grading_candidates` 审计面，**种类词整体退出缺省关键词表**；紧急域两测试件现跑 **124 passed / 0 failed / 0 xfailed / 0 xpassed**，10 枚标记点／21 实例清零而**断言期望值一寸未动**。**接手者读这条的方法论**：本窗挂账时量出的残差是「92 passed / 18 xfailed / 2 xpassed（当时值）」，那两枚 xpass 后来被证实**不是绿灯**——同一条 bug（旧词表 P0 档含种类词「地震」，见标题就提 P0）恰好撞中境内 6.5/7.1 两格的期望值，而矩阵其余格全判 P0。⇒ 铁律留在这里：**xpass 是"隐式兜底"的线索，永远不许当成"这块已经对了"**；要摘牌先回答"今天凭什么给到这个档"。施工与逐项证据 `.superpowers/sdd/2026-09-21-unify-wave/logs/SEAT-WP3-IMPL.md`；**行为变更报备**：定级整体变保守（该席 598 条真数据对比＝变吵 0 条／变安静 192 条），且未经真机——评审席 REV-WP3 攻击报告回来前视同待裁。
6. **16 条待裁项**：`decisions/PENDING-RULINGS-20260922.md`（一句大白话+字母选项+推荐，**指过去、别在这儿重开**）。
   其中第 9（闸要不要开）、10（挂死要不要出诊断卡）、11（层 2 要不要执法 feature gate）、12（空角色=系统特权豁免要不要收紧）是本波新长出来的。
7. **收尾网**：生成物三件 `--write` + `--check` 归零 → 文档棘轮基线由 owner **逐条改回真身再降**（只降不升）→ 冻结窗清树 → 四门禁全量（`dev.ps1` 只有用户能跑）→ 台账 #49 / HANDBOOK §39 / 本文件收口。见 `CLOSEOUT-RUNBOOK-20260922.md`。

---

## 4. 禁碰面清单（本波收紧过的，后来者**别用"放宽判据"去"修"**）

- **`GAP_CEILING` 是手写整数、不可导出**：改回 `len(...)` 现算，`test_gap_ceiling_tracks_registered_debt` 方向锁当场红（旧写法与被检清单同一表达式=真缺口永不超过上限=结构性假绿）。只能**只降不升**。
- **`test_dedupe_predicates_share_one_implementation` 有两条委托边**（`tests/test_outbound_gate.py`）：
  `is_emergency_dedupe_key` **和** `active_push_key_shape_ok` 都必须既被 import 又被调用，键规范规则本体**只住在 `domains/emergency_info/service/dedupe.py`**，闸侧零新正则。把非 emg 分支内联成宽松谓词会被第二条边抓到（POISON1 实证）。
- **多入口活性锁** `test_every_resolved_capability_entry_reaches_the_central_seam`（`test_prepared_adapter_canary.py`）：凡 root 里比较过某 `capability_id` 的分发函数必须汇到两条缝之一。取数口 `_root_dispatch_comparisons()` **单一实现**（violations/覆盖面/注毒自证共用同一判据，别再抄第二份 AST 抽取）。非空转锚点写的是"当年出事那五枚（weather/wiki/news/eat/epic）必须被看着"，**不是函数个数**。
- **`seam_registered_cids()` 只证声明**：它降账的前提是**多入口活性锁同时成立**——两把锁缺一不许降账（R-PREP C-1 就是栽在"声明即通电"，见 §5）。docstring/缺口账头注都写了这句，别删。
- **文档死链/坐标棘轮只降不升**（`test_doc_link_integrity.py`）：S-DOCLINK2 已把 `MD_DEAD_LINKS` 收到 0、S-DOCFIX 在逐条改回真身。**禁止为了变绿直接调大基线数字**（那是把执法面调松）。
- **`test_outbound_gate.py` T6 = 正向锁**：root 必须仍引用中央出口、裸 `send_queue.submit` **==0**；引用面白名单逐文件放行 root，**不许放开整树**。
- **`GAP` 门的 `orchestrated_command` 幂等标记** `orchestrated_capability_id`：命令入口包过、汇合点不得再包一次（否则一次调用两层治理跑两回、审计落两行）。
- **中央壳 `orchestrated_command` 未在册 id 原样直呼**：这是逐字节旧路，别"顺手"给它加治理。
- **审计 sink 幂等**：`AuditHookRegistry.register` 按 `is` 去重（重复注册会把一次终态放大成 N 行、污染"每次调用恰一行"判据）。

---

## 5. 踩过的坑（含本波自己打的脸，每一条都真咬过人）

1. **C-1：四族主动投递接了闸、但键规范仍只认 `emg` ⇒ 开闸当天四族全量静默丢消息**，而关态（现网缺省 `enabled=False`）逐字节直通，**既有闸测试一片绿（当时 59 例，枚数以现跑为准）测试全绿看不见**。
   根因=`dedupe_key_shape_ok` 整条委托给 `is_emergency_dedupe_key`（第一行 `segments[0]!="emg"⇒False`）。修法=申报制命名空间（`dedupe_namespace` 强制申报、漏报即 `TypeError` 而非静默丢），规则本体不出 `dedupe.py`。**属"关态绿=测的是闸不存在"病型**。（`SEAT-MAIN.md` §33）
2. **多入口绕过缝、缺口账却按声明降账 = 假账**：`bot.weather` 除命令入口外还有别名入口、自然语言入口两条把闭包直接交给 `_run_capability_through_pipeline`（层 2 零参与），而缺口账凭纯声明式 `seam_registered_cids()` 就记它 WIRED 并降棘轮——**更糟的是那条判据 docstring 把"生产可达"甩给一把根本不存在的活性锁**（循环论证+注释说谎）。修法=包缝下沉到汇合点 + 补真·多入口活性锁。**这是"存在性糊过活性判据"的又一例**。（§38）
3. **`_skip_gate()` 那条"因 bug 才绿"的用例**：`max_per_target_per_minute=0` **根本没进限流腿**（有 `>0` 守卫），那条"闸拦下"用例其实是靠 C-1 才绿的；改限额=1 后又暴露**限流给的是 defer 不是 skip**（顺延态照旧入列带 `deliver_after`），旧断言"拦下⇒队列零入列"也错。用例改名并换四件真语义判据。（§33 被推翻①）
4. **注毒用例写死受害者 cid ⇒ 它被迁进 WIRED 那一刻，注毒变空跑**；同理写死受害函数名、`"reminder"` 期望值都栽过。改法=一律**现算/取差集**（`sorted(set(NOT_WIRED)-set(invoke_hits))[0]`），理由写进 docstring。地板数字也别想当然（写过 `>=5` 实跑得 2）。（§35/§36/§38 自咬）
5. **文档里写花括号路径简写**（`test_..._{1,2}.py`）**会被链接门当成一个不存在的文件坐标**=本席自造红；写文档时别图省事，路径要么写实要么别写。（§37 末、§34 同类）
6. **`py_compile` / `compileall` 无视 `PYTHONDONTWRITEBYTECODE`**（主会话自己就是污染源），`dev.ps1 -Task typecheck` 也会造 `__pycache__` ⇒ 跑过 mypy 必回头清树。语法核验用 `ast.parse`。（§24⑨、`findings.md`）
7. **把席位简报的行号/键清单当真相**：派给 S-ENVEX 的 7 键里 3 枚 `config.py` 根本不存在（误读别席归属）；`GAP_CEILING` R-CENTRAL 读到 117 是旧快照、04:52 后已是别的值。**认文件现值、不认席简报**；键名派生前自己 `grep config.py`。（§24①、§33④）
   ——**本席写这份交接时也撞到一条**：`SEAT-MAIN` §37 停在 WIRED21/NOT_WIRED88/`GAP_CEILING=98`，现码是 **97**（B2 批 1 枚已并入库、日志未回填）。故本文件对一切计数只指真身/现算门，不抄死数。
8. 其它记过账的：权限门**方向反装两次**（平坦求交→层级→空角色豁免，两次都是"看着更严、实际拒错人"，豁免只做在 invoker 门上、**不写进共享谓词 `roles_satisfy`**）；吞异常=静默拆掉错误卡旁路（`INVOKER_ERROR_DATA_KEY` 让崩溃原样回层 1）；中央件**构造位置是装配顺序问题不是风格**（闸原建在消费者之上、两投递函数还是模块级 ⇒ "闭包可捕获"是假前提）；测试污染 `default_invoker()` 单例（用 `_probe_invoker()`/mini 实例）；`M-3` 评审意见**拒修附理由**不盲从。（§13/§25/§29/§34/§36）
9. **管道吞退出码 = 把假绿写进自己的复跑手册**：本会话在冻结窗用 `cmd | tail -2; echo "EXIT=$?"` 连取四次"EXIT=0"，那全是 `tail` 的码；重跑改成先重定向再取码才是真值。**门"绿"的证据必须来自门本身**，不能来自它后面那一环。（`SEAT-MAIN.md` §45）
10. **修好一处死导入 ≠ 装了把能防复发的门**（全量跑完后处置，先登记）：mypy 顺手抓到 `domains/chat_reply/character/knowledge_service.py` 的 `from .kb_wiki import …` 指向 v21r2 重组后的**不存在的模块**——同族缺陷 2026-09-19 已在 `providers.py` 修过，但当时的门 `test_every_kb_wiki_import_path_in_providers_resolves` **扫描面写死成 providers.py 一个文件**，所以第二处复发时全树仍绿。更糟的是这条炸点被 `service_wiring.py` 的 `except Exception` 压成一行 warning。精确成因链（**本席初判"调用方从不传 stores"坐标写错，已由独立席纠出并复核**）：根 `__init__.py` 调 `register_v21_services(config)` **只传 config**，`service_wiring.py` 的 `knowledge_stores` 形参缺省 `None` ⇒ `build_knowledge_service(config, stores=None)` ⇒ `if stores:` 恒假 ⇒ 每次都走那条会炸的分支 ⇒ 该服务**一开闸就必然装配失败**而账面只少一行 warning。**量级与 §1 那两枚 P0 同型**：整条链挂在总闸 `bot_v21_service_wiring_enabled`（缺省 `False`、生产 `.env` 未设）后面 ⇒ 现网零影响，但属于"开闸即坏"。⇒ 两形态合体：「一处修、其余副本漂」+「门只覆盖被抓过的那一件」。修法=改真身路径 **+** 把门扩成"扫全包每一条 kb_wiki 导入"。（`SEAT-MAIN.md` §46）

---

## 6. 证据地图 + 复跑命令簿（Git Bash，直接粘贴，都带 §2 前缀）

**逐席/逐回合原始记录**：
- 主会话流水（本波真相在此，不在本文件）：`logs/SEAT-MAIN.md` §20–§38（§33=C-1、§34=评审处置+别名清点、§35=prepared B0、§36=I-2/M-2/M-3、§37=B1、§38=多入口 R-PREP C-1）。
- 完成度审计（逐维，已被 adversarial 席订正一轮）：`decisions/COMPLETION-AUDIT-20260922.md`。
- 待裁 12 项：`decisions/PENDING-RULINGS-20260922.md`。收尾顺序有意的：`decisions/CLOSEOUT-RUNBOOK-20260922.md`。
- prepared 施工图：`decisions/PREPARED-ADAPTER-PLAN-20260922.md`；主动投递改道裁定件：`decisions/WAVE42-active-push-central-exit.md`。
- 规格权威：`docs/design/capability-orchestration-adoption-spec.md`（§5 两层边界、§7 禁第三套）。

**复跑（挑要验的点，指符号名不指行号）**：
```bash
# 中央壳与两同名契约归并
pytest tests/test_capability_result_unique.py tests/test_v21_s10_protocols.py \
       tests/test_capability_single_registration.py -q
# 命令形缝 / 单执行点位 / 多入口活性锁（R-PREP C-1 的判据）
pytest tests/test_orchestration_callsite_single.py tests/test_prepared_adapter_canary.py -q
# prepared 逐批 + 逐 id 行为矩阵 + 缺口账棘轮（GAP_CEILING/NOT_WIRED 现值以账件为准）
pytest tests/test_prepared_adapter_batch1.py tests/test_prepared_adapter_batch2.py \
       tests/test_prepared_adapter_batch3.py tests/test_central_dispatch_matrix.py \
       tests/test_descriptor_wiredness_ledger.py -q
# 主动投递单一出口 + 键形两条委托边
pytest tests/test_outbound_gate.py tests/test_outbound_bypass_prohibition_gate.py -q
# creation/TTS 协议对等 + 文案单源 + 好感度八档单源
pytest tests/test_creation_protocol_parity.py tests/test_copy_single_source.py \
       tests/test_affinity_tier_single_source.py -q
# 2026-09-22 冻结窗新落四把门（via 身份耐久 / 降级预算 / 两条"只准降"棘轮）
pytest tests/test_central_via_identity_and_entry_durability.py tests/test_central_fallback_budget.py \
       tests/test_legacy_shim_import_ratchet.py tests/test_media_identity_single_source_ratchet.py -q
# 现算取数口＝账的真身（别信任何文档里写死的数，包括本页）；两本账分开现算
python -c "import sys;sys.path.insert(0,'tests');import test_legacy_shim_import_ratchet as g; print('prod',len(g.live_shim_leaves()),sum(g.collect_legacy_shim_edges().values()),g.SHIM_EDGE_CEILING); print('tests',sum(g.collect_tests_legacy_shim_edges().values()),g.TESTS_SHIM_EDGE_CEILING)"
python -c "import sys;sys.path.insert(0,'tests');import test_media_identity_single_source_ratchet as g; print(g.scan_identity_sites())"
# 揪 xpass：挂账池里混着"今天已经对"的实例＝隐式兜底的线索（本窗就这么抓到 WP3 那两格，已坐实并摘牌）
pytest tests/test_emergency_info_taxonomy.py -q -rX
# 生成物体检（先 --check，红了才由 owner --write）
pytest tests/test_cross_validation_gates.py tests/test_doc_sync_gates.py \
       tests/test_doc_link_integrity.py -q
```
生成物 `--check` **取退出码别用管道**：`cmd | tail; echo "EXIT=$?"` 拿到的是 `tail` 的码=**假绿**（本会话 2026-09-22 冻结窗当场栽过一次，见 §5 第 9 条）。正确写法 `cmd >/tmp/x 2>&1; echo "EXIT=$?"; tail /tmp/x`，或 bash 用 `${PIPESTATUS[0]}`。全量四门禁（`dev.ps1 -Task test/lint/typecheck/runtime-layout`）**只有用户能跑**，收尾冻结窗跑。

---

## 7. 下一个 AI 请先做什么

**先跑 §6 中央电池那一组（`BOT_AUTOSYNC=0`）确认地基没塌**，再读 `COMPLETION-AUDIT` 与 §1 那四条「在册但未执法／同级披露」与 §4 禁碰面；
然后**只做一件事**：按 `CLOSEOUT-RUNBOOK` 的**固定顺序**（先记账口径 → 吃评审红 → 重录生成物 → 冻结窗清树）推进收尾，
把 prepared 剩余批次里**最干净的下一枚金丝雀先行**接进去。**不 commit、不重启**（提交与重启裁决权在用户），
**不放宽任何一把本波收紧的门换绿**——要动判据先进 `PENDING-RULINGS` 让她拍板。凡遇 campus 坐标棘轮那条继承红：认、不代改。
