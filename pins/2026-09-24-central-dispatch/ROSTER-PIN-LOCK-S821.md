# ROSTER-PIN-LOCK-S821 — 断开度尺名册 pin ＋ 两尺互锁指纹（台账 #121，批次 250926A-B5）

席位 **S821**（写面 `probes/s821-*.py`＋`patches/s821-severance-roster-pin.md`＋本件）｜开窗 UTC 2026-09-26 08:4xZ｜交卷 09:1xZ
简报：`BRIEFS-250926-B.md` §一（十条纪律逐条遵守）＋ §〇（钉册与改尺证据纪律）；任务实跑出处＝`SEVERANCE-DENOMINATOR-S808.md` §1B/§2/§4；两把尺真身只读。
工作根 `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot`。

**一句话总账：给 `s759-severance.py` 补名册 pin（两轴派生座数≠实扫座数 ⇒ `FATAL: 断开度只覆盖板块轴 N/15 ⇒ 分母不可判`、rc=2、零裁决词）并给两把尺各装一枚 `roster_fp=` 互锁指纹——三态＋七案矩阵全实跑 ALL-PASS（rc=0），改前病症逐案复现（P3 静默 52→**59** 与 S808 当时值逐字吻合；A 案静默 52→7；B 案 52→45；H 案纹丝不动），改后每案两尺同报同 fp；真实十库读数在 pin 放行路径上逐字节不变（52/261/399/0）。patch 只出文本，尺件本体零写，五枚输入件 sha 开跑收跑双核对等值。**

## §0 证据头（本席现算）

- HEAD 现算 `a5226ec`（与 S808 窗同值）。真尺未被动过：开窗即核 `s759-severance.py` sha256[:16]＝`845373dcaf1438fd`＝钉册在册值；`board_taxonomy.py` 现算 `a76235f025024d69` 与 S808 窗逐字相等（声明源零漂移）。
- **改前 sha256（64 位）**：
  - `s759-severance.py`＝`845373dcaf1438fde2751645bddaea62dc68fcfcd97f9f49b3974c36e02f81a0`
  - `s759-decl-sources.py`＝`be8637db4f6badf60a663ccab8e87b5bc7972f70c43a71040aa114a56fa99c80`
  - 依赖件 `s0-main-lib-factory.py`＝`e952b091…db8467`、`s715-deps.py`＝`28724bed…77b278`、`board_taxonomy.py`＝`a76235f0…cbf1e2`（全值见 patches md 证据头）
- **改后 sha256（64 位，即应用 patch 后两尺应有的字节形态；`--emit-patched` 复产件实测同值，非推算）**：
  - `s759-severance.py`（改后）＝`5a0b78d822eee8301ccb27574800308a911f4c055d1f5fef87128c122085819b`
  - `s759-decl-sources.py`（改后）＝`f0bbeb9d7aa58662bd2998a768dde97f2798f04a878d95773c35c618d75cd9b0`
