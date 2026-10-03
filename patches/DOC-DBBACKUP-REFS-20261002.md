# DOC 工单 · db_backup 挪家残余指针普查（2026-10-02 下午窗）

- 席：DOC（只读普查，唯一写面＝本工单；零 git 写 / 零进程 / 零配置改 / 未派子代理）。
- 事件：`plugins/bot_unified_runtime/runtime/db_backup.py` → `plugins/bot_unified_runtime/domains/ops/db_backup.py`；唯一生产消费者 `domains/ops/admin/runtime_admin.py:244` 已同批改 `from plugins.bot_unified_runtime.domains.ops import db_backup`（实读复核）。
- 方法注：模块名子串 `db_backup` 是三种旧形态（`runtime.db_backup` 点号 / `runtime/db_backup` 路径 / `from …runtime import db_backup`）的公共子串 ⇒ 先子串全量扫（＝形态扫超集），再逐形态精确复核，两轴（git grep＝tracked、grep -r＝含未跟踪）都跑。

## ① 命令与命中清单

### 普查一：代码面（plugins/ scripts/ tests/ bot.py 根 *.py）

命令（tracked 轴）：
```
git grep -n "db_backup"                  # 子串全量
git grep -n "runtime\.db_backup"         # 点号形 → 0 命中
git grep -n "runtime/db_backup"          # 路径形
git grep -n "runtime import db_backup"   # import 形 → 0 命中
```
命令（含未跟踪轴）：
```
grep -rEn "runtime\.db_backup|runtime/db_backup|runtime import db_backup" \
  plugins scripts tests bot.py docs patches COMMANDS.md   # 已核 __pycache__ 不存在
```

命中（代码面全量）：
- **会执行的真实 import：仅 1 枚且已是新路径**——`plugins/bot_unified_runtime/domains/ops/admin/runtime_admin.py:244`（241 行 docstring 提 `db_backup._reject_production_target`＝模块限定名无路径，非残余）。全树再无第二处 import（含 `__init__` 再导出、动态 importlib，均 0）。
- **monkeypatch/mock 字符串目标：0**。
- **注释/docstring 提及旧路径：1**——`tests/test_config_key_registration_ledger.py:289`（`CORPUS_FLOOR_BASELINE` 行尾注释，2026-10-02 现算复录的历史账，点名当时三枚未入库在飞件含 `plugins/bot_unified_runtime/runtime/db_backup.py`；非可执行、非 patch 目标——该测试运行时走 `census.py_files()` 现算计数，不读这行注释）。
- 其余子串命中全在新件自身（`domains/ops/db_backup.py` 内部 `bot_db_backup_*` 配置键，与模块路径无关）；bot.py / scripts/ / `config.py` / 根 *.py：0 命中。
- 现场核验：旧件已不在盘（`ls plugins/bot_unified_runtime/runtime/`＝`__init__.py / capability_protocols.py / content_route.py / pipeline.py / pricing.py / settings.py` 六件）；`plugins/bot_unified_runtime/runtime/__pycache__/` 目录已不存在（前账 `db_backup.cpython-312.pyc` 缓存残余已清，无 runtime-layout 缓存风险）；新件当前态＝`??` 未跟踪。

### 普查二：文档面

命令：
```
grep -n "db_backup" docs/README.md docs/CODE-MAP.md COMMANDS.md \
  docs/db-owners.md docs/config-catalog-full.md            # 0 命中
grep -rn "db_backup" docs/boards/                          # 0 命中
grep -c "db_backup" docs/HANDBOOK.md docs/HANDOFF-FIXWAVE-20261002.md   # 6 / 11（只计数）
```
- 六个点名地图类文档（README / CODE-MAP / COMMANDS / db-owners / config-catalog-full）＋ boards/**：**零提法**（连历史账注记都没有）⇒ 无任何文档面 live 指针。
- `docs/HANDBOOK.md` 6 行（5747/5760/5795/5843/5845/5856）、`docs/HANDOFF-FIXWAVE-20261002.md` 11 行：按工单只计数不细读（主会话已知＝历史账；注：HANDBOOK 5760 对 `db_backup.py` 是裸文件名无路径，挪家不改文件名，不构成死指针）。

### 普查三：生成物面

命令：`grep -n "db_backup" docs/command-catalog.md docs/auto-facts.md tests/render_hashes.json`
→ 三件 **0 命中**：无生成器产物引用旧路径，无需重录自愈。

## ② 判定

**代码面 ＋ 在册文档面（工单点名六件＋boards）＝零 live 指针。** 无需同批补改任何 import、mock 目标或地图文档。

边界一枚（改不改均可，零功能影响）：`tests/test_config_key_registration_ledger.py:289` 注释里的旧路径 `plugins/bot_unified_runtime/runtime/db_backup.py`。该行是带日期戳的"当时值"历史账（记当时三枚未入库在飞件），按规则 10 形态可原样保留；若主会话要顺手收口，改法＝该路径后补「（现 `domains/ops/db_backup.py`）」六个字，不动数值、不动容差。

## ③ 不确定项

1. `.superpowers/` 不在普查面：其中 `.superpowers/sdd/2026-10-02-fixwave/half-done/test_db_backup.py.HALF-WRITTEN` 仍在盘（停尸件，非可执行、不被 import，HANDBOOK/HANDOFF 已在账），未计入也未动。
2. 挪家未留旧路径 shim：`tests/test_legacy_shim_import_ratchet.py`、`tests/test_shim_retirement_ledger.py`、`domains/core/board_shim_ledger.py` 均无 db_backup 行 ⇒ 无垫片登记需要退役；若本波本意就是"无 shim 直挪"，现树自洽。
3. lint / pytest 本席未跑（只读席、无执行面）：本工单只对静态指针普查结论负责，不背"全绿"账；四道门读数以主会话实跑为准。

## ④ 未尽事项（普查面外，仅登记不动手）

- `patches/` 十件席位工作单提及旧路径（tracked：E1:103、F1:121/124、F2:83/139、HB-A:76、HB-C:15、Q1:224/226/254、R1:113/115/134、S1:76-78；untracked：B1-TTS:147/149/151/211、P3A:276）——全部日期戳历史账，按惯例不改，仅登记。
- `docs/HANDBOOK.md`（6 行）与 `docs/HANDOFF-FIXWAVE-20261002.md`（11 行）是否随波改指真身，属主会话禁写面裁量，本席未动。
- 新件 `domains/ops/db_backup.py` 未跟踪；提交 / 推送 / 重启按常令由用户执行或明示授权，本席未触碰。
