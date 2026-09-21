# metadata-gate-window-sampling — kb-sync 元数据闸「有界窗口计数」改造

状态：完成（未 commit；生效需重启 bot）

席次：S2-METADATA-GATE（2026-09-20/21 夜间波次）
可改面：`plugins/bot_unified_runtime/domains/location/knowledge/kb_wiki.py`、
`tests/test_kb_metadata_probe_window.py`（续）、`tests/test_kb_metadata_probe_bounds.py`（新）
实际改动：**只有上面这三个文件**（外加本份报告与 `%TEMP%` 一次性取证脚本）。

---

## 0. 交接遗产

`tests/test_kb_metadata_probe_window.py`（9 例，上一阵亡席留下的 RED 件，生产码一字未动）
先行读全，然后按它的断言实现，**没有改动它任何期望值**，也没发现它与本单描述冲突：

- 它要求 `probe_corpus_time_fields(kb_dir)` 返回**恰好** `{probed, with_time, has_fields}`
  三键（多处用 `probe == {...}` 全等等值），且 `corpus_has_time_fields` 保留为同源 bool 包装；
- 它要求 `metadata_probed` / `metadata_with_time` 同时进同步结果与 `read_kb_sync_summary` 落库摘要；
- 它钉的阈值口径是「≥1 行命中 且 ≥窗口 10%」，`_METADATA_PROBE_WINDOW_LINES` 从模块常量取；
- 它钉 `metadata_refreshed == 2 × (窗口-1)`：与 `vector_knowledge.sync_document_metadata`
  （:1257-1314）**逐列计数**的既有语义一致，实跑证实，无需改期望。

## 1. 现状代码读解（修前）

| 位置（工作树） | 事实 |
|---|---|
| `domains/location/knowledge/kb_wiki.py:418-439` | `corpus_has_time_fields` 只取**第一条非空行**判 `"crawled_at" in row`；首行是坏 JSON 时 `except ValueError: return False` |
| 同文件 `:419-423`（HEAD 版 406-410） | docstring 论证「首行一条、不做全表扫描」的成本理由——本次一并改掉，不留自相矛盾注释 |
| 同文件 `:938`（HEAD 版 925） | 唯一生产调用点：`_refresh_kb_metadata_if_needed` 里决定刷不刷 |
| `domains/chat_reply/character/vector_knowledge.py:1243-1314` | 缺口计数（`crawl_at IS NULL`）与零嵌入回填（只 UPDATE 两列，`refreshed` 按列计），**本席零接触** |

注：真实模块在 `domains/location/knowledge/`（v21r2 域重组），`domains/location/kb_wiki.py` 不存在；
`plugins/bot_unified_runtime/character/kb_wiki.py` 是 PEP 562 活垫片，新符号自动透出，无需登记。

## 2. 设计（判据形态：一行样本 → 有界窗口计数）

1. **探针 `probe_corpus_time_fields(kb_dir, *, topics=(), window=300)`**（`:440-491`）：
   流式逐行读，`probed` 只计「合法 JSON 对象行」，`with_time` 计其中带 `crawled_at` 的行数；
   空行/坏 JSON/非对象行**既不进分子也不进分母**（旧实现里首行坏 JSON 直接把全库判死）。
2. **阈值**：`with_time >= 1 and with_time * 100 >= probed * 10`（整数比对，不留浮点边界毛刺）。
   下限 1 保证微型语料（1-9 行全带字段）行为与旧版向后一致。
3. **有界性三把锁**：窗口判定放**循环体末尾**（放开头会为下一行先付一次读）；
   `islice(handle, 6000)` 钉死原始行扫描上限（被 topics 滤掉的行也必须计数，否则窄域配置下
   会一路 continue 到文件尾，退化成每夜全表扫——这条是我自己引入 topics 参数后必须补的）；
   文件缺失/中途解码失败 → 已拿到的样本如实交出（缺文件即 `{0,0,False}`，绝不硬刷）。
4. **采样总体 = 被闸管的总体**：闸调用时传 `topics=parse_topics(config)`，与
   `refresh_kb_metadata` 的过滤口径同源。否则会出现「闸拿 A 域的字段分布给 B 域放行，
   回填却只刷 B 域」——同一族「不具代表性样本替全体背书」缺陷换了个方向重演。
5. **判据依据外流**：`metadata_probed` / `metadata_with_time` 进 `_empty_kb_result`（`:791-792`）、
   `_sync_summary` 落库面（`:940-941`）、以及人读的 `public_message`（`:1191-1202`，
   ok 与 skipped 两路都带「探针 N 行、M 行带字段 + 台账缺口」）。
6. **刷新语义一字未动**：只换「要不要刷」这道闸（`:986-1010`），hash 比对、零嵌入、
   stale/missing 归类全在既有路径上。

## 3. 实施（改动行号，均为工作树现状）

