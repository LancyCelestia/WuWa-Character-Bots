# v21r2 EP1 席日志（尾声清账·第一批：不碰根 __init__ 的独立清账项）

- 席位：EP1（2026-09-18）
- 纪律：固定解释器 `ChatBot_Runtime/venv/Scripts/python.exe`；`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`；pytest `--basetemp=%TEMP%/v21r2-ep1 -p no:cacheprovider`；禁 dev.ps1；零 git 写；根 `__init__.py`、RWOCb 五域（core/ops/decision/alerts+error_report/contracts）、MAT 文档域、S14b/WIREb/RK4b 新建域、`domains/render` 全部未触碰。

## 任务 1：scripts/extract_trigger_words.py 旧路径锚修复（S11 移交项）——已闭环

**取证结论：锚修复已在工作树落盘（RWC4 波内收口项），本席复核判定+实跑验证后关账，零代码改动。**

- 取证：`git diff -- scripts/extract_trigger_words.py` = 2 行改动（WIP 未提交）——`BASE_ROUTER_MODULE`/`BASE_ROUTER_REL` 由 `plugins.bot_unified_runtime.runtime.base_router`（旧路）改指 `plugins.bot_unified_runtime.domains.chat_reply.runtime.base_router`（canonical）。与 RWC4 日志「文件路径负载锚 8 文件（含 extract_trigger_words 旧路文本锚——不改则读垫片壳静默空转）」及「S11 席两观测红当波收口=test_pinyin_triggers_3 收集错」互相印证；S11 日志所述红点为 RWC4 在飞窗口期观测，现状已消。
- **判定（读 canonical 直连 vs 经垫片安全读取→择前者，且已在盘形态即前者）**：旧路 `plugins/bot_unified_runtime/runtime/base_router.py` 现为 668 字节 PEP 562 活转发垫片（`__getattr__`→import_module(canonical)），文件体内**无 `build_route_rules`/`RouteRule` 表**；本脚本第 97 行是对文件文本做 AST 静态提取（`next(... build_route_rules ...)`），若改读垫片文本必然 `StopIteration`——垫片对「运行时 import」透明、对「源码文本解析」不透明，故必须直读 canonical 文件路径。现形态正确，无进一步改动空间。
- 实跑证据 ①：`python scripts/extract_trigger_words.py` → **exit 0**，stdout 1252 行 JSON（route_rule_count=33、capability_count=32、behavioral_detector_count=29、verified_trigger_total=412、help_topic_count=77、help_topics_missing_trigger_records=[]），stderr 空。残留体检红点为既有台账项（cross_capability_conflicts 1 条 bot.group_info×bot.moegirl「群主是谁」、gate_help_to_route_violations 若干），属体检上报语义、非本席范围。
- 实跑证据 ②：`pytest tests/test_pinyin_triggers_3.py tests/test_pinyin_triggers_2.py tests/test_pinyin_triggers.py tests/test_trigger_spec.py tests/test_trigger_bidirectional_gate.py --basetemp=%TEMP%/v21r2-ep1 -p no:cacheprovider` → **1317 passed, 2 skipped, 1 xfailed in 2.58s**，收集期 StopIteration 消失（S11 移交红点关闭）。
- 状态：**完成（verified）**。未 commit（与全工作树 WIP 同待用户裁决）。

## 任务 3：树卫生清扫——已闭环（7 目录全清，零残留）

**盘点（2026-09-18 05:38 扫描，排除 .git/ChatBot_Runtime/ChatBot_Archive）**：

| 路径 | 类型 | 文件数 | 体积 | 最新写入 |
|---|---|---|---|---|
| `./.mypy_cache` | mypy 增量缓存 | 18 | 40102KB | 05:14:56（清扫前 ~23min） |
| `./.ruff_cache` | ruff 缓存 | 4 | 22KB | 05:19:39（清扫前 ~18min） |
| `plugins/bot_unified_runtime/__pycache__` | pyc | 1 | 340KB | 05:09:41 |
| `plugins/bot_unified_runtime/control_plane/__pycache__` | pyc | 1 | 16KB | 05:09:41 |
| `plugins/bot_unified_runtime/decision/__pycache__` | pyc | 1 | 4KB | 05:09:41 |
| `plugins/bot_unified_runtime/domains/core/decision/__pycache__` | pyc | 2 | 12KB | 05:09:41 |
| `plugins/bot_unified_runtime/domains/meme/reactions/__pycache__` | pyc | 1 | 48KB | 05:09:41 |