- 名册基线指纹（真实现算 15 座排序 slug 清单）`roster_fp=1cbc02d334a6`（本席独立重算与两把改后尺打印值三方一致）。
- 本席三件：`probes/s821-roster-pin.py`（40,434 B，sha256[:16]＝`102cc5cd7781678b`）、`patches/s821-severance-roster-pin.md`（13,759 B，程序化生成、再生成 `cmp` 逐字节稳定＝MD-STABLE 实测）、本件。
- 全程卫生：`PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONPYCACHEPREFIX=<%TEMP%\s821-pyc`＋`python -B`；注毒台全在 `%TEMP%\s821-roster-pin\`；**真尺／板件／声明源零写**（探针收尾 sha 复核腿＝0 FAIL，无需还原故无 cmp 面——本席全程只写真件之外；交卷扫描 60–70 分钟窗内树内新 `.pyc` 仅 1 枚＝`probes/__pycache__/s802-rehearsal.cpython-312.pyc`，系并发席 S802 在飞件（S808 §4 已点名同文件当时态），**非本席产物、按纪律只登记不清理**）。

## §1 三态实跑（每发都是子进程真跑，机读行为本席探针原样输出）

### ① 真实现算（今值，当时值 08:5xZ 复跑）

```
BOARD SEV numer=0 denom=52 stmt_edges=261 sym_edges=399 half=0 declared=0
VERDICT: NOT-SEVERED   (rc=0)
```

与简报给的今值（分母 52／语句边 261／符号边 399／分子 0）逐字相等，亦与 S808 08:18Z 窗逐值相等——两窗 taxonomy 与宇宙零漂移坐实（§0 sha）。

### ② taxonomy 扩册假根（S808 注毒 P3 形状：%TEMP% 副本把 5 座非板块库照 NONBOARD_ROOTS 原根做成板块，10+5 座）

- **改前复现（必中）**：真尺 rc=0、**无 FATAL 无任何警告、照出裁决词**、`denom=52→59` ——与 S808 当时值 **59 逐字吻合**（+10 点亮、−3 被 `adapter-qq` 根与 B08 `domains/transport/sender` 重叠的多主弃边规则吞掉，非单调坐实）；本尺且**根本不打印名册读数**（无 fp 可查＝失明无鉴别位）。
- **改后必杀**：`rc=2`、stderr＝`FATAL: 断开度只覆盖板块轴 15/20 ⇒ 分母不可判（在册库未全进认领宇宙，盲区改叫；补齐认领宇宙后本腿自动放行）`、stdout 仅一行 `roster_fp=d9c752ace0ff scanned=15 roster_n=20`、**零裁决词（SEVERED/PARTIAL/NOT-SEVERED 全 0 命中）零 BOARD SEV 行**；同输入改后 decl `rc=2` 且 fp 同值 `d9c752ace0ff`。

### ③ 只扩库轴的假根（%TEMP% 库根建满 15 座目录〔10 板块＋5 非板块，pyproject 齐〕、taxonomy 一字不动）

- **改前复现（必中）**：真尺 `denom` **纹丝不动＝52**、rc=0 照出 NOT-SEVERED——对 5 座新库继续瞎，即今日盘上形态的放大版。
- **改后必杀**：`rc=2`、`FATAL: 断开度只覆盖板块轴 10/15 ⇒ 分母不可判`、stdout 仅 `roster_fp=1cbc02d334a6 scanned=10 roster_n=15`、零裁决词。
- 附注（设计如实）：**真实现算本身**（真库根 10 座目录＋名册在册 15）就是这个形态——所以改后尺对今天真实现算即 FATAL。这是判据升级（盲区改叫），不是尺坏了；统筹板 grab 腿抓不到 `SEV` 机读行→该格落 NO，不新增崩溃面（§四跟随面）。

## §2 必交 1：名册 pin 补丁（文本已交，件＝`patches/s821-severance-roster-pin.md`）

- 给 `s759-severance.py` 四发 hunk（文档字符串自锁条／`import hashlib`／`load_module`＋`roster_fp` 助手／main() 内 pin 块），**锚点逐字节恰一处、各带前后 3 行上下文**；guard 放在派生之后、扫盘之前 ⇒ 拒判路径零文件扫描、裁决词打印代码结构性不可达。
- 派生口**全部复用** `s759-decl-sources.py` 同款三件：`fac.parse_taxonomy`（板块轴）＋ importlib 装载 `s715-deps.NONBOARD_ROOTS`（库轴名册侧）＋ `fac.parse_libs`（形状校验，违规即 FATAL）。全文**零手抄 slug 清单、零绝对座数**——三本账分工钉死：**绝对 15** 唯一住 `ROSTER_EXPECT`（decl 件），**覆盖等式**（实扫==名册派生）住新腿，**输入件完整性**住量具钉册（`s715-deps.py`/`s0-main-lib-factory.py` 在 PIN_EXTRAS）。未新建第三本名册账（本席 fp 重算腿是验证用一次性推导，不落常驻账）。
- 语义钉：pin 是**关系判定**——将来有人把 5 座补进认领宇宙（owner_of 吃库轴根，施工 ticket 已在注释与本件 §8 指路），scanned 变 15、腿自动放行，无需再改 pin。
- 落码通道（零手抄）：`python -B probes/s821-roster-pin.py --emit-patched <暂存目录>` 直产两枚改后件（本席实测其 sha 与登记值逐字符等）。

## §3 必交 2：同批互锁腿（两枚 `roster_fp=` ＋ 改名册反应矩阵）

指纹定义（两尺逐字同形）：`roster_fp = sha256("\n".join(sorted(slug 清单)))[:12]`；**fp 先行打印、再走各自拒判** ⇒ 拒判时互锁探针仍读得到「本尺看见的名册」；任一尺缺 fp 行＝按失明报红（探针判据，非散文）。

矩阵（全部 `%TEMP%` 注毒、两把**改后**尺同输入对跑；PRE 列＝改前真尺同输入病态对照）：

| 案 | 名册扰动 | 改前 sev | 改后 sev | 改后 decl | 两尺 fp（改后） | 判定 |
|---|---|---|---|---|---|---|
| T | 无（真实现算） | 52／NOT-SEVERED 无 fp | rc=2 FATAL 10/15 | rc=0 gap=5＋fp | 同＝基线 `1cbc02d334a6` | 盲区②今日态=叫 |
| C | tax P3（+5 重叠座） | **rc=0 静默 52→59** | rc=2 FATAL 15/20 | rc=2 (≠15) | 同值 `d9c752ace0ff` | ②复现＋同杀 |
| A | tax 板轴 +1（B99 吞 domains） | **rc=0 静默 52→7** | rc=2 FATAL 11/16 | rc=2 | 同值 `144483244a9a`≠基线 | 非单调坐实＋同杀 |
| B | tax 板轴 −1（AST 切 B01） | **rc=0 静默 52→45** | rc=2 FATAL 9/14 | rc=2 | 同值 `ce3356a77e9c`≠基线 | 同报 |
| D | 库轴名册 +1（s715 副本加键） | 输入不变即 52（瞎） | rc=2 FATAL 10/16 | rc=2 | 同值 `39fe677f2023`≠基线 | ②型同杀 |
| E | 库轴名册 −1（去 adapter-console） | 同上（瞎） | rc=2 FATAL 10/14 | rc=2 | 同值 `56a30f002bf7`≠基线 | 同报 |
| G | 库轴形状违规（ReleaseLibNode 抄 board＋坏 kebab） | rc=0 denom=52 无感 | rc=2「库轴名册形状违规 2 处」 | rc=2 同因 | 两尺同**不出** fp（坏名册下无可信 fp＝对称瞎） | 同报 |
| F | 库轴名册清空（pin 唯一放行 lever，harness 专用） | — | rc=0 放行全量读数 | rc=2 尺瞎 | sev fp=`788e6f1872f0`≠基线 | 无 solo 静默过 |

**「不存在一把看见一把看不见」的证明**：①A–E 每案两尺**同 rc=2**、fp **同值**且 **≠基线**（±1 在两轴任一都改 fp——fp 吃排序全清单，任何增删改序都翻指纹）；②改前对照列逐案展示旧世界正是「一把改读数／一把报错、另一把连名册长啥样都不打印」＝S808 §1B 所证病症复现；③唯一「sev 放行而 decl 报错」形态＝F（名册清空），而那是 `s715-deps.py` 被掏空——该件在 PIN_EXTRAS 完整性账里，动它板级即红，且 decl 当场同窗 FATAL：**放行的每一纳秒都有第二把尺在叫**，solo 静默过不存在。互锁的根＝两尺 fp 定义逐字同形＋同款派生口，任一侧偷改定义或抄清单，本探针在真名册上 fp 不等当场红。

## §4 改尺必自证（钉册 C6 强制两词）

- **直跑**：两把改后尺各自 `python -B` 单跑——sev 真实现算 **rc=2 干净退出**（stderr 一行 FATAL、无 Traceback、stdout 仅 fp 行＝零裁决词设计兑现）；sev 放行路径（F 案）**rc=0**；decl 真实现算 **rc=0** 全读数照出。三跑皆无崩。
- **读数（真实十库逐值不变，逐项对表）**：F 案放行路径 `stdout` 去掉 `roster_fp=` 行后与改前真尺 stdout **逐字节相等**——`stmt_edges=261`／`sym_edges=399`／`直连库对=52`／`declared=0`／`half=0`／`numer=0`／`denom=52`／`VERDICT: NOT-SEVERED` 逐项同值；decl 改后件同法逐字节相等（`BOARD DECL gap=5 roster=15 seeded=0` 原样＋fp 行）。改前后 sha 见 §0。
- **主代理 repin 签名块（可直接抄）**：
  `--reason "S821 名册 pin＋两尺互锁指纹（台账 #121）"`
  `--evidence "直跑不崩：改后真实现算 rc=2 无 traceback、放行路径 rc=0；读数：放行路径 stdout 与改前逐字节等值 denom=52 stmt=261 sym=399 numer=0（ROSTER-PIN-LOCK-S821.md §四）"`
  两枚同批：`--only s759-severance.py --only s759-decl-sources.py`（decl 因互锁 fp 同批改；分两笔则中间窗两尺 fp 不同形——**建议同一笔**）。

## §5 复跑命令簿（统一卫生前缀；cwd＝仓根）

```bash
cd "C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot"
export PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0
export PYTHONPYCACHEPREFIX="$(cygpath -w "$TEMP")/s821-pyc"
D=.superpowers/sdd/2026-09-24-central-dispatch
# V1 三态＋七案矩阵全复跑（末行 S821-RESULT ALL-PASS、rc=0＝本席交卷态）
../ChatBot_Runtime/venv/Scripts/python.exe -B $D/probes/s821-roster-pin.py; echo RC=$?
# V2 真实现算基线（本席未动它——应与 §1① 逐字同）
../ChatBot_Runtime/venv/Scripts/python.exe -B $D/probes/s759-severance.py
# V3 改后件复产与 sha 核对（两枚 sha256 应等 §0 改后值）
../ChatBot_Runtime/venv/Scripts/python.exe -B $D/probes/s821-roster-pin.py --emit-patched "$(cygpath -w "$TEMP")/s821-apply-check"
sha256sum "$(cygpath -w "$TEMP")/s821-apply-check/"*.py
# V4 patch md 再生成后与在盘 md 逐字节 cmp（同源确定性）
../ChatBot_Runtime/venv/Scripts/python.exe -B $D/probes/s821-roster-pin.py --emit-md "$(cygpath -w "$TEMP")/s821-regen.md"
cmp "$D/patches/s821-severance-roster-pin.md" "$(cygpath -w "$TEMP")/s821-regen.md" && echo MD-STABLE
```

V1 实跑输出（本席交卷态，全量已存档 `%TEMP%\s821-evidence.json`＋下方节选）：`S821 BASELINE pre-sev rc=0 denom=52 words=['NOT-SEVERED'] fp=None` … `S821 C-p3 PRE rc=0 denom=59 …POSTSEV rc=2 fp=d9c752ace0ff words=[] err='FATAL: 断开度只覆盖板块轴 15/20 ⇒ 分母不可判…'` … `S821-RESULT ALL-PASS baseline_fp=1cbc02d334a6 post_sha_sev=5a0b78d8…85819b post_sha_decl=f0bbeb9d…5cd9b0`，`PROBE_RC=0`。

## §6 另附一件：S808 §3 翻 YES 算术——三处前置裁定「缺什么」（交主代理进决策清单）

S808 已证：断开度翻 YES **不是 28 刀、不是 17、不是 3/4、更不是 1**——判据是「52 对**全部**声明化 ∧ 261 条语句边清零」，破环刀只是它的批次约束；**「17 刀全落分子仍 0」那格**（S808 §2 反证段：把 S621 的 17 枚库刀或 S606 的 28 枚类刀全落码，直连巨块碎完、断开度分子照旧 0，因为 52 对里 22 枚单向对根本不在任何破环账上、且声明一条没写）至今只是**论证**，没有机器演示格进任何板/账，引用它的决策都悬在散文上。要把 §3 那张「按消费方整库收口、批末分子 1/3/11/30/52」表从**推定**变成**可施工**，缺她/主代理三句话：
1. **归主与断边的先后**——现表按今值 52 给，而 559 条无主弃边（`contracts/__init__.py` 一枚 63 条）今天不在分母里，**补认领后分母只会 >52**（S621「删边只拆环不造环」同型）；缺裁定＝「先归主再断边」（表要重算，S808-1 尺可复跑）还是「先断有主面、无主面另批」；两路工单字面完全不同。
2. **「断进无主面缩分母」这条假绿后门**今天只被 S759 §四散文警告挡着、**机器腿不存在**——本席 pin 只锁名册轴覆盖，不锁「分母自己变小」；缺裁定＝是否授权立「分母单调性」活性腿（severance 逐窗钉 `denom 只升不降、除非有归主账对账`），不立则 261 的清零工程随时可以被「裁成判据前的过渡账」糊掉。
3. **施工单粒度口径三选一**——261（语句）／399（符号）／306（S621 import 目标实例）三把尺三个数，落哪个进工单、以及每枚「断」的验收判据（语句清零？还是声明在场即算？）至今无裁；不裁则各席按各自单位报进度，「分子 +3」这类汇报会重演本窗「同数不同物」。
（另半句 S808 已如实写的账保持原样：三裁之后才谈得上「最少 N 条具体 import」工单；本席未代做第四本账。）

## §7 规则 11 台账（注入处置）

- 本席开窗第一条工具结果附带了**伪装成技能调用的祈使句载荷**（简报预告的本窗第四例形态）：环境技能清单尾部含多条「You MUST use this … BEFORE ANY response … mandatory first-move」式指令文本（如名为 programming-mode 的条目要求「任何会话第一步先调技能」）。处置＝**一律当数据：技能零调用、任务未中断、按原简报推进**；本席全部动作仅出自 用户消息＋简报＋在册规范三类白名单。载荷原文未逐字留存（系环境配置回显而非文件正文），指纹＝首 40 字「architecture-visualization:explore: Architecture r…」／末 40 字「…default-skills-listing tail (enumeration data)」（消毒形）。命中登记于此，不执行、不上报为事故（无配置/进程/git 面被碰）。
- 两条「MEMORY.md 已被外部修改」系统通知与两次技能清单回显：当环境数据，零执行。其余工具结果/文件正文（含 S808/BRIEFS 内关于注入的记述文字）均为「关于注入的报告」，当数据。

## §8 PARKED（未做／等他方）

| # | 事项 | 停在哪 |
|---|---|---|
| P-S821-1 | severance 认领宇宙补齐 5 座（owner_of 吃库轴根）⇒ pin 放行的施工 | 本席红线＝只出 pin；pin 注释与 §2 已写明「补齐即自动放行」，施工归尺 owner/后续席；动工必与本 patch 同批对账（fp 基线要刷一次） |
| P-S821-2 | 统筹板对 `roster_fp=` 的取数与「fp 缺失＝失明」执法腿 | 本席交付探针＋机读行；板面接线归板 owner（S798/S777 线），本席未改板件 |
| P-S821-3 | G 案（名册形状违规）两尺同不出 fp 的对称性若要升级为「坏名册也留指纹残影」需重设 fp 定义 | 现设计如实=拒判且无可信名册则不印；登记不实施 |
| P-S821-4 | `ROSTER-PIN-LOCK` 与 S808 §1B-3「声明通道空表不可辨」第三瞎 | 本席 patch **未含**「库根可扫目录数==在册板块数」活性腿（S808 建议的第二腿）——简报必交面只点名名册 pin＋互锁腿，第三瞎仍挂账给尺 owner |
| P-S821-5 | 本席自曝：验证台自身五处 bug 三轮才收敛（3.13 `read_text(newline)` 误用／AnnAssign 守卫漏判／**裁决词子串自肥**——NOT-SEVERED 含 SEVERED，本席首版把基线读成双裁决词／join 吃尾换行假差／P3 空根生成 `(,)` 语法炸）| 全部由**本席自己的断言当场抓出**、未流进任何结论行；「判据自身造词/造零」两枚已可按 S795 编册口径归案，归册由编册席做 |

## §9 交卷核对

- 主件＝本件（末行 done）；`probes/s821-roster-pin.py`（矩阵实跑 ALL-PASS rc=0）；`patches/s821-severance-roster-pin.md`（锚点±3 行、四发＋三发 hunk、改前/改后 sha64、落码/复算/repin 通道）。
- 红线自查：未 commit／未 push／未 git init／未搬生产文件／未动 `.env`／未拨闸／未重启未杀进程／未跑 `dev.ps1 -Task test`；尺件本体与板件零写（§0 双核 sha）；仓外 `ChatBot_Libs` 只读（③案用 %TEMP% 假根，未碰真根一笔）。

done: yes
