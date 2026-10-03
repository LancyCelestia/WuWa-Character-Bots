# BKT 工单 — A/B 红集分桶器（2026-10-02 下午窗）

## 一、任务与范围

席 BKT（重派，前席被并发墙弹回零产出）。使命＝构建并自证 A/B 红集分桶器：读两份 pytest `-q --tb=no -rf` 输出（A＝HEAD 轴、B＝工作树轴），提取 FAILED node ID，按函数级/参数级两档归一后分三桶 `NEW_ONLY`（净新增红）/`GONE_ONLY`（转绿）/`COMMON`（既存红）；`--json` 出口；NEW_ONLY 空 ⇒ rc 0、非空 ⇒ rc 1（终门机读口）。约束：只新建两件交付物＋本工单，零 git 写、零进程动作、零配置改、未派子代理。写前自检：三个目标文件名均确认不存在。

## 二、交付物与设计

- `scripts/ab_red_bucket.py`（新建，纯标准库）：`extract_failed_nodeids`（优先锁 `short test summary info` 分节、缺横幅退回全文；ANSI 剥码；CRLF 兼容；重复行去重）→ `function_level`（剥结尾 `[...]` 串）→ `bucket`（匹配在函数级归一、点名在参数级原貌；common params＝两侧并集）→ `render_report`/`_payload`/`main`。头部 docstring 含 A/B 两轴生成命令全文（卫生前缀 `PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0` + `-p no:cacheprovider --basetemp=仓外`；A 轴按台账 #68 走 `git archive HEAD` 仓外同尺复跑）。
- **折行归并**：真机实证（pytest 9.1.1，本仓 venv）重定向下短摘要行不折行、超宽省略消息（`_format_trimmed`）；真折行发生在 CI 环境变量在场或 `-vv`（多行 reprcrash message 整段接行后）。归并逻辑覆盖三形态：折点在 `FAILED` 关键字后（空格接）、在 ` - ` 分隔符前（空格接）、在 node ID token 中段（直接拼）；node ID 只取合并后第 2 个空白分隔 token（node ID 不含空白），消息侧粘连不影响判定。病态边界（折点把 node ID 尾切在「数字开头+空格」处）不保证，已写入 docstring。
- `tests/test_ab_red_bucket.py`（新建）：9 发锁——①三桶划分 ②折行归并（三形态＋桶级归一）③NEW_ONLY 非空 ⇒ rc 1／空 ⇒ rc 0 ④参数尾两档归一（正向＋反向）⑤`--json` 出口与裸计数行边界 ⑥CRLF/重复行 ⑦function_level 纯函数面参数化。

## 三、自证（实跑，均 2026-10-02 本机）

1. `PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ChatBot_Runtime/venv/Scripts/python.exe -m pytest -p no:cacheprovider --basetemp="$TEMP/qoder-BKT/bt" -q tests/test_ab_red_bucket.py` → **末行 `9 passed in 2.92s`**。
2. 手工 4 行两份小样端到端：`NEW_ONLY n=1`（test_new_red）/`GONE_ONLY n=1`（test_was_red）/`COMMON n=2`（`test_vlm_gate[media_archive.vlm]` 归一到函数级点名）→ `rc=1`；同文件自比 → `rc_identical=0`；`--json` 落盘可解析。`--help` 可用。
3. `python -m ruff check --no-cache scripts/ab_red_bucket.py tests/test_ab_red_bucket.py` → **`All checks passed!`**（曾中 RUF100 一枚：E402 不在钉版集，noqa 反脏——已摘）。
4. `git status --porcelain` 确认仅两件 untracked 新文件，零他碰。未提交（无 git 写权限）⇒ 按规则 5 以可复跑命令＋实跑输出作证。

## 四、边界与风险

- 解析面按本仓 pytest 9.1.1 实证行为＋简报点名的折行场景设计；`ERROR` 行按终止符处理但不入红集（canonical 命令 `-rf` 不列 error）。
- 折点切在「node ID 尾段以数字开头＋空格」的病态输入不保证归并（已声明）。
- 两轴输入必须同 venv 同尺异 rootdir，否则桶全漂——docstring 已写明 A 轴生成命令。
- rc 1 仅由 NEW_ONLY 驱动；GONE_ONLY/COMMON 只供人读与 JSON 消费。

## 五、接手指引

终门用法：`python scripts/ab_red_bucket.py a_head.txt b_worktree.txt`（机读 rc）；需要留档加 `--json out.json`。本工单与两件新文件均未入库（零 git 写），由主会话决定提交时机；AGENTS.md/HANDBOOK 增量按规程由收尾方统一落（本席受简报范围约束未触碰）。

## 六、收尾采认（席 BKT-F，2026-10-02）

- **采认**：在盘两件确认为席 BKT 遗产（均 untracked、零他碰），本席写面＝本工单＋tests 件一处注释；scripts 件零改动。
- **简报与盘面不符（诚实底线，如实记不补写历史）**：简报称「tests 件 ：19 尚有 `# noqa: E402` 死注释、工单未落盘」；盘面现算两相反——noqa 已被 BKT 摘除（§三.3 自记 RUF100 一枚已摘），本工单亦已在盘。判读＝简报取证滞后于 BKT 落盘终态。
- **规格符合性复核（引 BKT-3 只读取证清单，与本工单 §二/§三 逐项相符）**：三桶划分／`--json` 出口／rc 两态判据／抗折行三变体归并／参数化两档归一／`--help` 全过。
- **一行修落笔**：：19 中置 import 上方补普通注释「中置 import 有意：被测件在 scripts/ 包内，先把仓库根插进 sys.path 再导入。」——意图在码，盘面已无任何 noqa 可被 RUF100 判死注释。
- **判据读数末行原样（本席实跑，卫生前缀同 §三）**：pytest（`-q -p no:cacheprovider --basetemp=<仓外>/qoder-BKTF/bt`）末行 **`9 passed in 3.83s`**；ruff（`--no-cache`，两件）末行 **`All checks passed!`**（rc=0）。
- **净新增红 0**：scripts 件零改动、tests 件 9/9 全绿、ruff 两件 0 命中、两件 untracked 不触他席在飞面 ⇒ 本波域内净新增红 0（全树读数归主会话盘面口径）。
- **归属账（三代同件）**：BKT＝落盘两件＋自证＋本工单（含 RUF100 摘除）；BKT-3＝只读取证＋请示收尾；BKT-F＝采认＋注释落笔＋复跑全绿＋本节记账。入库提交由用户执行。

## §七 傍窗主会话修（SPC 实测 bug 回收，2026-10-02 20:5x）

SPC 席实测三失效形态后判定真 bug：`_flush` 取「第 2 个空白 token」把含空格参数尾巴（HEAD 红集实测 `[J9 gallery_empty 乱贴]`）腰斩在首个空格。修＝node ID 解析改「`FAILED ` 之后、首个 ` - ` 之前的整段」（pytest 短摘要格式；消息缺席取整段），`scripts/ab_red_bucket.py` 头注与 `_flush` 注释同批记案。回归腿 `test_space_inside_param_tail_is_not_truncated`（带消息/裸形态/折行复合/桶级不吞四向）入 `tests/test_ab_red_bucket.py`。主会话实跑：`pytest tests/test_ab_red_bucket.py -q` → 10 passed；ruff 两件 All checks passed。终门分桶以修后版执行。
