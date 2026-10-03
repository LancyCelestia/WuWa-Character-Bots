# M17 工单：M-17 自动配音安全门补传 sender_id 的外溢面分析（2026-10-02 下午窗）

席 M17（只读分析席）。对象＝席 INT 在 `plugins/bot_unified_runtime/domains/media/capabilities/tts.py:1556` 给 M-17 群面门补传第四参 `sender_id`（未提交，工作树态；同文件另混席 B1 `_quota_bound` 配额件，与本分析无关）。使命＝把行为变化外溢面讲清，供用户裁决"上车/回退"，不代裁。全部结论带 file:line；`.env` 读数为本席实读（只读开关布尔，未触碰密钥）。

## ① 链路：这扇门挡的是什么

- **门真身**：`should_voice_reply(config, message, result)`＝对话**自动配音**的完整门链纯谓词（tts.py:1517-1577）。挡的形态＝**bot 自己 `bot.chat` 回复的自动配音**（bot.chat 文字回复 → 追加合成语音出站），不是命令路语音（`build_tts_capability` 另有自己的门），也不是语音识别。
- **调用者（全树恰三处，全为同参转发）**：`voice_enricher.py:143`（hook 短路「该不该配」）、`result_transform.py:264`（中央第三形真身幂等复读）、`__init__.py:375`（装配短路）。门链冻结序：hook 总键 ∧ 无既有 issue ∧ should_voice_reply ∧ 取文（含内容门）∧ 文字硬顶 ∧ 产出步（result_transform.py:246-248 docstring）。
- **谁的消息会经过**：仅 `group_id` 非空的消息进 M-17 门（tts.py:1555 `if group_id`）；私聊消息永不进（私聊面不吃群名单，tts.py:1533-1534）。群内**任何触发了 bot.chat 回复的消息**都过这道门（上游能否回话由 policy/gate 另判，不在本门）。
- **门后下游**：过门后取文走 `resolve_speech_text`→`speech_block_reason`（tts.py:1329-1357）——**这半边内容门在 HEAD 就已传 sender_id**（HEAD:1316，改前既有款），即 TTS 的"文字能说才配说"判据早已同源带人。

## ② 语义差与新放行集合

- **改前**：群面自动配音要求 `G ∈ 群白名单`（减群黑），与发言人无关。
- **改后**：`G ∈ 群白` **或** `S ∈ 私白(非空) ∧ S ∉ 私黑`，群黑仍永远最先赢（判定顺序①群黑→②群白→③人腿→④False，content_route.py:931-968；判定真身在 content_route，tts.py 只是把 last-mile 消费者接上）。
- **新放行精确集合**：`{(G,S): G∉群白 ∧ G∉群黑 ∧ 私白非空 ∧ S∈私白 ∧ S∉私黑}` 的群消息——**按消息逐条人闸**：同群里非白名单成员的消息仍被拒（sender 不中即 False），不是整群放开。
- **两案权衡**：
  - 「文字都露骨了语音却不配」：同一集合里 chat 正文亲密门（chat.py:3958-3961，同源带 sender）与 TTS 内容门（tts.py:1339-1344，HEAD 既有带 sender）都已放行——改前 tts.py:1556 是**最后一个不帶 sender 的消费者**＝「半条腿」（tts.py:1552-1554 新注；tests/test_intimate_group_switch_delivery.py:694-699 同判词）。本次改动**不新增政策**，只是把 2026-10-02 用户在 content_route 裁定的人腿补齐到最后一个消费者。
  - 「语音是更强暴露面」：语音全群可听、落盘可转发、人格归因更强；但**受众集合与已放行的露骨文字完全同群**，且露骨**内容**只在 intimate 档激活时才产生（per-user 钉+TTL，content_route.py:974-1009），TTS 侧还有内容门 fail-closed 复判。残余差异＝媒介形态，非受众扩大。
