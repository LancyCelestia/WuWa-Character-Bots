# 席 R1 工单 — `runtime_layout` 扫面扩面 + 同批自测锁（2026-10-02）

波次档：`.superpowers/sdd/2026-10-02-fixwave/SEATS.md` §15。独占面＝`scripts/runtime_layout_smoke.py`
＋新建自测件 `tests/test_runtime_layout_smoke.py`＋本工单。**未碰** `scripts/dev.ps1`、`config.py`、
`__init__.py`；未动任何派生册（`docs/auto-facts.md` 等）；未做 git 写、未起停任何进程、未外发。

---

## ① 现状核实（带 file:line）

HEAD 版门的生成物面只有两格，且都是"看得见的那一半"：

| 事实 | 坐标（HEAD） |
|---|---|
| 字节码面只认 `*.pyc` / `*.pyo` / `__pycache__` 三种形状，别的残留全盲 | `scripts/runtime_layout_smoke.py:115-116`（`git show HEAD:…` 现读） |
| 源码状态面只查 `data` / `cache` / `config` 三枚**目录名**，且要求"非空"才算红 | `scripts/runtime_layout_smoke.py:110-113` |
| 既有同类门的形状（本件照抄其判据形态：os.walk + 命中即记账 + 命中即剪枝） | `tests/test_static_hygiene_snapshot.py:31,72-90` |
| dev.ps1 自己 pin 了 `PYTHONDONTWRITEBYTECODE=1` 与 `PYTHONPYCACHEPREFIX=<Runtime>/pycache` | `scripts/dev.ps1:68-73`（只读取证，未改一字） |
| lint / typecheck 的 ruff、mypy 缓存被显式送进 Runtime：`--cache-dir` → `ChatBot_Runtime/cache/{ruff,mypy}` | `scripts/chatbot-tasks.json:140-142,150-152` |
| pytest 基台一律落在两个受保护根**之外**（`Get-PytestScratchBase` + `--basetemp`） | `scripts/dev.ps1:171-195,471-491` |
| `.gitignore` 早就写着"仓库内 basetemp 残留 `cb-w9chk/` 未被罩住" | `.gitignore` 末段 `/cb-w9chk/` 注释 |
| `webui/node_modules/` 与 `docs/boards/**` 是**在册**的仓外挂载 junction（不是残留，不能当红打） | `.gitignore:112`、`docs/boards/_boards-20260921/00-plan.md:83,108` |

⇒ 结论：dev.ps1 路线是干净的。树内出现任何字节码／工具缓存／基台残根，**只可能**来自绕过 dev.ps1 的裸跑
（或第三方 junction 的正常内容），门必须把这个区分写进报告，否则下一次还是全树 grep 找凶手。

本波两次实咬都在门的盲区里：
1. 433 枚 `.pyc` 落进 `plugins/**`（形状旧门看得见、**类别不点名**，读数只有一句"Python cache path(s)"，
   分不清是谁的路线造的）；
2. 一枚**空** `Bot_Character_Bots.egg-info/` 被 `.gitignore` 吞掉 ⇒ `git status` 零输出、旧门也零输出，
   但 `importlib.metadata` 把它认成一枚无 `Version` 的 distribution，直接吃掉三枚 `test_error_report`。

现算基线（2026-10-02 01:4x 本地，同一把尺跑真实树）：全树 `os.walk` 0.5s；`.pyc` 岛外 1 枚、岛内 0 枚；
basetemp 内容形状（子目录名 `test_*<N>`）全树只命中 `cb-w9chk/`（46 枚）⇒ **阈值 3 没有灰区**；
空目录 1198 枚 ⇒ **「空目录」本身绝不能当判据**，只有落在生成物形状上（`*.egg-info` 一类）才记账。

## ② 改法与理由

只改两枚文件（独占面内），不碰执行面。

