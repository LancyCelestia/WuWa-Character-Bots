# pins-channel —— 适配轴「库↔库版本区间」声明通道（从无到有的可落件包）

席位 S764（批次 250926A-4）｜ 全案叙述与判决在 `../PINS-CHANNEL-S764.md`
本目录只装**可粘贴增量与判据原文**，不落生产码、不动十库、未 commit。

## 文件地图

| 文件 | 是什么 | 落地时进哪儿 |
|---|---|---|
| `patch-01-declaration-side.md` | 仓内**声明源侧**增量：真身三面（区间策略／pair 例外／显式豁免）＋求值口 `expected_range` 唯一真身 | `plugins/bot_unified_runtime/domains/core/workspace_manifest.py`（三件套真身，加腿不建第二件） |
| `patch-02-manifest-side.md` | **manifest 侧**增量：仓外① `workspace-lib.manifest.json` 的 `depends` 键（由②投影，工厂不另起尺）＋ schema `/1→/2`＋同批跟随五件 | `probes/s0-main-lib-factory.py`（主代理席写面，本席只出文本） |
| `patch-03-gate-legs.py` | **机器门判据原文**（可执行规格，已 exec 实测）：守恒腿＋投影腿＋读点腿＋尺瞎自锁＋环账 | 并入 `tests/test_workspace_manifest_gate.py`（与 S727 L-11 同门加腿） |
| `rows-52.expected.md` | 52 对**期望投影行**（由尺现算，非手抄）：逐对回答「谁钉谁的哪个区间」 | 派生件，重生成即覆盖 |

## 三句要点

1. **唯一落点**＝既有 pins 真身（S594 设计、S612 实跑十条锁、S715 按 D-2甲 改形、S727 出可粘贴全文
   的 `workspace_manifest.py` 三件套）的 `cross_library_edges`——**不新建第二真身、不开第二通道**；
   仓外① 的 `depends` 与仓内② 的账行都是这条真身的投影，不是并列的另一本册。
2. **谁读它**：门禁期 `test_workspace_manifest_gate.py`（读②↔①↔AST 现算，执法）；
   治理期 `s744-adaptation-matrix` 的 P2 通道（今值 verdict 会翻离 `NO_DECLARATION_CHANNEL_ON_DISK`）
   与 `s0-main-lib-factory`（写①）。**运行期不读**（治理元数据，非装配期开关）——本席如实标此边界。
3. **两把反制腿都在**：①「声明了但没人读」＝`p_adapt_no_silent_fields`（L-11 同族派生尺）＋
   `ADAPT-RANGE-DIVERGE`／`OVERRIDE-NOWHY`（逐对堵「填了不看」）；②「删声明必同批守恒」＝
   `p_adapt_ledger_matches_ast` 双向差集 `ADAPT-MISS`／`ADAPT-STALE`＋三分恒等式（沿用 S744 三账与棘轮只降教训）。

## 复跑

```bash
cd /c/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot
export PYTHONIOENCODING=utf-8 BOT_AUTOSYNC=0 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX="$TEMP/s764-pyc"
PY=/c/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe
S=.superpowers/sdd/2026-09-24-central-dispatch
# 先复跑 S744 矩阵出 %TEMP%/s764-adaptation-matrix.json（命令见其报告 §陆），再：
"$PY" -B $S/probes/s764-requires-rows.py --out $S/pins-channel/rows-52.expected.md   # 期望投影行＋自身守恒
"$PY" -B $S/probes/s764-teeth.py                                                       # 门腿杀伤力，应 TEETH-OK 16/16
```

> **R7 迁面注（2026-09-27）**：本包受追踪真身＝`pins/2026-09-24-central-dispatch/pins-channel/`；
> `.superpowers` 同名目录为迁移前历史副本（保留不动）。消费读点（s764-teeth/s853/s869/s889）已改指本受追踪副本。
> 注：`s764-requires-rows.py` 自带 `--out` 护栏只准写 %TEMP% 或 .superpowers（禁写生产树），重新导出期望行仍落席目录——这是尺的既有自锁，不随迁放宽；
> 与受追踪副本比对即验等值。
