# patch-02 —— manifest 侧增量（仓外① 自述 `depends`：由②投影，工厂不另起第二把尺）

**落点文件（现位）**：`.superpowers/sdd/2026-09-24-central-dispatch/probes/s0-main-lib-factory.py`
（主代理席写面——**本席只出文本不落码**；行号会漂，按内容锚施工）
**内容锚**：库实体装配段内、以 `manifest = {` 起手的字面 dict（开窗时现算位于 :430–:446，
键面 `"@schema": "chatbot.workspace-lib-manifest/1"` … `"planned_tag"` … `"authority_note"`）。

## 派生链（唯一方向，禁回头抄）

```
真身三面（策略/例外/豁免，patch-01）
  → 生成器 workspace_manifest_sync（AST 现算边集 ＋ 策略求值 → ②cross_library_edges 逐行带区间）
    → 库工厂（读②中 consumer==本库 的行 → ① 的 "depends"）
```

工厂**不自己数 AST**——它拿②现成行投影。两把验证尺（门 vs 生成器）在 patch-03 讲；
这里是第三条**搬运**腿，零派生逻辑，防「三处各算一遍各错各的」。

## 可粘贴块一：装配段前，读②（fail-closed）

```python
    # S764 适配轴：①的 depends 自②投影。②不在＝FATAL——缺省成"空依赖"＝把「没账」读成
    # 「没依赖」，正是 S744 判罪的那类假零；同批未落地前宁可不跑这一 pass。
    ledger_path = repo / "docs" / "workspace-manifest.json"
    if not ledger_path.is_file():
        print("FATAL: ②指回账不存在（docs/workspace-manifest.json）——depends 投影拒绝以空表代打",
              file=sys.stderr)
        return 2
    ledger_data = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger_edges = ledger_data.get("cross_library_edges")
    if ledger_edges is None:
        print("FATAL: ②无 cross_library_edges 键（生成器未适配或未随批）", file=sys.stderr)
        return 2
```

## 可粘贴块二：`manifest = {` dict 内加一键（并把 schema 升 `/2`）

```python
        manifest = {
            "@schema": "chatbot.workspace-lib-manifest/2",     # /1→/2：新增 depends 键（白名单式 schema）
            ...（其余键原样）...
            # 本库对姊妹库的版本区间自述：consumer==本 slug 的全部 import-ast 行。
            # 零依赖＝合法空列表（形状与"没账"由 schema 代区分：②缺席根本到不了这里）。
            "depends": sorted(
                ({"provider": r["provider"],
                  "requires_min": r["requires_min"],
                  "requires_max_exclusive": r["requires_max_exclusive"]}
                 for r in ledger_edges
                 if r.get("kind") == "import-ast" and r.get("consumer") == slug),
                key=lambda e: e["provider"]),
        }
```

`authority_note` 同批改口（②与对账门未落地前那句作废；落地后改为）：
「①＝本库版本权威与依赖自述（发布期随库改）；`depends` 列＝②指回账的投影，手改＝门红
（`ADAPT-PROJ-*` 两腿）；主仓仍是代码真身。」

## 同批跟随清单（本增量单独进＝必红，逐条点名）

| # | 跟随面 | 为什么同批 | 今值证据（本席现算） |
|---|---|---|---|
| F1 | patch-01 真身三面 ＋ 生成器填 `cross_library_edges` 逐行区间 ＋ ②投影件 | 工厂读②，②无人写＝FATAL 常驻 | ② `docs/workspace-manifest.json` 现算 ABSENT |
| F2 | patch-03 门腿并进 `tests/test_workspace_manifest_gate.py` | ①写了没人对账＝在册未执法 | 该门件现算 ABSENT（三件套整体候选态） |
| F3 | ① schema `/2` 的消费方面 | 现算全树 `workspace-lib-manifest/1` 字面**只在工厂一处写**（grep 十件读方无一硬比对 `@schema`，s744 只比 api-surface 的 schema）——但治理尺若日后加 schema 等值腿，须按 `/2` 写 | 本席 `grep -rln "workspace-lib-manifest" probes/` 十一件逐一查读法 |
| F4 | 跑序钉死：**工厂(建/刷①版本面) → sync(②) → 工厂(depends pass)** 或 sync 先行复用盘上① | ①↔②互为读方，无环的唯一解是**分两 pass**；写进库面 README（S757）与命令册（S755） | 本席 §〇 环账：52 对单一巨型强连通——**声明面成环不构成执行环**（读序两 pass 即断） |
| F5 | `probes/s744-adaptation-matrix.py` 的 pair 归因腿跟进（只报不改） | 其 P2 命中记账键为 `"{bid}->?:{k}"`，而 pinned 查找式认 `"{c}->{p}"` 与 `"?:->{slug}"` ⇒ ① `depends` 落地后 **verdict 会翻离 `NO_DECLARATION_CHANNEL_ON_DISK`，但 52 对逐对仍判不出"已钉"**（半瞎）| 本席读其 :399–:403 三行原文坐实；该件写面属 S744，本席不动，**归因由 patch-03 门腿承担权威位**，S744 保持通道普查位 |

## 禁项（写死，防施工走样）

- 禁在工厂内自算 AST 边集（第二把派生尺）；禁把 `depends` 做成手填。
- 禁「②缺席时打 `"depends": []` 继续跑」——fail-closed 是判据的一部分。
- 禁把十库 `pyproject.toml` 的 `[project].dependencies` 当本通道的替身（那是 pip 面，
  属报告 §二 丙案，另一条账）。