- `kb_wiki.py:15-19` 模块 docstring：元数据条目补「要不要刷由有界窗口计数判定」，旧理由作废
- `kb_wiki.py:46` `from itertools import chain, islice`
- `kb_wiki.py:421-437` 探针注释块 + 三常量（`_METADATA_PROBE_WINDOW_LINES=300` /
  `_METADATA_PROBE_MIN_RATIO_PCT=10` / `_METADATA_PROBE_MAX_SCAN_LINES=6000`）
- `kb_wiki.py:440-491` 新 `probe_corpus_time_fields`
- `kb_wiki.py:494-500` `corpus_has_time_fields` 改为同源 bool 包装（签名保留，旧论证删除）
- `kb_wiki.py:791-792` `_empty_kb_result` 两新键缺省 0
- `kb_wiki.py:940-941` `_sync_summary` 两新键
- `kb_wiki.py:1003-1010` 闸改用探针 + 记 probed/with_time（注释同改）
- `kb_wiki.py:1191-1202` `public_message` 观测行带判据依据
- `tests/test_kb_metadata_probe_window.py` 原样保留（9 例全绿）
- `tests/test_kb_metadata_probe_bounds.py` 新 13 例（实收 13，含 5 组参数化阈值锁：域scoped 取样、扫描上限、读预算硬锁、
  脏尾不越窗、阈值参数化 5 组 + 反例、非对象行、依据外流到 public_message/摘要）

## 4. 实跑证据（全部离线 tmp_path，未碰 ChatBot_Runtime / 未触发嵌入 / 未跑 knowledge-sync）

### 4.1 RED → GREEN 行为对照（旧判据逐字取自 `git show HEAD:` 而非手写）

取证脚本：`ChatBot/ChatBot/%TEMP%/mg-red-green-probe.py`（gitignored scratch，可删）。
同一场景「首行无 `crawled_at`、第 2..300 行全带」，RED 路把闸的谓词换成 HEAD 的
`corpus_has_time_fields`（AST 从 `git show HEAD:…/kb_wiki.py` 提取后 exec），GREEN 路用工作树探针：

```
$ PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8 ../ChatBot_Runtime/venv/Scripts/python.exe -B "%TEMP%/mg-red-green-probe.py"
--- 从 git HEAD 提取的旧判据（def 行与文档串首行） ---
def corpus_has_time_fields(kb_dir: Path) -> bool:
    """documents.jsonl 首行是否带 ``crawled_at``（语料侧是否已增强）。
--- RED：旧判据（首行一票否决） ---
[red-legacy] 首轮 status=skipped_corpus_without_time_fields gaps=300 || 增强轮 status=skipped_corpus_without_time_fields refreshed=0 probed=1 with_time=0 台账仍缺=300/300
--- GREEN：工作树新判据（有界窗口计数） ---
[green-window] 首轮 status=skipped_corpus_without_time_fields gaps=300 || 增强轮 status=ok refreshed=598 probed=300 with_time=299 台账仍缺=1/300
```

即：修前整库被一行样本否决（300 篇全 NULL、refreshed=0），修后正常回填 598 处（299 篇 × 两列），
确实没数据的那 1 篇仍留 NULL（`台账仍缺=1/300`，不硬刷）。

### 4.2 回归族全绿

```
$ PYTHONDONTWRITEBYTECODE=1 ../ChatBot_Runtime/venv/Scripts/python.exe -B -m pytest tests/test_kb_metadata_probe_window.py tests/test_kb_metadata_probe_bounds.py tests/test_kb_wiki_metadata_sync.py tests/test_kb_topic_name_contract.py tests/test_kb_wiki_sync.py tests/test_kb_wiki_retriever_wiring.py tests/test_v21r2_stall_kbsync.py tests/test_sdd9_n3re.py tests/test_no_source_tree_data_writes.py -q --basetemp="$TEMP/mgA" -p no:cacheprovider
........................................................................ [ 74%]
.........................                                                [100%]
97 passed in 7.11s
```

`tests/test_kb_topic_name_contract.py`（F3 席交付件，本席只读）与 `test_kb_wiki_metadata_sync.py`
（含 `test_run_kb_sync_task_auto_backfills_once` 的 skipped→ok→not_needed 三段既有语义）全绿
→ topics / reconcile / 回填语义零回归，未过界。

### 4.3 静态门

```
$ ruff check --cache-dir ../ChatBot_Runtime/cache/ruff plugins/.../kb_wiki.py tests/test_kb_metadata_probe_window.py tests/test_kb_metadata_probe_bounds.py
All checks passed!
$ python -B -m mypy --cache-dir ../ChatBot_Runtime/cache/mypy --explicit-package-bases --ignore-missing-imports plugins/.../kb_wiki.py
Success: no issues found in 1 source file
```

### 4.4 变异检查（每处变异只被预期用例杀掉）

