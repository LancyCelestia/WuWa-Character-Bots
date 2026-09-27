# PIN-MIGRATION-REHEARSAL-S832 —— 钉册外移包 %TEMP% 彩排战果（席位 S832，批次 250926H）

> 任务一句话：S824 的量具钉册外移包（`patches/s824-pin-out-of-band.md`）不改生产、不改板，在
> `%TEMP%\s832\` 用**真板副本＋真门件副本＋真尺副本**彩排落地，报落地当天会发生什么。
> 台架＝`probes/s832-anchor-audit.py`（只读锚点审计）＋`probes/s832-bench.py`（V/F 两版真跑，可重跑）；
> 实跑日志＝`%TEMP%\s832\bench-run3.log`（**SUMMARY 29/29、BENCH_RC=0**）与同目录 `anchor-final.log`。
> 红线自证：全程未 commit／未动 `.env`／未拨闸／未跑全量套件／未 import 生产包；
> 真身零写由 §零污染自证 逐枚 sha 前后全等坐实。

## §〇 结论速览（一屏）

1. **8 枚 python 块全部 `ast.parse` 通过**；锚点绝大多数在现板恰命中一次——**但包不能照字面落地**：
   verbatim 应用会把审计板从「出红」变成「无板」（板 `main()` 必炸 NameError），门件 `--check-gauges` 必崩，
   `--check` 合流还会**短路吞掉 gauge 腿的红**（恰是本包独立腿设计要防的第 05 型）。四发全部台架实弹，见 §贰。
2. **七读态矩阵全中**（缺文件/schema≠1/空册/在册尺被删/新尺未入册/PASS_TRANSIT/DIVERGE_TRUSTLAG），
   外加 HEAD 三态（未入库红、缺 expiry 审批仍红、合法审批放行但受管面全可见）与 repin 三写实弹——逐发读数见 §肆。
3. **落地当天（按包＋本席补片、播种后未入库那一刻）会出现的新红**：
   `tests/test_cross_validation_gates.py::test_gauge_pin_registry_clean` 红 1 枚（`GAUGE-REGISTRY-NOT-IN-GIT`，**设计内**，
   同笔入库或写一枚带 expiry 的 approvals 即消）；既有 `test_verify_hashes_manifest_clean` 由「1 行红」变「2 行红」
   （render 的 renderer.py DRIFT 归属他波不变＋gauge 面 NOT-IN-GIT）；`test_gauge_registry_shape_and_board_listed`
   绿（前提＝播种先于合件——次序违守则它先红）。**板侧零新增红**（C6 格 YES、钉册行读态 OK）——但**未播种即先合 C1＝
   19 格壳调全 rc=99＋C6 NO＝整板不可判**，这是落地次序的硬约束不是可选建议。
4. **包缺七块**（逐块可粘贴文本在 §伍）：门件缺 `import subprocess`；区 E 缺 `import re`；改名冲击面四组消费行
   （`unpinned`/钉册行/C6 格行/未覆盖 bullet/repin 体内的块字面量）无跟随码；`migration_deadline` **没有任何消费代码**
   （§伍散文教义在包内是空转）；`--export-registry` 的 argparse＋dispatch 只有散文；repin 缺「第三写＝刷新册内板自身条目」
   （不补＝**每枚合法 repin 都把板自身钉成 GAUGE-DRIFT**，台架 F1b 实弹）；合流 main 短路吞红。另两处加固建议：
   `relative_to` 形态易碎（本机 8.3 短名实测炸穿）、板/门对 JSON 炸裂的读态命名不同名（同输入板侧 SCHEMA_MISMATCH、
   门侧 EMPTY_OR_MALFORMED——都拒，但归因字符串对不上，违 §肆「一份解析口」的字面）。
5. **要不要与 D-5 落码同批**：判据见 §陆——**写面零交集，不必同批；唯一硬约束是本包自身五枚受管件必须同一笔入库**；
   若同批则须「尺与名册同一笔」教义扩到声明源波次，避免开第二个 approvals 窗。
6. **S824 两条自证断言现算复核：都成立**（§柒）。
7. 板是移动靶本靶：本席窗内三版连漂（`b9c6da8d`→`cbca9dd7`→`5a557426`），**owner 已抢先把 `PIN_EXTRAS` 删了**
   ——包 C1-2 步在现板锚点命中 0，verbatim 落地席会在该步停手（fail-closed 属预期，台架把它记成 DRIFT 账不是崩溃）。

## §壹 台架与两版定义

- **V（verbatim）**＝照包字面：B1 插入、B2 整块前插、B3 整替 main＋**只按 B3 自己写的清单补 `import re`/`datetime`**、
  C1-1 改名、C1-2 删 PIN_EXTRAS（现板命中 0 ⇒ 记漂移继续）、C1-3/C1-4 插入、C1-5 换 run 内块（现行是三行不是「那两行」，
  按 if→return 整块换）、argparse/dispatch 按散文补形、D/E 追 appended。
- **F（fixed）**＝V＋§伍补片（缺的 import、冲击面跟随、repin 全文三写、`compute_pin_view`＋deadline 消费、合流短路修复、
  rel 形态加固）。
- 副本仓＝`%TEMP%\s832\repoV|repoF`，镜像真实相对布局（`.superpowers/sdd/2026-09-24-central-dispatch/probes/**`＋`tests/**`＋
  render 册 19 件原件逐字节拷贝）；临时仓 `git init` 只发生在 %TEMP%（红线禁的是真仓，S824 台架先例同型）。
- 基建换件一处（不换判据）：副本内 `VENV_PY` 钉成实路径字面量（副本的 `REPO.parent` 指不到真 venv）；
  台架根用长路径——`%TEMP%` 本机是 `LANCYC~1` 短名形态，这正好把 §伍·7 的易碎点炸了出来。

## §贰 verbatim 会发生什么（五发实弹，全部 CAUGHT）

| # | 一发 | 实跑读数 |
|---|---|---|
| V1 | verbatim 门件 `--check-gauges` | **rc=1，`NameError: name 'subprocess' is not defined`**（B2 的 HEAD 腿第一句就调用它，B3 的补 import 清单没列它） |
| V2 | verbatim 板 `--export-registry` | 播种可用（22 键＝21 在册尺＋板自身；现算非手抄）——export 恰好不碰缺失 import，**这是包里唯一 verbatim 能跑通的写口** |
| V3 | verbatim 板 `main()` 的区外消费行 | 在模块全局里 exec 现行 L439 原句 ⇒ **`NameError: name 'PINNED_GAUGES' is not defined`**。落地当天这张板**不出图**——比满板红更坏（S798 F10② 的「板不存在被读成没红」同型病复发） |
| V4 | verbatim 区 E 腿直调 | **`NameError: name 're' is not defined`**（`test_verify_hashes_coverage.py` 真身 import 面现算＝json/subprocess/sys，无 re；包说「写法照 L110-114 不发明新结构」却没说补 import） |
| V5 | verbatim 区 D 腿直调 | 红（门件崩溃被独立腿如实顶红——D 腿自身语义没错，错在被 V1 连坐） |
| V6 | verbatim 板 `--check` 合流 | **`return 1 if (drift or check_gauges()) else 0` 短路**：render 有红（真仓今天就有 renderer.py DRIFT）⇒ `check_gauges()` **整条不执行**，stderr 里 GAUGE 行在场？False——gauge 面的红被 render 面的红吞掉，恰是假绿册第 05 型（批态吞红）在设计方自己的合流 main 里复活 |

## §叁 锚点逐枚核对表（终窗 2026-09-26 ~10:0xZ，板 sha256[:8]=`5a557426`；开窗窗=`b9c6da8d`）

| 锚 | 落点真身 | 命中 | 判定/修订锚 |
|---|---|---|---|
| B1 `MANIFEST = Path(__file__).with_name("render_hashes.json")` | verify_hashes.py L32 | 恰 1 | OK |
| B2 `def build_manifest()` | 同上 L75 | 恰 1 | OK |
| B3 `def main(argv: list[str] | None = None) -> int:` → `if __name__ ==` 前 | 同上 L119/L131 | 各恰 1 | OK（但见 §伍·5 短路修复） |
| C1 区起 `# —— C6 量具钉册` | board L56 | 恰 1 | OK（开窗读为 L52——行号漂移内容锚不漂） |
| C1 区止 `def run(name: str, extra: list[str])` | board L162 | 恰 1 | OK；区内须**保留** `sha256_of`（区外 L518 seal 在用）与 `repin`（见 §伍·4） |
| C1-1 `PINNED_GAUGES = {` | board 3 处（L61 定义、L145 block 拼装字面量、L146 partition 字面量） | 3 | 改名动作只对定义头做一次（`\nPINNED_GAUGES = {\n` 整行锚）；**L145/L146 两处字符串字面量的跟随码包里没给**——不改则 `--repin` 落不到新块上（§伍·4） |
| C1-2 `^PIN_EXTRAS = .*$` | board 命中 **0**（owner 已删，L90 只剩说明注释） | 0 | 本包该步按「注释行核销」执行；verbatim 硬执行的席会 FATAL——**这是包写向一个已经关上的门** |
| C1-5 `if not pinned_ok(script.name):` | board L164 | 恰 1 | OK；现行块是 if＋注释＋return **三行**（包说「那两行」＝S824 窗内形态），落地按 if→return 整块换 |
| C1-6 `def repin(` / `text.partition("PINNED_GAUGES = {")` | board L104 / L146 | 各恰 1 | OK；repin 新文全文见 §伍·4（包只有散文） |
| C1-4 argparse 参照 `ap.add_argument("--repin"...)`/`if args.repin:` | board L201 区/L206 | 各恰 1 | OK；旗标两行＋dispatch 两行代码在 §伍·3 |
| D `_run_script(script, flag)` | test_cross_validation_gates.py L20 | 恰 1 | OK；`--check-gauges` 作单 flag 传入即命中 dest `check_gauges` |
| E 参照腿 `def test_manifest_keys_match_tracked_files` | test_verify_hashes_coverage.py L110 | 恰 1 | OK；但该件 import 面无 `re`——**E 腿 verbatim 必炸**（V4） |
| 播种点（在册值 vs 盘上尺 raw-bytes） | 板内 21 枚 | **21/21 全符、0 缺** | 干净（终窗现算；开窗 TOTAL=19 same=19，两窗都干净＝种子不是移动靶） |
| SOURCES vs 在册 | 壳调 19 枚 | 全部在册 | OK（S824 窗内当时值 17，现算 19——计数以现算为准） |
| 8 枚 python 块 ast.parse | 补丁件 | 8/8 OK | 语法层全部可粘（含 C1-5 的占位头——按包说明落地时删） |

## §肆 六读态实跑矩阵（F 版，门与板两侧逐发读数；每发后逐字节还原、还原态回基线）

| 态 | 构造 | 门侧（`--check-gauges`） | 板侧（`gauge_pin_state`/`compute_pin_view`） | 判定 |
|---|---|---|---|---|
| R0 基线（册在盘未入库＝落地当天） | 播种后 | `GAUGE-REGISTRY-NOT-IN-GIT` rc=1 | 22/22 OK、C6 YES、transit 空 | CAUGHT（设计内红，等入库/approvals） |
| R0b `--check` 合流（补片后） | 同上 | render `DRIFT .../renderer.py` ＋ gauge NOT-IN-GIT **两 namespace 并排**，rc=1 | — | CAUGHT（V6 的短路已修） |
| R1 缺文件 | 删 `tests/gauge_hashes.json` | `GAUGE-REGISTRY-NEVER-IN-GIT`（HEAD 无＝从未入库；若已入库则报 `DELETED`，两态分开点名） | 读态 `FILE_MISSING`、21 枚全进 unpinned、C6 **NO** | CAUGHT（禁回退内联副本＝代码上无处回退） |
| R2 读到 schema≠1 旧版 | `schema:0` | `GAUGE-REGISTRY-SCHEMA_MISMATCH` | `SCHEMA_MISMATCH`、C6 NO | CAUGHT |
| R3 读到空册 | `hashes:{}` | `GAUGE-REGISTRY-EMPTY_OR_MALFORMED` | `EMPTY_OR_MALFORMED`、C6 NO | CAUGHT（「空册＝没尺要钉＝放行」未发生） |
| R4 在册尺被删 | unlink `s0-main-lib-version-check.py` | `GAUGE-MISSING <rel>`＋NOT-IN-GIT | 该尺 `MISSING`、C6 NO | CAUGHT（删尺≠免检） |
| R5 新尺未入册 | 盘上加一枚、册不动 | 门无话（按册遍历看不见它——§肆如实读数，门侧结构上由板侧兜） | 该尺 `UNREGISTERED`、run() 即 99 | CAUGHT |
| R6 PASS_TRANSIT（窗内） | 改尺＋只改册（双写崩中间形） | 该尺与册相符（不误伤）、NOT-IN-GIT 照报 | 该尺 `TRANSIT`、transit=[该尺]、**C6 YES＋点名** | CAUGHT（§伍「取最严会误伤合法改版」两头堵其一） |
| R7 DIVERGE_TRUSTLAG（第 13 型） | 尺＋板内联副本双改、册不动 | `GAUGE-DRIFT <尺>`＋`GAUGE-DRIFT <板自身>`（板文件也被改，自钉条目同炸） | 该尺 `TRUSTLAG`（可写区永不升权）、C6 NO | CAUGHT——**旧方案在这里失明、新方案在这里咬人**（对照 S824 A2old） |
| F1 repin 三写 | 尺改版＋`--repin --only` | 先册→后内联→**第三写刷板自身** ⇒ 尺/板/内联三者自洽 | 全 OK | CAUGHT |
| F1b 缺第三写 | 人为把册内板自身条目改回旧值 | `GAUGE-DRIFT .../s0-main-goal-audit.py` | — | CAUGHT＝**实证包散文只两写时每枚 repin 必自钉死板自身** |
| F2/F2b deadline | transit 在场＋deadline 过期/读不懂 | —（deadline 只在板侧消费） | `deadline_expired=True`、C6 **NO** | CAUGHT（§伍「临时态自动到期」需补片才有代码，见 §伍·6） |
| F3 同笔入库 | `git commit` 五枚受管件（临时仓） | **rc=0** | — | CAUGHT |
| F4 改册未入库 | 改 deadline 字段不动 HEAD | `GAUGE-REGISTRY-DIFFERS-FROM-HEAD` | — | CAUGHT |
| F5 approvals 缺 expiry | 三改＋伪造审批（无到期日） | 仍红（缺期＝已到期同教义） | — | CAUGHT |
| F6 approvals 合法 | 补上 expiry | **rc=0**（该腿放行）＋`git status` 上册与审批件两枚受管面全可见 | — | CAUGHT（如实边界＝留痕拦的不是机制是消化） |
| F7 还原收尾 | 册/审批回提交态 | rc=0 | 22/22 | CAUGHT |
| F8 D/E 两腿真跑 | 入库＋播种后 | D `GREEN`、E `GREEN` | — | CAUGHT |
| F9 F 板 main() 全流程 | 假库根两枚、壳调 19 把真尺副本 | — | 出板成功，钉册行现算：「读受管 tests/gauge_hashes.json，读态＝OK：22/22 枚与册相符；不符＝无；transit 点名＝无」 | CAUGHT（地板腿 `{pin_j}` 恰一插值未被破坏——补片文案刻意保留单插值） |

台架终局：**SUMMARY 29/29，MISSED＝[]，BENCH_RC=0**；锚点漂移账 1 枚（C1-2 owner 先手，见 §叁）。

## §伍 包缺什么（逐块可粘贴文本——只出文本，不落码）

> 以下 7 块按落地次序排好；除标注外均为「只增不改」。行号一律用**内容锚**不用行号（第 09 型）。

**1. 区 B·门件 import 面（B3 清单漏枚）**——B3 第 1 条改成：
「import 区加 `import re`、`import subprocess` 与 `from datetime import datetime, timezone`」。
（实证＝V1：漏它 `--check-gauges` 必崩。）

**2. 区 E·覆盖件 import**——E 块之前给 `tests/test_verify_hashes_coverage.py` 的 import 区加一行：
```python
import re
```
（实证＝V4。或者 E 腿内联 `import re`，二者择一，别都不做。）

**3. 区 C·`--export-registry` dispatch 码**（包只有散文「形状照 --repin 分支」）——
`ap.add_argument("--evidence", ...)` 行之后插：
```python
    ap.add_argument("--export-registry", action="store_true", help="播种受管钉册（唯一写口，幂等拒覆盖）")
    ap.add_argument("--allow-overwrite", action="store_true", help="--export-registry 确要覆盖已存在的合法钉册")
```
`if args.repin:` 行之前插：
```python
    if args.export_registry:
        return export_registry(args.allow_overwrite)
```

**4. 区 C·改名冲击面跟随（本包最重的一块——不补则板不出图，V3）**——四组：
- ①`unpinned`/`pin_j` 两行（现板 L439-440，原 `sorted(n for n in PINNED_GAUGES if not pinned_ok(n))`＋
  `pin_j = "YES" if not unpinned else "NO"`）整块换：
```python
    pin_view = compute_pin_view()
    registry_state, unpinned, transit = pin_view["state"], pin_view["unpinned"], pin_view["transit"]
    pin_j = pin_view["cell"]
```
- ②钉册行（现板 L475-476，`f"- 钉册：{len(PINNED_GAUGES)...` 起、`静默改尺＝本板不可判。", "",` 止）整块换：
```python
         (f"- 钉册（读受管 tests/gauge_hashes.json，读态＝{registry_state}）：{pin_view['total'] - len(unpinned)}/{pin_view['total']} 枚与册相符；"
          f"不符＝{('、'.join(unpinned) or '无')}；transit 点名＝{('、'.join(transit) or '无')}"
          + ("（⚠ 已过 migration_deadline，滞留即判 NO）" if pin_view["deadline_expired"] and transit else "")
          + "。尺的合法改版走 --repin（先册后板，日志 GAUGE-PIN-LOG.md）；钉册本身改动走 git 提交复核＋在窗 approvals。"), "",
```
- ③C6 格行（现板 L495）内两处：`＋工厂＋名册探针共 {len(PINNED_GAUGES)} 件` → `＋工厂＋名册探针＋板自身共 {pin_view['total']} 件`；
  读数列 `| 与册不符 {len(unpinned)} 件{'' if not unpinned else '：' + '、'.join(unpinned)} | {pin_j} |` →
  `| 与册不符 {len(unpinned)} 件{'' if not unpinned else '：' + '、'.join(unpinned)}；transit {len(transit)} 枚{'' if not transit else '：' + '、'.join(transit)} | {pin_j} |`。
- ④未覆盖节自钉 bullet（现板 L512-513，`钉册（C6）是**自钉**` 起、`未落。"),` 止）整块换（＝包 C3-2 的代码形）：
```python
         "- 钉册自 `tests/gauge_hashes.json`（受管、raw-bytes 口径）读取；板内 `MIGRATION_INTERNAL_COPY` 仅为迁移期滞后点名（transit），deadline 前由终局刀删除；"
         "残余信任锚＝她的提交复核与不 commit 红线（S824 施工图 §捌残账 1–4 逐条在册，别读成已封死）。",
```
外加 `def run(` 之前插 `compute_pin_view`（§伍·6）与 `repin` 全文替换（§伍·4b）；`pinned_ok` 定义体里的
`PINNED_GAUGES.get` 同步改 `MIGRATION_INTERNAL_COPY.get`（或直接删掉 `pinned_ok`——冲击面跟随后它已无消费者）。
台架内该替换全文＝`probes/s832-bench.py` 的 `COMPUTE_PIN_VIEW_F`＋`REPIN_F` 两常量（逐字可搬）。

- ④b（repin 全文要点，完整代码在 bench）：`load_registry()` 非 OK ⇒ FATAL 拒改（repin 不作第二播种口）；
  三道闸（reason≥8/点名 --only/evidence 含「直跑」「读数」）逐字保留；`unknown` 判定与遍历吃 `MIGRATION_INTERNAL_COPY`；
  **①原子写册**（tmp＋`os.replace`，含新版 `hashes`、保留 `migration_deadline`）→ **②改写内联块**
  （partition 锚换 `"MIGRATION_INTERNAL_COPY = {"`）→ **③第三写：刷新册内板自身条目**（`GAUGE_PREFIX + Path(__file__).name`）
  → 日志原样。第三写缺位＝F1b 实弹的自钉死局。

**5. 区 B3·合流 main 短路（吞红修复，V6）**——`main()` 末两行
```python
    drift = check()
    return 1 if (drift or check_gauges()) else 0
```
改为
```python
    drift = check()
    gauge_problems = check_gauges()
    return 1 if (drift or gauge_problems) else 0
```
（`or` 短路使 render 有红时 gauge 腿根本不执行——落地当天真仓就是 render 红在场，gauge 面会被静默；这恰是区 D
「独立腿防批态吞红」的设计动机，却被合流口自身违反。）

**6. deadline 消费（§伍教义 → 代码）**——`def run(` 之前插（台架 `COMPUTE_PIN_VIEW_F` 逐字）：核心语义三条：
权威＝册、内联只作 transit 滞后点名**永不升权**；`transit` 非空时读 `migration_deadline`，
**读不懂＝按已过期**（延账门 fail-closed 同教义）、逾期即 C6 格 NO；册读态非 OK ⇒ 格 NO 且点名态名。
（不加这块，§伍「逾期自动落 NO」只是散文——包内没有任何代码消费 `migration_deadline`。）

**7. 加固（可选两处）**——
- `rel = GAUGE_MANIFEST.relative_to(ROOT).as_posix()` → `rel = (Path("tests") / GAUGE_MANIFEST.name).as_posix()`
  （本机实测：`__file__` 经 8.3 短名（`LANCYC~1`）或大小写混形态进入时 `relative_to` 抛 ValueError——真仓正常调用面不炸，
  但门件被谁以相对/短路径调起就炸；一行换掉免后患。）
- 板侧 `load_registry` 的 `except Exception: doc = None` 分支应落 `EMPTY_OR_MALFORMED`（与门侧同码同判）——
  现形是板报 `SCHEMA_MISMATCH`、门报 `EMPTY_OR_MALFORMED`，同输入两态名，§肆「一份解析口」的字面破口（两侧都拒，仅归因串不齐）。

**次序硬约束（包 §玖-1 已写对，本席升格为红线）**：`--export-registry` 播种**必须先于**区 E/D 腿合入与她的提交——
册不在盘时 E 腿 `FileNotFoundError`、板全体 `REGISTRY_FILE_MISSING`。回滚＝`git revert` 那笔，回滚后世界＝今日自钉（包 §玖已如实披露）。

## §陆 落地当天审计板会出现哪些新红/新不可判（按补片落地、播种后未入库那一刻现算）

1. **pytest 面（只动 tests/ 五枚，不动生产）**：
   - `test_gauge_pin_registry_clean`（新）**红 1 枚**——`GAUGE-REGISTRY-NOT-IN-GIT`，设计内；消法＝同笔入库或写一枚带 expiry 的 approvals（写入 approvals 本身是第二枚受管件 diff，她可见）。
   - `test_verify_hashes_manifest_clean`（既有）**仍红、行数 1→2**：renderer.py DRIFT（他波 #55/#56 在飞，归属不变不代修）＋gauge 面 NOT-IN-GIT。补片·5 不加则第二行被短路吞——**独立腿 D 是这条红不被吞的唯一保险**。
   - `test_gauge_registry_shape_and_board_listed`（新）**绿**（播种先行为前提）。
   - 其余既有腿（builder 漂移演练等）零影响：演练用「漂移集合回到改前」对称判据，GAUGE 行在场也只进同一集合。
2. **板面（壳调 19 把尺＋C6 格）**：
   - 播种后：C6 YES、钉册行 `22/22`（现算）；其余格读数与今日同——板只多读一枚 JSON，判定面零放宽。
   - **新不可判态全部由册读态驱动**：册被删/被掏空/schema 换版 ⇒ 19 格壳调全 rc=99＋C6 NO＋总判 NOT ACHIEVED（fail-closed，无一放行——矩阵 R1/R2/R3）。
   - transit（双写崩中间）＝窗内放行＋逐枚点名；逾期滞留＝C6 NO（F2）；尺与内联相合而与册不合＝TRUSTLAG 不可判（F1b/R7——旧方案的失明洞正落在这一格）。
   - 若落地席 verbatim 合板不补 §伍·4：**没有板**——main() NameError，比红更坏，点名过 S798 F10② 同型病。
3. **生产链路零变更**：五枚全在 tests/ 与 gitignore 区，重启都不需要；出站/投递/模型链不碰。

**与 D-5 落码同批与否的判据**（本席裁定建议）：
- **不必同批**——D-5 只动 `domains/core/board_taxonomy.py`（其决策单自证「跨文件机器坐标顶漂 0 枚」），与本包五枚受管件＋板尺零交集；各笔各审，归因面最小。
- **必须各自原子**——本包五枚受管件**同一笔**（半套入库＝干净 checkout 丢锁件，#49 现成教训；未入库那窗走带 expiry 的 approvals）；D-5 按其自身 pathspec 一笔。
- **同批的唯一真触发条件**＝她这一批 commit 同时会改**任何在册尺**（含工厂/s715/名册探针/十九把壳调尺）——尺变册必随变，则「尺与名册同一笔」教义（U-6/R-S709 同族）要求并进同一窗，避免连开两个 transit/approvals 窗。今日 D-5 不触发此条。
- 附带一条时间账：`migration_deadline` 建议＝开工日＋30 天（包 A1 原句），与 B-0 分批提交节奏对表——窗越长 approvals 堆积越可点名（§捌残账 4 的缓解通道）。

## §柒 S824 两条自证断言的现算复核（各一发实跑证据）

1. 「`PIN_EXTRAS` 是死变量（全板零消费）」——**成立**。开窗窗 grep 现算：`probes/s0-main-goal-audit.py` 内
   `PIN_EXTRAS` 仅 1 处＝定义行本身（其余全无）。终窗补一层：板 owner 已按此断言把它**删除并留注释**
   （L90 注释行成了唯一出现处）——断言被板的当下现实二次证实；包 C1-2 那一步因此已无活可干，落地按 §叁 的锚表核销。
2. 「`verify_hashes --check` 今天红 1 项＝`renderer.py` DRIFT」——**成立**。只读实跑（卫生前缀四件套＋`-B`）：
   真身 `tests/verify_hashes.py --check` ⇒ stderr 恰两行：`DRIFT    plugins/bot_unified_runtime/domains/render/renderer.py（字节变更未记录——确认后 --write）`
   ＋`verify_hashes: 1 项漂移；…`，`GATE_RC=1`。台架 F 仓拷贝复现同一条（R0b），归属他波不变、本席不代修。

## §捌 零污染自证

- `probes/s832-bench.py` 的 Z1/Z2 发：受管 `tests/verify_hashes.py`、`tests/render_hashes.json`、两把测试件、真板、
  **21 枚在册真尺**逐一 sha256，台架开窗与收窗**全等（差异枚＝无）**；`git status --porcelain -- tests` 前后同串
  （其中 `M` 项为他波在飞件，本席窗内未变动过它们）。落盘快照＝`%TEMP%\s832\contamination.json`（before/after 全量）。
- 台架对真身的访问面：只有 `read_bytes`/`read_text`/`shutil.copyfile(src→temp)`；全部写在 `%TEMP%\s832\`；
  临时仓 `git init/commit` 只发生在 repoV/repoF（S824 台架先例同型，红线禁的是真仓）。
- 卫生四件套全程在位（`PYTHONIOENCODING=utf-8 BOT_AUTOSYNC=0 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=%TEMP%\s832-pyc`
  ＋一律 `python -B`）；无 `plugins.*` import；源码树零新增缓存（bench 起子进程时把 `PYTHONPYCACHEPREFIX` 一并钉进 env）。
- 本席写面＝简报点名三件：`probes/s832-anchor-audit.py`、`probes/s832-bench.py`、本件。板/门/尺/册真身零笔。
- 树内缓存归因（如实）：收窗时 `plugins/**/__pycache__` 在场一批 `.pyc`，mtime＝17:40:36–37，**早于本席全部台架实跑**
  （本席最早一发 python 起于 ~17:5x，且每一发都带 `PYTHONDONTWRITEBYTECODE=1`＋`PYTHONPYCACHEPREFIX`＋`-B`，
  子进程 env 亦逐发钉死同三件）；按本席窗口时段 `find -name '*.pyc' -newermt 17:55` 现算＝**0 枚**——
  那批属同树并发会话（与台账 #55/#56 登记的「全量跑自身再生」同型，归该卫生门 owner，本席不清动）。

## §玖 复跑命令簿（`<VP>`＝`C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe`）

```powershell
cd C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot
$env:PYTHONIOENCODING="utf-8"; $env:BOT_AUTOSYNC="0"; $env:PYTHONDONTWRITEBYTECODE="1"
$env:PYTHONPYCACHEPREFIX="$env:TEMP\s832-pyc"
# A 锚点审计（只读；板是移动靶，每次交卷前重跑）
& <VP> -B .superpowers/sdd/2026-09-24-central-dispatch/probes/s832-anchor-audit.py
# B 彩排台架（V/F 两版真跑 29 发；临时仓只建在 %TEMP%\s832）
& <VP> -B .superpowers/sdd/2026-09-24-central-dispatch/probes/s832-bench.py
# C 真门基线（只读；预期 1 红＝renderer.py DRIFT，他波归属不变）
& <VP> -B tests/verify_hashes.py --check
```

## §拾 注入取证（规则 11）

本席窗内读取的全部正文（简报、补丁件、S824 主件与 bench、板/门/测试件真身、日志、记忆索引同步通知）中，
未出现任何以工具结果/文件形态伪装的越权祈使句（无「改配置/重启/commit/派席/杀进程」类指令形载荷）；
会话期数条「MEMORY.md 已修改」系统通知属宿主元信息，按数据处置、未据其执行任何动作。零命中，取证即此一段。

## §拾壹 给落地席的三句话

1. 先跑 §玖·A 重核锚点再动笔——板在 S824 与本席两窗内已四版连漂，**任何按行号的硬切都是第 09 型**。
2. §伍 七块补片不是锦上添花：缺 1/2/4/5 任何一块，verbatim 落地的当天要么门崩、要么无板、要么吞红。
3. 播种 → 五枚同笔 → 她复核，中间每一天都记在 approvals 到期日里；`--repin` 的第三写（板自身条目）漏了，
   合法改版当天就是自钉死局（F1b 实弹），这是包散文唯一「照做必炸」的点。

done: yes