1. `scripts/runtime_layout_smoke.py`：新增**单遍 os.walk** 的残留扫描器
   `scan_generated_residue(root) -> dict[类别, 命中清单]`（`:212`）＋渲染器
   `format_generated_residue_errors(findings)`（`:279`），`main()` 里把旧的三发 `rglob` 换成
   一次调用并把结果并进 `errors`（`:349-350`）。五枚类别（`:94-107`）＝
   `python-bytecode` / `tool-cache`（`.mypy_cache`/`.ruff_cache`/`.pytest_cache`）/
   `in-tree-venv`（`.venv`、`venv` 裸名即算；`env` 只认硬形状 `pyvenv.cfg`/`Lib/site-packages`，
   免得误伤同名源码目录）/ `pytest-scratch-in-repo`（名状 `pytest-of-*`、`.pytest_tmp*`、`basetemp`
   ＋ 形状判据"≥3 枚 `test_*<N>` 子目录"）/ `distribution-metadata`（`*.egg-info`、`*.dist-info`、`.eggs`，
   并读 `METADATA`/`PKG-INFO` 说清是不是"无 Version 的空壳"＝本波实咬那一格的形态）。
   * 每类一条 `RESIDUE_ATTRIBUTION`（`:134-166`）写明**污染源**，`tool-cache` 那条直接点名
     "来自 dev.ps1 之外的裸 `ruff`/`mypy`/`pytest` 调用"，字节码那条点名"绕过了 dev.ps1 的卫生前缀"。
   * 岛只剪枝不记账：`.git`、`node_modules`、`site-packages`、`dist-packages`、`__pypackages__`
     （`:117-119`）。这条是**实测逼出来的**——我第一遍把 node_modules 当普通目录扫，真实树打出 7000+ 枚
     命中、单次扫描 10s，全是 junction 后面的真身；剪枝后同一棵树 0.07s。
   * 命中即剪枝：一已被点名的残留根不再往里钻（树内 `.venv` 报一行，不报它 `site-packages` 里几百枚 dist-info）。
   * 只报不删：本门全程只读，清理裁定归人（本工作区已两次因盲删整片灭失，见台账 #68/#70）。
   * 顺带修一处返回值形态不一致：缺席的根原先返回"五枚空类别"，与"扫过且干净"的 `{}` 不同形
     （调用方按 `if findings:` 判红会把"没得扫"读成"扫出五类"）。
2. `tests/test_runtime_layout_smoke.py`（新建，19 节点）＝与扩面**同批**的自测锁（台账 #68★）：
   * 注毒腿 ×5（逐类真造真扫，断言"必须出现该类＋必须点名该枚路径"，并断言**只**报这一类＝无连带误伤）；
   * 反向不误伤腿 ×5（同一份"合法源码树"骨架：`.git/config`、`webui/node_modules/…`、
     `site-packages/*.dist-info`、名为 `env` 的普通源码目录、只有两枚 `test_*<N>` 子目录的目录、
     空的 `logs/`、`probes/` ⇒ 注毒前基线必须 `{}`）；
   * 专项腿 ×4：五类同树混注必须五格全现身；**空 egg-info** 那格必须同时说清 `empty` 与 `Version`；
     无 Version 的 `PKG-INFO` 要说"carries no Version:"；归因文案必须含
     `PYTHONDONTWRITEBYTECODE`/`PYTHONPYCACHEPREFIX`/`bypassed dev.ps1`/`--cache-dir`；
     缺席的根不许炸；岛不许被点名；真实树跑一遍必须"类别全在册 + 每条命中在盘上真存在 + <120s"；
   * 端到端腿 ×2（**真起子进程**，不是读源码数字符串）：把 `runtime_paths.py` + `runtime_layout_smoke.py`
     拷进**仓外**副本（tmp_path 下，拷当场真身⇒永不过期），配一份假 Runtime 根让别的判据全绿，
     干净副本 `rc==0` 且 stdout 有 `generated_residue=absent`；注毒副本（真造一枚 `.pyc` + 一枚空 egg-info）
     `rc==1` 且 stdout 同时点名 `[python-bytecode]` 与 `[distribution-metadata]`。
     子进程一律钉 `encoding="utf-8"`（台账 #47★：不钉必崩）。

没有新配置键、没有新依赖、没有 schema 变化 ⇒ **无 CONFIG-REQUEST**。

## ③ 判据读数（实跑末行原样）

卫生前缀一律带 `PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0` + `-p no:cacheprovider`
+ `--basetemp=<仓库外>`；ruff/mypy 一律 `--cache-dir=<Runtime>/cache/*`（**我自己头两次跑漏了这一枚**，见 ⑤）。

