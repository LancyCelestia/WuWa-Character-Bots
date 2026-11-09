# HANDOFF-STRAY-DIRS-20261007 — MyWorkspace 下两枚错位目录：取证完毕 + 修复待执行交接

> **本文件是什么**：2026-10-07 用户发现 `Documents\MyWorkspace\` 下两枚目录在工作区外，命查「是什么 / 为啥在外 / 修复」。本席完成 systematic-debugging Phase-1/2（根因调查与定性），**零仓库改动、零删除、零移动**；用户中途令「停止工作，准备交接」。本文件＝唯一交接账。**接手 AI 先读根 `AGENTS.md`**，本文件只记本案。
>
> **权威链**：项目规则/台账以 `AGENTS.md` 为准；波次全账以 `docs/HANDBOOK.md` 为准；本案上游前置档＝`HANDOFF-RESCUE-20260930.md`（§12）。

---

## 一、结论速览（30 秒版）

1. **`MyWorkspace\ChatBot_Runtime\`（错位壳）不是运行时根**。真身＝`MyWorkspace\ChatBot\ChatBot_Runtime\`（`.env:11` 绝对路径钉死，data/ 10-07 仍在活跃写入）。错位壳里**只有** `cache\mypy\`（10-06 00:22，≈40MB mypy 缓存）与 `cache\seat-debt\`（10-04 01:18–01:50，某席位的词位债务核查断点草稿），无 data/无 venv 无任何库。**根因＝AI 席位手跑工具时把「仓外缓存位」相对深度多算一层 `..`**（从仓库根 `MyWorkspace\ChatBot\ChatBot` 跳到 `MyWorkspace` 而不是 `MyWorkspace\ChatBot\`）；10-04 与 10-06 两次独立踩中 ⇒ 操作纪律坑，**不是 dev.ps1 工具 bug**（`dev.ps1:64-65` 的 RuntimeRoot 推导正确，verified）。
2. **`MyWorkspace\_rescue_ChatBot_20260930\`＝0930 抢救波交卷物**（`bot-gates\` 四道门跑测证据 + `bot-head-ref\` HEAD 正文快照），是前席**有意**从易失 `%TEMP%` 搬出的「仓外永久位」，不是事故。处置悬案＝`HANDOFF-RESCUE-20260930.md` §12.7.10：「要不要按规则 9 正式进 `ChatBot_Archive\2026-09-30\`（压缩→testzip→manifest）？」——用户今日「帮我修复」即等于点头，**待下一席执行**。
3. **bot 在跑**（PID 10072 占 8080 LISTENING，2026-10-07 实测）；两枚目录与活进程无关（最后写入分别为 10-06 00:22 / 09-30 18:14），处置**无需动任何进程**。

---

## 二、证据账（全部 verified 实测 @2026-10-07，置信度标注）

| # | 事实 | 证据 |
|---|---|---|
| E1 | 运行时根真身 | `.env:11`＝`BOT_RUNTIME_DATA_DIR=C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/data`（绝对路径；该行非密钥可读）；`.env.example:15` 缺省 `../ChatBot_Runtime/data`（相对 PROJECT_ROOT，`scripts/runtime_paths.py:32` `PROJECT_ROOT=parents[1]`） |
| E2 | 错位壳内容仅两件 | `ls -laR` 实测：`cache\mypy\3.12\`（16 枚 `cache.*.db`，mtime 10-06 00:22）＋ `cache\seat-debt\`（`NOTES.md`、`driver1-7.py`、`drift.json`、`states.json`、`tree/`、`probe*.txt`、`added.tsv`、`attrib.txt`、`_gatefile.diff`，mtime 10-04 01:18–01:50）。壳顶层再无他物 |
| E3 | 真身健在且活跃 | `MyWorkspace\ChatBot\ChatBot_Runtime\` 全须全尾（venv/backups/cache/config/data/git/logs/pycache/scripts/…）；`data/` mtime 10-07 23:35、`cache/` mtime 10-06 17:46（＝dev.ps1 正常写真身侧的旁证） |
| E4 | 工具缓存位定义 | `scripts/dev.ps1:165-166`：`ruffCache`/`mypyCache` 均 `Join-Path $RuntimeRoot "cache\..."`；`scripts/chatbot-tasks.json:160-162` typecheck 步带 `--cache-dir {mypyCache}` |
| E5 | dev.ps1 RuntimeRoot 推导**正确** | `dev.ps1:64-65`：`$Root = Resolve-Path (Join-Path $PSScriptRoot "..")`（=仓库根）；`$RuntimeRoot = Join-Path (Split-Path -Parent $Root) "ChatBot_Runtime"`（=`MyWorkspace\ChatBot\ChatBot_Runtime`）。⇒ 走 dev.ps1 的缓存**不可能**落到 MyWorkspace 层；stray 里的 mypy 缓存必是**绕开 dev.ps1 手跑且 `--cache-dir` 深度写错**所致 |
| E6 | 仓内引用面 | grep 全仓（md/py/json/ps1）：`_rescue_ChatBot_20260930` 仅 `HANDOFF-RESCUE-20260930.md:221` 与 `:294` 两处；`seat-debt` **零命中**；stray 形态 `MyWorkspace\ChatBot_Runtime`（即 `..\..` 深度）**零命中** |
| E7 | seat-debt 性质 | `cache\seat-debt\NOTES.md` 首行自陈「Seat-debt checkpoint (NOT the deliverable; REPORT.md comes later in one Write)」＝某席 10-04 的词位债务/roster 计数核查断点（要点：全提交段账面恒 477、净新增 0；基线 ca2889d 本已红 489>467；转折笔 `e26c3709` +1 unit +13 roster；基线树 `831b02b5` 绿 467）。**正式 REPORT.md 不在其中**，是否已进 HANDBOOK 待下一席核对（§四步 3） |
| E8 | rescue 目录内容 | `bot-gates\`＝0930 四道门跑测证据（`full/`、`head-baseline.log/.xml`、`patches/`、`probes/`、`reports/`（含 `ADDENDUM-SECTION12.md`——`HANDOFF-RESCUE:221` 引的复跑说明就住这里）、`tools/`、`work/`、`bt-A2/`、a4/a8 探针件等）；`bot-head-ref\`＝HEAD 正文快照（含全套 HANDOFF 档）。体积见 E10 |
| E9 | bot 进程 | `netstat`：PID 10072 LISTENING 127.0.0.1:8080（2026-10-07 实测）＝生产 bot 在跑。两枚目录与其无关 |
| E10 | 体积（du 实测） | `MyWorkspace\ChatBot_Runtime`＝**110M**；`_rescue_ChatBot_20260930`＝**481M**（HANDOFF §12.7.10 的「98MB」只是交卷物部分，HEAD 正文快照占大头；当时值口径） |

---

## 三、根因定性（Phase 1/2 结论）

- **stray `MyWorkspace\ChatBot_Runtime`**：`MyWorkspace` 层目录树里，「仓外」的正确深度是**一层** `..`（仓库根的父目录＝`MyWorkspace\ChatBot\`，真身 Runtime 就在那）。两次（10-04 seat-debt、10-06 mypy）独立多跳一层落到 `MyWorkspace` ⇒ **席位操作纪律坑**：绕开 `dev.ps1` 手跑工具 + 仓外相对路径深度拍脑袋。无代码可修（E5 已排除工具 bug）；防复发走 §四步 5 的规则面。
- **rescue 目录**：非事故。前席按「别放易失 %TEMP%、也别进 git」定的仓外中转位，但按其自记（HANDOFF §12.7.10 第 10 条）**没走完规则 9 归档就停机了**，等用户裁定——即本次用户看到的「为啥放在工作区外面」的答案。

---

## 四、修复步骤（下一席按序执行）

> 纪律：全程零 git 写、零进程动作、不碰真身 `ChatBot\ChatBot_Runtime\`；每步先现算再动（台账 #52★）。

0. **补证**：du 两目录回填 E10；`ls -la` 快照真身顶层＋`data/` 文件计数（AC4 基线）；确认 bot 仍在跑（`netstat -ano | findstr :8080`）。
1. **rescue 归档**（规则 9 口径）：`_rescue_ChatBot_20260930\` 整目录压缩为 zip → `python -c "import zipfile; zipfile.ZipFile(...).testzip()"` ＋解压副本抽样比对 → 移入 `ChatBot_Archive\2026-09-30\`（该目录已存在，与 `container-loose-files\` 并列，勿覆盖）→ 写 manifest（来源/时刻/文件数/sha256）→ 验证通过后才删源目录。
2. **指针同步**：`HANDOFF-RESCUE-20260930.md:221` 与 `:294` 两处 `MyWorkspace\_rescue_ChatBot_20260930\` 改为新归档位（只改路径不动史实）；注意 `:221` 引的复跑说明 `ADDENDUM-SECTION12.md` 本体在 `bot-gates\reports\` 里（随包一起进归档），指针要写清「归档包内 `bot-gates\reports\ADDENDUM-SECTION12.md`」；同批 grep HANDBOOK 有无第三处引用，一并同步（文档-事实同步，规则禁臆造）。
3. **seat-debt 留证**：先 grep HANDBOOK/台账确认 E7 那份债务核查结论（477/489/`e26c3709` 一线）是否已有正式落账；无论有无，把 `seat-debt\` 整目录并入步骤 1 的 zip（或单独 zip 进 `ChatBot_Archive\2026-10-07\`）——**不裸删**（它是他席唯一在盘断点，NOTES.md 自陈 REPORT 未写）。
4. **删 stray 壳**：上述归档验证通过后，删 `MyWorkspace\ChatBot_Runtime\` 整目录（`mypy\` 本属可再生缓存；`seat-debt\` 已有归档副本）。删除前最后 `ls -laR` 一次核对无新增内容（防在飞席位又写入）。
5. **防复发（规则面，最小改动）**：在根 `AGENTS.md` 文件卫生节加一行操作纪律：「仓外缓存/草稿一律落 `ChatBot_Runtime\cache\`（真身，走 dev.ps1 的 ruffCache/mypyCache 键）或 `%TEMP%`；相对深度从仓库根**一层 `..` 封顶**，禁止 `..\..`」。注意 AGENTS.md 体积顶 30000/32768 机器门（台账 #62），加行前看余量，或改记 HANDBOOK。
6. **顺带登记不擅动**：`MyWorkspace\_c_probe.txt`（5 字节，09-29 23:50）疑似同族探针残留；另有 `MyWorkspace\pytest_tmp\`（09-28）疑似 pytest basetemp 残留——向用户点名待裁，未授权不删。

## 五、验收标准（AC，全部满足才算完）

- AC1 `MyWorkspace\ChatBot_Runtime` 与 `_rescue_ChatBot_20260930` 在盘零残留（`ls` 实证）。
- AC2 归档 zip testzip 通过＋抽样字节级一致（至少 `bot-gates/full.log` 与 `seat-debt/NOTES.md` 各抽 1 件），manifest 落归档目录。
- AC3 仓内 `grep -rn '_rescue_ChatBot_20260930'` 无断链引用（指针已全部指向新位置）。
- AC4 真身 `ChatBot\ChatBot_Runtime\` 动前快照与动后复核一致（未被误触）。
- AC5 全程零 git 写操作、零进程动作；bot（PID 8080）全程不受影响。

## 六、本席声明

- 本席**只做了只读取证**：未删、未移、未改任何仓库文件，未跑任何测试，零 git 写操作。
- 唯一新增＝本交接文档。置信度：§二 E1-E9＝verified（实跑命令＋盘面实测）；E10＝unknown（未回填）；§三根因＝verified（基于 E5 代码读数＋两日期独立踩点的组合推断，残余不确定＝「具体哪两个席位所写」无法回溯，不影响修复方案）。