- **附注**：TTS 门链本身不查 intimate 钉——它闸的是"会话面"；露骨与否由上游生成档位+下游 assess_public_content 把守，层间分工与改前一致。

## ③ 护栏清单（一条群消息要被配音须全过；含现态实读）

| # | 闸 | 位置 | `.env` 现态（实读） |
|---|---|---|---|
| 0 | 上游回话门（群触发/安静时间/限流/搭话好感门） | policy/gate | 未变，不在本波 |
| 1 | hook 总键 `bot_tts_voice_hook_enabled` | voice_enricher.py:138 / result_transform.py:258 | **false**（.env:479） |
| 2 | 既有 issue 短路 | voice_enricher.py:140 | — |
| 3 | TTS 总闸 `bot_tts_enabled` | tts.py:1542 | **false**（.env:431） |
| 4 | 自动配音闸 `bot_tts_auto_reply_enabled` | tts.py:1544 | **false**（.env:436） |
| 5 | 未带音频 ∧ 出自 bot.chat | tts.py:1546-1549 | — |
| 6 | scope 礼仪门 `BOT_TTS_AUTO_REPLY_SCOPE=private` ⇒ 群消息在此全灭 | tts.py:1550→1488-1494 | **private**（.env:437）＝群面的**独立第二总闸** |
| 7 | **M-17 名单门（本次改动点）** | tts.py:1556-1561 | — |
| 8 | 概率门 0.10 确定性哈希 / always=false | tts.py:1563-1577 | .env:440=0.10 / 442=false |
| 9 | 内容门（同源名单+assess_public_content，fail-closed）+文字硬顶 | tts.py:1338-1357 / result_transform.py:299-309 | — |
| 10 | **生效面**：全部未提交未重启 | 台账 #10 | 生产进程仍跑旧代码 |

**结论**：总闸关＋自动闸关＋hook 关＋scope=private，四重**相互独立**的关断全部压着群面；叠加未提交未重启 ⇒ **TTS 总闸关闭期间此外溢零实害（verified：.env 四行实读）**。要任何实害须用户同时手动开总闸+自动闸+hook 且把 scope 改 group/all 再重启——每一步都是显式动作。

## ④ 两案对照（不代裁；PENDING-DECISIONS-20261002b.md Y1 已列双向）

- **案A 回退**：tts.py:1556-1561 恢复三参调用（删 `sender_id=` 实参，8 行→1 行）。content_route 对空 sender_id＝旧版逐字节（content_route.py:953-954 注明）⇒ 该消费者语义干净回到"仅群白名单"。**连带成本**：① tests/test_intimate_group_switch_delivery.py:694-731 的 AST 消费者腿必红，须同批删/改判据；② tts.py 退回半条腿，与同源消费者 chat.py:3958、tts.py:1339 不一致（同一会话文字面人腿开着、配音面关着）；③ ⚠ 同文件混有席 B1 `_quota_bound` 未入库件——**禁止整文件 `git checkout` 回退**，必须 hunk 级手工回退，否则吃掉 B1 件。
- **案B 独立开关**（如 `bot_tts_autodub_person_leg`）：动 config.py 新字段＋`.env.example`＋（要热改再加 settings.py）三面齐（台账 #68 幽灵字段教训：只补一面必红另一面）＋tts.py:1556 加分支＋测试腿。**代价**＝在「名单＝安全门单一事实源」（tts.py:1528-1534 分层 docstring）之外造第二把政策真身，漂移面 +1；**收益**＝用户可单独关配音面人腿而保留文字面（分级暴露面诉求）。

## ⑤ 建议（一句话）

建议上车（维持现状）：该改动不立新政策，只是把已裁定的 content_route 人腿补齐到最后一个半条腿消费者、使语音与文字同源同判，且四重独立关断下现时零实害；若用户确要"语音单独降级"，选案B并接受第二真身代价。

---
席 M17 2026-10-02｜只读，零 git 写/零进程动作/零配置改；本工单为本席唯一落盘件。