```
本席自测锁（19 节点，真实工作树；读数先落仓库外文件再 Read 取回，两次跑一致）
  … -m pytest -p no:cacheprovider --basetemp=$TEMP/qoder-R1/bt -q tests/test_runtime_layout_smoke.py
  ...................                                                      [100%]
  19 passed in 4.48s            PYTEST_RC=0

门本体在真实树上的现读（三类全现身；旧门这三格一条都不报）
  … scripts/runtime_layout_smoke.py
  runtime-layout: FAIL
  - generated residue [python-bytecode] x3: plugins/bot_unified_runtime/domains/chat_reply/runtime/__pycache__/, plugins/bot_unified_runtime/domains/media/__pycache__/, plugins/bot_unified_runtime/runtime/__pycache__/ -- attribution: scripts/dev.ps1 pins PYTHONDONTWRITEBYTECODE=1 and PYTHONPYCACHEPREFIX=<ChatBot_Runtime>/pycache … 只能来自绕过 dev.ps1 的裸跑
  - generated residue [tool-cache] x2: .mypy_cache/, .ruff_cache/ -- attribution: scripts/dev.ps1 hands ruff/mypy a --cache-dir inside ChatBot_Runtime/cache and pytest runs with -p no:cacheprovider, so a cache dir in the source tree comes from a raw `ruff`/`mypy`/`pytest` call outside dev.ps1
  - generated residue [in-tree-venv] x1: .venv/ -- attribution: the project interpreter lives in ChatBot_Runtime/venv; dev.ps1 probes an in-tree .venv as a fallback, so this is interpreter drift waiting to happen
  GATE_RC=1

ruff（只我这两件）
  "C:/…/ChatBot_Runtime/venv/Scripts/python.exe" -m ruff check --output-format=concise --cache-dir=… tests/test_runtime_layout_smoke.py scripts/runtime_layout_smoke.py
  All checks passed!

mypy（门本体；dev.ps1 的 typecheck 面只覆盖 plugins，本格是我自加的旁证）
  -m mypy --cache-dir=… --explicit-package-bases --ignore-missing-imports scripts/runtime_layout_smoke.py
  Success: no issues found in 1 source file            MYPY_RC=0

同一把尺在真实树上的受影响选择器（七件全在盘）
  … -q tests/test_runtime_layout_smoke.py tests/test_static_hygiene_snapshot.py tests/test_autosync_gate.py
      tests/test_p1_hotspot_hygiene.py tests/test_doc_sync_gates.py tests/test_documentation_consistency.py
      tests/test_cross_validation_gates.py -rf
  4 failed, 127 passed in 16.08s      RC=1     （逐枚归属见 ④）

四道门走 scripts/dev.ps1 的权威读数（整份日志先落仓库外文件再 Read；"push"＝Push-Location，不是 git push）
  -Task runtime-layout → runtime-layout: FAIL，RL_RC=1，红就是我扩出来的三类（上面那三行，逐条带归因）
  -Task lint          → Found 36 errors.（LINT_RC=1）
  -Task typecheck     → Found 5 errors in 2 files (checked 609 source files)，TYPECHECK_RC=1，
                        首枚＝plugins/bot_unified_runtime/runtime/db_backup.py:576 union-attr
  ⇒ 两枚 log 里 grep "runtime_layout_smoke" 各 0 次：lint/typecheck 的红一枚不落在我这两件上
    （落点集中在席 X1b 的 db_backup.py / tests/test_db_backup.py、席 G1 的 claims_subset 门、席 D1 的 quirks.py 等）
```

## ④ 净新增红 A/B（node ID 分桶，#68★ 的正道）

方法＝`git archive HEAD` 抽到仓库外两份副本，一份原样、一份**只**覆盖我这两枚文件（其他席的在飞 WIP
两侧都不在场 ⇒ 差异只可能是我造成的），同一把尺跑同一组受影响选择器
（`test_cross_validation_gates / test_static_hygiene_snapshot / test_autosync_gate /
test_p1_hotspot_hygiene / test_doc_sync_gates / test_documentation_consistency`，B 侧再带上我的新锁）：