| 变异 | 结果 |
|---|---|
| A 去掉 10% 比例门槛（`has_fields = with_time >= 1`） | 2 failed：`test_stray_enriched_line_among_plain_is_noise`、`test_probe_threshold_rejects_sub_ratio_hits` |
| B 去掉 `islice` 扫描上限 | 1 failed：`test_probe_stops_at_scan_cap_instead_of_full_scan` |
| C 窗口判定挪到循环体开头 | 1 failed：`test_probe_requests_only_its_window_of_lines`（读 301 行 ≠ 300） |

变异后均已还原（`grep MUT` 只剩 `_SYNC_TASK_MUTEX`），并复跑 97 例全绿。

### 4.5 树卫生

```
$ git status --porcelain | grep -E "kb_metadata|location/knowledge/kb_wiki|.sdd-reports"
 M plugins/bot_unified_runtime/domains/location/knowledge/kb_wiki.py
?? .sdd-reports/
?? tests/test_kb_metadata_probe_bounds.py
?? tests/test_kb_metadata_probe_window.py
$ ls -d __pycache__ .pytest_cache .ruff_cache .mypy_cache data   →  全部 No such file
$ find . -name "__pycache__" -newermt "-40 minutes"              →  空
```

`plugins/bot_unified_runtime/character/kb_wiki.py`（旧路径垫片）显示的 ` M` 是别的席位的改动，非本席。

## 5. 主会话这次转述里哪句不准

1. **路径不准**：「`domains/location/kb_wiki.py:418-439`」——真身是 `domains/location/knowledge/kb_wiki.py`
   （v21r2 域重组），`domains/location/` 下没有 kb_wiki.py。行号 418-439、`:421-423` 成本论证段、
   `:419-423` docstring 三处**都对得上**，只有目录层级错。
2. **旧判据比「只看首行」还脆一档**：转述说「只看首行有没有 crawled_at」。实际首行若是**坏 JSON**，
   旧实现是 `except ValueError: return False`——一行脏数据同样一票否决，这条触发概率比「行序一变」高。
   新探针把坏行排除在分子分母之外（另有专项用例）。
3. **N 取几百：成立，且可量化**——窗口 300 行 ≈ 全库 75,737 行的 0.4%，按 237MB 折算窗口读约 1MB 级；
   「成本权衡仍成立」这句准。我据此把 `has_fields` 的分母定为**实际计入的样本数**（probed），
   不是固定窗口，否则 10 行的微型语料会被自己的窗口判死（向后不兼容，转述没提这点）。
4. **「向后保守」需补一句**：窗口内 0 命中 ≠ 语料真没字段（字段可能排在第 N+1 行之后）。
   这是有意的保守不对称——宁可少刷一晚，不硬刷 75,737 个 NULL；现在 skipped 状态带
   probed/with_time，连续多轮 `probed=300 with_time=0` 才构成「真没字段」的证据。转述里
   「前 N 行确实全不带字段时仍诚实判 skipped」按字面实现，但「诚实」的边界是**窗口内诚实**。
5. **「今晚读数就会变好」不成立**：闸修好了，但（a）本席禁跑 knowledge-sync、禁写 Runtime，
   （b）铁律「改代码必须重启 bot 才生效」——所以生产 `metadata_status` 什么时候从 skipped 变 ok，
   取决于提权重启的时点，不是这次改动落地当晚。缺口方向仍是「留 NULL」不是「丢数据」，与昨晚
   那次跳过的正确性判断一致。
6. **可观测面有一处本席无权动**：`control_plane/webui_knowledge.py:66-90` 的
   `_KB_SYNC_PUBLIC_FIELDS` 是**白名单过滤器**（消费点 :496 `{key: payload[key] for key in ... if key in payload}`），
   我新加的两键落库了但不会出现在 WebUI 知识页。请主会话在 `"metadata_status",`（:86）之后插两行：
   ```python
       "metadata_probed",
       "metadata_with_time",
   ```
   纯追加，`if key in payload` 兜住缺键（改动前后都不会红任何测试），本席按禁改表只报不动。
7. **未加任何配置键**：窗口/比例/扫描上限是模块常量（`config.py` 在禁改表）。若要把 N 外显成
   `BOT_KB_WIKI_METADATA_PROBE_LINES`，需要主会话裁：改动 = config 一字段 + catalog + .env.example +
   `probe_corpus_time_fields` 的 `window=` 传参处一行，本席未做。

## 6. 遗留与移交

- 全量 `dev.ps1 -Task test` 未跑（本席只跑 kb 家族 97 例 + 两静态门 scoped），终态计数归收尾合流。
- 真机验收：重启后跑一轮 kb-sync，看 `metadata_status=ok`、`metadata_refreshed≈2×篇数`，
  或读 `knowledge_meta['kb_sync_last_summary']` 的 `metadata_probed/metadata_with_time`。
- 外部 `kb_coverage_cli.py`（Crawl Wiki 仓，禁改）若要把 probed/with_time 打进读数行，是爬虫侧一步改动。
- 未 commit（禁 git 写操作）；一次性取证脚本在 `ChatBot/ChatBot/%TEMP%/mg-red-green-probe.py`，可随时删。
