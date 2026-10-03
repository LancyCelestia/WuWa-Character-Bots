# TW8 工单：触发词债「余 8 枚」逐枚点名（2026-10-02 下午窗，只读席）

席 TW8｜使命＝把 `tests/test_trigger_word_single_source.py` 词面尺超上限的 8 枚差数逐枚点名，交还债主波（HANDBOOK §61 D-21 执行账）。全程只读（本文档除外）；行号为 2026-10-02 现算值、随编辑漂移（#50★）。

## ① 红输出末行原样

```
FAILED tests/test_trigger_word_single_source.py::test_word_site_debt_within_ceiling
FAILED tests/test_trigger_word_single_source.py::test_copy_turned_into_reference_lowers_ledger_stays_green
2 failed, 16 passed in 112.28s (0:01:52)
```

关键断言（两枚同因）：
- `AssertionError: 词面级独立声明债（计账）475 > 上限 467（raw 549，名册抵销 74）`（:696）
- `AssertionError: 方向锁失效：手抄=565 引用=549 基线=549 计账基线=475 上限=467`（:839）

## ② 点名表：超 8 的真实构成＝新债 9 枚 − moegirl 自然回落 1

方法（台账 #68 正道）：`git archive 831b02b`（末次核账 commit，2026-09-27）抽仓库外同尺复跑，三趟对账 P1 现树×现行尺＝475/549/74 ✓、P2 基线树×基线尺＝467/527/60 ✓（与核账注原文一字不差）、P3 基线树×现行尺＝P2 ⇒ 判据扫描面零漂移，分桶＝纯树漂移；P1' 复算确定性 ✓。固定现行名册逐词归因 ΣΔ＝**+8 整**。

| # | 词面 | 声明位键（登记用） | 计数载体行（真身文件:行） | 所属能力面 | 债计 |
|---|---|---|---|---|---|
| 1 | `我` | `inline:plugins/bot_unified_runtime/domains/chat_reply/capabilities/affinity.py` | affinity.py:414（`arg not in {"我","自己","me"}`） | 好感度（个人板/群板切换） | 三位共 +2（每词兜底留一位） |
| 2 | `我` | `inline:plugins/bot_unified_runtime/domains/chat_reply/character/reflection.py` | reflection.py:829（`not text.startswith("我")`，quirk 无类目门） | 记忆反思回路 | （同上合并计） |
| 3 | `我` | `…/domains/schedule/capabilities/schedule_board.py#t1:_QUESTION_FIRST_PERSON_HEAD_WORDS#regex` | schedule_board.py:162（`"我的\|我\|本人\|自己"`） | 日程板问句第一人称头词表 | （同上合并计） |
| 4 | `本周` | `inline:…/domains/schedule/capabilities/schedule_board.py` | schedule_board.py:906（`return today, week_sunday, "本周"` 混合元组） | 日程板取数解析 | +1 |
| 5 | `randpic` | `inline:…/domains/meme/capabilities/randpic_timing.py` | randpic_timing.py:132、143（`audit_tags=("randpic", f"timing:…", …)` 混合元组） | 随机图定时波审计标签 | +1 ⚠ **§61/REMAINING8.tsv 漏列** |
| 6 | `identity` | `inline:…/domains/chat_reply/character/person_profile.py` | person_profile.py:349（`return "identity", body` 混合元组） | 按人画像（需求11） | +1 |
| 7 | `poke` | `inline:…/domains/chat_reply/capabilities/poke_routing.py` | poke_routing.py:132、699、763（臂名/判定集混合容器，三处全撤才掉单元） | 戳一戳三线选路 | +1 |
| 8 | `关` | `inline:…/domains/chat_reply/character/reply_policy.py` | reply_policy.py:575（`text.lower() in {"off","none","关","默认不开","不开","无"}`） | T8 回复风格关闭解析 | +1 |
| 9 | `yes`/`no` | `inline:…/domains/chat_reply/policy/gate.py`（两枚同源两腿） | gate.py:107、109（`.env` 布尔折叠集合） | 门禁配置布尔解析（无用户触发面） | +2 |
| − | `moegirl` | （回落位）`inline:…/bot_unified_runtime/__init__.py` 已消失 | — | 随机 cos 相关（#19） | **−1 信贷** |

锚点事实：`我` 入债的根因位＝#3 schedule_board 头词表（831b02b 后新入库）把 `我` 送进词汇表，才唤醒 affinity/reflection 两枚内联旧字面（09-29 S-BASE 摘牌时它们确不在场，现又回归）。基线 `我` 单元 0 → 现 3。

