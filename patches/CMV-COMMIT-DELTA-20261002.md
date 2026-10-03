# CMV 工单 — CM 提交清单增量勘误（席 CMV · 2026-10-02 下午窗 · 只读核对席）

> 使命：把 `patches/CM-COMMIT-PLAN-20261002.md`（对 09:11:25Z/97 行快照负责）对到**当前树**，出增量勘误。
> 全程只读；读数＝`git status --porcelain`（v1）＋`git diff --stat`＋工单正文实读；未实跑任何测试（零进程动作）。
> 本勘误**不改 CM 原单**；用户按「CM 原单＋本勘误」合卷执行。

## ① 现树快照

- 拍时＝2026-10-02T09:35Z；HEAD＝`143098d`（`v0.0.1-alpha.3`，**CM 时刻后零新提交**，verified）。
- `git status --porcelain`＝**102 行**＝M 60＋?? 42。
- 对账：CM 快照 97 行＋5 枚新落 ??（AUD／CM-COMMIT-PLAN／DER／DRAFT-HANDBOOK-MERGE／PENDING-20261002b）＝102，**逐枚严丝合缝**（verified）。
- **消失面＝空**：CM 五批清单逐路径回查现 status，62 枚 CM 认领件无一失踪；CM 点名的 templates.py／.qoder/ 仍不存在。
- CM 时刻后主会话改的两件（diff 实读）：
  - `docs/auto-facts.md`：1 hunk，2+/2−（--write 重录 2 行）。
  - `tests/test_config_key_registration_ledger.py`：**2 hunk，+133/−1，不是"一枚常量行"**——hunk① 地板常量行替换（(784,1606,3,684)→(784,1612,3,688)，行内含主会话 2026-10-02 自主窗 1610/687 与续窗 CHK 抓漂 1612/688 两段现算复录前账）；hunk② **席 Z1「双向边界腿」追加块约 132 行**（`assert_floor_two_sided`，自称 2026-10-01、并发在飞件，严格只追加未动旧行）。⚠ 该文件当前 diff＝**混两席**（主会话地板行＋Z1 追加腿），见③。

## ② 勘误表（批号/动作/文件/理由）

| 批 | 动作 | 文件 | 理由 |
|---|---|---|---|
| B | **补入 +1**（6→7 枚） | `patches/IVF-INTIMATE-BLAST-RADIUS-20261002.md` | **CM 遗漏**：CM 批B 注记亲引「tts.py 混两席（IVF 工单实锤）」，取证名单也含 IVF，但五批文件清单均未收；不补＝B1 半边的证据工单落单 |
| E | **补入 +6**（9→15 枚） | `patches/L2-PRODLINT-20261002.md` | **CM 遗漏**：capability_protocols(RUF100)／nonebot(RUF023)／db-owners(PIE810) 三处 lint hunk 出处工单，CM 引其 hunk 却没收其单 |
| E | **补入 +5** | `patches/CM-COMMIT-PLAN-20261002.md`、`AUD-TICKET-RECON-20261002.md`、`PENDING-DECISIONS-20261002b.md`、`DER-DERIVED-LEDGER-20261002.md`、`DRAFT-HANDBOOK-MERGE-20261002.md` | CM 快照后新落 ?? 工单族；正文实读全为只读席/汇编席工单，唯一写面＝工单自身，已收卷。注：DRAFT 正文落点＝HANDBOOK §73（主会话并账时用），工单本身可先行入库；PEND 单点名 13 工单含 IVF/L2，反证②两枚确系遗漏 |
| 暂缓→**批F** | **移出暂缓** | `tests/test_config_key_registration_ledger.py` | 归属变化：CM 列「文档完整性族暂缓（别席在飞）」；现主会话已改地板行 → 转 F（见③；⚠ diff 含 Z1 腿） |
| 禁入→**批G** | **解禁** | `docs/auto-facts.md` | 归属变化：CM 禁入理由「生成物，随主会话收口」——主会话已收口（--write 重录 2 行），前提消失，见③ |
| — | 无动作 | 批A/批C/批D | 全部 38 枚在树无变化，勘误为零；批D 剔除 nonebot.py、批C 枚数 23 均维持 |

