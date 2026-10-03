# CMV2 工单 — 提交清单最终增量（席 CMV2 · 2026-10-02 下午窗 · 只读清单席）

> 使命：出 CM＋CMV 合卷之后的**最后一版增量**（CMV3 口径；之后主会话收卷不再批量落盘）。
> 手段＝`git status --porcelain` 全量对照 CM/CMV 两单批表；零 git 写／零进程动作／零配置改；唯一写面＝本工单。
> 执行方式＝「CM 原单＋CMV 勘误＋本增量」三卷合读。

## ① 快照

- HEAD＝`143098d`（`v0.0.1-alpha.3`，CMV 时刻后**零新提交**，verified）。
- 初拍＝**120 行**（2026-10-02T10:20:16Z）；复拍＝**121 行**（10:23:27Z）。窗口内新落 `patches/NB4-FOUR-REDS-20261002.md`——**别席仍在写盘**，本单只对 10:23:27Z 快照负责。
- 构成＝**M 60＋?? 61**。M 面自 CMV（09:35Z，102 行＝M60+??42）以来**零变化**；新增全部为 19 枚 ?? 工单，逐枚严丝合缝（comm 双向对账：新增 19、失踪 0，verified）。
- UNO/INV 单自称「status 已 116」：系其落笔时读数；本席现算＝121，以现算为准。
- 「MER 稿」**不在盘面**（patches/ 实查无 MER-*；若指 DRAFT-HANDBOOK-MERGE，已入 CMV 批E＋5；若另有意稿，落盘后随批E 补）。

## ② CMV→CMV2 新增面（19 枚 ??，全归批E）

CMV-COMMIT-DELTA-20261002（本单前身）、FCK-DRAFT-FACTCHECK、FLR-LEDGER-FULL、HLP-HELP-COUPLING、IDX-PATCHES-INDEX、INJ-SWEEP、INV-WRITTEN-FACES、M17-TTS-SPILLOVER、NB4-FOUR-REDS、OWN-DBOWNERS-XVALID、RESTART-CHECKLIST、RLX-PROCESSLOG-RECOUNT、SNP-STRUCT-NET、TLN-TIMELINE、TRG-HOTFACE-LOCKS、TW8-TRIGGER-DEBT-8、UNO-NEXT-ACTIONS、WCH-HOTFACE-WATCH、WLF-WAVE-LOCKS-FINAL——全部 `patches/*.md` 只读席工单，无一源码/测试/生成物。

## ③ 最终批表（七批总账；只列本版增量，未变批引前单）

| 批 | 枚数 | 本版动作 |
|---|---|---|
| A 挪家 | 3 | 无变化 → CM 批A |
| B 亲密人员门 | 7 | 无变化 → CM 批B＋CMV 补 IVF |
| C 测试件 | 23 | 无变化 → CM 批C |
| D 生产件 | 12 | 无变化 → CM 批D（nonebot.py 仍剔除） |
| **E 工单/文档** | **34**（15→34） | **＋19＝②节清单**；原 15 枚见 CM 批E＋CMV 补入（L2/CM 原单/AUD/PENDING/DER/DRAFT） |
| F 地板复录 | 1 | 无变化 → CMV 批F（Z1 腿收笔与否仍待用户确认） |
| G 生成册 | 1 | 无变化 → CMV 批G |
| **合计** | **81** | 五批 52→62→**81** |

总账核验：121＝批内 81＋禁入 8＋待裁 3＋暂缓 29，账平（verified）。
- 禁入 8：AGENTS.md、HANDBOOK、command-catalog、render_hashes.json＋.meta、test_trigger_word_single_source、echo.py、meme_library.py（→CM③＋CMV 解禁 auto-facts 后）。
- 待裁 3：.zcodeignore（来历未明）、personas/shorekeeper/imagery_families.txt＋tests/test_reply_style_imagery_default.py（规则 8 灵魂资产对，用户单独裁）。
- 暂缓 29：#66 三件、voice_enricher、日程族二件、media_archive、文档完整性族余部 8、X2 双锁对、F3 邮件对、未认领 M 测试 10（→CM③；CMV「暂缓余 30」按文件计实为 29，本席现算口径）。

## ④ 禁入复核（🔴 新面孔审查）

- 19 枚新 ?? **全部为 patches/ 工单**：无 Temp 残留、无日志、无 .pyc/__pycache__、无 data/、无半截源码——**无需新增禁入项**。
- 旧面孔维持：.zcodeignore 仍待裁不收；echo/meme_library/test_trigger_word 仍在飞不收；command-catalog/render_hashes 生成物仍未收口不收。
- ⚠ 本单落盘后 `patches/CMV2-FINAL-DELTA-20261002.md` 自身也成 ??——归批E（同 CMV-DELTA 先例），批E 实收 35 枚时以 add 后 `git diff --cached --name-only` 核对为准。
- 若收卷前再有工单落盘：同形 `patches/*-20261002.md` 工单一律随批E；非此形态的不识不收。

## ⑤ 防吞口诀（照抄 CM 原单第四节，八批一体适用）

1. 只准 `git add -- <显式路径逐枚>`；禁 `-A`／`.`／`-u`／`commit -a`。
2. add 后 `git diff --cached --name-only`：枚数相等＋名字逐字一致，多一枚少一枚都停手。
3. `git diff --cached --stat` 对增删行数量级。
4. 裸 `git commit -F patches/CM-COMMIT-MSG-<批号>.txt`；禁 `-m` 内联、消息里禁反引号。
5. 提交后 `git show --stat HEAD` 核对；夹带 ⇒ `git reset --soft HEAD~1` 重来（用户执行）。
6. **每批动手前重跑 `git status --porcelain`**：别席在飞三度实证（95→97→102→120→121），新 ?? 先对照本单④归类，不识的不收。

---
席 CMV2 落款：2026-10-02T10:23:27Z 拍树；零 git 写／零进程动作／零配置改／未派子代理；唯一写面＝本工单。