## ③ 两案闭法动点（只列动点，不代裁不改）

**案①补登记**（动一处：`tests/test_trigger_word_single_source.py` 的 `INTENTIONAL_UNITS` 追加第六批；上限 467 与 AUDIT_HISTORY 一字不动，先例＝ROSTER-467-b）：
- 必登 8 枚（→475−8=467 恰贴线回绿）：上表 #1 #2 #4 #6 #7 #8 #9两腿；#1/#2 按 REMAINING8.tsv 第 13/14 行「HEAD 在册原行复登」（第二批原行 git 历史可溯）。
- 建议加登第 9 枚 #5 `randpic@randpic_timing`（owner=`bot.randpic`，`_CAPABILITY_ID` 在 randpic_timing.py:38）→475−9=466，不靠 moegirl 信贷托底。
- #3 schedule_board `我` 位**不必登**（min(hits, len−1) 帽下登 2 枚已抵满），但须知情：它是在册免费位。
- 🔴 #9 与 #5 的「确属有意」理由须由 gate 波／randpic 波 owner 自写（§61 红线：主会话不替别家波次写判词）。

**案②撤词／真改引用**（动生产源码，逐位动点＝②表载体行；撤词改判定语义，须 owner 波自证行为不回归）：
- `我` 三位的最小真修＝schedule_board.py:162 头词表不再以裸 `我` 入词汇表（撤 #3 一位 ⇒ affinity/reflection 两枚内联自动跌出词汇表，`我` 债归零）；或 reflection.py:829 / affinity.py:414 改引用同一常量（跨域 import 违强隔离，需裁）。
- `本周`＝schedule_board.py:906 改引 `_QUESTION_WINDOW_TERMS` 解析真身；`identity`＝person_profile.py:349；`poke`＝poke_routing.py:132/699/763 三处齐动；`关`＝reply_policy.py:575；`yes/no`＝§61 新格② 中央布尔判定案（真身候选 `scripts/runtime_paths.py`，十处改引用＋注毒腿）——两案在 #9 上合流。

## ④ 与 HANDBOOK §61 在册账的对照

- **总数同口径**：§61「余 8 枚、上限仍红」与本次现算 475−467=8 一致；其读数链（487→475、抵销 62→74、名册 74 条、16 passed/2 failed）全部复现 ✓。
- **枚举不同口径**：§61/`%TEMP%\cb-d21\REMAINING8.tsv` 的 8＝我×2＋本周＋关＋identity＋poke＋yes＋no；本次现算超 8 的真实构成＝**9 枚新债 − moegirl 回落 1**。§61 清单**漏 `randpic@randpic_timing.py`**，其位被 moegirl 信贷（`__init__.py` 内联位消失，未深挖归属）暗中补足——按 §61 8 枚登记虽可贴线回绿，但 randpic 位无登记＋信贷是隐形缓冲，任一反弹即再红。
- **「我」第三位**：schedule_board 头词表位（#3）§61 未提；不登记不影响回绿（每词兜底一位），但它是唤醒另两位的根因位，案②应优先看它。
- **入库状态**：14:10 会话的第五批 12 枚＋T25「待审」只在**工作树**（`git diff HEAD` 唯一 hunk＝该批），HEAD 未含；§61「已入库」实为「已写入在册文件、未提交」（该节自记「不提交」，语义无冲突但字面易误读）。
- gate yes/no 来自 f3f177a（10-01 P2a）与本次「831b02b 后新增」归因一致 ✓。

## ⑤ 未尽事项

1. #9（yes/no）与 #5（randpic）的 owner 判词空缺：分别待 gate 波（§61 新格②③ 待裁——若③通过布尔位剔出触发词债，超 8 变超 6，本表相应缩）、randpic 波。
2. §61 新格①（`ledger_stamp()` 不含 inline 腿＝指纹对内联漂移结构性失明）仍开放；本席三趟对账恰好全靠内联腿，佐证该格必修。
3. moegirl −1 信贷的归属波未深挖（`__init__.py` 内联位消失）；若彼波回写该位，账 +1。
4. 本席零写（除本工单）：echo.py 未碰、名册未动、零 git 写、零进程动作；测试读数 16 passed/2 failed 为本席实跑（112.28s）。
5. 建议债主波收账时把本表 9 枚键与 REMAINING8.tsv 合并成单一可粘贴册，淘汰「8 枚」旧口径，防下次对账再出隐藏信贷。