总账：五批 52 → **62 枚**（A3＋B7＋C23＋D12＋E15＋F1＋G1）；禁入余 8（auto-facts 移出后）；暂缓余 30。102＝62＋8＋30，账平（verified）。

## ③ 批F／批G 建议

**批F 地板复录批（1 枚）**：`tests/test_config_key_registration_ledger.py` 整文件。
- 动机：主会话续窗现算复录地板（1610→1612／687→688；地板升＝尺更利非放宽），独立成批不与任何功能批捆。
- 🔴 正文不能只写"一枚常量行"：diff 实测 2 hunk——① 地板行（主会话 2026-10-02，含 INT 两枚读点＋DBT 新测试件的差数点名）；② **席 Z1 `assert_floor_two_sided` 双向边界腿追加块（约 132 行）**。建议正文两席并写、检查点 `git show --stat HEAD` ＝1 枚 +133/−1。
- 收前由用户确认：Z1 是否已收笔（该块自称"并发在飞件"）；若 Z1 未收笔且不想带它走，本批须等——同文件 hunk 级拆分踩 #70★ 部分暂存 hunk 漂移坑，**不建议拆**。

**批G 生成册批（1 枚）**：`docs/auto-facts.md` 整文件。
- 依据 HANDOFF R6 先例「别席收笔后一次性重录入库」：生成者（主会话 --write）已收笔，现为干净单 hunk 2+/2−。
- 建议**单独成批不并入 E**：机器册（规则 10）与叙述文档/工单性质不同，且其余生成物（command-catalog、render_hashes×2）仍禁入未收口——单列 G 免得"生成物"身份在 E 批里被稀释。若用户嫌碎可并 E（E 变 16 枚），两案任裁。

## ④ 在飞未收卷件清单（一律「待收卷后再入批」）

- **TRG／M17 两席工单**：受命点名，**盘上尚无**（`patches/` 实查 09:35Z 无 TRG-*／M17-*）；落盘后按工单族补批E。
- 禁入在飞面：`echo.py`（P3A 点名别席持有）＋`tests/test_trigger_word_single_source.py`（echo 族）；`meme_library.py`（台账 #72 WT-only）。
- 批F 内嵌：席 Z1 追加腿是否收笔待确认（见③）。
- 待用户裁：`.zcodeignore`（来历未明）；`personas/shorekeeper/imagery_families.txt`＋`test_reply_style_imagery_default.py`（规则 8 灵魂资产，CM 建议用户单独裁一批——维持）。
- 暂缓 30 件维持 CM 原判（#66 三件、V1 余部、日程族、media_archive、文档完整性族余部、X2 双锁对、F3 邮件对、10 枚未认领 M 测试）。

## ⑤ 防吞口诀重申（照抄 CM 原单第四节，批 F/G 同样适用）

1. 只准 `git add -- <显式路径逐枚>`；禁 `-A`／`.`／`-u`／`commit -a`。
2. add 后 `git diff --cached --name-only`：枚数相等＋名字逐字一致，多一枚少一枚都停手。
3. `git diff --cached --stat` 对增删行数量级（批F 预估 +133/−1；批G 预估 +2/−2）。
4. 裸 `git commit -F patches/CM-COMMIT-MSG-<批号>.txt`；禁 `-m` 内联、消息里禁反引号。
5. 提交后 `git show --stat HEAD` 核对；夹带 ⇒ `git reset --soft HEAD~1` 重来。
6. **每批动手前重跑 `git status --porcelain`**：TRG/M17 等在飞席仍在写盘（97→102 实证），新 ?? 先对照本单②③归类，不识的不收。

---
席 CMV 落款：2026-10-02T09:35Z 拍树；零 git 写／零进程动作（status/diff/head 只读）／零配置改／未派子代理；唯一写面＝本工单。