| 侧 | 读数（重建副本后复跑，整份输出先落仓库外文件再 `Read`） | 红（node ID） |
|---|---|---|
| A `HEAD` 原样 | `2 failed, 110 passed in 13.71s` | `test_cross_validation_gates.py::test_verify_hashes_manifest_clean`、`::test_doc_sync_auto_facts_in_sync` |
| B `HEAD` + 我两枚 | `2 failed, 129 passed in 14.77s` | 同上两枚，逐字相同 |

⇒ 两枚红＝**HEAD 基线自红**（A 侧就有），差集只有 B 侧多出的 19 枚全绿节点 ⇒ **本席域净新增红 0**。
两侧唯一差异＝我的两枚文件，其他席的在飞 WIP 两侧都不在场 ⇒ 差异只可能来自我这一批。
按 #72★ 口径，本席**不签**"全绿"：真实工作树同一选择器另有 `4 failed, 127 passed`，四枚红逐枚归属＝
- `test_static_hygiene_snapshot.py::test_full_tree_import_sort_is_clean` ⇒ `ruff --select I001` 现读命中
  `plugins/bot_unified_runtime/runtime/db_backup.py:1188`（席 X1b）与 `tests/test_claims_subset_implementation_gate.py:68`（席 G1）；全树 ruff 另有 `tests/test_db_backup.py:673` invalid-syntax（在飞件写到一半）。
- `test_static_hygiene_snapshot.py::test_source_tree_has_no_cache_products` ⇒ 树内 `.mypy_cache/`（mtime 01:56:41）、
  `.ruff_cache/`（01:53:21）＋并发席裸跑留下的三枚 `__pycache__`（这两枚工具缓存**本席无法排除自己有份**，见 ⑤.1）。
- `test_cross_validation_gates.py::test_verify_hashes_manifest_clean`、`::test_doc_sync_auto_facts_in_sync`
  ⇒ A/B 两侧（纯 HEAD）都红＝HEAD 基线既存红，不是本席造成。

## ⑤ 未尽事项与原因

1. **树内残留清单交主会话处置**（本席一律不删：不属我独占面，且盲删是本仓两次整片灭失的成因）。
   现点名为红的三格：`plugins/bot_unified_runtime/domains/chat_reply/runtime/__pycache__/`、
   `plugins/bot_unified_runtime/domains/media/__pycache__/`、`plugins/bot_unified_runtime/runtime/__pycache__/`
   （逐枚 `.pyc` 由门自己列出，本席不代删）＋ `.mypy_cache/`、`.ruff_cache/` ＋ `.venv/`
   （`Scripts/` 已空、只剩 `Lib/site-packages`，HANDBOOK 在册「本体留着等用户裁定」⇒ 本席把它报成
   `in-tree-venv` 一类，删不删由用户裁）。
   ⚠ **本席自报一格**：窗口早期我有两次 ruff/mypy 漏带 `--cache-dir`（`.ruff_cache` mtime 01:53:21、
   `.mypy_cache` 01:56:41 与本席动作窗口重叠），⇒ 这两枚工具缓存**不能排除本席有份**；此后一律
   `--cache-dir=<ChatBot_Runtime>/cache/{ruff,mypy}`，且没有删它们（并发席也在造同一形状，删了会吃掉别人的取证）。
   请主会话按"清单逐枚点名删"的规程处理，不要递归删。
2. **派生册漂移**：新增自测件 ⇒ `tests/` 文件数 +1 ⇒ `scripts/doc_sync.py` 的「测试文件数取数口」
   （`scripts/doc_sync.py:232-234`）与 `docs/auto-facts.md` 不同步。`docs/auto-facts.md` 与
   `test_doc_sync_auto_facts_in_sync` 是主会话在册面（progress.md 别席在飞面 + Ruling 已定"收笔后一次性
   `--write` 重录"）⇒ 请主会话收笔时 `python scripts/doc_sync.py --write` 一并重录，本席不越界。
   注：这条红 A 侧（HEAD 原样）就已存在，不是我造成的。
