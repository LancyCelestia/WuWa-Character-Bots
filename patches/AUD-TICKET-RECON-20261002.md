# 工单 AUD · 八单账面↔盘面对账（2026-10-02 下午窗 · 只读对账席）

- 席：AUD（只读；唯一写面＝本工单）。零 git 写 / 零进程动作 / 零配置改 / 未派子代理。
- 复跑环境：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0` + Runtime venv；pytest `-p no:cacheprovider --basetemp=%TEMP%/qoder-AUD/*`（目录预建）；ruff `--no-cache`。
- ⚠ **环境异常披露（非树缺陷）**：本席初段复跑，凡用 `tmp_path` 的套件（d2/bkt/dbt/img）全 ERROR——venv 内 `pytest_asyncio` 陈旧 `__pycache__` 字节码接管 basetemp 创建（`mkdir(parents=False, exist_ok=False)`），`co_filename` 指向 `WuWa-Character-Bots\.venv\...plugin.py:924`，而该目录在本席跑窗中被外部删除（源码 `???` 不可读）；各席命令模板的 `mkdir -p basetemp` 恰好掩盖此坑。预建 basetemp 后全绿复现。venv＝受保护运行数据，本席未动。**教训：直跑 pytest 前先 `mkdir -p` basetemp 全路径**。
- ⚠ **mtime 异常一枚**：`scripts/ab_red_bucket.py` 与 `tests/test_store_write_trace_d2.py` mtime 同到 100ns（16:47:31.6022914）＝同批拷贝痕迹；内容实测不受影响。

## 判定表（每席一行；读数＝本席实跑末行，mtime＝+0800）

| 席/工单 | 在盘 | 抽验读数（本席实跑） | 判定 |
|---|---|---|---|
| INT | ✓16:11 | `16 passed in 3.60s`；tts.py:1556 调用带第四参 `sender_id=`（读码实证，group 形调用全文仅此一枚）；POISON-INT＝0、content_route.py POISON＝0；群分支四步顺序①黑②白③人腿(`pwl and sid in pwl and sid not in pbl`)④False＋docstring 裁定行全在盘（:893-968） | **一致** |
| MIG | ✓16:34 | `15 passed in 2.70s` | **一致** |
| L1 | ✓16:27 | 四件 ruff `All checks passed!`；w1 `28 passed in 10.52s`；d2 当时读数 1F16P 与 D2F 修后 17P 时间线自洽（测试件 mtime 16:47） | **一致** |
| L2 | ✓16:45 | 五件 ruff `All checks passed!`；五文件 mtime 16:42-16:43 与工单 16:38-16:39 基线＋修复叙事吻合 | **一致** |
| D2F | ✓16:48 | `17 passed in 3.37s`；双腿注毒构造在盘（test_db_backup 无关；test_store_write_trace_d2.py 注毒腿两步 replace） | **一致**（附 mtime 同纳秒异常注记） |
| BKT | ✓16:59 | `9 passed in 2.43s`；两件 ruff `All checks passed!`；`scripts/ab_red_bucket.py --help` rc=0 | **一致** |
| DOC | ✓16:06 | `git grep runtime\.db_backup`／`runtime import db_backup`（plugins/scripts/tests/bot.py）均零命中；runtime_admin.py:244＝`from plugins.bot_unified_runtime.domains.ops import db_backup`（唯一活 import）；旧 `runtime/` 目录现存六件无 db_backup ✓；path 形仅 `tests/test_config_key_registration_ledger.py:289` 历史账注释（工单已自flag，非可执行）；**新发现**：`tests/test_db_backup.py:46/:594` 含旧路径字符串＝DBT 注毒标记串（17:01 落盘，晚于 DOC 工单 55 分钟，属扫尺自身夹具非 live 指针） | **一致**（结论"零 live 指针"在当前盘面仍成立） |
| DBT | ✓17:03 | `28 passed in 3.58s`；ruff `All checks passed!` | **一致** |
| IMG | ✓17:00 | 两件合跑 `23 passed in 8.55s`；现算 shorekeeper=12 族／danya=0 族／文件非注释行 12，逐项吻合；`personas/` 未动（imagery_families.txt mtime 01:58） | **一致** |
| CHK | ✓16:58 | 4 红读数当时真实；主会话复录地板（1612/688）后本席实跑四 poison 腿 **`4 passed in 88.24s`** ⇒ 闭环；其余 10 把锁未复跑（成本超抽验档）。**mtime 反常**：`:289` 内容（事后账）与 mtime 12:12:20.9740988 差 ≥5h ⇒ 该面 mtime 失去"未被动过"旁证力 | **一致**（4红→主会话修复→4绿闭环；mtime 反常记档） |
| IVF | ✓但§②表截断（16:54，在飞） | 静态抽验：gate 测试 6 件清单 ✓、tts.py `_quota_bound`×4（B1 在飞面）✓、test_intimate 16P ✓；101 件全量读数未复跑 | **存疑（未完卷）** |
| FULL | ✓§③④⑤待填 | `/tmp/qoder-FULL/wt-axis-pytest.txt` 17:23 仍在写（~22%）＝工单"待填"诚实 | **未完卷（在飞，无虚报）** |
| BASE | ✓§③⑤待填 | §④ 已填两行本席核到落盘物：mypy-B2.txt（16:55）、head-axis-pytest-B2.txt 17:23 ~22% 在飞；b2 副本目录在盘 | **未完卷（在飞，无虚报）** |

## CHK 四腿补验（主会话复录地板 1612/688 之后）

- 实跑（basetemp 预建）：`pytest test_poison_11/_14/_15/_16` 四节点 ⇒ **`4 passed in 88.24s (0:01:28)`**。
- 判定升级：CHK 的 4 红读数当时真实；主会话复录地板已治愈四腿（本席实跑闭环）⇒ **一致**（mtime 反常仍记档：该文件 mtime 不再反映最新写入）。

## 总评

1. **已完卷十单（INT/MIG/L1/L2/D2F/BKT/DOC/DBT/IMG/CHK）账面↔盘面零虚报**：10 项 pytest 读数逐位复现或闭环（16/15/28/17/9/28/23/4 passed＋CHK 4红→修复→4绿），ruff 全绿＋`--help` rc=0；静态声称（sender 第四参、四步顺序、POISON=0、新家 import、12 族）逐一在盘坐实。
2. **两条环境级旁证警告**：① venv 陈旧字节码坑（见上，各席侥幸被 mkdir -p 掩盖，建议写进 dev.ps1 或交接账）；② `test_config_key_registration_ledger.py` 的 mtime 已失去"是否被动过"的旁证力（内容与 mtime 相差 ≥5 小时）。
3. **在飞三席（IVF/FULL/BASE）工单诚实待填，无虚报**；BASE 披露的"曾覆写前席副本"事故与占位地图已记录在案。