- 5 个 `__pycache__` 同秒（05:09:41.7xx）生成=单次无护环 import 事件（方向恰为 RWOCb 在飞域 decision/core/decision/control_plane，系在飞席冒烟直跑 python 所致）；`.mypy_cache`/`.ruff_cache` 为在飞席工具缓存（根级）。清扫时点距最新写入 18 分钟、清扫期间零新写入、删除零文件锁——判定均非「正在写的活跃缓存」，按规程备份后全清。
- **备份**：`%TEMP%/v21r2-ep1-hygiene-backup-20260918-053848/`（28 文件，含 40MB mypy 缓存；目录名 `__` 编码原路径分隔符），备份零错误，可整体回滚。
- **清除**：7/7 CLEANED（过程注记：本会话 Git Bash 环境 `rm` 不在 PATH，首轮 `|| echo` 把 127 误报成 DELETE-LOCKED，改 `cmd //c rmdir /s /q` 兜底后全清——并非文件锁，如实记录）。
- **终验**：全仓缓存目录 0、`.pyc` 0、根级杂散 `data/` 0、`sources/data/` 整目录已随 W3 迁移不复存在（AGENTS.md 第 6 条所载旧豁免路径已被 canonical 取代，本席如实登记待根 __init__ 子波清账时同步文档）。
- **qx.json 完好验证**：唯一真身 `plugins/bot_unified_runtime/domains/weather/assets/qx.json`，sha256=`e8285e77d8edf2f90faf670b6f39d8dc3b03e995d1128ef64b2cc4d86361b668`（与 W3/RW 各席日志引用的 e8285e77 一致），JSON 可解析、**2527 区县全量在载**；`domains/weather/assets/` 目录仅含 qx.json，无杂物。
- 杂散 data/ 专项：全仓 `data` 目录仅剩 7 个 domains 域内 canonical 载体（divination/finance/food/location/music/schedule/weather 的 data 子包=真身模块目录，非运行时数据）+`domains/schedule/data/calendar_exceptions.json`（S11 席 schema 模板资产，留档不删）。零测试直写源码树 data/ 残留（G1 写入拦截守卫持续生效实证）。
- 状态：**完成（verified）**。

## 任务 2：垫片退役清单盘点——已闭环（只读产出，零退役动作）

**交付物：`docs/design/v21r2-shim-retirement-inventory.md`（689 行，尾声退役波施工图）。**

- 方法：全仓 AST 机核（**1155 个 .py**=plugins+tests+scripts+根，零人工转录——RW15 教训机读直驱）。垫片判定=非 domains/ 路径且顶层体仅含 docstring/import/`__all__`/`__path__`/`__getattr__`/`__dir__` 且拓扑目标含 `…bot_unified_runtime.domains.*`（绝对 import 与 PEP562 `_CANONICAL` 双形态，相对导入 level 解析）。消费方计数=AST import 边（精确匹配+`from pkg import shim` 父绑定；模块级/函数级分列）+字符串引用（monkeypatch 字符串式/importlib 串/文本锚，只计非 AST 消费文件）。
- **快照总计：275 张垫片 / 1591 条消费边**。形态：静态 re-export 139、PEP562 活转发 131、包静态 re-export 5。判定分布：需先改写消费方 135、在飞占域（RWOC）55、仅测试消费方 44、可直接退役 41。
- **波次归因**（垫片 docstring 自带标记，`v21r2 [reorg] <波>` 正则提取，275/275 全命中）：W1a 28、W1b 16、W2 4、W3 3、W4 2、W5 10、W6 8、W7 10、W8 21、W9 7、W10 9、W11 11、W12 4、W13 11、W14 11、W15a 23、W15b 10、W15d 20、W16 5、RWC3 7、**RWOC 55（在飞持续增长）**——与各波日志声明张数逐一吻合（外部交叉验证通过）。
- **判定规则成文**（§2）：零消费=直接删；仅测试消费方=同波改写后删；有 src import/字串引用=全部消费点改 canonical 后删；docstring=RWOC → 在飞占域其它席不得代拆；src 函数级旧路取符号×测试旧路补丁并存=疑似 LEGAL 配对（RW8 social_v2/eat:518 先例）双侧同波同步。
- **全局前置**（§3）：①108 张垫片被根 `__init__.py` 惰性导入消费 → 硬前置=子波 5；②RWOCb 收官先行；③每批退役同波门禁（全量收集 0 错+verify_hashes+doc_sync+受影响域回归，删除后旧路径 import 由测试网兜 ImportError）；④包垫片与子模块垫片同批删（子模块 import 隐式初始化父包）。
- **LEGAL 配对疑似 8 张**（§6）：capabilities.auto_send/content_parser/subscribe、character.memory、llm.providers、sender（29 个测试文件旧路补丁=最大配对面）、sources.parsers、sources.parsers.http_util。
- **方法盲区如实登记**：拼接字符串动态 import 理论漏检（各波日志未见实例）；1 个在飞文件语法红未入扫=domains/ops/incident/service.py:215 invalid syntax（**S14 席在飞 WIP，本席未触**，观测报备）。
- 复现：机核脚本与 JSON 存 `%TEMP%/v21r2-ep1-shim-inventory.py` / `v21r2-ep1-shim-inventory.json`（+文档生成器 `v21r2-ep1-shim-doc-gen.py`），重跑可复现。检测器抽验：contracts/media、decision/outbound、audit/file_logger、route_demo、parsers 聚合包 `__init__` 五点实读全为真垫片，零误报实证。
- 状态：**完成（verified）**。本任务只读，零代码/垫片改动。

## 收尾

- 全程零 git 写、根 `__init__.py`/RWOCb 五域/MAT/S14b/WIREb/RK4b/domains/render 零触碰（任务 1 脚本锚系既有 WIP 非本席改动）。
- 本席自产零缓存（全程 PYTHONDONTWRITEBYTECODE=1 + basetemp=%TEMP%/v21r2-ep1 + no:cacheprovider）。
- **清扫后增量观测（收尾时点）**：根 `.mypy_cache`（18 文件）/`.ruff_cache`（4 文件）在清扫后 ~10 分钟内被在飞席位重新写入（newest_age≈570-590s）——属「正在写的活跃缓存」，按简报条款**跳过留条目**移交最终退役波（届时以同款 freshness 检查判定）；本席清扫实效以 05:38-05:39 时点「7/7 清零、终验 0 缓存」为准。
- COORDINATION.md 已追加本席一行（第 56 行，UTF-8 完整性 python 复核通过）。