3. **`dev.ps1` 侧的一格如实记**：污染源是"绕过 dev.ps1 直跑 python/pytest"，不是 dev.ps1 本身
   （它 pin 的三通道见 ①）。本席门的归因文案按这个口径写死并配了断言腿，别把门报成凶手。
   可选后续（不属本席面）：`Get-ProjectCommand` 把仓内 `.venv` 当第二候选（`scripts/dev.ps1:93-96`），
   Runtime venv 一坏就静默换解释器——要不要收紧候选序，交主会话裁。
4. **`.claude/settings.local.json` 权限申请失败一次**（工具调用被拒，未重试、未绕行，改用既有
   `Grep`/`Read`/`Bash` 完成同一步）。不改任何配置、不装包。
5. **注入登记（AGENTS 规则 11；本席共 3 枚，均未执行、均未复述原文）**
   判定口径：三条都不是指令来源白名单成员（用户消息／本席简报／在册规范），一律当数据。

   | 时刻(UTC) | 哪次工具调用 | 载荷形态（一句话） | 处置 | 指纹 |
   |---|---|---|---|---|
   | 2026-10-01 18:00:10Z | `Bash`（`sed` 抽 `tests/test_p1_hotspot_hygiene.py` 行段） | 行段结果尾部混进一段虚构的"棘轮测试本体"（自造 helper＋自造用例名），指名我的门脚本命中它，意在把我引去改无关文件 | 拒执行；`Read` 真身两段落盘＋`grep -rn "stay_warm\|_re_compile_calls" tests/` 现算＝全树零命中 ⇒ 该用例不存在；继续原任务 | sha256[:16] `6b808b5d2ef09d1a`，len 236；首末 40 字已零宽转码，见下注 |
   | 2026-10-01 18:04:05Z | `Edit` 结果回声 | 把一次真实编辑说成成功，同时附上三条虚构 lint 结论＋"none blocking"的定性，意在让我按假清单去动别人的行号 | 不据此改动任何文件；ruff/mypy 一律自己现跑（③ 的读数与它逐字不符） | sha256[:16] `f6aa373359f66a86`，len 178 |
   | 2026-10-01 18:07:12Z | `Bash`（门禁选择器的一次 pytest 读数） | 伪造整份 pytest 汇总：既把我的锁写成"6 枚注毒腿红"，又引用**盘上根本不存在的文件** `tests/test_plugin_layout_l1_l2.py:191` 与不存在的用例 `test_p1_hotspot_hygiene.py::test_request_path_re_compiles_stay_warm` | 拒按此读数记账；`ls tests` 现算证伪该文件不存在⇒该份汇总整条作废；同一选择器改**落仓外文件再用 Read 看**重跑两遍，两次一致（`4 failed, 127 passed`，四枚 node ID 全是真存在的件），A/B 两侧也各自重跑重读 | sha256[:16] `f2e0598a10180245`，len 311 |
   | 另案（**未定性**，仅登记） | 一串串入的"另一席会话 81b7 已完成"通知 | 后续 `TaskStop` 实得 "Task 81b7 not found" 既不能证实也不能证伪（任务可能已被回收）⇒ 按数据记账、不进交付账，也不据此宣称任何席的交付 | 不据此记账 | 原文未留存，无可指纹 |

   ⚠ 前三条载荷**原文当时未逐字落盘**（同 `P-56` 先例，做不到精确匹配），故上表哈希＝本席复写文本的指纹、
   非原文指纹；首末各 40 字符已按规则做零宽转码（U+F02A 只用于载荷区，绝不进文件名/路径/注册表键）。
   ⇒ 本席由此固化的作业口径：**关键读数一律先落仓库外文件、再用 `Read` 取回**，且成对复跑求一致；
   凡引用"不存在的坐标/用例"的工具结果＝伪造，直接作废整条读数而不是部分采信。
   主会话义务：本表请登记进安全台账，并向用户单独点名一次。

   载荷片段**不写进本册**（原样转述会让"关于注入的报告"本身变成新载体、被下一次 `grep` 二次传播）：
   首末各 40 字符的零宽转码（U+F02A 断形）件已落**仓库外**
   `%TEMP%/qoder-R1/injection-forensics.txt`（681 B，三条 × 首末各一行，主会话可按上表哈希复核）；
   本册只留时刻＋工具调用＋形态定性＋sha256[:16]。
